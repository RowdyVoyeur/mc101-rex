#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""
repack_qspi_container.py — Rebuild a Roland QSPI filesystem update container
(e.g. RPG69_C1A_up.bin: idm1.bin + sdram1.bin) from extracted payloads.

Byte layout (derived from, and round-trip-verified against, the stock
RPG69_C1A_up.bin; see unpack_roland_update.py for the reader):

    0x000000  u32 header word 0 = len(container) - 0x30, rest of 0x20 prefix zero
    0x000020  'QSPI' magic, u32 0x20, u32 entry_size (32), u32 num_files
    0x000030  num_files x 32-byte TOC entries:
              char name[16]; u32 offset; u32 length; u16 checksum; u16 0; u32 reserved
    payload  at TOC offsets; gap bytes between/after payloads are preserved verbatim
    len-0x34  u32 CRC-32 (IEEE) over bytes [0, len-0x34)
    len-0x30  0x30-byte footer string

Per-file checksum field (verified on stock MC-101 Core 1):
    sum16le = sum of little-endian 16-bit words over the region
              [offset(file_i), offset(file_{i+1})) for every file, and
              [offset(last), len-0x34) for the last file.
    (Zero-filled gaps contribute nothing, so the field equals the payload-only
    sum on the stock image; the region form is what reproduces both stock
    checksums exactly: idm1 0x348c, sdram1 0x1dbd.)

Usage:
  Round-trip self-test (no payloads given — rebuilds from the container's own
  extracted bytes and requires byte-identical output):
      python3 repack_qspi_container.py --verify vendor/.../RPG69_C1A_up.bin

  Build a patched container:
      python3 repack_qspi_container.py --out OUT.bin \
          --file idm1.bin=new.bin [IN.bin]
  Payload sizes may grow; growth consumes the trailing gap region (the tail
  gap of the stock MC-101 C1A is 234,512 B). All other regions (prefix, TOC,
  inter-file gaps, tail-structure bytes after the last payload) are copied
  verbatim; header word 0, checksum fields and footer CRC-32 are recomputed.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path


