#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""
parse_scatterload.py — ARM Scatterload Table Parser for Roland MC-101 Core 0

Parses the ARM Compiler (armcc) __scatterload table located in the Core 0
SDRAM image at 0x602C9904 (file offset 0x2C9904).

Maps all load and execution regions:
- Copy regions: .itcm, .sram_data, .e0043000
- Zero-init regions: .sdram_bss, .itcm_bss, .sram_bss, peripheral RAMs
"""

import sys
import struct
from pathlib import Path

SCATTERLOAD_TABLE_FLASH_OFFSET = 0x2C9904
SCATTERLOAD_TABLE_SDRAM_ADDR = 0x602C9904

HANDLERS = {
    0x600003F6: "__scatterload_null (NOP / In-place)",
    0x60000478: "__scatterload_copy (Memcpy)",
    0x60000494: "__scatterload_zeroinit (Memset 0)",
}

REGION_NAMES = {
    # Handled by __scatterload_null
    (0x60000000, 0x60000000): "SDRAM Text / Read-Only Data (In-place)",
    # Handled by __scatterload_copy
    (0x6031279C, 0x01000000): "Core 0 ITCM Vector Table",
    (0x60312B9C, 0x01000400): "Core 0 ITCM Fast Code",
    (0x6035583C, 0x20000000): "Shared SRAM Data Chunk 1",
    (0x60355ACC, 0x20000290): "Shared SRAM Data Chunk 2",
    (0x60356578, 0xE0043000): "Hardware Peripheral / Debug Data",
    # Handled by __scatterload_zeroinit
    (0x6031279C, 0x6031279C): "SDRAM Primary BSS (Overlays Load Region)",
    (0x6031279C, 0x61700000): "SDRAM Upper BSS Chunk 1",
    (0x6031279C, 0x61800000): "SDRAM Upper BSS Chunk 2 (Audio / Wave RAM)",
    (0x6035583C, 0x01050000): "ITCM BSS",
    (0x60356578, 0x20000D3C): "Shared SRAM BSS",
    (0x60356578, 0x40048000): "Internal On-Chip RAM BSS 1",
    (0x60356578, 0x40068000): "Internal On-Chip RAM BSS 2",
    (0x603565B0, 0xE0043038): "Hardware Peripheral BSS",
}

def parse_scatterload(binary_path: Path):
    data = binary_path.read_bytes()
    print(f"[*] Analyzing binary: {binary_path} ({len(data):,} bytes)")
    
    if len(data) < SCATTERLOAD_TABLE_FLASH_OFFSET + 16:
        print("[-] File too small for scatterload table", file=sys.stderr)
        return

    print(f"[*] Scatterload Table at offset 0x{SCATTERLOAD_TABLE_FLASH_OFFSET:06X} (SDRAM: 0x{SCATTERLOAD_TABLE_SDRAM_ADDR:08X})\n")
    print(f"{'Idx':<4} {'SDRAM File Addr':<17} {'Src (Load)':<12} {'Dst (Exec)':<12} {'Length':<12} {'Handler / Action':<35} {'Region Description'}")
    print("=" * 130)

    idx = 0
    while True:
        entry_off = SCATTERLOAD_TABLE_FLASH_OFFSET + idx * 16
        if entry_off + 16 > len(data):
            break
        entry = data[entry_off : entry_off + 16]
        src, dst, length, handler = struct.unpack("<IIII", entry)

        # Check if entry is valid
        if handler not in HANDLERS:
            # End of table
            break

        handler_desc = HANDLERS.get(handler, f"Unknown (0x{handler:08X})")
        region_desc = REGION_NAMES.get((src, dst), "Custom Region")
        file_addr_str = f"0x{0x60000000 + entry_off:08X}"

        print(f"{idx:<4} {file_addr_str:<17} 0x{src:08X}   0x{dst:08X}   0x{length:08X}   {handler_desc:<35} {region_desc}")
        idx += 1

    print("=" * 130)
    print(f"[+] Total scatterload entries parsed: {idx}")

if __name__ == "__main__":
    p = Path("vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin")
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
    parse_scatterload(p)

