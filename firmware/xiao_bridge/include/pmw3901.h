// PMW3901 optical-flow driver — header-only, Arduino SPI.
//
// The bridge's SECOND sensor (the VL53L1X is the first): a downward-looking optical-flow chip
// that reports frame-to-frame image motion in counts. Counts are NOT velocity — the host turns
// them into one via v = (counts * rad_per_count / dt - omega) * height, which is why the flow
// reply carries raw counts + the bridge's own timestamps and nothing pre-cooked. See
// docs/SIM2REAL.md "Optical flow" and neural_whoop/bench/msp.py::decode_bridge_flow.
//
// PROVENANCE OF THE MAGIC. The power-on reset, the chip-id check, the register read/write
// timings and the 71-write "performance optimisation" sequence below are transcribed VERBATIM
// from Bitcraze's MIT-licensed Arduino driver (bitcraze/Bitcraze_PMW3901,
// src/Bitcraze_PMW3901.cpp). The values are PixArt proprietary and undocumented — the datasheet
// says only "write these in this order" — so they are copied, never derived, and must not be
// "tidied". They are transcribed from the Arduino library rather than from crazyflie-firmware
// because the two disagree in four places (0x74, and three writes on pages 0x14/0x15); this is
// the one that matches the library the breakout vendors themselves point at.
//
// Register map (PMW3901MB datasheet): 0x00 Product_ID (0x49), 0x02 Motion (bit7 = MOT),
// 0x03/0x04 Delta_X lo/hi, 0x05/0x06 Delta_Y lo/hi, 0x07 SQUAL, 0x3A Power_Up_Reset,
// 0x5F Inverse_Product_ID (0xB6). Reading 0x02 LATCHES the delta registers, so the five reads
// must stay in that order and must not be reordered around other traffic.
//
// Blocking cost: registerRead is 50+50+100 us of mandated settling plus SPI, so one
// readMotion() (five reads) is ~1 ms. That is a quarter of the ToF poll and it lands in the
// same place — LAST in loop(), on a bounded cadence, never between an inbound MSP request and
// its forward to the FC. main.cpp times it as its own section (sec_poll_flow).

#pragma once

#include <Arduino.h>
#include <SPI.h>

// Wiring. Overridable in wifi_config.h (same "solder joints live in the config header" rule as
// FC_TX_PIN/FC_RX_PIN), but defaulted here so a wifi_config.h written before the flow sensor
// existed still compiles. D8/D9/D10 are the XIAO ESP32-S3's hardware-SPI trio; D3 is a free
// GPIO (D7/GPIO44 is deliberately avoided — see the pin history in README.md).
#ifndef FLOW_SCK_PIN
#define FLOW_SCK_PIN 7  // XIAO silkscreen D8
#endif
#ifndef FLOW_MISO_PIN
#define FLOW_MISO_PIN 8  // XIAO silkscreen D9
#endif
#ifndef FLOW_MOSI_PIN
#define FLOW_MOSI_PIN 9  // XIAO silkscreen D10
#endif
#ifndef FLOW_CS_PIN
#define FLOW_CS_PIN 4  // XIAO silkscreen D3
#endif

class Pmw3901 {
 public:
  static constexpr uint8_t kChipId = 0x49;
  static constexpr uint8_t kChipIdInverse = 0xB6;

