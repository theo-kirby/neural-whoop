// MicoAir MTF-02P driver: one downward module carrying BOTH bridge sensors (ToF rangefinder +
// optical flow), replacing the VL53L1X + PMW3901 pair (2026-08-20; the PMW3901 breakout was
// convicted dead by three independent implementations, and the MTF-02P's ToF reaches 6 m where
// the VL53L1X trusted ~1.3 m).
//
// The sensor is a UART TALKER, not a polled peripheral: in MSP mode it pushes unsolicited
// MSP v2 frames at 115200 8N1, 50 Hz —
//   * MSP2_SENSOR_RANGEFINDER (0x1F01): u8 quality, i32 distance_mm (negative = out of range)
//   * MSP2_SENSOR_OPTIC_FLOW  (0x1F02): u8 quality, i32 motionX, i32 motionY
// (the INAV "MSP sensor" upstream messages — the module is built to plug into an INAV FC, and
// we impersonate one). Flow units are deliberately uncalibrated in this protocol — INAV applies
// an opflow scale, and we apply the measured `--rad-per-count` exactly as with the PMW3901, so
// the host-side seam is unchanged: counts accumulate here, the host differences and scales.
//
// This class is a pure incremental parser over a Stream: feed() never blocks, poll() drains
// whatever bytes the UART FIFO holds (a bounded amount per call), and all state is "latest
// sample + cumulative sums" — the same shape main.cpp kept for the two old sensors, so the
// MSP_BRIDGE_TOF / MSP_BRIDGE_FLOW replies stay byte-identical to the host.
//
// MSP v2 framing (both directions look the same on the wire):
//   '$' 'X' dir(u8) flag(u8) function(u16 LE) payload_size(u16 LE) payload crc8_dvb_s2
// where the CRC runs from `flag` through the last payload byte. The sensor sends dir '<'
// (it is the requester pushing at an FC); we accept '<' and '>' alike.
#pragma once

#include <Arduino.h>

class Mtf02 {
 public:
  // ---- rangefinder (latest sample) ----
  bool range_ok = false;      // latest sample was in range (distance >= 0)
  uint16_t range_mm = 0xFFFF; // latest range, mm (0xFFFF = never / out of range)
  uint8_t range_quality = 0;  // sensor's own 0-255 confidence for the latest sample
  uint32_t range_ms = 0;      // millis() of the latest RANGEFINDER frame (0 = never)

  // ---- optical flow (cumulative — the host differences two replies) ----
  int32_t sum_dx = 0;         // running motionX sum since boot (wraps; host uses wrap_delta)
  int32_t sum_dy = 0;         // running motionY sum since boot
  uint16_t n_frames = 0;      // cumulative flow-frame count (wraps; diagnostic)
  uint8_t flow_quality = 0;   // latest flow quality (the squal-equivalent: low = bad surface)
  uint8_t flow_motion = 0;    // 1 if the latest frame carried nonzero motion
  uint32_t flow_ms = 0;       // millis() of the latest OPTIC_FLOW frame (0 = never)

  // ---- link diagnostics (what the heartbeat prints when something is wrong) ----
  uint32_t bytes_rx = 0;      // every byte seen on the UART, parsed or not
  uint32_t frames_range = 0;  // valid RANGEFINDER frames
  uint32_t frames_flow = 0;   // valid OPTIC_FLOW frames
  uint32_t frames_other = 0;  // valid MSP v2 frames with any other function id
  uint32_t crc_fail = 0;      // frames that failed the checksum
  uint32_t mav_like = 0;      // 0xFD/0xFE seen while hunting a header: MAVLink-mode signature
  uint32_t mico_like = 0;     // 0xEF seen while hunting a header: MicoLink-mode signature

  // Newest frame of either kind — "is the sensor alive at all".
  uint32_t lastFrameMs() const { return max(range_ms, flow_ms); }
  bool everFrame() const { return lastFrameMs() != 0; }
  bool alive(uint32_t now_ms, uint32_t fresh_ms = 1000) const {
    return everFrame() && now_ms - lastFrameMs() < fresh_ms;
  }

  // Drain the UART FIFO. Bounded per call so a flood (wrong baud spewing garbage) cannot
  // stretch one loop() pass: 115200 baud is ~12 bytes/ms and the bridge loops well under a
  // millisecond, so 256 is comfortably more than a loop's worth of arrivals.
  void poll(Stream& s) {
    for (int i = 0; i < 256; i++) {
      const int c = s.read();
      if (c < 0) return;
      feed(static_cast<uint8_t>(c));
    }
  }

