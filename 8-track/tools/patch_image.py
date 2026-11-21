#!/usr/bin/env python3
#
# Copyright 2026 Ed Coffey
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v.2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
"""Verify and apply the MC-101 8-track patch-site manifest.

The manifest (``manifest/sites.json``) is the durable, declarative inventory of
every patch site. Each site records:

- ``address``  : virtual address in the image's load address space
- ``length``   : number of bytes covered by ``expected``
- ``expected`` : hex string of the stock bytes at that address
- ``patch``    : hex string to write, or null for verification-only sites

For the current scouting phase every ``patch`` is null, so the tool acts as a
firmware-version consistency check: it proves the inventory still matches the
stock decrypted image without changing a single byte.

Usage:
    patch_image.py --image App1_Main_decrypted.bin \
                   --manifest manifest/sites.json \
                   --output build/App1_Main_decrypted.8track.bin

    patch_image.py ... --check-only
    patch_image.py ... --reference-image RPG68_C0A_clean_decrypted.bin
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_address(value: str) -> int:
    return int(value, 0)


def hex_to_bytes(value: str) -> bytes:
    if value is None:
        return b""
    value = value.strip().replace(" ", "")
    if value == "":
        return b""
    if len(value) % 2:
        raise ValueError(f"hex string has odd length: {value!r}")
    return bytes.fromhex(value)


def load_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def verify_sites(sites: list[dict], image: bytes, base: int, label: str) -> tuple[int, int]:
    """Return (checked, failures) and print a line per failure."""
    checked = 0
    failures = 0
    for site in sites:
        expected = site.get("expected")
        if not expected:
            continue
        addr = parse_address(site["address"])
        length = int(site["length"])
        want = hex_to_bytes(expected)
        if len(want) != length:
            print(
                f"[-] {label} {site['id']}: manifest length {length} does not match "
                f"expected byte count {len(want)}",
                file=sys.stderr,
            )
            failures += 1
            continue
        off = addr - base
        if off < 0 or off + length > len(image):
            print(
                f"[-] {label} {site['id']}: address 0x{addr:08X} (+{length}) is "
                f"outside the image",
                file=sys.stderr,
            )
            failures += 1
            continue
        got = image[off : off + length]
        checked += 1
        if got != want:
            failures += 1
            first = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
            print(
                f"[-] {label} {site['id']} @0x{addr:08X}: mismatch at offset "
                f"{first} (got {got[first]:02x}, expected {want[first]:02x})",
                file=sys.stderr,
            )
    return checked, failures


def apply_patches(sites: list[dict], image: bytearray, base: int) -> int:
    """Apply every non-null patch in-place. Returns the number applied."""
    applied = 0
    for site in sites:
        patch = site.get("patch")
        if not patch:
            continue
        addr = parse_address(site["address"])
        data = hex_to_bytes(patch)
        off = addr - base
        image[off : off + len(data)] = data
        applied += 1
        print(f"[+] applied {site['id']} @0x{addr:08X} ({len(data)} bytes)")
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify and apply the MC-101 8-track patch-site manifest."
    )
    parser.add_argument("--image", required=True, type=Path, help="Input decrypted image")
    parser.add_argument("--manifest", required=True, type=Path, help="sites.json")
    parser.add_argument("--output", type=Path, help="Output image (required unless --check-only)")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify expected bytes; do not write an output image",
    )
    parser.add_argument(
        "--reference-image",
        type=Path,
        help="Optional MC-707 reference image to verify reference_sites against",
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Override the image load base (default: manifest base_address)",
    )
    args = parser.parse_args()

    if not args.image.exists():
        print(f"[-] input image not found: {args.image}", file=sys.stderr)
        return 1
    if not args.manifest.exists():
        print(f"[-] manifest not found: {args.manifest}", file=sys.stderr)
        return 1
    if not args.check_only and args.output is None:
        print("[-] --output is required unless --check-only is used", file=sys.stderr)
        return 1

    manifest = load_manifest(args.manifest)
    base = parse_address(args.base) if args.base else parse_address(manifest["base_address"])
    image = args.image.read_bytes()

    sites = manifest.get("sites", [])
    checked, failures = verify_sites(sites, image, base, "MC-101")

    refs = manifest.get("reference_sites", [])
    if args.reference_image:
        if not args.reference_image.exists():
            print(f"[-] reference image not found: {args.reference_image}", file=sys.stderr)
            return 1
        ref_image = args.reference_image.read_bytes()
        ref_checked, ref_failures = verify_sites(refs, ref_image, base, "MC-707")
        checked += ref_checked
        failures += ref_failures
    elif refs:
        print(f"[*] skipping {len(refs)} reference sites (no --reference-image)")

    total_patchable = sum(1 for s in sites if s.get("patch"))
    print(
        f"[*] {args.image}: {checked} sites checked, {failures} mismatch(es), "
        f"{total_patchable} patch(es) armed"
    )

    if failures:
        print("[-] verification FAILED", file=sys.stderr)
        return 1

    if args.check_only:
        print("[+] verification OK")
        return 0

    out_image = bytearray(image)
    applied = apply_patches(sites, out_image, base)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(out_image)
    print(f"[+] wrote {args.output} ({len(out_image):,} bytes, {applied} patch(es) applied)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
