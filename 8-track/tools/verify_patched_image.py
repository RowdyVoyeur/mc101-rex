#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v.2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""Capstone-based post-patch verifier for App1_Main_decrypted.8track.bin."""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
from pathlib import Path

try:
    import capstone
except ImportError:
    capstone = None

BASE_VA = 0x60000000


def decode_bw(img: bytes, va: int) -> int:
    """Decode an unconditional B.W T3 at `va` and return its target VA."""
    hw1, hw2 = struct.unpack_from("<HH", img, va - BASE_VA)
    assert (hw1 & 0xF800) == 0xF000 and (hw2 & 0xD000) == 0x9000, f"unconditional b.w (T3) expected at {va:#x}"
    s = (hw1 >> 10) & 1
    i1 = 1 - (s ^ ((hw2 >> 13) & 1))
    i2 = 1 - (s ^ ((hw2 >> 11) & 1))
    raw = (s << 23) | (i1 << 22) | (i2 << 21) | ((hw1 & 0x3FF) << 11) | (hw2 & 0x7FF)
    return va + 4 + (raw * 2 - (1 << 25 if s else 0))


def decode_bl(img: bytes, va: int) -> int:
    """Decode a 32-bit BL at `va` and return its target VA (bit 0 stripped)."""
    hw1, hw2 = struct.unpack_from("<HH", img, va - BASE_VA)
    assert (hw1 & 0xF800) == 0xF000 and (hw2 & 0xD000) == 0xD000, f"bl expected at {va:#x}"
    s = (hw1 >> 10) & 1
    i1 = 1 - (s ^ ((hw2 >> 13) & 1))
    i2 = 1 - (s ^ ((hw2 >> 11) & 1))
    raw = (s << 24) | (i1 << 23) | (i2 << 22) | ((hw1 & 0x3FF) << 12) | ((hw2 & 0x7FF) << 1)
    return (va + 4 + raw - (1 << 25 if s else 0)) & ~1


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify patched 8-track firmware image.")
    parser.add_argument("--stock", required=True, type=Path)
    parser.add_argument("--patched", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    stock = args.stock.read_bytes()
    patched = args.patched.read_bytes()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    if len(stock) != len(patched):
        print(f"[-] Image size mismatch: {len(stock)} vs {len(patched)}", file=sys.stderr)
        return 1

    # 1. Verify only declared patch ranges changed
    allowed = bytearray(len(stock))
    sites_by_id = {s["id"]: s for s in manifest["sites"]}
    active_sites = [s for s in manifest["sites"] if s.get("patch")]
    for s in active_sites:
        va = int(s["address"], 0)
        length = int(s["length"])
        off = va - BASE_VA
        allowed[off : off + length] = b"\x01" * length
        want = bytes.fromhex(s["patch"])
        got = patched[off : off + length]
        if got != want:
            print(f"[-] Patch site {s['id']} @0x{va:08X} does not match patch bytes", file=sys.stderr)
            return 1

    for idx, (a, b, ok) in enumerate(zip(stock, patched, allowed)):
        if a != b and not ok:
            print(f"[-] Unexpected byte modification at VA 0x{BASE_VA + idx:08X}", file=sys.stderr)
            return 1

    # 2. Verify SYSTEM(MIDI) descriptor and 23-entry table
    desc_off = 0x6021A214 - BASE_VA
    tbl_ptr, tbl_cnt = struct.unpack_from("<II", patched, desc_off)
    assert tbl_ptr == 0x602D2800 and tbl_cnt == 23, f"Bad SYSTEM(MIDI) descriptor: {hex(tbl_ptr)}, {tbl_cnt}"
    tbl_off = tbl_ptr - BASE_VA
    entries = [struct.unpack_from("<7I", patched, tbl_off + i * 28) for i in range(tbl_cnt)]
    trk_ch_pids = [e[1] for e in entries[5:13]]
    assert trk_ch_pids == list(range(0x00B, 0x013)), f"Unexpected Track Ch1..8 rel_pids: {trk_ch_pids}"

    # 3. Verify 20-channel USB Vendor Audio Streaming IN descriptor and hardware bridge setup
    usb_ch = patched[0x602CA730 - BASE_VA]
    usb_bit = patched[0x602CA732 - BASE_VA]
    usb_pkt = struct.unpack_from("<H", patched, 0x602CA741 - BASE_VA)[0]
    assert usb_ch == 20, f"Expected USB Vendor IN bNrChannels=20, got {usb_ch}"
    assert usb_bit == 0x18, f"Expected USB Vendor IN bBitResolution=24 (0x18), got {usb_bit}"
    assert usb_pkt == 0x020C, f"Expected USB Vendor IN wMaxPacketSize=0x020C (524), got {hex(usb_pkt)}"
    assert patched[0x600AADE6 - BASE_VA : 0x600AADE8 - BASE_VA] == bytes.fromhex("1426"), "Bad USB-INIT-CH"
    assert patched[0x600AADE8 - BASE_VA : 0x600AADEA - BASE_VA] == bytes.fromhex("0625"), "Bad USB-INIT-FIFO3"
    assert patched[0x600AADEE - BASE_VA : 0x600AADF0 - BASE_VA] == bytes.fromhex("4821"), "Bad USB-INIT-BURST"
    assert patched[0x600AB4AC - BASE_VA : 0x600AB4AE - BASE_VA] == bytes.fromhex("4826"), "Bad USB-IF1-BURST"
    assert patched[0x600AB51E - BASE_VA : 0x600AB520 - BASE_VA] == bytes.fromhex("1422"), "Bad USB-IF2-CH"
    assert patched[0x600AB58C - BASE_VA : 0x600AB58E - BASE_VA] == bytes.fromhex("0622"), "Bad USB-IF2-FIFO3"

    # 4. Verify 8-track Project (.prj) Load/Save, Sequencer, & Import invariants
    assert patched[0x6003EB82 - BASE_VA : 0x6003EB84 - BASE_VA] == bytes.fromhex("082a"), "Bad .prj track loop @0x6003EB82"
    assert patched[0x6003ED04 - BASE_VA : 0x6003ED08 - BASE_VA] == bytes.fromhex("baf1080f"), "Bad .prj track loop @0x6003ED04"
    assert patched[0x6003F134 - BASE_VA : 0x6003F136 - BASE_VA] == bytes.fromhex("082d"), "Bad .prj track loop @0x6003F134"
    assert patched[0x60046300 - BASE_VA : 0x60046302 - BASE_VA] == bytes.fromhex("082c"), "Bad post-load 8-track sync @0x60046300"
    assert patched[0x6008EC7A - BASE_VA : 0x6008EC7C - BASE_VA] == bytes.fromhex("0820"), "Bad project import 8-track count @0x6008EC7A"
    assert patched[0x60342EBA - BASE_VA : 0x60342EBC - BASE_VA] == bytes.fromhex("0822"), "Bad SEQ-ACTIVE-TRK (expected 0822)"
    assert patched[0x600A0AF2 - BASE_VA : 0x600A0AF4 - BASE_VA] == bytes.fromhex("0420"), "Bad MIDI-ALL-OFF-CH (should be stock 0420)"
    assert patched[0x6005B422 - BASE_VA : 0x6005B426 - BASE_VA] == bytes.fromhex("00f015b8"), "Bad PRJ-LOAD-PRESERVE b.w 0x6005B450"
    assert patched[0x6005B452 - BASE_VA : 0x6005BEA0 - BASE_VA] == stock[0x6005B452 - BASE_VA : 0x6005BEA0 - BASE_VA], "Screen 0x16/0x17 project load event handler must be stock from 0x6005B452 onward"
    # PRJ-POST-LOAD (0x60046424) replaces the enclosing project-load function's
    # epilogue, so tramp_prj_load_init is a TAIL CALL that must return through the
    # caller's frame. Required contract, checked from both sides:
    #   stock site epilogue = add sp, sp, #0x28 ; pop.w {r4-r10, pc}  (0ab0 bde8f087)
    #   cave routine tail   = add sp, sp, #0x30 ; pop.w {r4-r10, pc}  (0cb0 bde8f087)
    #                         with "sub sp, sp, #8" at entry  (-8 + 0x30 == +0x28)
    assert stock[0x60046424 - BASE_VA : 0x6004642A - BASE_VA] == bytes.fromhex("0ab0bde8f087"), \
        "PRJ-POST-LOAD site must remain a tail-call epilogue position (add sp,sp,#0x28; pop.w {r4-r10,pc})"
    assert patched[0x60046424 - BASE_VA : 0x6004642A - BASE_VA] == bytes.fromhex(sites_by_id["PRJ-POST-LOAD"]["patch"]), \
        "Bad PRJ-POST-LOAD b.w tramp_prj_load_init at 0x60046424 (upper-4 tracks start at ZERO volume without it)"
    # Decode the b.w by hand (no capstone dependency) to locate the routine, then
    # confirm its frame math: entry "sub sp, sp, #8" (82b0) + tail "add sp, sp, #0x30"
    # == the stock "add sp, sp, #0x28", with an identical pop mask.
    hw1, hw2 = struct.unpack_from("<HH", patched, 0x60046424 - BASE_VA)
    # B.W T3 (unconditional) has fixed bits hw1 = 11110 S...... and hw2 = 10 J1 1 J2 ......;
    # the conditional T4 form would read 11 J1 1 J2 (mask 0xD000 value 0xD000), which is rejected.
    assert (hw1 & 0xF800) == 0xF000 and (hw2 & 0xD000) == 0x9000, \
        "PRJ-POST-LOAD must start with an unconditional b.w (B.W T3) to the init routine"
    s = (hw1 >> 10) & 1
    i1 = 1 - (s ^ ((hw2 >> 13) & 1))
    i2 = 1 - (s ^ ((hw2 >> 11) & 1))
    raw = (s << 23) | (i1 << 22) | (i2 << 21) | ((hw1 & 0x3FF) << 11) | (hw2 & 0x7FF)
    prj_init_va = 0x60046424 + 4 + (raw * 2 - (1 << 25 if s else 0))
    assert patched[prj_init_va - BASE_VA : prj_init_va - BASE_VA + 2] == bytes.fromhex("82b0"), \
        f"tramp_prj_load_init at {prj_init_va:#x} must open with 'sub sp, sp, #8' (the tail-call frame adjustment)"
    tail_off = patched[prj_init_va - BASE_VA : prj_init_va - BASE_VA + 0x100].find(bytes.fromhex("0cb0bde8f087"))
    assert tail_off != -1, \
        f"tramp_prj_load_init tail-call epilogue (add sp,sp,#0x30; pop.w {{r4-r10,pc}}) missing at {prj_init_va:#x}"
    # ESC2 audio register hooks were reverted to stock after the Attempt 8 DAC regression
    # (REG-1 wrote the DSP streaming bus value 0x2C00 into the DAC-routed slots
    # 0x6660/6668/666C/6678/6684, silencing all DAC audio).  NARROW-REG (2026-11-13)
    # re-patches a strictly verified subset inside these windows: it routes only the
    # Track 5/6/7 router slots 0x66B0/0x66B4/0x66B8 to 0x2C00 and clears the Track
    # 5/6/7 loopback enables (word 0x40026248 bits 8/9/10 via bitbands 0x424C4920/24/28),
    # mirroring the MC-707 dispatcher event 0x3A end state.  DAC slots and the
    # streaming FIFO regs (0x66BC/0x6688) stay stock by construction.
    assert patched[0x6001ABB0 - BASE_VA : 0x6001ABB4 - BASE_VA] == stock[0x6001ABB0 - BASE_VA : 0x6001ABB4 - BASE_VA], \
        "USB-ROUTER-INIT @0x6001ABB0 must be stock (boot DAC-slot writes 0x6660..0x6684 live behind it)"
    for s, e in ((0x6001AC6C, 0x6001AD98), (0x6001ADA0, 0x6001ADC8)):
        assert patched[s - BASE_VA : e - BASE_VA] == stock[s - BASE_VA : e - BASE_VA], \
            "audio port init 0x6001AC6C..0x6001ADC7 must be stock except NARROW-REG-B0 @0x6001AD98"
    # Audio-start leaf 0x6001B030: the entry push must survive (tramp_router_b4tail's
    # pop {r4,lr}; bx lr returns through it), and the stock 0x6A48=1 / streaming FIFO
    # 0x66BC=0x803 block between the two patched sites must stay untouched.
    assert patched[0x6001B030 - BASE_VA : 0x6001B032 - BASE_VA] == bytes.fromhex("10b5"), \
        "audio-start leaf must keep its 'push {r4,lr}' entry (tail-call frame of tramp_router_b4tail)"
    assert patched[0x6001B03A - BASE_VA : 0x6001B04C - BASE_VA] == stock[0x6001B03A - BASE_VA : 0x6001B04C - BASE_VA], \
        "audio-start leaf 0x6001B03A..0x6001B04B (0x6A48=1, FIFO 0x66BC=0x803) must stay stock"

    # NARROW-REG trampolines: each site is a single b.w into the SDRAM cave; the
    # routine must write exactly 0x2C00 (the MC-707 DSP streaming bus value) via
    # the stock writer helper 0x600220F0 to exactly the one verified slot, touch no
    # forbidden register (DAC slots, FIFO regs, power-off bitband), and resume/return
    # as the stock site did.
    if "NARROW-REG-B8" not in sites_by_id:
        # NARROW-REG disabled (README §4 Attempt 13, 8-TRACK.md §11.9): the MC-101
        # ESC2 write-enable mask clears bit 13 of every 0x2C00 write on
        # 0x66B0/66B4/66B8 (live readback 0x0C00), so the router route is
        # hardware-dead and the four sites are out of the manifest.  Their
        # addresses must therefore be byte-identical to stock.
        for nva, nlen, nlabel in (
            (0x6001AD98, 8, "NARROW-REG-B0"),
            (0x6001B032, 8, "NARROW-REG-B8"),
            (0x6001B04C, 6, "NARROW-REG-LB"),
            (0x6001B052, 14, "NARROW-REG-B4"),
        ):
            assert patched[nva - BASE_VA : nva - BASE_VA + nlen] == stock[nva - BASE_VA : nva - BASE_VA + nlen], \
                f"{nlabel} is disabled (write-mask fuse, 8-TRACK.md §11.9): {nva:#x}..{nva + nlen:#x} must be stock"
    FORBIDDEN = {0x40026660, 0x40026668, 0x4002666C, 0x40026678, 0x40026684, 0x400266BC, 0x40026688, 0x424C4510}
    for sid, slot_val, resume_va, tail in (
        ("NARROW-REG-B8", 0x400266B8, 0x6001B03A, "b.w"),
        ("NARROW-REG-B0", 0x400266B0, 0x6001ADA0, "b.w"),
        ("NARROW-REG-B4", 0x400266B4, None, "tailpop"),
    ):
        if sid not in sites_by_id:
            continue  # NARROW-REG disabled (see stock assertion above)
        site_va = int(sites_by_id[sid]["address"], 16)
        t = decode_bw(patched, site_va)
        body = patched[t - BASE_VA : t - BASE_VA + 16]
        assert body[0:4] == bytes.fromhex("4ff43051"), f"{sid}: trampoline must open with 'mov.w r1, #0x2C00' (707 streaming bus)"
        hw = struct.unpack_from("<H", patched, t - BASE_VA + 4)[0]
        assert hw & 0xF800 == 0x4800, f"{sid}: 'ldr r0,[pc,#imm8*4]' slot-pointer load expected at {t + 4:#x}"
        lit = struct.unpack_from("<I", patched, (((t + 8) & ~3) + (hw & 0xFF) * 4) - BASE_VA)[0]
        assert lit == slot_val, f"{sid}: trampoline target slot must be {slot_val:#010x}, pool says {lit:#010x}"
        assert decode_bl(patched, t + 6) == 0x600220F0, f"{sid}: must tail to the stock router writer 0x600220F0"
        forbidden_words = {struct.unpack_from("<I", patched, t - BASE_VA + i)[0] for i in range(0, 16, 2)}
        assert not (forbidden_words & FORBIDDEN), f"{sid}: trampoline pools reference a forbidden register"
        if tail == "b.w":
            assert decode_bw(patched, t + 10) == resume_va, f"{sid}: trampoline must resume at {resume_va:#x}"
        else:
            assert body[10:16] == bytes.fromhex("bde810407047"), \
                f"{sid}: must reproduce the leaf's tail-call epilogue 'pop.w {{r4,lr}}; bx lr' after the writer"
    # NARROW-REG-LB: movs r0,#0 + three bitband stores (clear bits 8/9/10 of word
    # 0x40026248, the exact set the MC-707 dispatcher clears at audio start) + resume.
    if "NARROW-REG-LB" in sites_by_id:
        lb_va = int(sites_by_id["NARROW-REG-LB"]["address"], 16)
        t = decode_bw(patched, lb_va)
        body = patched[t - BASE_VA : t - BASE_VA + 16]
        assert body[0:2] == bytes.fromhex("0020"), "NARROW-REG-LB must open with 'movs r0, #0'"
        for i, bitband in enumerate((0x424C4920, 0x424C4924, 0x424C4928)):
            hw = struct.unpack_from("<H", patched, t - BASE_VA + 2 + i * 4)[0]
            assert hw & 0xF800 == 0x4800, "NARROW-REG-LB: 'ldr r1,[pc]' expected"
            assert struct.unpack_from("<H", patched, t - BASE_VA + 4 + i * 4)[0] == 0x6008, "NARROW-REG-LB: 'str r0,[r1]' expected"
            lit = struct.unpack_from("<I", patched, (((t + 6 + i * 4) & ~3) + (hw & 0xFF) * 4) - BASE_VA)[0]
            assert lit == bitband, f"NARROW-REG-LB: bitband pool word {i} must be {bitband:#010x}, got {lit:#010x}"
        assert decode_bw(patched, t + 14) == 0x6001B052, "NARROW-REG-LB must resume at the NARROW-REG-B4 branch (0x6001B052)"
    assert patched[0x60035E74 - BASE_VA : 0x60035E78 - BASE_VA] == bytes.fromhex("41f05101"), "Bad UI-DIRTY-FDR orr r1, r1, #0x51"
    assert patched[0x60337744 - BASE_VA : 0x60337747 - BASE_VA] == bytes.fromhex("161616"), "Bad FDR-ITCM-TBB"
    assert patched[0x60330874 - BASE_VA : 0x60330878 - BASE_VA] == bytes.fromhex("51f82610"), "FDR-TONE-FALLBACK must be reverted to stock 51f82610 @0x60330874"
    assert patched[0x60046420 - BASE_VA : 0x60046424 - BASE_VA] == stock[0x60046420 - BASE_VA : 0x60046424 - BASE_VA], "Unexpected modification at 0x60046420 (should be stock)"

    # 5. Banked UpdateFaderRgbLeds loop (bank-B record/flash fidelity).
    #    Stock: the loop counter r4 IS the track, so record pointer
    #    (*[r5+0xc] + r4*0x100), pid (0x90 + r4), engine track index (uxth r1, r4),
    #    the selected/record gate (cmp selected byte, r4) and the fader LED id
    #    (0x1c + r4) were all pinned to bank A (tracks 1..4).
    #    Patched: r7 is the physical loop base 0..3 and the loop head rebuilds
    #    r4 = r7 + bank (bank = bit 2 of the selected-track byte 0x61800200, read
    #    locklessly through [r5+0x10] - fw_get_param fails its mutex in this ISR),
    #    so the 22 record/pid/state-query/gate uses of r4 follow the bank while the
    #    2 fader RGB LED ids are unbanked (0x1c + physical).  In bank A the bank is
    #    0, so r4 == r7 == physical and bank A is stock by construction; the checks
    #    below pin that contract down.
    assert sites_by_id["FDR-BANK-LOOPBASE"]["length"] == 2
    assert patched[0x6009920A - BASE_VA : 0x6009920C - BASE_VA] == bytes.fromhex("0027"), \
        "FDR-BANK-LOOPBASE must be 'movs r7, #0' (physical fader loop base)"
    assert patched[0x6009920C - BASE_VA : 0x60099212 - BASE_VA] == stock[0x6009920C - BASE_VA : 0x60099212 - BASE_VA], \
        "'mov sb, r4' + 'sub.w r5, r8, #0x14' at 0x6009920C must stay stock (the cave reads r5/r8)"
    # The loop bottom site must be exactly one bl so the stock back-edge survives.
    assert sites_by_id["FDR-BANK-BOT"]["length"] == 4
    assert patched[0x600992C0 - BASE_VA : 0x600992C2 - BASE_VA] == stock[0x600992C0 - BASE_VA : 0x600992C2 - BASE_VA], \
        "the 'blt' at 0x600992C0 must stay stock: it is the loop back-edge into the patched loop head 0x60099212"
    # The LED-id hooks must leave the LED setter argument setup alone.
    assert patched[0x600992B4 - BASE_VA : 0x600992BC - BASE_VA] == stock[0x600992B4 - BASE_VA : 0x600992BC - BASE_VA], \
        "FDR-LED-ID1 fall-through (mov r1, r6 / sxth r0, r0 / bl led setter) must stay stock"
    assert patched[0x6009935C - BASE_VA : 0x60099362 - BASE_VA] == stock[0x6009935C - BASE_VA : 0x60099362 - BASE_VA], \
        "FDR-LED-ID2 must return to stock at 0x6009935C (sxth r0, r0 / bl led setter / b loop bottom)"
    # Consumers of the banked r4 must stay stock instructions.
    for va in (0x60099244, 0x6009925E, 0x600992DE, 0x60099316, 0x6009937A, 0x600993C4, 0x60099438):
        assert patched[va - BASE_VA : va - BASE_VA + 4] == bytes.fromhex("04f19000"), \
            f"'add.w r0, r4, #0x90' @0x{va:08X} must stay stock (banked r4 yields pid 0x90..0x97)"
    for va in (0x600992D2, 0x600992F6, 0x60099302, 0x6009930C):
        assert patched[va - BASE_VA : va - BASE_VA + 2] == bytes.fromhex("a1b2"), \
            f"'uxth r1, r4' @0x{va:08X} (engine track index) must stay stock (banked r4 = track 0..7)"
    for va in (0x60099288, 0x6009933A, 0x60099398, 0x600993E8, 0x6009940C, 0x60099456, 0x6009948A):
        assert patched[va - BASE_VA : va - BASE_VA + 2] == stock[va - BASE_VA : va - BASE_VA + 2], \
            f"record-pointer index math @0x{va:08X} must stay stock (banked r4 selects the record)"
    assert patched[0x6009922C - BASE_VA : 0x6009922E - BASE_VA] == stock[0x6009922C - BASE_VA : 0x6009922E - BASE_VA], \
        "the selected/record gate 'cmp r3, r4' at 0x6009922C must stay stock (banked r4 makes it match in bank B)"
    # The superseded per-site colour hooks must be gone: with banked r4 the colour
    # index read is already bank-relative, and re-adding the bank would double-bank
    # the record pointer (reading past the 8 x 0x100 record array at 0x61991810).
    for va in (0x60099234, 0x6009936A, 0x600993B4, 0x60099428):
        assert patched[va - BASE_VA : va - BASE_VA + 4] == stock[va - BASE_VA : va - BASE_VA + 4], \
            f"superseded colour hook @0x{va:08X} must be removed (LED-FDR-COL1..4 double-bank the record pointer)"
    # Loop arithmetic, modelled from the cave routines it depends on:
    #   tramp_fdr_top  (0x602D2694): bank = selected byte & 4; r4 = r7 + bank
    #   tramp_fdr_bot  (0x602D26AA): r7 += 1; cmp r7, #4
    # plus the stock back-edge "blt 0x60099212" => 4 iterations, the 4 tracks of
    # the bank.  The bottom routine must not touch the banked r4: r4 == 4 occurs
    # in bank A (bank 0, physical 4), so any bank bit read back out of r4 is wrong
    # there, and a counter masked to 2 bits wraps to 0 -> the loop never exits and
    # the timer ISR spins forever.
    assert patched[0x602D26AA - BASE_VA : 0x602D26B0 - BASE_VA] == bytes.fromhex("0137" "042f" "7047"), \
        "tramp_fdr_bot must be 'adds r7,#1 / cmp r7,#4 / bx lr' (stock loop control on the physical counter)"

    def fdr_iter(selected: int) -> list[int]:
        """Track numbers (r4) the patched loop visits for a selected-track byte."""
        bank, r7, seen = selected & 4, 0, []
        while True:
            seen.append(r7 + bank)     # tramp_fdr_top: r4 = physical fader + bank
            r7 += 1                    # tramp_fdr_bot
            if not r7 < 4:             # cmp r7, #4 + stock blt
                return seen

    for sel in range(8):
        seen = fdr_iter(sel)
        assert seen == list(range(sel & 4, (sel & 4) + 4)), \
            f"selected byte {sel}: loop must walk exactly the 4 tracks of its bank, got {seen}"
        assert sorted(t & 3 for t in seen) == [0, 1, 2, 3], \
            f"selected byte {sel}: the unbanked LED ids must hit each of the 4 faders once"
        assert seen.count(sel) == 1, \
            f"selected byte {sel}: the gate 'cmp selected, r4' must match exactly once (that is the flashing fader)"

    # 5. Verify Roland MC-107 boot splash branding string
    assert patched[0x602A7373 - BASE_VA : 0x602A7379 - BASE_VA] == b"MC-101", "Bad STR-SPLASH-LCD (should be stock MC-101)"
    assert patched[0x600480F4 - BASE_VA : 0x60048102 - BASE_VA] == b"Roland MC-101\x00", "Bad STR-NAME-01 (should be stock Roland MC-101)"
    assert patched[0x600AA214 - BASE_VA : 0x600AA21B - BASE_VA] == b"MC-101\x00", "Bad STR-USB-PROD (should be stock MC-101)"
    assert patched[0x6004F1D4 - BASE_VA : 0x6004F1E5 - BASE_VA] == b"Roland MC-107   \x00", "Bad STR-NAME-02"

    # 6. Disassemble SDRAM cave, cave 2, and ITCM fader/knob handler
    if capstone is not None:
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        cave_insns = list(md.disasm(patched[0x602D2600 - BASE_VA : 0x602D27FC - BASE_VA], 0x602D2600))
        assert len(cave_insns) >= 50, f"Unexpectedly few instructions in SDRAM cave: {len(cave_insns)}"

        # SDRAM cave 2 (0x602D2B00..0x602D2BFF) was freed when the diagnostic probes
        # were removed; it must stay untouched stock padding.
        cave2_area = patched[0x602D2B00 - BASE_VA : 0x602D2C00 - BASE_VA]
        assert cave2_area == stock[0x602D2B00 - BASE_VA : 0x602D2C00 - BASE_VA], "Freed SDRAM cave 2 must be stock"
        assert cave2_area.count(0x00) == len(cave2_area), "Freed SDRAM cave 2 should be zero padding"

        itcm_insns = list(md.disasm(patched[0x6033776E - BASE_VA : 0x603377B6 - BASE_VA], 0x01024FD2))
        assert len(itcm_insns) >= 20, f"Unexpected instruction count in ITCM handler: {len(itcm_insns)}"
    else:
        out = subprocess.check_output(
            [
                "arm-none-eabi-objdump",
                "-D",
                "-b",
                "binary",
                "-m",
                "arm",
                "-M",
                "force-thumb",
                f"--start-address={0x602D2600 - BASE_VA}",
                f"--stop-address={0x602D26E6 - BASE_VA}",
                str(args.patched),
            ],
            text=True,
        )
        assert "undefined" not in out.lower(), "Undefined instruction in SDRAM cave"

    print(
        f"[+] Post-patch verification OK: {len(active_sites)} patch sites verified, "
        f"SYSTEM(MIDI) 23 entries (Track Ch1..8), 20-ch USB Vendor audio, "
        f"NARROW-REG {'ACTIVE' if 'NARROW-REG-B8' in sites_by_id else 'DISABLED (write-mask fuse, 8-TRACK.md 11.9)'}, "
        f"8-track .prj I/O, and Capstone disassembly OK."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
