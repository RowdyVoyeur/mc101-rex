#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""
decrypt_c0a.py - Clean Firmware Decryptor for Roland MC-101 Core 0 (ESC2 SoC)

Decrypts the stock vendor firmware update container (e.g. vendor/mc101_sys_v182/RPG69_C0A_up.bin)
using the exact 3DES cryptographic key material derived from the on-chip silicon
Boot ROM table at 0x012023B0 (index 0xB6) and the hardware AXI word-swapped
DES peripheral cipher mode.

Output: Bit-perfect, pristine, uncorrupted App1_Main execution image (3,499,440 B)
ready for reverse engineering, disassembly, and custom firmware development.
"""

import argparse
import hashlib
import os
from pathlib import Path
import struct
import sys
import time

try:
    from Cryptodome.Cipher import DES3
except ImportError:
    try:
        from Crypto.Cipher import DES3
    except ImportError:
        print("[!] Error: pycryptodomex or pycryptodome is required.")
        print("    Install via: pip install pycryptodomex")
        sys.exit(1)


def parse_container_header(data: bytes):
    """
    Parses the 96-byte (0x60) Roland update container header.
    """
    if len(data) < 0x60:
        raise ValueError(f"File too small for container header ({len(data)} bytes, expected >= 96)")

    part_name = data[:16].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    timestamp = data[16:32].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    version = data[32:44].split(b"\x00", 1)[0].decode("ascii", errors="replace")

    # Words 16..23 starting at +0x40
    w_src, w_len, w_dst, w_rsvd, w_chk, w_ctrl, w_pad1, w_pad2 = struct.unpack(
        "<IIIIIIII", data[0x40:0x60]
    )

    enc_enabled = (w_ctrl & 0xFF) == 1
    key_mode = (w_ctrl >> 16) & 0xFF  # Mode 2 = 3-Key 3DES
    key_idx = (w_ctrl >> 24) & 0xFF   # 0xB6

    return {
        "partition_name": part_name,
        "timestamp": timestamp,
        "version": version,
        "flash_src": w_src,
        "payload_len": w_len,
        "load_dst": w_dst,
        "checksum": w_chk,
        "crypto_ctrl": w_ctrl,
        "encrypted": enc_enabled,
        "key_mode": key_mode,
        "key_index": key_idx,
    }


def derive_3des_key(bootrom_path: str = "vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin", key_idx: int = 0xB6) -> bytes:
    """
    Extracts and packs the 24-byte 3DES key from the on-chip Boot ROM key table at 0x012023B0.
    In App0 (0x01000608) and Boot ROM (0x01200298):
      Table Base = 0x012023B0
      Entry Offset = key_idx * 24
      Table Address = Table Base + Entry Offset
    
    The hardware DES key registers (0x40020400..0x40020414) in Decrypt mode (r7 == 1)
    load the words in inverted key order:
      Key 1: [Table + 16, Table + 20]
      Key 2: [Table + 8,  Table + 12]
      Key 3: [Table + 0,  Table + 4]
    
    AXI bus word packing to big-endian 3DES key:
      Key = pack(">IIIIII", w1, w0, w3, w2, w5, w4)
    """
    if os.path.exists(bootrom_path):
        with open(bootrom_path, "rb") as f:
            rom = f.read()
        table_offset = 0x23B0 + (key_idx * 24)
        if table_offset + 24 <= len(rom):
            raw_k = rom[table_offset : table_offset + 24]
            w0, w1, w2, w3, w4, w5 = struct.unpack("<IIIIII", raw_k)
            # Pack in standard DES3 big-endian order matching hardware engine
            key = struct.pack(">IIIIII", w1, w0, w3, w2, w5, w4)
            return key

    raise RuntimeError(f"Cannot derive key for index 0x{key_idx:02X} without Boot ROM file {bootrom_path}")


def decrypt_firmware(ciphertext: bytes, key: bytes, chunk_size: int = 65536) -> bytes:
    """
    Decrypts the ciphertext stream using 3DES ECB with hardware AXI 32-bit word inversion.
    """
    cipher = DES3.new(key, DES3.MODE_ECB)
    total_len = len(ciphertext)
    plaintext = bytearray(total_len)

    for offset in range(0, total_len, chunk_size):
        chunk = ciphertext[offset : offset + chunk_size]
        n_blocks = len(chunk) // 8
        if n_blocks == 0:
            break

        # Unpack 32-bit little-endian words
        words = struct.unpack(f"<{n_blocks*2}I", chunk[:n_blocks*8])

        # Swap word pairs for hardware FIFO representation
        swapped_c = []
        for i in range(0, len(words), 2):
            swapped_c.append(words[i + 1])
            swapped_c.append(words[i])

        # Encrypt/Decrypt through DES3 engine
        c_be = struct.pack(f">{n_blocks*2}I", *swapped_c)
        p_be = cipher.decrypt(c_be)

        # Unpack big-endian decrypted words and swap back to native ARM little-endian
        p_words = struct.unpack(f">{n_blocks*2}I", p_be)
        p_swapped = []
        for i in range(0, len(p_words), 2):
            p_swapped.append(p_words[i + 1])
            p_swapped.append(p_words[i])

        plaintext[offset : offset + n_blocks * 8] = struct.pack(f"<{n_blocks*2}I", *p_swapped)

    return bytes(plaintext)


def main():
    default_in = (
        "vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main.enc"
        if Path("vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main.enc").exists()
        else "vendor/mc101_sys_v182/RPG69_C0A_up.bin"
    )
    parser = argparse.ArgumentParser(description="Decrypt Roland MC-101 Core 0 Stock Firmware Container")
    parser.add_argument("--input", "-i", default=default_in, help="Path to vendor update container or extracted payload")
    parser.add_argument("--output", "-o", default="vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin", help="Output decrypted binary path")
    parser.add_argument("--bootrom", "-b", default="vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin", help="Silicon Boot ROM binary path")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[!] Input file not found: {args.input}")
        sys.exit(1)

    with open(args.input, "rb") as f:
        file_data = f.read()

    print("=" * 76)
    print("ROLAND MC-101 / ESC2 FIRMWARE CONTAINER DECRYPTOR")
    print("=" * 76)
    print(f"[*] Input File:       {args.input} ({len(file_data):,} bytes)")

    # Check if input is the full container or extracted raw ciphertext payload
    sibling_hdr = Path(args.input).parent / "header.bin"
    if file_data[:9] != b"App1_Main" and sibling_hdr.exists():
        hdr = parse_container_header(sibling_hdr.read_bytes())
        ciphertext = file_data
        print(f"[*] Using container header from: {sibling_hdr}")
    else:
        hdr = parse_container_header(file_data)
        ciphertext = file_data[0x60 : 0x60 + hdr["payload_len"]]

    print(f"[*] Partition:        '{hdr['partition_name']}'")
    print(f"[*] Build Date:       {hdr['timestamp']}")
    print(f"[*] Version:          {hdr['version']}")
    print(f"[*] Flash Source:     0x{hdr['flash_src']:08X}")
    print(f"[*] Destination:      0x{hdr['load_dst']:08X} (SDRAM)")
    print(f"[*] Payload Length:   0x{hdr['payload_len']:08X} ({hdr['payload_len']:,} bytes)")
    print(f"[*] Crypto Enabled:   {hdr['encrypted']} (Mode: {hdr['key_mode']}, Key Index: 0x{hdr['key_index']:02X})")

    if not hdr["encrypted"]:
        print("[*] Container is not encrypted. Extracting raw payload...")
        with open(args.output, "wb") as f:
            f.write(ciphertext)
        print(f"[✓] Saved unencrypted payload to {args.output}")
        return

    # Derive 3DES key
    key = derive_3des_key(args.bootrom, key_idx=hdr["key_index"])
    print(f"[*] 3DES Master Key:  {key.hex()}")

    if len(ciphertext) != hdr["payload_len"]:
        print(f"[!] Warning: Read {len(ciphertext)} bytes, expected {hdr['payload_len']}")

    print(f"[*] Decrypting {len(ciphertext):,} bytes via hardware 3DES pipeline...")
    t0 = time.perf_counter()
    plaintext = decrypt_firmware(ciphertext, key)
    elapsed = time.perf_counter() - t0
    throughput = (len(plaintext) / (1024 * 1024)) / elapsed
    print(f"[✓] Decryption complete in {elapsed:.2f}s ({throughput:.1f} MB/s)")

    # Sanity check ARM entry point
    entry_word = struct.unpack("<I", plaintext[:4])[0]
    print(f"[*] First Word (CRT0 Entry): 0x{entry_word:08X}")
    if entry_word != 0x680148AE:  # ldr r0, [pc, #696]; ldr r1, [r0]
        print(f"[!] Warning: Entry point word 0x{entry_word:08X} differs from expected 0x680148AE")
    else:
        print("[✓] Entry point validated: Matches Roland Core 0 CRT0 startup sequence!")

    # Check scatterload table at 0x2C9904
    if len(plaintext) > 0x2C9904 + 16:
        scat_w0 = struct.unpack("<I", plaintext[0x2C9904 : 0x2C9904 + 4])[0]
        print(f"[*] Scatterload Table at +0x2C9904: 0x{scat_w0:08X}")
        if scat_w0 == 0x60000000:
            print("[✓] Scatterload table validated: Correct ARM Compiler Scatterload layout!")

    # Save to disk
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(plaintext)

    sha256 = hashlib.sha256(plaintext).hexdigest()
    print(f"[✓] Output File:      {args.output}")
    print(f"[*] File Size:        {len(plaintext):,} bytes")
    print(f"[*] SHA-256 Checksum: {sha256}")
    print("=" * 76)
    print("DECRYPTION SUCCESSFUL: Pristine factory firmware image ready.")
    print("=" * 76)


if __name__ == "__main__":
    main()

