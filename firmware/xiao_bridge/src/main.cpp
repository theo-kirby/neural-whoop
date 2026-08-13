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
// The one deliberate exception to transparency: the bridge owns its own DOWNWARD SENSORS and
// answers two MSP ids of ours locally (Betaflight never sees either) —
//   * cmd 192 MSP_BRIDGE_TOF  — VL53L1X rangefinder (CJMCU-531 on I2C, D5/SDA + D6/SCL): range.
//   * cmd 193 MSP_BRIDGE_FLOW — PMW3901 optical flow (SPI, D8/D9/D10 + D3/CS): motion counts.
// Requests for those ids are consumed, never forwarded; every other '$' packet passes through
// untouched. With neither sensor wired the bridge still boots and proxies; the replies just
// carry ok=0. That interception is also what makes `bench.py latency` able to split the air
// path from the FC path, so it matters just as much on ESP-NOW.
//
// The flow reply is deliberately a CUMULATIVE, NON-DESTRUCTIVE read: it reports running count
// sums and the bridge's own timestamp of the newest sample, and the host differences successive
// replies. A "counts since you last asked" reply would have been smaller and wrong — it makes
// every reply a destructive read, so a dropped packet silently eats motion, and a second client
// (a `bench.py flow` window left open next to a flight) steals it. Differencing is idempotent.
//
// LED: solid while command packets are flowing (<250 ms old), slow blink when idle/linkless.

#include <Arduino.h>
#include <ArduinoOTA.h>
#include <ESPmDNS.h>
#include <VL53L1X.h>
#include <WiFi.h>
#include <Wire.h>

#include "wifi_config.h"  // FC UART pins/baud (+ the WiFi credentials in the UDP build)
#include "pmw3901.h"      // optical flow (reads the FLOW_*_PIN defines wifi_config.h may set)

#ifdef NW_LINK_ESPNOW
#include <esp_now.h>
#include <esp_wifi.h>

#include "espnow_config.h"
#else
#include <WiFiUdp.h>
#endif

// Downward-ToF I2C pins — overridable from wifi_config.h, same "solder joints live in the
// config header" rule as FC_TX_PIN/FC_RX_PIN (they were hardcoded in initTof() until the
// 2026-08-13 rebuild made every net configurable). Defaults = the original build.
#ifndef TOF_SDA_PIN
#define TOF_SDA_PIN 6  // XIAO silkscreen D5
#endif
#ifndef TOF_SCL_PIN
#define TOF_SCL_PIN 43  // XIAO silkscreen D6
#endif

#ifndef MDNS_NAME
#define MDNS_NAME "whoop-bridge"
#endif

