// UART wiring probe (pio run -e uart_probe): no WiFi — sends "ping <n>\r\n" out the FC
// UART every second and hex-dumps every byte received, all over USB serial. Pair with
// Betaflight CLI `serialpassthrough uart1 115200` on the FC side:
//   - "ping" lines appear in the Betaflight CLI  -> XIAO TX -> FC RX direction works
//   - typing in the CLI shows hex on this monitor -> FC TX -> XIAO RX direction works
// Uses the same FC_TX_PIN/FC_RX_PIN/FC_BAUD as the bridge (wifi_config.h).

#include <Arduino.h>

#include "wifi_config.h"

namespace {
HardwareSerial fc(1);
uint32_t last_ping_ms = 0;
uint32_t n = 0;
}  // namespace

void setup() {
  Serial.begin(115200);
  fc.begin(FC_BAUD, SERIAL_8N1, FC_RX_PIN, FC_TX_PIN);
  delay(2000);
  Serial.printf("uart probe: tx=GPIO%d rx=GPIO%d @%d\n", FC_TX_PIN, FC_RX_PIN, FC_BAUD);
}

void loop() {
  if (millis() - last_ping_ms > 1000) {
    last_ping_ms = millis();
    fc.printf("ping %lu\r\n", (unsigned long)++n);
    Serial.printf("[tx] ping %lu\n", (unsigned long)n);
  }
  while (fc.available()) {
    int b = fc.read();
    Serial.printf("[rx] %02X '%c'\n", b, (b >= 32 && b < 127) ? (char)b : '.');
  }
}
