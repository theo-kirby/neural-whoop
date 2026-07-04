// XIAO ESP32-S3 MSP bridge: transparent UDP <-> UART proxy between the host and the
// flight controller (sim2real branch B, docs/SIM2REAL.md).
//
// Design: the bridge carries raw MSP frames unmodified in both directions (the DroneBridge
// pattern), so the host talks the same protocol over WiFi that it talks over USB — the
// entire scripts/bench.py toolkit works through it via --udp. The bridge itself is dumb on
// purpose: no parsing beyond a header sanity check, no state. Safety comes from Betaflight's
// own MSP-RC freshness window (300 ms): when the link drops, the bridge simply has nothing
// to forward and the FC's msp_override failsafe policy takes over. The bridge never
// fabricates a frame.
//
// LED: solid while command packets are flowing (<250 ms old), slow blink when idle/linkless.

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include "wifi_config.h"

namespace {

constexpr uint32_t kLinkFreshMs = 250;
constexpr size_t kBufSize = 512;

HardwareSerial fc(1);
WiFiUDP udp;

IPAddress peer_ip;
uint16_t peer_port = 0;
uint32_t last_cmd_ms = 0;

uint8_t rx_buf[kBufSize];  // UDP -> UART
uint8_t tx_buf[kBufSize];  // UART -> UDP

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // power save adds 100 ms+ latency spikes; this link flies a drone
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.printf("\nbridge up: %s:%u -> FC UART%d @%d\n", WiFi.localIP().toString().c_str(),
                UDP_PORT, 1, FC_BAUD);
}

}  // namespace

void setup() {
  Serial.begin(115200);  // USB CDC debug
  pinMode(LED_BUILTIN, OUTPUT);
  fc.begin(FC_BAUD, SERIAL_8N1, FC_RX_PIN, FC_TX_PIN);
  connectWifi();
  udp.begin(UDP_PORT);
}

void loop() {
  // Host -> FC: forward each UDP payload that looks like MSP ('$' header) to the UART.
  int n = udp.parsePacket();
  if (n > 0) {
    n = udp.read(rx_buf, sizeof(rx_buf));
    if (n > 0 && rx_buf[0] == '$') {
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

  const bool fresh = (millis() - last_cmd_ms) < kLinkFreshMs && last_cmd_ms != 0;
  digitalWrite(LED_BUILTIN, fresh ? HIGH : ((millis() >> 9) & 1));

  if (WiFi.status() != WL_CONNECTED) connectWifi();
}
