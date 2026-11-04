#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""
patch_boot_string.py - Modify Core 0 boot splash version string and repackage container

Modifies the 16x2 LCD line 1 boot splash format string from:
  "        Ver.%4s"
to:
  "r/MC707 Ver.%4s"

Then repackages the patched payload into an unencrypted Roland update container
with all CRC-32 checksums dynamically recalculated.
"""

import argparse
import sys
import zlib
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.package_c0a_firmware import package_firmware, verify_container, CONTROL_WORD_NO_DECRYPTION

DEFAULT_SRC = Path("vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin")
DEFAULT_OUT = Path("build/RPG69_C0A_up.bin")

OLD_STRING = b"        Ver.%4s\x00"
NEW_STRING = b"r/MC707 Ver.%4s\x00"

def main():
    parser = argparse.ArgumentParser(description="Modify Core 0 boot splash version string and repackage unencrypted container")
    parser.add_argument("--input", "-i", type=Path, default=DEFAULT_SRC,
                        help=f"Path to decrypted payload (default: {DEFAULT_SRC})")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUT,
                        help=f"Path to output patched update container (default: {DEFAULT_OUT})")
    parser.add_argument("--string", "-s", type=str, default="r/MC707 Ver.%4s",
                        help="New boot splash string (must be exactly 16 bytes null-terminated)")
    args = parser.parse_args()

    src_payload = args.input
    if not src_payload.exists():
        print(f"[-] Error: Source payload not found: {src_payload}", file=sys.stderr)
        print("    Ensure you have decrypted App1_Main.enc using tools/decrypt_c0a.py", file=sys.stderr)
        sys.exit(1)

    payload = bytearray(src_payload.read_bytes())
    target_offset = 0x0004F1C4

    # Encode new string with null terminator
    new_str_bytes = args.string.encode('ascii')
    if not new_str_bytes.endswith(b'\x00'):
        new_str_bytes += b'\x00'

    if len(new_str_bytes) != len(OLD_STRING):
        print(f"[-] Error: String length must be exactly {len(OLD_STRING)} bytes (got {len(new_str_bytes)})", file=sys.stderr)
        sys.exit(1)

    # Verify original string at expected offset
    cur = bytes(payload[target_offset : target_offset + len(OLD_STRING)])
    if cur != OLD_STRING:
        print(f"[-] Error: Expected '{OLD_STRING}' at 0x{target_offset:08X}, but found '{cur}'", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Found target boot string at file offset 0x{target_offset:08X} (SDRAM: 0x{0x60000000+target_offset:08X})")
    print(f"    - Original: {cur}")
    print(f"    - Patching: {new_str_bytes}")

    # Apply patch
    payload[target_offset : target_offset + len(new_str_bytes)] = new_str_bytes

    # Calculate new payload CRC-32 (Word 20)
    payload_crc = zlib.crc32(payload) & 0xFFFFFFFF
    print(f"[*] New Payload CRC-32 (Word 20): 0x{payload_crc:08X}")

    # Package into unencrypted container (Word 21 = 0x00000000)
    print("[*] Packaging into unencrypted update container (Control Word: 0x00000000)...")
    container = package_firmware(bytes(payload), CONTROL_WORD_NO_DECRYPTION)

    # Write output container
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(container)
    print(f"[+] Saved patched unencrypted container to: {args.output} ({len(container):,} bytes)")

    # Verify container
    print("\n" + "=" * 76)
    print("VERIFYING GENERATED CONTAINER:")
    print("=" * 76)
    verify_container(args.output)

if __name__ == "__main__":
    main()
