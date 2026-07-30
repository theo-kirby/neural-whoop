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

const uint8_t kDroneMac[6] = ESPNOW_DRONE_MAC;

// --- lock-free SPSC ring: producer = WiFi task (recv callback), consumer = loop() -----------
// Aligned 32-bit loads/stores are atomic on the ESP32-S3, so a single producer index and a
// single consumer index need no mutex. Whole packets only: a partial write would splice two
// MSP frames together and desync the host parser, so a packet that does not fit is dropped.
uint8_t ring[kRingSize];
volatile uint32_t ring_head = 0;  // written by the callback
volatile uint32_t ring_tail = 0;  // written by loop()

// Counters (read in the debug heartbeat; approximate by design, never gate behaviour).
volatile uint32_t n_ring_drop = 0;
uint32_t n_tx = 0, n_rx = 0, n_oversize = 0, n_send_fail = 0, n_bad_frame = 0;

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

void onCompleteFrame(const uint8_t* f, size_t len) {
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
  if (len > 0) ringPush(data, static_cast<size_t>(len));
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
  while (ringUsed() > 0) {
    const uint32_t t = ring_tail;
    const uint32_t used = ringUsed();
    // One contiguous span at a time (the ring wraps).
    const uint32_t span = min(used, static_cast<uint32_t>(kRingSize - (t & kRingMask)));
    Serial.write(&ring[t & kRingMask], span);
    ring_tail = t + span;
    n_rx += span;
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
    DBG("status: tx %lu  rx %lu B  oversize %lu  send_fail %lu  ring_drop %lu  bad_hdr %lu\n",
        (unsigned long)n_tx, (unsigned long)n_rx, (unsigned long)n_oversize,
        (unsigned long)n_send_fail, (unsigned long)n_ring_drop, (unsigned long)n_bad_frame);
  }
#endif
}
