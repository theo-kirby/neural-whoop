// Multimeter-paced wire test: proves each flow net end-to-end with nothing but DC volts.
// The espnow build's chip-id probe already exonerates pin *ordering*; what it can't see is a
// broken wire or a cold joint. This toggles one configured flow net at a time at 1 Hz —
// meter black probe on GND, red probe on the BREAKOUT pad for that net, and a good wire
// flips ~0 <-> ~3.3 V once a second. Any serial input advances to the next net; the cycle
// repeats forever. No WiFi, no FC, no sensor driver.
//
// FLOW_CS is held HIGH (deasserted) while other nets toggle, so the PMW3901 keeps its MISO
// hi-Z and driving the MISO net from this side is safe.

#include <Arduino.h>

#include "wifi_config.h"

struct Net {
  int gpio;
  const char* label;
};

// MOS first: the toggle phase starts there straight from boot, so the test keeps running on
// power alone even when the (flaky) USB link drops mid-measurement.
static const Net NETS[] = {
    {FLOW_MOSI_PIN, "flow MOS"},
    {FLOW_CS_PIN, "flow CS"},
    {FLOW_SCK_PIN, "flow CLK"},
    {FLOW_MISO_PIN, "flow MIS"},
};
static const int N_NETS = sizeof(NETS) / sizeof(NETS[0]);

// XIAO ESP32-S3 silkscreen for a GPIO (same map as the wifi_config.h header comment).
static const char* silk(int gpio) {
  switch (gpio) {
    case 1: return "D0"; case 2: return "D1"; case 3: return "D2"; case 4: return "D3";
    case 5: return "D4"; case 6: return "D5"; case 43: return "D6"; case 44: return "D7";
    case 7: return "D8"; case 8: return "D9"; case 9: return "D10";
    default: return "?";
  }
}

static void idleAll() {
  for (int i = 0; i < N_NETS; i++) pinMode(NETS[i].gpio, INPUT);
  // CS deasserted-high whenever it isn't itself under test.
  pinMode(FLOW_CS_PIN, OUTPUT);
  digitalWrite(FLOW_CS_PIN, HIGH);
}

// Phase-1 short scan, no meter needed. Every flow net lands on a high-impedance sensor pin
// (MISO stays hi-Z while CS is deasserted), so under our internal pulls (~45 k) a healthy
// net FOLLOWS the pull. A net reading HIGH under pulldown is bridged to a high source (the
// 3V3 rail, or a net we're driving high); LOW under pullup is bridged to GND. Then a
// pairwise pass: drive each net and see whether any *other* net follows it.
static int readWithPull(int gpio, int pull) {
  pinMode(gpio, pull);
  delayMicroseconds(200);
  int v = digitalRead(gpio);
  pinMode(gpio, INPUT);
  return v;
}

static void shortScan() {
  Serial.println("--- short scan: each net under internal pullup/pulldown ---");
  for (int i = 0; i < N_NETS; i++) {
    for (int j = 0; j < N_NETS; j++) pinMode(NETS[j].gpio, INPUT);
    int up = readWithPull(NETS[i].gpio, INPUT_PULLUP);
    int dn = readWithPull(NETS[i].gpio, INPUT_PULLDOWN);
    const char* verdict = (up == 1 && dn == 0) ? "floats (GOOD: follows the pull)"
                          : (up == 1 && dn == 1) ? "TIED HIGH — bridged to 3V3/rail?"
                          : (up == 0 && dn == 0) ? "TIED LOW — bridged to GND?"
                                                 : "erratic";
    Serial.printf("%-8s %-3s (GPIO%d): pullup=%d pulldown=%d -> %s\n", NETS[i].label,
                  silk(NETS[i].gpio), NETS[i].gpio, up, dn, verdict);
  }
  Serial.println("--- pairwise: drive each net, do the others follow? ---");
  for (int a = 0; a < N_NETS; a++) {
    for (int j = 0; j < N_NETS; j++) pinMode(NETS[j].gpio, INPUT);
    pinMode(NETS[a].gpio, OUTPUT);
    for (int level = 0; level <= 1; level++) {
      digitalWrite(NETS[a].gpio, level);
      delayMicroseconds(200);
      for (int b = 0; b < N_NETS; b++) {
        if (b == a) continue;
        // Pull the observed net the OPPOSITE way; if it still follows the driven net,
        // they're bridged.
        int v = readWithPull(NETS[b].gpio, level ? INPUT_PULLDOWN : INPUT_PULLUP);
        if (v == level)
          Serial.printf("BRIDGE? %s follows %s (driven %s)\n", NETS[b].label, NETS[a].label,
                        level ? "HIGH" : "LOW");
      }
    }
    pinMode(NETS[a].gpio, INPUT);
  }
  // A "TIED HIGH" net can be a solder bridge to 3V3 (fault) or an onboard pull-up resistor
  // on the breakout (fine — proves the wire!). Discriminate by sinking briefly: a resistor
  // loses to the pin driver instantly; a hard bridge holds the pin high. ~50 us into a worst
  // -case dead short is far inside the pad's survivable region.
  Serial.println("--- hard/soft: sink each net LOW for 50 us and read it back ---");
  for (int i = 0; i < N_NETS; i++) {
    for (int j = 0; j < N_NETS; j++) pinMode(NETS[j].gpio, INPUT);
    pinMode(NETS[i].gpio, OUTPUT_OPEN_DRAIN);
    digitalWrite(NETS[i].gpio, LOW);
    delayMicroseconds(50);
    int v = digitalRead(NETS[i].gpio);
    digitalWrite(NETS[i].gpio, HIGH);
    pinMode(NETS[i].gpio, INPUT);
    Serial.printf("%-8s %-3s (GPIO%d): sinks to %s -> %s\n", NETS[i].label,
                  silk(NETS[i].gpio), NETS[i].gpio, v ? "HIGH" : "LOW",
                  v ? "HARD TIE — real bridge to 3V3"
                    : "soft pull-up — wire GOOD, resistor on the breakout");
  }
  Serial.println("--- short scan done ---");
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("wire_test: short scan, then 1 Hz toggle per net (any key -> next net)");
  shortScan();
}

void loop() {
  for (int i = 0; i < N_NETS; i++) {
    idleAll();
    const Net& n = NETS[i];
    Serial.printf("=== %s: %s (GPIO%d) toggling — meter on the breakout's %s pad ===\n",
                  n.label, silk(n.gpio), n.gpio, n.label);
    pinMode(n.gpio, OUTPUT);
    while (Serial.available()) Serial.read();
    bool level = false;
    while (!Serial.available()) {
      level = !level;
      digitalWrite(n.gpio, level);
      Serial.printf("%s %s -> %s (expect ~%s at the pad)\n", n.label, silk(n.gpio),
                    level ? "HIGH" : "LOW", level ? "3.3 V" : "0 V");
      delay(1000);
    }
    while (Serial.available()) Serial.read();
  }
}
