"""Stage-0 bench tooling: talk to the real flight controller over USB (docs/SIM2REAL.md).

Pure-stdlib MSP v1 codec (unit-tested without hardware) + a thin pyserial client. The serial
dependency is the ``bench`` extra and is imported lazily, so the codec stays core-importable.
"""

from neural_whoop.bench.msp import (  # noqa: F401
    MSP_ANALOG,
    MSP_API_VERSION,
    MSP_ATTITUDE,
    MSP_FC_VARIANT,
    MSP_FC_VERSION,
    MSP_MOTOR,
    MSP_RAW_IMU,
    MSP_RC,
    MSP_SET_MOTOR,
    MSP_SET_RAW_RC,
    MSP_STATUS,
    MspClient,
    MspError,
    MspParser,
    MspTimeout,
    decode_analog,
    decode_attitude,
    decode_fc_version,
    decode_raw_imu,
    decode_u16s,
    encode_msp_v1,
    pack_rc_channels,
)
