// XIAO ESP32-S3 MSP bridge: transparent link <-> UART proxy between the host and the flight
// controller (sim2real branch B, docs/SIM2REAL.md).
//
// Design: the bridge carries raw MSP frames unmodified in both directions (the DroneBridge
// pattern), so the host talks the same protocol over the air that it talks over USB — the
// entire scripts/bench.py toolkit works through it. The bridge itself is dumb on purpose: no
// parsing beyond a header sanity check, no state. Safety comes from Betaflight's own MSP-RC
// freshness window (300 ms): when the link drops, the bridge simply has nothing to forward and
// the FC's msp_override failsafe policy takes over. The bridge never fabricates an FC frame.
//
// TWO TRANSPORTS, one loop (docs/ESPNOW.md):
//   * default        — WiFi station + UDP (port UDP_PORT), reachable at whoop-bridge.local.
//   * -DNW_LINK_ESPNOW — ESP-NOW straight to a desk-side XIAO dongle (src/espnow_dongle.cpp).
//     No association, no DHCP, no beacons/DTIM, no mesh roaming: the measured p99 of the pure
//     air hop was 124 ms on WiFi, which is what this exists to fix.
// Everything below the `link*()` seam — ToF interception, the loop_max / per-section timers,
// the LED, the FC UART path — is byte-for-byte the same code in both builds. WiFi stays the
// default so rollback is a reflash (`pio run -e xiao_bridge -t upload`).
//
// The one deliberate exception to transparency: the bridge owns a downward VL53L1X ToF
// rangefinder (CJMCU-531 breakout on I2C, D5/SDA + D6/SCL as wired on our unit) and answers
// MSP v1 cmd 192 (MSP_BRIDGE_TOF, our id — Betaflight never sees it) locally with the latest
// range. Requests for that id are consumed, never forwarded; every other '$' packet passes
// through untouched. With no sensor wired the bridge still boots and proxies; the reply just
// carries ok=0. That interception is also what makes `bench.py latency` able to split the air
// path from the FC path, so it matters just as much on ESP-NOW.
//
// LED: solid while command packets are flowing (<250 ms old), slow blink when idle/linkless.

#include <Arduino.h>
#include <VL53L1X.h>
#include <WiFi.h>
#include <Wire.h>

#include "wifi_config.h"  // FC UART pins/baud (+ the WiFi credentials in the UDP build)

#ifdef NW_LINK_ESPNOW
#include <esp_now.h>
#include <esp_wifi.h>

#include "espnow_config.h"
#else
#include <ESPmDNS.h>
#include <WiFiUdp.h>
#endif

#ifndef MDNS_NAME
#define MDNS_NAME "whoop-bridge"
#endif

