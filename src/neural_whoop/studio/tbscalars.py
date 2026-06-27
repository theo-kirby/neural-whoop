"""Minimal, dependency-free TensorBoard scalar reader for the Studio.

The Studio extra is intentionally light (FastAPI + uvicorn + pyyaml) — pulling in ``tbparse``
(which drags ``tensorboard`` + ``pandas``) just to draw a few training curves isn't worth it. A
TB event file is a stream of TFRecord-framed ``Event`` protobufs; scalar summaries are a tiny,
stable corner of that wire format, so we walk it by hand here. Validated to match ``tbparse`` value
for value on the project's run logs.

Public surface: :func:`read_scalars` (one event file) and :func:`run_scalars` (find + read the
event file in a run dir, with optional downsampling for transport).
"""

from __future__ import annotations

import struct
from pathlib import Path

#: Per-series point cap returned to the browser (keeps the JSON small; charts don't need more).
_MAX_POINTS = 600


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = out = 0
    while True:
        b = buf[i]
        i += 1
        out |= (b & 0x7F) << shift
        if not b & 0x80:
            return out, i
        shift += 7


def _fields(buf: bytes):
    """Yield ``(field_number, wire_type, value)`` over a protobuf message body.

    ``value`` is an int for varints, or the raw ``bytes`` slice for 64-bit / length-delimited /
    32-bit fields (we only ever need the bytes for those here).
    """
    i, n = 0, len(buf)
    while i < n:
        key, i = _read_varint(buf, i)
        fn, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _read_varint(buf, i)
            yield fn, wt, v
        elif wt == 1:
            yield fn, wt, buf[i : i + 8]
            i += 8
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            yield fn, wt, buf[i : i + ln]
            i += ln
        elif wt == 5:
            yield fn, wt, buf[i : i + 4]
            i += 4
        else:  # groups (3/4) never appear in Event/Summary scalars
            raise ValueError(f"unsupported protobuf wire type {wt}")


def read_scalars(path: str | Path) -> dict[str, list[tuple[int, float]]]:
    """Parse one ``events.out.tfevents.*`` file into ``{tag: [(step, value), ...]}``.

    TFRecord framing per record: ``uint64 len`` · ``uint32 len-crc`` · ``len`` payload bytes ·
    ``uint32 payload-crc``. The payload is an ``Event``; we read its ``step`` (field 2) and
    ``summary`` (field 5), then each ``Summary.Value`` (field 1) for a ``tag`` (field 1) +
    ``simple_value`` (field 2, little-endian float32). CRCs are ignored.
    """
    data = Path(path).read_bytes()
    out: dict[str, list[tuple[int, float]]] = {}
    i, n = 0, len(data)
    while i + 12 <= n:
        (rec_len,) = struct.unpack_from("<Q", data, i)
        i += 12  # length + its CRC
        rec = data[i : i + rec_len]
        i += rec_len + 4  # payload + its CRC
        if len(rec) < rec_len:
            break  # truncated tail (writer still flushing) — stop cleanly
        step = 0
        summary = None
        for fn, wt, val in _fields(rec):
            if fn == 2 and wt == 0:
                step = val
            elif fn == 5 and wt == 2:
                summary = val
        if summary is None:
            continue
        for fn, wt, val in _fields(summary):
            if fn != 1 or wt != 2:
                continue
            tag = simple = None
            for vfn, vwt, vval in _fields(val):
                if vfn == 1 and vwt == 2:
                    tag = vval.decode("utf-8", "replace")
                elif vfn == 2 and vwt == 5:
                    simple = struct.unpack("<f", vval)[0]
            if tag is not None and simple is not None:
                out.setdefault(tag, []).append((step, simple))
    return out


def _downsample(points: list[tuple[int, float]], cap: int) -> list[tuple[int, float]]:
    """Uniformly thin a series to <= ``cap`` points, always keeping the last point."""
    if len(points) <= cap:
        return points
    stride = len(points) / cap
    idxs = {min(len(points) - 1, int(k * stride)) for k in range(cap)}
    idxs.add(len(points) - 1)
    return [points[k] for k in sorted(idxs)]


def run_scalars(run_dir: str | Path, *, cap: int = _MAX_POINTS) -> dict[str, dict[str, list]]:
    """Read the newest event file in ``run_dir`` into chart-ready ``{tag: {steps, values}}``.

    Returns ``{}`` if the dir has no event file. Series are downsampled to ``cap`` points.
    """
    run_dir = Path(run_dir)
    events = sorted(run_dir.glob("events.out.tfevents.*"), key=lambda p: p.stat().st_mtime)
    if not events:
        return {}
    raw = read_scalars(events[-1])
    out: dict[str, dict[str, list]] = {}
    for tag, pts in raw.items():
        pts = _downsample(pts, cap)
        out[tag] = {"steps": [p[0] for p in pts], "values": [p[1] for p in pts]}
    return out
