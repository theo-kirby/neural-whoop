// Independent-implementation check: the canonical Bitcraze_PMW3901 library instead of our
// in-repo pmw3901.h — the "wrong library?" falsifier. SPI.begin() is called FIRST with the
// rig's actual pins; the ESP32 core's begin() early-returns when already initialized, so the
// library's internal default-pin begin() is a no-op and the custom pin map survives.

#include <Arduino.h>
#include <SPI.h>

#include "Bitcraze_PMW3901.h"

#ifndef FLOW_SCK_PIN
#define FLOW_SCK_PIN 8
#endif
#ifndef FLOW_MISO_PIN
#define FLOW_MISO_PIN 7
#endif
#ifndef FLOW_MOSI_PIN
#define FLOW_MOSI_PIN 9
#endif
#ifndef FLOW_CS_PIN
#define FLOW_CS_PIN 44
#endif

Bitcraze_PMW3901 flow(FLOW_CS_PIN);

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.printf("=== Bitcraze_PMW3901 library probe sck=GPIO%d miso=GPIO%d mosi=GPIO%d "
                "cs=GPIO%d ===\n",
                FLOW_SCK_PIN, FLOW_MISO_PIN, FLOW_MOSI_PIN, FLOW_CS_PIN);
  SPI.begin(FLOW_SCK_PIN, FLOW_MISO_PIN, FLOW_MOSI_PIN, FLOW_CS_PIN);
}

void loop() {
  bool ok = flow.begin();
  Serial.printf("flow.begin() -> %s\n", ok ? "TRUE <<< SENSOR ALIVE" : "false (init failed)");
  if (ok) {
    for (;;) {
      int16_t dx = 0, dy = 0;
      flow.readMotionCount(&dx, &dy);
      Serial.printf("dx=%d dy=%d\n", dx, dy);
      delay(200);
    }
  }
  delay(2000);
}
