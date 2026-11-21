#!/usr/bin/env python3
"""For every site constructing 0x40000000-base addresses (mov.w/add.w #0x40000000),
show the following 8 instructions and reconstruct the final address from
add.w/adds/orr immediates + register offsets of str/ldr using that base register."""
import sys, re
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC707_SD, MC101_IDM, MC707_IDM, SD_BASE, IDM_BASE
import capstone

def main(which, kind):
    im = Img((MC101_SD if which == "mc101" else MC707_SD) if kind == "sdram"
             else (MC101_IDM if which == "mc101" else MC707_IDM),
             SD_BASE[which] if kind == "sdram" else IDM_BASE)
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    md.skipdata = True
    va = im.base + 0x20
    hi = im.base + len(im.data)
    while va < hi:
        blob = im.read(va, min(0x10000, hi - va))
        ins_list = list(md.disasm(blob, va))
        for i, ins in enumerate(ins_list):
            if re.search(r"#0x40000000$", ins.op_str) and ins.mnemonic in ("mov.w", "mov", "add.w", "adds.w", "orr.w", "orr"):
                reg = ins.op_str.split(",")[0].strip() if ins.mnemonic.startswith("mov") else ins.op_str.split(",")[1].strip()
                print(f"--- {ins.address:08X}: {ins.mnemonic} {ins.op_str}")
                for j in range(i + 1, min(i + 9, len(ins_list))):
                    n = ins_list[j]
                    print(f"    {n.address:08X}: {n.bytes.hex():<8} {n.mnemonic} {n.op_str}")
                    if n.mnemonic in ("bx", "pop") or re.search(rf"\[{reg}", n.op_str):
                        pass
                va2 = va
        va += len(blob)
    print(f"# done {im.path}", file=sys.stderr)

main(sys.argv[1], sys.argv[2])