namespace {

constexpr uint32_t kLinkFreshMs = 250;
constexpr size_t kBufSize = 512;

// Bridge-local MSP command: latest ToF range. Payload: u16 range_mm, u8 range_status
// (VL53L1X, 0 = valid), u16 age_ms (65535 = never), u8 sensor_ok, u16 loop_max_ms. Mirrored in
// neural_whoop/bench/msp.py (MSP_BRIDGE_TOF / decode_bridge_tof) — change both together.
// The trailing loop_max_ms was appended 2026-07-30; older hosts slice the first 6 bytes and
// ignore it, so the field is backwards-compatible in both directions.
constexpr uint8_t kMspBridgeTof = 192;
// dataReady() is a BLOCKING I2C read, so every poll is dead time for the proxy. The sensor
// free-runs at 25 ms; 12 ms still catches every sample with one spare poll, at half the bus
// traffic of the old 5 ms.
constexpr uint32_t kTofPollMs = 12;
// Cap on inbound packets serviced per loop() pass. The host fires 3-5 MSP queries per control
// tick as a burst; draining one per pass made the burst take 3-5 loop iterations (and any
// blocking call in between stretched the whole tick). Bounded so a flood can't starve the
// FC->host path.
constexpr int kMaxRxPerLoop = 8;

HardwareSerial fc(1);
VL53L1X tof;

uint32_t last_cmd_ms = 0;

bool tof_ok = false;        // sensor found + ranging
uint16_t tof_mm = 0xFFFF;   // latest range (mm)
uint8_t tof_status = 0xFF;  // latest VL53L1X range_status (0 = valid)
uint32_t tof_ms = 0;        // millis() of the latest sample (0 = never)
uint32_t tof_poll_ms = 0;

// Worst loop() duration in the current 5 s status window. This is the bridge's own account of
// how long it went without servicing the link — the quantity that shows up host-side as a
// frozen telemetry frame (obs_age_ms spikes). Reported on the USB heartbeat and in the ToF reply.
uint32_t loop_max_us = 0;

// Per-section worst case in the same window. loop_max alone said "something blocks ~100 ms under
// host traffic" but not WHAT: 2026-07-30 measurements exonerated both original suspects (the I2C
// poll runs every loop and idles at 4 ms; WiFi modem sleep is already off, see connectWifi). The
// stall appears ONLY when the host polls — i.e. somewhere in the link path — so time each section
// separately and let the bridge name the guilty call instead of guessing again.
// NOTE: sec_tof_reply is a SUBSET of sec_link_rx (the reply is sent inside the drain loop).
uint32_t sec_link_rx = 0, sec_tof_reply = 0, sec_uart_tx = 0, sec_poll_tof = 0, sec_status = 0;

inline void bump(uint32_t& slot, uint32_t t0_us) {
  const uint32_t dt = micros() - t0_us;
  if (dt > slot) slot = dt;
}

uint8_t rx_buf[kBufSize];  // link -> UART
uint8_t tx_buf[kBufSize];  // UART -> link

// ============================ transport seam ================================================
// Four calls, two implementations. linkBegin() brings the radio up; linkReceive() pops the next
// inbound packet (0 = nothing waiting, never blocks); linkReply()/linkPublish() send back to the
// host (reply = the source of the packet being handled, publish = the established command peer);
// linkMaintain() is the per-loop keepalive; linkStatus() fills the heartbeat's transport half.

#ifdef NW_LINK_ESPNOW

const uint8_t kDongleMac[6] = ESPNOW_DONGLE_MAC;

// Inbound packets land in a WiFi-task callback that must not block, so they are copied into a
// lock-free SPSC ring (length-prefixed, whole packets only) and popped in loop(). Aligned 32-bit
// loads/stores are atomic on the ESP32-S3, so a single producer index and a single consumer
// index need no mutex.
constexpr size_t kRingSize = 4096;  // power of two: the mask arithmetic depends on it
constexpr size_t kRingMask = kRingSize - 1;
uint8_t ring[kRingSize];
volatile uint32_t ring_head = 0;  // written by the recv callback
volatile uint32_t ring_tail = 0;  // written by loop()

volatile uint32_t n_ring_drop = 0;
uint32_t n_link_tx = 0, n_link_fail = 0;
bool peer_ready = false;  // set once a packet has arrived (mirrors the UDP build's peer_port)

bool ringPush(const uint8_t* d, size_t len) {
  const uint32_t need = len + 2;
  if (kRingSize - (ring_head - ring_tail) <= need) {
    n_ring_drop++;  // whole packet dropped: a partial write would splice two MSP frames
    return false;
  }
  const uint32_t h = ring_head;
  ring[h & kRingMask] = len & 0xFF;
  ring[(h + 1) & kRingMask] = (len >> 8) & 0xFF;
  for (size_t i = 0; i < len; i++) ring[(h + 2 + i) & kRingMask] = d[i];
  ring_head = h + need;
  return true;
}

void onSent(const uint8_t*, esp_now_send_status_t status) {
  // Link-layer ACK result. Counted, never blocked on: ESP-NOW already retries below us, stale
  // data is worse than missing data, and Betaflight's 300 ms MSP-RC failsafe is the safety net.
  if (status != ESP_NOW_SEND_SUCCESS) n_link_fail++;
}

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onRecv(const esp_now_recv_info_t*, const uint8_t* data, int len) {
#else
void onRecv(const uint8_t*, const uint8_t* data, int len) {
#endif
  if (len > 0) ringPush(data, static_cast<size_t>(len));
}

void linkBegin() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();     // never associate: ESP-NOW is peer-to-peer
  WiFi.setSleep(false);  // power save is exactly the latency this transport exists to delete
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("esp_now_init FAILED — no link");
    return;
  }
#ifdef ESPNOW_PMK
  esp_now_set_pmk(reinterpret_cast<const uint8_t*>(ESPNOW_PMK));
#endif
  esp_now_register_send_cb(onSent);
  esp_now_register_recv_cb(onRecv);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, kDongleMac, 6);
  peer.channel = ESPNOW_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) Serial.println("esp_now_add_peer FAILED");
  Serial.printf("\nbridge up (ESP-NOW): dongle %02X:%02X:%02X:%02X:%02X:%02X ch %d"
                " -> FC UART1 @%d (tx=GPIO%d rx=GPIO%d)\n",
                kDongleMac[0], kDongleMac[1], kDongleMac[2], kDongleMac[3], kDongleMac[4],
                kDongleMac[5], ESPNOW_CHANNEL, FC_BAUD, FC_TX_PIN, FC_RX_PIN);
}

