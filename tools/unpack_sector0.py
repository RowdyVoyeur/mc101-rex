#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""
tools/unpack_sector0.py - Unpack and Decrypt Roland MC-101 Physical Flash Sector 0

Extracts the 4 primary partitions from the 768 KB physical flash dump:
  1. Reset Vectors & Bootstrap Stub (0x000000 - 0x002000, 8 KB)
  2. App0 Stage 1 Primary Bootloader (0x002000 - 0x005F80, 16.25 KB, RPG69_C0L)
  3. App0_UPD Recovery Updater Container (0x040000 - 0x0708F0, 198.9 KB, RPG69_C0U)
  4. IndivCode Serial & Factory Calibration Block (0x0B0000 - 0x0C0000, 64 KB)

Then:
  - Unpacks the App0_UPD update container into header, payload, and trailer.
  - Decrypts App0_UPD.enc using the 3DES key derived from the Silicon Boot ROM (Key Index 0xB5).
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import zlib

# Ensure tools directory is on sys.path for decrypt_c0a imports
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from decrypt_c0a import derive_3des_key, decrypt_firmware, parse_container_header


def parse_and_verify_footer(data: bytes, label: str):
    """
    Parses standard 64-byte Roland update trailer (12B pad, 4B CRC32, 48B string).
    """
    if len(data) < 64:
        return {"valid": False, "error": "Too small"}
    crc_bytes = data[-52:-48]
    expected_crc = struct.unpack('<I', crc_bytes)[0]
    payload_for_crc = data[:-52]
    actual_crc = zlib.crc32(payload_for_crc)
    ident_str = data[-48:].decode('latin1', errors='replace').rstrip('\x00 \r\n')
    return {
        "valid": expected_crc == actual_crc,
        "expected_crc32": f"0x{expected_crc:08X}",
        "actual_crc32": f"0x{actual_crc:08X}",
        "ident_string": ident_str
    }