  void feed(uint8_t b) {
    bytes_rx++;
    switch (st_) {
      case St::kDollar:
        if (b == '$') {
          st_ = St::kX;
        } else if (b == 0xFD || b == 0xFE) {
          mav_like++;  // sensor jumper/config left in MAVLink mode
        } else if (b == 0xEF) {
          mico_like++;  // sensor left in MicoLink mode
        }
        break;
      case St::kX:
        st_ = (b == 'X') ? St::kDir : St::kDollar;
        break;
      case St::kDir:
        st_ = (b == '<' || b == '>') ? St::kFlag : St::kDollar;
        break;
      case St::kFlag:
        crc_ = crc8(0, b);
        st_ = St::kFuncLo;
        break;
      case St::kFuncLo:
        func_ = b;
        crc_ = crc8(crc_, b);
        st_ = St::kFuncHi;
        break;
      case St::kFuncHi:
        func_ |= static_cast<uint16_t>(b) << 8;
        crc_ = crc8(crc_, b);
        st_ = St::kSizeLo;
        break;
      case St::kSizeLo:
        size_ = b;
        crc_ = crc8(crc_, b);
        st_ = St::kSizeHi;
        break;
      case St::kSizeHi:
        size_ |= static_cast<uint16_t>(b) << 8;
        crc_ = crc8(crc_, b);
        pay_i_ = 0;
        // Oversize payloads are consumed byte-for-byte (kept in CRC, not stored) so an unknown
        // frame can't desync the stream; only the first kMaxPayload bytes are retained.
        st_ = (size_ == 0) ? St::kCrc : St::kPayload;
        break;
      case St::kPayload:
        if (pay_i_ < kMaxPayload) pay_[pay_i_] = b;
        pay_i_++;
        crc_ = crc8(crc_, b);
        if (pay_i_ >= size_) st_ = St::kCrc;
        break;
      case St::kCrc:
        if (b == crc_) {
          handleFrame();
        } else {
          crc_fail++;
        }
        st_ = St::kDollar;
        break;
    }
  }

 private:
  static constexpr uint16_t kMaxPayload = 32;  // real frames are 5 (range) and 9 (flow) bytes
  static constexpr uint16_t kFuncRangefinder = 0x1F01;
  static constexpr uint16_t kFuncOpticFlow = 0x1F02;

  enum class St : uint8_t { kDollar, kX, kDir, kFlag, kFuncLo, kFuncHi, kSizeLo, kSizeHi,
                            kPayload, kCrc };
  St st_ = St::kDollar;
  uint16_t func_ = 0, size_ = 0, pay_i_ = 0;
  uint8_t crc_ = 0;
  uint8_t pay_[kMaxPayload];

  static uint8_t crc8(uint8_t crc, uint8_t b) {  // crc8_dvb_s2, MSP v2's checksum
    crc ^= b;
    for (int i = 0; i < 8; i++) crc = (crc & 0x80) ? (crc << 1) ^ 0xD5 : (crc << 1);
    return crc;
  }

  static int32_t i32le(const uint8_t* p) {
    return static_cast<int32_t>(static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
                                (static_cast<uint32_t>(p[2]) << 16) |
                                (static_cast<uint32_t>(p[3]) << 24));
  }

  void handleFrame() {
    if (func_ == kFuncRangefinder && size_ >= 5) {
      frames_range++;
      range_quality = pay_[0];
      const int32_t mm = i32le(pay_ + 1);
      // Negative = the sensor's own "out of range" flag. The sample still stamps range_ms (the
      // sensor is alive and answered); range_ok is what gates the value, exactly like the
      // VL53L1X's range_status did.
      range_ok = mm >= 0;
      range_mm = range_ok ? static_cast<uint16_t>(min<int32_t>(mm, 0xFFFE)) : 0xFFFF;
      range_ms = millis();
    } else if (func_ == kFuncOpticFlow && size_ >= 9) {
      frames_flow++;
      flow_quality = pay_[0];
      const int32_t mx = i32le(pay_ + 1);
      const int32_t my = i32le(pay_ + 5);
      sum_dx += mx;  // cumulative by design — see the MSP_BRIDGE_FLOW note in main.cpp
      sum_dy += my;
      flow_motion = (mx != 0 || my != 0) ? 1 : 0;
      n_frames++;
      flow_ms = millis();
    } else {
      frames_other++;
    }
  }
};
