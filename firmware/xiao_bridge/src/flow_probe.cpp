// PMW3901 wiring probe + count-scale calibration rig. No WiFi, no FC, no battery — USB alone.
// Run this after soldering the flow sensor and BEFORE flashing the bridge, the same way
// i2c_scan.cpp precedes the ToF (firmware/xiao_bridge/README.md).
//
// Pass 1 is the handshake: chip id 0x49 / inverse 0xB6. Anything else is wiring — the SPI trio
// or CS, or an unpowered board (3V3, not 5V: this breakout has no regulator input). The two ids
// are printed even on failure, because WHICH wrong value comes back is the diagnostic: 0x00
// means MISO never goes high (open MISO, or the sensor unpowered), 0xFF means it never goes low
// (MISO shorted high, or CS never asserted), and a plausible-but-wrong pair means the bus works
// but something is corrupting it (clock too fast, wrong SPI mode).
//
// Pass 2 streams motion at 10 Hz and is the CALIBRATION rig, which is the real reason this
// exists. The flow-to-velocity constant is
//
//     v = (counts / dt) * rad_per_count * height
//
// and `rad_per_count` is the one number the datasheet does not hand you usably. Measure it
// instead: rest the sensor at a KNOWN height above a textured surface (a printed page, not a
// bare white desk), send any character to zero the sums, slide it exactly 100 mm along +x, and
// read the count total. Then rad_per_count = distance / (height * counts). Do it at two heights
// and the pair should agree — if they do not, the lens standoff is wrong or the surface is too
// close to the 80 mm minimum. That measured constant is what neural_whoop.pilot's flow
// integrator and configs/flow-hover.yaml's `flow_scale_frac` DR are calibrated against.

#include <Arduino.h>

#include "pmw3901.h"

namespace {

Pmw3901 flow;
int32_t sum_dx = 0, sum_dy = 0;
uint32_t n = 0;
uint32_t last_print_ms = 0;

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(2000);  // USB CDC needs a moment before the first print is visible
  Serial.println("\n=== PMW3901 probe ===");
  Serial.printf("pins: sck=GPIO%d miso=GPIO%d mosi=GPIO%d cs=GPIO%d\n", FLOW_SCK_PIN,
                FLOW_MISO_PIN, FLOW_MOSI_PIN, FLOW_CS_PIN);

  const bool ok = flow.begin();
  Serial.printf("chip_id 0x%02X (want 0x49)  inverse 0x%02X (want 0xB6)  -> %s\n", flow.chipId(),
                flow.chipIdInverse(), ok ? "OK" : "FAIL");
  if (!ok) {
    Serial.println("no sensor. check 3V3 (NOT 5V), GND, and the four SPI wires; RST must be");
    Serial.println("tied HIGH (it is active-low reset — a floating RST reads as random resets).");
    return;
  }
  Serial.println("\nslide the sensor over a TEXTURED surface at a known height.");
  Serial.println("send any character to zero the sums; rad_per_count = distance/(height*counts)");
  Serial.println("\n      dx     dy    squal  mot        sum_dx     sum_dy   n");
}

void loop() {
  if (!flow.ok()) {
    delay(1000);
    return;
  }
  if (Serial.available()) {
    while (Serial.available()) Serial.read();
    sum_dx = sum_dy = 0;
    n = 0;
    Serial.println("-- sums zeroed --");
  }

  int16_t dx = 0, dy = 0;
  uint8_t squal = 0;
  bool motion = false;
  flow.readMotion(&dx, &dy, &squal, &motion);
  sum_dx += dx;
  sum_dy += dy;
  n++;

  // Sample fast (the chip frames far quicker than a human can read), print slow.
  if (millis() - last_print_ms >= 100) {
    last_print_ms = millis();
    Serial.printf("  %6d %6d   %4u   %s   %10ld %10ld  %lu\n", dx, dy, squal,
                  motion ? "Y" : ".", (long)sum_dx, (long)sum_dy, (unsigned long)n);
  }
  delay(10);
}
