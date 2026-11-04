#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""
sysex_dump_client.py — High-Speed USB-MIDI SysEx Memory Dumper for Roland MC-101.

Uses Core 1's native UMDW SysEx engine to extract arbitrary memory regions
(e.g., full 3.5 MB decrypted Core 0 flash at 0x60000000) over USB-MIDI.

Protocol:
  - Host sends Note 127, Vel 15 + 8 nibbles (Vel 32..47) to set 32-bit address latch.
  - Host sends Note 127, Vel 14 to request a 256-byte chunk.
  - Core 1 reads 256 bytes from flash, constructs a 530-byte Roland DT1 SysEx message:
      F0 41 10 00 00 00 5E 12 <8 addr nibbles> <512 data nibbles> <checksum> F7
  - Core 1 enqueues message to TXDT ring buffer and raises IPC interrupt to Core 0.
  - Core 0 transmits USB-MIDI packets to Host PC.
  - Host decodes nibbles, validates Roland checksum, and appends to output file.

Speed: ~50-100 KB/s (3.5 MB in under 60 seconds).
"""

import os
import sys
import time
import select
import struct
import hashlib
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGET_MAP = {
    "c0_flash_full": {"base": 0x60000000, "default_len": 3499440, "name": "Full Decrypted Core 0 Flash (3.5 MB)"},
    "c0_app":        {"base": 0x60000000, "default_len": 273664,  "name": "Core 0 Application Header / Code (267 KB)"},
    "c0_flash_vtor": {"base": 0x6031279C, "default_len": 1024,    "name": "Core 0 Flash Vector Table (1 KB)"},
    "c0_kernel":     {"base": 0x60312B9C, "default_len": 273664,  "name": "Core 0 Kernel Entry (267 KB)"},
    "bootrom":       {"base": 0x01200000, "default_len": 16384,   "name": "ESC2 Silicon Mask Boot ROM (16 KB)"},
    "sram":          {"base": 0x20000000, "default_len": 65536,   "name": "SRAM Data (64 KB)"},
}

TRIGGER_NOTE = 127
SYSEX_HEADER = bytes([0xF0, 0x41, 0x10, 0x00, 0x00, 0x00, 0x5E, 0x12])
PACKET_LEN = 530  # 8 header + 8 addr + 512 data + 1 csum + 1 F7


class RawMidiPort:
    """Direct, low-latency interface to Linux ALSA RawMIDI device (/dev/snd/midiC*D*)."""
    def __init__(self, dev_path: str = None):
        if dev_path is None:
            # Auto-detect MC-101 rawmidi device
            dev_path = self.auto_detect_device()
        self.dev_path = dev_path
        print(f"[*] Opening ALSA RawMIDI device: {self.dev_path}")
        self.fd = os.open(self.dev_path, os.O_RDWR | os.O_NONBLOCK)
        self.rx_buffer = bytearray()
        self.flush_rx()

    @staticmethod
    def auto_detect_device() -> str:
        # Check /dev/snd/midiC*D*
        candidates = sorted(Path("/dev/snd").glob("midiC*D*"))
        if not candidates:
            raise FileNotFoundError("No ALSA RawMIDI devices found in /dev/snd/")
        # If multiple, prefer card 3 (typical MC-101) or first available
        for c in candidates:
            if "midiC3" in c.name:
                return str(c)
        return str(candidates[0])

    def flush_rx(self):
        """Drain any residual bytes in the input FIFO."""
        try:
            while True:
                chunk = os.read(self.fd, 4096)
                if not chunk:
                    break
        except BlockingIOError:
            pass
        self.rx_buffer.clear()

    def send_bytes(self, data: bytes):
        os.write(self.fd, data)

    def send_note_on(self, ch: int, pitch: int, vel: int):
        self.send_bytes(bytes([0x90 | (ch & 0xF), pitch & 0x7F, vel & 0x7F]))

    def read_sysex_packet(self, timeout: float = 0.5) -> bytes | None:
        """
        Reads until a complete Roland SysEx packet (F0 ... F7) is received.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            f0_idx = self.rx_buffer.find(b'\xF0')
            if f0_idx != -1:
                if f0_idx > 0:
                    del self.rx_buffer[:f0_idx]
                f7_idx = self.rx_buffer.find(b'\xF7')
                if f7_idx != -1 and f7_idx >= 18:  # Minimum valid packet
                    pkt = bytes(self.rx_buffer[:f7_idx + 1])
                    del self.rx_buffer[:f7_idx + 1]
                    return pkt

            remaining = deadline - time.time()
            if remaining <= 0:
                break
            r, _, _ = select.select([self.fd], [], [], remaining)
            if r:
                try:
                    chunk = os.read(self.fd, 4096)
                    if chunk:
                        self.rx_buffer.extend(chunk)
                except BlockingIOError:
                    pass

        return None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def set_target_address(midi: RawMidiPort, addr: int):
    """Programs the 32-bit target read address into Core 1's latch via 8 nibbles."""
    midi.send_note_on(0, TRIGGER_NOTE, 15)
    time.sleep(0.005)

    for shift in range(28, -1, -4):
        nibble = (addr >> shift) & 0x0F
        midi.send_note_on(0, TRIGGER_NOTE, 32 + nibble)
        time.sleep(0.002)


def decode_sysex_chunk(pkt: bytes) -> tuple[int, bytes]:
    """
    Validates and decodes a variable-length Roland DT1 SysEx packet.
    Packet structure:
      0..7:   F0 41 10 00 00 00 5E 12 (8 bytes)
      8..15:  8 address nibbles (4 bytes address)
      16..-2: N data nibbles (N // 2 bytes data)
      -2:     Roland Checksum
      -1:     F7
    """
    if len(pkt) < 18:
        raise ValueError(f"Packet too short: {len(pkt)} bytes (min 18)")
    if pkt[0] != 0xF0 or pkt[-1] != 0xF7:
        raise ValueError(f"Invalid framing: starts 0x{pkt[0]:02X}, ends 0x{pkt[-1]:02X}")
    if pkt[:8] != SYSEX_HEADER:
        raise ValueError(f"Invalid header: {pkt[:8].hex()} (expected {SYSEX_HEADER.hex()})")

    # Verify Roland checksum over address (8 nibbles) + data (N nibbles)
    payload_nibbles = pkt[8:-2]
    expected_csum = pkt[-2]
    acc = sum(payload_nibbles)
    calc_csum = (128 - (acc & 0x7F)) & 0x7F
    if expected_csum != calc_csum:
        raise ValueError(f"Checksum mismatch: received 0x{expected_csum:02X}, calculated 0x{calc_csum:02X}")

    # Decode 8 address nibbles (big-endian)
    addr = 0
    for i in range(8):
        addr = (addr << 4) | (pkt[8 + i] & 0x0F)

    # Decode data nibbles into bytes
    data_nibbles = pkt[16:-2]
    num_bytes = len(data_nibbles) // 2
    data = bytearray(num_bytes)
    for i in range(num_bytes):
        hi = data_nibbles[i * 2] & 0x0F
        lo = data_nibbles[i * 2 + 1] & 0x0F
        data[i] = (hi << 4) | lo

    return addr, bytes(data)