namespace {

constexpr uint32_t kLinkFreshMs = 250;
constexpr size_t kBufSize = 512;

// Every net gets its own GPIO — a duplicate is a config typo that fails at runtime in the least
// debuggable way (the default FLOW_CS_PIN collided with a rewired FC_RX_PIN in the 2026-08
// configs and nothing complained). Fail the BUILD instead: the one guaranteed-cheap moment to
// catch it is before the airframe closes up around the USB port. (C++11-safe recursion — the
// Arduino core does not guarantee constexpr loops.)
constexpr int kNetPins[] = {FC_TX_PIN,   FC_RX_PIN,    TOF_SDA_PIN,  TOF_SCL_PIN,
                            FLOW_SCK_PIN, FLOW_MISO_PIN, FLOW_MOSI_PIN, FLOW_CS_PIN};
constexpr bool pinsDistinct(const int* p, int n, int i = 0, int j = 1) {
  return i >= n - 1 ? true
         : j >= n   ? pinsDistinct(p, n, i + 1, i + 2)
         : p[i] == p[j] ? false
                        : pinsDistinct(p, n, i, j + 1);
}
static_assert(pinsDistinct(kNetPins, 8),
              "pin collision: two nets in wifi_config.h share a GPIO (check FC_*, TOF_*, FLOW_*)");

// Bridge-local MSP command: latest ToF range. Payload: u16 range_mm, u8 range_status
// (VL53L1X, 0 = valid), u16 age_ms (65535 = never), u8 sensor_ok, u16 loop_max_ms. Mirrored in
// neural_whoop/bench/msp.py (MSP_BRIDGE_TOF / decode_bridge_tof) — change both together.
// The trailing loop_max_ms was appended 2026-07-30; older hosts slice the first 6 bytes and
// ignore it, so the field is backwards-compatible in both directions.
constexpr uint8_t kMspBridgeTof = 192;
// Bridge-local MSP command: optical flow. Payload: i32 sum_dx, i32 sum_dy (cumulative counts
// since boot), u32 t_ms (bridge millis() of the newest sample, 0 = never), u16 n_frames
// (cumulative sample count, wraps), u8 squal, u8 motion, u8 sensor_ok, u16 age_ms (65535 =
// never). Mirrored in neural_whoop/bench/msp.py (MSP_BRIDGE_FLOW / decode_bridge_flow) — change
// both together. Cumulative by design (see the header note): the host differences two replies
// to get (dx, dy, dt), so a lost packet costs resolution, never motion.
constexpr uint8_t kMspBridgeFlow = 193;
// Bridge-local MSP command: open the over-the-air reflash window (see "OTA escape hatch"
// below). Request payload MUST be the 4-byte magic "NWOT" — a bare id is too easy to emit by
// accident for a command that drops the flight link. Reply: u8 accepted, u8 will_reboot
// (1 = this build now leaves the link and serves ArduinoOTA; 0 = WiFi build, where OTA is
// already running full-time and nothing changes). Mirrored in neural_whoop/bench/msp.py
// (MSP_BRIDGE_OTA) — change both together.
constexpr uint8_t kMspBridgeOta = 194;
constexpr uint8_t kOtaMagic[4] = {'N', 'W', 'O', 'T'};
// dataReady() is a BLOCKING I2C read, so every poll is dead time for the proxy. The sensor
// free-runs at 25 ms; 12 ms still catches every sample with one spare poll, at half the bus
// traffic of the old 5 ms.
constexpr uint32_t kTofPollMs = 12;
// One readMotion() is five register reads at 200 us of mandated settling each — ~1 ms of
// blocking SPI, a quarter of the ToF poll. The chip frames at up to 121 fps; 10 ms samples it
// well inside the 50 Hz control loop while keeping the duty cycle at ~10%. Counts ACCUMULATE
// between host reads, so a slower poll loses nothing but resolution.
constexpr uint32_t kFlowPollMs = 10;
// Cap on inbound packets serviced per loop() pass. The host fires 3-5 MSP queries per control
// tick as a burst; draining one per pass made the burst take 3-5 loop iterations (and any
// blocking call in between stretched the whole tick). Bounded so a flood can't starve the
// FC->host path.
constexpr int kMaxRxPerLoop = 8;

HardwareSerial fc(1);
VL53L1X tof;
Pmw3901 flow;

uint32_t last_cmd_ms = 0;

bool tof_ok = false;        // sensor found + ranging
uint16_t tof_mm = 0xFFFF;   // latest range (mm)
uint8_t tof_status = 0xFF;  // latest VL53L1X range_status (0 = valid)
uint32_t tof_ms = 0;        // millis() of the latest sample (0 = never)
uint32_t tof_poll_ms = 0;

bool flow_ok = false;        // sensor found + initialised
int32_t flow_dx = 0;         // cumulative motion counts since boot (host differences these)
int32_t flow_dy = 0;
uint32_t flow_ms = 0;        // millis() of the latest sample (0 = never)
uint16_t flow_n = 0;         // cumulative sample count (wraps; diagnostic)
uint8_t flow_squal = 0;      // latest surface quality (low = featureless floor)
uint8_t flow_motion = 0;     // Motion register MOT bit on the latest sample
uint32_t flow_poll_ms = 0;

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
uint32_t sec_poll_flow = 0;

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
  // This board's own STA MAC is printed so a fresh/replacement XIAO can be identified during
  // the one USB flash it will ever get — no separate mac_probe flash needed.
  Serial.printf("\nbridge up (ESP-NOW): this board %s  dongle %02X:%02X:%02X:%02X:%02X:%02X ch %d"
                " -> FC UART1 @%d (tx=GPIO%d rx=GPIO%d)\n",
                WiFi.macAddress().c_str(), kDongleMac[0], kDongleMac[1], kDongleMac[2],
                kDongleMac[3], kDongleMac[4], kDongleMac[5], ESPNOW_CHANNEL, FC_BAUD, FC_TX_PIN,
                FC_RX_PIN);
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
  // Own MAC on every heartbeat, not just at boot: the boot print routinely races USB CDC
  // enumeration and is lost, and the MAC is what espnow_config.h verification needs.
  snprintf(out, cap, "ESP-NOW ch %d  mac %s  tx %lu  send_fail %lu  ring_drop %lu",
           ESPNOW_CHANNEL, WiFi.macAddress().c_str(), (unsigned long)n_link_tx,
           (unsigned long)n_link_fail, (unsigned long)n_ring_drop);
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
  Serial.printf("\nbridge up: %s (%s.local):%u  mac %s -> FC UART1 @%d (tx=GPIO%d rx=GPIO%d)"
                "  RSSI %d dBm  BSSID %s\n",
                WiFi.localIP().toString().c_str(), MDNS_NAME, UDP_PORT,
                WiFi.macAddress().c_str(), FC_BAUD, FC_TX_PIN, FC_RX_PIN, WiFi.RSSI(),
                WiFi.BSSIDstr().c_str());
}

