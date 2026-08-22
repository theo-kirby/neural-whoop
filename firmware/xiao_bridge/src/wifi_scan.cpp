// RF health probe: WiFi scan + crystal report (pio run -e wifi_scan_minikit -t upload).
//
// Written for the 2026-08-22 dongle-candidate triage: an MH-ET LIVE MiniKit clone printed at
// 74880 baud against a Serial.begin(115200) — the 26-vs-40 MHz crystal signature — and a
// mis-clocked crystal takes the radio's PLL with it, so "does WiFi see anything at all" is the
// one-number verdict on whether a board can be an ESP-NOW dongle. Scan finds APs = RF healthy;
// zero APs forever in a busy 2.4 GHz environment = the radio is off-frequency, use another
// board. Prints the runtime-detected crystal frequency too, which names the fault directly.
#include <Arduino.h>
#include <WiFi.h>

#include "soc/rtc.h"

void setup() {
  Serial.begin(115200);  // on a mis-clocked board this lands at baud*xtal_actual/xtal_assumed
  delay(2000);
  Serial.printf("\n=== RF health probe ===\n");
  Serial.printf("detected XTAL: %d MHz  (26 here + garbled-at-115200 serial = clone crystal)\n",
                (int)rtc_clk_xtal_freq_get());
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
}

void loop() {
  const int n = WiFi.scanNetworks(/*async=*/false, /*hidden=*/true);
  Serial.printf("scan: %d network(s)\n", n);
  for (int i = 0; i < n && i < 8; i++) {
    Serial.printf("  ch %2d  %4d dBm  %s\n", WiFi.channel(i), WiFi.RSSI(i),
                  WiFi.SSID(i).c_str());
  }
  WiFi.scanDelete();
  delay(3000);
}