def sum16le(b: bytes) -> int:
    if len(b) % 2:
        raise ValueError("sum16le requires an even-length region, got %d" % len(b))
    return sum(struct.unpack("<%dH" % (len(b) // 2), b)) & 0xFFFF


def parse_container(data: bytes) -> dict:
    if data[0x20:0x24] != b"QSPI":
        raise ValueError("no QSPI magic at 0x20")
    entry_size, num_files = struct.unpack("<II", data[0x28:0x30])
    if entry_size != 32:
        raise ValueError("unexpected TOC entry size %d" % entry_size)
    toc: list[dict] = []
    for i in range(num_files):
        e = data[0x30 + i * 32: 0x30 + (i + 1) * 32]
        name = e[:16].split(b"\x00")[0].decode("latin1")
        offset, length, csum, _lo, _hi = struct.unpack("<IIHHI", e[16:32])
        toc.append({"name": name, "offset": offset, "length": length,
                    "csum": csum, "entry": e})
    offsets = sorted(f["offset"] for f in toc)
    for f in toc:
        nxt = offsets[offsets.index(f["offset"]) + 1] if offsets.index(f["offset"]) + 1 < len(offsets) else len(data) - 0x34
        f["region_end"] = nxt
        region = data[f["offset"]:nxt]
        if sum16le(region) != f["csum"]:
            raise ValueError("%s: region sum16le 0x%04x != TOC 0x%04x"
                             % (f["name"], sum16le(region), f["csum"]))
    crc_at = struct.unpack("<I", data[-0x34:-0x30])[0]
    crc_calc = zlib.crc32(data[:-0x34])
    if crc_at != crc_calc:
        raise ValueError("footer CRC 0x%08x != computed 0x%08x" % (crc_at, crc_calc))
    return {"toc": toc, "footer": data[-0x30:]}


def repack(data: bytes, replacements: dict[str, bytes]) -> bytes:
    meta = parse_container(data)
    toc = meta["toc"]
    payloads = {f["name"]: data[f["offset"]:f["offset"] + f["length"]] for f in toc}
    for name, blob in replacements.items():
        if name not in payloads:
            raise ValueError("no TOC entry named %r (have: %s)"
                             % (name, ", ".join(sorted(payloads))))
        payloads[name] = blob

    ps = sorted(toc, key=lambda f: f["offset"])
    n = len(ps)
    # gaps[i] = bytes between end of payload i-1 (or TOC end, for i=0) and
    # offset of payload i; tail = bytes from end of last payload to len-0x34.
    gaps: list[bytes] = []
    prev = 0x30 + 32 * n
    for f in ps:
        gaps.append(data[prev:f["offset"]])
        prev = f["offset"] + f["length"]
    tail = data[prev:len(data) - 0x34]
    for g in gaps + [tail]:
        if len(g) % 2:
            raise ValueError("odd-length gap region cannot carry sum16le")

    # Assembled layout: [0,0x30) verbatim, new TOC, gap0, p0, gap1, p1, ...,
    # gapN-1, pN-1, tail, CRC32, footer string. Payload i lands at
    # new_offset_i = old_offset_i + accumulated delta of preceding payloads;
    # grow/shrink of a payload consumes/returns the gap that follows it (the
    # tail for the last payload), all preserved verbatim.
    out = bytearray(data[:0x30])
    new_toc = bytearray()
    delta = 0
    for i, f in enumerate(ps):
        blob = payloads[f["name"]]
        gap_after = gaps[i + 1] if i + 1 < n else tail
        csum = (sum16le(blob) + sum16le(gap_after)) & 0xFFFF
        entry = bytearray(f["entry"])
        struct.pack_into("<IIHHI", entry, 16, f["offset"] + delta, len(blob), csum, 0, 0)
        new_toc += entry
        delta += len(blob) - f["length"]
    out += new_toc
    for i, f in enumerate(ps):
        out += gaps[i]
        out += payloads[f["name"]]
    out += tail
    # Header word 0 = len(container) - 0x30; the CRC covers it, so set it
    # before computing (final length = body so far + 4-byte CRC + 0x30 footer).
    struct.pack_into("<I", out, 0x00, len(out) + 0x34 - 0x30)
    out += struct.pack("<I", zlib.crc32(bytes(out)) & 0xFFFFFFFF)
    out += meta["footer"]
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("container", type=Path)
    ap.add_argument("--file", action="append", default=[],
                    metavar="NAME=PATH", help="replace TOC file NAME with bytes from PATH")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--verify", action="store_true",
                    help="round-trip: rebuild from the container's own payloads, "
                         "require byte-identical output, write nothing")
    args = ap.parse_args()

    data = args.container.read_bytes()
    if args.verify:
        rt = repack(data, {})
        if rt == data:
            print("[+] Round-trip byte-identical (%d bytes, CRC 0x%08X)"
                  % (len(rt), struct.unpack('<I', rt[-0x34:-0x30])[0]))
            return 0
        for i in range(min(len(rt), len(data))):
            if rt[i] != data[i]:
                print("[-] first byte diff at 0x%X: %02X vs %02X" % (i, rt[i], data[i]))
                break
        else:
            print("[-] length differs: %d vs %d" % (len(rt), len(data)))
        return 1

    repl = {}
    for spec in args.file:
        name, _, path = spec.partition("=")
        repl[name] = Path(path).read_bytes()
    if not repl:
        ap.error("no --file replacements given (use --verify for the round-trip test)")
    out = repack(data, repl)
    if args.out is None:
        ap.error("--out required when replacing files")
    args.out.write_bytes(out)
    print("[+] Wrote %s (%d bytes, CRC 0x%08X)"
          % (args.out, len(out), struct.unpack('<I', out[-0x34:-0x30])[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