  // Bring the sensor up. Returns false if the chip-id handshake fails (nothing wired, wrong
  // pins, dead board) — the caller treats that exactly like a missing ToF: proxy on regardless.
  bool begin(uint8_t cs = FLOW_CS_PIN, int8_t sck = FLOW_SCK_PIN, int8_t miso = FLOW_MISO_PIN,
             int8_t mosi = FLOW_MOSI_PIN) {
    cs_ = cs;
    SPI.begin(sck, miso, mosi, cs);
    pinMode(cs_, OUTPUT);

    // Reset the SPI port (CS high/low/high with the bus idle) before talking.
    SPI.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE3));
    digitalWrite(cs_, HIGH);
    delay(1);
    digitalWrite(cs_, LOW);
    delay(1);
    digitalWrite(cs_, HIGH);
    delay(1);
    SPI.endTransaction();

    registerWrite(0x3A, 0x5A);  // power-on reset
    delay(5);
    chip_id_ = registerRead(0x00);
    chip_id_inv_ = registerRead(0x5F);
    if (chip_id_ != kChipId || chip_id_inv_ != kChipIdInverse) return false;

    // Clear the motion registers once so the first real read is not a boot-time accumulation.
    registerRead(0x02);
    registerRead(0x03);
    registerRead(0x04);
    registerRead(0x05);
    registerRead(0x06);
    delay(1);

    initRegisters();
    ok_ = true;
    return true;
  }

  bool ok() const { return ok_; }
  uint8_t chipId() const { return chip_id_; }
  uint8_t chipIdInverse() const { return chip_id_inv_; }

  // Latch and read one motion sample. `motion` is the Motion register's MOT bit (data since the
  // last read); `squal` is surface quality — low on a featureless surface, which is the honest
  // "this reading means nothing" signal a white desk produces.
  void readMotion(int16_t* dx, int16_t* dy, uint8_t* squal, bool* motion) {
    const uint8_t mot = registerRead(0x02);  // latches Delta_X/Delta_Y — must come first
    const uint8_t xl = registerRead(0x03);
    const uint8_t xh = registerRead(0x04);
    const uint8_t yl = registerRead(0x05);
    const uint8_t yh = registerRead(0x06);
    *dx = static_cast<int16_t>((static_cast<uint16_t>(xh) << 8) | xl);
    *dy = static_cast<int16_t>((static_cast<uint16_t>(yh) << 8) | yl);
    *motion = (mot & 0x80) != 0;
    *squal = registerRead(0x07);
  }

  void registerWrite(uint8_t reg, uint8_t value) {
    reg |= 0x80u;  // MSB set = write
    SPI.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE3));
    digitalWrite(cs_, LOW);
    delayMicroseconds(50);
    SPI.transfer(reg);
    SPI.transfer(value);
    delayMicroseconds(50);
    digitalWrite(cs_, HIGH);
    SPI.endTransaction();
    delayMicroseconds(200);
  }

  uint8_t registerRead(uint8_t reg) {
    reg &= ~0x80u;  // MSB clear = read
    SPI.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE3));
    digitalWrite(cs_, LOW);
    delayMicroseconds(50);
    SPI.transfer(reg);
    delayMicroseconds(50);
    const uint8_t value = SPI.transfer(0);
    delayMicroseconds(100);
    digitalWrite(cs_, HIGH);
    SPI.endTransaction();
    return value;
  }

 private:
  static constexpr uint32_t kSpiHz = 2000000;  // datasheet ceiling for this part

  // PixArt's undocumented power-up optimisation sequence. Copied verbatim; do not reorder, do
  // not deduplicate the repeated page selects (0x7F is the page register — the repeats ARE the
  // semantics), do not drop the 100 ms delay in the middle.
  void initRegisters() {
    static const uint8_t kInit[][2] = {
        {0x7F, 0x00}, {0x61, 0xAD}, {0x7F, 0x03}, {0x40, 0x00}, {0x7F, 0x05}, {0x41, 0xB3},
        {0x43, 0xF1}, {0x45, 0x14}, {0x5B, 0x32}, {0x5F, 0x34}, {0x7B, 0x08}, {0x7F, 0x06},
        {0x44, 0x1B}, {0x40, 0xBF}, {0x4E, 0x3F}, {0x7F, 0x08}, {0x65, 0x20}, {0x6A, 0x18},
        {0x7F, 0x09}, {0x4F, 0xAF}, {0x5F, 0x40}, {0x48, 0x80}, {0x49, 0x80}, {0x57, 0x77},
        {0x60, 0x78}, {0x61, 0x78}, {0x62, 0x08}, {0x63, 0x50}, {0x7F, 0x0A}, {0x45, 0x60},
        {0x7F, 0x00}, {0x4D, 0x11}, {0x55, 0x80}, {0x74, 0x1F}, {0x75, 0x1F}, {0x4A, 0x78},
        {0x4B, 0x78}, {0x44, 0x08}, {0x45, 0x50}, {0x64, 0xFF}, {0x65, 0x1F}, {0x7F, 0x14},
        {0x65, 0x60}, {0x66, 0x08}, {0x63, 0x78}, {0x7F, 0x15}, {0x48, 0x58}, {0x7F, 0x07},
        {0x41, 0x0D}, {0x43, 0x14}, {0x4B, 0x0E}, {0x45, 0x0F}, {0x44, 0x42}, {0x4C, 0x80},
        {0x7F, 0x10}, {0x5B, 0x02}, {0x7F, 0x07}, {0x40, 0x41}, {0x70, 0x00},
    };
    static const uint8_t kInitTail[][2] = {
        {0x32, 0x44}, {0x7F, 0x07}, {0x40, 0x40}, {0x7F, 0x06}, {0x62, 0xF0}, {0x63, 0x00},
        {0x7F, 0x0D}, {0x48, 0xC0}, {0x6F, 0xD5}, {0x7F, 0x00}, {0x5B, 0xA0}, {0x4E, 0xA8},
        {0x5A, 0x50}, {0x40, 0x80},
    };
    for (auto& rv : kInit) registerWrite(rv[0], rv[1]);
    delay(100);  // mandated settle between the two halves
    for (auto& rv : kInitTail) registerWrite(rv[0], rv[1]);
  }

  uint8_t cs_ = FLOW_CS_PIN;
  bool ok_ = false;
  uint8_t chip_id_ = 0, chip_id_inv_ = 0;
};
