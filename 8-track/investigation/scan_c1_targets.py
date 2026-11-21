#!/usr/bin/env python3
"""Collect branch targets + literal entry points for Core 1 images.
Outputs: histogram of in-image bl/b.w targets per 64K; cross-image pointer lists."""
import sys, struct
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC707_SD, MC101_IDM, MC707_IDM, SD_BASE, IDM_BASE

def all_branch_targets(im):
    """Yield (site, target) for every bl/b/b.w/bx-literal? -> only direct bl/b.w/b."""
    d = im.data
    for i in range(0, len(d) - 4, 2):
        hw = struct.unpack_from("<H", d, i)[0]
        t = None
        if hw & 0xE000 == 0xE000 and hw & 0x1800 == 0x1800:
            continue  # conditional b with weird cond (0xE800 area = LDRD etc.)
        if hw & 0xF800 == 0xE000:  # b imm11 (cond=1110)
            imm = hw & 0x7FF
            if imm & 0x400:
                imm -= 0x800
            t = im.base + i + 4 + imm * 2
        elif (hw & 0xF800) == 0xF000 and i + 4 <= len(d) - 2:
            hw2 = struct.unpack_from("<H", d, i + 2)[0]
            if hw2 & 0xC000 == 0x8000:  # b.w/bl.w
                imm = ((hw & 0x7FF) << 12) | (hw2 & 0x7FF)
                if (hw >> 10) & 1:
                    imm -= 1 << 23
                elif not (hw2 >> 11) & 1:
                    imm -= 1 << 22
                t = im.base + i + 4 + imm
        if t is not None:
            yield im.base + i, t

def main():
    which = sys.argv[1]
    im = Img(MC101_SD if which == "mc101" else MC707_SD, 0x61000000)
    lo, hi = im.base + 0x20, im.base + len(im.data)
    tgts = []
    for site, t in all_branch_targets(im):
        if lo <= t < hi:
            tgts.append(t & ~1)
    tgts.sort()
    import collections
    hist = collections.Counter(t >> 16 for t in tgts)
    print("bl/b.w in-image targets per 64K (unique):")
    for k in sorted(hist):
        print(f"  {im.base + (k << 16):08X} {hist[k]:5d}")
    print(f"total targets={len(tgts)} unique={len(set(tgts))} max_target=0x{max(tgts):08X} min_target=0x{min(tgts):08X}")
    tail = sorted(t for t in set(tgts) if t > 0x61200000)
    print("targets > 0x61200000:", [hex(t) for t in tail[:40]])

main()
