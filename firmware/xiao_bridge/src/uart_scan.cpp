// FC UART wiring probe (pio run -e uart_scan): finds which XIAO pins the flight controller's
// MSP UART is actually wired to, by asking the FC for its API version on each candidate pair
// and watching for a real '$M>' reply. The UART counterpart of i2c_scan.
//
// REQUIRES THE FLIGHT BATTERY IN (props off). The FC must be powered to answer, and pass 1
// depends on it driving its TX pad.
//
// Two passes:
//
//   1. Idle-level pass, read two ways. A plain INPUT reading is NOT enough: some pins carry a
//      ROM pull-up (GPIO44/D7 is the native UART0 RX and reads HIGH on a bare board, with no FC
//      attached at all — it fooled the first version of this tool). So each pin is also read
//      with INPUT_PULLDOWN: the internal pull-down is ~45k, which a real push-pull UART driver
//      wins easily, while an internal pull-up loses. HIGH *against the pull-down* is the honest
//      "something external is driving this" signal. If nothing survives that test, the FC's TX
//      is not reaching the XIAO (open wire, or wires on a different UART's pads) and no pin
//      permutation will fix it.
//   2. Probe pass. Send MSP_API_VERSION on each candidate (tx, rx) and hex-dump the answer. A
//      reply beginning '$M>' names the wiring for FC_TX_PIN / FC_RX_PIN. The pair configured in
//      wifi_config.h is ALWAYS probed, even if pass 1 thinks its RX is idle — pass 1 is a
//      heuristic and must not be able to veto the documented wiring.
//
// Deliberately conservative about what it drives: only pins pass 1 found undriven are used as
// TX, so the probe never fights an FC output. D5/D6 are skipped (the ToF I2C bus).

#include <Arduino.h>

#include "wifi_config.h"

