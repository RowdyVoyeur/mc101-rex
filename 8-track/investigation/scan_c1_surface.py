#!/usr/bin/env python3
"""Deliverable 3: literal sites in sdram1.bin + idm1.bin whose pc-literal pool
slot holds a value in the shared-audio-surface ranges. Annotate with window."""
import sys, struct
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC707_SD, MC101_IDM, MC707_IDM, SD_BASE, IDM_BASE
import capstone

RANGES = [
    ("AUD_DMA_PL080", 0x40031000, 0x40031140),
    ("SAI/QSPI1_blk", 0x40032000, 0x40032100),
    ("DMAC0",         0x40001000, 0x40001140),
    ("DMAC1",         0x40030000, 0x40030100),
    ("USB_BRIDGE",    0x40080000, 0x40080A00),
    ("IPC_MBOX",      0x01140000, 0x01141000),
    ("SRAM_AUD_PP",   0x20020000, 0x20021000),
    ("SRAM_ENG_BUF",  0x20080000, 0x20081000),
]

def main(which, kind):
    p = (MC101_SD if which == "mc101" else MC707_SD) if kind == "sdram" else (MC101_IDM if which == "mc101" else MC707_IDM)
    base = SD_BASE[which] if kind == "sdram" else IDM_BASE
    im = Img(p, base)
    allvals = set()
    for _, lo, hi in RANGES:
        allvals |= set(range(lo, hi))
    hits = im.literal_users(allvals)
    # group by range
    byrng = {}
    for site, reg, val in hits:
        for nm, lo, hi in RANGES:
            if lo <= val < hi:
                byrng.setdefault(nm, []).append((site, reg, val))
                break
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    for nm, lo, hi in RANGES:
        hl = sorted(byrng.get(nm, []))
        print(f"\n=== {nm} {lo:08X}-{hi:08X}: {len(hl)} sites in {kind} ===")
        seen = set()
        for site, reg, val in hl:
            if site in seen:
                continue
            seen.add(site)
            print(f"site {site:08X} ldr {reg},=0x{val:08X}")
            # decode a window: from site-6 to site+0x30
            w0 = site - 4
            for ins in md.disasm(im.read(w0, 0x40), w0):
                tag = ""
                if f"[{reg}" in ins.op_str and ins.mnemonic.startswith(("str", "ldr")):
                    tag = "   <<<"
                print(f"    {ins.address:08X}: {ins.bytes.hex():<8} {ins.mnemonic} {ins.op_str}{tag}")

main(sys.argv[1], sys.argv[2])
