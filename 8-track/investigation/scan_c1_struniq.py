#!/usr/bin/env python3
"""Content-level string diff: strings unique to A (no superstring in B)."""
import sys, re
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC707_SD, MC101_IDM, MC707_IDM

def toks(s):
    return set(m.group() for m in re.finditer(r"[A-Za-z][A-Za-z0-9_%*./:-]{3,}", s))

def main(A, B, minlen=6):
    a = Img(A, 0x61000000 if "sdram" in A else 0x01100000)
    b = Img(B, 0x61000000 if "sdram" in B else 0x01100000)
    bset = set()
    for va, t in b.strings(minlen):
        bset |= toks(t)
    seen = {}
    for va, t in a.strings(minlen):
        for w in toks(t):
            if w not in bset and w not in seen:
                seen[w] = va
    for w, va in sorted(seen.items(), key=lambda kv: kv[1]):
        print(f"{va:08X}  {w}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--a"); p.add_argument("--b"); p.add_argument("--minlen", type=int, default=6)
    a = p.parse_args()
    main(a.a, a.b, a.minlen)
