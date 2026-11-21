#!/usr/bin/env python3
"""Build and verify the MC-101 v1.82 8-track firmware update (Core 0 + Core 1)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

DEFAULT_C0_STOCK = REPO_ROOT / "vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin"
DEFAULT_MANIFEST = HERE / "manifest/sites.json"
DEFAULT_OUT_DIR = REPO_ROOT / "build/8-track/out"


def run(cmd: list[str | Path]) -> None:
    """Run a build/verification step, raising on failure."""
    str_cmd = [str(c) for c in cmd]
    print(f"+ {' '.join(str_cmd)}")
    subprocess.run(str_cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify stock manifest (and any existing outputs) without rebuilding",
    )
    ap.add_argument(
        "--regen-manifest",
        action="store_true",
        help="Regenerate manifest/sites.json via tools/gen_manifest.py before building",
    )
    args = ap.parse_args()

    py = sys.executable
    c0_patched = args.out_dir / "App1_Main_decrypted.8track.bin"
    c0_pkg = args.out_dir / "RPG69_C0A_up.bin"
    c1_pkg = args.out_dir / "RPG69_C1A_up.bin"

    if args.regen_manifest:
        run([py, HERE / "tools/gen_manifest.py"])

    if args.verify_only:
        run([
            py,
            HERE / "tools/patch_image.py",
            "--image", DEFAULT_C0_STOCK,
            "--manifest", DEFAULT_MANIFEST,
            "--check-only",
        ])
        if c0_patched.is_file():
            run([
                py,
                HERE / "tools/verify_patched_image.py",
                "--stock", DEFAULT_C0_STOCK,
                "--patched", c0_patched,
                "--manifest", DEFAULT_MANIFEST,
            ])
        if c1_pkg.is_file():
            run([py, HERE / "tools/repack_qspi_container.py", "--verify", c1_pkg])
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Core 0: verify + patch + verify + package
    run([
        py,
        HERE / "tools/patch_image.py",
        "--image", DEFAULT_C0_STOCK,
        "--manifest", DEFAULT_MANIFEST,
        "--output", c0_patched,
    ])
    run([
        py,
        HERE / "tools/verify_patched_image.py",
        "--stock", DEFAULT_C0_STOCK,
        "--patched", c0_patched,
        "--manifest", DEFAULT_MANIFEST,
    ])
    run([
        py,
        REPO_ROOT / "tools/package_c0a_firmware.py",
        c0_patched,
        "--output", c0_pkg,
        "--no-decryption",
    ])

    # Core 1: patch DSP + verify QSPI container
    run([py, HERE / "tools/patch_c1a_dsp.py", "--out", c1_pkg])
    run([py, HERE / "tools/repack_qspi_container.py", "--verify", c1_pkg])

    print(f"\n[OK] Built {c0_pkg} and {c1_pkg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
