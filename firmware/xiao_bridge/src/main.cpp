// XIAO ESP32-S3 MSP bridge: transparent UDP <-> UART proxy between the host and the
// flight controller (sim2real branch B, docs/SIM2REAL.md).
//
// Design: the bridge carries raw MSP frames unmodified in both directions (the DroneBridge
// pattern), so the host talks the same protocol over WiFi that it talks over USB — the
// entire scripts/bench.py toolkit works through it via --udp. The bridge itself is dumb on
// purpose: no parsing beyond a header sanity check, no state. Safety comes from Betaflight's
// own MSP-RC freshness window (300 ms): when the link drops, the bridge simply has nothing
// to forward and the FC's msp_override failsafe policy takes over. The bridge never
// fabricates an FC frame.
//
// The one deliberate exception to transparency: the bridge owns a downward VL53L1X ToF
// rangefinder (CJMCU-531 breakout on the XIAO's stock I2C pins, D4/SDA + D5/SCL) and answers
// MSP v1 cmd 192 (MSP_BRIDGE_TOF, our id — Betaflight never sees it) locally with the latest
// range. Requests for that id are consumed, never forwarded; every other '$' packet passes
// through untouched. With no sensor wired the bridge still boots and proxies; the reply just
// carries ok=0.
//
// LED: solid while command packets are flowing (<250 ms old), slow blink when idle/linkless.

#include <Arduino.h>
#include <ESPmDNS.h>
#include <VL53L1X.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>

#include "wifi_config.h"

#ifndef MDNS_NAME
#define MDNS_NAME "whoop-bridge"
#endif

namespace {

constexpr uint32_t kLinkFreshMs = 250;
constexpr size_t kBufSize = 512;

// Bridge-local MSP command: latest ToF range. Payload: u16 range_mm, u8 range_status
// (VL53L1X, 0 = valid), u16 age_ms (65535 = never), u8 sensor_ok. Mirrored in
// neural_whoop/bench/msp.py (MSP_BRIDGE_TOF / decode_bridge_tof) — change both together.
constexpr uint8_t kMspBridgeTof = 192;
constexpr uint32_t kTofPollMs = 5;  // dataReady() is an I2C read; don't hammer it every loop

HardwareSerial fc(1);
WiFiUDP udp;
VL53L1X tof;

IPAddress peer_ip;
uint16_t peer_port = 0;
uint32_t last_cmd_ms = 0;

bool tof_ok = false;        // sensor found + ranging
uint16_t tof_mm = 0xFFFF;   // latest range (mm)
uint8_t tof_status = 0xFF;  // latest VL53L1X range_status (0 = valid)
uint32_t tof_ms = 0;        // millis() of the latest sample (0 = never)
uint32_t tof_poll_ms = 0;

uint8_t rx_buf[kBufSize];  // UDP -> UART
uint8_t tx_buf[kBufSize];  // UART -> UDP

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

// Downward VL53L1X: short-distance mode (fastest, ambient-robust, ~1.3 m reach — plenty for
// whoop hover heights), 20 ms timing budget, free-running at 25 ms (~40 Hz). Absent sensor is
// fine: init() fails, tof_ok stays false, the bridge proxies as before.
void initTof() {
  Wire.begin();  // XIAO ESP32-S3 stock I2C: D4/GPIO5 = SDA, D5/GPIO6 = SCL
  Wire.setClock(400000);
  tof.setTimeout(100);
  if (!tof.init()) {
    Serial.println("tof: no VL53L1X on I2C (D4=SDA D5=SCL) — ranging disabled");
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
  uint8_t p[6] = {static_cast<uint8_t>(tof_mm & 0xFF), static_cast<uint8_t>(tof_mm >> 8),
                  tof_status, static_cast<uint8_t>(age & 0xFF), static_cast<uint8_t>(age >> 8),
                  static_cast<uint8_t>(tof_ok ? 1 : 0)};
  uint8_t frame[3 + 2 + sizeof(p) + 1] = {'$', 'M', '>', sizeof(p), kMspBridgeTof};
  uint8_t ck = sizeof(p) ^ kMspBridgeTof;
  for (size_t i = 0; i < sizeof(p); i++) {
    frame[5 + i] = p[i];
    ck ^= p[i];
  }
  frame[5 + sizeof(p)] = ck;
  udp.beginPacket(udp.remoteIP(), udp.remotePort());
  udp.write(frame, sizeof(frame));
  udp.endPacket();
}

}  // namespace

void setup() {
  Serial.begin(115200);  // USB CDC debug
  pinMode(LED_BUILTIN, OUTPUT);
  fc.begin(FC_BAUD, SERIAL_8N1, FC_RX_PIN, FC_TX_PIN);
  initTof();
  connectWifi();
  udp.begin(UDP_PORT);
}

void loop() {
  pollTof();

  // Host -> FC: forward each UDP payload that looks like MSP ('$' header) to the UART —
  // except requests for the bridge's own MSP_BRIDGE_TOF id, answered here and consumed.
  int n = udp.parsePacket();
  if (n > 0) {
    n = udp.read(rx_buf, sizeof(rx_buf));
    if (n >= 6 && rx_buf[0] == '$' && rx_buf[2] == '<' && rx_buf[4] == kMspBridgeTof) {
      sendTofReply();
    } else if (n > 0 && rx_buf[0] == '$') {
      peer_ip = udp.remoteIP();
      peer_port = udp.remotePort();
      last_cmd_ms = millis();
      fc.write(rx_buf, n);
    }
  }

  // FC -> host: ship whatever telemetry bytes are waiting back to the last commander.
  // Chunk boundaries don't matter — the host parser is incremental.
  int avail = fc.available();
  if (avail > 0 && peer_port != 0) {
    size_t take = min((size_t)avail, sizeof(tx_buf));
    size_t got = fc.readBytes(tx_buf, take);
    if (got > 0) {
      udp.beginPacket(peer_ip, peer_port);
      udp.write(tx_buf, got);
      udp.endPacket();
    }
  }

  // XIAO ESP32-S3 user LED is active-LOW: LOW = lit.
  const bool fresh = (millis() - last_cmd_ms) < kLinkFreshMs && last_cmd_ms != 0;
  digitalWrite(LED_BUILTIN, fresh ? LOW : (((millis() >> 9) & 1) ? LOW : HIGH));

  // 5 s status heartbeat on USB: link quality at the actual flying spot, mesh node identity
  // (BSSID changes when a repeater steals the association), and whether commands are flowing.
  static uint32_t last_status_ms = 0;
  if (millis() - last_status_ms > 5000) {
    last_status_ms = millis();
    Serial.printf("status: %s  RSSI %d dBm  BSSID %s  %s\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI(), WiFi.BSSIDstr().c_str(),
                  fresh ? "commands flowing" : "idle");
  }

  if (WiFi.status() != WL_CONNECTED) connectWifi();
}
