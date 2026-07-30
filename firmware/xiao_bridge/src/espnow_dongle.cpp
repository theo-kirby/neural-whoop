// ESP-NOW desk dongle: a transparent USB-CDC <-> ESP-NOW proxy for raw MSP frames.
//
//   Mac ──USB CDC──► XIAO#2 (this) ──ESP-NOW──► XIAO(drone) ──UART──► FC
//
// This is the host half of the ESP-NOW link (docs/ESPNOW.md). It replaces the WiFi/UDP path,
// whose measured tail — p99 124 ms on the pure host<->bridge hop, motors off — is the project's
// top blocker. ESP-NOW drops association, DHCP, beacons/DTIM, mesh roaming and the host's
// background WiFi scans; the packet goes peer-to-peer on a fixed channel.
//
// The dongle is deliberately dumb and stateless, like the bridge it talks to: it re-frames
// bytes into whole MSP packets and forwards them. It never answers an MSP id itself and never
// fabricates a frame — MSP_BRIDGE_TOF is still answered on the DRONE side, so the bench's
// air-vs-FC latency split keeps working unchanged.
//
// Two footguns, both handled here:
//
//   1. `Serial` (USB CDC) IS the data path. Any stray Serial.print corrupts the MSP stream, so
//      every debug print is behind -DDONGLE_DEBUG and goes out a SEPARATE UART. Default off.
//   2. The ESP-NOW receive callback runs in WiFi-task context. It must not block and must not
//      touch USB CDC, so it only memcpy's into a lock-free SPSC ring that loop() drains.
//
// Size: ESP_NOW_MAX_DATA_LEN is 250 B. MSP v1's theoretical max frame is 261 B, but our command
// set peaks around 86 B (mode ranges). Oversize frames are DROPPED AND COUNTED, never silently
// truncated — a truncated MSP frame would fail checksum host-side and look like link noise.
// Fragmentation is a deliberate follow-up, not a v1 feature.
//
// Build:
//   pio run -e espnow_dongle -t upload            # the real thing
//   pio run -e espnow_loopback -t upload          # echoes frames back on USB (no radio) —
//                                                 # proves CDC framing before ESP-NOW is involved

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "espnow_config.h"

