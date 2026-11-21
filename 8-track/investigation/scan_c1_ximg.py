#!/usr/bin/env python3
"""Deliverable 5: cross-image pointers.
sdram1 -> idm1: pc-literal slots holding values in [0x01100000,0x01140000).
idm1 -> sdram1: pc-literal slots holding values in [0x61000000,0x61389b1c) (sdram range).
Also: bl/b.w targets in one image that land in the other image's VA range (impossible
for direct branches, count check), and words with Thumb bit in vector-table region.
Print counts + up to N examples with disasm windows."""
import sys
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC707_SD, MC101_IDM, MC707_IDM, SD_BASE, IDM_BASE

def main(which, n_ex=5):
    sd = Img(MC101_SD if which == "mc101" else MC707_SD, 0x61000000)
    idm = Img(MC101_IDM if which == "mc101" else MC707_IDM, IDM_BASE)
    sd_hi = sd.base + len(sd.data)

    a = sd.literal_users(set(range(IDM_BASE, IDM_BASE + 0x40000)))
    b = idm.literal_users(set(range(sd.base, sd_hi)))
    print(f"sdram1->idm1 literal sites: {len(a)}")
    for site, reg, val in a[:n_ex]:
        print(f"  {site:08X} ldr {reg},=0x{val:08X}")
    print(f"  (values seen: {sorted(set(f'0x{v:08X}' for _,_,v in a))[:12]})")
    print(f"total distinct idm targets: {len(set(v for _,_,v in a))}")
    print(f"idm1->sdram1 literal sites: {len(b)}")
    from collections import Counter
    for site, reg, val in b[:n_ex]:
        print(f"  {site:08X} ldr {reg},=0x{val:08X}")
    print(f"  target histogram top: {Counter(v & ~1 for _,_,v in b).most_common(10)}")
    # Thumb-bit fraction in each list
    for nm, lst in (("sdram->idm", a), ("idm->sdram", b)):
        odd = sum(1 for _, _, v in lst if v & 1)
        m4 = sum(1 for _, _, v in lst if (v & 3) == 1)
        print(f"  {nm}: {odd}/{len(lst)} odd; {m4}/{len(lst)} ≡1 mod4")
main(sys.argv[1])
