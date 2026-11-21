#!/usr/bin/env python3
"""Shared analysis helper for Core 1 firmware images (MC-101 RPG69_C1A vs MC-707 RPG68_C1A).

Address model (see docs/system_architecture_and_boot_flow.md §2 and 8-track/8-TRACK.md §11.1):
  sdram1.bin  -> file offset 0x20 == VA 0x61000000  (shared SDRAM, Zen-Core engine, plaintext Thumb)
  idm1.bin    -> file offset 0x20 == VA 0x01100000  (Core 1 ITCM; vector table at file offset 0x20)

Each payload file carries a 32-byte header ahead of the image that lands at the segment
base, so runtime VA = file offset + segment base - 0x20.  The bases below are therefore
`segment base - 0x20`; a VA passed to any subcommand is a *runtime* VA.  Addresses in the
docs written as file offsets (e.g. the descriptor dump "base 0x6109AB00") are 0x20 higher
than the runtime VA (0x6109AAE0).

The CLI (subcommands) is the interface used by the investigation; import Img for scripting.
Run `python3 c1img.py -h` for subcommand help.
"""
from __future__ import annotations
import argparse, re, struct, sys
from pathlib import Path

import capstone

MC101_SD = "vendor/mc101_sys_v182/extracts/RPG69_C1A/sdram1.bin"
MC101_IDM = "vendor/mc101_sys_v182/extracts/RPG69_C1A/idm1.bin"
MC707_SD = "vendor/mc707_sys_v182/extracts/RPG68_C1A/sdram1.bin"
MC707_IDM = "vendor/mc707_sys_v182/extracts/RPG68_C1A/idm1.bin"

PAYLOAD_HEADER = 0x20  # bytes of file header ahead of the segment base (see docstring)
SD_BASE = {"mc101": 0x61000000 - PAYLOAD_HEADER, "mc707": 0x61000000 - PAYLOAD_HEADER}
IDM_BASE = 0x01100000 - PAYLOAD_HEADER


class Img:
    """A Core 1 image mapped at a runtime VA base."""

    def __init__(self, path: str, base: int):
        self.path = str(path)
        self.base = base
        self.data = Path(path).read_bytes()

    def __len__(self):
        return len(self.data)

    def off(self, va: int) -> int:
        return va - self.base

    def read(self, va: int, n: int) -> bytes:
        return self.data[self.off(va):self.off(va) + n]

    def word(self, va: int) -> int:
        return struct.unpack_from("<I", self.data, self.off(va))[0]

    def disasm(self, va: int, n: int):
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        yield from md.disasm(self.read(va, n), va)

    def disasm_at(self, va: int, n: int = 0x40):
        """Disassemble n bytes starting at va, stripping the Thumb bit."""
        yield from self.disasm(va & ~1, n)

    # ------------------------------------------------------------------ strings
    def strings(self, minlen: int = 5):
        for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, self.data):
            yield self.base + m.start(), m.group().decode("ascii")

    # ------------------------------------------------------- literal-pool scan
    def _ldr_literals(self):
        """Yield (site_va, register, target_va) for ldr rN,[pc,#imm] literals."""
        d = self.data
        for i in range(0, len(d) - 4, 2):
            hw = struct.unpack_from("<H", d, i)[0]
            if hw & 0xF800 == 0x4800:  # ldr rT,[pc,#imm7*4]
                al = (self.base + i + 4) & ~3
                yield self.base + i, "r%d" % (hw >> 8 & 7), al + ((hw & 0xFF) << 2)
            elif (hw & 0xF0FF) == 0xF0DF and i + 4 <= len(d) - 4:  # ldr.w rT,[pc,#imm12]
                hw2 = struct.unpack_from("<H", d, i + 2)[0]
                al = (self.base + i + 4) & ~3
                imm = hw2 & 0xFFF
                yield self.base + i, "r%d" % (hw2 >> 12 & 0xF), al + (imm if hw2 & 0x8000 else imm * 4)

    def literal_users(self, values: set[int], window: int = 0):
        """Code sites whose pc-relative literal pool slot *holds* one of `values`.

        If window>0, the loaded value is additionally required to fall in a pool slot
        within [value, value+window) (e.g. a struct base covering +0x200 members).
        """
        slots = {}
        for off in range(0, len(self.data) - 4, 4):
            v = struct.unpack_from("<I", self.data, off)[0]
            if v in values:
                slots.setdefault(self.base + off, v)
        hits = []
        for site, reg, target in self._ldr_literals():
            if target in slots:
                val = slots[target]
                if window and not (target - 4 <= val and val <= target + window):
                    pass
                hits.append((site, reg, val))
        return hits

    def code_refs(self, va: int):
        """bl/b.w/b targets that land exactly on va."""
        d = self.data
        out = []
        for i in range(0, len(d) - 4, 2):
            hw = struct.unpack_from("<H", d, i)[0]
            t = None
            if hw & 0xE000 == 0xE000:  # b imm11
                t = self.base + i + 4 + ((hw & 0x7FF) << 1) - 0x1000 * ((hw >> 10) & 1) * 2
            elif hw & 0xF800 == 0xF000 and i + 2 <= len(d) - 2:
                hw2 = struct.unpack_from("<H", d, i + 2)[0]
                if hw2 & 0xC000 == 0x8000:  # b.w / bl.w
                    imm = ((hw & 0x7FF) << 12) | (hw2 & 0x7FF)
                    sign = (hw >> 10) & 1
                    j = (hw2 >> 11) & 1
                    if sign:
                        imm -= 1 << 23
                    elif not j:
                        imm -= 1 << 22
                    t = self.base + i + 4 + imm
            if t == va:
                out.append(self.base + i)
        return out