void linkBegin() {
  connectWifi();
  udp.begin(UDP_PORT);
  // OTA runs full-time in this build — the board is already on the LAN, so there is no window
  // to open: `pio run -e xiao_bridge_ota -t upload` works whenever the bridge is powered.
  ArduinoOTA.setHostname(MDNS_NAME);
  ArduinoOTA.begin();
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
  ArduinoOTA.handle();  // non-blocking poll of the OTA socket
}

void linkStatus(char* out, size_t cap) {
  snprintf(out, cap, "%s  RSSI %d dBm  BSSID %s", WiFi.localIP().toString().c_str(), WiFi.RSSI(),
           WiFi.BSSIDstr().c_str());
}

#endif  // NW_LINK_ESPNOW
// ============================ end transport seam ============================================

// ============================ OTA escape hatch ==============================================
// After final assembly the drone XIAO's USB port is a mechanical liability to reach
// (2026-08-13 rebuild), so the USB flash that installs this firmware is designed to be the
// LAST one — every later change arrives over the air:
//   * WiFi/UDP build — ArduinoOTA simply runs beside UDP full-time (see linkBegin), no window
//     needed. `pio run -e xiao_bridge_ota -t upload` whenever the bridge is powered.
//   * ESP-NOW build, command path — the host sends bridge-local id 194 + magic "NWOT"
//     (`bench.py ota` through the dongle). The bridge acks, drops the flight link, joins WiFi
//     (wifi_config.h credentials), announces MDNS_NAME.local, and serves ArduinoOTA for
//     kOtaWindowMs. `pio run -e xiao_bridge_espnow_ota -t upload`. A finished upload reboots
//     into the new firmware; a timeout restarts back into normal service.
//   * ESP-NOW build, rescue path — if NO link packet has EVER arrived kOtaBootFallbackMs after
//     boot, the command path can't work either (wrong dongle MAC / wrong channel / dead
//     dongle), so the bridge opens the same window on its own, then restarts and listens
//     again, forever. A battery plug-in therefore always makes the board flashable, even with
//     a completely broken espnow_config.h. Flights are unaffected: the host polls from session
//     start, and the first packet disarms the fallback for good.
// LED during the window: fast ~10 Hz strobe — visibly distinct from solid (commands flowing)
// and the ~1 Hz idle blink. Typing 'O' into the USB monitor also opens the window (ESP-NOW
// build), for bench use when the board happens to be on a cable anyway.

#ifdef NW_LINK_ESPNOW

constexpr uint32_t kOtaWindowMs = 180000;      // how long the window serves before giving up
constexpr uint32_t kOtaBootFallbackMs = 120000;  // silence-after-boot before the rescue window
bool ota_started = false;

[[noreturn]] void otaWindow() {
  esp_now_deinit();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  Serial.printf("OTA window: joining %s\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) delay(100);
#ifdef WIFI_SSID2
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.disconnect(true);
    Serial.printf("OTA window: joining %s\n", WIFI_SSID2);
    WiFi.begin(WIFI_SSID2, WIFI_PASS2);
    t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) delay(100);
  }
#endif
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("OTA window: no WiFi -- restarting into normal service");
    ESP.restart();
  }
  MDNS.begin(MDNS_NAME);
  ArduinoOTA.setHostname(MDNS_NAME);
  ArduinoOTA.onStart([]() {
    ota_started = true;  // hold the window open past its deadline while an upload runs
    Serial.println("OTA: receiving");
  });
  ArduinoOTA.onError([](ota_error_t e) {
    // A failed transfer must not wedge the window open forever (ota_started stays true).
    Serial.printf("OTA error %d -- restarting\n", static_cast<int>(e));
    ESP.restart();
  });
  ArduinoOTA.begin();
  Serial.printf("OTA window open %lus: %s (%s.local) -- pio run -e xiao_bridge_espnow_ota -t upload\n",
                (unsigned long)(kOtaWindowMs / 1000), WiFi.localIP().toString().c_str(),
                MDNS_NAME);
  t0 = millis();
  while (millis() - t0 < kOtaWindowMs || ota_started) {
    ArduinoOTA.handle();  // a successful upload reboots from inside this call
    digitalWrite(LED_BUILTIN, ((millis() / 50) & 1) ? LOW : HIGH);
    delay(1);
  }
  Serial.println("OTA window closed -- restarting into normal service");
  ESP.restart();
  for (;;) {}  // unreachable; satisfies [[noreturn]]
}

