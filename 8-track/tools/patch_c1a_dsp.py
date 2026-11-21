#!/usr/bin/env python3
"""
patch_c1a_dsp.py — Patch MC-101 Core 1 (RPG69_C1A_up.bin / sdram1.bin) to
output Tracks 5-8 (DSP slots 0x258C..0x2593) alongside Tracks 1-4 (0x2584..0x258B)
for 20-channel USB Audio IN.

Relocates the Mixer/Output DSP program (0x610ADEE8..0x610B59D0) to the end of
sdram1.bin and clones the stock Track 4 L/R output template (0x610B58A4..0x610B58C4)
for Tracks 5-8 (0x258C..0x2593) plus silenced ch 19-20 (0x2C00..0x2C01), then
repacks RPG69_C1A_up.bin into the QSPI container's trailing gap.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from repack_qspi_container import parse_container, repack  # noqa: E402

SDRAM1_BASE = 0x61000000 - 0x20  # 32-byte payload header

DSP_ORIG_START = 0x610ADEE8
DSP_ORIG_END = 0x610B59D0
DSP_INSERT_VA = 0x610B58C4
DSP_LEN_VA = 0x610B59D4
DSP_ORIG_LEN = 0x00007A86

DSP_TEMPLATE_VA = DSP_INSERT_VA - 0x20  # Track 4 L/R (0x258A..0x258B), 32 bytes
# Append Tracks 5-8 (0x258C..0x2593) + 2 unused slots in the 0x25xx page
# (0x25A2..0x25A3, 0 hits across all of idm1.bin and sdram1.bin) for ch 19-20.
EXTRA_SLOT_PAIRS = [
    (0x258C, 0x258D),
    (0x258E, 0x258F),
    (0x2590, 0x2591),
    (0x2592, 0x2593),
    (0x25A2, 0x25A3),
]
TOTAL_INSERT_SIZE = len(EXTRA_SLOT_PAIRS) * 0x20  # 0xA0

PTR_UPDATES = [
    (0x610A3764, 0x610ADEE8, 0),
    (0x610A3EF4, 0x610ADF08, 0),
    (0x610B59DC, 0x610ADF14, 0),
    (0x610B59EC, 0x610B599C, TOTAL_INSERT_SIZE),
    (0x610B59FC, 0x610B59A4, TOTAL_INSERT_SIZE),
    (0x610B5A0C, 0x610B59AC, TOTAL_INSERT_SIZE),
    (0x610B5A1C, 0x610B59B4, TOTAL_INSERT_SIZE),
    (0x610B5A2C, 0x610B59BC, TOTAL_INSERT_SIZE),
]

# Parameter/coefficient offsets (relative to 0x610ADF14) that fall at or after
# DSP_INSERT_VA (0x610B58C4 - 0x610ADF14 = 0x79B0) and must shift by +0x80.
PARAM_OFF_UPDATES = [
    (0x610B5AC4, 0x7A40),
    (0x610B5AC8, 0x7A20),
    (0x610B5AD0, 0x7A4C),
    (0x610B5AD4, 0x7A2C),
    (0x610B5ADC, 0x7A24),
    (0x610B5AE0, 0x7A04),
    (0x610B5AE8, 0x7A32),
    (0x610B5AEC, 0x7A12),
    (0x610B5AF4, 0x79EE),
    (0x610B5AF8, 0x79CE),
    (0x610B5B00, 0x79FA),
    (0x610B5B04, 0x79DA),
    (0x610B5B0C, 0x7A08),
    (0x610B5B10, 0x79E8),
    (0x610B5B18, 0x7A16),
    (0x610B5B1C, 0x79F6),
    (0x610B6028, 0x79BA),
    (0x610B6048, 0x79CA),
    (0x610B63A8, 0x7A60),
    (0x610B63AC, 0x7A40),
]


def u32(buf: bytes | bytearray, va: int) -> int:
    return struct.unpack_from("<I", buf, va - SDRAM1_BASE)[0]


def put_u32(buf: bytearray, va: int, val: int) -> None:
    struct.pack_into("<I", buf, va - SDRAM1_BASE, val)


def build_extra_channels(s101: bytes) -> bytes:
    """Clone Track 4 L/R (0x258A..0x258B) from stock MC-101 sdram1 for EXTRA_SLOT_PAIRS."""
    tpl_off = DSP_TEMPLATE_VA - SDRAM1_BASE
    template = s101[tpl_off : tpl_off + 0x20]
    if len(template) != 0x20:
        raise ValueError("Truncated DSP channel template")
    for idx, expected_slot in ((0, 0x258A), (1, 0x258B)):
        got_slot = struct.unpack_from("<H", template, idx * 16 + 8)[0]
        if got_slot != expected_slot:
            raise ValueError(
                f"Expected stock template slot 0x{expected_slot:04x}, got 0x{got_slot:04x}"
            )
    out = bytearray()
    for slot_l, slot_r in EXTRA_SLOT_PAIRS:
        pair = bytearray(template)
        struct.pack_into("<H", pair, 8, slot_l)
        struct.pack_into("<H", pair, 24, slot_r)
        out.extend(pair)
    return bytes(out)


def patch_sdram1(s101: bytes, c1a_data: bytes) -> bytes:
    buf = bytearray(s101)

    # Verify expected original values
    if u32(buf, DSP_LEN_VA) != DSP_ORIG_LEN:
        raise ValueError(
            f"Unexpected DSP length at 0x{DSP_LEN_VA:08x}: "
            f"0x{u32(buf, DSP_LEN_VA):08x} != 0x{DSP_ORIG_LEN:08x}"
        )
    for ptr_va, expected_target, _ in PTR_UPDATES:
        got = u32(buf, ptr_va)
        if got != expected_target:
            raise ValueError(
                f"Unexpected pointer at 0x{ptr_va:08x}: "
                f"0x{got:08x} != 0x{expected_target:08x}"
            )
    for param_va, expected_off in PARAM_OFF_UPDATES:
        got = u32(buf, param_va)
        if got != expected_off:
            raise ValueError(
                f"Unexpected DSP param offset at 0x{param_va:08x}: "
                f"0x{got:08x} != 0x{expected_off:08x}"
            )

    ins_bytes = build_extra_channels(s101)

    # Preserve the 36 bytes immediately following sdram1.bin in the QSPI
    # container (0x3c6b1c..0x3c6b40 -> VAs 0x61389afc..0x61389b20), which hold
    # scatterload source words 0x61389b14 (0) and 0x61389b18 (0xac44 = 44100 Hz).
    s1_end_in_c1a = 0x3D000 + len(s101)
    post_s1 = c1a_data[s1_end_in_c1a : s1_end_in_c1a + 0x24]
    buf.extend(post_s1)
    if u32(buf, 0x61389B14) != 0 or u32(buf, 0x61389B18) != 0xAC44:
        raise ValueError(
            f"Unexpected scatterload tail: 0x61389b14=0x{u32(buf, 0x61389B14):08x}, "
            f"0x61389b18=0x{u32(buf, 0x61389B18):08x}"
        )

    # Zero-pad up to 0x38a000 (16-byte aligned) before placing relocated DSP program
    if len(buf) > 0x38A000:
        raise ValueError("Unexpected sdram1 size")
    buf.extend(b"\x00" * (0x38A000 - len(buf)))
    new_base = SDRAM1_BASE + len(buf)

    # Build relocated DSP program with 0x258C..0x2593 inserted at DSP_INSERT_VA
    orig_start_off = DSP_ORIG_START - SDRAM1_BASE
    insert_off = DSP_INSERT_VA - SDRAM1_BASE
    orig_end_off = DSP_ORIG_END - SDRAM1_BASE
    relocated = (
        s101[orig_start_off:insert_off]
        + ins_bytes
        + s101[insert_off:orig_end_off]
    )
    buf.extend(relocated)

    # Update length, pointers, and post-insert parameter offsets
    put_u32(buf, DSP_LEN_VA, DSP_ORIG_LEN + TOTAL_INSERT_SIZE)
    for ptr_va, old_target, shift in PTR_UPDATES:
        new_target = new_base + (old_target - DSP_ORIG_START) + shift
        put_u32(buf, ptr_va, new_target)
    for param_va, old_off in PARAM_OFF_UPDATES:
        put_u32(buf, param_va, old_off + TOTAL_INSERT_SIZE)

    return bytes(buf)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--c1a-in",
        type=Path,
        default=REPO_ROOT / "vendor/mc101_sys_v182/RPG69_C1A_up.bin",
    )
    ap.add_argument(
        "--sdram1-101",
        type=Path,
        default=REPO_ROOT / "vendor/mc101_sys_v182/extracts/RPG69_C1A/sdram1.bin",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "build/8-track/out/RPG69_C1A_up.bin",
    )
    args = ap.parse_args()

    c1a_data = args.c1a_in.read_bytes()
    s101 = args.sdram1_101.read_bytes()

    patched_s1 = patch_sdram1(s101, c1a_data)
    delta = len(patched_s1) - len(s101)
    if delta > 0:
        # Trim `delta` zero bytes from the end of the QSPI tail (before CRC32+footer)
        # so the container stays the exact stock size (4194144 bytes).
        out_data = bytearray(repack(c1a_data, {"sdram1.bin": patched_s1}))
        if any(b != 0 for b in out_data[-0x34 - delta : -0x34]):
            raise ValueError("Repacked tail end is not zero-padded")
        del out_data[-0x34 - delta : -0x34]
        struct.pack_into("<I", out_data, 0x00, len(out_data) - 0x30)
        import zlib
        crc = zlib.crc32(bytes(out_data[:-0x34])) & 0xFFFFFFFF
        struct.pack_into("<I", out_data, len(out_data) - 0x34, crc)
        out_data = bytes(out_data)
    else:
        out_data = repack(c1a_data, {"sdram1.bin": patched_s1})
    meta = parse_container(out_data)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(out_data)

    sha = hashlib.sha256(out_data).hexdigest()[:16]
    s1_info = next(f for f in meta["toc"] if f["name"] == "sdram1.bin")
    print(
        f"[OK] Wrote {args.out} ({len(out_data)} bytes, sha256={sha}..., "
        f"sdram1 len=0x{s1_info['length']:x} csum=0x{s1_info['csum']:04x})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
