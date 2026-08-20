// MTF-02P bring-up probe + calibration rig (pio run -e mtf_probe -t upload && pio device
// monitor). No WiFi, no FC — just the sensor's UART into the parser, with everything printed.
// Run this on the BENCH XIAO for first power-up of a new module (the assembled drone XIAO
// never takes probe firmware — it is OTA-only; diagnose that one over the air via the main
// firmware's heartbeat, which carries the same counters).
//
// What it answers, in order:
//   1. Is anything on the wire at all? (bytes/s — 0 means power or harness; the probe
//      alternates its listen pin between MTF_RX_PIN and MTF_TX_PIN every 5 s while silent, so
//      a TX/RX-swapped harness names itself.)
//   2. Is the sensor in MSP mode? (valid frames/s at ~50 each; 0xFD/0xFE bytes = MAVLink mode,
//      0xEF = MicoLink mode — both mean "move the jumper / MicoAssistant setting to MSP".)
//   3. Do range and flow behave? (wave a hand: range tracks; slide over a textured page: the
//      cumulative sums move and flow quality sits high.)
//
// CALIBRATION (the same slide test the PMW3901 rig ran, README "Optical-flow wiring"): rest
// the sensor at a known height over a printed page, send any character to ZERO the sums, slide
// exactly 100 mm, read the totals: rad_per_count = distance / (height * counts). Repeat at a
// second height — the two must agree, or the standoff is wrong. That number is the pilot's
// --rad-per-count, and it has NO default.
#include <Arduino.h>

#include "mtf02.h"

#ifndef MTF_RX_PIN
#define MTF_RX_PIN 6  // XIAO silkscreen D5 (GPIO6)  <- sensor TX
#endif
#ifndef MTF_TX_PIN
#define MTF_TX_PIN 43  // XIAO silkscreen D6 (GPIO43) -> sensor RX (listen-only fallback here)
#endif

namespace {
HardwareSerial mtf_serial(2);
Mtf02 mtf;
int rx_active = MTF_RX_PIN;
uint32_t last_print_ms = 0;
uint32_t last_bytes = 0, last_range_frames = 0, last_flow_frames = 0;
}  // namespace

void setup() {
  Serial.begin(115200);
  delay(2000);  // let USB CDC enumerate so the banner is actually seen
  Serial.printf("mtf_probe: MTF-02P on rx=GPIO%d (alt GPIO%d), MSP mode expected @115200\n",
                MTF_RX_PIN, MTF_TX_PIN);
  Serial.println("any keypress zeroes the flow sums (slide-calibration rig)");
  mtf_serial.setRxBufferSize(1024);
  mtf_serial.begin(115200, SERIAL_8N1, rx_active, /*txPin=*/-1);
}

void loop() {
  mtf.poll(mtf_serial);

  if (Serial.available()) {
    while (Serial.available()) Serial.read();
    mtf.sum_dx = 0;
    mtf.sum_dy = 0;
    Serial.println("--- flow sums ZEROED — slide exactly 100 mm now ---");
  }

  const uint32_t now = millis();
  if (now - last_print_ms < 1000) return;
  const uint32_t dt_s = (now - last_print_ms + 500) / 1000;
  last_print_ms = now;

  const uint32_t bps = (mtf.bytes_rx - last_bytes) / max<uint32_t>(dt_s, 1);
  const uint32_t range_hz = (mtf.frames_range - last_range_frames) / max<uint32_t>(dt_s, 1);
  const uint32_t flow_hz = (mtf.frames_flow - last_flow_frames) / max<uint32_t>(dt_s, 1);
  last_bytes = mtf.bytes_rx;
  last_range_frames = mtf.frames_range;
  last_flow_frames = mtf.frames_flow;

  if (mtf.bytes_rx == 0) {
    // Silent wire: alternate the listen pin every 5th silent second (listen-only — safe).
    static uint8_t silent_s = 0;
    if (++silent_s >= 5) {
      silent_s = 0;
      rx_active = (rx_active == MTF_RX_PIN) ? MTF_TX_PIN : MTF_RX_PIN;
      mtf_serial.end();
      mtf_serial.begin(115200, SERIAL_8N1, rx_active, /*txPin=*/-1);
    }
    Serial.printf("no bytes (listening GPIO%d) — check 5V/GND, or wait for the pin swap\n",
                  rx_active);
    return;
  }
  if (!mtf.everFrame() && (mtf.mav_like > 10 || mtf.mico_like > 10)) {
    Serial.printf("WRONG MODE: %lu MAVLink-like / %lu MicoLink-like bytes, 0 MSP frames — set "
                  "the sensor to MSP (jumper / MicoAssistant)\n",
                  (unsigned long)mtf.mav_like, (unsigned long)mtf.mico_like);
    return;
  }
  if (rx_active != MTF_RX_PIN) {
    Serial.printf("NOTE: live wire is GPIO%d, not GPIO%d — harness TX/RX swapped\n", rx_active,
                  MTF_RX_PIN);
  }
  Serial.printf("rx %lu B/s  range %u Hz  flow %u Hz  crc_fail %lu  |  range %u mm (q %u%s)  |"
                "  sum_dx %ld  sum_dy %ld  (flow q %u)\n",
                (unsigned long)bps, (unsigned)range_hz, (unsigned)flow_hz,
                (unsigned long)mtf.crc_fail, mtf.range_mm, mtf.range_quality,
                mtf.range_ok ? "" : " OUT-OF-RANGE", (long)mtf.sum_dx, (long)mtf.sum_dy,
                mtf.flow_quality);
}
