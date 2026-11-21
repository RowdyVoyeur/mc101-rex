#!/usr/bin/env python3
"""List distinct cross-image literal targets with top examples + 16-byte context."""
import sys
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC101_IDM, SD_BASE, IDM_BASE
from collections import Counter, defaultdict

sd = Img(MC101_SD, 0x61000000)
idm = Img(MC101_IDM, IDM_BASE)
sd_hi = sd.base + len(sd.data)

a = sd.literal_users(set(range(IDM_BASE, IDM_BASE + 0x40000)))
b = idm.literal_users(set(range(sd.base, sd_hi)))

print("== sdram1 -> idm1 distinct values (count, odd?):")
for v, c in Counter((v, v & 1) for _, _, v in a).most_common(60):
    print(f"  0x{v[0]:08X} n={c} odd={v[1]}")
print("== idm1 -> sdram1 odd (code-entry) targets:")
odd = [(s, r, v) for s, r, v in b if v & 1]
for v, c in Counter(v for _, _, v in odd).most_common(15):
    sites = [s for s, r, vv in odd if vv == v]
    print(f"  0x{v:08X} n={c} sites={[hex(x) for x in sites[:4]]}")
print("== idm1 -> sdram1 even (data) targets top:")
ev = [v for _, _, v in b if not (v & 1)]
for v, c in Counter(ev).most_common(15):
    print(f"  0x{v:08X} n={c}")