namespace {

constexpr size_t kMaxFrame = 261;   // MSP v1 worst case: 6 header/trailer + 255 payload
constexpr size_t kRingSize = 4096;  // power of two; SPSC mask arithmetic below depends on it
constexpr size_t kRingMask = kRingSize - 1;

// Dongle-local MSP command (like the bridge's kMspBridgeTof): the dongle answers it ITSELF with
// its own counters and never puts it on the air. Added 2026-07-30 during bring-up, when the drone
// reported 378 replies sent + 0 send failures while the host saw only 300 — proving frames were
// reaching this board and dying between the recv callback and USB. There is no other way to read
// these: `Serial` is the data path, so -DDONGLE_DEBUG needs a second UART on wires the bench
// doesn't have. In-band beats a jumper.
constexpr uint8_t kMspDongleStats = 193;

const uint8_t kDroneMac[6] = ESPNOW_DRONE_MAC;

// --- lock-free SPSC ring: producer = WiFi task (recv callback), consumer = loop() -----------
// Aligned 32-bit loads/stores are atomic on the ESP32-S3, so a single producer index and a
// single consumer index need no mutex. Whole packets only: a partial write would splice two
// MSP frames together and desync the host parser, so a packet that does not fit is dropped.
uint8_t ring[kRingSize];
volatile uint32_t ring_head = 0;  // written by the callback
volatile uint32_t ring_tail = 0;  // written by loop()

// Counters (read via kMspDongleStats / the debug heartbeat; never gate behaviour).
volatile uint32_t n_ring_drop = 0;
volatile uint32_t n_rx_pkts = 0;  // ESP-NOW packets the callback actually saw
uint32_t n_tx = 0, n_rx = 0, n_oversize = 0, n_send_fail = 0, n_bad_frame = 0;
uint32_t n_usb_short = 0;         // times the CDC layer accepted less than we offered
uint32_t loop_max_us = 0;         // worst loop() this window — the dongle's own account

inline uint32_t ringUsed() { return ring_head - ring_tail; }

// Push one whole ESP-NOW payload. Returns false (and counts) if it will not fit.
bool ringPush(const uint8_t* data, size_t len) {
  if (len == 0) return true;
  if (kRingSize - ringUsed() <= len) {  // strictly less than free space: keep head != tail sane
    n_ring_drop++;
    return false;
  }
  uint32_t h = ring_head;
  for (size_t i = 0; i < len; i++) ring[(h + i) & kRingMask] = data[i];
  ring_head = h + len;
  return true;
}

// --- debug UART (default OFF; USB CDC is the data path) -------------------------------------
#ifdef DONGLE_DEBUG
#ifndef DONGLE_DEBUG_TX_PIN
#define DONGLE_DEBUG_TX_PIN 1  // XIAO D0
#endif
#ifndef DONGLE_DEBUG_RX_PIN
#define DONGLE_DEBUG_RX_PIN 2  // XIAO D1
#endif
HardwareSerial dbg(1);
#define DBG_BEGIN() dbg.begin(115200, SERIAL_8N1, DONGLE_DEBUG_RX_PIN, DONGLE_DEBUG_TX_PIN)
#define DBG(...) dbg.printf(__VA_ARGS__)
#else
#define DBG_BEGIN() ((void)0)
#define DBG(...) ((void)0)
#endif

// --- incremental MSP v1 framer over the USB CDC byte stream ---------------------------------
// Mirrors neural_whoop/bench/msp.py::MspParser: sync on '$M', accept '<' '>' '!' as direction,
// then size/cmd/payload/checksum. We forward the frame VERBATIM (checksum included) — the
// dongle validates only enough to find boundaries, it is not an MSP endpoint.
uint8_t frame[kMaxFrame];
size_t frame_len = 0;

void onCompleteFrame(const uint8_t* f, size_t len);

void feedHostByte(uint8_t b) {
  if (frame_len == 0) {
    if (b != '$') return;  // resync: drop noise until a header starts
    frame[frame_len++] = b;
    return;
  }
  if (frame_len == 1) {
    // '$' then something else: could be the start of a fresh header ("$$M<"), so keep the '$'.
    if (b != 'M') { frame_len = (b == '$') ? 1 : 0; return; }
    frame[frame_len++] = b;
    return;
  }
  if (frame_len == 2) {
    if (b != '<' && b != '>' && b != '!') { frame_len = 0; n_bad_frame++; return; }
    frame[frame_len++] = b;
    return;
  }
  frame[frame_len++] = b;
  // Header(3) + size + cmd + payload(size) + checksum
  if (frame_len >= 5) {
    const size_t need = 5 + static_cast<size_t>(frame[3]) + 1;
    if (frame_len >= need) {
      onCompleteFrame(frame, need);
      frame_len = 0;
    }
  }
}

// Answer kMspDongleStats locally ('$M>' framing, so the host's stock parser reads it like any
// other reply). Consumed here, never forwarded — same contract as the bridge's ToF id.
void sendStatsReply() {
  const uint16_t lmax = min<uint32_t>(loop_max_us / 1000, 0xFFFF);
  uint8_t p[24];
  auto put32 = [&](size_t off, uint32_t v) {
    p[off] = v & 0xFF; p[off + 1] = (v >> 8) & 0xFF; p[off + 2] = (v >> 16) & 0xFF; p[off + 3] = v >> 24;
  };
  auto put16 = [&](size_t off, uint16_t v) { p[off] = v & 0xFF; p[off + 1] = v >> 8; };
  put32(0, n_tx);            // frames put on the air (host -> drone)
  put32(4, n_rx_pkts);       // ESP-NOW packets the recv callback saw (drone -> host)
  put32(8, n_rx);            // bytes actually written back out to USB
  put16(12, n_oversize);
  put16(14, n_send_fail);
  put16(16, n_ring_drop);
  put16(18, n_bad_frame);
  put16(20, lmax);
  put16(22, min<uint32_t>(n_usb_short, 0xFFFF));
  uint8_t frame[3 + 2 + sizeof(p) + 1] = {'$', 'M', '>', sizeof(p), kMspDongleStats};
  uint8_t ck = sizeof(p) ^ kMspDongleStats;
  for (size_t i = 0; i < sizeof(p); i++) { frame[5 + i] = p[i]; ck ^= p[i]; }
  frame[5 + sizeof(p)] = ck;
  Serial.write(frame, sizeof(frame));
}

void onCompleteFrame(const uint8_t* f, size_t len) {
#ifndef DONGLE_LOOPBACK
  // Intercept before the radio: this id is ours, the drone has never heard of it.
  if (len >= 6 && f[2] == '<' && f[4] == kMspDongleStats) {
    sendStatsReply();
    return;
  }
#endif
#ifdef DONGLE_LOOPBACK
  // Bring-up step 2: prove USB CDC framing (host -> dongle -> host) with no radio in the path.
  Serial.write(f, len);
  n_tx++;
#else
  if (len > ESP_NOW_MAX_DATA_LEN) {
    // Dropped, never truncated. If this ever counts above zero, MSP fragmentation is the fix.
    n_oversize++;
    DBG("DROP oversize frame: cmd %u, %u B > %u\n", f[4], (unsigned)len, ESP_NOW_MAX_DATA_LEN);
    return;
  }
  const esp_err_t err = esp_now_send(kDroneMac, f, len);
  if (err != ESP_OK) {
    n_send_fail++;  // queue full / peer gone: fire-and-forget, MSP's own retry covers it
    DBG("send failed: %d (cmd %u)\n", (int)err, f[4]);
  } else {
    n_tx++;
  }
#endif
}

// --- ESP-NOW callbacks ----------------------------------------------------------------------
void onSent(const uint8_t*, esp_now_send_status_t status) {
  // Link-layer ACK result. Logged, never blocked on: stale data is worse than missing data, and
  // Betaflight's 300 ms MSP-RC failsafe is the real safety net.
  if (status != ESP_NOW_SEND_SUCCESS) n_send_fail++;
}

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onRecv(const esp_now_recv_info_t*, const uint8_t* data, int len) {
#else
void onRecv(const uint8_t*, const uint8_t* data, int len) {
#endif
  // WiFi-task context: memcpy only. No Serial, no blocking, no printf.
  if (len > 0) {
    n_rx_pkts++;
    ringPush(data, static_cast<size_t>(len));
  }
}

void initEspNow() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();          // never associate: ESP-NOW is peer-to-peer
  WiFi.setSleep(false);       // power save is exactly the latency we came here to delete
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    DBG("esp_now_init failed\n");
    // Nothing useful left to do; blink fast so the failure is visible without a debug UART.
    while (true) {
      digitalWrite(LED_BUILTIN, (millis() >> 6) & 1);
      delay(10);
    }
  }
#ifdef ESPNOW_PMK
  esp_now_set_pmk(reinterpret_cast<const uint8_t*>(ESPNOW_PMK));
#endif
  esp_now_register_send_cb(onSent);
  esp_now_register_recv_cb(onRecv);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, kDroneMac, 6);
  peer.channel = ESPNOW_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) DBG("esp_now_add_peer failed\n");
}

}  // namespace

