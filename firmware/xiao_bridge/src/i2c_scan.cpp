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
// D2/D3 are deliberately excluded: they are the FC UART pair (rewired 2026-08-08, was D0/D1,
// before that D9/D10), and clocking them would drive signals into the flight controller.

#include <Arduino.h>
#include <Wire.h>

namespace {

struct Pin {
  uint8_t gpio;
  const char *name;
};

// XIAO ESP32-S3 broken-out pins, minus D2/D3 (FC UART).
constexpr Pin kPins[] = {
    {1, "D0"},  {2, "D1"},  {5, "D4"},  {6, "D5"},  {43, "D6"},
    {44, "D7"}, {7, "D8"},  {8, "D9"},  {9, "D10"},
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
  // Wire.end() leaves the pins routed to the I2C peripheral in the GPIO matrix, so a pin used
  // as SCL in one pair keeps clocking in later pairs and every pair with the right SDA appears
  // to ACK. Forcing both pins back to plain inputs detaches them.
  pinMode(sda, INPUT);
  pinMode(scl, INPUT);
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

// Clock sweep on the expected pair. Precedent (initTof(), 2026-07-29 rewire): this bus already
// dropped from 400 kHz to 100 kHz once — harness capacitance vs the breakout's ~10k pull-ups.
// If 0x29 ACKs only at a slow clock, the chip is alive and the fault is rise time (wire length /
// joint quality), not wiring order. If it ACKs at nothing down to 10 kHz, the chip itself (or
// its ground return) is the fault.
void clockSweep(uint8_t sda, uint8_t scl, const char *sda_name, const char *scl_name) {
  Serial.printf("\n--- clock sweep, SDA=%s SCL=%s, addr 0x29 ---\n", sda_name, scl_name);
  constexpr uint32_t kClocks[] = {400000, 100000, 50000, 10000};
  for (uint32_t hz : kClocks) {
    Wire.begin(sda, scl, hz);
    Wire.beginTransmission(0x29);
    const uint8_t err = Wire.endTransmission();
    Serial.printf("  %6lu Hz : %s (Wire err %u)\n", static_cast<unsigned long>(hz),
                  err == 0 ? "ACK  <- sensor alive at this speed" : "no ACK", err);
    Wire.end();
    pinMode(sda, INPUT);
    pinMode(scl, INPUT);
  }
}

// Short test: drive one line LOW, read the other. Independent lines each have their own ~10k
// pull-up, so the undriven one stays HIGH; if it follows LOW, the two are bridged (solder short
// at either end of the harness). This is the fault that matches "idles HIGH, times out under
// traffic, never ACKs at any speed".
void shortTest(uint8_t a, uint8_t b, const char *a_name, const char *b_name) {
  Serial.printf("\n--- short test, %s <-> %s ---\n", a_name, b_name);
  for (int dir = 0; dir < 2; dir++) {
    const uint8_t drv = dir == 0 ? a : b, sense = dir == 0 ? b : a;
    const char *dn = dir == 0 ? a_name : b_name, *sn = dir == 0 ? b_name : a_name;
    pinMode(sense, INPUT);
    pinMode(drv, OUTPUT);
    digitalWrite(drv, LOW);
    delay(2);
    const bool follows = digitalRead(sense) == LOW;
    Serial.printf("  drive %s LOW -> %s reads %s %s\n", dn, sn, follows ? "LOW" : "HIGH",
                  follows ? "<- BRIDGED (solder short)" : "(independent, ok)");
    pinMode(drv, INPUT);
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(3000);  // USB CDC needs a moment before the host is listening
  Serial.println("\n=== i2c_scan: XIAO ESP32-S3 bus probe ===");
  idleLevels();
  scanAllPairs();
  shortTest(6, 43, "D5", "D6");
  clockSweep(6, 43, "D5", "D6");   // the wiring initTof() expects
  clockSweep(43, 6, "D6", "D5");   // and swapped, in case the harness crossed them
  Serial.println("\ndone. (reset the board to run again)");
}

void loop() {
  delay(1000);
}