def load(which: str, kind: str) -> Img:
    which = which.lower()
    if kind == "sdram":
        return Img(MC101_SD if which == "mc101" else MC707_SD, SD_BASE[which])
    return Img(MC101_IDM if which == "mc101" else MC707_IDM, IDM_BASE)


# ------------------------------------------------------------------ subcommands
def cmd_map(a):
    im = load(a.which, a.kind)
    d = im.data
    print(f"{im.path}  {len(d)} bytes  VA base 0x{im.base:08X}")
    # region layout: runs of zeros (BSS/padding) vs data vs code
    ZERO = b"\x00" * 64
    runs, s = [], 0
    i = 0
    while i < len(d):
        if d[i:i + 64] == ZERO:
            j = d.find(b"\x00" * 64, i + 64)
            j = len(d) if j < 0 else j + 64
            if j - i >= 0x400:
                runs.append((i, j, "zero"))
            i = j
        else:
            i += 1
    print("zero runs >= 1K:")
    for s, e, _ in runs:
        print(f"  {im.base+s:08X}..{im.base+e:08X}  {e-s:8d} B")
    # strings
    print("strings (model-specific first, if --mc707 path given):")
    mine = dict(im.strings(a.minlen))
    if a.other:
        o = Img(a.other, im.base)
        oth = set(t for _, t in o.strings(a.minlen))
        mine = {v: t for v, t in mine.items() if t not in oth}
    for v, t in sorted(mine.items()):
        print(f"  {v:08X}  {t!r}")


def cmd_dis(a):
    im = load(a.which, a.kind)
    va = int(a.va, 16)
    for ins in im.disasm_at(va, a.len):
        print(f"  {ins.address:08X}: {ins.bytes.hex():<10} {ins.mnemonic:<9} {ins.op_str}")


def cmd_lit(a):
    im = load(a.which, a.kind)
    vals = {int(v, 16) for v in a.values}
    if a.range is not None:
        lo, hi = (int(x, 16) for x in a.range.split("-"))
        vals |= set(range(lo, hi))
    for site, reg, val in im.literal_users(vals):
        print(f"  {site:08X} ldr {reg}, = {val:08X}")
        n = getattr(a, "follow", 0)
        if n:
            for ins in im.disasm(site, min(n, 0x80)):
                if ins.mnemonic.startswith("str") and f"[{reg}" in ins.op_str:
                    print(f"      store {ins.address:08X}: {ins.mnemonic} {ins.op_str}")


def cmd_xref(a):
    im = load(a.which, a.kind)
    for t in im.code_refs(int(a.va, 16)):
        print(f"  caller {t:08X}")


def cmd_diff(a):
    aimg = load(a.which, "sdram")
    bimg = Img(a.other, aimg.base)
    n = min(len(aimg.data), len(bimg.data))
    diffs = [i for i in range(n) if aimg.data[i] != bimg.data[i]]
    print(f"model A={aimg.path}  B={bimg.path}")
    print(f"len A={len(aimg.data)}  len B={len(bimg.data)}  shared={n}  tail_delta={len(bimg.data)-len(aimg.data)}")
    if not diffs:
        print("no differing bytes in shared prefix")
        return
    runs, s, p = [], diffs[0], diffs[0]
    for i in diffs[1:]:
        if i > p + a.gap:
            runs.append((s, p))
            s = i
        p = i
    runs.append((s, p))
    print(f"{len(diffs)} differing bytes in {n} shared; {len(runs)} clusters (gap>{a.gap}):")
    for s, e in runs:
        print(f"  A{aimg.base+s:08X}/B{bimg.base+s:08X}..{bimg.base+e:08X} ({e-s+1} B)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(kind, *pos):
        sp = sub.add_parser(kind)
        sp.add_argument("which", choices=["mc101", "mc707"])
        for name in pos:
            sp.add_argument(name)
        return sp

    sp = add("map")
    sp.add_argument("--kind", choices=["sdram", "idm"], default="sdram")
    sp.add_argument("--minlen", type=int, default=6)
    sp.add_argument("--other", default=None)
    sp.set_defaults(fn=cmd_map)

    sp = add("dis", "va")
    sp.add_argument("--kind", choices=["sdram", "idm"], default="sdram")
    sp.add_argument("--len", dest="len", type=int, default=0x40)
    sp.set_defaults(fn=cmd_dis)

    sp = add("lit", "values")
    sp.add_argument("--kind", choices=["sdram", "idm"], default="sdram")
    sp.add_argument("--range", default=None)
    sp.add_argument("--follow", type=int, default=0)
    sp.set_defaults(fn=cmd_lit)

    sp = add("xref", "va")
    sp.add_argument("--kind", choices=["sdram", "idm"], default="sdram")
    sp.set_defaults(fn=cmd_xref)

    sp = add("diff", "other")
    sp.add_argument("--gap", type=int, default=256)
    sp.set_defaults(fn=cmd_diff)

    a = p.parse_args(argv)
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