int linkReceive(uint8_t* out, size_t cap) {
  if (ring_head - ring_tail < 2) return 0;
  const uint32_t t = ring_tail;
  const uint32_t len = ring[t & kRingMask] | (static_cast<uint32_t>(ring[(t + 1) & kRingMask]) << 8);
  if (ring_head - t < len + 2) return 0;  // torn write: impossible for whole-packet pushes
  const uint32_t n = min<uint32_t>(len, cap);
  for (uint32_t i = 0; i < n; i++) out[i] = ring[(t + 2 + i) & kRingMask];
  ring_tail = t + 2 + len;
  peer_ready = true;
  return static_cast<int>(n);
}

// One MSP frame per packet on the way IN (the dongle re-frames), but the FC->host direction is
// a raw byte STREAM — chunk boundaries are meaningless to the host's incremental parser, so
// splitting at the 250 B ESP-NOW payload cap loses nothing. (Whole-frame oversize guarding is
// the dongle's job, on the direction where frames actually exist.)
void linkWrite(const uint8_t* data, size_t len) {
  for (size_t off = 0; off < len; off += ESP_NOW_MAX_DATA_LEN) {
    const size_t n = min(len - off, static_cast<size_t>(ESP_NOW_MAX_DATA_LEN));
    if (esp_now_send(kDongleMac, data + off, n) != ESP_OK) {
      n_link_fail++;  // fire-and-forget: never block the loop on the radio
      return;
    }
    n_link_tx++;
  }
}

void linkReply(const uint8_t* data, size_t len) { linkWrite(data, len); }
bool linkPeerKnown() { return peer_ready; }
void linkPublish(const uint8_t* data, size_t len) { linkWrite(data, len); }
void linkMaintain() {}

void linkStatus(char* out, size_t cap) {
  snprintf(out, cap, "ESP-NOW ch %d  tx %lu  send_fail %lu  ring_drop %lu", ESPNOW_CHANNEL,
           (unsigned long)n_link_tx, (unsigned long)n_link_fail, (unsigned long)n_ring_drop);
}

#else  // ---------------------------------------- WiFi + UDP (default) ------------------------

WiFiUDP udp;
IPAddress peer_ip;
uint16_t peer_port = 0;
IPAddress src_ip;  // source of the packet currently being handled (the ToF reply's destination)
uint16_t src_port = 0;

// Try one network for ~8 s; return true if joined.
bool tryNetwork(const char* ssid, const char* pass) {
  Serial.printf("joining %s ", ssid);
  WiFi.begin(ssid, pass);
  for (int i = 0; i < 32; i++) {
    if (WiFi.status() == WL_CONNECTED) return true;
    delay(250);
    Serial.print(".");
  }
  Serial.println(" no");
  WiFi.disconnect(true);
  return false;
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // power save adds 100 ms+ latency spikes; this link flies a drone
  // Primary first (the flying-spot hotspot), then the fallback (home LAN), forever.
  while (true) {
    if (tryNetwork(WIFI_SSID, WIFI_PASS)) break;
#ifdef WIFI_SSID2
    if (tryNetwork(WIFI_SSID2, WIFI_PASS2)) break;
#endif
  }
  // mDNS: reachable as whoop-bridge.local regardless of what DHCP handed out.
  MDNS.begin(MDNS_NAME);
  Serial.printf("\nbridge up: %s (%s.local):%u -> FC UART1 @%d (tx=GPIO%d rx=GPIO%d)  RSSI %d dBm  BSSID %s\n",
                WiFi.localIP().toString().c_str(), MDNS_NAME, UDP_PORT, FC_BAUD, FC_TX_PIN,
                FC_RX_PIN, WiFi.RSSI(), WiFi.BSSIDstr().c_str());
}

void linkBegin() {
  connectWifi();
  udp.begin(UDP_PORT);
}

int linkReceive(uint8_t* out, size_t cap) {
  if (udp.parsePacket() <= 0) return 0;
  const int n = udp.read(out, cap);
  src_ip = udp.remoteIP();
  src_port = udp.remotePort();
  return n;
}

