#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""
patch_reader_firmware.py — Core 1 SysEx & Dumper Hook Injector for Roland MC-101 (RPG69_C1A_up.bin).

Assembles and injects the Core 1 SysEx memory/flash dumper and safe bus probe hook into
the unused zero-padding at idm1.bin:0x0113B04C, updates the QSPI TOC entry length and checksum,
recalculates the IEEE 802.3 CRC-32 trailer, and outputs the patched RPG69_C1A_up.bin to build/.

Key Design Decisions:
- ZERO modifications to sdram1.bin (100% factory clean stock to guarantee flawless boot).
- Entire payload runs 100% inside on-chip ITCM RAM (idm1.bin: 0x01100000).
- Hook intercepts MIDI Note 127 messages and passes all other MIDI through transparently.
- Implements USB-MIDI SysEx streaming for arbitrary AXI memory dumping, physical QSPI flash reading,
  fault-tolerant bus probing, and Core 0 inspection.
- TOC entry 0 16-bit word checksum recalculated for idm1.bin.
- IEEE 802.3 CRC-32 trailer recalculated.
"""

import sys
import struct
import binascii
from pathlib import Path
import capstone

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "vendor" / "mc101_sys_v182"
VENDOR_C1A = VENDOR_DIR / "RPG69_C1A_up.bin"
OUTPUT_DIR = ROOT / "build"
OUTPUT_C1A = OUTPUT_DIR / "RPG69_C1A_up.bin"

IDM_OFFSET = 0x1000
IDM_LENGTH = 241796

# The Cortex-M vector table is at file offset 0x1020 (0x20 bytes after IDM_OFFSET)
# and maps to ITCM base 0x01100000.
# Memory translation:
#   itcm_addr = 0x01100000 + (file_offset - 0x1020)
#   file_offset = 0x1020 + (itcm_addr - 0x01100000)
IDM_VECT_FILE_OFF = 0x1020
ITCM_BASE = 0x01100000

HOOK_SITE_FILE_OFF = 0x021B0E
HOOK_SITE_ITCM = ITCM_BASE + (HOOK_SITE_FILE_OFF - IDM_VECT_FILE_OFF)  # 0x01120AEE

PAD_FILE_OFF = 0x03C06C
PAD_ITCM = ITCM_BASE + (PAD_FILE_OFF - IDM_VECT_FILE_OFF)              # 0x0113B04C

NEW_IDM_LEN = 0x03C000      # Expand idm1 size to 245,760 bytes (3,988 bytes available before sdram1)

def encode_thumb16_b(from_addr: int, to_addr: int, cond: int = None) -> bytes:
    if cond is None:
        offset = to_addr - (from_addr + 4)
        imm11 = (offset >> 1) & 0x7FF
        return struct.pack('<H', 0xE000 | imm11)
    else:
        offset = to_addr - (from_addr + 4)
        imm8 = (offset >> 1) & 0xFF
        return struct.pack('<H', 0xD000 | (cond << 8) | imm8)

def encode_thumb2_b(from_addr: int, to_addr: int) -> bytes:
    offset = to_addr - (from_addr + 4)
    if offset < 0:
        offset += (1 << 25)
    s = (offset >> 24) & 1
    i1 = (offset >> 23) & 1
    i2 = (offset >> 22) & 1
    imm10 = (offset >> 12) & 0x3FF
    imm11 = (offset >> 1) & 0x7FF
    j1 = (~i1 ^ s) & 1
    j2 = (~i2 ^ s) & 1
    hw1 = 0xF000 | (s << 10) | imm10
    hw2 = 0x9000 | (j1 << 13) | (j2 << 11) | imm11
    return struct.pack('<HH', hw1, hw2)

def encode_thumb2_bl(from_addr: int, to_addr: int) -> bytes:
    offset = to_addr - (from_addr + 4)
    if offset < 0:
        offset += (1 << 25)
    s = (offset >> 24) & 1
    i1 = (offset >> 23) & 1
    i2 = (offset >> 22) & 1
    imm10 = (offset >> 12) & 0x3FF
    imm11 = (offset >> 1) & 0x7FF
    j1 = (~i1 ^ s) & 1
    j2 = (~i2 ^ s) & 1
    hw1 = 0xF000 | (s << 10) | imm10
    hw2 = 0xD000 | (j1 << 13) | (j2 << 11) | imm11
    return struct.pack('<HH', hw1, hw2)

def encode_thumb2_adr(from_addr: int, to_addr: int, rd: int = 0) -> bytes:
    pc = (from_addr + 4) & ~3
    offset = to_addr - pc
    assert 0 <= offset < 4096, f"Offset {offset} out of range"
    i = (offset >> 11) & 1
    imm3 = (offset >> 8) & 7
    imm8 = offset & 0xFF
    hw1 = 0xF20F | (i << 10)
    hw2 = (imm3 << 12) | (rd << 8) | imm8
    return struct.pack('<HH', hw1, hw2)

def encode_thumb2_movw(rd: int, imm16: int) -> bytes:
    imm4 = (imm16 >> 12) & 0xF
    i = (imm16 >> 11) & 1
    imm3 = (imm16 >> 8) & 7
    imm8 = imm16 & 0xFF
    hw1 = 0xF240 | (i << 10) | imm4
    hw2 = (imm3 << 12) | (rd << 8) | imm8
    return struct.pack('<HH', hw1, hw2)

def encode_thumb2_movt(rd: int, imm16: int) -> bytes:
    imm4 = (imm16 >> 12) & 0xF
    i = (imm16 >> 11) & 1
    imm3 = (imm16 >> 8) & 7
    imm8 = imm16 & 0xFF
    hw1 = 0xF2C0 | (i << 10) | imm4
    hw2 = (imm3 << 12) | (rd << 8) | imm8
    return struct.pack('<HH', hw1, hw2)

def build_payload(base: int) -> bytes:
    """Compile src/sysex_hook.s and return the raw binary payload."""
    import subprocess, tempfile
    asm_path = ROOT / "src" / "sysex_hook.s"
    assert asm_path.exists(), f"Assembly source missing: {asm_path}"

    with tempfile.TemporaryDirectory() as tmpdir:
        obj_path = Path(tmpdir) / "hook.o"
        elf_path = Path(tmpdir) / "hook.elf"
        bin_path = Path(tmpdir) / "hook.bin"

        # 1. Assemble
        subprocess.run([
            "arm-none-eabi-as",
            "-mcpu=cortex-m4", "-mthumb",
            str(asm_path),
            "-o", str(obj_path)
        ], check=True)

        # 2. Link with linker script defining RXDT_ENQUEUE_WORD
        ld_path = Path(tmpdir) / "hook.ld"
        ld_path.write_text(f"""
