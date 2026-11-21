#!/usr/bin/env python3
"""Level-1 layout scan for Core 1 sdram1.bin: code density per 64K chunk via
linear disassembly, entropy class, string density. Chunked to stay under timeouts."""
import sys, struct
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC707_SD, SD_BASE

def code_density(im, start, end, step=2):
    """Return per-4K-chunk: (valid_inst_frac, avg_inst_size, n_incomplete) linear Thumb disasm."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    md.skipdata = True
    CHUNK = 0x1000
    out = []
    va = start & ~(CHUNK - 1)
    end = min(end, im.base + len(im.data))
    while va < end:
        blob = im.read(va, min(CHUNK, end - va))
        n = 0
        bad = 0
        sz = 0
        for ins in md.disasm(blob, va):
            n += 1
            sz += ins.size
            if ins.mnemonic in ("(bad)", "unknown"):
                bad += 1
        out.append((va, n, bad, sz))
        va += CHUNK
    return out

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else MC101_SD
    im = Img(path, SD_BASE["mc101"])
    res = code_density(im, im.base + 0x20, im.base + len(im.data))
    for va, n, bad, sz in res:
        frac = (n - bad) / max(n, 1)
        mark = "CODE " if frac > 0.97 and sz > 0x1000 * 0.45 else ("data " if sz < 0x1000 * 0.55 else "mix  ")
        print(f"{va:08X} {mark} ins={n:5d} bad={bad:5d} bytes_cov={sz:5d}")
