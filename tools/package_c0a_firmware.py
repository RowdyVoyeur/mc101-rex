#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""
package_c0a_firmware.py — Roland MC-101 Core 0 Container Packaging Tool

Packages a given Core 0 binary payload (encrypted or unencrypted) into the
official Roland RPG69_C0A_up.bin update container format, or verifies an
existing container.

Format Structure:
- 96-byte Header (App1_Main metadata, SDRAM target addresses, control word)
- Payload body (raw machine code or encrypted blocks)
- 64-byte Footer (12-byte zero padding, 4-byte IEEE 802.3 CRC-32, 48-byte ASCII tag)
"""

import sys
import struct
import zlib
import argparse
from pathlib import Path

# ==============================================================================
# CONFIGURATION VARIABLES - ROLAND RPG69_C0A CONTAINER SPECIFICATION
# ==============================================================================
# All parameters are defined here at module top for transparency, documentation,
# and easy editing. No magic numbers/strings are embedded inline.

# --- Header Fields (Offset 0x00..0x60 = 96 Bytes) ---

# Application / Module Identity
APP_NAME_STRING = "App1_Main"
# Target module name, fixed 16-byte field (0x00..0x0F), null-padded

BUILD_TIMESTAMP_STRING = "2023/05/17 22:54"
# Firmware build timestamp, 16-byte ASCII field (0x10..0x1F)

VERSION_STRING = "0.010001"
# Internal module firmware version string, 8-byte ASCII field (0x20..0x27)

# Memory Map & Destination Offsets
# Note: 0x60000000..0x61FFFFFF is 32 MB External SDRAM. App0 reads the payload
# from QSPI0 Flash (offset 0x000C0060) and loads/decrypts it into SDRAM.
SDRAM_TARGET_BASE = 0x60000000
# Target SDRAM base address (0x28..0x2B)

HEADER_RESERVED_WORD_0x2C = 0x00000000
# Reserved 32-bit word at offset 0x2C..0x2F

ENTRY_POINT_OFFSET = 0x000C0040
# Execution entry point / vector table offset within Flash partition (0x30..0x33)

HEADER_PADDING_BYTES_0x34 = b"\xFF" * 12
# 12 bytes of reserved padding (0xFF) at offset 0x34..0x3F

PAYLOAD_FLASH_OFFSET = 0x000C0060
# Payload body start offset in QSPI0 Flash (0x40..0x43)

DESTINATION_BASE_ADDRESS = 0x60000000
# Execution / load destination base address in SDRAM (0x48..0x4B)

HEADER_RESERVED_WORD_0x4C = 0x00000000
# Reserved 32-bit word at offset 0x4C..0x4F

# Integrity and Crypto Control Words
# Word 20 at offset 0x50..0x53: IEEE 802.3 CRC-32 of the decrypted / loaded SDRAM payload.
# Checked by App0 (0x01000524) via Hardware CRC32 peripheral (0x40105000) before booting.
# For stock Core 0 firmware, CRC-32 is 0x513FC2D9.

# Word 21 at offset 0x54..0x57: Architecture & Bootloader Crypto Execution Flags
# - CONTROL_WORD_ENCRYPTED (0xB6020001):
#     Stock Roland encrypted mode. Bit 0=1 instructs App0 and Boot ROM to initialize
#     the hardware 3DES cipher engine using key slot 0xB6.
# - CONTROL_WORD_NO_DECRYPTION (0x00000000):
#     Unencrypted / plaintext mode. Bit 0=0 instructs App0 (0x010005F6) and Boot ROM
#     (0x01200280) to bypass cipher decryption entirely and DMA-load plaintext code directly into SDRAM.
CONTROL_WORD_ENCRYPTED = 0xB6020001
CONTROL_WORD_NO_DECRYPTION = 0x00000000

# Active control word used when not explicitly overridden via CLI:
DEFAULT_CONTROL_WORD = CONTROL_WORD_NO_DECRYPTION

HEADER_TERMINATOR_WORD_0x58 = 0x00000000
# Reserved / terminator word at offset 0x58..0x5B

HEADER_TERMINATOR_WORD_0x5C = 0xFFFFFFFF
# Terminator word at offset 0x5C..0x5F

# --- Footer / Trailer Fields (Offset -0x40..0x00 = 64 Bytes) ---

FOOTER_PREFIX_ZERO_PADDING = b"\x00" * 12
# 12 null bytes preceding the CRC-32 trailer (offset 0x00..0x0B of footer)

# Note: Offset 0x0C..0x0F of footer (len - 0x34) is the dynamically calculated
# IEEE 802.3 CRC-32 checksum covering all preceding bytes of the container.
# Verified by the Hardware CRC32 peripheral (0x40105000) via function 0x6004F46C.

FOOTER_BUILD_TAG_STRING = "Roland RPG69_C0AVER.1.82-BLD.14423 0517 22 54 58"
# 48-byte ASCII identification and build string at the end of the update container (len - 0x30)

# ==============================================================================
# CONTAINER BUILDER FUNCTIONS
# ==============================================================================

def build_header(payload_len: int, control_word: int, payload_crc: int) -> bytes:
    """
    Constructs the 96-byte Roland App1 container header.
    All fields are populated using configured variables.
    """
    hdr = bytearray(96)

    # 0x00..0x0F: Target module name (16 bytes, null-padded)
    app_bytes = APP_NAME_STRING.encode("latin1")
    if len(app_bytes) > 16:
        raise ValueError(f"APP_NAME_STRING exceeds 16 bytes: {APP_NAME_STRING}")
    hdr[0x00 : len(app_bytes)] = app_bytes

    # 0x10..0x1F: Build timestamp string (16 bytes, null-padded)
    ts_bytes = BUILD_TIMESTAMP_STRING.encode("latin1")
    if len(ts_bytes) > 16:
        raise ValueError(f"BUILD_TIMESTAMP_STRING exceeds 16 bytes: {BUILD_TIMESTAMP_STRING}")
    hdr[0x10 : 0x10 + len(ts_bytes)] = ts_bytes

    # 0x20..0x27: Version string (8 bytes, null-padded)
    ver_bytes = VERSION_STRING.encode("latin1")
    if len(ver_bytes) > 8:
        raise ValueError(f"VERSION_STRING exceeds 8 bytes: {VERSION_STRING}")
    hdr[0x20 : 0x20 + len(ver_bytes)] = ver_bytes

    # 0x28..0x2B: Target SDRAM base address
    struct.pack_into("<I", hdr, 0x28, SDRAM_TARGET_BASE)

    # 0x2C..0x2F: Reserved word
    struct.pack_into("<I", hdr, 0x2C, HEADER_RESERVED_WORD_0x2C)

    # 0x30..0x33: Entry point / vector table offset
    struct.pack_into("<I", hdr, 0x30, ENTRY_POINT_OFFSET)

    # 0x34..0x3F: Reserved padding bytes
    if len(HEADER_PADDING_BYTES_0x34) != 12:
        raise ValueError(f"HEADER_PADDING_BYTES_0x34 must be 12 bytes, got {len(HEADER_PADDING_BYTES_0x34)}")
    hdr[0x34:0x40] = HEADER_PADDING_BYTES_0x34

    # 0x40..0x43: Payload flash body offset
    struct.pack_into("<I", hdr, 0x40, PAYLOAD_FLASH_OFFSET)

    # 0x44..0x47: Dynamic payload length in bytes
    struct.pack_into("<I", hdr, 0x44, payload_len)

    # 0x48..0x4B: Execution / load destination base address
    struct.pack_into("<I", hdr, 0x48, DESTINATION_BASE_ADDRESS)

    # 0x4C..0x4F: Reserved word
    struct.pack_into("<I", hdr, 0x4C, HEADER_RESERVED_WORD_0x4C)

    # 0x50..0x53: Word 20 integrity token (CRC-32 of loaded SDRAM payload)
    struct.pack_into("<I", hdr, 0x50, payload_crc)

    # 0x54..0x57: Word 21 bootloader control & cipher flags
    struct.pack_into("<I", hdr, 0x54, control_word)

    # 0x58..0x5B: Terminator word 0x58
    struct.pack_into("<I", hdr, 0x58, HEADER_TERMINATOR_WORD_0x58)

    # 0x5C..0x5F: Terminator word 0x5C
    struct.pack_into("<I", hdr, 0x5C, HEADER_TERMINATOR_WORD_0x5C)

    return bytes(hdr)


def build_footer(crc32_val: int) -> bytes:
    """
    Constructs the 64-byte Roland update trailer footer:
    - 12 null bytes padding (0x00..0x0B)
    - 4-byte IEEE 802.3 CRC-32 (0x0C..0x0F)
    - 48-byte ASCII model / build string (0x10..0x3F)
    """
    ftr = bytearray(64)

    # 0x00..0x0B: Prefix null padding
    if len(FOOTER_PREFIX_ZERO_PADDING) != 12:
        raise ValueError("FOOTER_PREFIX_ZERO_PADDING must be 12 bytes")
    ftr[0x00:0x0C] = FOOTER_PREFIX_ZERO_PADDING

    # 0x0C..0x0F: Little-endian CRC-32
    struct.pack_into("<I", ftr, 0x0C, crc32_val)

    # 0x10..0x3F: 48-byte identification string
    tag_bytes = FOOTER_BUILD_TAG_STRING.encode("latin1")
    if len(tag_bytes) > 48:
        raise ValueError(f"FOOTER_BUILD_TAG_STRING exceeds 48 bytes ({len(tag_bytes)} bytes)")
    ftr[0x10 : 0x10 + len(tag_bytes)] = tag_bytes

    return bytes(ftr)


def package_firmware(payload: bytes, control_word: int) -> bytes:
    """
    Packages a raw binary payload into a complete Roland RPG69_C0A update container.
    Calculates dynamic payload CRC-32 (Word 20) and IEEE 802.3 CRC-32 trailer.
    """
    payload_len = len(payload)
    payload_crc = zlib.crc32(payload) & 0xFFFFFFFF
    hdr = build_header(payload_len, control_word, payload_crc)

    # The IEEE 802.3 CRC-32 covers all preceding container bytes:
    # 96-byte header + payload + 12-byte footer prefix padding
    data_for_crc = hdr + payload + FOOTER_PREFIX_ZERO_PADDING
    crc32_val = zlib.crc32(data_for_crc) & 0xFFFFFFFF

    ftr = build_footer(crc32_val)
    container = hdr + payload + ftr

    return container


def verify_container(container_path: Path) -> bool:
    """
    Verifies an existing container's header, footer, and IEEE 802.3 CRC-32 checksum.
    """
    if not container_path.exists():
        print(f"[-] File not found: {container_path}", file=sys.stderr)
        return False

    data = container_path.read_bytes()
    if len(data) < 160:  # 96-byte header + 64-byte footer
        print(f"[-] File too small to be a valid container ({len(data)} bytes)", file=sys.stderr)
        return False

    hdr = data[:96]
    ftr = data[-64:]
    app_name = hdr[0x00:0x10].rstrip(b"\x00").decode("latin1", errors="replace")
    build_ts = hdr[0x10:0x20].rstrip(b"\x00").decode("latin1", errors="replace")
    version = hdr[0x20:0x28].rstrip(b"\x00").decode("latin1", errors="replace")
    sdram_base = struct.unpack("<I", hdr[0x28:0x2C])[0]
    entry_pt = struct.unpack("<I", hdr[0x30:0x34])[0]
    payload_off = struct.unpack("<I", hdr[0x40:0x44])[0]
    payload_len = struct.unpack("<I", hdr[0x44:0x48])[0]
    dest_base = struct.unpack("<I", hdr[0x48:0x4C])[0]
    token = struct.unpack("<I", hdr[0x50:0x54])[0]
    ctrl_word = struct.unpack("<I", hdr[0x54:0x58])[0]

    stored_crc = struct.unpack("<I", ftr[0x0C:0x10])[0]
    tag_str = ftr[0x10:0x40].rstrip(b"\x00").decode("latin1", errors="replace")

    calc_crc = zlib.crc32(data[:-52]) & 0xFFFFFFFF
    crc_ok = (stored_crc == calc_crc)

    print(f"[*] Container Verification: {container_path}")
    print(f"    - Total Size: {len(data):,} bytes")
    print(f"    - Module Name: '{app_name}'")
    print(f"    - Build Timestamp: '{build_ts}'")
    print(f"    - Version: '{version}'")
    print(f"    - SDRAM Base: 0x{sdram_base:08X}, Dest Base: 0x{dest_base:08X}")
    print(f"    - Entry Point Offset: 0x{entry_pt:08X}")
    print(f"    - Payload Flash Offset: 0x{payload_off:08X}")
    print(f"    - Payload Length in Header: {payload_len:,} bytes (actual: {len(data) - 160:,} bytes)")
    print(f"    - Word 20 Token: 0x{token:08X}")
    decrypt_flag = ctrl_word & 1
    swap_flag = (ctrl_word >> 4) & 0x0F
    mode_flag = (ctrl_word >> 8) & 0xFF
    key_idx = (ctrl_word >> 16) & 0xFF
    print(f"    - Word 21 Control Word: 0x{ctrl_word:08X} (Decrypt={decrypt_flag}, KeyIdx={key_idx}, Mode={mode_flag}, Swap={swap_flag})")
    print(f"    - Build Tag: '{tag_str}'")
    print(f"    - Stored CRC-32: 0x{stored_crc:08X}")
    print(f"    - Calculated CRC-32: 0x{calc_crc:08X}")
    print(f"    - CRC-32 Status: {'[+] VALID' if crc_ok else '[-] INVALID / MISMATCH'}")

    return crc_ok


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Package a binary payload into a Roland RPG69_C0A_up.bin update container, or verify an existing one."
    )
    parser.add_argument(
        "payload",
        nargs="?",
        default="vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin",
        help="Path to input payload binary (default: vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin)"
    )
    parser.add_argument(
        "-o", "--output",
        default="build/RPG69_C0A_up.bin",
        help="Path for output container file (default: build/RPG69_C0A_up.bin)"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--encrypted",
        action="store_true",
        help="Use stock encrypted header control word (0xB6020001)"
    )
    group.add_argument(
        "--no-decryption",
        action="store_true",
        help="Use no-decryption / unencrypted header control word (0x06020000)"
    )
    parser.add_argument(
        "--control-word",
        type=lambda x: int(x, 0),
        help="Explicitly specify 32-bit control word (e.g. 0xB6020001, 0x06020000)"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify the header, footer, and CRC-32 of the file passed as payload"
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    if args.verify:
        ok = verify_container(Path(args.payload))
        sys.exit(0 if ok else 1)

    payload_path = Path(args.payload)
    if not payload_path.exists():
        print(f"[-] Error: Payload file not found: {payload_path}", file=sys.stderr)
        sys.exit(1)

    payload_data = payload_path.read_bytes()
    print(f"[*] Input payload: {payload_path} ({len(payload_data):,} bytes)")

    # Determine control word
    if args.control_word is not None:
        control_word = args.control_word
        mode_str = f"Custom (0x{control_word:08X})"
    elif args.encrypted:
        control_word = CONTROL_WORD_ENCRYPTED
        mode_str = "Stock Encrypted (0xB6020001)"
    elif args.no_decryption:
        control_word = CONTROL_WORD_NO_DECRYPTION
        mode_str = "Plaintext / No Decryption (0x06020000)"
    else:
        control_word = DEFAULT_CONTROL_WORD
        mode_str = f"Default configured (0x{control_word:08X})"

    print(f"[*] Header Control Word: 0x{control_word:08X} [{mode_str}]")

    container = package_firmware(payload_data, control_word)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(container)

    crc = struct.unpack("<I", container[-0x34:-0x30])[0]
    print(f"[+] Successfully generated: {out_path}")
    print(f"    - Total size: {len(container):,} bytes (Header: 96B, Payload: {len(payload_data):,}B, Footer: 64B)")
    print(f"    - IEEE 802.3 CRC-32: 0x{crc:08X}")


if __name__ == "__main__":
    main()

