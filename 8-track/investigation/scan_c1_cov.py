#!/usr/bin/env python3
"""Recursive-descent code coverage for Core1 sdram1.bin.
Seeds: idm1 vector handlers + all Thumb-bit pointers (v&1, v%4==1) in idm1/sdram1
pointing into sdram1 range. BFS: decode basic blocks, follow bl/b/cond/literal-bx.
Outputs per-64K coverage. Caches to /tmp/opencode/cov_<key>.txt"""
import sys, struct, collections
sys.path.insert(0, "8-track/tools")
from c1img import Img, MC101_SD, MC707_SD, MC101_IDM, MC707_IDM, SD_BASE, IDM_BASE
import capstone

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "mc101"
    sd = Img(MC101_SD if which == "mc101" else MC707_SD, 0x61000000)
    idm = Img(MC101_IDM if which == "mc101" else MC707_IDM, IDM_BASE)
    lo, hi = sd.base + 0x20, sd.base + len(sd.data)
    seeds = set()

    def seed(v):
        v &= ~1
        if lo <= v < hi and v & 1 == 0:
            seeds.add(v)

    # idm1: every word in sdram range with Thumb bit
    for off in range(0, len(idm.data) - 3, 4):
        v = struct.unpack_from("<I", idm.data, off)[0]
        if lo <= v < hi and v & 1:
            seed(v)
    # sdram1: words ≡1 mod4 in range (pc-literal convention), plus vectors table style
    for off in range(0, len(sd.data) - 3, 4):
        v = struct.unpack_from("<I", sd.data, off)[0]
        if lo <= v < hi and (v & 3) == 1:
            seed(v)
    # in-image bl/b.w direct call targets (reliable within code regions)
    for i in range(0x20, len(sd.data) - 4, 2):
        hw = struct.unpack_from("<H", sd.data, i)[0]
        if (hw & 0xF800) == 0xF000:
            hw2 = struct.unpack_from("<H", sd.data, i + 2)[0]
            if hw2 & 0xC000 == 0x8000 and (hw2 & 0x1000):  # bl.w (L bit = hw2 bit12)
                imm = ((hw & 0x7FF) << 12) | (hw2 & 0x7FF)
                if (hw >> 10) & 1:
                    imm -= 1 << 23
                elif not (hw2 >> 11) & 1:
                    imm -= 1 << 22
                seed(sd.base + i + 4 + imm)

    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    visited = bytearray(len(sd.data))
    covered = bytearray(len(sd.data))
    q = collections.deque(sorted(seeds))
    nblocks = 0
    while q:
        va = q.popleft()
        o = va - sd.base
        if o < 0x20 or o >= len(sd.data) - 2 or visited[o]:
            continue
        visited[o] = 1
        nblocks += 1
        last_end = 0
        try:
            gen = md.disasm(sd.read(va, 512), va)
            for ins in gen:
                last_end = ins.address + ins.size
                covered[ins.address - sd.base: ins.address - sd.base + ins.size] = b"\x01" * ins.size
                m = ins.mnemonic
                ops = ins.op_str
                if m in ("bx", "blx"):
                    if ops.startswith("lr"):
                        break
                    break
                if m == "pop" and "pc" in ops:
                    break
                if m in ("b", "b.w") and ops.startswith("#0x"):
                    t = int(ops.lstrip("#"), 16) & ~1
                    if not ops.startswith("#0x"): pass
                    q.append(t)
                    break
                if m in ("bx", "bl"):
                    pass
                if m == "bl" or m == "bl.w":
                    if ops.startswith("#0x"):
                        q.append(int(ops.lstrip("#"), 16) & ~1)
                    continue
                if m.startswith("b.") or m in ("bne", "beq", "bgt", "blt", "bge", "bls", "bhi", "bhs", "blo",
                                                "cbz", "cbnz", "tbb", "tbh"):
                    if ops.startswith("#0x") or ", #0x" in ops:
                        try:
                            t = int(ops.rsplit("#", 1)[1].lstrip("#"), 16) & ~1
                            q.append(t)
                        except Exception:
                            pass
                    continue
                # literal pool bx detection: ldr rN,[pc,#imm] then bx/blx rN
                if m == "ldr" and "[pc," in ops:
                    reg = ops.split(",")[0].split()[-1]
                    nxt = None
                    try:
                        nxt = next(gen)
                    except StopIteration:
                        pass
                    if nxt is not None:
                        covered[nxt.address - sd.base: nxt.address - sd.base + nxt.size] = b"\x01" * nxt.size
                        if nxt.mnemonic in ("bx", "blx") and nxt.op_str == reg:
                            val = sd.word(nxt.address - 0)  # placeholder
                            # find literal value: address in pool = (ins.address+4)&~3 + imm
                            imm = int(ops.rsplit("#", 1)[1].lstrip("#"), 16)
                            pool = ((ins.address + 4) & ~3) + imm
                            v = sd.word(pool)
                            if lo - 1 <= v <= hi:
                                q.append(v & ~1)
                        # fallthrough: re-process nxt by continuing loop is hard; emulate:
                        # push a resume marker
                        q.append(nxt.address)
                        # mark visited lightly so we continue from nxt (already covered)
                        break
                # default: continue linear
            else:
                # 512-byte window exhausted mid-block: resume at window end
                if last_end:
                    q.append(last_end)
        except capstone.CsError:
            pass
    print(f"blocks={nblocks} seeds={len(seeds)}")
    hist = collections.Counter()
    GRAN = int(sys.argv[2]) if len(sys.argv) > 2 else 0x10000
    for o in range(0x20, len(sd.data)):
        if covered[o]:
            hist[(sd.base + o) // GRAN] += 1
    out = []
    for k in sorted(hist):
        out.append((k * GRAN, hist[k]))
    for va, n in out:
        print(f"{va:08X} cov={n:5d}/65536")

main()