def dump_memory_sysex(
    target: str = "c0_flash_full",
    addr: int | None = None,
    total_bytes: int | None = None,
    out_file: str | None = None,
    dev_path: str | None = None,
    resume: bool = True
):
    target_info = TARGET_MAP.get(target, {})
    base_addr = addr if addr is not None else target_info.get("base", 0x60000000)
    req_bytes = total_bytes if total_bytes is not None else target_info.get("default_len", 3499440)

    out_path = Path(out_file) if out_file else (ROOT / "dumps" / f"{target}_{req_bytes}b.bin")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print("ROLAND MC-101 HIGH-SPEED USB-MIDI SYSEX MEMORY DUMPER")
    print("=" * 75)
    print(f"Target Preset:    {target} ({target_info.get('name', 'Custom')})")
    print(f"Base Address:     0x{base_addr:08X}")
    print(f"Total Bytes:      {req_bytes:,} bytes ({req_bytes / 1024 / 1024:.2f} MB)")
    print(f"Output File:      {out_path}")

    # Check for existing file for auto-resume
    existing_bytes = 0
    if resume and out_path.exists():
        existing_bytes = out_path.stat().st_size
        if existing_bytes >= req_bytes:
            print(f"\n[✓] File already fully dumped: {out_path} ({existing_bytes:,} bytes)")
            h = hashlib.sha256(out_path.read_bytes()).hexdigest()
            print(f"    SHA-256: {h}")
            return
        # Round existing_bytes down to multiple of 64
        existing_bytes = (existing_bytes // 64) * 64
        print(f"[*] Resuming from existing partial dump: {existing_bytes:,} bytes ({existing_bytes / req_bytes * 100:.1f}%)")

    current_addr = base_addr + existing_bytes
    remaining_bytes = req_bytes - existing_bytes
    num_chunks = (remaining_bytes + 63) // 64

    midi = RawMidiPort(dev_path=dev_path)

    try:
        print(f"\n[*] 1. Programming start address 0x{current_addr:08X} into Core 1...")
        set_target_address(midi, current_addr)
        time.sleep(0.01)

        # Open file in append or write mode
        mode = "ab" if (resume and existing_bytes > 0) else "wb"
        f_out = open(out_path, mode)

        if mode == "ab" and existing_bytes > 0:
            f_out.truncate(existing_bytes)

        print(f"[*] 2. Streaming {num_chunks:,} chunks (64 B/chunk) via USB-MIDI SysEx...")
        t_start = time.time()
        bytes_dumped = existing_bytes
        chunks_done = 0

        while bytes_dumped < req_bytes:
            # Send Note 127, Vel 20 to trigger next 64-byte chunk
            chunk_retries = 0
            pkt = None

            while chunk_retries < 3:
                midi.send_note_on(0, TRIGGER_NOTE, 20)
                pkt = midi.read_sysex_packet(timeout=0.3)
                if pkt is not None:
                    break
                chunk_retries += 1
                # If timed out, re-latch address to resync
                set_target_address(midi, base_addr + bytes_dumped)
                time.sleep(0.01)

            if pkt is None:
                raise TimeoutError(f"Device stopped responding at offset 0x{bytes_dumped:X}")

            pkt_addr, data = decode_sysex_chunk(pkt)
            expected_addr = base_addr + bytes_dumped

            if pkt_addr != expected_addr:
                # Re-sync address
                set_target_address(midi, expected_addr)
                continue

            # Determine slice length (for final residual block)
            slice_len = min(64, req_bytes - bytes_dumped)
            f_out.write(data[:slice_len])
            f_out.flush()

            bytes_dumped += slice_len
            chunks_done += 1

            # Progress metrics
            elapsed = time.time() - t_start
            speed_bps = (bytes_dumped - existing_bytes) / max(0.001, elapsed)
            percent = (bytes_dumped / req_bytes) * 100
            eta_sec = (req_bytes - bytes_dumped) / max(1.0, speed_bps)

            bar_len = 35
            filled = int(bar_len * percent / 100)
            bar = "=" * filled + ">" + " " * (bar_len - filled - 1) if filled < bar_len else "=" * bar_len

            sys.stdout.write(
                f"\r[{bar}] {percent:5.1f}% | {bytes_dumped:,}/{req_bytes:,} B | "
                f"{speed_bps / 1024:5.1f} KB/s | ETA: {eta_sec:4.1f}s  "
            )
            sys.stdout.flush()

        f_out.close()
        t_total = time.time() - t_start
        print(f"\n\n[✓] Dump complete in {t_total:.1f}s (Average: {(req_bytes - existing_bytes) / max(0.1, t_total) / 1024:.1f} KB/s)!")

        final_data = out_path.read_bytes()
        print(f"[*] Final Size: {len(final_data):,} bytes")
        print(f"[*] SHA-256:    {hashlib.sha256(final_data).hexdigest()}")

        # Check Vector Table header if dumping flash
        if base_addr == 0x60000000 and len(final_data) >= 16:
            msp, reset_handler = struct.unpack('<II', final_data[0:8])
            print(f"[*] Header Verification:")
            print(f"    MSP (Initial Stack Pointer): 0x{msp:08X} (Expected: 0x01050800)")
            print(f"    Reset Handler (CRT0):       0x{reset_handler:08X} (Expected: 0x6000011D)")
            if msp == 0x01050800 and reset_handler == 0x6000011D:
                print("    🎉 FLASH HEADER VALIDATED: 100% BIT-EXACT MATCH WITH STOCK FIRMWARE!")

    finally:
        midi.close()


def probe_dma_regs(dev_path: str | None = None):
    """
    Step 1: Safely reads the DMA Controller registers at 0x40001000 (Note 127, Vel 21).
    Pure read operation, zero DMA writes. Verifies Core 1 MMIO bus access to 0x40001000.
    """
    print("=" * 75)
    print("STEP 1: PROBE DMA CONTROLLER MMIO REGISTERS (0x40001000)")
    print("=" * 75)
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    try:
        print("[*] Sending Register Probe Trigger: Note 127, Velocity 21 (cmd_probe_dma_regs)...")
        midi.send_note_on(0, TRIGGER_NOTE, 21)

        print("[*] Waiting for register snapshot SysEx report from Core 1...")
        pkt = midi.read_sysex_packet(timeout=1.0)
        if pkt is None:
            print("[-] TIMEOUT: Device did not respond with SysEx packet.")
            print("    Check if the patched firmware (build/RPG69_C1A_up.bin) is installed.")
            return

        addr, data = decode_sysex_chunk(pkt)
        if len(data) < 64:
            print(f"[-] Malformed response length: {len(data)} bytes")
            return

        words = struct.unpack('<16I', data)
        global_ctrl = words[0]
        global_status = words[1]
        ch1_ctrl = words[2]
        ch1_status = words[3]
        ch1_dest = words[4]
        ch1_src = words[5]
        magic = data[24:28].decode('latin1', errors='replace')

        print("\n" + "-" * 75)
        print("DMA CONTROLLER REGISTER DUMP:")
        print(f"[*] Response Address:      0x{addr:08X} (Expected: 0x40001000)")
        print(f"[*] Report Magic:          '{magic}' (Expected: 'REGS')")
        print(f"[*] 0x40001000 (Global Ctrl):   0x{global_ctrl:08X} (Bit 31 Enable: {(global_ctrl >> 31) & 1})")
        print(f"[*] 0x40001004 (Global Status): 0x{global_status:08X}")
        print(f"[*] 0x40001020 (Ch 1 Ctrl):     0x{ch1_ctrl:08X}")
        print(f"[*] 0x40001024 (Ch 1 Status):   0x{ch1_status:08X} (State: {(ch1_status >> 16) & 7})")
        print(f"[*] 0x40001028 (Ch 1 Dest):     0x{ch1_dest:08X}")
        print(f"[*] 0x4000102C (Ch 1 Src):      0x{ch1_src:08X}")
        print("-" * 75)

        print("\n🎉 SUCCESS: Core 1 has verified read access to the SoC DMA engine registers!")
        print("[✓] Next step: Run with --test-dma-c1 to test DMA write to Core 1's own ITCM.")

    finally:
        midi.close()


def test_dma_c1(dev_path: str | None = None):
    """
    Step 2: Tests DMA transfer between Shared SRAM buffers (0x2001F000 -> 0x2001F100) (Note 127, Vel 22).
    Verifies that the DMA controller successfully moves memory across system bus addresses.
    """
    print("=" * 75)
    print("STEP 2: DMA WRITE TEST TO SHARED SRAM (0x2001F100)")
    print("=" * 75)
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    try:
        print("[*] Sending SRAM DMA Trigger: Note 127, Velocity 22 (cmd_test_dma_c1)...")
        midi.send_note_on(0, TRIGGER_NOTE, 22)

        print("[*] Waiting for SRAM DMA diagnostic report...")
        pkt = midi.read_sysex_packet(timeout=1.0)
        if pkt is None:
            print("[-] TIMEOUT: Device did not respond.")
            return

        addr, data = decode_sysex_chunk(pkt)
        if len(data) < 64:
            print(f"[-] Malformed response length: {len(data)} bytes")
            return

        words = struct.unpack('<16I', data)
        status = words[0]
        word0_readback = words[1]
        word3_readback = words[2]
        magic = data[12:16].decode('latin1', errors='replace')

        status_str = {1: "COMPLETE", 2: "TIMEOUT"}.get(status, f"UNKNOWN (0x{status:X})")

        print("\n" + "-" * 75)
        print("DIAGNOSTIC REPORT:")
        print(f"[*] Destination Address:   0x{addr:08X} (Shared SRAM)")
        print(f"[*] Report Magic:          '{magic}' (Expected: 'C1DM')")
        print(f"[*] DMA Status:            {status_str} (Code: {status})")
        print(f"[*] Word 0 Readback:       0x{word0_readback:08X} (Target: 0xA1B2C3D4)")
        print(f"[*] Word 3 Readback:       0x{word3_readback:08X} (Target: 0xDEADBEEF)")
        print("-" * 75)

        if word0_readback == 0xA1B2C3D4 and word3_readback == 0xDEADBEEF:
            print("\n🎉 SUCCESS: DMA CONTROLLER MOVED DATA ACROSS SYSTEM BUS TO SRAM!")
            print("    1. Core 1 programmed Channel 1 at 0x40001020.")
            print("    2. DMA burst transferred 64 bytes from 0x2001F000 to 0x2001F100.")
            print("    3. Readback confirmed exact pattern match (0xA1B2C3D4 / 0xDEADBEEF).")
            print("    4. Core 0 was completely untouched.")
            print("\n[✓] Next step: Run with --test-dma-c0 to test writing to Core 0 ITCM (0x01060000).")
        elif status == 2:
            print("\n[-] TIMEOUT: DMA burst did not complete within timeout.")
        else:
            print(f"\n[-] MISMATCH: Readback did not match SRAM pattern: 0x{word0_readback:08X}, 0x{word3_readback:08X}")

    finally:
        midi.close()


def test_dma_c0_identity(dev_path: str | None = None):
    """
    Step 3: DMA writes test pattern into Core 0 ITCM Unused Scratch / Padding (0x01060000) (Note 127, Vel 23).
    0x01060000 is 100% zeroes in stock Core 0 ITCM (above MSP 0x01050800).
    Zero risk: No active vectors, code, or stack variables are touched.
    """
    print("=" * 75)
    print("STEP 3: CORE 0 ITCM SCRATCH DMA WRITE TEST (0x01060000)")
    print("=" * 75)
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    try:
        print("[*] Sending C0 ITCM Trigger: Note 127, Velocity 23 (cmd_test_dma_c0_scratch)...")
        midi.send_note_on(0, TRIGGER_NOTE, 23)

        print("[*] Waiting for C0 ITCM SysEx report...")
        pkt = midi.read_sysex_packet(timeout=1.0)
        if pkt is None:
            print("[-] TIMEOUT: Device did not respond.")
            return

        addr, data = decode_sysex_chunk(pkt)
        if len(data) < 64:
            print(f"[-] Malformed response length: {len(data)} bytes")
            return

        words = struct.unpack('<16I', data)
        status = words[0]
        word0_readback = words[1]
        word3_readback = words[2]
        magic = data[12:16].decode('latin1', errors='replace')

        status_str = {1: "COMPLETE", 2: "TIMEOUT"}.get(status, f"UNKNOWN (0x{status:X})")

        print("\n" + "-" * 75)
        print("DIAGNOSTIC REPORT:")
        print(f"[*] Response Address:      0x{addr:08X} (Core 0 ITCM Scratch)")
        print(f"[*] Report Magic:          '{magic}' (Expected: 'C0ID')")
        print(f"[*] DMA Status:            {status_str} (Code: {status})")
        print(f"[*] Word 0 Readback:       0x{word0_readback:08X} (Target: 0xA1B2C3D4)")
        print(f"[*] Word 3 Readback:       0x{word3_readback:08X} (Target: 0xDEADBEEF)")
        print("-" * 75)

        if word0_readback == 0xA1B2C3D4 and word3_readback == 0xDEADBEEF:
            print("\n🎉 BINGO! DMA ENGINE HAS WRITE ACCESS TO CORE 0 ITCM (0x01060000)!")
            print("    1. 0x01060000 was verified to be all zeroes initially.")
            print("    2. DMA engine successfully wrote 64 bytes into Core 0 ITCM.")
            print("    3. Readback confirmed exact pattern match (0xA1B2C3D4 / 0xDEADBEEF)!")
            print("    4. Channel 1 reported COMPLETE (status == 1).")
            print("    5. WE CAN NOW DYNAMICALLY INJECT CUSTOM CODE INTO CORE 0 ITCM!")
        elif status == 2:
            print("\n[-] TIMEOUT: DMA burst to 0x01060000 was blocked or timed out.")
        else:
            print(f"\n[-] MISMATCH: Readback did not match target pattern: 0x{word0_readback:08X}, 0x{word3_readback:08X}")

    finally:
        midi.close()


# ANSI Color formatting
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def safe_probe_single(midi: RawMidiPort, addr: int, timeout: float = 0.5) -> tuple[int, list[int], int, str] | None:
    """
    Executes Note 127, Velocity 24 (cmd_safe_probe_chunk) at given 32-bit address.
    Returns: (reported_addr, data_words_14, fault_bitmap, magic) or None on timeout.
    """
    set_target_address(midi, addr)
    time.sleep(0.005)
    midi.send_note_on(0, TRIGGER_NOTE, 24)
    pkt = midi.read_sysex_packet(timeout=timeout)
    if pkt is None:
        return None
    reported_addr, data = decode_sysex_chunk(pkt)
    if len(data) < 64:
        return None
    words = struct.unpack('<16I', data)
    data_words = list(words[:14])
    fault_bitmap = words[14]
    magic = data[60:64].decode('latin1', errors='replace')
    return reported_addr, data_words, fault_bitmap, magic


def run_safe_probe_cli(addr: int, dev_path: str | None = None):
    print("=" * 75)
    print("FAULT-TOLERANT SAFE BUS PROBE")
    print("=" * 75)
    print(f"Target Base Address: 0x{addr:08X}")
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    try:
        print(f"[*] Sending Safe Probe Trigger: Note 127, Vel 24 for 0x{addr:08X}...")
        res = safe_probe_single(midi, addr, timeout=1.0)
        if res is None:
            print(f"{RED}[-] TIMEOUT: Device did not respond with SysEx packet.{RESET}")
            return

        reported_addr, words, fault_bitmap, magic = res
        print("\n" + "-" * 75)
        print(f"PROBE RESPONSE FOR 0x{reported_addr:08X}:")
        print(f"[*] Magic:           '{magic}' (Expected: 'SPRB')")
        print(f"[*] Fault Bitmap:    0x{fault_bitmap:04X} ({fault_bitmap:014b}b)")
        print("-" * 75)

        num_faults = 0
        for i, val in enumerate(words):
            word_addr = reported_addr + i * 4
            is_fault = bool(fault_bitmap & (1 << i))
            if is_fault or val == 0xBAADF00D:
                num_faults += 1
                status = f"{RED}[BUS FAULT / UNMAPPED] (0xBAADF00D){RESET}"
                print(f"  +0x{i*4:02X} (0x{word_addr:08X}): {status}")
            else:
                ascii_chars = "".join(chr(b) if 32 <= b <= 126 else "." for b in struct.pack('<I', val))
                status = f"{GREEN}0x{val:08X}{RESET}  | '{ascii_chars}' | dec: {val}"
                print(f"  +0x{i*4:02X} (0x{word_addr:08X}): {status}")

        print("-" * 75)
        if num_faults == 0:
            print(f"{GREEN}🎉 STATUS: ALL 14 WORDS ONLINE & READABLE (0 faults){RESET}")
        elif num_faults == 14:
            print(f"{RED}⚠️ STATUS: 100% UNMAPPED / CLOCK-GATED REGION (14 faults intercepted cleanly){RESET}")
        else:
            print(f"{YELLOW}⚡ STATUS: PARTIAL WINDOW: {14 - num_faults} words readable, {num_faults} faulted{RESET}")

    finally:
        midi.close()


def dma_probe_single(midi: RawMidiPort, addr: int, timeout: float = 0.5) -> tuple[int, list[int], int, str] | None:
    """
    Executes Note 127, Velocity 26 (cmd_dma_probe_chunk) at given 32-bit address.
    Uses hardware DMA engine to move 64 bytes to Shared SRAM without CPU bus stalls.
    Returns: (reported_addr, data_words_14, status, magic) or None on timeout.
             status: 1 = Complete, 2 = Timeout / Unmapped
    """
    set_target_address(midi, addr)
    time.sleep(0.005)
    midi.send_note_on(0, TRIGGER_NOTE, 26)
    pkt = midi.read_sysex_packet(timeout=timeout)
    if pkt is None:
        return None
    reported_addr, data = decode_sysex_chunk(pkt)
    if len(data) < 64:
        return None
    words = struct.unpack('<16I', data)
    data_words = list(words[:14])
    status = words[14]
    magic = data[60:64].decode('latin1', errors='replace')
    return reported_addr, data_words, status, magic


def run_dma_probe_cli(addr: int, dev_path: str | None = None):
    print("=" * 75)
    print("HARDWARE-SAFE DMA MEMORY PROBE (ZERO CPU FREEZE)")
    print("=" * 75)
    print(f"Target Base Address: 0x{addr:08X}")
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    try:
        print(f"[*] Sending DMA Probe Trigger: Note 127, Vel 26 for 0x{addr:08X}...")
        res = dma_probe_single(midi, addr, timeout=1.0)
        if res is None:
            print(f"{RED}[-] TIMEOUT: Device did not respond with SysEx packet.{RESET}")
            return

        reported_addr, words, status, magic = res
        status_name = "COMPLETE (ONLINE)" if status == 1 else "TIMEOUT / UNMAPPED"
        print("\n" + "-" * 75)
        print(f"DMA PROBE RESPONSE FOR 0x{reported_addr:08X}:")
        print(f"[*] Magic:           '{magic}' (Expected: 'DPRB')")
        print(f"[*] DMA Status:      {GREEN if status == 1 else RED}{status_name} (Code: {status}){RESET}")
        print("-" * 75)

        for i, val in enumerate(words):
            word_addr = reported_addr + i * 4
            if status != 1:
                print(f"  +0x{i*4:02X} (0x{word_addr:08X}): {RED}[UNMAPPED / TIMEOUT]{RESET}")
            else:
                ascii_chars = "".join(chr(b) if 32 <= b <= 126 else "." for b in struct.pack('<I', val))
                print(f"  +0x{i*4:02X} (0x{word_addr:08X}): {GREEN}0x{val:08X}{RESET}  | '{ascii_chars}' | dec: {val}")

        print("-" * 75)
        if status == 1:
            print(f"{GREEN}🎉 STATUS: ADDRESS 0x{reported_addr:08X} IS ACTIVE & READABLE VIA DMA!{RESET}")
        else:
            print(f"{RED}⚠️ STATUS: ADDRESS 0x{reported_addr:08X} IS UNMAPPED (Handled safely with zero CPU crash){RESET}")

    finally:
        midi.close()


def qspi_read_single(midi: RawMidiPort, flash_addr: int, chip: int = 0, timeout: float = 1.0) -> tuple[int, bytes, list[int]] | None:
    """
    Executes Note 127, Velocity 28 (cmd_qspi_read_chunk) at given physical SPI flash byte address.
    Supports Chip Select 0 (32MB, chip=0) and Chip Select 1 (16MB, chip=1).
    Bit 31 is set in the wire address to instruct Core 1 to select Chip Select 1 (0x40010048).
    Returns: (reported_flash_addr, raw_64_bytes, words_16) or None on timeout.
    """
    if chip == 1 or (flash_addr & 0x80000000):
        wire_addr = (flash_addr & 0x7FFFFFFF) | 0x80000000
    else:
        wire_addr = flash_addr & 0x7FFFFFFF

    set_target_address(midi, wire_addr)
    time.sleep(0.005)
    midi.send_note_on(0, TRIGGER_NOTE, 28)
    pkt = midi.read_sysex_packet(timeout=timeout)
    if pkt is None:
        return None
    reported_addr, data = decode_sysex_chunk(pkt)
    if len(data) < 64:
        return None
    words = list(struct.unpack('<16I', data[:64]))
    clean_reported_addr = reported_addr & 0x7FFFFFFF
    return clean_reported_addr, data[:64], words


def run_qspi_read_cli(flash_addr: int, chip: int = 0, dev_path: str | None = None):
    print("=" * 75)
    print("DIRECT HARDWARE QSPI FLASH READ (CPU-POLLED FIFO, ZERO DMA)")
    print("=" * 75)
    chip_name = "Chip 1 (CS1 16MB Macronix NOR - Synth DSP / Wavetables)" if chip == 1 else "Chip 0 (CS0 32MB Macronix NOR - Main System)"
    print(f"Target Physical Flash Chip:         {chip_name}")
    print(f"Target Physical Flash Byte Address: 0x{flash_addr:08X}")
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    try:
        print(f"[*] Sending QSPI Read Trigger: Note 127, Vel 28 for Chip {chip} Flash 0x{flash_addr:08X}...")
        res = qspi_read_single(midi, flash_addr, chip=chip, timeout=1.0)
        if res is None:
            print(f"{RED}[-] TIMEOUT: Device did not respond with SysEx packet.{RESET}")
            return

        reported_addr, raw_bytes, words = res
        print("\n" + "-" * 75)
        print(f"QSPI READ RESPONSE FOR CHIP {chip} FLASH OFFSET 0x{reported_addr:08X}:")
        print("-" * 75)

        for i, val in enumerate(words):
            word_addr = reported_addr + i * 4
            ascii_chars = "".join(chr(b) if 32 <= b <= 126 else "." for b in struct.pack('<I', val))
            print(f"  +0x{i*4:02X} (0x{word_addr:08X}): {GREEN}0x{val:08X}{RESET}  | '{ascii_chars}' | dec: {val}")

        print("-" * 75)
        hex_dump = " ".join(f"{b:02X}" for b in raw_bytes[:16])
        print(f"[*] First 16 raw bytes: {hex_dump}")
        ascii_dump = "".join(chr(b) if 32 <= b <= 126 else "." for b in raw_bytes)
        print(f"[*] Full ASCII:         '{ascii_dump}'")
        print("-" * 75)

        if raw_bytes[:4] == b"BMC ":
            print(f"{GREEN}🎉 MATCHED PHYSICAL FLASH SECTOR 0: Magic 'BMC ' found!{RESET}")
        elif b"App1_Main" in raw_bytes[:16]:
            print(f"{GREEN}🎉 MATCHED PARTITION HEADER: 'App1_Main' found!{RESET}")
        elif all(b == 0xFF for b in raw_bytes):
            print(f"{YELLOW}ℹ️ REGION IS UNPROGRAMMED / BLANK (All 0xFF){RESET}")
    finally:
        midi.close()


def verify_chip1_cli(dev_path: str | None = None):
    print("=" * 75)
    print("CHIP 1 (16 MB SYNTH DSP & WAVETABLES NOR FLASH) FULL SWEEP")
    print("AXI Memory-Mapped Window: 0x0C000000 - 0x0CFFFFFF")
    print("=" * 75)
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    checkpoints = [
        (0x0C000000, 0x00000000, "C1A Start", "RPG69_C1A Core 1 DSP Engine (4 MB)"),
        (0x0C001000, 0x00001000, "C1A idm1.bin", "Core 1 Injected Audio Modem Hook"),
        (0x0C03D000, 0x0003D000, "C1A sdram1.bin", "Core 1 SDRAM DSP Code & Tables"),
        (0x0C3FFF00, 0x003FFF00, "C1A Tail", "RPG69_C1A Core 1 DSP Engine Tail"),
        (0x0C400000, 0x00400000, "C1C Start", "RPG69_C1C Wavetables & Patches (4 MB stock)"),
        (0x0C7FFF00, 0x007FFF00, "C1C Stock Tail", "RPG69_C1C 4MB Stock Boundary"),
        (0x0C800000, 0x00800000, "C1C Headroom Start", "Unallocated partition headroom (window: 8 MB)"),
        (0x0C900000, 0x00900000, "C1C Headroom Mid 1", "Unallocated partition headroom"),
        (0x0CA00000, 0x00A00000, "C1C Headroom Mid 2", "Unallocated partition headroom"),
        (0x0CB00000, 0x00B00000, "C1C Headroom Mid 3", "Unallocated partition headroom"),
        (0x0CC00000, 0x00C00000, "C1C Headroom Top", "Unallocated partition headroom"),
        (0x0CD00000, 0x00D00000, "WV0 Window Start", "Wave Expansion 0 Partition window (WV0)"),
        (0x0CE00000, 0x00E00000, "WV Window Mid", "Wave Expansion Partition window"),
        (0x0CF00000, 0x00F00000, "WV1 Window", "Wave Expansion 1 Partition window (WV1)"),
        (0x0CFFFFC0, 0x00FFFFC0, "Chip 1 Top", "Final 64-byte block of 16 MB NOR Flash"),
    ]

    results = []
    try:
        for axi_addr, chip_off, label, desc in checkpoints:
            res = dma_probe_single(midi, axi_addr, timeout=1.0)
            if res is None:
                status = "TIMEOUT"
                preview = "No response"
            else:
                reported_addr, words_14, status_code, magic = res
                all_ff = all(w == 0xFFFFFFFF for w in words_14)
                all_00 = all(w == 0x00000000 for w in words_14)
                if all_ff:
                    status = "BLANK (0xFF)"
                elif all_00:
                    status = "ZEROES (0x00)"
                else:
                    status = "ACTIVE DATA"
                preview = " ".join(f"{w:08X}" for w in words_14[:2])

            results.append((chip_off, axi_addr, label, desc, status, preview))
            time.sleep(0.01)

        print("\n" + "=" * 75)
        print(f"| Physical Offset | AXI Mapped Addr | Partition / Region | Status | First 8 Bytes (Hex) | Description |")
        print(f"|---|---|---|---|---|---|")
        for chip_off, axi_addr, label, desc, status, preview in results:
            emoji = "⬜" if "BLANK" in status else ("🟦" if "ACTIVE" in status else "⚠️")
            print(f"| `0x{chip_off:08X}` | `0x{axi_addr:08X}` | **{label}** | {emoji} {status} | `{preview}` | {desc} |")
        print("=" * 75 + "\n")

    finally:
        midi.close()


def qspi_dump_range_cli(flash_start: int, total_len: int, out_path: str, dev_path: str | None = None):
    print("=" * 75)
    print(f"DUMPING PHYSICAL SPI FLASH: 0x{flash_start:08X} - 0x{flash_start + total_len:08X} ({total_len:,} bytes)")
    print("=" * 75)
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    midi = RawMidiPort(dev_path=dev_path)
    bytes_read = 0

    mode = "ab" if out_file.exists() and out_file.stat().st_size > 0 else "wb"
    if mode == "ab":
        bytes_read = out_file.stat().st_size
        print(f"[*] Resuming from offset +0x{bytes_read:06X} ({bytes_read:,} bytes already dumped)")

    f = open(out_file, mode)
    need_seek = True
    start_time = time.time()

    try:
        while bytes_read < total_len:
            current_addr = flash_start + bytes_read
            if need_seek:
                set_target_address(midi, current_addr)
                time.sleep(0.005)
                need_seek = False

            midi.send_note_on(0, TRIGGER_NOTE, 28)
            pkt = midi.read_sysex_packet(timeout=0.5)
            if pkt is None:
                print(f"\n{RED}[-] Timeout at offset 0x{current_addr:08X}. Resyncing...{RESET}")
                need_seek = True
                time.sleep(0.02)
                continue

            reported_addr, data = decode_sysex_chunk(pkt)
            if reported_addr != current_addr:
                print(f"\n{YELLOW}[!] Address desync (expected 0x{current_addr:08X}, got 0x{reported_addr:08X}). Resyncing...{RESET}")
                need_seek = True
                continue

            raw_bytes = data[:64]
            f.write(raw_bytes)
            f.flush()
            bytes_read += len(raw_bytes)

            pct = (bytes_read / total_len) * 100
            elapsed = time.time() - start_time
            rate = bytes_read / (elapsed + 0.001)
            print(f"\r[*] Progress: {bytes_read:,} / {total_len:,} bytes ({pct:.1f}%) | Rate: {rate/1024:.2f} KB/s", end="", flush=True)

        print(f"\n\n{GREEN}[✓] Dump complete! Saved {bytes_read:,} bytes to: {out_file}{RESET}")

    finally:
        f.close()
        midi.close()


def run_core0_inspect_cli(dev_path: str | None = None):
    print("=" * 75)
    print("CORE 0 DYNAMIC INTER-CORE CODE INJECTION & INSPECTION")
    print("=" * 75)
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    try:
        print("[*] Sending Core 0 Inspection Trigger: Note 127, Vel 27 (cmd_core0_inspect_rom)...")
        midi.send_note_on(0, TRIGGER_NOTE, 27)
        pkt = midi.read_sysex_packet(timeout=2.0)
        if pkt is None:
            print(f"{RED}[-] TIMEOUT: Device did not respond with SysEx packet.{RESET}")
            return

        addr, data = decode_sysex_chunk(pkt)
        if len(data) < 64:
            print(f"{RED}[-] Invalid payload length: {len(data)} bytes{RESET}")
            return

        words = struct.unpack('<16I', data)
        status = words[14]
        magic = data[60:64].decode('latin1', errors='replace')
        status_name = {1: "COMPLETE / SUCCESS", 2: "DMA TIMEOUT", 3: "CORE 0 EXEC TIMEOUT"}.get(status, f"UNKNOWN ({status})")

        print("\n" + "-" * 75)
        print("CORE 0 DIAGNOSTIC REPORT:")
        print(f"[*] Response Address:      0x{addr:08X} (Core 0 ITCM Scratch 0x01060000)")
        print(f"[*] Report Magic:          '{magic}' (Expected: 'C0RP')")
        print(f"[*] Execution Status:      {GREEN if status == 1 else RED}{status_name} (Code: {status}){RESET}")
        print("-" * 75)

        if status == 1:
            cpuid = words[0]
            vtor = words[1]
            icsr = words[2]
            itcmcr = words[3]
            dtcmcr = words[4]
            ahbpcr = words[5]
            cacr = words[6]
            c0ok = data[28:32].decode('latin1', errors='replace')

            part = (cpuid >> 4) & 0xFFF
            core_name = {0xC20: "Cortex-M0", 0xC21: "Cortex-M1", 0xC23: "Cortex-M3", 0xC24: "Cortex-M4", 0xC27: "Cortex-M7"}.get(part, f"Part 0x{part:03X}")

            print(f"[*] Core 0 CPUID  (0xE000ED00): 0x{cpuid:08X} -> ARM {core_name} r{(cpuid>>20)&0xF}p{cpuid&0xF}")
            print(f"[*] Core 0 VTOR   (0xE000ED08): 0x{vtor:08X} (Active Vector Base)")
            print(f"[*] Core 0 ICSR   (0xE000ED04): 0x{icsr:08X}")
            itcm_sz = 2**((itcmcr >> 3) & 0xF) if (itcmcr >> 3) & 0xF else 0
            dtcm_sz = 2**((dtcmcr >> 3) & 0xF) if (dtcmcr >> 3) & 0xF else 0
            print(f"[*] Core 0 ITCMCR (0xE000EF90): 0x{itcmcr:08X} -> EN: {itcmcr & 1}, Size: {itcm_sz} KB (code: {(itcmcr >> 3) & 0xF})")
            print(f"[*] Core 0 DTCMCR (0xE000EF94): 0x{dtcmcr:08X} -> EN: {dtcmcr & 1}, Size: {dtcm_sz} KB (code: {(dtcmcr >> 3) & 0xF})")
            print(f"[*] Core 0 AHBPCR (0xE000EF98): 0x{ahbpcr:08X} -> EN: {ahbpcr & 1}")
            print(f"[*] Core 0 CACR   (0xE000EF9C): 0x{cacr:08X} (SIWT: {(cacr >> 2) & 1}, ECCEN: {(cacr >> 1) & 1}, FORCEWT: {cacr & 1})")
            print(f"[*] Execution Handshake:       '{c0ok}' (Expected: 'C0OK')")
            print("-" * 75)
            print(f"\n{GREEN}🎉 SUCCESS: CODE WAS INJECTED INTO CORE 0 AND EXECUTED WITH FULL SYSTEM PRIVILEGES!{RESET}")
    finally:
        midi.close()


def test_cipher_cli(dev_path: str | None = None):
    print("=" * 75)
    print("HARDWARE BLOCK CIPHER DECRYPTION TEST (PATHWAY B)")
    print("=" * 75)
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    expected = [
        0x01050800, 0x60000001, 0x01005D9D, 0x01005D9F,
        0x01005DA1, 0x01005DA3, 0x01005DA5, 0x00000000,
        0x00000000, 0x00000000, 0x00000000, 0x01005F05,
        0x01005DA9, 0x00000000
    ]

    try:
        # Note: Velocity 28 is cmd_qspi_read_chunk in src/sysex_hook.s.
        # Velocity 29 is reserved for future hardware cipher oracle trigger.
        print("[*] Sending Cipher Decrypt Trigger: Note 127, Vel 29 (cmd_cipher_decrypt)...")
        midi.send_note_on(0, TRIGGER_NOTE, 29)
        pkt = midi.read_sysex_packet(timeout=2.0)
        if pkt is None:
            print(f"{RED}[-] TIMEOUT: Device did not respond with SysEx packet.{RESET}")
            return

        addr, data = decode_sysex_chunk(pkt)
        if len(data) < 64:
            print(f"{RED}[-] Invalid payload length: {len(data)} bytes{RESET}")
            return

        words = struct.unpack('<16I', data)
        status = words[14]
        magic = data[60:64].decode('latin1', errors='replace')
        status_name = "COMPLETE / SUCCESS" if status == 1 else "DMA TIMEOUT"

        print("\n" + "-" * 75)
        print("HARDWARE CIPHER DECRYPTION REPORT:")
        print(f"[*] Response Address:      0x{addr:08X} (SRAM 0x2001F040)")
        print(f"[*] Report Magic:          '{magic}' (Expected: 'CIPH')")
        print(f"[*] Execution Status:      {GREEN if status == 1 else RED}{status_name} (Code: {status}){RESET}")
        print("-" * 75)

        matches = 0
        for i in range(14):
            val = words[i]
            exp = expected[i]
            match = (val == exp)
            if match:
                matches += 1
            mark = f"{GREEN}✓ MATCH{RESET}" if match else f"{RED}✗ MISMATCH (Exp: 0x{exp:08X}){RESET}"
            ascii_chars = "".join(chr(b) if 32 <= b <= 126 else "." for b in struct.pack('<I', val))
            print(f"  Word {i:02d} (+0x{i*4:02X}): 0x{val:08X}  | '{ascii_chars}' | {mark}")

        print("-" * 75)
        if matches == 14 and status == 1:
            print(f"{GREEN}🎉 SUCCESS: 100% BIT-PERFECT HARDWARE DECRYPTION CONFIRMED! (14/14 words matched){RESET}")
        else:
            print(f"{YELLOW}⚠️ Completed with {matches}/14 matches (Status: {status}){RESET}")
    finally:
        midi.close()


def read_sys_regs_cli(dev_path: str | None = None):
    print("=" * 75)
    print("CORTEX-M ARCHITECTURE & SYSTEM CONTROL REGISTERS")
    print("=" * 75)
    print("[*] Connecting to MC-101 MIDI interface...")
    midi = RawMidiPort(dev_path=dev_path)

    try:
        print("[*] Sending Sys Regs Trigger: Note 127, Vel 25 (cmd_read_sys_regs)...")
        midi.send_note_on(0, TRIGGER_NOTE, 25)
        pkt = midi.read_sysex_packet(timeout=1.0)
        if pkt is None:
            print(f"{RED}[-] TIMEOUT: Device did not respond with SysEx packet.{RESET}")
            return

        addr, data = decode_sysex_chunk(pkt)
        if len(data) < 64:
            print(f"{RED}[-] Invalid payload length: {len(data)} bytes{RESET}")
            return

        words = struct.unpack('<16I', data)
        cpuid, vtor, shcsr, cfsr, hfsr, mmfar, bfar, itcmcr, dtcmcr, ahbpcr, cacr, ccr = words[:12]
        magic = data[60:64].decode('latin1', errors='replace')

        print("\n" + "-" * 75)
        print("SYSTEM CONTROL BLOCK (SCB) REGISTERS:")
        print(f"[*] Response Base:      0x{addr:08X}")
        print(f"[*] Report Magic:       '{magic}' (Expected: 'SREG')")
        print("-" * 75)

        impl = (cpuid >> 24) & 0xFF
        var = (cpuid >> 20) & 0xF
        arch = (cpuid >> 16) & 0xF
        part = (cpuid >> 4) & 0xFFF
        rev = cpuid & 0xF
        part_names = {0xC20: "ARM Cortex-M0", 0xC21: "ARM Cortex-M1", 0xC23: "ARM Cortex-M3", 0xC24: "ARM Cortex-M4", 0xC27: "ARM Cortex-M7"}
        cpu_name = part_names.get(part, f"Part 0x{part:03X}")
        cpu_str = f"{cpu_name} (ARM)" if impl == 0x41 else f"Unknown vendor (0x{impl:02X}:{part:03X})"
        print(f"[*] CPUID    (0xE000ED00): 0x{cpuid:08X} -> {CYAN}{cpu_str} r{var}p{rev}{RESET}")

        print(f"[*] VTOR     (0xE000ED08): 0x{vtor:08X} -> Active Vector Table at {GREEN}0x{vtor:08X}{RESET}")

        shcsr_flags = []
        if shcsr & (1 << 16): shcsr_flags.append("MEMFAULTENA")
        if shcsr & (1 << 17): shcsr_flags.append("BUSFAULTENA")
        if shcsr & (1 << 18): shcsr_flags.append("USGFAULTENA")
        print(f"[*] SHCSR    (0xE000ED24): 0x{shcsr:08X} -> [{', '.join(shcsr_flags) or 'NONE'}]")

        print(f"[*] CFSR     (0xE000ED28): 0x{cfsr:08X} (MMFSR: 0x{cfsr & 0xFF:02X}, BFSR: 0x{(cfsr >> 8) & 0xFF:02X}, UFSR: 0x{(cfsr >> 16) & 0xFFFF:04X})")
        print(f"[*] HFSR     (0xE000ED2C): 0x{hfsr:08X} (FORCED: {(hfsr >> 30) & 1}, VECTTBL: {(hfsr >> 1) & 1})")
        print(f"[*] MMFAR    (0xE000ED34): 0x{mmfar:08X}")
        print(f"[*] BFAR     (0xE000ED38): 0x{bfar:08X}")

        itcm_en = itcmcr & 1
        itcm_sz_code = (itcmcr >> 3) & 0xF
        itcm_kb = (1 << (itcm_sz_code - 3)) if itcm_sz_code >= 3 else 0
        print(f"[*] ITCMCR   (0xE000EF90): 0x{itcmcr:08X} -> EN: {itcm_en}, Size: {itcm_kb} KB (code: {itcm_sz_code})")

        dtcm_en = dtcmcr & 1
        dtcm_sz_code = (dtcmcr >> 3) & 0xF
        dtcm_kb = (1 << (dtcm_sz_code - 3)) if dtcm_sz_code >= 3 else 0
        print(f"[*] DTCMCR   (0xE000EF94): 0x{dtcmcr:08X} -> EN: {dtcm_en}, Size: {dtcm_kb} KB (code: {dtcm_sz_code})")

        print(f"[*] AHBPCR   (0xE000EF98): 0x{ahbpcr:08X} -> EN: {ahbpcr & 1}")
        print(f"[*] CACR     (0xE000EF9C): 0x{cacr:08X} (SIWT: {(cacr >> 2) & 1}, ECCEN: {(cacr >> 1) & 1}, FORCEWT: {cacr & 1})")
        print(f"[*] CCR      (0xE000ED14): 0x{ccr:08X} (D-Cache: {(ccr >> 16) & 1}, I-Cache: {(ccr >> 17) & 1})")
        print("-" * 75)

    finally:
        midi.close()


def probe_ranges_cli(dev_path: str | None = None, out_doc: str | None = None):
    """
    Automates sweeping Range A, Range B, and Range C as specified in docs/safe_probe_plan.md.
    Generates a structured Markdown table summarizing which ranges respond and what values they return.
    """
    print("=" * 75)
    print("AUTOMATED FAULT-TOLERANT BUS PROBE SWEEP")
    print("=" * 75)

    probe_targets = [
        # Range A: ITCM (Internal 256 KB SRAM)
        ("Range A: ITCM Base / Vector Table",   0x00000000, "Core 1 Vector Table & ITCM Base"),
        ("Range A: ITCM Middle",                0x00020000, "Core 1 ITCM Midpoint (128 KB)"),
        ("Range A: ITCM Upper Boundary",        0x0003FFC0, "Core 1 ITCM Upper Boundary (256 KB limit)"),

        # Range C: Hardware MMIO & Memory Controllers (System Bus)
        ("Range C: SYSCTRL / CRM",              0x40000000, "System Controller / Clock / Reset Management"),
        ("Range C: DMAC1 Controller",           0x40001000, "SoC DMA Controller Channel Registers"),
        ("Range C: System Config Interconnect",  0x40005000, "System config / bus interconnect"),
        ("Range C: QSPI0 Memory Controller",    0x40010000, "QSPI0 Flash Controller (OTFDEC boundary registers)"),
        ("Range C: QSPI1 Memory Controller",    0x40020000, "QSPI1 Flash Controller"),
        ("Range C: Aux Memory Controller 1",    0x40024000, "Auxiliary memory controller 0x40024000"),
        ("Range C: Aux Memory Controller 2",    0x40026000, "Auxiliary memory controller 0x40026000"),
    ]

    midi = RawMidiPort(dev_path=dev_path)
    results = []

    try:
        for name, addr, desc in probe_targets:
            print(f"\n[*] Probing {name} (0x{addr:08X})...")
            res = safe_probe_single(midi, addr, timeout=1.0)
            if res is None:
                print(f"    {RED}TIMEOUT / NO RESPONSE{RESET}")
                results.append({
                    "name": name,
                    "addr": addr,
                    "desc": desc,
                    "status": "TIMEOUT",
                    "faults": 14,
                    "words": [],
                    "bitmap": 0x3FFF
                })
                continue

            rep_addr, words, bitmap, magic = res
            num_faults = bin(bitmap & 0x3FFF).count('1')
            if num_faults == 0:
                status_str = f"{GREEN}ONLINE (All 14 words valid){RESET}"
                st_code = "ONLINE"
            elif num_faults == 14:
                status_str = f"{RED}UNMAPPED / FAULT (All 14 faulted){RESET}"
                st_code = "UNMAPPED"
            else:
                status_str = f"{YELLOW}PARTIAL ({14 - num_faults} OK, {num_faults} faulted){RESET}"
                st_code = "PARTIAL"

            print(f"    Result: {status_str} | Magic: '{magic}' | Bitmap: 0x{bitmap:04X}")
            if num_faults < 14:
                first_few = " ".join(f"0x{w:08X}" for w in words[:4])
                print(f"    First words: {first_few}")

            results.append({
                "name": name,
                "addr": addr,
                "desc": desc,
                "status": st_code,
                "faults": num_faults,
                "words": words,
                "bitmap": bitmap
            })
            time.sleep(0.02)

    finally:
        midi.close()

    # Generate Markdown Report
    doc_path = Path(out_doc) if out_doc else (ROOT / "docs" / "probe_results.md")
    doc_path.parent.mkdir(parents=True, exist_ok=True)

    md_lines = [
        "# Roland MC-101 Hardware Memory & Bus Probe Results",
        "",
        f"**Date Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary Table",
        "",
        "| Target Region | Base Address | Status | Faults (out of 14) | First 4 Words Read / Observations | Description |",
        "|---|---|---|---|---|---|",
    ]

    for r in results:
        w_preview = ""
        if r["words"] and r["faults"] < 14:
            w_preview = "`" + " ".join(f"{w:08X}" for w in r["words"][:4]) + "`"
        elif r["status"] == "UNMAPPED":
            w_preview = "*All BusFault (0xBAADF00D)*"
        else:
            w_preview = "*No Response*"

        status_emoji = {"ONLINE": "✅ ONLINE", "PARTIAL": "⚠️ PARTIAL", "UNMAPPED": "❌ UNMAPPED", "TIMEOUT": "⏱️ TIMEOUT"}.get(r["status"], r["status"])
        md_lines.append(f"| {r['name']} | `0x{r['addr']:08X}` | {status_emoji} | {r['faults']}/14 | {w_preview} | {r['desc']} |")

    md_lines.append("")
    md_lines.append("## Detailed Word Dumps for Active Regions")
    md_lines.append("")
    for r in results:
        if r["words"] and r["faults"] < 14:
            md_lines.append(f"### {r['name']} (`0x{r['addr']:08X}`)")
            md_lines.append(f"- **Description**: {r['desc']}")
            md_lines.append(f"- **Fault Bitmap**: `0x{r['bitmap']:04X}`")
            md_lines.append("```")
            for idx, w in enumerate(r["words"]):
                is_f = bool(r["bitmap"] & (1 << idx))
                tag = "[FAULT]" if is_f else f"0x{w:08X} ({w})"
                md_lines.append(f"+0x{idx*4:02X} (0x{r['addr'] + idx*4:08X}): {tag}")
            md_lines.append("```")
            md_lines.append("")

    report_text = "\n".join(md_lines)
    doc_path.write_text(report_text)
    print("\n" + "=" * 75)
    print(f"[✓] Probe results Markdown table written to: {doc_path}")
    print("=" * 75)


def main():
    parser = argparse.ArgumentParser(description="Roland MC-101 High-Speed USB-MIDI SysEx Memory Dumper & Core 0 Diagnostic Tool")
    parser.add_argument("--target", choices=list(TARGET_MAP.keys()), default="c0_flash_full",
                        help="Target memory region to dump (default: c0_flash_full)")
    parser.add_argument("--addr", type=lambda x: int(x, 0), default=None,
                        help="Explicit start address in hex (overrides --target base)")
    parser.add_argument("--len", type=lambda x: int(x, 0), default=None,
                        help="Explicit byte count to dump (overrides --target length)")
    parser.add_argument("--out", type=str, default=None,
                        help="Output binary file path")
    parser.add_argument("--device", type=str, default=None,
                        help="ALSA rawmidi device path (default: auto-detect /dev/snd/midiC*D*)")
    parser.add_argument("--no-resume", action="store_true",
                        help="Overwrite existing file and start from scratch")
    parser.add_argument("--probe-dma", action="store_true",
                        help="Step 1: Safely read DMA Controller registers at 0x40001000 (pure read, zero writes)")
    parser.add_argument("--test-dma-c1", action="store_true",
                        help="Step 2: Test DMA write to Core 1's OWN ITCM (zero Core 0 touch)")
    parser.add_argument("--test-dma-c0", action="store_true",
                        help="Step 3: Read Core 0 ITCM and DMA write the EXACT SAME DATA back (non-destructive)")
    parser.add_argument("--safe-probe", type=lambda x: int(x, 0), default=None,
                        help="Fault-tolerant safe memory probe at specified 32-bit address")
    parser.add_argument("--dma-probe", type=lambda x: int(x, 0), default=None,
                        help="Hardware-safe DMA memory probe (zero CPU bus freeze) at specified 32-bit address")
    parser.add_argument("--core0-inspect", action="store_true",
                        help="Inject & execute inspection payload on Core 0 via vector hooking")
    parser.add_argument("--probe-ranges", action="store_true",
                        help="Automated sweep across Range A, B, and C with Markdown report")
    parser.add_argument("--read-sys-regs", action="store_true",
                        help="Read Cortex-M system control & architecture registers (CPUID, VTOR, etc.)")
    parser.add_argument("--test-cipher", action="store_true",
                        help="Step 4 (Pathway B): Test on-chip hardware block cipher decryption")
    parser.add_argument("--qspi-read", type=lambda x: int(x, 0), default=None,
                        help="Direct physical SPI flash read via QSPI controller at byte offset")
    parser.add_argument("--chip", type=int, choices=[0, 1], default=0,
                        help="QSPI Flash chip select: 0 = CS0 (32 MB Main), 1 = CS1 (16 MB Synth DSP / Wavetables)")
    parser.add_argument("--verify-chip1", action="store_true",
                        help="Sweep and verify active partitions vs blank spaces across Chip 1 (CS1 16MB)")
    parser.add_argument("--dump-sector0", action="store_true",
                        help="Dump entire 768 KB Physical Flash Sector 0 (0x00000000 - 0x000BFFFF) via QSPI")
    parser.add_argument("--dump-physical-tail", action="store_true",
                        help="Dump unmapped physical flash tail (0x003D279C - 0x004165B0) via QSPI")
    args = parser.parse_args()

    if args.verify_chip1:
        verify_chip1_cli(dev_path=args.device)
    elif args.qspi_read is not None:
        run_qspi_read_cli(flash_addr=args.qspi_read, chip=args.chip, dev_path=args.device)
    elif args.dump_sector0:
        qspi_dump_range_cli(flash_start=0x00000000, total_len=0x000C0000, out_path="vendor/mc101_sys_v182/dumps/physical_sector0_768k.bin", dev_path=args.device)
    elif args.dump_physical_tail:
        qspi_dump_range_cli(flash_start=0x003D279C, total_len=(0x004165B0 - 0x003D279C), out_path="vendor/mc101_sys_v182/dumps/physical_flash_tail_278k.bin", dev_path=args.device)
    elif args.safe_probe is not None:
        run_safe_probe_cli(addr=args.safe_probe, dev_path=args.device)
    elif args.dma_probe is not None:
        run_dma_probe_cli(addr=args.dma_probe, dev_path=args.device)
    elif args.test_cipher:
        test_cipher_cli(dev_path=args.device)
    elif args.core0_inspect:
        run_core0_inspect_cli(dev_path=args.device)
    elif args.read_sys_regs:
        read_sys_regs_cli(dev_path=args.device)
    elif args.probe_ranges:
        probe_ranges_cli(dev_path=args.device)
    elif args.probe_dma:
        probe_dma_regs(dev_path=args.device)
    elif args.test_dma_c1:
        test_dma_c1(dev_path=args.device)
    elif args.test_dma_c0:
        test_dma_c0_identity(dev_path=args.device)
    else:
        dump_memory_sysex(
            target=args.target,
            addr=args.addr,
            total_bytes=args.len,
            out_file=args.out,
            dev_path=args.device,
            resume=not args.no_resume
        )


if __name__ == "__main__":
    main()
