#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""
Roland MC-101 / Zen-Core Firmware Update Unpacker & Inspector
Unpacks Roland RPG69_*.bin update container files into extracted subdirectories.
"""

import argparse
import json
import os
from pathlib import Path
import struct
import sys
import zlib


def verify_and_parse_footer(data: bytes, filename: str):
    """
    Parses the standard 52-byte Roland update trailer:
    - 4-byte CRC-32 (IEEE 802.3) covering all bytes up to -0x34
    - 48-byte ASCII identification and build string
    """
    if len(data) < 0x34:
        raise ValueError(f"{filename}: File too small for Roland update footer")

    payload_for_crc = data[:-0x34]
    expected_crc = struct.unpack('<I', data[-0x34:-0x30])[0]
    actual_crc = zlib.crc32(payload_for_crc)

    footer_str = data[-0x30:].decode('latin1', errors='replace').rstrip('\x00 \r\n')
    crc_ok = (expected_crc == actual_crc)

    return {
        "footer_string": footer_str,
        "expected_crc32": f"0x{expected_crc:08x}",
        "actual_crc32": f"0x{actual_crc:08x}",
        "crc_valid": crc_ok
    }


def unpack_qspi_container(bin_path: Path, out_dir: Path):
    """
    Unpacks a Roland QSPI filesystem image container.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(bin_path, 'rb') as f:
        data = f.read()

    footer_info = verify_and_parse_footer(data, bin_path.name)
    assert footer_info["crc_valid"], f"CRC mismatch in {bin_path.name}"

    magic = data[0x20:0x24]
    if magic != b'QSPI':
        raise ValueError(f"{bin_path.name}: Expected magic 'QSPI', found {magic}")

    # Header is 16 bytes at 0x20..0x30: magic (4), u1 (4), entry_size (4), num_files (4)
    # TOC entries begin immediately at 0x30
    entry_size, num_files = struct.unpack('<II', data[0x28:0x30])
    toc_start = 0x30

    files_manifest = []

    for i in range(num_files):
        entry_bytes = data[toc_start + i * entry_size : toc_start + (i + 1) * entry_size]
        raw_name = entry_bytes[:16].split(b'\x00')[0].decode('latin1')
        offset, length, csum, reserved = struct.unpack('<IIII', entry_bytes[16:32])

        file_payload = data[offset : offset + length]

        # Determine reconstructed name if truncated by 16-byte fixed buffer
        clean_name = raw_name
        if len(raw_name) == 16:
            if clean_name.endswith('.bi'):
                clean_name += 'n'
            elif clean_name.endswith('.b'):
                clean_name += 'in'
            elif clean_name.endswith('.'):
                clean_name += 'bin'
            elif '.' not in clean_name:
                clean_name += '.bin'

        target_file = out_dir / clean_name
        with open(target_file, 'wb') as out_f:
            out_f.write(file_payload)

        files_manifest.append({
            "index": i,
            "raw_name": raw_name,
            "clean_name": clean_name,
            "offset": f"0x{offset:08x}",
            "offset_dec": offset,
            "size_bytes": length,
            "checksum_field": f"0x{csum:04x}",
            "extracted_path": str(target_file.name)
        })

    manifest = {
        "container_filename": bin_path.name,
        "format": "Roland QSPI Filesystem Container",
        "footer": footer_info,
        "toc": {
            "num_files": num_files,
            "entry_size": entry_size,
            "files": files_manifest
        }
    }

    with open(out_dir / "manifest.json", 'w') as mf:
        json.dump(manifest, mf, indent=2)

    print(f"[✓] Unpacked QSPI container {bin_path.name} ({num_files} files) -> {out_dir}")
    return manifest