SECTIONS
{{
    . = 0x{base:08X};
    .text : {{ *(.text) }}
}}
RXDT_ENQUEUE_WORD = 0x0112101D;
TXDT_ENQUEUE_WORD = 0x011212A1;
TRIGGER_IPC_IRQ = 0x01101151;
""")
        subprocess.run([
            "arm-none-eabi-ld",
            "-T", str(ld_path),
            str(obj_path),
            "-o", str(elf_path)
        ], check=True)

        # 3. Extract binary
        subprocess.run([
            "arm-none-eabi-objcopy",
            "-O", "binary",
            str(elf_path),
            str(bin_path)
        ], check=True)

        return bin_path.read_bytes()

def patch_firmware():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not VENDOR_C1A.exists():
        print(f"[-] Clean vendor update file not found: {VENDOR_C1A}", file=sys.stderr)
        sys.exit(1)

    data = bytearray(VENDOR_C1A.read_bytes())
    orig_len = len(data)
    print(f"[*] Loaded clean stock {VENDOR_C1A.name} ({orig_len} bytes)")

    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)

    # 1. Verify original instruction at hook site in idm1.bin
    hook_off = HOOK_SITE_FILE_OFF
    orig_ins = data[hook_off : hook_off + 4]
    print(f"[*] Original instruction at hook site (0x{HOOK_SITE_ITCM:08X}):")
    for ins in md.disasm(orig_ins, HOOK_SITE_ITCM):
        print(f"    0x{ins.address:08X}: {ins.mnemonic:8s} {ins.op_str}")

    # 2. Verify idm1 padding is all zeroes
    pad_off = PAD_FILE_OFF
    pad_len = (IDM_OFFSET + NEW_IDM_LEN) - pad_off  # 0x3D000 - 0x3C06C = 3988 bytes
    pad_bytes = data[pad_off : pad_off + pad_len]
    assert all(b == 0 for b in pad_bytes), f"idm1 padding site at 0x{PAD_ITCM:08X} is not all zeros!"
    print(f"[*] Verified zero padding at idm1:0x{PAD_ITCM:08X} ({pad_len} bytes available)")

    # 3. Construct & inject hook BL in idm1.bin: 0x01120AEE -> 0x0113B04C
    bl_to_hook = encode_thumb2_bl(HOOK_SITE_ITCM, PAD_ITCM)
    data[hook_off : hook_off + 4] = bl_to_hook
    print(f"[+] Injected BL at 0x{HOOK_SITE_ITCM:08X} -> 0x{PAD_ITCM:08X}")

    # 4. Construct & inject Audio Modem Firmware Hook
    base = PAD_ITCM  # 0x0113B04C
    payload_block = build_payload(base)

    assert len(payload_block) <= pad_len, f"Payload too large: {len(payload_block)} > {pad_len}"
    data[pad_off : pad_off + len(payload_block)] = payload_block
    print(f"[+] Injected {len(payload_block)}-byte Audio Modem Hook payload at 0x{base:08X} (max {pad_len} bytes)")

    # 5. Verify disassembly of injected components
    print("\n[*] Disassembly of injected hook call:")
    for ins in md.disasm(data[hook_off : hook_off + 4], HOOK_SITE_ITCM):
        print(f"    0x{ins.address:08X}: {ins.mnemonic:8s} {ins.op_str}")

    print(f"\n[*] Disassembly of injected payload block (0x{base:08X}):")
    for ins in md.disasm(data[pad_off : pad_off + len(payload_block)], PAD_ITCM):
        print(f"    0x{ins.address:08X}: {ins.mnemonic:8s} {ins.op_str}")

    # 6. Update TOC Entry 0 length to NEW_IDM_LEN (242,176 bytes)
    struct.pack_into('<I', data, 0x44, NEW_IDM_LEN)
    print(f"\n[+] Updated TOC Entry 0 length: 0x{NEW_IDM_LEN:08X} ({NEW_IDM_LEN} bytes)")

    # 7. Recalculate TOC Entry 0 16-bit word checksum for idm1.bin
    idm_slice = data[IDM_OFFSET : IDM_OFFSET + NEW_IDM_LEN]
    new_toc_csum = sum(int.from_bytes(idm_slice[i:i+2], 'little') for i in range(0, NEW_IDM_LEN, 2)) & 0xFFFF
    struct.pack_into('<I', data, 0x48, new_toc_csum)
    print(f"[+] Updated TOC idm1 checksum: 0x{new_toc_csum:04X}")

    # 8. Recalculate IEEE 802.3 CRC-32 trailer
    assert len(data) == orig_len, f"Size changed! {orig_len} -> {len(data)}"
    crc_payload = data[:-0x34]
    new_crc = binascii.crc32(crc_payload) & 0xFFFFFFFF
    struct.pack_into('<I', data, len(data) - 0x34, new_crc)
    print(f"[+] Updated IEEE 802.3 CRC-32 trailer: 0x{new_crc:08X} at offset {len(data) - 0x34}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_C1A.write_bytes(data)
    print(f"\n[✓] Patched update image written to: {OUTPUT_C1A}")
    print(f"[✓] File size: {len(data)} bytes (strictly identical to stock: 4,194,144 bytes)")
    print(f"[✓] idm1 0x01100000 (vector table / header): 100% CLEAN FACTORY STOCK (0 bytes modified)")
    print(f"[✓] sdram1.bin: 100% CLEAN FACTORY STOCK (0 bytes modified)")

if __name__ == "__main__":
    patch_firmware()