#endif  // NW_LINK_ESPNOW
// ============================ end OTA escape hatch ==========================================

// Downward VL53L1X: short-distance mode (fastest, ambient-robust, ~1.3 m reach — plenty for
// whoop hover heights), 20 ms timing budget, free-running at 25 ms (~40 Hz). Absent sensor is
// fine: init() fails, tof_ok stays false, the bridge proxies as before.
void initTof() {
  Wire.begin(TOF_SDA_PIN, TOF_SCL_PIN);  // pins live in wifi_config.h (defaults: D5/D6)
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
    Serial.printf("tof: no VL53L1X on I2C (sda=GPIO%d scl=GPIO%d) — ranging disabled\n",
                  TOF_SDA_PIN, TOF_SCL_PIN);
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

// Bring up the PMW3901. Absent sensor is fine — exactly like the ToF, flow_ok stays false and
// the bridge proxies as before. Note this shares no bus with the ToF (SPI vs I2C), so a fault
// in one cannot take the other down.
void initFlow() {
  if (!flow.begin()) {
    Serial.printf("flow: no PMW3901 on SPI (sck=GPIO%d miso=GPIO%d mosi=GPIO%d cs=GPIO%d)"
                  " — chip_id 0x%02X/0x%02X, want 0x49/0xB6\n",
                  FLOW_SCK_PIN, FLOW_MISO_PIN, FLOW_MOSI_PIN, FLOW_CS_PIN, flow.chipId(),
                  flow.chipIdInverse());
    return;
  }
  flow_ok = true;
  Serial.println("flow: PMW3901 up");
}

// Poll at a bounded cadence and ACCUMULATE. Unlike the ToF (where only the freshest range
// matters) every count here is displacement — dropping a sample loses real motion — so the
// running sums are what the reply carries.
void pollFlow() {
  if (!flow_ok || millis() - flow_poll_ms < kFlowPollMs) return;
  flow_poll_ms = millis();
  int16_t dx = 0, dy = 0;
  uint8_t squal = 0;
  bool motion = false;
  flow.readMotion(&dx, &dy, &squal, &motion);
  flow_dx += dx;
  flow_dy += dy;
  flow_squal = squal;
  flow_motion = motion ? 1 : 0;
  flow_n++;
  flow_ms = millis();
}

// Answer an intercepted MSP_BRIDGE_FLOW request. Same '$M>' framing as the ToF reply.
void sendFlowReply() {
  const uint32_t age = flow_ms ? min<uint32_t>(millis() - flow_ms, 0xFFFE) : 0xFFFF;
  uint8_t p[19];
  memcpy(p + 0, &flow_dx, 4);
  memcpy(p + 4, &flow_dy, 4);
  memcpy(p + 8, &flow_ms, 4);
  memcpy(p + 12, &flow_n, 2);
  p[14] = flow_squal;
  p[15] = flow_motion;
  p[16] = flow_ok ? 1 : 0;
  p[17] = static_cast<uint8_t>(age & 0xFF);
  p[18] = static_cast<uint8_t>(age >> 8);
  uint8_t frame[3 + 2 + sizeof(p) + 1] = {'$', 'M', '>', sizeof(p), kMspBridgeFlow};
  uint8_t ck = sizeof(p) ^ kMspBridgeFlow;
  for (size_t i = 0; i < sizeof(p); i++) {
    frame[5 + i] = p[i];
    ck ^= p[i];
  }
  frame[5 + sizeof(p)] = ck;
  linkReply(frame, sizeof(frame));
}

// Answer + act on an intercepted MSP_BRIDGE_OTA request. The magic payload is checked before
// anything else: a command that drops the flight link must be impossible to send by accident.
// May not return (ESP-NOW build: acks, then leaves for the OTA window and eventually reboots).
void handleOtaRequest(const uint8_t* buf, int n) {
  const bool magic_ok = n >= 10 && buf[3] >= 4 && memcmp(buf + 5, kOtaMagic, 4) == 0;
#ifdef NW_LINK_ESPNOW
  const uint8_t will_reboot = 1;
#else
  const uint8_t will_reboot = 0;  // WiFi build: OTA already runs full-time, nothing to do
#endif
  uint8_t p[2] = {static_cast<uint8_t>(magic_ok ? 1 : 0),
                  static_cast<uint8_t>(magic_ok ? will_reboot : 0)};
  uint8_t frame[3 + 2 + sizeof(p) + 1] = {'$', 'M', '>', sizeof(p), kMspBridgeOta};
  uint8_t ck = sizeof(p) ^ kMspBridgeOta;
  for (size_t i = 0; i < sizeof(p); i++) {
    frame[5 + i] = p[i];
    ck ^= p[i];
  }
  frame[5 + sizeof(p)] = ck;
  linkReply(frame, sizeof(frame));
#ifdef NW_LINK_ESPNOW
  if (magic_ok) {
    delay(100);   // let the radio actually send the ack before esp_now_deinit()
    otaWindow();  // never returns
  }
#endif
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
  initFlow();
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
    } else if (n >= 6 && rx_buf[0] == '$' && rx_buf[2] == '<' && rx_buf[4] == kMspBridgeFlow) {
      const uint32_t t_tx_us = micros();
      sendFlowReply();
      bump(sec_tof_reply, t_tx_us);  // same "bridge-answered a local id" budget as the ToF
    } else if (n >= 6 && rx_buf[0] == '$' && rx_buf[2] == '<' && rx_buf[4] == kMspBridgeOta) {
      handleOtaRequest(rx_buf, n);  // may not return (ESP-NOW build: reboots via OTA window)
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

  // Blocking sensor buses — deliberately LAST, so neither can sit between an inbound MSP request
  // and its forward to the FC. A stalled bus now costs a dropped sample, not a dropped tick.
  const uint32_t t_tof_us = micros();
  pollTof();
  bump(sec_poll_tof, t_tof_us);

  const uint32_t t_flow_us = micros();
  pollFlow();
  bump(sec_poll_flow, t_flow_us);

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
    // An absent flow sensor is re-probed here, at heartbeat cadence: a fixed joint (or RST
    // jumper) then shows up within 5 s with no power cycle, and each failed probe prints the
    // chip ids — the actual diagnostic (0x00/0x00 = MISO stuck low: unpowered/CS/wrong wire;
    // 0xFF/0xFF = MISO floating; other garbage = SPI lines swapped). The probe costs a few ms
    // and runs ONLY while the sensor is absent, so a flow-equipped flight never pays it.
    if (!flow_ok) initFlow();
    char link[160];
    linkStatus(link, sizeof(link));
    char flowinfo[48];
    if (flow_ok) {
      snprintf(flowinfo, sizeof(flowinfo), "flow ok squal %u", flow_squal);
    } else {
      snprintf(flowinfo, sizeof(flowinfo), "flow ABSENT id 0x%02X/0x%02X want 0x49/0xB6",
               flow.chipId(), flow.chipIdInverse());
    }
    Serial.printf("status: %s  %s  loop_max %.1f ms"
                  "  [link_rx %.1f (sensor_reply %.1f)  uart_tx %.1f  poll_tof %.1f"
                  "  poll_flow %.1f  status %.1f]  %s\n",
                  link, fresh ? "commands flowing" : "idle", loop_max_us / 1000.0,
                  sec_link_rx / 1000.0, sec_tof_reply / 1000.0, sec_uart_tx / 1000.0,
                  sec_poll_tof / 1000.0, sec_poll_flow / 1000.0, sec_status / 1000.0, flowinfo);
    // Worst case per 5 s window, not since boot.
    loop_max_us = sec_link_rx = sec_tof_reply = sec_uart_tx = sec_poll_tof = sec_poll_flow = 0;
    // This print's own cost (USB CDC + the blocking WiFi.RSSI/BSSIDstr calls) seeds the new
    // window, so a slow heartbeat indicts itself rather than hiding in loop_max.
    sec_status = micros() - t_st_us;
  }

  linkMaintain();

#ifdef NW_LINK_ESPNOW
  // OTA rescue path: nothing has EVER arrived over ESP-NOW, so the command path can't reach us
  // either — open the window unprompted (see the "OTA escape hatch" block). The first real
  // packet of a session sets peer_ready and disarms this for good.
  if (!linkPeerKnown() && millis() > kOtaBootFallbackMs) otaWindow();
  // Bench convenience when the board happens to be on a USB cable anyway: 'O' in the monitor.
  if (Serial.available() && Serial.read() == 'O') otaWindow();
#endif

  const uint32_t dt_us = micros() - t_loop_us;
  if (dt_us > loop_max_us) loop_max_us = dt_us;
}