def unpack_c0a_container(bin_path: Path, out_dir: Path):
    """
    Unpacks Roland C0A container (App1_Main encrypted application binary).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(bin_path, 'rb') as f:
        data = f.read()

    footer_info = verify_and_parse_footer(data, bin_path.name)
    assert footer_info["crc_valid"], f"CRC mismatch in {bin_path.name}"

    hdr = data[:0x60]
    app_name = hdr[:16].split(b'\x00')[0].decode('latin1')
    build_time = hdr[16:32].split(b'\x00')[0].decode('latin1')
    version = hdr[32:40].split(b'\x00')[0].decode('latin1')
    flash_base = struct.unpack('<I', hdr[0x28:0x2c])[0]
    entry_point = struct.unpack('<I', hdr[0x30:0x34])[0]
    payload_len = struct.unpack('<I', hdr[0x44:0x48])[0]

    payload = data[0x60 : 0x60 + payload_len]
    trailer = data[0x60 + payload_len :]

    with open(out_dir / "header.bin", 'wb') as f: f.write(hdr)
    with open(out_dir / f"{app_name}.enc", 'wb') as f: f.write(payload)
    with open(out_dir / "footer.bin", 'wb') as f: f.write(trailer)

    manifest = {
        "container_filename": bin_path.name,
        "format": "Roland App1 Executable Container (Encrypted ECB-mode 64-bit Block Cipher)",
        "header": {
            "app_name": app_name,
            "build_timestamp": build_time,
            "version": version,
            "flash_base": f"0x{flash_base:08x}",
            "entry_point": f"0x{entry_point:08x}",
            "payload_len_bytes": payload_len
        },
        "footer": footer_info,
        "extracted_files": [
            "header.bin",
            f"{app_name}.enc",
            "footer.bin"
        ]
    }

    with open(out_dir / "manifest.json", 'w') as mf:
        json.dump(manifest, mf, indent=2)

    print(f"[✓] Unpacked App1 container {bin_path.name} -> {out_dir}")
    return manifest


def unpack_container(bin_path: Path, out_dir: Path):
    with open(bin_path, 'rb') as f:
        header = f.read(0x40)

    if len(header) >= 0x24 and header[0x20:0x24] == b'QSPI':
        return unpack_qspi_container(bin_path, out_dir)
    else:
        return unpack_c0a_container(bin_path, out_dir)


def main():
    parser = argparse.ArgumentParser(description="Unpack Roland MC-101 Firmware Update Containers (*.bin)")
    parser.add_argument("--input-dir", "-i", type=Path, default=Path("vendor/mc101_sys_v182"),
                        help="Directory containing Roland update .bin files (default: vendor/mc101_sys_v182)")
    parser.add_argument("--output-dir", "-o", type=Path, default=Path("vendor/mc101_sys_v182/extracts"),
                        help="Target directory for extracted subdirectories (default: vendor/mc101_sys_v182/extracts)")
    parser.add_argument("--file", "-f", type=Path, default=None,
                        help="Unpack a single specific update binary file")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.file is not None:
        target_files = [args.file]
    else:
        if not args.input_dir.exists():
            print(f"[!] Input directory not found: {args.input_dir}")
            sys.exit(1)
        # Find all direct *.bin files in input_dir (excluding subdirectories like dumps/ or extracts/)
        target_files = sorted([
            p for p in args.input_dir.iterdir()
            if p.is_file() and p.name.endswith(".bin") and not p.name.startswith(".")
        ])

    if not target_files:
        print(f"[!] No .bin files found in {args.input_dir}")
        sys.exit(1)

    print("=" * 76)
    print("ROLAND MC-101 FIRMWARE UPDATE UNPACKER")
    print("=" * 76)
    print(f"[*] Input:  {args.input_dir if args.file is None else args.file}")
    print(f"[*] Output: {args.output_dir}")
    print(f"[*] Found {len(target_files)} update binary file(s):")
    for f in target_files:
        print(f"    - {f.name} ({f.stat().st_size:,} bytes)")
    print("-" * 76)

    for bin_path in target_files:
        sub_name = bin_path.stem[:-3] if bin_path.stem.endswith('_up') else bin_path.stem
        sub_dir = args.output_dir / sub_name
        unpack_container(bin_path, sub_dir)

    print("=" * 76)
    print(f"[✓] All firmware containers successfully extracted to: {args.output_dir}")
    print("=" * 76)


if __name__ == "__main__":
    main()
