#!/usr/bin/env python3
"""Full linear disasm; record instructions whose immediates target key ranges
(catches addresses built by movw/movt/mov.w/add.w/orr.w, not just pc-literals).
Chunked: argv = image (sdram|idm) which start end."""
import sys, re
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC707_SD, MC101_IDM, MC707_IDM, SD_BASE, IDM_BASE
import capstone

KEYS = [
    ("AUD_DMA_PL080", 0x40031000, 0x40031140),
    ("SAI/QSPI1",     0x40032000, 0x40032100),
    ("DMAC0",         0x40001000, 0x40001140),
    ("DMAC1",         0x40030000, 0x40030100),
    ("USB_BRIDGE",    0x40080000, 0x40080A00),
    ("IPC_MBOX",      0x01140000, 0x01141000),
    ("SRAM_AUD_PP",   0x20020000, 0x20021000),
    ("SRAM_ENG_BUF",  0x20080000, 0x20081000),
    ("SYSCTRL",       0x40000000, 0x40000100),
    ("DSP_ENGINE",    0x40060000, 0x40076000),
    ("SRAM_CORE",     0x20000000, 0x200C0000),
    ("SDRAM_C1WAVE",  0x61800000, 0x61FD0000),
]
IMM16 = {0x4003, 0x4008, 0x0114, 0x2002, 0x2008, 0x4000, 0x4006, 0x4007, 0x6180, 0x6181, 0x61FE, 0x2000, 0x200B}

def in_key(v):
    for nm, lo, hi in KEYS:
        if lo <= v < hi:
            return nm
    return None

def main():
    kind, which, lo, hi = sys.argv[1], sys.argv[2], int(sys.argv[3], 16), int(sys.argv[4], 16)
    im = Img((MC101_SD if which == "mc101" else MC707_SD) if kind == "sdram"
             else (MC101_IDM if which == "mc101" else MC707_IDM),
             SD_BASE[which] if kind == "sdram" else IDM_BASE)
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    md.skipdata = True
    va = lo
    n = 0
    while va < hi:
        blob = im.read(va, min(0x10000, hi - va))
        for ins in md.disasm(blob, va):
            n += 1
            hits = []
            for mm in re.finditer(r"#(0x[0-9a-f]+|\d+)", ins.op_str):
                v = int(mm.group(1), 0)
                k = in_key(v)
                if k:
                    hits.append((k, v))
            m16 = re.match(r"mov(?:t|w)?\s+\w+, #0x([0-9a-f]+)$", ins.op_str)
            if m16 and ins.mnemonic in ("movt", "movw", "mov"):
                v = int(m16.group(1), 16)
                if v in IMM16 and ins.mnemonic == "movt":
                    hits.append(("IMM16-movt", v))
            if ins.mnemonic == "(bad)":
                pass
            if hits:
                print(f"{ins.address:08X} [{','.join(k for k,_ in hits)}] "
                      f"{ins.bytes.hex():<8} {ins.mnemonic} {ins.op_str}")
        va += len(blob)
    print(f"# scanned {n} insns in {lo:08X}-{hi:08X}", file=sys.stderr)

main()
