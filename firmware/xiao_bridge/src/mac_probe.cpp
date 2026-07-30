// MAC probe: print this board's STA MAC address in the exact form espnow_config.h wants.
//
//   pio run -e mac_probe -t upload && pio device monitor
//
// Run once per board (dongle and drone bridge) during ESP-NOW bring-up — ESP-NOW peers are
// addressed by MAC and there is no discovery in our build, so these two numbers ARE the
// pairing. Nothing else happens here: no WiFi join, no UART, no I2C.
//
// The address printed is the *station* MAC (WIFI_IF_STA), which is what esp_now_add_peer()
// matches against, and it is what both ESP-NOW binaries use (they run WIFI_STA with no AP).

#include <Arduino.h>
#include <WiFi.h>

void setup() {
  Serial.begin(115200);
  // USB CDC enumerates well after boot; without this the first prints vanish into the void.
  delay(2000);
  WiFi.mode(WIFI_STA);
  uint8_t mac[6];
  WiFi.macAddress(mac);
  Serial.println("\n=== XIAO ESP32-S3 MAC probe ===");
  Serial.printf("STA MAC : %s\n", WiFi.macAddress().c_str());
  Serial.printf("espnow_config.h form:\n  {0x%02X, 0x%02X, 0x%02X, 0x%02X, 0x%02X, 0x%02X}\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  Serial.println("Paste into ESPNOW_DRONE_MAC (the FC-wired board) or ESPNOW_DONGLE_MAC (the\n"
                 "desk board), then reflash both with the real firmware.");
}

void loop() {
  // Reprint slowly: the monitor is usually attached after the board has already booted.
  delay(5000);
  Serial.printf("STA MAC : %s\n", WiFi.macAddress().c_str());
}