// Answer the host that sent the packet in hand (bridge-answered ids); does NOT promote that
// host to the telemetry peer — a ToF-only client must not steal the FC stream.
void linkReply(const uint8_t* data, size_t len) {
  udp.beginPacket(src_ip, src_port);
  udp.write(data, len);
  udp.endPacket();
}

bool linkPeerKnown() { return peer_port != 0; }

void linkPublish(const uint8_t* data, size_t len) {
  udp.beginPacket(peer_ip, peer_port);
  udp.write(data, len);
  udp.endPacket();
}

void linkMaintain() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
}

void linkStatus(char* out, size_t cap) {
  snprintf(out, cap, "%s  RSSI %d dBm  BSSID %s", WiFi.localIP().toString().c_str(), WiFi.RSSI(),
           WiFi.BSSIDstr().c_str());
}

#endif  // NW_LINK_ESPNOW
// ============================ end transport seam ============================================

// Downward VL53L1X: short-distance mode (fastest, ambient-robust, ~1.3 m reach — plenty for
// whoop hover heights), 20 ms timing budget, free-running at 25 ms (~40 Hz). Absent sensor is
// fine: init() fails, tof_ok stays false, the bridge proxies as before.
void initTof() {
  Wire.begin(D5, D6);  // as wired on our unit: D5/GPIO6 = SDA, D6/GPIO43 = SCL
  // 100 kHz, not 400: after the 2026-07-29 rewire the sensor stopped ACKing at 400 kHz
  // (Wire error 263 = ESP_ERR_TIMEOUT) while i2c_scan reached it fine at 100 kHz on these
  // same pins — the longer harness' bus capacitance pushes rise time through the breakout's
  // ~10k pull-ups past the 400 kHz budget. Costs ~2 ms per poll instead of ~0.6 ms; that is
  // inside the 25 ms poll period, but it is blocking, so watch `bench.py latency` if the MSP
  // RTT budget ever gets tight.
  Wire.setClock(100000);
  // 10 ms, not 100: setTimeout bounds how long a BLOCKING I2C transaction may stall loop(),
  // and loop() is the whole MSP proxy. The 2026-07-30 flights show host-side obs_age spiking
  // to ~200 ms on ~5% of control ticks with the entire telemetry frame frozen — the signature
  // of one or two I2C reads timing out at the old 100 ms budget. A whoop control loop cannot
  // afford a 100 ms blind window to salvage one range sample; drop the sample instead.
  tof.setTimeout(10);
  if (!tof.init()) {
    Serial.println("tof: no VL53L1X on I2C (D5=SDA D6=SCL) — ranging disabled");
    return;
  }
  tof.setDistanceMode(VL53L1X::Short);
  tof.setMeasurementTimingBudget(20000);
  tof.startContinuous(25);
  tof_ok = true;
  Serial.println("tof: VL53L1X up (short mode, 40 Hz)");
}

// Poll the sensor at a bounded cadence; keep only the freshest sample.
void pollTof() {
  if (!tof_ok || millis() - tof_poll_ms < kTofPollMs) return;
  tof_poll_ms = millis();
  if (!tof.dataReady()) return;
  tof.read(false);  // non-blocking: data is ready
  tof_mm = tof.ranging_data.range_mm;
  tof_status = static_cast<uint8_t>(tof.ranging_data.range_status);
  tof_ms = millis();
}

// Answer an intercepted MSP_BRIDGE_TOF request straight from the bridge ('$M>' framing so the
// host's stock MSP parser reads it like any FC reply).
void sendTofReply() {
  const uint32_t age = tof_ms ? min<uint32_t>(millis() - tof_ms, 0xFFFE) : 0xFFFF;
  const uint32_t lmax = min<uint32_t>(loop_max_us / 1000, 0xFFFF);
  uint8_t p[8] = {static_cast<uint8_t>(tof_mm & 0xFF), static_cast<uint8_t>(tof_mm >> 8),
                  tof_status, static_cast<uint8_t>(age & 0xFF), static_cast<uint8_t>(age >> 8),
                  static_cast<uint8_t>(tof_ok ? 1 : 0),
                  static_cast<uint8_t>(lmax & 0xFF), static_cast<uint8_t>(lmax >> 8)};
  uint8_t frame[3 + 2 + sizeof(p) + 1] = {'$', 'M', '>', sizeof(p), kMspBridgeTof};
  uint8_t ck = sizeof(p) ^ kMspBridgeTof;
  for (size_t i = 0; i < sizeof(p); i++) {
    frame[5 + i] = p[i];
    ck ^= p[i];
  }
  frame[5 + sizeof(p)] = ck;
  linkReply(frame, sizeof(frame));
}

}  // namespace

