#!/usr/bin/env python3
"""Pattern-based code/data classifier for Core 1 images (level-1 layout).
Per window (default 4K) compute fraction of 16-bit halfwords matching:
  - push/pop  (hw & 0xFF00 == 0xB400..0xB700)  : ~0.4% random, ~2-4% in code
  - ldr[pc]   (hw & 0xF800 == 0x4800)          : ~3.1% random,  ~6-9% in code
  - 32-bit thumb prefix pair (hw&0xE000==0xE000) bl/b.w etc
Classify CODE / DATA / ZERO / MIX. Print transitions."""
import sys, struct
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC707_SD

BASES = {"mc101_sd": 0x61000000, "mc707_sd": 0x61000000,
         "mc101_idm": 0x01100000, "mc707_idm": 0x01100000}

def profile(path, base, lo, hi, step=0x1000):
    im = Img(path, base)
    prev = None
    for va in range(lo, hi, step):
        blob = im.read(va, step)
        n = len(blob) // 2
        if n == 0:
            continue
        push = ldrpc = hz = 0
        for i in range(0, len(blob) - 1, 2):
            hw = struct.unpack_from("<H", blob, i)[0]
            if hw == 0:
                hz += 1
            m = hw & 0xFF00
            if 0xB400 <= m <= 0xB700:
                push += 1
            if hw & 0xF800 == 0x4800:
                ldrpc += 1
        pp, lp, zz = push / n, ldrpc / n, hz / n
        cls = "ZERO" if zz > 0.6 else ("CODE" if pp > 0.012 and lp > 0.045 else ("DATA" if pp < 0.006 and lp < 0.038 and zz < 0.6 else "MIX"))
        if cls != prev:
            print(f"{va:08X} {cls} push={pp:.3f} ldrpc={lp:.3f} zero={zz:.3f}")
            prev = cls

if __name__ == "__main__":
    key = sys.argv[1]
    lo = int(sys.argv[2], 16)
    hi = int(sys.argv[3], 16)
    path = {"mc101_sd": MC101_SD, "mc707_sd": MC707_SD}.get(key)
    if path is None:
        path = sys.argv[4]
    profile(path, BASES[key], lo, hi)