def unpack_sector0(
    input_path: Path,
    output_dir: Path,
    bootrom_path: Path,
    decrypt: bool = True
):
    print("=" * 76)
    print("ROLAND MC-101 PHYSICAL FLASH SECTOR 0 UNPACKER & DECRYPTOR")
    print("=" * 76)
    print(f"[*] Input Sector 0:  {input_path}")
    print(f"[*] Output Dir:       {output_dir}")
    print(f"[*] Boot ROM:         {bootrom_path}")
    print("-" * 76)

    if not input_path.exists():
        print(f"[!] Error: Sector 0 file not found at {input_path}")
        sys.exit(1)

    with open(input_path, "rb") as f:
        data = f.read()

    total_len = len(data)
    if total_len < 0xC0000:
        print(f"[!] Warning: Dump size is {total_len:,} bytes, expected >= 786,432 bytes (768 KB)")

    output_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Part 1: Reset Vectors & Flash Bootstrap Stub (0x000000 - 0x002000, 8 KB)
    # -------------------------------------------------------------------------
    p1_data = data[0x000000:0x002000]
    p1_path = output_dir / "part1_reset_vectors.bin"
    with open(p1_path, "wb") as f:
        f.write(p1_data)
    p1_sp, p1_reset = struct.unpack("<II", p1_data[:8])
    print(f"[✓] Part 1: Reset Vectors & Bootstrap Stub ({len(p1_data):,} bytes)")
    print(f"    Saved:   {p1_path.name}")
    print(f"    Initial: SP=0x{p1_sp:08X}, ResetHandler=0x{p1_reset:08X}")

    # -------------------------------------------------------------------------
    # Part 2: App0 Stage 1 Primary Bootloader (0x002000 - 0x005F80, 16,256 B)
    # -------------------------------------------------------------------------
    # Magic 'BMC 0.10' at 0x2000, payload length at 0x200C
    bmc_magic = data[0x002000:0x002008]
    p2_payload_len = struct.unpack("<I", data[0x00200C:0x002010])[0]
    p2_end = 0x002010 + p2_payload_len + 64  # include 64-byte footer
    p2_data = data[0x002000:p2_end]
    p2_path = output_dir / "part2_app0_bootloader.bin"
    with open(p2_path, "wb") as f:
        f.write(p2_data)

    p2_footer_info = parse_and_verify_footer(data[0x000000:p2_end], "RPG69_C0L")
    print(f"[✓] Part 2: App0 Primary Bootloader ({len(p2_data):,} bytes)")
    print(f"    Saved:   {p2_path.name}")
    print(f"    Header:  Magic='{bmc_magic.decode('latin1', errors='replace')}', Payload={p2_payload_len:,} bytes")
    print(f"    Footer:  '{p2_footer_info['ident_string']}' (CRC: {p2_footer_info['actual_crc32']}, Valid={p2_footer_info['valid']})")

    # -------------------------------------------------------------------------
    # Part 3: App0_UPD Recovery Updater Container (0x040000 - 0x0708F0, 198,896 B)
    # -------------------------------------------------------------------------
    c_hdr = data[0x040000:0x040060]
    hdr_info = parse_container_header(c_hdr)
    p3_payload_len = hdr_info["payload_len"]
    p3_total_len = 0x60 + p3_payload_len + 64
    p3_data = data[0x040000 : 0x040000 + p3_total_len]
    p3_path = output_dir / "part3_App0_UPD_up.bin"
    with open(p3_path, "wb") as f:
        f.write(p3_data)

    p3_footer_info = parse_and_verify_footer(p3_data, "RPG69_C0U")
    print(f"[✓] Part 3: App0_UPD Update Container ({len(p3_data):,} bytes)")
    print(f"    Saved:   {p3_path.name}")
    print(f"    App:     '{hdr_info['partition_name']}' v{hdr_info['version']} ({hdr_info['timestamp']})")
    print(f"    Footer:  '{p3_footer_info['ident_string']}' (CRC: {p3_footer_info['actual_crc32']}, Valid={p3_footer_info['valid']})")

    # -------------------------------------------------------------------------
    # Part 4: IndivCode Factory Serial & Calibration Block (0x0B0000 - 0x0C0000)
    # -------------------------------------------------------------------------
    p4_data = data[0x0B0000:0x0C0000]
    p4_path = output_dir / "part4_indiv_code.bin"
    with open(p4_path, "wb") as f:
        f.write(p4_data)
    indiv_magic = p4_data[:16].decode("latin1", errors="replace").rstrip("\x00")
    serial_str = p4_data[16:48].decode("latin1", errors="replace").rstrip("\x00 \r\n")
    print(f"[✓] Part 4: IndivCode Calibration & Serial ({len(p4_data):,} bytes)")
    print(f"    Saved:   {p4_path.name}")
    print(f"    Tag:     '{indiv_magic}', Serial='{serial_str}'")

    # -------------------------------------------------------------------------
    # Unpack App0_UPD Container into Subdirectory
    # -------------------------------------------------------------------------
    print("-" * 76)
    print("[*] Unpacking App0_UPD Container...")
    app0_upd_dir = output_dir / "App0_UPD"
    app0_upd_dir.mkdir(parents=True, exist_ok=True)

    upd_header = p3_data[:0x60]
    upd_payload = p3_data[0x60 : 0x60 + p3_payload_len]
    upd_footer = p3_data[0x60 + p3_payload_len :]

    hdr_file = app0_upd_dir / "header.bin"
    enc_file = app0_upd_dir / "App0_UPD.enc"
    ftr_file = app0_upd_dir / "footer.bin"

    with open(hdr_file, "wb") as f: f.write(upd_header)
    with open(enc_file, "wb") as f: f.write(upd_payload)
    with open(ftr_file, "wb") as f: f.write(upd_footer)

    print(f"[✓] Extracted header.bin ({len(upd_header)} bytes)")
    print(f"[✓] Extracted App0_UPD.enc ({len(upd_payload):,} bytes, Encrypted: {hdr_info['encrypted']})")
    print(f"[✓] Extracted footer.bin ({len(upd_footer)} bytes)")

    # -------------------------------------------------------------------------
    # Decrypt App0_UPD.enc
    # -------------------------------------------------------------------------
    dec_file = app0_upd_dir / "App0_UPD_decrypted.bin"
    if decrypt:
        if not bootrom_path.exists():
            print(f"[!] Boot ROM not found at {bootrom_path}; cannot decrypt App0_UPD.")
        else:
            print(f"[*] Decrypting App0_UPD.enc using Boot ROM key table (Index: 0x{hdr_info['key_index']:02X})...")
            key = derive_3des_key(str(bootrom_path), key_idx=hdr_info["key_index"])
            print(f"[*] 3DES Master Key (Slot 0x{hdr_info['key_index']:02X}): {key.hex()}")

            plaintext = decrypt_firmware(upd_payload, key)
            with open(dec_file, "wb") as f:
                f.write(plaintext)

            entry_word = struct.unpack("<I", plaintext[:4])[0]
            sha256 = hashlib.sha256(plaintext).hexdigest()
            print(f"[✓] Decrypted App0_UPD -> {dec_file.name} ({len(plaintext):,} bytes)")
            print(f"[*] CRT0 Entry Point: 0x{entry_word:08X} ({'VALID' if entry_word == 0x680148AE else 'DIFFERENT'})")
            print(f"[*] SHA-256 Checksum: {sha256}")

    # Write Manifest
    manifest = {
        "source": input_path.name,
        "format": "Roland MC-101 Physical Flash Sector 0",
        "partitions": {
            "part1_reset_vectors": {
                "offset": "0x000000",
                "length": len(p1_data),
                "file": p1_path.name
            },
            "part2_app0_bootloader": {
                "offset": "0x002000",
                "length": len(p2_data),
                "file": p2_path.name,
                "magic": "BMC 0.10",
                "footer": p2_footer_info
            },
            "part3_App0_UPD": {
                "offset": "0x040000",
                "length": len(p3_data),
                "file": p3_path.name,
                "header": hdr_info,
                "footer": p3_footer_info,
                "unpacked": {
                    "header": hdr_file.name,
                    "ciphertext": enc_file.name,
                    "decrypted": dec_file.name if dec_file.exists() else None,
                    "footer": ftr_file.name
                }
            },
            "part4_indiv_code": {
                "offset": "0x0B0000",
                "length": len(p4_data),
                "file": p4_path.name,
                "serial_string": serial_str
            }
        }
    }

    with open(output_dir / "manifest.json", "w") as mf:
        json.dump(manifest, mf, indent=2)

    print("=" * 76)
    print(f"[✓] Sector 0 Unpacking & Decryption complete: {output_dir}")
    print("=" * 76)


def main():
    parser = argparse.ArgumentParser(description="Unpack and Decrypt Roland MC-101 Physical Flash Sector 0")
    parser.add_argument("--input", "-i", type=Path,
                        default=Path("vendor/mc101_sys_v182/dumps/physical_sector0_768k.bin"),
                        help="Path to physical Sector 0 dump (default: vendor/mc101_sys_v182/dumps/physical_sector0_768k.bin)")
    parser.add_argument("--output-dir", "-o", type=Path,
                        default=Path("vendor/mc101_sys_v182/extracts/sector0"),
                        help="Output directory (default: vendor/mc101_sys_v182/extracts/sector0)")
    parser.add_argument("--bootrom", "-b", type=Path,
                        default=Path("vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin"),
                        help="Path to dumped Silicon Mask Boot ROM (default: vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin)")
    parser.add_argument("--no-decrypt", action="store_true",
                        help="Skip decryption of App0_UPD.enc")
    args = parser.parse_args()

    unpack_sector0(
        input_path=args.input,
        output_dir=args.output_dir,
        bootrom_path=args.bootrom,
        decrypt=not args.no_decrypt
    )


if __name__ == "__main__":
    main()