void setup() {
  Serial.begin(115200);  // USB CDC debug (the drone bridge's Serial is NOT a data path)
  pinMode(LED_BUILTIN, OUTPUT);
  fc.begin(FC_BAUD, SERIAL_8N1, FC_RX_PIN, FC_TX_PIN);
  initTof();
  linkBegin();
}

void loop() {
  const uint32_t t_loop_us = micros();

  // Host -> FC: forward each inbound payload that looks like MSP ('$' header) to the UART —
  // except requests for the bridge's own MSP_BRIDGE_TOF id, answered here and consumed.
  // Drain the whole burst: the host sends its per-tick queries back to back.
  const uint32_t t_rx_us = micros();
  for (int i = 0; i < kMaxRxPerLoop; i++) {
    const int n = linkReceive(rx_buf, sizeof(rx_buf));
    if (n <= 0) break;
    if (n >= 6 && rx_buf[0] == '$' && rx_buf[2] == '<' && rx_buf[4] == kMspBridgeTof) {
      const uint32_t t_tx_us = micros();
      sendTofReply();
      bump(sec_tof_reply, t_tx_us);
    } else if (rx_buf[0] == '$') {
#ifndef NW_LINK_ESPNOW
      peer_ip = src_ip;
      peer_port = src_port;
#endif
      last_cmd_ms = millis();
      fc.write(rx_buf, n);
    }
  }
  bump(sec_link_rx, t_rx_us);

  // FC -> host: ship whatever telemetry bytes are waiting back to the last commander.
  // Chunk boundaries don't matter — the host parser is incremental.
  const uint32_t t_utx_us = micros();
  int avail = fc.available();
  if (avail > 0 && linkPeerKnown()) {
    size_t take = min((size_t)avail, sizeof(tx_buf));
    size_t got = fc.readBytes(tx_buf, take);
    if (got > 0) linkPublish(tx_buf, got);
  }
  bump(sec_uart_tx, t_utx_us);

  // Blocking I2C — deliberately LAST, so it can never sit between an inbound MSP request and
  // its forward to the FC. A stalled bus now costs a dropped range sample, not a dropped tick.
  const uint32_t t_tof_us = micros();
  pollTof();
  bump(sec_poll_tof, t_tof_us);

  // XIAO ESP32-S3 user LED is active-LOW: LOW = lit.
  const bool fresh = (millis() - last_cmd_ms) < kLinkFreshMs && last_cmd_ms != 0;
  digitalWrite(LED_BUILTIN, fresh ? LOW : (((millis() >> 9) & 1) ? LOW : HIGH));

  // 5 s status heartbeat on USB: transport health at the actual flying spot (WiFi: link quality
  // and mesh node identity, since a repeater stealing the association changes the BSSID;
  // ESP-NOW: send failures and ring drops) and whether commands are flowing.
  static uint32_t last_status_ms = 0;
  if (millis() - last_status_ms > 5000) {
    const uint32_t t_st_us = micros();
    last_status_ms = millis();
    char link[128];
    linkStatus(link, sizeof(link));
    Serial.printf("status: %s  %s  loop_max %.1f ms"
                  "  [link_rx %.1f (tof_reply %.1f)  uart_tx %.1f  poll_tof %.1f  status %.1f]\n",
                  link, fresh ? "commands flowing" : "idle", loop_max_us / 1000.0,
                  sec_link_rx / 1000.0, sec_tof_reply / 1000.0, sec_uart_tx / 1000.0,
                  sec_poll_tof / 1000.0, sec_status / 1000.0);
    // Worst case per 5 s window, not since boot.
    loop_max_us = sec_link_rx = sec_tof_reply = sec_uart_tx = sec_poll_tof = 0;
    // This print's own cost (USB CDC + the blocking WiFi.RSSI/BSSIDstr calls) seeds the new
    // window, so a slow heartbeat indicts itself rather than hiding in loop_max.
    sec_status = micros() - t_st_us;
  }

  linkMaintain();

  const uint32_t dt_us = micros() - t_loop_us;
  if (dt_us > loop_max_us) loop_max_us = dt_us;
}
