#!/usr/bin/env python3
"""Quick Capstone scouting: literal-pool xrefs to strings + function starts.

Usage: scout_strings.py <image> <base-hex> <code-end-hex> [regex]
"""
import re, struct, sys
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN
from capstone.arm import ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC

def thumb_disasm(data, base, end):
    """Yield instructions across the whole range, resyncing past invalid bytes."""
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    off = 0
    while off + 2 <= end:
        got = False
        for ins in md.disasm(data[off:end], base + off):
            got = True
            off += ins.size
            yield ins
        if not got:
            off += 2

def main():
    path, base_s, end_s = sys.argv[1], sys.argv[2], sys.argv[3]
    pat = re.compile(sys.argv[4], re.I) if len(sys.argv) > 4 else re.compile(r"track", re.I)
    data = Path(path).read_bytes()
    base, end = int(base_s, 0), int(end_s, 0)
    size = end - base

    # string table: offset -> text
    strings = {}
    for m in re.finditer(rb"[ -~]{4,}", data[:size]):
        strings[base + m.start()] = m.group().decode("latin1")

    lit = {}   # insn addr -> literal value
    funcs = set()
    insns = {}
    for ins in thumb_disasm(data, base, size):
        insns[ins.address] = ins
        # function prologue heuristics
        if ins.id and ins.mnemonic in ("push", "stmdb"):
            ops = ins.op_str
            if "lr" in ops:
                funcs.add(ins.address)
        if ins.mnemonic in ("bl", "blx", "b", "bx"):
            try:
                t = ins.operands[0]
                if t.type == 2:  # imm
                    funcs.add(t.imm)
            except Exception:
                pass
        if ins.mnemonic.startswith("ldr") and len(ins.operands) >= 2:
            op = ins.operands[1]
            if op.type == ARM_OP_MEM and op.mem.base == ARM_REG_PC:
                pc = (ins.address + 4) & ~3
                addr = pc + op.mem.disp
                off = addr - base
                if 0 <= off <= size - 4:
                    val = struct.unpack_from("<I", data, off)[0]
                    lit[ins.address] = val

    def enclosing(a):
        cands = [f for f in funcs if f <= a]
        return max(cands) if cands else None

    hits = []
    for ia, val in lit.items():
        s = strings.get(val)
        if s and pat.search(s):
            hits.append((ia, val, s, enclosing(ia)))

    hits.sort()
    print(f"# {path}")
    print(f"# strings={len(strings)} litloads={len(lit)} prologues={len(funcs)} hits={len(hits)}")
    for ia, val, s, fn in hits:
        print(f"{ia:08x} fn={fn if fn is None else format(fn,'08x')} str={val:08x} {s[:100]}")

if __name__ == "__main__":
    main()