namespace {

struct Pin {
  uint8_t gpio;
  const char *name;
};

// XIAO ESP32-S3 broken-out pins, minus D5/D6 (ToF I2C).
constexpr Pin kPins[] = {
    {1, "D0"}, {2, "D1"}, {3, "D2"},  {4, "D3"}, {5, "D4"},
    {44, "D7"}, {7, "D8"}, {8, "D9"}, {9, "D10"},
};
constexpr size_t kNumPins = sizeof(kPins) / sizeof(kPins[0]);

constexpr uint32_t kBaud = 115200;
constexpr uint32_t kReplyWaitMs = 200;

bool driven[kNumPins];  // pass 1 result: pin is held HIGH by something external

HardwareSerial probe(1);

// MSP v1 request for MSP_API_VERSION (cmd 1, no payload): '$','M','<',len,cmd,checksum.
void sendApiVersionRequest() {
  const uint8_t cmd = 1, len = 0;
  const uint8_t frame[6] = {'$', 'M', '<', len, cmd, static_cast<uint8_t>(len ^ cmd)};
  probe.write(frame, sizeof(frame));
  probe.flush();
}

// Sample a pin under a given input mode; returns how many of 8 reads were HIGH.
int sampleHigh(uint8_t gpio, uint8_t mode) {
  pinMode(gpio, mode);
  delay(2);
  int high = 0;
  for (int s = 0; s < 8; s++) {
    high += digitalRead(gpio) == HIGH ? 1 : 0;
    delay(1);
  }
  return high;
}

void idleLevels() {
  Serial.println("\n--- pass 1: idle levels (battery must be IN) ---");
  Serial.println("Each pin read twice: floating, then against the ~45k internal pull-down.");
  Serial.println("Staying HIGH against the pull-down = really driven by the FC.");
  Serial.println("HIGH floating but LOW pulled down = only an internal pull-up (e.g. GPIO44).\n");
  int driven_count = 0;
  for (size_t i = 0; i < kNumPins; i++) {
    const int floatHigh = sampleHigh(kPins[i].gpio, INPUT);
    const int pdHigh = sampleHigh(kPins[i].gpio, INPUT_PULLDOWN);
    const int puHigh = sampleHigh(kPins[i].gpio, INPUT_PULLUP);
    pinMode(kPins[i].gpio, INPUT);
    driven[i] = (pdHigh == 8);
    const char *verdict;
    if (pdHigh == 8) {
      verdict = "DRIVEN high (external)";
    } else if (puHigh == 0) {
      // The internal pull-up cannot even lift the pin. Either the line is held low by something
      // low-impedance (a real driver, or a short to GND), or this pin's input buffer is dead --
      // which is exactly D7/GPIO44's documented failure on this unit. Not distinguishable from
      // inside the chip; move the wire to a known-good pin to tell them apart.
      verdict = "STUCK LOW even with pull-up -- shorted to GND, driven low, or DEAD INPUT";
    } else if (puHigh == 8 && floatHigh == 0) {
      verdict = "open (pull-up lifts it; nothing connected/driving)";
    } else if (floatHigh == 8) {
      verdict = "internal pull-up only -- NOT connected";
    } else {
      verdict = "unstable/floating";
    }
    Serial.printf("  %-3s GPIO%-2u : float=%d/8 pulldown=%d/8 pullup=%d/8  %s\n", kPins[i].name,
                  kPins[i].gpio, floatHigh, pdHigh, puHigh, verdict);
    if (driven[i]) driven_count++;
  }
  if (driven_count == 0) {
    Serial.println("\n  !! Nothing is externally driven. With the battery IN and its UART set to");
    Serial.println("     MSP, the FC's TX pad idles HIGH and should hold a connected pin high even");
    Serial.println("     against the pull-down. So the FC->XIAO wire is open, shorted to GND, or");
    Serial.println("     soldered to a pad on a different UART. Check continuity from the FC's T1");
    Serial.println("     pad to the XIAO pin, and confirm those pads really are UART1's.");
    Serial.printf("     (The configured pair from wifi_config.h -- TX=GPIO%d RX=GPIO%d -- is still\n",
                  FC_TX_PIN, FC_RX_PIN);
    Serial.println("      probed below regardless, in case the line is driven but sitting low.)");
  }
}

// Try one (tx, rx) pair; return true if the FC answered with an MSP reply header.
bool probePair(uint8_t tx, uint8_t rx, const char *tx_name, const char *rx_name) {
  probe.begin(kBaud, SERIAL_8N1, rx, tx);
  delay(20);
  while (probe.available()) probe.read();  // drain boot noise
  sendApiVersionRequest();

  uint8_t buf[64];
  size_t n = 0;
  const uint32_t deadline = millis() + kReplyWaitMs;
  while (millis() < deadline && n < sizeof(buf)) {
    if (probe.available()) buf[n++] = probe.read();
  }
  probe.end();
  pinMode(tx, INPUT);
  pinMode(rx, INPUT);

  if (n == 0) return false;

  Serial.printf("  TX=%-3s RX=%-3s : %u bytes:", tx_name, rx_name, static_cast<unsigned>(n));
  for (size_t i = 0; i < n && i < 16; i++) Serial.printf(" %02X", buf[i]);
  const bool msp = n >= 3 && buf[0] == '$' && buf[1] == 'M' && buf[2] == '>';
  Serial.println(msp ? "   <== MSP REPLY! this is the wiring" : "   (bytes, but not an MSP reply)");
  return msp;
}

void probeAllPairs() {
  Serial.println("\n--- pass 2: MSP probe over plausible pin pairs ---");
  Serial.println("RX candidates = pins pass 1 saw driven; TX candidates = pins it saw undriven");
  Serial.println("(so we never drive into an FC output).\n");
  int hits = 0, tried = 0;

  // The documented wiring first, unconditionally: pass 1 is a heuristic and must not be able to
  // veto the pair the bridge actually ships with.
  Serial.printf("  [configured pair from wifi_config.h] TX=GPIO%d RX=GPIO%d\n", FC_TX_PIN, FC_RX_PIN);
  tried++;
  if (probePair(FC_TX_PIN, FC_RX_PIN, "cfgTX", "cfgRX")) hits++;

  for (size_t r = 0; r < kNumPins; r++) {
    if (!driven[r]) continue;  // only pins the FC appears to be driving can be our RX
    for (size_t t = 0; t < kNumPins; t++) {
      if (t == r || driven[t]) continue;
      if (kPins[t].gpio == FC_TX_PIN && kPins[r].gpio == FC_RX_PIN) continue;  // already done
      tried++;
      if (probePair(kPins[t].gpio, kPins[r].gpio, kPins[t].name, kPins[r].name)) hits++;
    }
  }
  Serial.printf("\n  %d pair(s) tried, %d MSP reply(ies).\n", tried, hits);
  if (hits == 0) {
    bool any_driven = false;
    for (size_t i = 0; i < kNumPins; i++) any_driven |= driven[i];
    if (!any_driven) {
      // The common case, and the one to trust: nothing external is driving any pin, so the
      // inbound wire is the fault. Do NOT blame the outbound direction here -- with no inbound
      // link there is no evidence either way about whether the FC hears us.
      Serial.println("  No MSP reply, and pass 1 found nothing externally driven. The fault is the");
      Serial.println("  FC->XIAO direction: that wire is open, shorted, or on the wrong pad. The");
      Serial.println("  XIAO->FC direction is UNTESTED -- a reply needs both, so nothing here says");
      Serial.println("  anything about it. Fix the inbound wire, re-run, and this will tell you.");
    } else {
      Serial.println("  A pin is externally driven but no MSP reply came back. Inbound looks alive,");
      Serial.println("  so suspect the XIAO->FC wire into the FC's R1 pad, or that Betaflight's MSP");
      Serial.println("  port is not the UART those pads belong to.");
    }
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(3000);  // USB CDC needs a moment before the host is listening
  Serial.println("\n=== uart_scan: which pins is the FC's MSP UART on? ===");
  Serial.println("(flight battery IN, props OFF)");
  idleLevels();
  probeAllPairs();
  Serial.println("\ndone. (reset the board to run again)");
}

void loop() {
  delay(1000);
}
