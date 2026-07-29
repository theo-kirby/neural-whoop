// FC UART wiring probe (pio run -e uart_scan): finds which XIAO pins the flight controller's
// MSP UART is actually wired to, by asking the FC for its API version on each candidate pair
// and watching for a real '$M>' reply. The UART counterpart of i2c_scan.
//
// REQUIRES THE FLIGHT BATTERY IN (props off). The FC must be powered to answer, and pass 1
// depends on it driving its TX pad.
//
// Two passes:
//
//   1. Idle-level pass. Every candidate pin is read as a plain INPUT, pull-ups OFF. An idle
//      UART line held by a *powered* FC sits HIGH, so pins reading HIGH are the ones something
//      is actively driving — i.e. candidates for the FC's TX pad landing on our RX. If NOTHING
//      reads HIGH, the FC's TX is not reaching the XIAO at all (broken wire, or the wires are
//      on pads belonging to a different UART) and no pin permutation will fix it.
//   2. Probe pass. For each (tx, rx) candidate, send MSP_API_VERSION and hex-dump whatever
//      comes back. A reply beginning '$M>' means that pair is the wiring — put it in
//      wifi_config.h as FC_TX_PIN / FC_RX_PIN.
//
// Deliberately conservative about what it drives: only pins that pass 1 found *undriven* are
// used as TX, so the probe never fights an FC output. D5/D6 are skipped (the ToF I2C bus).

#include <Arduino.h>

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

void idleLevels() {
  Serial.println("\n--- pass 1: idle levels (pull-ups OFF, battery must be IN) ---");
  Serial.println("HIGH = something is driving this pin => candidate for the FC's TX pad.");
  Serial.println("LOW/unstable = nothing driving it.\n");
  for (size_t i = 0; i < kNumPins; i++) pinMode(kPins[i].gpio, INPUT);
  delay(10);
  int driven_count = 0;
  for (size_t i = 0; i < kNumPins; i++) {
    int high = 0;
    for (int s = 0; s < 8; s++) {
      high += digitalRead(kPins[i].gpio) == HIGH ? 1 : 0;
      delay(1);
    }
    driven[i] = (high == 8);
    const char *verdict = high == 8 ? "HIGH (driven)" : (high == 0 ? "LOW" : "unstable/floating");
    Serial.printf("  %-3s GPIO%-2u : %s\n", kPins[i].name, kPins[i].gpio, verdict);
    if (driven[i]) driven_count++;
  }
  if (driven_count == 0) {
    Serial.println("\n  !! No pin is being driven. With the battery IN, the FC's TX pad should hold");
    Serial.println("     its line HIGH. So the FC->XIAO wire is open, or it is soldered to a pad on");
    Serial.println("     a different UART than the one Betaflight has set to MSP. Check continuity");
    Serial.println("     from the FC's T1 pad to the XIAO pin, and confirm you are on UART1's pads.");
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
  for (size_t r = 0; r < kNumPins; r++) {
    if (!driven[r]) continue;  // only pins the FC appears to be driving can be our RX
    for (size_t t = 0; t < kNumPins; t++) {
      if (t == r || driven[t]) continue;
      tried++;
      if (probePair(kPins[t].gpio, kPins[r].gpio, kPins[t].name, kPins[r].name)) hits++;
    }
  }
  Serial.printf("\n  %d pair(s) tried, %d MSP reply(ies).\n", tried, hits);
  if (tried == 0) {
    Serial.println("  Nothing to try: pass 1 found no driven pin. Fix the FC->XIAO wire first.");
  } else if (hits == 0) {
    Serial.println("  A pin is driven but the FC never answered MSP. That means the FC->XIAO");
    Serial.println("  direction is probably fine and the XIAO->FC direction is not: the FC never");
    Serial.println("  hears the request. Check the XIAO TX wire into the FC's R1 pad, and that");
    Serial.println("  Betaflight's MSP port really is the UART those pads belong to.");
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
