// Pre-solder bring-up test (pio run -e blink_test): joins WiFi with the same
// wifi_config.h the real bridge uses, prints the IP, and toggles the user LED on
// UDP "on"/"off" packets to UDP_PORT — proving board, USB flashing, WiFi join, and
// the UDP RX/TX path end-to-end before anything is wired to the FC.
//
// From the host:  printf on  | nc -u -w1 <bridge-ip> 14550   (LED lights, replies "ok on")
//                 printf off | nc -u -w1 <bridge-ip> 14550
// While no packet has arrived for 2 s, the LED slow-blinks as a heartbeat.

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include "wifi_config.h"

namespace {

WiFiUDP udp;
char buf[64];
bool led_cmd = false;
uint32_t last_pkt_ms = 0;

// XIAO ESP32-S3 user LED (GPIO21) is active-LOW.
void setLed(bool on) { digitalWrite(LED_BUILTIN, on ? LOW : HIGH); }

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("joining %s ", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.printf("\ntest bridge up: %s  (UDP %u, RSSI %d dBm)\n",
                WiFi.localIP().toString().c_str(), UDP_PORT, WiFi.RSSI());
}

}  // namespace

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  setLed(false);
  connectWifi();
  udp.begin(UDP_PORT);
}

void loop() {
  int n = udp.parsePacket();
  if (n > 0) {
    n = udp.read(buf, sizeof(buf) - 1);
    if (n > 0) {
      buf[n] = '\0';
      last_pkt_ms = millis();
      if (strncmp(buf, "on", 2) == 0) led_cmd = true;
      if (strncmp(buf, "off", 3) == 0) led_cmd = false;
      Serial.printf("rx %d bytes from %s:%u -> LED %s\n", n,
                    udp.remoteIP().toString().c_str(), udp.remotePort(),
                    led_cmd ? "ON" : "OFF");
      udp.beginPacket(udp.remoteIP(), udp.remotePort());
      udp.printf("ok %s", led_cmd ? "on" : "off");
      udp.endPacket();
    }
  }

  const bool recent = last_pkt_ms != 0 && (millis() - last_pkt_ms) < 2000;
  if (recent) {
    setLed(led_cmd);
  } else {
    setLed((millis() >> 9) & 1);  // idle heartbeat
  }

  if (WiFi.status() != WL_CONNECTED) connectWifi();
}
