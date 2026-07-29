// I2C wiring probe (pio run -e i2c_scan): finds a VL53L1X (or anything else) on the bus
// regardless of which pins it actually landed on, and — more usefully — tells you whether the
// sensor has power at all before you start second-guessing SDA/SCL.
//
// Two passes, no WiFi, no FC needed:
//
//   1. Idle-level pass. Every candidate pin is read as a plain INPUT with the internal
//      pull-up OFF. The CJMCU-531 breakout carries its own ~10k pull-ups to VIN, so a pin
//      wired to a *powered* sensor reads HIGH with nothing driving it. A floating pin is
//      LOW/erratic. This is the decisive VIN check: if SDA and SCL both read LOW here, the
//      3V3 wire is the fault and no amount of pin-swapping will help.
//   2. Scan pass. Sweeps every ordered (SDA, SCL) pair of candidate pins, probing addresses
//      0x08..0x77. A VL53L1X answers at 0x29 by default. Any hit prints the pin pair that
//      found it, which is the wiring you should put in initTof()/Wire.begin().
//
// D9/D10 are deliberately excluded: they are the FC UART pair, and clocking them would drive
// signals into a flight controller that is usually unpowered on the bench.

#include <Arduino.h>
#include <Wire.h>

namespace {

struct Pin {
  uint8_t gpio;
  const char *name;
};

// XIAO ESP32-S3 broken-out pins, minus D9/D10 (FC UART).
constexpr Pin kPins[] = {
    {1, "D0"},  {2, "D1"},  {3, "D2"},  {4, "D3"},  {5, "D4"},
    {6, "D5"},  {43, "D6"}, {44, "D7"}, {7, "D8"},
};
constexpr size_t kNumPins = sizeof(kPins) / sizeof(kPins[0]);

void idleLevels() {
  Serial.println("\n--- idle levels (internal pull-ups OFF) ---");
  Serial.println("HIGH = held up by an external pull-up => sensor powered and wired here.");
  Serial.println("LOW  = floating or shorted to GND.\n");
  for (size_t i = 0; i < kNumPins; i++) {
    pinMode(kPins[i].gpio, INPUT);
  }
  delay(10);
  int high_count = 0;
  for (size_t i = 0; i < kNumPins; i++) {
    // Sample a few times: a floating pin rarely reads the same value repeatedly.
    int high = 0;
    for (int s = 0; s < 8; s++) {
      high += digitalRead(kPins[i].gpio) == HIGH ? 1 : 0;
      delay(1);
    }
    const char *verdict = high == 8 ? "HIGH (pulled up)" : (high == 0 ? "LOW" : "unstable/floating");
    Serial.printf("  %-3s GPIO%-2u : %s\n", kPins[i].name, kPins[i].gpio, verdict);
    if (high == 8) high_count++;
  }
  if (high_count < 2) {
    Serial.println("\n  !! Fewer than 2 pins are pulled high. A powered CJMCU-531 pulls BOTH");
    Serial.println("     SDA and SCL high. Check 3V3 -> VIN and GND before anything else.");
  }
}

// Probe one (sda, scl) pair; returns the number of devices that ACKed.
int scanPair(uint8_t sda, uint8_t scl, const char *sda_name, const char *scl_name) {
  Wire.begin(sda, scl, 100000);
  int found = 0;
  for (uint8_t addr = 0x08; addr <= 0x77; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      if (found == 0) Serial.printf("  SDA=%s SCL=%s :", sda_name, scl_name);
      Serial.printf(" 0x%02X%s", addr, addr == 0x29 ? " (VL53L1X!)" : "");
      found++;
    }
  }
  if (found) Serial.println();
  Wire.end();
  return found;
}

void scanAllPairs() {
  Serial.println("\n--- bus scan over every candidate pin pair ---");
  int total = 0;
  for (size_t a = 0; a < kNumPins; a++) {
    for (size_t b = 0; b < kNumPins; b++) {
      if (a == b) continue;
      total += scanPair(kPins[a].gpio, kPins[b].gpio, kPins[a].name, kPins[b].name);
    }
  }
  if (total == 0) {
    Serial.println("  nothing ACKed on any pin pair.");
    Serial.println("  => the sensor is unpowered, not connected, or dead. Re-check the idle");
    Serial.println("     levels above; SDA/SCL order does NOT matter for this conclusion.");
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(3000);  // USB CDC needs a moment before the host is listening
  Serial.println("\n=== i2c_scan: XIAO ESP32-S3 bus probe ===");
  idleLevels();
  scanAllPairs();
  Serial.println("\ndone. (reset the board to run again)");
}

void loop() {
  delay(1000);
}
