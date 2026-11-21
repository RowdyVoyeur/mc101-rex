# Patch manifest schema

`manifest/sites.json` is the durable inventory of every MC-101 v1.82 8-track
patch site. During scouting all `patch` values are `null`; the build therefore
acts as a firmware-consistency check. Phase 1 fills in the bytes.

## Top-level fields

| Field | Meaning |
|---|---|
| `schema` | Manifest schema version (currently `1`) |
| `base_address` | Load address of both images (`0x60000000`) |
| `primary_image` | MC-101 decrypted Core 0 image (repo-relative) |
| `reference_image` | MC-707 decrypted Core 0 image (repo-relative) |
| `sites` | MC-101 patch sites |
| `reference_sites` | MC-707 reference checkpoints |

## Site fields

| Field | Meaning |
|---|---|
| `id` | Stable identifier, also used in `8-TRACK.md` |
| `address` | Virtual address (`0x...`) |
| `length` | Number of bytes covered by `expected` |
| `expected` | Hex string of the stock bytes at `address` |
| `patch` | Hex string to write, or `null` for verification-only |
| `area` | `panel`, `bank`, `sel`, `data-model`, `table`, `project`, `mixer`, `aux` |
| `kind` | `verify`, `hook`, `table`, `candidate`, `reference`, `not-a-gate`, `unclassified` |
| `phase` | 0 = baseline, 1 = track selection, 2 = labels, 3 = knob bank, 4 = regression |
| `status` | `verified`, `candidate`, `reference`, `unclassified` |
| `description` | Human-readable finding |

## Address mapping

Both images are flat and loaded at `0x60000000`, so:

```
file_offset = address - 0x60000000
```

The patcher uses this mapping directly.

## Adding a patch

1. Confirm `expected` against the stock image (`cmake --build ... --target verify`).
2. Set `patch` to the replacement hex string.
3. Bump `phase`/`status` and update `8-TRACK.md`.
4. Rebuild and test on hardware.

Never change `expected` to match a patched image; it must always describe stock.