void setup() {
  Serial.begin(115200);  // USB CDC — THE DATA PATH. Nothing else may print here.
  pinMode(LED_BUILTIN, OUTPUT);
  DBG_BEGIN();
  DBG("espnow_dongle up\n");
#ifndef DONGLE_LOOPBACK
  initEspNow();
  DBG("peer %02X:%02X:%02X:%02X:%02X:%02X ch %d\n", kDroneMac[0], kDroneMac[1], kDroneMac[2],
      kDroneMac[3], kDroneMac[4], kDroneMac[5], ESPNOW_CHANNEL);
#endif
}

void loop() {
  const uint32_t t_loop_us = micros();

  // Host -> air: drain USB CDC through the framer. Bounded per pass so a flood of host writes
  // can never starve the air -> host direction below.
  uint8_t buf[256];
  for (int pass = 0; pass < 4; pass++) {
    const int avail = Serial.available();
    if (avail <= 0) break;
    const size_t take = min(static_cast<size_t>(avail), sizeof(buf));
    const size_t got = Serial.readBytes(buf, take);
    for (size_t i = 0; i < got; i++) feedHostByte(buf[i]);
    if (got < sizeof(buf)) break;
  }

  // Air -> host: drain the ring the recv callback fills. Chunk boundaries do not matter; the
  // host's MSP parser is incremental.
  //
  // Serial.write() RETURNS A SHORT COUNT under USB CDC back-pressure, and honouring it is not
  // optional: the first cut advanced ring_tail by the requested span regardless, which threw away
  // every byte the CDC layer had not accepted AND counted them as sent. Measured 2026-07-30 —
  // dongle reported 400/400 replies written while the host received 310 (22.5% loss), with the
  // radio and both ring buffers provably clean. Loopback hid it completely, because that build
  // never brings WiFi up and so never contends for the CDC FIFO. Advance only by what was
  // actually accepted; the remainder stays in the ring for the next pass.
  while (ringUsed() > 0) {
    const uint32_t t = ring_tail;
    const uint32_t used = ringUsed();
    // One contiguous span at a time (the ring wraps).
    const uint32_t span = min(used, static_cast<uint32_t>(kRingSize - (t & kRingMask)));
    const size_t wrote = Serial.write(&ring[t & kRingMask], span);
    ring_tail = t + wrote;
    n_rx += wrote;
    if (wrote < span) {
      n_usb_short++;  // back-pressure: come back next loop() rather than dropping the tail
      break;
    }
    // Push it out NOW. Without this the CDC layer sits on a 14-byte MSP reply waiting for more
    // bytes to make a full USB packet, and the reply is delivered only when the NEXT few replies
    // pile in behind it. Measured 2026-07-30: every byte arrived (5600/5600, zero loss) but ~18%
    // of round trips missed a 250 ms deadline, because replies were landing in batches instead of
    // one at a time. A control link is exactly the latency-over-throughput case flushing is for.
    Serial.flush();
  }

  // Solid while frames are flowing, slow blink when idle. Active-LOW on the XIAO ESP32-S3.
  static uint32_t last_tx_ms = 0;
  static uint32_t seen_tx = 0;
  if (n_tx != seen_tx) { seen_tx = n_tx; last_tx_ms = millis(); }
  const bool fresh = last_tx_ms != 0 && (millis() - last_tx_ms) < 250;
  digitalWrite(LED_BUILTIN, fresh ? LOW : (((millis() >> 9) & 1) ? LOW : HIGH));

#ifdef DONGLE_DEBUG
  static uint32_t last_status_ms = 0;
  if (millis() - last_status_ms > 5000) {
    last_status_ms = millis();
    DBG("status: tx %lu  rx %lu B  oversize %lu  send_fail %lu  ring_drop %lu  bad_hdr %lu  usb_short %lu\n",
        (unsigned long)n_tx, (unsigned long)n_rx, (unsigned long)n_oversize,
        (unsigned long)n_send_fail, (unsigned long)n_ring_drop, (unsigned long)n_bad_frame,
        (unsigned long)n_usb_short);
  }
#endif

  const uint32_t dt_us = micros() - t_loop_us;
  if (dt_us > loop_max_us) loop_max_us = dt_us;
}
