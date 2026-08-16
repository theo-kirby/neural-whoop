// Last-resort PMW3901 probe: bit-banged SPI mode 3 at ~1 kHz — no SPI peripheral, no timing
// margin questions, nothing between us and the pins. Reads Product_ID (0x00) and
// Inverse_Product_ID (0x5F) forever, printing raw values. A live chip prints 0x49/0xB6 at this
// speed no matter how marginal it is at 2 MHz; steady 0xFF/0x00/noise means no functioning
// chip on the wires, full stop. Pins via -D (defaults = the 2026-08-16 spare-rig transplant).

#include <Arduino.h>

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

static const int kHalfUs = 500;  // ~1 kHz clock

static void clkDelay() { delayMicroseconds(kHalfUs); }

static void writeBit(bool b) {
  digitalWrite(FLOW_SCK_PIN, LOW);  // mode 3: shift on falling
  digitalWrite(FLOW_MOSI_PIN, b);
  clkDelay();
  digitalWrite(FLOW_SCK_PIN, HIGH);  // sample on rising
  clkDelay();
}

static bool readBit() {
  digitalWrite(FLOW_SCK_PIN, LOW);
  clkDelay();
  digitalWrite(FLOW_SCK_PIN, HIGH);
  bool b = digitalRead(FLOW_MISO_PIN);
  clkDelay();
  return b;
}

static uint8_t readReg(uint8_t addr) {
  digitalWrite(FLOW_CS_PIN, LOW);
  delayMicroseconds(100);
  for (int i = 7; i >= 0; i--) writeBit((addr >> i) & 1);  // MSB first, bit7=0 -> read
  delayMicroseconds(200);  // > tSRAD
  uint8_t v = 0;
  for (int i = 7; i >= 0; i--) v |= (uint8_t)readBit() << i;
  delayMicroseconds(100);
  digitalWrite(FLOW_CS_PIN, HIGH);
  return v;
}

static void writeReg(uint8_t addr, uint8_t val) {
  digitalWrite(FLOW_CS_PIN, LOW);
  delayMicroseconds(100);
  for (int i = 7; i >= 0; i--) writeBit(((addr | 0x80) >> i) & 1);
  for (int i = 7; i >= 0; i--) writeBit((val >> i) & 1);
  delayMicroseconds(100);
  digitalWrite(FLOW_CS_PIN, HIGH);
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.printf("=== PMW3901 BIT-BANG probe (~1 kHz) sck=GPIO%d miso=GPIO%d mosi=GPIO%d "
                "cs=GPIO%d ===\n",
                FLOW_SCK_PIN, FLOW_MISO_PIN, FLOW_MOSI_PIN, FLOW_CS_PIN);
  pinMode(FLOW_CS_PIN, OUTPUT);
  digitalWrite(FLOW_CS_PIN, HIGH);
  pinMode(FLOW_SCK_PIN, OUTPUT);
  digitalWrite(FLOW_SCK_PIN, HIGH);  // mode 3 idle
  pinMode(FLOW_MOSI_PIN, OUTPUT);
  pinMode(FLOW_MISO_PIN, INPUT);
  delay(50);
  writeReg(0x3A, 0x5A);  // power-on reset
  delay(10);
}

void loop() {
  uint8_t id = readReg(0x00);
  uint8_t inv = readReg(0x5F);
  Serial.printf("Product_ID 0x%02X (want 0x49)  Inverse 0x%02X (want 0xB6)  %s\n", id, inv,
                (id == 0x49 && inv == 0xB6) ? "<<< ALIVE" : "");
  delay(500);
}
