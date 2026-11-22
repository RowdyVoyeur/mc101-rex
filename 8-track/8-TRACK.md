# MC-101 8-Track Enablement — Scouting Report and Patch Plan

Status: **Implementation complete and verified**.

This document plans and describes how to expose the MC-101's hidden tracks 5–8 by patching the
Core 0 application image (`App1_Main_decrypted.bin`, `RPG69_C0A`, base `0x60000000`).
The MC-707 1.82 Core 0 image (`RPG68_C0A_clean_decrypted.bin`, same base) is used as
the 8-track reference implementation.

Everything in this directory (`8-track/`) is the workspaces for the patch: plan, site
manifest, patcher, verifier, and injected Thumb payloads.

---

## 1. Executive summary

The important conclusion from scouting is:

> **The MC-101 track data model is already 8-wide. Tracks 5–8 exist in the project
> format, the parameter tree, the per-track buffer table, and the track-count logic.
> What is missing is UI exposure: the panel dispatcher only routes four select
> buttons (logical IDs 6–9) to `SelectTrack`, and the on-screen label tables only
> contain four entries.**

Consequences:

- No large "4 → 8" data-model rewrite is required.
- The primary gate is a handful of bytes in the panel dispatcher
  (`FUN_60035558`) plus a bank/selection state.
- The MC-707 equivalents of the core track functions are byte-for-byte similar and
  also loop to 8, which is strong confirmation that the 4-track limit on the MC-101
  is a product/UI decision, not an engine limitation.
- Secondary work is cosmetic/UI: 4-wide label tables, a 4-wide level-meter widget
  table, and any screen that lays out one column per track.

---

## 2. Evidence

### 2.1 Images and address spaces

| Image | File | Load base | Code/rodata extent | Scatterload table |
|---|---|---|---|---|
| MC-101 Core 0 | `vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin` | `0x60000000` | `0x60000000`–`0x6031279C` | `0x602C9904` |
| MC-707 Core 0 | `vendor/mc707_sys_v182/extracted/RPG68_C0A_clean_decrypted.bin` | `0x60000000` | `0x60000000`–`0x603D8AE0` | `0x6037BECC` |

Both are flat images loaded at `0x60000000`, so `file_offset = address - 0x60000000`
(the patcher uses this direct mapping).

### 2.2 The MC-101 already stores 8 tracks

Confirmed in the MC-101 image itself (not just inferred from the MC-707):

- **8 per-track project/section names** at `0x602A88F0`:
  `Track1 CLIP PHR_CC` … `Track8 CLIP PHR_CC`.
- **Packed track names**: `TRACK1`..`TRACK8` at `0x6021AC6F`, `T1`..`T8` at
  `0x6021ACB0`.
- **Genuine 8-entry track buffer pointer table** at `0x6021ACF0`:
  `0x619928F0, 0x619F4930, 0x61A56970, 0x61AB89B0, 0x61B1A9F0, 0x61B7CA30,
  0x61BDEA70, 0x61C40AB0` — 8 pointers, stride `0x62040`.
- **Per-track-clip stride** `0x5C40` used by the copy/count helpers
  (`FUN_60051EC0`, `FUN_6005200C`, `FUN_60054134`), which build 8-entry base-pointer
  tables (`local_40[0..7]`).
- **Track-count-by-type already loops 8** in `FUN_60051744`
  (`cmp r5,#8` at `0x6005177C`, `0x60051798`, `0x600517B4`).
- **Track-slot limit logic already permits 8** in `FUN_600542CC`
  (`0x600542F8`–`0x60054312`): if there is no looper track the limit is `8`,
  otherwise `5`; it is compared against the type-2 track count.

Cross-check with the MC-707 reference:

- `FUN_60051744` (MC-101) hash-matches `FUN_60065F38` (MC-707). Both implement the
  same type counting with `iVar3 < 8`.
- `FUN_60050D70` (MC-101 `GetTrackType`) hash-matches `FUN_60064F50`.
- The parameter getter/setter pair hash-matches:
  MC-101 `FUN_6009CB2C` → MC-707 `FUN_600DD91C`;
  MC-101 `FUN_6009CB9C` → MC-707 `FUN_600DD98C`.

### 2.3 The actual gate: panel dispatch

`FUN_6001E1F4` is the panel-event trampoline. It reads the logical button ID from
`*(short *)(event + 2)` and calls the main dispatcher
`FUN_60035558(this, button_id)` at `0x6001E1FE`.

`FUN_60035558` then:

1. Handles buttons `10..14` early (MFX / SOUND / FILTER / MOD / FX) with a 5-entry
   TBB at `0x60035680`; this writes the current "edit page" state.
2. Falls through to a `TBH` at `0x600356B6` (table at `0x600356C0`) that dispatches
   all button IDs.

The decoded TBH table for the track-select range is:

| Button ID | Physical MC-101 control | TBH target | Meaning |
|---|---|---|---|
| `6` | `SEL1` | `0x60035CBC` | `SelectTrack(0)` |
| `7` | `SEL2` | `0x60035CBC` | `SelectTrack(1)` |
| `8` | `SEL3` | `0x60035CBC` | `SelectTrack(2)` |
| `9` | `SEL4` | `0x60035CBC` | `SelectTrack(3)` |
| `10` | `MFX` | `0x6003644A` | (also consumed by the 10–14 block) |
| `11` | `SOUND` | `0x60035E9A` | knob/edit page |
| `12` | `FILTER` | `0x60035F3E` | knob/edit page |
| `13` | `MOD` | `0x60036010` | knob/edit page |
| `14` | `FX` | `0x60036084` | knob/edit page |

The four select cases converge on:

```
60035CBC  subs  r1, r4, #6      ; a1 1f      track = button - 6
60035CBE  mov   r0, r5          ; 28 46
60035CC0  bl    0x600344CC      ; fe f7 04 fc  SelectTrack(track)
```

`FUN_600344CC` is the real `SelectTrack(track)`:

```
600344D4  bmi  ...              ; negative -> 0
600344D6  cmp  r4, #8           ; 08 2c
600344D8  it   ge               ; a8 bf
600344DA  movge r4, #7           ; 07 24
```

So `SelectTrack` already accepts `0..7` and clamps to `7`. The only reason the user
can never reach 4–7 is that no UI path ever passes those indices.

MC-707's logical button table at `0x6037D92C` maps IDs `6..13` to `SEL1..SEL8`,
confirming the 8-track layout uses the same dispatcher shape with a wider table.

### 2.4 Current-track state and notifications

- Getter: `FUN_6009CB2C(3, 0, -1)` — group `3`, param `0` = current track.
  Used by 132 MC-101 functions (209 call sites).
- Direct writer: `FUN_6009CB9C(3, 0, value, ...)` — e.g. inside `FUN_60054598`
  at `0x60054662`.
- `FUN_600344CC` notifies listeners with `FUN_6009BFDC(0x1C, track)` at `0x6003458A`.
- Per-track type lives at `(7, 0x3C9, track)`; per-track "exists/selected" at
  `(7, 0x3CA, track)`.

Because all of these are indexed by a plain track number and iterate to 8, simply
supplying track indices 4–7 is sufficient for the engine side.

---

## 3. Patch-site inventory

The inventory is split by subsystem. `ID` values are used by
`manifest/sites.json` and the patcher.

Legend: **V** = verified against the stock image; **C** = candidate, still needs
confirmation before patching.

### 3.1 Panel input and track selection (primary gate)

| ID | Address | Function | Finding | Action |
|---|---|---|---|---|
| `UI-01` | `0x6001E1F4` | panel trampoline | Reads `event+2`, calls dispatcher | Optional hook point for bank state |
| `UI-02` | `0x60035558` | main panel dispatcher | TBH table at `0x600356C0`; IDs 6–9 → `0x60035CBC` | **Primary patch**: add bank offset |
| `UI-03` | `0x60035CBC` | dispatcher SEL case | `subs r1,r4,#6` (V: `a1 1f`) | Change to `button - 6 + bank*4` |
| `UI-04` | `0x60035CC0` | dispatcher SEL case | `bl 0x600344CC` (V: `fe f7 04 fc`) | Keep; or redirect through a trampoline |
| `UI-05` | `0x600344CC` | `SelectTrack` | Clamps 0..7 (V: `08 2c / a8 bf / 07 24`) | **No change needed** (already 8-wide) |
| `UI-06` | `0x60035C96`–`0x60035C9E` | SEL LED/highlight | `ldrh` + `orr #4` on UI state | Extend for 8 (cosmetic) |
| `UI-07` | `0x602CABA4` | logical button name table | `[6..9]=SEL1..4`, `[10..13]=MFX/SOUND/FILTER/MOD` (V) | Extend/repoint if remapping IDs |
| `UI-08` | `0x602A873C` etc. | label string pool | `SEL1..SEL4`, `LEVEL1..4`, `MEAS_P1..4` (V) | Add `SEL5..8`/`LEVEL5..8` labels (cosmetic) |

**Recommended in-place change** for `UI-03`: replace the 2-byte
`subs r1, r4, #6` with an equivalent that adds the bank. Since `0x60035CBC` is
inside a dense dispatcher, the clean approach is a 4-byte branch (`b.w`) to a
trampoline in a code cave, which computes `r1 = r4 - 6 + (bank << 2)` and branches
back to `0x60035CC0`. This is cleaner than trying to squeeze bank logic into
2-byte Thumb instructions.

### 3.2 Bank/selection state

| ID | Address | Function | Finding | Action |
|---|---|---|---|---|
| `BNK-01` | `0x60035558` | dispatcher | No bank concept today | Add `bank` byte to a spare global |
| `BNK-02` | `0x60035CBC` | SEL case | Always selects lower bank | Apply bank offset |
| `BNK-03` | `0x600344CC` | `SelectTrack` | No bank awareness | Keep engine call pure; bank is UI-only |
| `BNK-04` | `0x6003458A` | `SelectTrack` notify | Notifies `(0x1C, track)` | Listeners already handle 0..7 |

The bank is **cosmetic UI state**; it must not leak into the project data model.
Store it in a spare byte of the UI/context struct (the same class of global as
`DAT_60035954`), and reset it on mode changes (`EXIT`, `PROJECT`, `CLIP`, `SEQ`,
`NOTE`, etc.) to avoid surprising the user.

### 3.3 8-wide SEL scan (already written for 8)

| ID | Address | Function | Finding | Action |
|---|---|---|---|---|
| `SEL-01` | `0x60097A88` | clip/note UI | Loops logical IDs `6..13` with `cmp r4,#8` at `0x60097AF6` (V: `08 2c f1 db`) | Works as-is; IDs 10–13 collide with MFX/SOUND/FILTER/MOD |
| `SEL-02` | `0x60097C2C` | clip/note UI | Additional `cmp #8` on track/step indexing | Verify not a 4-wide gate |
| `SEL-03` | `0x60065A84` | clip/looper handler | Derives track via `subs r1,r4,#6` at `0x60065E12` before `SelectTrack` | **Second gate**: must also gain bank offset or be repointed |
| `SEL-04` | `0x6007DFB2` | (uncertain) | Third call to `SelectTrack`; Ghidra does not recognize containing function | Locate and classify before patch |

`SEL-03` is important: `FUN_60065A84` is a second, independent path into
`SelectTrack`, so the bank logic must be applied consistently in both
`FUN_60035558` and `FUN_60065A84`, or better, inside a single trampoline that both
call.

### 3.4 Track-slot data model (verified 8-wide; no patch)

| ID | Address | Function | Finding |
|---|---|---|---|
| `DM-01` | `0x60051744` | `CountTracksByType(type)` | Loops `0..7` (V) |
| `DM-02` | `0x60050D70` | `GetTrackType(track)` | `FUN_6009CB2C(7,0x3C9,track,0)`; MC-707 match `FUN_60064F50` |
| `DM-03` | `0x60051EC0` | clip copy/init | 8-entry base-pointer table |
| `DM-04` | `0x6005200C` | clip copy/init | 8-entry base-pointer table |
| `DM-05` | `0x60054134` | clip copy/init | 8-entry base-pointer table |
| `DM-06` | `0x600542CC` | track-slot limit | limit `8` (no looper) / `5` (looper) (V) |
| `DM-07` | `0x60054598` | current-track setter | Writes `(3,0)` at `0x60054662` |
| `DM-08` | `0x6021ACF0` | track buffer table | 8 pointers, stride `0x62040` (V) |

No patches are expected here. These are the functions to regression-test after the
UI patch.

### 3.5 4-wide UI label/config tables

These tables hold exactly four track labels. They must either be extended to eight
or made bank-aware (show `1–4` or `5–8` depending on the bank).

| ID | Address | Contents | Finding |
|---|---|---|---|
| `TBL-01` | `0x602CABA4` | logical button names | `SEL1..SEL4` then `MFX/SOUND/FILTER/MOD` (V) |
| `TBL-02` | `0x602A873C` | `SEL1` string pool | 4 entries, stride 0x2C |
| `TBL-03` | `0x602A8744` | `LEVEL1..4` | referenced by `0x602CACB4`, `0x602CAD0C`, `0x602CC25C` |
| `TBL-04` | `0x602A874C` | `MEAS_P1..4` | referenced by `0x602CACA4` |
| `TBL-05` | `0x602CAC80` | UI element names | `MEAS_P1..4`, `LEVEL1..4`, pads, `C1..C4` |
| `TBL-06` | `0x602CC240` | UI element names | `LEVEL1..4`, `C1..C4`, boot/menu strings |
| `TBL-07` | `0x60227CC0` | 16-byte widget/encoder records | `C4`, `DUMMY`, `LEVEL1..4`, `DUMMY` |

Reference: the MC-707 label pool at `0x6033BD5C` already contains
`SEL1..SEL8`, `LEVEL1..8`, `TR1_P1..TR8_P1`, `FILTER1..8`, `FX1..8`, and the
MC-707 button table at `0x6037D92C` maps `6..13` to `SEL1..SEL8`.

Important: `TBL-03`/`TBL-04` are pointer *tables* whose entries point into the
string pool. Extending them requires either appending new strings into a code cave
or reusing the MC-707-style packed names. The patcher should treat these as a
single logical table replacement, not independent byte edits.

### 3.6 Menu / project / save-load

| ID | Address | Finding |
|---|---|---|
| `PRJ-01` | `0x602A88F0` | `Track1..Track8 CLIP PHR_CC` — project format already 8-wide (V) |
| `PRJ-02` | `0x6021AC6F` | packed `TRACK1..TRACK8` (V) |
| `PRJ-03` | `0x6021ACB0` | packed `T1..T8` (V) |

No project-format change is needed. The existing save/load code can already carry
eight tracks; verify by creating a project with tracks 5–8 after the UI patch.

### 3.7 Mixer / level meter

| ID | Address | Finding |
|---|---|---|
| `MIX-01` | `FUN_60060528` (MC-707) | mixer level display switches on `this+0x1A18` cases `0..10` → EXT IN/PC IN/TRACK1..8/MIX OUT |
| `MIX-02` | MC-101 | **no** `LEVEL : TRACK n` / `TRACKn_L Level` strings |
| `MIX-03` | `0x602C4BE0` | MC-101 `LEVEL1_B/G/R` bitmap assets exist (4 banks) |

The MC-101 does not have the MC-707's numeric mixer screen. A "level meter per
track" for tracks 5–8 therefore needs either:
- a new small screen, or
- a 4-wide meter that follows the current bank (simplest; matches the physical UI).

Because the MC-101 only has four knobs/level indicators, the bank-following meter
is the recommended approach.

### 3.8 Auxiliary 4-wide loops and candidate gates

| ID | Address | Function | Finding | Status |
|---|---|---|---|---|
| `AUX-01` | `0x600527E0` | UI layout | Loops `0..3` at `0x60052A58`, `0x600530BC`, `0x600533E0` | C: likely 4-column display, not engine |
| `AUX-02` | `0x60052FFC`, `0x60052A7E` | UI layout | `cmp #4` on a mode, not track | C: not a gate |
| `AUX-03` | `0x60097ABA` | clip UI | `cmp r0,#4` on a mode | C: not a gate |
| `AUX-04` | `0x6005BAA4` | "TRACK 1 - 5" layout | Switch on `DAT_6005BD90`, not track count | Not a gate |
| `AUX-05` | `0x6005B6A8` | saved-model splash | Save/UI, not track count | Not a gate |

These are recorded so they are not re-investigated. The 26 `cmp #4` vs `cmp #8`
candidates from the hash-matched function diff are listed in
`/tmp/opencode/xmatch/cmp_map.json` during development; none was a decisive track
gate.

---

## 4. UI proposal for the MC-101 panel

### 4.1 Physical constraint

The MC-101 has:

- **4 track-select buttons** (logical IDs `6..9`, labelled `SEL1..SEL4`), and
- **4 knobs `C1..C4`** (no physical faders; the MC-707 is the model with 8 faders).

The user request refers to "4 faders/knobs". On real MC-101 hardware these are the
four knobs `C1..C4`; the plan below treats them as the per-track control bank.

### 4.2 Track selection: toggle / bank (recommended)

Recommended behaviour, matching the requirement "pressing selected 1 selects 5":

- Maintain a 1-bit `track_bank` state (0 = tracks 1–4, 1 = tracks 5–8).
- Pressing `SELn`:
  - if `track_bank == 0` and `n` is **not** the currently selected lower track →
    select track `n` (normal behaviour, bank stays 0);
  - if `track_bank == 0` and `n` **is** the currently selected lower track →
    set `track_bank = 1` and select track `n + 4`;
  - if `track_bank == 1` and `n` is the currently selected upper track →
    clear `track_bank` and select track `n`;
  - otherwise select track `n + 4`.
- Any mode button (`PROJECT`, `CLIP`, `SEQ`, `NOTE`, `SCAT`, `EXIT`, `ENTER`)
  clears `track_bank`.
- The four `SEL` LEDs indicate the bank: steady = lower, blinking/alternate
  pattern = upper. If LED patterns are too invasive, show `TRACK 5–8` in the
  existing status display.

This gives full access with zero new buttons and no chords.

### 4.3 Alternative selection schemes (evaluated, not recommended)

| Scheme | Mapping | Pros | Cons |
|---|---|---|---|
| Chord | `SEL1+SEL2`→5, `SEL1+SEL3`→6, `SEL1+SEL4`→7, `SEL2+SEL3`→8 | No extra state | Ambiguous, hard to discover, conflicts with multi-press handling |
| Double-click | single = 1–4, double = 5–8 | Familiar | Needs a timing window in the panel ISR; risk of lag |
| Long-press | long SELn = track n+4 | Simple | Conflicts with other long-press semantics |
| Toggle (chosen) | second press on active SEL → upper | Stateless per press, discoverable | Needs current-track comparison |

### 4.4 Knob/fader bank

When `track_bank == 1`, the four knobs `C1..C4` should address tracks 5–8 instead
of 1–4. Implementation options:

1. **Index translation in the knob event path** (recommended): translate knob
   index `n` to track `track_bank*4 + n` when the current knob mode is a per-track
   mode (`LEVEL`, `MEAS_P`, etc.). This reuses the existing parameter plumbing.
2. **Bank-aware widget table**: patch the 16-byte widget records at `0x60227CC0`
   so the `LEVEL1..4` slots point at the current bank's track. This is simpler but
   requires editing pointer tables in place.
3. **Two banks of knob assignments**: store two copies of the assignment table and
   swap the base pointer. Most robust, but needs a code cave.

The knob route must be validated against the MC-707 `FADER.IMG` /
`FADERSINGLE_ACTIVE__34.IMG` assets, which show the MC-707 implements fader
positions as a separate display layer. The MC-101 has no equivalent fader layer,
so option 1 is the least invasive.

---

## 5. Implementation phases

### Phase 0 — Baseline (this change)

- Record all sites in `manifest/sites.json`.
- Build a patched image with **no byte changes**; verify every `expected` byte
  string matches the stock image. This catches accidental cross-version drift.
- Tooling: `cmake -G Ninja`, `cmake --build build-8track`, `ctest`.

### Phase 1 — Track selection gate

- Add `track_bank` state and the toggle semantics.
- Patch the two `SelectTrack` entry paths:
  - `FUN_60035558` SEL case (`0x60035CBC`),
  - `FUN_60065A84` clip/looper case (`0x60065E12`).
- Prefer a single shared trampoline so both paths cannot diverge.
- Acceptance: `SEL1..SEL4` can select tracks 1–8; `SelectTrack(4..7)` reaches the
  engine; project save/load preserves tracks 5–8; transport and clip playback work
  on all eight tracks.

### Phase 2 — UI labels and screens

- Add/bank-switch `SEL5..8`, `LEVEL5..8`, `MEAS_P5..8`.
- Make the level meter follow the active bank.
- Update LED feedback for the bank.
- Acceptance: no out-of-range label lookups, no crash when a track has no clip.

### Phase 3 — Knob/fader bank

- Translate knob indices 0–3 to tracks `bank*4 + n`.
- Add a visible indicator when knobs are on the upper bank.
- Acceptance: knob edits affect the expected track in both banks.

### Phase 4 — Regression

- Track types: MIDI, audio, looper.
- Looper limit (`FUN_600542CC`): limit 8 when no looper, 5 when a looper exists.
- Project save/load round trip with eight tracks.
- Existing four-track projects load unchanged.

---

## 6. Build system

The scaffold lives in `8-track/` and is driven by CMake + Ninja.

```
8-track/
├── 8-TRACK.md              # this document
├── CMakeLists.txt          # build entry point
├── CMakePresets.json       # Ninja presets
├── manifest/
│   └── sites.json          # patch-site inventory (with expected bytes)
├── tools/
│   ├── patch_image.py      # verify + apply manifest -> built binary
│   └── scout_strings.py    # Capstone string/xref scout used during RE
└── src/                    # (phase 2+) injected Thumb payload sources
```

### 6.1 Configure and build

```bash
cmake -S 8-track -B build-8track -G Ninja
cmake --build build-8track            # verify + produce patched image
cmake --build build-8track --target verify
cmake --build build-8track --target package
```

Outputs:

- `build-8track/out/App1_Main_decrypted.8track.bin`
- `build-8track/out/RPG69_C0A_up.bin` (only with the `package` target)

### 6.2 How the patcher works

`tools/patch_image.py` reads `manifest/sites.json`:

- Each site records `address`, `expected` bytes, optional `patch` bytes, a phase,
  and a status.
- `--check-only` verifies `expected` at every site and fails on mismatch.
- Without `--check-only`, it verifies then applies every non-null `patch` and
  writes the output image.
- Sites with `"patch": null` are **verification-only** until implementation.

This deliberately satisfies the current constraint ("scout, do not implement exact
byte changes yet"): the build succeeds and proves the inventory is correct, while
the actual patch bytes remain `null` until Phase 1.

### 6.3 Packaging

`tools/package_c0a_firmware.py` (repo root) repackages the patched payload as a
Roland `RPG69_C0A_up.bin` container, recomputing the payload CRC-32 (header word
20) and the IEEE 802.3 CRC-32 trailer. The default plaintext control word is used
for development; the stock encrypted control word is available with `--encrypted`
once the patch is finalized.

---

## 7. Risks and open questions

1. **Two `SelectTrack` callers.** `FUN_60035558` and `FUN_60065A84` both compute
   `button - 6`. Patching only one leaves an inconsistent path. The plan uses one
   shared trampoline.
2. **Led/UI state uses 4-slot assumptions.** `FUN_60035558` sets highlight bits and
   the level meter is 4-wide. Expect cosmetic bugs until Phase 2.
3. **Third `SelectTrack` call at `0x6007DFB2`.** Ghidra did not identify the
   containing function. Must be located and classified before Phase 4.
4. **Looper limit semantics.** `FUN_600542CC` uses `8`/`5`; confirm whether the
   `5` is "4 + one looper" and whether exposing 8 tracks should raise it.
5. **Plaintext boot path.** Repackaging with the no-decryption control word relies
   on App0 accepting plaintext payloads. Confirm on hardware with a
   no-op-patched image before shipping a real patch.
6. **MC-101 has knobs, not faders.** If the requirement literally means physical
   faders, the MC-101 cannot provide them without external MIDI/CC input; the
   knob-bank design is the closest native equivalent.

---

## 8. Reference: MC-101 ↔ MC-707 address map

| Role | MC-101 | MC-707 |
|---|---|---|
| `CountTracksByType` | `FUN_60051744` | `FUN_60065F38` |
| `GetTrackType` | `FUN_60050D70` | `FUN_60064F50` |
| Parameter getter | `FUN_6009CB2C` | `FUN_600DD91C` |
| Parameter setter | `FUN_6009CB9C` | `FUN_600DD98C` |
| Logical button table | `0x602CABA4` (`SEL1..4`) | `0x6037D92C` (`SEL1..8`) |
| Track label pool | `0x602A873C` (4 wide) | `0x6033BD5C` (8 wide) |
| Mixer level display | none | `FUN_60060528` |
| Track buffer table | `0x6021ACF0` (8) | — |

---

## 9. Detailed Implementation Specification (Implemented)

All 48 active patches are assembled via `arm-none-eabi-as` by `tools/gen_manifest.py`, stored in `manifest/sites.json`, applied by `tools/patch_image.py`, and verified via Capstone disassembly in `tools/verify_patched_image.py`.

### 9.1 Safe SDRAM Code & Table Cave (`0x602D2600..0x602D2A84`, 1,156 bytes)

The patched helpers and tables are located in a verified 6,864-byte contiguous zero-padded executable SDRAM region (`0x602D2600..0x602D40D0`) with zero incoming pointers:

- **`CAVE-01` (`0x602D2600..0x602D27FF`, 512 bytes, 378 bytes used)**:
  - `get_cur_track` (`0x602D2600`): Queries `CurTrack = fw_get_param(3, 0, -1, 0)` (`0..7`).
  - `resolve_sel_track` (`0x602D2612`): Given `r4 = 6..9` (`SEL1..4`), computes `cand = (r4 - 6) + (CurTrack & 4)`. When `cand == CurTrack`:
    - If `[START]` (`button 0x12`, Start/Stop Track) is held, keeps `target = cand`.
    - If `[SHIFT]` (`button 0`, Track `EDIT` menu `Screen 0x36`) is held and `GetActiveScreenId()` (`0x6001CC44`) is not yet `0x36`, keeps `target = cand` so the first `[SHIFT] + [SELn]` enters the `EDIT` menu for the currently selected track, and pressing `[SHIFT] + [SELn]` again while in `Screen 0x36` toggles `cand ^= 4` between the printed track (`1..4`) and the `+4` track (`5..8`).
    - Otherwise toggles bank (`target = cand ^ 4`).
    Updates `r4 = target + 6`, mirrors active track `r6` to `cur_track_var` at `0x602D27FC` (dedicated word in `CAVE-01` so ITCM fader and knob handlers can read it atomically without cross-boundary branching or UI struct collisions) **and** to the stock selected-track byte `*(int8_t *)0x61800200` (read by `UpdateFaderRgbLeds`/`UpdateSelButtonLeds`, bank bit = bit 2), and returns `target` (`0..7`) in `r0` and `r1`.
  - `tramp_sel_main` (`0x602D265E`) & `tramp_sel_empty` (`0x602D2668`): Shared entry hooks for `HandleButtonPress` (`0x60035CBC`) and `HandleEmptyTrackScreen` (`0x60065E04`).
  - `tramp_sel_led_check` (`0x602D267C`): Bank-aware helper for `UpdateSelButtonLeds` (`0x600977AC`). For tracks 1–4 (`r6 < 4`), illuminates (or flashes in `EDIT` mode) the button matching `r6 & 3` and leaves the other 3 dark; for tracks 5–8 (`r6 >= 4`), inverts the illumination so the other 3 buttons are illuminated (or flashing in `EDIT` mode) and the button matching `r6 & 3` is dark.
  - `tramp_fdr_top` (`0x602D2694`) & `tramp_fdr_bot` (`0x602D26AA`): Banked loop control for `UpdateFaderRgbLeds` (`0x60099200`). `tramp_fdr_top` (hooked at `FDR-BANK-TOP`, `0x60099212`) reads the bank from bit 2 of the selected-track byte `*[r5+0x10] == 0x61800200` — the same lockless byte the stock gate at `0x60099224` tests, never `fw_get_param` (§9.6, mutex in ISR) — rebuilds `r4 = r7 + bank` (`r7` = physical fader `0..3`), and returns the banked record pointer `*[r5+0xc] + r4*0x100` in `r0`, so the record-mode/colour reads, pid `0x90 + r4` state queries (`0x90..0x97` are all dispatched), engine track-index queries (`uxth r1, r4`) and the selected/record gate follow the bank as stock code. `tramp_fdr_bot` (hooked at `FDR-BANK-BOT`, `0x600992BC`) is plain stock loop control on the physical counter (`adds r7, #1 / cmp r7, #4`, flags for the stock `blt 0x60099212`), and must **not** touch `r4` or recover the bank from it: `r4 == 4` occurs in bank A, so `r4 & 4` reads as "bank B" there, the counter wraps, and the loop never terminates inside the timer ISR (README §1 BF-8).
  - `tramp_fdr_ledid1` (`0x602D26B0`) & `tramp_fdr_ledid2` (`0x602D26BC`): Un-bank the two fader RGB LED id computations (`0x600992B0` steady path, `0x60099356` flash/red path) to `0x1c + (r4 & 3)`, because with banked `r4` the stock `add.w r0, r4, #0x1c` would address **pad** LED ids `0x20..0x23` (LED map `0x601d0554`: `0x1c..0x1f` fader RGB, `0x20..0x2f` pads). `tramp_fdr_ledid2` also re-supplies the LED mode `#3` that stock took from `r7` (`mov r1, r7` at `0x6009935A`), now that `r7` is the loop base. The steady colour needs no hook: it comes from `record[banked] + 0x224` natively (the former `tramp_fader_color_idx` + `LED-FDR-COL1..4` sites are deleted — with banked `r4` they double-banked the record pointer).
  - `tramp_drum_mute_led` (`0x602D26D0`) & `tramp_drum_mute_press` (`0x602D26E8`): Bank-aware helpers for Drum-Pad Mute (`SEL1..4 + Pad`).
  - `tramp_knob_multi_r6` (`0x602D26FA`) & `tramp_knob_multi_r5` (`0x602D270C`): Bank-aware helpers for `HandleKnobEvent` (`0x60036940`) in `MULTI` knob mode (hooked before the `Single` knob-mode merge targets `0x60036A1A` and `0x60036B6E`).
  - `tramp_prj_load_init` (`0x602D2724`): Project-load initialization reached by `PRJ-POST-LOAD` (`b.w` from `0x60046424`). Resets the active-track variables (`cur_track_var` `0x602D27FC` and the stock selected-track byte `0x61800200`) to `0`, fills `tone_level_cache[0..7] = 100` (`0x200199F8`), and for tracks 5–8 sets Area 2 fader params `0x4B + t*3` to `255` via `fw_set_param(2, 0x4B + t*3, 255, -1)` (`0x6009CB9C`) **and** dispatches `255` to the Sound Engine DSP mixer queue via `fw_set_dsp_param(255, 0x4B + t*3)` (`0x6006C82C`). The DSP dispatch is what unmutes the upper bank at project load: deleting this routine made tracks 5–8 start at zero volume again (hardware verified both ways, README §2 Attempts 9–10).
    **Tail-call frame contract (do not modify):** the hook site is the enclosing project-load function's *epilogue* (stock `0ab0bde8f087` = `add sp, sp, #0x28` + `pop.w {r4-r10, pc}`). The routine therefore emulates that epilogue: it opens with `sub sp, sp, #8` and ends with `add sp, sp, #0x30` + `pop.w {r4-r10, pc}` (`0cb0bde8f087`), i.e. `−0x08 + 0x30 == +0x28` with the identical pop mask `0x87F0`. Adding pushes, or changing either `sp` constant, corrupts the caller's frame and faults. `tools/verify_patched_image.py` asserts the stock site bytes, the patch bytes, the hand-decoded `b.w` target, the entry `sub sp, sp, #8`, and the tail sequence inside the target routine.
  - `cur_track_var` (`0x602D27FC`): Dedicated 4-byte atomic variable holding the active track (`0..7`), initialized to 0.
- **`MENU-MIDI-TBL` (`0x602D2800..0x602D2A83`, 644 bytes = `23 * 28` bytes)**:
  - Relocated and expanded `SYSTEM(MIDI):` `ITEM_LIST_PRM` table inserting 4 new 28-byte entries (`grp = 4`, `rel_pid = 0x00F..0x012`, `sub_idx = -1`) for `Track Ch5..8` immediately after `Track Ch4` (`rel_pid = 0x00E`), pointed to by `MENU-MIDI-DESC` at `0x6021A214`.
  - Relocating from `0x6005BAA4` completely restores the stock project loading screen (Screen 0x17, `0x6005BAA4..0x6005BE98`) and string pool (`NOW LOADING...`, `PROJECT`), restoring flawless project and clip sequence loading.

### 9.2 Unrolled ITCM Fader Loop & `MULTI` Knob Handler (`0x01024FD2..0x01025050`, File VA `0x6033776E`)

The MC-101 has 4 physical volume faders (`LEVEL1..4`, ADC IDs `1..4`) and 4 encoders (`C1..C4`, ADC IDs `7..10`). In the stock firmware, the real-time ADC dispatcher in ITCM (`0x01024F0C`, file VA `0x603376A8`) dispatches `r6 = 1..4` via a `TBB` table at `0x01024FA6` to 4 unrolled 32-byte blocks (`0x01024FD2..0x01025050`, 128 bytes total) with hardcoded command IDs `0x3F, 0x42, 0x45, 0x48` (`0x3F + track * 3`):

- **`FDR-ITCM-TBB` (`0x60337742`, exec `0x01024FA6`, 6 bytes)**: Routes all 4 faders (`r6 = 1..4`) to offset `0x16` (`0x01024FD2`).
- **`FDR-ITCM-CODE` (`0x6033776E`, exec `0x01024FD2`, 128 bytes)**:
  - `itcm_fader_entry` (`0x01024FD2`): Directly reads atomic `CurTrack` from `cur_track_var` (`0x602D27FC`), computes `track = (r6 - 1) + (CurTrack & 4)` (`0..7`), computes `cmd_id = 0x3F + track * 3` (`0x3F..0x54`), and sends the level message.
  - `itcm_knob_multi` (`0x01025010`, jumped to from `KNOB-ITCM-MULTI` at exec `0x01025064`): Directly reads atomic `CurTrack` from `cur_track_var` (`0x602D27FC`) and offsets `C1..C4` in `MULTI` mode by `CurTrack & 4` (`r8 = (r6 - 7) + (CurTrack & 4)`).

### 9.3 Menu Parameter Providers Fixed from 4 Tracks to 8 Tracks

All four parameter providers that use a stack lookup table to skip tracks `5..8` are patched in-place to map linearly across all 8 tracks:

| Parameter | GPID | `FormatValue` | `GetValue` | `SetValue` | `GetMinMax` |
|---|---|---|---|---|---|
| `RECORDING: RecSource` | `0x23F` | `0x6006F088` (`PRM-RECSRC-FMT`) | `0x6006F1F8` (`PRM-RECSRC-GET`) | `0x6006F258` (`PRM-RECSRC-SET`) | `0x6006F334`: `5 -> 9` (`PC, TRK1..8, MIXOUT`) |
| `SCATTER EDIT: Position` | `0x483` | `0x6007D0C4` (`PRM-SCATPOS-FMT`) | `0x6007D214` (`PRM-SCATPOS-GET`) | `0x6007D262` (`PRM-SCATPOS-SET`) | `0x6007D32C`: `5 -> 9` (`PC, TRK1..8, MIXOUT`) |
| `SCAT EDIT: DT1 Pos` | `0x4B6` | `0x6007E9F0` (`PRM-SCATDT1-FMT`) | `0x6007EB3A` (`PRM-SCATDT1-GET`) | `0x6007EB86` (`PRM-SCATDT1-SET`) | `0x6007EC50`: `6 -> 10` (`OFF, PC, TRK1..8, MIXOUT`) |
| `TRACK(GEN): Insert` | `0x402` | `0x60070558` (`PRM-TRKINS-FMT`) | `0x6007078E` (`PRM-TRKINS-GET`) | `0x600708C6` (`PRM-TRKINS-SET`) | `0x60070AA6` (already `CurTrack + 3 = 3..10`) |

### 9.4 20-Channel USB `Vendor` Mode Audio Output (Interface 2 AltSetting 1)

When set to `Vendor` USB driver mode (`PID 0x0229` on MC-707, `PID 0x022B` on MC-101), the MC-707 outputs **20 channels** (10 stereo pairs: 1 stereo downmix pair, 8 individual track pairs for Tracks 1–8, and 1 external input pair), whereas the stock MC-101 outputs **10 channels** (5 stereo pairs: 1 stereo downmix pair + 4 individual track pairs for Tracks 1–4). Comparing MC-101 (`0x602CA6B2..0x602CA756`, `0x600AAD74`, `0x600AB480`) against MC-707 (`0x6037CCB2..0x6037CD56`, `0x600EDB5C`, `0x600EE268`) revealed that the entire USB Audio Streaming pipeline is identical except for 8 sites:

- **`USB-DESC-CH` (`0x602CA730`, 1 byte)**: Changes `bNrChannels` in the High-Speed `Vendor` Audio Streaming IN (Interface 2, AltSetting 1) Format Type I descriptor from `0x0A` (`10`) to `0x14` (`20`), matching MC-707 (`0x6037CD30`).
- **`USB-DESC-PKT` (`0x602CA741`, 2 bytes)**: Changes `wMaxPacketSize` on the High-Speed Isochronous IN Endpoint (`0x8E`) descriptor from `0x0108` (`264` bytes) to `0x020C` (`524` bytes), matching MC-707 (`0x6037CD41`).
- **`USB-INIT-CH` (`0x600AADE6`, 2 bytes)**: In `USB_OnBusResetOrConnect` (`0x600AAD74`), changes `movs r6, #0x0a` to `movs r6, #0x14` so hardware USB Audio IN bridge register `0x40080900` is initialized for 20 channels in `Vendor` mode (`2` channels in `Generic` mode), matching MC-707 (`0x600EDBCE`).
- **`USB-INIT-FIFO3` (`0x600AADE8`, 2 bytes)**: In `USB_OnBusResetOrConnect`, changes FIFO parameter 3 from `4` to `6` (`movs r5, #6`, `06 25`), matching MC-707 (`0x600EECD0`), preventing hardware FIFO buffer underrun.
- **`USB-INIT-BURST` (`0x600AADEE`, 2 bytes)**: In `USB_OnBusResetOrConnect`, changes burst size from 48 bytes to 72 bytes (`movs r1, #0x48`, `48 21`), matching MC-707 (`0x600EECAA`).
- **`USB-IF1-BURST` (`0x600AB4AC`, 2 bytes)**: In `USB_OnSetInterface` (`0x600AB480`), changes burst size from 48 bytes to 72 bytes (`movs r6, #0x48`, `48 26`), matching MC-707 (`0x600EF32C`).
- **`USB-IF2-CH` (`0x600AB51E`, 2 bytes)**: In `USB_OnSetInterface`, changes `moveq r2, #0x0a` to `moveq r2, #0x14` when Interface 2 AltSetting 1 is selected in `Vendor` mode before writing hardware USB Audio IN bridge register `0x40080900`, matching MC-707 (`0x600EE306`).
- **`USB-IF2-FIFO3` (`0x600AB58C`, 2 bytes)**: In `USB_OnSetInterface`, changes FIFO parameter 3 from `4` to `6` (`moveq r2, #6`, `06 22`), matching MC-707 (`0x600EF40C`).
- Because the MC-101 lacks external audio input ADC hardware, the 10th stereo pair (`EXT IN`, channels 19–20) remains zeroed in the audio bridge buffer and outputs silence automatically.

### 9.5 8-Track Project File (`.prj`) Load, Save, & Import Verification

A byte-for-byte comparison of the MC-101 and MC-707 project/clip serialization, deserialization, post-load sync, pre-save sync, and project import pipelines confirmed that the stock MC-101 firmware is **already 100% 8-track native** for `.prj` files:

- **Project `.prj` Reader & Writer (`0x6003E500..0x60046000` in MC-101 vs `0x6004AFD0..0x60052D68` in MC-707)**:
  - Instruction-for-instruction identical. All track loops iterate over `0..7` (`cmp r2, #8` at `0x6003EB82`, `cmp.w sl, #8` at `0x6003ED04`, `cmp r5, #8` at `0x6003F134` & `0x6003F14A`, 8-case `tbb` at `0x6003F950`, and all 8 track struct offsets at `0x6003FAC8..0x6003FB30`).
  - Model header validation (`0x6003EAD8` and `0x6003FA8C`) accepts both `Saved Model == 1` (MC-707) and `Saved Model == 2` (MC-101).
- **Post-Load / Pre-Save Sync & Parameter Init (`0x600462C8..0x600466F0` and `0x60054598..0x60054784`)**:
  - Iterates over all 8 tracks (`cmp r4, #8` at `0x60046300`, `0x6004637E`, `0x60046596`, `0x600465C2`, `cmp.w r8, #8` at `0x60046316`, and `cmp r6, #8` at `0x6005476C`).
  - Screen 0x16/0x17 project load event handler and UI routines (`0x6005B3F0..0x6005BE98`) are preserved 100% stock, ensuring clean project loading and sequence deserialization.
- **Track / Clip Import from `.prj` File (`0x6008E4B4..0x6008EDFC` and `0x6007C800..0x6007CA80`)**:
  - Sets the project track count `[r5, #0x648]` to `8` (`0x6008EC7A: movne r0, #8`) and exposes all 8 tracks (`TRACK 1..8`, `T1-01..T8-16`).

### 9.6 Sequencer Track Advancement, Project Load Synchronization, Audio Crossbar, & "Roland MC-107" Branding

- **Sequencer Active Track Count (`SEQ-TRK-CNT`, `0x60342EBA`, 2 bytes)**:
  - The sequencer constructor at `0x60342EBA` sets `*(0x20000F14)` (the active sequencer track count). The stock MC-101 firmware wrote `4` (`04 22`), whereas the MC-707 at `0x60414792` writes `8` (`08 22`).
  - Analysis confirmed that all underlying per-track sequencer buffers on the MC-101 (`0x20000F30`, 8 entries of `0x730`, and `0x200048B0`, 8 entries of `0x54`) are statically sized for 8 tracks in BSS. Patching `0x60342EBA` to `08 22` (`movs r2, #8`) activates clip sequence advancement and triggers for tracks 5–8 without allocating extra heap memory.
- **Project Load Track Preservation (`PRJ-LOAD-PRESERVE`, `0x6005B422`, 16 bytes)**:
  - Replaces the stock New Project wipe loop (`0x6005B422..0x6005B430`), which explicitly deallocated tracks 4..7, with `b.w 0x6005B450` (`target_exit`). In `FUN_6005B3F0` (Screen 0x17 project load completion), Mode 1 (Load Project) jumps directly to `0x6005B432` / `0x6005B450`, bypassing `0x6005B422`.
  - Together with the post-load hook below, this is what makes the upper-4 tracks audible on a cold boot: with the wipe loop bypassed the `.prj` deserializer keeps the project's own stored clips and parameter ranges for tracks 5..8, and `PRJ-POST-LOAD` then pushes unity `255` fader values into the UI shadow and the DSP mixer (hardware verified: audible with no fader touch). Consequence: a project that stores tracks 5..8 at very low volume **is** raised to unity `255` on load.
  - **Project Post-Load Init (`PRJ-POST-LOAD`, `0x60046424`, 6 bytes, `b.w tramp_prj_load_init; nop`)**: Hooks the epilogue of the universal project-load completion function (the function that owns `0x600462C8`, reached from cold boot `FUN_600513a4`, the Screen 0x17 dialog and the reload path `FUN_60054ae4`) and runs `tramp_prj_load_init` (§9.1) as a **tail call** of that epilogue. Required: deleting it made tracks 5..8 start at **zero volume** at project load (README §2, Attempts 9–10) — `PRJ-LOAD-PRESERVE` alone does not set the DSP mixer state for the upper bank. The routine's frame contract is documented in §9.1 and enforced by `tools/verify_patched_image.py` from both sides.
  - **`PRJ-LOAD-INIT` (`0x6005B452`) stays removed**: it sat in the Screen 0x17 dialog event handler, which is not on the cold-boot load path (README §2, Attempt 8). `0x6005B452..0x6005BEA0` and `0x60046420` are asserted stock by `tools/verify_patched_image.py` (see README §1 BF-3/BF-6: that region is the stock project-loading screen and strings).
- **Audio Crossbar Router Initialization (`USB-ROUTER-INIT`, `0x6001ABB0`) — Removed (Attempt 8 DAC regression)**:
  - Historical: hooked `0x6001ABB0` with `b.w tramp_crossbar_init`, configuring the Roland ESC2 audio crossbar routing registers identically to MC-707 `0x6001B010`. Removed because the companion `AUDIO-DAC-CLEAN` early return truncated the stock audio-port init and the trampolines overwrote the stock `0xC01`/`0xC02` output slot assignments, killing DAC audio on all tracks (README §1 REG-1). `0x6001ABB0`, `0x6001AC6C..0x6001ADC8`, `0x6001B030` are verified stock:
    - Downmix L/R: `0x40026660 = 0x800`
    - Track 1: `0x40026668 = 0xc02`
    - Tracks 2–4: `0x4002666C, 0x40026678, 0x40026684 = 0xc01`
    - Tracks 5–7: `0x400266B0, 0x400266B4, 0x400266B8 = 0xc01`
    - Ext In L/R: `0x400266C0, 0x400266C4, 0x40026D30, 0x40026D34 = 0` (clean silence).
    - Bitband register: `0x424C4500 = 0`.
    > **Note on Crossbar DMA Fifos & Peripheral Clashes**: Earlier revisions attempted to route Tracks 5–8 using registers `0x40026688` and `0x400266BC`. However, on Roland ESC2 hardware, `0x40026688` and `0x400266BC` are streaming DMA FIFO control registers rather than crossbar router registers; writing `0xc01` to them corrupts DMA FIFO synchronization and produces harsh buzzing noise on USB channels 11–20. A subsequent revision attempted writing to `0x40026468` and `0x4002646C` (used on MC-707 for assignable out); on MC-101 hardware this triggered an immediate power shutdown before the "Loading..." message (Boot Failure 7). Therefore, `0x400264xx` is strictly prohibited during `tramp_crossbar_init`.
    This streamed downmix to USB channels 1–2, tracks 1–7 cleanly to USB channels 3–16, and silence to USB channels 19–20 without power-down risks. All of these writes are gone from the build: the `CAVE-02` cave that held `tramp_crossbar_init` is freed, and per-track stems for USB channels 11–20 are produced by **Core 1** (`RPG69_C1A/sdram1.bin`), not Core 0 (README §4).
- **Fader LED Atomic State Lookup (Eliminating Mutex Contention & Pad Flicker)**:
  - In `UpdateFaderRgbLeds` (`0x60099200`), running from high-frequency timer interrupts, calls to `fw_get_param` failed RTOS mutex acquisition (`0x600384f4`) and returned `-1` (`0xFFFFFFFF`), which masked to `4` (`-1 & 4`) and forced fader LEDs to upper track colors on every tick.
  - Furthermore, using `0x60A8F6D4` collided with `UI_STATE` (`0x60A8F46C + 0x268`), which is overwritten during pad presses and event loops with internal flags having bit 2 set (`val & 4 != 0`), locking faders to bank 2 and causing pad hit flicker.
  - Dedicating `cur_track_var` at `0x602D27FC` in `CAVE-01` and reading it non-blocking atomically completely eliminates mutex contention, UI struct collisions, LED bank locking, and pad hit flicker.
- **Banked `UpdateFaderRgbLeds` loop (`FDR-BANK-LOOPBASE` / `FDR-BANK-TOP` / `FDR-BANK-BOT` / `FDR-LED-ID1` / `FDR-LED-ID2`)**:
  - Stock `UpdateFaderRgbLeds` uses one counter `r4` (`0..3`, bound `cmp r4, #4 / blt 0x60099212`) simultaneously as record-array index (`*[r5+0xc] + r4*0x100`, base `0x61991810`), record-state param id (`0x90 + r4`), engine track index (`uxth r1, r4`), selected/record gate operand (`cmp r3, r4` vs byte `*[r5+0x10] == 0x61800200`) and fader RGB LED id (`0x1c + r4`) — so the whole routine is pinned to bank A (tracks 1..4) and the selected fader cannot flash for tracks 5..8.
  - The patch keeps the stock loop body and remaps the counter: `r7` becomes the physical fader `0..3` (`movs r7, #0` at `0x6009920A`), the head (`bl tramp_fdr_top`) rebuilds `r4 = r7 + bank`, the bottom (`bl tramp_fdr_bot`) advances `r7` with stock `adds/cmp` semantics for the stock `blt`, and the two LED-id sites are un-banked to `0x1c + (r4 & 3)`. Bank A is stock by construction (`bank == 0` ⇒ `r4 == r7`).
  - Nothing downstream needs a bound change — verified 8-wide at byte level: record array 8 × `0x100` (`0x6002602E`, size `#0x800` at `0x60044638`/`0x600449CE`), pids `0x90..0x97` getter/setter arms (`0x60033960..0x60033998` / `0x60034198..0x600341C2`), record-state writer/clearer bounds 8 (`0x600659FA` / `0x60065F10`), engine query impls (`0x60031b2c`, `0x6033F2A8`, `0x6033EC24`, `0x6033F11C`).
  - Gate byte `0x61800205 == 1` (the gate's second condition, whose writer was not located statically — no literal pool references to `0x61800201..05`, no `strb [base,#5]` near any of the 53 loaders of `0x61800200`): resolved positively on hardware — the bank-B flash works with stock code untouched, so stock runtime sets this byte (README §3, Attempt 12).
- **Model Branding ("Roland MC-107")**:
  - `STR-NAME-02` (`0x6004F1D4`, 17 bytes): `Roland MC-101   \x00` -> `Roland MC-107   \x00`. This string is rendered by `FUN_6004F17C` on line 1 of the startup LCD display.
  - Note: Speculative string patches (`STR-USB-PROD`, `STR-NAME-01`, `STR-NAME-03`, and `STR-SPLASH-LCD`) were investigated and reverted to stock. Specifically, `STR-USB-PROD` (`0x600AA214`) was checked by `FUN_600AA148` during early boot USB MIDI initialization against the fixed USB product descriptor table; altering it caused `FUN_600AA148` to return `-1` and hang before "Now Loading...".

### 9.7 Complete Active Patch Summary (52 Sites)

Regenerated from `manifest/sites.json` (run `python3 tools/gen_manifest.py` to refresh).

| ID | VA | Size | Description |
|---|---|---|---|
| `CAVE-01` | `0x602D2600` | 512 B | SDRAM trampoline cave in zero-padded region (atomic track lookup, bank toggle, LED, drum-mute, knob helpers) |
| `MENU-MIDI-TBL` | `0x602D2800` | 644 B | Extended 23-entry SYSTEM(MIDI) ITEM_LIST_PRM table adding Track Ch5..8 (rel_pid `0x00F`..`0x012`) |
| `MENU-MIDI-DESC` | `0x6021A214` | 8 B | Repoint SYSTEM(MIDI) descriptor from (`0x60219F48`, 19) to (`0x602D2800`, 23) |
| `UI-03` | `0x60035CBC` | 8 B | `HandleButtonPress` SEL1..4: resolve track 0..7 with bank toggle (including [SHIFT]+[SEL1..4] EDIT mode toggle) and update r4 |
| `UI-DIRTY-FDR` | `0x60035E74` | 4 B | `HandleButtonPress` SEL1..4: set UI dirty bit 4 (`0x10`) to immediately trigger `UpdateFaderRgbLeds` on bank/track selection |
| `SEL-03` | `0x60065E04` | 6 B | `HandleEmptyTrackScreen` SEL1..4: query `IsTrackAllocated` for track candidate without mutating bank state |
| `LED-SEL-CHECK` | `0x600977C0` | 4 B | `UpdateSelButtonLeds`: illuminate/flash selected button for tracks 1..4; invert (other 3 illuminated/flashing, selected dark) for tracks 5..8 |
| `LED-SEL-BLINK` | `0x600977CC` | 4 B | `UpdateSelButtonLeds`: query blink state `0x90` + `CurTrack` (r6 = 0..7) |
| `FDR-BANK-LOOPBASE` | `0x6009920A` | 2 B | `UpdateFaderRgbLeds` entry: `movs r4, #0` -> `movs r7, #0` — `r7` becomes the physical loop base `0..3` (stock used `r7` only as LED mode `#3`, re-supplied by FDR-LED-ID2) |
| `FDR-BANK-TOP` | `0x60099212` | 6 B | `UpdateFaderRgbLeds` loop head -> `bl tramp_fdr_top`: rebuild `r4 = physical fader + bank` (bank = bit 2 of the selected-track byte `*[*r5+0x10] == 0x61800200`, lockless — never `fw_get_param` in this ISR) and return the banked record pointer, so record-mode/colour reads, pid `0x90+r4` queries, engine track-index queries (`uxth r1, r4`) and the selected/record gate follow the bank |
| `FDR-BANK-BOT` | `0x600992BC` | 4 B | `UpdateFaderRgbLeds` loop bottom -> `bl tramp_fdr_bot`: stock loop control on the physical counter (`adds r7, #1 / cmp r7, #4`), flags for the stock `blt 0x60099212` left at `0x600992C0`; must not touch banked `r4` (deriving the bank from `r4` wraps the counter and spins the ISR — README §1 BF-8) |
| `FDR-LED-ID1` | `0x600992B0` | 4 B | `UpdateFaderRgbLeds` steady-colour LED write -> `bl tramp_fdr_ledid1`: un-bank the fader RGB LED id to `0x1c + (r4 & 3)` (banked `0x1c + r4` = pad LED ids `0x20..0x23`) |
| `FDR-LED-ID2` | `0x60099356` | 6 B | `UpdateFaderRgbLeds` flash/red LED write -> `bl tramp_fdr_ledid2`: same unbanked LED id, plus LED mode `#3` (stock took it from `r7`, now the loop base) |
| `MUTE-LED-BANK` | `0x60097AE8` | 6 B | `UpdatePadLeds` drum-mute check: offset track index r4 by active bank (`CurTrack` & 4) |
| `SEL-01` | `0x60097AF4` | 8 B | `UpdatePadLeds` drum-mute loop bound: clamp physical button scan to 4 (SEL1..4, IDs 6..9) |
| `MUTE-PAD-BANK` | `0x600377F6` | 6 B | `HandlePadPress` drum-mute check: offset track index r6 by active bank (`CurTrack` & 4) |
| `FDR-ITCM-TBB` | `0x60337742` | 6 B | ITCM fader TBB table (exec `0x01024FA6`): route fader IDs 1..4 to unified banked handler at `0x01024FD2` |
| `FDR-ITCM-CODE` | `0x6033776E` | 128 B | ITCM unified bank-aware fader handler (`0x01024FD2`) and MULTI knob helper (`0x01025010`) |
| `KNOB-ITCM-MULTI` | `0x60337800` | 4 B | ITCM MULTI knob handler (exec `0x01025064`): jump to bank-aware track resolver |
| `KNOB-UI-MULTI1` | `0x60036A16` | 4 B | `HandleKnobEvent` MULTI popup (`0x60036A16`): offset knob track index by active bank (`CurTrack` & 4) before Single-mode merge target `0x60036A1A` |
| `KNOB-UI-MULTI2` | `0x60036B6A` | 4 B | `HandleKnobEvent` MULTI edit (`0x60036B6A`): offset knob track index r5 by active bank (`CurTrack` & 4) before Single-mode merge target `0x60036B6E` |
| `PRM-RECSRC-FMT` | `0x6006F088` | 18 B | `RecSource` `FormatValue`: map UI index 0..9 linearly to engine value 1..10 (PC, TRK1..8, MIXOUT) |
| `PRM-RECSRC-GET` | `0x6006F1F8` | 32 B | `RecSource` `GetValue`: map engine value 0..10 to UI index max(0, val - 1) |
| `PRM-RECSRC-SET` | `0x6006F258` | 16 B | `RecSource` `SetValue`: map UI index 0..9 to engine value idx + 1 |
| `PRM-RECSRC-MAX` | `0x6006F334` | 2 B | `RecSource` `GetMinMax`: increase max UI index from 5 to 9 (10 options: PC, TRK1..8, MIXOUT) |
| `PRM-SCATPOS-FMT` | `0x6007D0C4` | 18 B | Scatter Position `FormatValue`: map UI index 0..9 to engine value 1..10 (PC, TRK1..8, MIXOUT) |
| `PRM-SCATPOS-GET` | `0x6007D214` | 30 B | Scatter Position `GetValue`: map engine value 0..10 to UI index max(0, val - 1) |
| `PRM-SCATPOS-SET` | `0x6007D262` | 14 B | Scatter Position `SetValue`: map UI index 0..9 to engine value idx + 1 |
| `PRM-SCATPOS-MAX` | `0x6007D32C` | 2 B | Scatter Position `GetMinMax`: increase max UI index from 5 to 9 |
| `PRM-SCATDT1-FMT` | `0x6007E9F0` | 18 B | Scat DT1 Pos `FormatValue`: map UI index 0..10 to engine value (OFF=0, PC=2, TRK1..8=3..10, MIXOUT=11) |
| `PRM-SCATDT1-GET` | `0x6007EB3A` | 24 B | Scat DT1 Pos `GetValue`: map engine value 0..11 to UI index 0..10 |
| `PRM-SCATDT1-SET` | `0x6007EB86` | 14 B | Scat DT1 Pos `SetValue`: map UI index 0..10 to engine value (idx >= 1 ? idx + 1 : 0) |
| `PRM-SCATDT1-MAX` | `0x6007EC50` | 2 B | Scat DT1 Pos `GetMinMax`: increase max UI index from 6 to 10 (11 options: OFF, PC, TRK1..8, MIXOUT) |
| `PRM-TRKINS-FMT` | `0x60070558` | 18 B | Track Insert `FormatValue`: map UI index 0..10 to engine value (0=OFF, 7..9=PC IN, 10..16=TRACK1..7) |
| `PRM-TRKINS-GET` | `0x6007078E` | 24 B | Track Insert `GetValue`: map engine value 0..16 to UI index max(0, val - 6) |
| `PRM-TRKINS-SET` | `0x600708C6` | 14 B | Track Insert `SetValue`: map UI index 0..10 to engine value (idx >= 1 ? idx + 6 : 0) |
| `PRJ-LOAD-PRESERVE` | `0x6005B422` | 16 B | Project load: preserve tracks 5..8 clips/allocations (bypass stock wiping loop) |
| `PRJ-POST-LOAD` | `0x60046424` | 6 B | Project load completion exit: `b.w tramp_prj_load_init` (a **tail call** of the stock epilogue `add sp, sp, #0x28` + `pop.w {r4-r10, pc}`) inits tracks 5..8 to unity `255` via `fw_set_param` + `fw_set_dsp_param`; without it the upper bank starts at **zero volume** (README §2, Attempts 9–10) |
| `SEQ-TRK-CNT` | `0x60342EBA` | 2 B | Sequencer constructor: set active track count from 4 to 8 (movs r2, #8) |
| `MIDI-RX-TRK-CNT` | `0x603234B6` | 2 B | ITCM incoming MIDI RX track-channel loop (exec `0x01010D1A`): extend `Track Ch1..4` scan to `Track Ch1..8` (`cmp r4, #4` -> `cmp r4, #8`) |
| `MIDI-CH-ALLOFF` | `0x6003D674` | 20 B | `SYSTEM(MIDI)` Track Ch edit All-Sound-Off check: accept GPID `0xDB..0xE2` (`Track Ch1..8`) instead of `0xDB..0xDE` |
| `USB-DESC-CH` | `0x602CA730` | 1 B | USB High-Speed Vendor Audio Streaming IN Format Type I descriptor `bNrChannels`: 10 (`0x0A`) -> 20 (`0x14`) |
| `USB-DESC-PKT` | `0x602CA741` | 2 B | USB High-Speed Vendor Isochronous IN Endpoint (`0x8E`) `wMaxPacketSize`: 264 (`0x0108`) -> 524 (`0x020C`) |
| `USB-INIT-CH` | `0x600AADE6` | 2 B | `USB_OnBusResetOrConnect`: configure hardware USB Audio IN bridge (`0x40080900`) for 20 channels (movs r6, #`0x14`) in Vendor mode |
| `USB-INIT-FIFO3` | `0x600AADE8` | 2 B | `USB_OnBusResetOrConnect`: configure hardware USB Audio IN bridge FIFO parameter 3 = 6 (movs r5, #6) for 20 channels |
| `USB-INIT-BURST` | `0x600AADEE` | 2 B | `USB_OnBusResetOrConnect`: configure hardware USB Audio IN bridge burst size = 72 bytes (movs r1, #`0x48`) for 20 channels |
| `USB-IF1-BURST` | `0x600AB4AC` | 2 B | `USB_OnSetInterface`: configure hardware USB Audio IN bridge burst size = 72 bytes (movs r6, #`0x48`) in Vendor mode |
| `USB-IF2-CH` | `0x600AB51E` | 2 B | `USB_OnSetInterface`: configure hardware USB Audio IN bridge (`0x40080900`) for 20 channels (moveq r2, #`0x14`) when Interface 2 `AltSetting` 1 is selected in Vendor mode |
| `USB-IF2-FIFO3` | `0x600AB58C` | 2 B | `USB_OnSetInterface`: configure hardware USB Audio IN bridge FIFO parameter 3 = 6 (moveq r2, #6) when Interface 2 `AltSetting` 1 is selected in Vendor mode |
| `NARROW-REG-B0` | `0x6001AD98` | 8 B | Boot audio-port init: router slot `0x400266B0` (Track 5 USB IN) → DSP streaming bus `0x2C00` via `tramp_router_b0` (`0x602D27AA`); sole writer, audio start never rewrites it (§10.1/§10.4) |
| `NARROW-REG-B8` | `0x6001B032` | 8 B | Audio-start leaf head: router slot `0x400266B8` (Track 7 USB IN) → `0x2C00` via `tramp_router_b8` (`0x602D277A`), resume `0x6001B03A`; `0x6A48=1`/FIFO `0x803` writes stay stock |
| `NARROW-REG-LB` | `0x6001B04C` | 6 B | Audio-start leaf: clear loopback enables `0x424C4920/24/28` (word `0x40026248` bits 8/9/10) via `tramp_router_lb` (`0x602D2788`); stock enabled Track 6 loopback at audio start |
| `NARROW-REG-B4` | `0x6001B052` | 14 B | Audio-start leaf tail: router slot `0x400266B4` (Track 6 USB IN) → `0x2C00` via `tramp_router_b4tail` (`0x602D279A`, reproduces the leaf's `pop {r4,lr}; bx lr` tail-call); DAC slots untouched by construction |
| `STR-NAME-02` | `0x6004F1D4` | 17 B | LCD splash screen line 1: 'Roland MC-101   ' -> 'Roland MC-107   ' |

## 10. Core 0 Router / USB IN Bridge Static Map (2026-11-13, analysis + §10.4 NARROW-REG built/CTest-green, not yet flashed)

All findings below are byte-verified by literal-pool word dumps against both decrypted Core 0 images (`vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin`, `vendor/mc707_sys_v182/extracts/RPG68_C0A/App1_Main_decrypted.bin` — the 707 image was decrypted with `tools/decrypt_c0a.py`).

### 10.1 The Track 5–8 router slot writers (MC-101) — complete census

Pure pool-encoding scan (every 4-byte word equal to the slot address, then every literal-`ldr` window that lands on it) proves each Track 5–8 slot has exactly **one** writer in MC-101 Core 0:

| Slot | Track | Sole writer site | Value written | Context |
|---|---|---|---|---|
| `0x400266B0` | 5 | `0x6001AD9A` (pool word `0x6001AE44`) | `0x800` (loopback/test source) | Inside audio-port init `0x6001AC6C` (boot, called at `0x600A9DB2`) |
| `0x400266B4` | 6 | `0x6001B058` (pool word `0x6001B070`) | `0x800` via `lsls r1,r0,#0xb` tail | Tail-call of audio-start leaf `0x6001B030` |
| `0x400266B8` | 7 | `0x6001B034` (pool word `0x6001B060`) | `0` | Head of audio-start leaf `0x6001B030` (called at `0x60026696`) |
| `0x400266BC` | — | `0x6001B046` | `0x803` then `1` | **Streaming DMA FIFO register, not a router slot** — never touch |

Audio-start leaf `0x6001B030` (verified write set, all via writer helper `0x600220F0` = `str r1,[r0]; bx lr`): `0x66B8=0`, `0x6A48=1`, FIFO `0x66BC=0x803`, **loopback bitband `0x424C4924 = 1`** (word `0x40026248` bit 9), tail `0x66B4=0x800`. The 707's runtime dispatcher does the exact inverse (see 10.2). Boot init `0x6001AC6C` (`0x6001AD98..0x6001AD9F` window) also writes `0x66C0=0x800` (Ext In L), FIFO `0x6688=0x800`, `0x667C/0x6680=0x800`, bitband words `0x40026200/0x40026208/0x40026210/0x40026218`, enables `0x424C451C..0x424C452C` and loopback enables `0x424C4920/30/34/38/3C`, and tail-writes a config block at `0x2100B510` (`0x800`, `0x420`, `0x421`). (Attempt 6's write list is confirmed modulo the site address: `0x66B0` is written at `0x6001AD9A`, not `0x6001AD4A`.)

Leaf `0x6001B074` (called at `0x600A9DB6`) writes **only** `0x6558=0`, `0x6A30=6`, `0x655C=0x806`, bitband `0x424C4360=0`, `0x6560=0x800`, bitband `0x424C4364=0`, `0x6564=0x800` — it does *not* touch `0x66B0/0x66B4` (earlier notes were wrong; corrected by pool-word dump).

### 10.2 MC-707 runtime routing dispatcher — and MC-101's lack of one

MC-707 Core 0 `0x60075534` is an event dispatcher (`r1` = event):
- Event `0x3A` (audio start) at `0x60075704..`: writes the DSP streaming bus value **`0x2C00`** via writer helper `0x60022E60` to slots `0x40026668/0x6C/0x78/0x84/0xB0/0xB4/0xB8` (pool `0x60075834..0x6007584C`), then clears loopback bitbands `0x424C4928/0x24/0x20` (word `0x40026248` bits 10/9/8) and `0x424C4524/0x18/0x0C` (word `0x40026228` bits 9/6/3).
- Event `0xB`: teardown, writes `0` to the same slots.
- `mov.w r1,#0x2C00` (bytes `4f f4 30 51`) occurs **7 times in MC-707, all inside this dispatcher, and 0 times anywhere in MC-101 Core 0**. The MC-101 has no twin dispatcher (the `cmp r1,#0x2e/#0x3a` byte hits in MC-101 are u16 data tables at `0x600CD0xx` and unrelated UI dispatchers).

Boot deltas (707 `0x6001B010` vs MC-101 `0x6001ABB0`): 707 additionally writes `0x66C4/0x6D30/0x6D34=0`, `0x66B8/0x66B4/0x66B0=0xC01`, bitband `0x424C4560` (word `0x40026228` bit 24); 101 writes only `0x6660=0x800`, `0x6668=0xC02`, `0x666C/0x678/0x684=0xC01`, bitband `0x424C4500` (bit 0). 707 leaf `0x6001B0C0`: `0x6468=0xC01, 0x646C=0xC01`; MC-101 leaf `0x6001AE50`: `0x6468: 0→0x800`, `0x646C=1`.

### 10.3 USB IN bridge (`0x40080000`) mask control census (MC-101; 707 twins)

| MC-101 fn | 707 twin | Semantics (decoded) |
|---|---|---|
| `0x60022CB0` | `0x600239F8` | Clears bit (ch−1) of mask words `bridge+0x340` **and** `bridge+0x344`; writes `0` to doorbell byte `bridge+0x4771` |
| `0x60022CE8` | `0x60023A30` | Sets bit (ch−1) of `bridge+0x340`; doorbell byte `bridge+0x4771 = 1` |
| `0x600228F8` | — | Clears bit (ch−1) of `bridge+0x344` only |
| `0x6002355C` | `0x60024250` | Stream-start wrapper: decodes stream-format word `ip=((r0>>3)&0x20)|((r0>>1)&0x1FC)`, writes `ip&0xa4 → bridge+0x340`; enables + clears-pending NVIC IRQs `0x6B..0x73` (`ISER[3]@0xE000E10C`, `ICPR[3]@0xE000E28C`, bound `cmp r1,#0xb` @`0x60023544`); `blx [ctx+0x30]` callback |
| `0x600236A4` | `0x600243D2` | Stream-start wrapper variant: writes caller `r2` (decode `((r0>>1)&0x1FC)|((r0>>3)&0x200)` then `&0xa4` in the 707) → `bridge+0x340`; `blx [ctx+0x30]` |
| `0x60022434` `0x600224B0` `0x60022558` | — | Registration trio: load RAM function-pointer slots `0x603A4C98`/`0x603A4E98`, call `0x60023A1C`, tail `orr #8` on `bridge+0x340` |

**Mask decode, `&0xa4` write masks, and the IRQ bound `cmp r1,#0xb` are byte-identical between MC-101 and MC-707** — the bridge stream-start path is *not* the model delta, and the earlier "widen mask bound for 20 channels" candidate is dead. All 8 accessor functions have zero static `bl` callers (reached via RAM function-pointer registration; the invoker is a live-probe target). Core 1 (both models) contains zero code-literal users of `0x40080000..0x40080A00` — Core 0 owns the bridge. Core 1 writes ESC2 router regs `0x400267C0..0x400267E8` (literal pool `0x610010C8..`): the engine programs the router, Core 0 owns the bridge.

### 10.4 NARROW-REG — implemented 2026-11-13 (built, CTest-green; next hardware flash reserved for it)

Goal: at audio start, route Tracks 5–7 (slots `0x66B0/0x66B4/0x66B8`) to the DSP streaming bus `0x2C00` and disable the loopback bit, exactly mirroring the MC-707 dispatcher's end-state, while leaving the DAC-routed slots `0x6660/0x6668/0x666C/0x6678/0x6684` (REG-1's kill mode) and the FIFO regs `0x66BC/0x6688` untouched. Sites, using the established micro-trampoline pattern into the verified zero-padding cave (`0x602D2600..0x602D40D0`):

1. **`NARROW-REG-B8` — `0x6001B032`** (8 B: `movs r1,#0` + `ldr r0→0x66B8` + `bl 0x600220F0`) → single `b.w tramp_router_b8`; the trampoline ends with `b.w 0x6001B03A`, the site's original fall-through.
2. **`NARROW-REG-LB` — `0x6001B04C`** (6 B: `ldr r1→0x424C4924` + `movs r0,#1` + `str r0,[r1]`) → `b.w tramp_router_lb`. The planned **2-byte in-place `movs r0,#0`** was rejected after implementation: it leaves the Track 5 (`0x424C4920`) and Track 7 (`0x424C4928`) loopback enables set, which is exactly the state that overrides router content with the loopback source. The trampoline clears all three bitbands `0x424C4920/24/28` (word `0x40026248` bits 8/9/10 — the full set the 707 dispatcher clears) and resumes at `0x6001B052`.
3. **`NARROW-REG-B4` — `0x6001B052`** (14 B: `lsls` + `pop.w` + `ldr r0→0x66B4` + `b.w 0x600220F0` tail call) → `b.w tramp_router_b4tail` (cave: `mov.w r1,#0x2C00; ldr r0,[pc]; bl 0x600220F0; pop {r4,lr}; bx lr` — pops the leaf's return address, preserving the tail-call contract) + nop fill.
4. **`NARROW-REG-B0` — `0x6001AD98`** (8 B: `lsls r1,r0,#0xb` + `ldr r0→0x66B0` + `bl 0x600220F0`) → `b.w tramp_router_b0` (writes `0x2C00→0x66B0`; `r0/r1` are dead across the site — both reloaded at `0x6001ADA0`, and `r4` is reloaded from a literal at `0x6001ADAA`).

Cave assembly note (cost 2 build cycles, worth recording): the register addresses must be defined with **`.set` inside the cave body, not through the `ext_syms` `.thumb_set` path**. `assemble_thumb`'s external-symbol prologue emits `.type <name>, %function` + `.thumb_set`, and a symbol typed `%function` gets **bit 0 set** in an `ldr rX, =sym` literal pool — `0x400266B8` silently becomes `0x400266B9`, i.e. every router write lands 1 byte off and the MMIO store is unaligned. Capstone disassembly of the built cave looked correct in the instruction stream; only dumping the pool words caught it.

Implemented 2026-11-13 in `tools/gen_manifest.py` (site count 48 → 52; cave `378/512` → `464/512` bytes) and enforced by `tools/verify_patched_image.py`, which decodes each site's `b.w`, then the trampoline's `ldr` pool word, `bl` target and resume, asserting the written slot is exactly `0x66B0/66B4/66B8`, the value is `0x2C00`, the writer is `0x600220F0`, and that the pool words reference **none** of the DAC slots `0x6660/6668/666C/6678/6684`, the FIFOs `0x66BC/0x6688`, or the power-off bitband `0x424C4510`. The earlier "audio port init `0x6001AC6C` must be stock" anchor is replaced by stock checks on `0x6001AC6C..0x6001AD98` and `0x6001ADA0..0x6001ADC8` (the window is untouched except at the patched site), plus stock leaf entry `push {r4,lr}` at `0x6001B030` and stock `0x6A48=1`/FIFO `0x803` block at `0x6001B03A..0x6001B04B`.

Risk control: no new register address is ever written and the only value written is the 707's stock streaming-bus value. Track 8 has no router slot at all (its content path is Core 1-side; see `docs/mc101_core1_structural_map.md`). Status: **built, CTest-green, NOT flashed** — the next hardware flash is reserved for this change, and the §10.5 probes should be read before and after it.

### 10.5 Live probe plan (zero flash, run when unit is attached)

`tools/probe_router_state.py` automates the whole target set below in one read-only pass (13 × 64-byte Vel 26 DMA windows, semantic decode of mask words/doorbell/loopback bits/router slots, JSON snapshot per run) — run it **before** and **after** the NARROW-REG flash and diff the JSONs. The primitives it drives:

`tools/sysex_dump_client.py` already implements every probe needed (Core 1 `src/sysex_hook.s` triggers, hardware-proven): Note 127 Vel 15 + 8 nibbles (Vel 32..47) = address latch; Vel 14 = 256-byte chunk; Vel 26 = `cmd_dma_probe_chunk` (arbitrary VA incl. MMIO — Core 1 MMIO bus access to `0x40001000` was verified long ago; pure read). Targets, ranked:

1. `0x40080340` / `0x40080344` (bridge per-channel mask words) + doorbell byte `0x40084771` — do the mask bits 10–19 ever get set at runtime, and by which registered callback?
2. Router slots `0x40026660..0x400266C4` (excluding FIFOs `0x6688`/`0x66BC`) and bitband words `0x40026228`/`0x40026248`, `0x40026468`/`0x4002646C`.
3. RAM function-pointer slots `0x603A4C98`/`0x603A4E98` and the dumper context block around them (invoker registration of the mask accessors).


### 10.6 Core 1 side: boot router-init census (2026-11-14, my own byte-verified pass; replaces the retracted agent report)

Method: pool-encoding scan over `sdram1.bin` (VA `0x61000000`) — enumerate every 16-bit `ldr rX,[pc,#imm8*4]` encoding (imm8 = full `bytes[0]`, slot = `Align(addr+4,4)+imm8*4`) and resolve the pool word. All facts below are my own reads; the LLM-agent report retracted in README §4 shares none of them.

1. **Core 1 owns a boot router-init function** (code region `0x61000C80..0x61001450`, spans the data islands at `0x61000D60..0x61000E7F` and `0x61001030..0x610011FF`). Every write goes through a veneer `bl 0x6107D492` = `movw ip,#0x2973; movt ip,#0x112; bx ip` → real writer at idm1 `0x01122973` (Core 1's twin of Core 0's `str r1,[r0]; bx lr` helper).
2. **USB IN mux window `0x40026600..0x40026654` (20 slots)**: written `0x801` by this boot function — site A `0x61000ED4..0x61000F92`, site B `0x61001230..0x610012F0` (same block, data islands split; the "43 literal refs" scan counts both windows). Surrounding slots `0x65B0..0x65EC`, `0x6794` get `0xC01` (physical pins). **MC-707 twin is byte-identical at the same VAs** — the static router config does not differ between models; whatever gives the 707 more streams lives elsewhere (runtime, Core 0 bridge side, or descriptor/mask layer — the §10.3 mask-bound result already showed the 20-ch mask is native).
3. **Second slot table `0x67C0..0x67F0` + `0x6704/0x6708`** written from `0x61000CCC..0x61000D58`: `0x801` everywhere except `0x67D0/67D4/67D8 = 0x802` and `0x67DC = 0x806` (indexed sources + bit 11 enable, consistent with §10 descriptor value semantics). Also 101/707 twins.
4. **Negative results (all self-derived)**: the 11 literal `0x2C00` words in sdram1 (101: `0x610A276C..0x610AB730`, 707 at `+0x50`) sit inside DSP parameter tables and have **zero** 16-bit-`ldr` code references — the DSP streaming bus value is not materialized as an immediate anywhere in Core 1. Bridge-region (`0x40080000..0x40080A00`) literal words: 33 in both, none referenced by the scan (data coincidences, confirming the prior census). idm1: no `0x2C00` literal, no ASCII `USB`/`stems`, no PL080-descriptor `ctl` words.
5. **Implication for ch 11–20 content**: Core 1 sets the 20 USB IN mux slots to source index `1` (`0x801`) once at boot; no static writer changes them at audio start in either model. NARROW-REG's `0x2C00` (Core 0 side, slots `0x66B0/66B4/0x66B8`) stays the only content-routing lever we control. The live probe (§10.5) will show the post-boot runtime state of `0x6600..0x6654` — add these 20 slots to the probe list on the next iteration if the flash result is ambiguous.

### 10.7 Core 1 T2 DMA transfer list: the real stem plumbing (2026-11-14, agent re-verification pass, every claim below byte-verified by me)

> **RETRACTED 2026-11-15 — see §10.10.** The "T2 = stem transfer list" *interpretation* is dead: the table is a **console/diagnostic DMA-descriptor dump**, and every indirect consumer of it is a printf/name-normaliser/indexed-name printer, not an audio walker. The geometry recorded below is also wrong in these specifics: `0x6109B148` is **not a base** — it is row 100's `+8` (aperture) field of a 129-row 16-B `{ctl,name,aperture,len}` table based at `0x6109AB00`; "28 rows"/"40 rows" and the "terminator @`0x6109B308`" follow from that misaligned reading; the real terminator is row 129 @`0x6109B310`; "12 MC-707-only tuples" is an artefact of the same offset; the table is 129/129 identical in `(ctl,aperture,len)` between models (§10.10). Kept verbatim as the historical record.

The first agent report was fabricated (retracted, README §4). Its re-run produced a report whose tables I re-derived independently — accepted facts below; the agent's *interpretive* labels are marked as such. Full report `/tmp/opencode/REPORT_mc101_core1_stems.md`, supporting scans `/tmp/opencode/core1/` (`t2decode.txt`, `banddiff.txt`, `relocs.txt`).

1. **T2 = sentinel-terminated 16-byte-row transfer list in sdram1** (VERIFIED): MC-101 base `0x6109B148`, 28 rows + terminator `0x6109B308`; MC-707 base `0x6109B0D8`, 40 rows + terminator `0x6109B358`. Row layout (VERIFIED as words; semantics of `+8 ctl` = agent's, plausible given trigger triplets `2/3/4` recur): `+0` aperture in `0x41xxxxxx` window space, `+4` len, `+8` `ctl` (`ctl&0xFF` = stream channel 7/8/9, `ctl>>16` = trigger id), `+12` RAM staging pointer (`0x612Cxxxx`) — **CORRECTED by §10.9: `+12` is a name-string pointer into the arena; the terminator is a hybrid row (real aperture/len/ctl words + inline `"---\0"` name)**. The device's own console dump format string `%3d %-16s %6X %6X %04X ` VERIFIED at MC-101 `0x6100C124`; MC-707 string exists at `0x6100C101` (agent said `0x6100C0FC` — off by 5, rejected in favor of my read).
2. **Set-diff on `(aperture, len, ctl)`: 12 MC-707-only tuples, 0 MC-101-only** (VERIFIED, exact tuple list in agent report and reproducible via `core1/t2decode.py`). MC-101 has **no ch6 rows at all**; 707 ch6 = `0x41860000/0x10000` trig4 + `0x418A0000/0x4000` trig6 (agent: OUT-side mirror of the 101's ch7 pair — interpretation). 707 ch7 = 12 rows **containing the 101's entire 2-row ch7** (VERIFIED: `0x41960000/0x10000` trig4 + `0x419A0000/0x4000` trig6 present in both — this is the USB Audio IN staging block, the lever for ch 11–20 content). Extra 707 ch7 rows: `0x41900000/0x41910000` six 8 KB slices trig `2/3/4`, `0x41940000/0x3000` trig5, `0x41128000/41129000/4112A000` 3×4 KB trig `102/3/4`. **ch8 (14 rows) and ch9 (12 rows + terminator) are byte-identical between models** (VERIFIED).
3. **Model difference is table DATA, not code**: no count/size constant — walk terminates at the `----` sentinel. Band `0x61000000..0x6100D000` diffs are pointer relocations (`+0x50`/`+0x200`), string-pool shifts, and `bl`-offset shifts only (VERIFIED: e.g. the boot router-init function of §10.6 has identical writes at identical VAs, single-byte `bl` offset deltas like `51fb`→`3ffb` @`0x61000CA6`). "Core 1 code is model-invariant, 8 stems needs only table rows" = agent's inference; consistent with everything verified, and Core 1 (`RPG69_C1A`) is the SD-flashable unencrypted core (zero brick risk).
4. **In-place append is impossible on MC-101** (agent claim, consistent with the `+0x70` base shift in 707): `0x6109B380..0x6109C160` behind the terminator is a live pointer table; the 707 build shifted T2's base down and everything downstream by `+0x50`/`+0x200`. Relocation footprint per agent: 3 pointer words `+0x50`, 142→148 RAM-arena words (table `0x610330F8..0x61033A20`), 4 code-band words (`0x61005858`, `0x61006F28`, `0x61008EE8`, `0x6100AB6C`) — **SUPERSEDED by §10.9**: the real footprint is 3–4 static pool words; the RAM-arena/code-band numbers were pass-1 fabrications-adjacent and retracted by the agent itself. A 2-row in-place append at `0x6109B31C` needs ZERO relocations (§10.9).
5. **Open questions**: T2 walk bound proven sentinel-side? (agent probe: idm1 thunk `0x6107DA14` → `0x01123ADD`); staging → DSP consumption geometry at `0x40056000 + idx*0x400` (8 KB slice = 256 fr × 8 ch × 4 B or 512 fr × 4 ch). Both zero-flash-static-answerable. — **CLOSED by §10.9** (2026-11-14 pass-2, byte-verified by me).

### 10.8 RETRACTED: `REC-LED-8CAP` — the "record LED loop cap" design (2026-11-14, killed by byte check before any flash)

**Design (retracted):** patch `0x60097808` `042c`→`082c` (`cmp r4, #4`→`#8`) in the function @`0x600977AC`, premised on that loop being a per-track record-LED scan whose iterations `r4 = 0..3` drive LED ids 10..13 for tracks 5..8, giving bank-B record-standby LEDs for free.

**Why it is wrong (VERIFIED, full disassembly of `0x600977AC..0x6009780A`):** every LED-driver call in the loop passes **`id = r4 + 6`** (`adds r0, r4, #6` @`0x600977DE/EC/FA`) — the loop scans LED ids **6..9 = the SEL1..4 button LEDs** (the same ids the hardware-verified `SEL-01` site clamps to 4), with the selected-track compare `cmp r4, r6` (`r6` = current-track param via `0x6009CB2C` type 3), the REC-standby scene compare `0x36` via `0x6001CC44` (blink mode 3), and the per-track blink query pid `0x90 + r4` (`0x600331E0`). This is `UpdateSelButtonLeds` — it already hosts the hardware-verified `LED-SEL-CHECK`/`LED-SEL-BLINK` sites. The MC-101 has **no LEDs for tracks 5..8**; the per-track record indication on this panel *is* the 16-segment LED strip, which `FDR-BANK-TOP/BOT/LED-ID1/ID2` already drives bank-aware (hardware verified). Extending this loop to `r4 = 4..7` would drive ids 10..13 → strip table entries @`0x601D0554` (strip positions 10..13, count 1) — **LED-strip segments** — in SEL-button steady/blink styles, colliding with fader-strip rendering of tracks 3..4 in bank A. Regression risk against a hardware-verified feature for zero hardware gain: rejected.

**Durable facts kept from this investigation (all VERIFIED):**
1. `UpdateSelButtonLeds` @`0x600977AC` is live: exactly one caller, `bl` @`0x60097916` inside the object flag-flusher `0x60097902` (dirty bit 0 of the u16 at `[r4]`).
2. Xref-scanner T4 decode fix (load-bearing tooling lesson): `BL` T4 requires `I1 = 1^(J1^S)`, `I2 = 1^(J2^S)` (J1=J2=1); the B.W formula is `I1 = J1^S`, `I2 = J2^S`. The first scanner used the B.W formula for BL and decoded every long backward call wrong — its "no callers" outputs are invalid. Self-test the scanner against a known call (e.g. `bl 0x6001CC44` @`0x600977C4`) before trusting any xref claim.
3. LED driver chain: `0x6001E6B8` gates ids `< 0x30`, dedups against a state array, forwards to `0x6001E704`, which maps ids through the strip table @`0x601D0554` (8-B entries: key/strip pos, type, segment count, repeat; key==pos identity for 0..23; id 2 has **count 0** = no physical strip segment, so ids are not all strip segments).
4. No MC-707 twin for `UpdateSelButtonLeds`: the head-pattern match @`0x60069328` is false (body diverges at +`0x0A`, ends in ASCII strings); the loop-tail signature `a01d 0121 00b2 6a68` has zero hits in the 707 image. The 707 UI diverged — MC-101's own code is the only reference for SEL LEDs.

### 10.9 T2 pass-2 (Q1–Q3 closed): verification verdicts + the append recipe (2026-11-14; agent pass-2, every accepted claim byte-verified by me)

> **RETRACTED 2026-11-15 — see §10.10.** The append recipe below is invalid and must not be executed. The rows are 16 B, not 20 (the 20-B `ldm.w`/`stm.w` is a printer scratch-buffer prefetch); there is no second terminator at `0x6109B33C` (that VA starts the **live parameter-name-pointer array**; the second `"---"` is `0x002D2D2D` at `0x6109B328`, the aperture field of a phantom row 130); the span `0x6109B31C..0x6109B338` is **seven zero words plus that one `0x002D2D2D`**, not 32 zero bytes; and `0x6100D004..0x6100D00C` is **not** a `{end,end,start}` pair table (real words `F0700B10, EE08FD57, E0810A10, 6109B31C, 6109E270, '[ASC'`). No descriptor row may be patched for routing at all — the table is diagnostic (§10.10).

Agent pass-2 report appended to `/tmp/opencode/REPORT_mc101_core1_stems.md` (scripts `/tmp/opencode/core1/v2_*.py`). My byte-verification: all design-driving claims reproduced from raw images; five discrepancies corrected below.

**Q1 — walk mechanics (VERIFIED):** T2 is referenced **only via static pool words** — exhaustive 16/32-bit ldr-literal reverse-lookup + `movw/movt` pair scan finds **0 instruction references** and **0 other data words** in `0x6109B148..0x6109B340` in sdram1/idm1 (both models). MC-101 words: `0x6100C120 = 0x6109B2F4` (sentinel−20, read once @`0x6100BD90`), `0x6100C464 = 0x6109B308` (sentinel, read once @`0x6100C244`), **and a third the agent's summary missed: `0x6100D00C = 0x6109B31C`** (sentinel+20, read once @`0x6100CC12`); MC-707 mirror `0x6100C0FC/0x6100C440/0x6100CFE8`. `0x6100D004..0x6100D00C` = `{list end-ptr 0x6109B308, end-ptr 0x6109B328, start-ptr 0x6109B31C}` + inline `"QSPI\0"` — a [begin,end) pair table for a **second, 1-record list** starting at `0x6109B31C`. Each walker site copies rows with `ldm.w r0,{r0,r1,r2,r3,ip}`+`stm.w` (**20-byte records**, not 16 — pass-1 record-structure reading retracted by the agent) and bounds on the RAM control block: `ldr r0,[r4,#0x10]; cmp r0,r5` @`0x6100BD9E` (VERIFIED bytes `2069a842 9cbf`). `movs r4,#0x1c` (`1c24`) sits at `0x6100BC16` (101) **and** `0x6100BCC6` (707) → 28 is not the row count; the walk is sentinel-driven, consistent with 707 = 40 rows. The §8 idm1 lead is dead: veneer `0x6107DA14` = `movw ip,#0x3ADD; movt ip,#0x112; bx ip` → `0x01123ADD` lands in an instruction stream (agent quoted its bytes `80 ed 01 0a` one byte low — those are at `0x01123ADC`, ARM-aligned; the point stands: not T2). idm1's record walker uses pool `0x01123D14 = 0x200835A4` (RAM control block); pass-1's `0x01103D14` was a transcription bug (VERIFIED code bytes `20469847`).

**Q2 — staging→DSP geometry (VERIFIED):** slot consumer anchor word `0x40056000` @sdram `0x6101B0AC` (101) / `0x6101B08C` (707 — the "+0x20 pointer reloc" pattern) and idm1 `0x01101054`; index chain `ubfx r4,r0,#2,#8` (`c0f38704`) + `add.w r5,r0,r4,lsl #10` (`00eb8425`) at exactly 2 VAs (`0x6101AE6E/74`, `0x6101AF0A/10`) = **slot = base + idx×0x400, 256 slots**; no 0x800/0x1000 stride variant (agent census). Channel census VERIFIED: MC-101 `{7:2, 8:14, 9:13}` (incl. sentinel), MC-707 `{6:2, 7:12, 8:14, 9:13}`; channel value 4 absent; all 6 len-`0x2000` rows in MC-101 are ch8 (707: ch7+8) → **8 KB = 8 slots = 256 frames × 8 ch**, the 512×4 reading excluded. USB IN rows: `0x41960000/0x10000` (64 KB = 8 slots×8 KB = 256 fr×8 ch) + `0x419A0000/0x4000` (16 KB = 256 fr×16 ch), both ch7, present in both models. f32 sample width = agent's instruction-mix count (5297 s vs 946 d), plausible, not independently re-derived; non-design-driving.

**Q3 — patch feasibility (VERIFIED, cheaper than pass-1):** `+12` = **name-string pointer**: all 28 MC-101 rows decode to ASCII names (`' (SD31)'`, `' (RAW)'`, `' (IEEE)'`, `'MXM4M(->DSP4)'` …); the 12 MC-707-only rows' names **already exist** in the MC-101 arena (`0x612C9108/0x612C94A8/0x612C9388/0x612C7058/0x612C7060` VERIFIED) ⇒ new row = 16 B (20 B copied), **0 new name bytes**. The 12 707-only apertures lie inside 101's min–max span but **outside every 101 row window `[ap, ap+len)`** (VERIFIED per-aperture) — they are DSP-side windows the 101 firmware's DSP side must create; runtime probe required. Space census (VERIFIED): arena `0x612C0000..0x612E0000` 90.5% populated (agent said 97% — minor), 4431 zero-runs, **max 65 B**, none ≥ 0x80 → "grow the arena" is dead; whole-image max zero run **388 B @`0x61150B04`**, zero runs ≥ 1 KB = **0** → no 16 KB staging slots exist as static space in the image.

**The append recipe (my synthesis from the verified structure):**
1. **2 rows, zero relocation:** the sentinel row is hybrid (real `ap=0x4115A000 len=0x200 ctl=0x40009` + inline name `"---\0"`), and a **second identical terminator sits at `0x6109B33C`** (VERIFIED bytes `2d2d2d00`), with `0x6109B31C..0x6109B33B` = 32 zero bytes between. Writing 2 new rows at `0x6109B31C` and `0x6109B328` extends the list and lands exactly on the existing second terminator: 32 B, in place, **no pool word moves** (the `0x6100D00C → 0x6109B31C` pointer keeps pointing at the new first-extra row — and the list pair table then describes the appended tail; its consumer @`0x6100CC12` must be checked before flashing).
2. **12 rows (707 set), relocated table:** a 12-row append at `0x6109B31C` (192 B + terminator → `0x6109B31C..0x6109B3CB`) overruns the second terminator (`0x6109B33C`) and **overwrites the live pointer array starting at `0x6109B33E`** (VERIFIED: pointer words to `0x612Dxxxx`) ⇒ in-place 12-row append is NOT possible. Relocate: lay the 41-row table (28 + 12 + terminator, 656 B) in the sdram1 **tail gap** (234,512 B free in the container; append to `sdram1.bin` → new table VA ≈ `0x6139xxxx`) and update the 4 pool words `0x6100C120/0x6100C464/0x6100D008/0x6100D00C` — footprint **4 data words, 0 instructions** (VERIFIED: no instruction forms any T2 address).
3. Staging: rows carry no staging-RAM pointer at all (only name strings), so new rows need only DSP-side windows to exist at runtime — the open hardware/probe question, not an image-space question.

**Agent pass-2 discrepancies recorded:** (a) "only 2 data words per model / move = 2 data words" → **3** (missed `0x6100D00C`; its retraction of `0x6100D00C = d0 18 08 20` is itself wrong — real word `0x6109B31C`); (b) "free space inert, 0 targeting pointers" → 1 targeting pointer (`0x6100D00C`); (c) "T2 entries 16 B" → walk copies **20-B records** (terminator = 5th word inline; agent self-retracted); (d) veneer landing bytes quoted 1 byte low; (e) arena occupancy 97% → 90.5%.

### 10.10 RETRACTED: T2 as stem plumbing — the descriptor table is a diagnostic dump (2026-11-15; all numbers below re-derived by me from raw images this session)

**Verdict.** The §10.7/§10.9 model — "a sentinel-terminated transfer list at `0x6109B148`/`0x6109B0D8` is the USB-stem plumbing, so a table-row append gives 8 stems" — is **wrong in both halves**. The table is a **console/diagnostic dump of DMA descriptors**; there is no audio walker among its consumers; and the geometry the model was built from came from reading a misaligned window inside a larger table. **No row of this table may be patched for routing.** The §10.7 "28 rows / 12 707-only tuples" and §10.9 append recipe are dead ends and must not be executed.

#### 10.10.1 Corrected geometry (byte-verified)

- **129 data rows + 1 terminator**, stride **16 B**, layout **`{u32 ctl, u32 name_ptr_or_inline, u32 aperture, u32 len}`**. (Not 20 B; not `{ap,len,ctl,name}`.)
- MC-101 base `0x6109AB00`, rows `k=0..128`, terminator `k=129` @`0x6109B310` = `{0x00040009, 0x002D2D2D, 0, 0}`.
- MC-707 base `0x6109AB50`, rows `k=0..128`, terminator `k=129` @`0x6109B360` = identical bytes `{0x00040009, 0x002D2D2D, 0, 0}`.
- **129/129 rows identical in `(ctl, aperture, len)`** between the two products. **0/129** name *pointers* are equal (the whole arena is shifted by the 707 build), but **129/129** pointed-to name *strings* are byte-identical. So this table is **model-invariant data**; it carries no 101-vs-707 stem-count difference, which is fatal to the "707 has 12 extra stem rows" premise.

#### 10.10.2 Why pass-1 got "28 rows at `0x6109B148`, terminator `0x6109B308`"

`0x6109B148 = 0x6109AB00 + 100*16 + 8` → **row 100's `+8` = its `aperture` field**, not a list base. Reading 16-B windows from `+8` yields pseudo-rows `{ap_k, len_k, ctl_{k+1}, name_{k+1}}`, whose `ap`/`len` are real but whose `ctl`/`name` belong to the *next* row. From row 100 that is `129-101 = 28` pseudo-rows, ending at `0x6109B308` = **row 128's aperture field** (`0x4115A000`), which the model then called a "terminator". The first pseudo-row is therefore `{ap=0x41960000, len=0x10000, ctl=0x00040007, name=0x612C8FCC}` — the "ch7 USB-IN staging pair" §10.7 built its thesis on is just descriptor rows 100–101 (names `SIO#5`, `""`). The "28 vs 40" split and the "12 MC-707-only tuples" are artefacts of the same `+8` offset. Likewise `0x6109B148` "28-row base" in §10.7 item 1 is this arithmetic.

#### 10.10.3 Tail map, MC-101 (all words byte-read this session)

```
0x6109B2E0  k=126  { 00000009, 612C9254, 4113C300, 00000080 }   "MXM2M(->DSP2)"
0x6109B2F0  k=127  { 00000009, 612C90D4, 4113C380, 00000080 }   "MXS1 "
0x6109B300  k=128  { 00000009, 612C95DC, 4115A000, 00000200 }   "MXM0M"
0x6109B310  k=129  { 00040009, 002D2D2D, 00000000, 00000000 }   terminator ("---" inline)
0x6109B320         { 00000000, 00000000, 002D2D2D, 00000000 }   phantom row 130 ("---" in the aperture field)
0x6109B33C         live parameter-name-pointer array: 612D0B24, 612D4308 "…ve Shift", 612C85B0 "RTC_DCY", 612D27EC "Tweeter Level", …
```

The span `0x6109B31C..0x6109B338` is **seven zero words plus one `0x002D2D2D`** (the phantom row 130's aperture at `0x6109B328`) — *not* "8 zero words" and *not* "32 zero bytes". `0x6109B33C` is not a terminator: it is the first live name pointer of the MID-string parameter-name array. Any append starting at `0x6109B31C` would collide with `0x6109B33C` at the 9th word.

#### 10.10.4 Consumer census — all four indirect consumers are printers (re-disassembled, byte-verified)

| site | pool word | points at | what it does |
|---|---|---|---|
| `0x6100BD90` | `0x6100C120 = 0x6109B2F4` | row 127's **name** field | `ldm.w r0,{r0,r1,r2,r3,ip}` (5-word `0x6109B2F4..0x6109B307`) then bound `ldr r0,[r4,#0x10]; cmp r0,r5`; formats a `%3d %-16s %6X %6X %04X ` row dump |
| `0x6100C244` | `0x6100C464 = 0x6109B308` | row 128's **aperture** field | `ldm.w` of `0x6109B308..0x6109B31B` then `bl 0x6107D4A6` (row printer); string `"QSPI Test Find '%s'\n"` @`0x6100C468` |
| `0x6100CC12` | `0x6100D00C = 0x6109B31C` | phantom-row span | `ldr.w r1,[r1,r2,lsl #2]; b.w 0x6107D654` — **indexed name printer** |
| `0x6100BE8E` | (inline use) | name field bytes | ASCII normaliser: clamp to `_`, pad to 16 |

None of these is on an audio path; none walks the table as a transfer list. The format string `%3d %-16s %6X %6X %04X ` @`0x6100C124` and the `"QSPI Test Find"` string are the diagnostic's own labels.

The **20-B `ldm.w`/`stm.w`** that §10.9 read as the record stride is a **printer scratch-buffer prefetch** (5 words into a stack buffer). The actual table walk copies **16 B**: `cmp r0,#0x10` @`0x6100BDC6`, `movs r2,#0x10` @`0x6100BDCE`, `bl 0x6107D514` @`0x6100BDD2` (memcpy), `adds r4,#0x10` @`0x6100BDD6`.

#### 10.10.5 No `{end,end,start}` pair table

`0x6100D000..0x6100D014` (101) = `F0700B10, EE08FD57, E0810A10, 6109B31C, 6109E270, 0x4353415B "[ASC"`. The 707 mirror at `0x6100CFDC..` differs only in `EE08FD91`, `6109B36C`, `6109E2C0` (pointer relocation). Three words are **not** a `{list_end, list_end, list_start}` triple; there is no second 1-record list. The `0x6109B31C` value is a lone pointer used by the indexed printer above.

#### 10.10.6 Where the real 8-track/ch 11–20 gate must be

With T2 closed, two data structures remain as live routing candidates, neither yet mapped to ch 1–10 vs ch 11–20:

1. **12-B `{name_ptr, aperture, len}` table** — the real base is MC-101 `0x61096168`, MC-707 `0x610961B8`; **29 rows** (`k=0..28`), stride **12 B**, followed by the inline terminator word `0x003F003F` @`0x610962C4` (707 @`0x61096314`). **29/29 rows identical in `(aperture,len)` and in pointed-to name strings**; every name pointer is relocated by the build shift. This is a run-finder result: it is the **only** maximal 12-B run in either image satisfying `(name_ptr ∈ image, aperture ∈ 0x40..0x43xxxxxx, len ≤ 0x1000000, len & 0xFFF == 0)`. Row names are DSP/port labels: `Wr(1)`, `Rd(1)`, `"          PC\n"`, `mac0/1`, `SIO#1`, `r1`, `mxmon1`, `SIO#3`, `r2`, `r3`, `mxmon3`, `SIO#5`, `n4`, `8`, `r7`, `Wr(0)`, `r0`, `fnc1`, `mxmon2`, `DRAMIO3`, `IO4`, `mxmon0`, `@mode2`; six rows (`k=5,8,11,14,17,28`) point 4 B *before* a `DSP_ENV0..4`/`DRAMIO4` string, so their `cstr` is empty and the intended label is the following word. Apertures: `0x41440000/0x3000`, `0x41460000/0x10000`, `0x414A0000/0x8000`, then `(0x41540000/0x3000, 0x41560000/0x10000, 0x415A0000/0x8000)` … repeating through `0x419A0000/0x4000`, then `0x41240000/0x10000` and `0x41110000/0x41114000/0x41118000/0x4111C000/0x41120000/0x41124000/0x41128000/0x41130000/0x41134000/0x41138000`, each `/0x1000`.
   **The old "22 rows @`0x610961C0`, `{aperture,len,name_ptr}`" was a `+4` phase error** (third instance of the same trap as §10.10.2): `0x610961C0 = 0x61096168 + 7*12 + 4` = **row 7's `aperture` field**, so the window began at row 7's `ap` and read each following row's `ap/len` paired with the *previous* row's `name`. That manufactured the `0x41640000/0x3000/0x612C6F0C` first tuple and put the real terminator `0x003F003F` into a "name" slot after 22 pseudo-rows. There is **no code xref**: the only raw word in either image that lands in the table is `0x61002950 = 0x6109622C`, and that is part of the printf data island `0x6100294C..0x610029F0` (`{0x61096148, 0x6109622C, 0x003F003F}` followed by `"Program N/A    %-4s %08lXh"`), not a table reference. Consumers therefore have to be found through the window-head structure, not through this table.
2. **Window-head table @`0x610A1EB8`** — **analyzed this session and closed as a DSP-core memory-window/MPU descriptor, not USB routing** (see §10.10.8).

The product difference is therefore **not** in static Core 1 router config (§10.6: 101/707 boot init byte-identical), **not** in the 16-B descriptor dump (129/129 identical), and **not** in the window-head structure (§10.10.8: per-DSP-core window setup, byte-identical semantics on both models). Remaining candidates: runtime Core 0 bridge/mask state (§10.3/§10.5 probes) or a Core 0 product-ID gate. Next step is the product-ID / track-count gating search over both products.

#### 10.10.8 Window-head structure is a per-DSP-core memory-window descriptor — dead end (byte-verified this session)

**Geometry correction.** The run is **6 records, stride `0x1C` (7 words)**, base `0x610A1EB8` (101; 707 mirror `0x610A1F08`), shape `{ap1,ap2,ap3, ctlA, ctlA+4, head, index}`:

```
610A1EB8: 41114000 41115000 41116000 41104400 41104404 41400000 00000001
610A1ED4: 41118000 41119000 4111A000 41105400 41105404 41500000 00000002
610A1EF0: 4111C000 4111D000 4111E000 41106400 41106404 41600000 00000003
610A1F0C: 41120000 41121000 41122000 41107400 41107404 41700000 00000004
610A1F28: 41124000 41125000 41126000 41108400 41108404 41800000 00000005
610A1F44: 41128000 41129000 4112A000 41109400 41109404 41900000 00000006
610A1F60: 41110000 41111000 41112000 41102400 41102404 41200000 0A980000   <- 7th, differently shaped
```

`ap1,ap2,ap3` step by `0x4000` within the group and by `0x4000` between groups; `ctlA` steps by `0x1000`; `head` steps by `0x100000` (`0x41400000..0x41900000`); `index` = `1..6`. The 7th record @`0x610A1F60` is **not** a window group: its `head` is `0x41200000` and its last word is `0x0A980000`, not a small index; it is a different table leaking into the stride. The previous §10.10.6 reading of "heads 0x41600000/0x41700000/0x41800000 with counts 3,4" was again a **phase error** — `0x610A1EF0` was taken as a group base, so each 7th word shifted by 4 words and the `index` field (`3,4,…`) was mistaken for a count. `0x610A1F58 = 0x41900000` on **both** models (707 `0x610A1FA8`); `0x610A1F7C = {09800000, 0x27, 0x69, 0x77}` followed by literals `1..0x0C`.

**Literal-pool users (all resolved to the right pool word this session).**

| site | pool | value / meaning |
|---|---|---|
| `0x610182DC`, `0x61018644` | `0x610A1F58` | `0x41900000`, used as a **flag word** |
| `0x6101A69A`, `0x6101A6AE`, `0x6101A6C8` | `0x610A2094` | record/len **array** (`0x40,0x40,0,0x40,…`), not a pointer |
| `0x6101A730` | `0x610A212C` | `0x00060021…` char/emit table (`"-0123456789"` at `0x610A214C`) |
| `0x6101B5C2`, `0x6101B5C8` | `0x610A2188` / `0x610A2184` | `0x10101010` / `0x10101034` fill constants |
| `0x6101BDE6` | `0x610A218C` | `0x4B491010` ("KI" tag) |
| `0x6101BE06/26/46/66/86` | `0x610A21D4/221C/2264/22AC/22F4` | 20-byte-stride table initializer args |

**Consumer classification.**

- `0x6101A698` / `0x6101A6AC` — **record-address accessors**: `ptr_array[r0] + (len_array[r0] * r1) << 4`, a `+4` variant, and a bounds-checked `<0x13` lookup. Pure array indexing; no bus/audio access.
- `0x6101A6DC` — `(...)` name/number **formatter** (magic `smull`, char table `0x610A212C`). String output.
- `0x6101B5B6` — UI **page/callback struct initializer**: 7 callbacks via `subw r1,pc`, `0x2c`-byte struct. UI plumbing.
- `0x6101BDDC` — **table initializer** writing 20-byte-stride entries (`0x6107d4e2` / `0x6107d4ec` per entry).
- `0x610182D6` and `0x6101863E` — the only two functions that consume `0x610A1F58`, and they are **DSP core memory-window/remap setup**:
  - test `r7 == #0x40004000`; build base `0x11000000`/`0x13000000` (fn1) and `0x10000000`/`0x12000000` (fn2);
  - `bfi` the core index at **bit 20**; program `[r4/r7+0x4c]` control registers;
  - write a **16-B window descriptor** into `[r5]`;
  - set `[r8+0x9ac]`, `[r8+0x9b0]`, `[r8+0x398]`, `[r8+0x6a4]`;
  - `sl = [0x610A1F58] = 0x41900000` is used as a **flag**, with bits 19/20 cleared — not as a bus address to stream audio.

**Verdict.** Every indirect consumer is a printer, a formatter, a UI struct init, or a table init; the two direct consumers program a **DSP core's memory window / MPU remap**, not the USB audio router. There is **no path from these 84 bytes to the 20-channel USB IN mux**. The window-head structure is therefore a confirmed dead end for the ch 11–20 gate, and the §10.10.6 "highest-value next disassembly target" framing is withdrawn. Any future work on the resume/window subsystem must not be justified by stem routing.

#### 10.10.7 Method note

All facts above were produced this session by `8-track/tools/c1img.py` reads over `vendor/mc101_sys_v182/extracts/RPG69_C1A/sdram1.bin` and `vendor/mc707_sys_v182/extracts/RPG68_C1A/sdram1.bin`: row dumps of `0x6109AB00..0x6109B338` (both models), `cstr()` comparison of all 129 name fields, the four consumer disassemblies, the `0x6100D000` word dump, and the 12-B table rows `0..45`. Every number in §10.10.1–§10.10.6 is a direct read, not an agent summary. The earlier T2 numbers were **only** wrong because they were derived from a `+8`-misaligned window inside this table; no byte of the original reports was fabricated here, but every interpretive claim in §10.7/§10.9 is withdrawn.

## 11. Core 0 is the product gate: streaming-DMA / FIFO asymmetry (2026-11-16, all claims byte-verified by me from the raw decrypted images)

Method: capstone Thumb disassembly with literal-pool resolution, `8-track/tools/c1img.py`
`Img.literal_users()` reverse lookups, 4-aligned pool-word scans, and T4/T2 `bl`
decoding (self-tested) over
`vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin`,
`vendor/mc707_sys_v182/extracts/RPG68_C0A/App1_Main_decrypted.bin`, and all four Core 1
payloads. No hardware was flashed in this session.

### 11.1 Core 1 payload VA mapping settled: runtime VA = file offset + base − `0x20`

Each Core 1 payload file carries a **32-byte header** in front of the image that lands at
the segment base. Independent proofs:

1. The idm1 pool word at runtime `0x01100E70` is `0x61000001` — a **Thumb** entry address
   into sdram1, unique among all 4-aligned idm1 words, identical in both models; and the
   sdram1 halfword at file offset `0x20` disassembles as T4 `bl` (`00f002f8`, `7df026fa`).
2. Ghidra's own `C1_SDRAM_SDRAM1` / `C1_ITCM_IDM1` blocks are `len − 0x20` long.
3. The idm1 vector table (MSP `0x200A91C8`, reset `0x01100DE5`) is at file offset `0x20`,
   i.e. runtime `0x01100000` — the only reading that puts a vector table at a
   `≥0x40`-aligned runtime address.
4. Reading Ghidra at runtime `0x61000000` == reading the file at offset `0x20`.

Consequence: **every Core 1 address written in §10.6–§10.10 as a *file* offset is `0x20`
too high as a runtime VA** (e.g. the descriptor dump "base `0x6109AB00`" is file-derived;
runtime is `0x6109AAE0`). The doc labels stay valid as file labels; the probe tools
(`tools/probe_apertures.py`) already use runtime values and are unaffected. This also
dissolves the old "MC-707 = MC-101 + `0x20` pointer relocation" notes: the whole model
shift is a header offset, not a relocation. Tooling consequence: `8-track/tools/c1img.py`
now maps payloads at `segment base − 0x20` (`PAYLOAD_HEADER`), so every subcommand address
is a runtime VA; spot-check `load('mc101','idm').read(0x01100000, 8)` ==
`c8910a20 e50d1001` (MSP + reset).

### 11.2 `0x2C00` census over all six images — Core 1 is model-identical

| image | `mov.w rX,#0x2C00` sites |
|---|---|
| MC-101 Core 0 | **0** |
| MC-707 Core 0 | **7**, all inside dispatcher `0x60075534` |
| MC-101 sdram1 / MC-707 sdram1 | **8 each, byte-identical sites** |
| MC-101 idm1 / MC-707 idm1 | 0 |

Core 1 is therefore **not** the product discriminator, and the 707's `0x2C00` writes are
confined to one Core 0 dispatcher (event `0x3A`) at
`0x60075736/740/74A/754/75E/768/778` → slots
`0x400266B8/66B4/66B0/6684/6678/666C/6668` (7 slots). The MC-101 has no twin of that
dispatcher (20-byte prefix scan: 0 hits), and its invoker `0x6004D32C` prefix is also
absent from the 707. **The product gate is in Core 0.**

### 11.3 The power-up twin pair, decoded as (slot, value) tables

101 `0x6001ABB2` (5 writes) vs 707 `0x6001B010` (13 writes), resolved literal-pool by
literal-pool:

| register | MC-101 | MC-707 |
|---|---|---|
| bitband `0x424C4500` | `*0x424C4500 = 0` | `*0x424C4500 = 0` |
| `0x40026660` | `0x800` | `0x800` |
| `0x40026684 / 6678 / 666C` | `0xC01` ×3 | `0xC01` ×3 |
| `0x40026668` | `0xC02` | `0xC02` |
| `0x400266B8 / 66B4 / 66B0` | **never written** | `0xC01` ×3 |
| `0x400266C4 / 0x40026D34 / 0x400266C0 / 0x40026D30` | **never written** | `0` ×4 |

Pool-word census (whole-image, 4-aligned): slot `0x40026D30`/`0x40026D34` have **zero**
pool words anywhere in the MC-101 Core 0 image — the 101 firmware never touches them.
`0x400266B0/66B4/66B8` each have exactly one 101 pool word (`0x6001AE44`, `0x6001B070`,
`0x6001B060`); the 707 has two each (power-up + dispatcher).

### 11.4 Streaming-DMA stream census (queue starters)

The queue starter (`707 0x6001ECA0` / `101 0x6001E3F0`) computes a channel-block base
`0x40021000 + idx*0x400` for `idx < 10`, else `0x40053800 + idx*0x400`, plus `idx*4 + 0x18`,
stores the control pointer at `[r7, idx*4]`, and calls `[desc+0]` as the start callback.
The callback writes `+0x00 = desc[0] & 0xFFFF` (source endpoint `0xB301` / `0xA101`),
`+0x04 = desc[0] >> 16`, `+0x0C = desc[1] >> 16` (`0x0B3F` / `0x030C`),
`+0x14 = desc[1] & 0xFFFF = 0x0803`, `+0x18 = desc[2] = 0x2000`.

Stream starters:

| model | site | queue | descriptor `{src, fmt, len}` | control blk | callback | leaf call | callers |
|---|---|---|---|---|---|---|---|
| 707 | `0x60027956` | 5 | `{0xB301, 0x0B3F0803, 0x2000}` (desc `0x6021423C`) | `0x6046AD54` | — | `bl 0x6001b43c` @`0x6002797E` | yes |
| 707 | `0x60028398` | 6 | `{0xA101, 0x0B3F0803, 0x2000}` (desc `0x60214248`) | `0x6046AD68` (`[0]=0`, `[4]=0x60031585` post-start cb, `[8]=0x60031A51`, `[0x10]=0x600250A1`) | — | `bl 0x6001b43c` @`0x600283BE` | **none** |
| 707 | `0x600283E4` | 4 | `{0xB301, 0x030C0803, 0x2000}` (desc `0x60214254`) | `0x6046AD7C` | `0x600315A5` | none (`strb 1 → 0x6037C5BC`) | **none** |
| 101 | `0x6002666C` | 6 | `{0xB301, 0x0B3F0803, 0x2000}` (desc `0x601D036C`) | `0x603A4A70` | — | leaf `0x6001B030` @`0x60026696` | `0x6004D32C` (sole) |
| 101 | `0x600272E0` | 4 | `{0xB301, 0x030C0803}` (desc `0x601D0378`) | `0x603A4A84` | `0x6002E951` | none (`strb 1 → 0x602C9FF0`) | **none** (dead code) |

MC-101 `0x600272E0` **is** the twin of 707 `0x600283E4` (same shape: `ldrd` descriptor →
stack, ctrl writes, `movs r0, #4; bl 0x6001e3f0`, `strb 1`), and it is unreachable: 0 `bl`
callers, 0 pool/struct pointer references in either model. The 707's `0xA101` stream
`0x60028398` is likewise uninvoked statically. So invocation of these streams is
**RAM-registered** (runtime function-pointer table), identical situation to the USB IN
bridge mask callbacks of §10.3. `0x6002732C` in the 101 is a small wrapper
(`movs r0,#6; bl 0x60019FAE`), **not** a stream starter — the earlier guess was wrong.
Even the 101's live stream chain is RAM-invoked: its sole caller `0x6004D32C` has **0**
references of any kind in Ghidra's DB.

**The cleanest product asymmetry found so far** (whole-image 4-aligned word census):
the DMA source endpoint `0x0000A101` occurs **exactly once** in the MC-707 Core 0 image —
as the first word of the descriptor at `0x60214248` — and **zero** times in the MC-101.
Both models have exactly **two** `0x0000B301` descriptors (707 `0x6021423C` / `0x60214254`,
101 `0x601D036C` / `0x601D0378`). The 8-byte descriptor pair `0000A101, 0B3F0803` has **0**
hits in the MC-101; the model's only unaligned byte-run hit (`0x601F3C03`) is a record table
of small ids (`…a1 00 00 00 | …a2 00 00 00`, 707 mirror `0x602970B7`), not a DMA endpoint.
The MC-707 firmware therefore has a **third DMA stream
from endpoint `0xA101` that has no counterpart anywhere in the MC-101**, and it is the same
model pair as the FIFO-enable difference of §11.5.

### 11.5 The decisive asymmetry: **how many streaming FIFOs get enabled**

- **MC-101 audio-start leaf `0x6001B030`** (writer helper `0x600220F0`, sole caller
  `0x60026696`) enables **one** FIFO: `0x400266BC = 0x803`, plus `0x400266B8 = 0`,
  `0x40026A48 = 1`, bitband `*0x424C4924 = 1`, tail `0x400266B4 = 0x800`.
- **MC-707 helper `0x6001B43C`** (writer helper `0x60022E60`, callers `0x6002797E` **and**
  `0x600283BE`) enables **two**: `0x40026688 = 0x803` **and** `0x400266BC = 0x803`, plus
  `0x4002668C = 0`, `0x40026A3C = 1`, bitband `*0x424C4510 = 1`, tail `0x40026670 = 0x800`.
- The sample-rate/mode function is **byte-identical** in both models (101 `0x6001C370`-band,
  707 `0x6001CA80`-band) and it disables **both** FIFOs (`0x400266BC` and `0x40026688` ← `0`).
  ⇒ the MC-101 firmware **does** address `0x40026688`; the register exists on the silicon,
  it is simply never *enabled*.
- Pool census (whole image, literal-`ldr` resolution): `0x40026688` has 2 users in each
  model; `0x40026A3C` has 1 user in the 707 (`0x6001B448`) and **0 pool words in the 101** —
  confirming Attempt 4's "does not exist on MC-101".

**Interpretation.** Track 8 has **no `0x400266xx` router slot on the MC-707 either**. The
second stem's path is the **second streaming FIFO** (`0x40026688 = 0x803`) fed by the
queue-6 `0xA101` stream, together with `0x400266C0 / 0x400266C4 / 0x40026D30 / 0x40026D34`
(the four registers the 707 zeroes at power-up and the 101 never touches). NARROW-REG
replicates only 3 of the 7 dispatcher slots (`0x66B0/66B4/66B8`) — it is a tracks-5–7 fix,
not a track-8 fix.

### 11.6 RETRACTED: the bit-band alias → word mapping used in §10.1/§10.4/§10.5

ARM bit-band aliasing is `alias = 0x42000000 + (word − 0x40000000) * 32 + bit * 4`.
Decoding every alias our docs cite:

| alias written by firmware | true word / bit | docs claimed |
|---|---|---|
| `0x424C4500` (101 power-up, `0x424C4510`, `0x424C451C`) | `0x400988A0` bits 0 / 4 / 7 | "word `0x400262xx`" ✗ |
| `0x424C4524` (707 dispatcher) | `0x400988A4` bit 1 | ✗ |
| `0x424C4920 / 4924 / 4928 / 492C / 493C` | `0x40098924` bits 0 / 1 / 2 / 3 / 7 | "word `0x40026248` bit 9" ✗ |

The claim "bitband `0x424C4924` = word `0x40026248` bit 9" is arithmetically impossible:
that alias for `0x40026248` bit 9 is `0x424B2A24`. Live baseline confirms the correction:
`0x40026248 = 0xF100` (bit 9 **clear**), `0x40026228 = 0xDAF`. `tools/probe_router_state.py`
has been corrected to read the real bit-band word blocks (`0x40098880`, `0x40098900`).

Corollary, and a hard constraint: the 707 helper sets `0x400988A0` bit 4
(alias `0x424C4510`), which on the **MC-101 is the power-off latch** (Attempt 4 killed the
unit). The same word bit has the opposite meaning per product ⇒ the 707 sequence **cannot be
replicated verbatim**; `writer(0x40026688, 0x803)` must be added **without** alias
`0x424C4510` and without `0x40026A3C`.

### 11.7 Staged NARROW-REG audit against the 707 dispatcher — consistent

The CAVE-02 trampolines put `0x2C00` on `0x66B8 / 66B4 / 66B0` (a subset of the 707's 7
slots), clear the loopback aliases (`0x424C4920/24/28` = the 707 dispatcher's bitband
clears), and **preserve** `0x400266BC = 0x803` (FIFO #2 enable) written by the leaf. No
DAC-routed slot and no FIFO register is written. Prediction for the next flash: channels
11–16 (tracks 5–7) become clean; channels 17–20 (track 8) stay silent, because the second
FIFO is not enabled. Any degradation of channels 1–10 ⇒ revert.


### 11.8 Queue-starter internals, descriptor semantics, and the RAM-registration targets (2026-11-16 follow-up, byte-verified)

Full decode of the MC-101 starter `0x6001E3F0` (twin of 707 `0x6001ECA0`, byte-identical
shape), arguments `r0 = queue idx`, `r1 = descriptor`, `r2 = ctrl block`:

```text
r5 = CB base = 0x40000000 + (0x21000 if idx < 10 else 0x53800) + idx*0x400
[r7 + idx*4] = r2                       ; r7 = ctrl-pointer table (literal pool)
if ([r2] != 0) blx [r2] with r0 = idx   ; ctrl[0] = optional pre-start cb
*CB       = 0xFFFF8000                  ; reset write, overwritten below
 CB[0x00]  = desc.half[0] = desc[0]&0xFFFF   ; source ENDPOINT (0xB301 / 0xA101)
 CB[0x04]  = desc.half[1] = desc[0]>>16
 CB[0x0C]  = desc.half[3] = desc[1]>>16      ; 0x0B3F / 0x030C
 CB[0x14]  = desc.half[2] = desc[1]&0xFFFF   ; 0x0803 (written over the constant 0xC)
 CB[0x18]  = desc.half[4] = desc[2]&0xFFFF   ; 0x2000 transfer length
 bl 0x6001E850 twice   ; installs an ISR in the LIVE vector table:
                       ; 0x6001E850: str r1, [SCB->VTOR (0xE000ED08) + 0x40 + r0*4]
                       ; r0 = idx*4 + (0x17 if idx < 2 else 0xC0) + 1
                       ; queue 4 -> VTOR+0x384 (IRQ 209), queue 5 -> +0x394 (IRQ 213),
                       ; queue 6 -> +0x3A4 (IRQ 217)
if ([ctrl+4] != 0) tail-call it with r0 = idx  ; ctrl[4] = post-start callback
```

Concrete values (literal-pool resolved):

| item | MC-101 | MC-707 |
|---|---|---|
| ctrl-pointer table base (`[base + queue*4]`) | `0x60A85E00` (RAM) | `0x60B5E4C0` (RAM) |
| CB reset constant written to `CB[0]` | `0xFFFF8000` | `0xFFFF8000` |
| ISR pool words (queue path) | `0x60023905`, `0x010241B5` | `0x6002464D`, `0x01027179` |
| vector installer | `0x6001E850` | `0x6001F328` |
| live USB-IN stream | **queue 6**, desc `0x601D036C` = `{0000B301, 0B3F0803, 00002000}`, ctrl `0x603A4A70`, starter `0x6002666C`, leaf `0x6001B030` @`0x60026696` | **queue 5**, ctrl `0x6046AD54`, starter `0x60027956`, helper `0x6001B43C` @`0x6002797E` |
| second stream (707 only) | — | **queue 6**, desc pool `0x60214248` → `{0000A101, 0B3F0803, 00002000}`, ctrl `0x6046AD68`, starter `0x60028398`, helper `0x6001B43C` @`0x600283BE` |
| queue-4 stream | **queue 4**, desc `0x601D0378` = `{0000B301, 030C0803, 00002000}`, ctrl `0x603A4A84`, starter `0x600272E0` = **dead code** (`strb 1 → 0x602C9FF0`, no leaf call) | **queue 4**, desc pool `0x60214254`, ctrl `0x6046AD7C`, starter `0x600283E4`, cb `0x600315A5`, no leaf call, statically uninvoked |

Note the **model-dependent queue numbering**: the MC-101's live B301 stream is queue **6**
while the MC-707's twin (same `{B301, 0B3F0803, 0x2000}` descriptor) is queue **5**. The
707 puts its extra `0xA101` stream in queue 6, so the same CB address `0x40022800`
(= `0x40021000 + 6*0x400`) is the B301 stream on the MC-101 and the A101 stream on the
MC-707.

The MC-101 image ends at `0x60356570`, so **every ctrl block and the ctrl-pointer table are
RAM (`.bss`)** — their contents are probe-only. That is why static xref hunting for the
invokers of the 707's extra streams came up empty, and it makes the RAM table the primary
live target. `tools/probe_router_state.py` now reads `0x60A85E00` (16 queue slots; `NULL` =
never registered), `0x603A4A40`/`0x603A4A80` (the 101's queue-6 / queue-4 ctrl blocks), CB
windows `0x40022000` (queue 4), `0x40022400` (queue 5), `0x40022800` (queue 6), and
`0xE000ED00` (SCB, for the live `VTOR`, so the installed DMA vectors at `VTOR+0x384/394/3A4`
can be read next session).

**Endpoint ↔ FIFO pairing (inference, strongly consistent):** every MC-101 stream uses
endpoint `0xB301`, and the MC-101 leaf enables exactly one FIFO — `0x400266BC`. The
MC-707's extra, MC-101-absent stream uses endpoint **`0xA101`**, and the MC-707's shared
audio-DMA enabler `0x6001B43C` (called from *both* the queue-5 and the queue-6 starters)
enables `0x40026688` **in addition** to `0x400266BC`. So `0xA101 ↔ 0x40026688` (second
streaming FIFO) and `0xB301 ↔ 0x400266BC`. That makes the track-8 patch shape concrete:

1. `writer(0x40026688, 0x803)` inside the audio-start leaf `0x6001B030` — the 707's exact
   value, **not** `0xC01`, and **without** alias `0x424C4510` (MC-101 power-off latch) and
   **without** `0x40026A3C` (0 pool words on MC-101).
2. A second stream started through `0x6001E3F0` with descriptor
   `{0x0000A101, 0x0B3F0803, 0x00002000}` (verbatim from the 707, as `.data` in the cave) and
   a RAM ctrl block `{0, post-start cb, arg, 0, arg, 0}`.
3. **Open question: the queue index.** CB and ctrl-table slots are indexed by queue, and the
   MC-101 already occupies queue 6 with its B301 stream, so the A101 stream needs a **free**
   index — RAM state, answered by the `0x60A85E00` probe (16 entries, `NULL` = unused). The
   707's own usage (`4 = B301/030C`, `5 = B301/0B3F`, `6 = A101/0B3F`) shows it is the
   endpoint/format pair, not the index, that the FIFO cares about.

Probe order for the next live session: `0x60A85E00` (free queues) →
`0x40022000`/`0x40022400`/`0x40022800`/`0x40022C00` (CB contents = the true
endpoint/format/length in use, and which queues are free) → `0x40026688`/`0x400266BC` (FIFO
state at runtime) → `0xE000ED08` (VTOR) → the DMA vectors.

Post-start callbacks (written to `ctrl[4]` by the starters; the value the starter
tail-calls): MC-101 queue 6 = **`0x6002E8ED`**, MC-101 queue 4 (dead) = `0x6002E951`;
MC-707 queue 5 = `0x60031521`, **queue 6 (the `0xA101` stream) = `0x60031585`** with
`ctrl[8] = 0x60031A51` and `ctrl[0x10] = 0x600250A1`. The 707's `0xA101` starter
`0x60028398` is a self-contained 24-instruction function whose entire context is three
literal pools (descriptor, ctrl block, three callbacks) — a direct donor for a
MC-101 track-8 stream trampoline.

### 11.9 POST-FLASH VERDICT: the ESC2 write-mask fuse — NARROW-REG is hardware-dead (2026-11-16, hardware-verified)

The NARROW-REG image (whole CRC `0x4539FDD6`) was flashed and probed live
(`/tmp/opencode/probe/postflash_narrowreg.json`, diff vs `baseline_preflash.json`).

1. **The flash and the trampolines are genuine.** DMA probes of the four branch sites
   (`0x6001AD80`, `0x6001B000`, `0x6001B040` windows) and CAVE-02 (`0x602D2B00..3F`,
   `0x602D2B40..7F`) read back **byte-identical to `App1_Main_decrypted.8track.bin`**.
2. **The router register self-clears bit 13 of every `0x2C00` write.** The slots read
   back **`0x0C00`** — at idle and after audio start (the leaf rewrites at every audio
   start, so the readback is post-trampoline): `0x400266B0 = 0x0C00`,
   `0x400266B4 = 0x0C00`, `0x400266B8 = 0x0C00`. The value accepted by the ESC2 is the
   write with **bit 13 (the DSP streaming-bus page) masked out**. On the MC-101 the
   write-enable mask for these slots is silicon-fused with bit 13 = 0 ⇒ the DSP
   streaming bus is physically absent from the 101's router inputs; no firmware on any
   core can open a write-enable fuse.
   **Caveat**: the surviving `0x0C00` is bit 10+11 + source 0 = an *enabled* mux input on
   the pin page with source index 0 — not silence.
3. **The acoustic diff (USB capture `hw:3,0` FLOAT_LE 44100 20ch, idle + playing):**
   - ch 1–10: clean (downmix + 4 stems at RMS −24.6…−11.3 dBFS while playing) — **no regression**.
   - ch 11–16: signal-independent garbage — RMS between idle and playing identical to
     0.1 dB (e.g. ch11 656.8 vs 656.8 dBFS as-float), 11-sample period (44-byte packet
     repeated by the stalled bridge), pairs mono-duplicated (11≡12, 13≡14, 15≡16:
     one router slot = one mono source per USB stereo pair).
   - ch 17–20: stock silence → 100 % repeating garbage. The only router delta in that
     domain is the LB site's loopback clear (`0x40026248`: `0xF100 → 0xF000`, bit 8 cleared).
     Bit 8 of that word gates the sampler-side path ⇒ the LB site is a **net regression**
     and must be reverted together with B0/B8/B4.
4. **Queue state (live, `0x60A85E00`)**: `[4] = 0x603A4A84` (queue-4 twin stream is
   registered at runtime), `[6] = 0x603A4A70` (live B301), `[5] = NULL` and
   `[7..15] = NULL` ⇒ **queue 5 is free** for the second (track-8) stream. The CB words
   read with hardware status `0xFFFF0000` overlaid: live queue-6 CB = endpoint
   `0x3301` (`0xFFFF3301`), `+0x0C = 0x0B3F`, `+0x14 = 0x0803`, `+0x18 = 0x000A`
   (length mutates per transfer — idle value 10, not the programmed `0x2000`).
   Queue-4 CB is resident too (endpoint `0x3301`, format `0x0C03`).
5. **SCB is outside DMA reach**: the Vel-26 probe returns status 2 for `0xE000ED00` ⇒
   `VTOR` and the installed DMA vectors cannot be read by this engine (PPB). Vector
   questions must be answered from Core 1 side channels or from static evidence.
6. **Disposition**: `ENABLE_NARROW_REG = False` in `gen_manifest.py` (sites
   `NARROW-REG-B0/B8/LB/B4` removed from the manifest; CAVE-02 freed). The page to
   blame — pin page `0x0Cxx` (accepted), DSP page `0x2Cxx` (fused). Consequences for
   the roadmap: (a) ch 11–16 have **no** attainable DSP source via ESC2 mux slots on
   MC-101 silicon; (b) the FIFO recipe (§11.8) is untouched by the fuse — FIFO control
   registers accepted `0x803` at runtime (`0x400266BC = 0x803` live on the 101);
   (c) any 8-stem plan must therefore assemble stems 5–7 on the bridge/DSP side of the
   ESC2, not on the router side.
7. **Lesson (new probe-interpretation rule)**: a router slot value read back ≠ the value
   written — the ESC2 applies a per-slot, per-product **write-enable mask**. Static
   write-byte audits must be paired with a readback probe before predicting routing
   behaviour; the readback is the hardware truth.

---

## 12. MC-707-Depth Drum Pad Edit, WMT1–4 Sample Tools, & Sample Chop (Screen `0x68`)

All additions below run purely on Core 0 (`RPG69_C0A_up.bin`) using verified zero-padded SDRAM knob-table tails (100% zero in stock, zero incoming references) and stock Zen-Core / Wave RAM / Core 1 IPC primitives.

### 12.1 Memory Map (Verified Zero-Padded SDRAM Caves)

| Region | Address Range | Size | Purpose |
| :--- | :--- | ---: | :--- |
| `DRUM-ENV-CLIP-HOOK` | `0x602D2A90..0x602D2ACF` | 64 B | Clip sync trampoline for Pitch/TVF/TVA Env param groups (`0x104+trk`, `0x10D+trk`, `0x116+trk`) |
| `DRUM-PAD-EDIT-TBL` | `0x602D2B00..0x602D3D7F` | 4,736 B | 11-section Drum Pad Edit descriptor + 147 new `ITEM_LIST_PRM` entries + deduplicated labels |
| `SMPL-EDIT-DESCS` | `0x602D3E60..0x602D3EC3` | 100 B | 4 × 12-byte section descriptors + `"WMT1..4 SMPL:"` headers for Screen `0x5D` |
| `DRUM-PHASE2-HOOKS` | `0x602D3EC8..0x602D40DF` | 536 B | Thumb-2 trampolines (`tramp_snd_clear_wmt`, `tramp_pad_snd_enter`, `tramp_bind_pad_wav_wmt`, `tramp_sample_del_wmt_scan`, `tramp_smpl_edit_get_id`, `tramp_smpl_edit_hdr`, `tramp_pad_audio_gate`) |
| `CHOP-CAVE-0` (`SCR-TBL-EXT`) | `0x602D4220..0x602D48BF` | 1,696 B | Relocated 105-entry Screen Table (stock 104 entries from `0x601D06D4` + Screen `0x68` + NULL) |
| `CHOP-CAVE-0` (`SCR-68-DESC`) | `0x602D48C0..0x602D48CF` | 16 B | Screen `0x68` descriptor `{ 0x602D4FE1, 0, 0, 0 }` |
| `CHOP-CAVE-0` (`PAD-SND-MENU-TBL`) | `0x602D48D0..0x602D49C7` | 248 B | Relocated 13-entry Drum Pad Sound Menu (`PRESET`, `PROJECT`, `WAVE FILE`, `WMT1..4 WAVE`, `PAD EDIT`, `WMT1..4 SMPL`, `SMPL CHOP`) |
| `CHOP-CAVE-0` (`CHOP-RAM`) | `0x602D4A00..0x602D4EFF` | 1,280 B | Zero-init `.bss` for `sample_chop.c` (`g_chop` pinned at `0x602D4A00` via `.chop_state`, `g_env[128]`, `g_chunk[256]`) |
| `CHOP-CAVE-1` (`CHOP-CODE`) | `0x602D4FE0..0x602D5CCF` | 3,312 B | `sample_chop.c` `.chop_entry` + `.text` (entry, event loop, audition, live WMT solo/restore, LCD helpers) |
| `CHOP-CAVE-2` (`CHOP-SLICE`) | `0x602D5DB0..0x602D6A9F` | 3,312 B | `sample_chop.c` `.chop_slice` + `.rodata` (Wave RAM truncator, User Sample creation, Core 1 IPC `0xFFFA`, Pad assignment, LCD renderer) |
| `CHOP-CAVE-3` (`CHOP-DETECT`) | `0x602D9400..0x602DA0DF` | 3,296 B | `sample_chop.c` `.chop_detect` (step slicer, 128-bin onset-flux transient detector, manual slice add/delete/nudge, sample loader) |

### 12.2 Phase 1 — MC-707-Depth Drum Pad Edit

- **`PAD-EDIT-ENV-CLIP` (`0x6004E108`), `PAD-EDIT-SEC-CNT` (`0x6004E12A`), `PAD-EDIT-SEC-PTR` (`0x6004E1A8`)**: Widens Screen `0x34` (`PAD EDIT`) from 3 to 11 sections pointing to `DRUM-PAD-EDIT-TBL` while keeping `INST EDIT` at index 1 (preserving stock `0x6004E1E8` Env Mode ↔ TVA T4 sync). `DRUM-ENV-CLIP-HOOK` sets the active clip on the 3 envelope parameter groups (`0x104+trk`, `0x10D+trk`, `0x116+trk`) alongside stock `0xFB+trk`.
- **`WMT4-FMT-BUGFIX` (`0x6008BB0A`) & `WMT4-SET-BUGFIX` (`0x6008BE04`)**: Fixes two stock Roland bugs in `DrumInst` formatting/setting where `WMT4` Bank/Type checked the wrong relative PID (`0x60`/`0x61` vs `WMT3`).

### 12.3 Phase 2 — Per-Layer `WMT1..4 WAVE` & `WMT1..4 SMPL`

- **`PAD-SND-*` (`0x6006A376..0x6006A648`)**: Repoints the Drum Pad Sound Menu to `PAD-SND-MENU-TBL` (13 entries), widens dial/left/right bounds from 5 to 13, and stores the selected WMT slot (`1..4`) in scratch SRAM (`0x602D2AF8`/`0x602D2AFC`) via `tramp_pad_snd_enter` / `tramp_snd_clear_wmt`.
- **`PAD-WAV-BIND-WMT` (`0x6002132E` → `tramp_bind_pad_wav_wmt`)**: When `mode_param == 0` (`WAVE FILE`), tail-calls stock `fw_bind_pad_wav` (`0x600299A4`). When `mode_param == 1..4` (`WMT1..4 WAVE`), writes `SW=1, GTYPE=2 (SAMP), WAV_NUM_L=sample_id+1` directly into `FW_DRUM_INST_TBL[trk] + clip*0x4A40 + pad_idx*0xD8 + 0x1C + wmt*0x1C` with audible defaults (`Level=127`, `Velo=1..127`), ensures `KitPad.InstNum != 0`, and calls `fw_mark_clip_dirty` (`0x6001A1A2`) without wiping other WMT layers or EQ/filter settings.
- **`SMPL-EDIT-GET1/2` (`0x6007C3BE`, `0x6007C504`) & `SMPL-EDIT-HDR` (`0x6007C468`)**: Redirects Screen `0x5D` (`SAMPLE EDIT`) to look up `WMT[w]` (`0x8E2 + w*0x17` Type / `0x8E4 + w*0x17` Wave L) via `fw_get_inst_prm` (`0x6009C064`) and display `"WMT1..4 SMPL:"`.
- **`SAMPLE-DEL-WMT-FIX` (`0x600877D6` → `tramp_sample_del_wmt_scan`)**: Loops over all 4 WMT slots (`stride 0x1C`) inside the Sample Delete usage scanner so User Samples assigned to `WMT2..4` are marked in-use.

### 12.4 Phase 3 — Sample Chop (`src/sample_chop.c`, Screen `0x68`)

- **Screen registration (`SCR-TBL-PTR1..4` @ `0x6001D4C4`, `0x6001D7A8`, `0x6001DF1C`, `0x60026008`)**: Repoints all 4 screen-table literals to `SCR-TBL-EXT` (`0x602D4220`) adding Screen `0x68` (`sample_chop_event`).
- **External Wave RAM hardware bridge (ITCM)**: `fw_get_sample_info` (`0x6004F880`) returns external 64 MB ERAM byte offsets, **not** Cortex-M7 SDRAM pointers. All waveform peak scans, transient detection, and slice truncation stream PCM through ITCM `0x01011D28` (`read16`), `0x01011D5E` (`bulk read`), and `0x0102C138` (`bulk write`, 4-byte aligned, with 64-byte zero lead-in/tail padding for Core 1's interpolator).
- **LCD CGRAM rendering**: Uploads 6 bar-height glyphs (slots `1..6`), a slice/transient tick (slot `7`), and a dynamic active-cursor + bar glyph (slot `0`) via `0x600974A4` / `0x60097554` without calling `0x60097520` directly (avoiding SPI7 race with the LCD task), and invalidates the CGRAM cache (`0x6009DBA4(0x60AD3E8A, 8)`) on `EV_CLOSE`.
- **Isolated live slice audition**:
  - **`CHOP-PAD-AUDIO-GATE` (`0x60099B16` → `tramp_pad_audio_gate`)**: Gates stock physical pad playback in `0x60099AF0` while `g_chop.active && g_chop.valid && g_chop.mode != MODE_SRC` (`g_chop` pinned at `0x602D4A00` via `.chop_state` and asserted at build time).
  - **Live WMT layer soloing**: Uses Roland's live parameter API `fw_set_param(0xFB + track, 0x8E1 + w*0x17, want, pad_idx, clip)` (`WMT1..4 Switch`) and `pid = 0x8E0` (`WMT Velo`) so Core 1 DSP immediately mutes all other WMT layers (both Preset `INT` waves and other `SAMP` layers) on the source pad during preview and restores them on `EXIT`/pad change.
  - **Real-time trigger**: Temporarily sets source User Sample Start/End (`0x11F / 0x98D, 0x98F`) and sends real-time Note-Off/Note-On directly to Core 1 internal synth port `2` (`0x60019FD6` → `0x60019FE0(2, msg)` → `0x60019EFA`).
- **Real truncated User Sample creation & Core 1 sync (`create_sliced_sample`)**: Allocates a free sample slot (`0..499`) and contiguous 32 KB Wave RAM blocks (`0x6002645C`), copies PCM + 64 B lead-in/tail zeros, populates 40-byte `SampleHeader` L/R entries + 1-to-1 block ownership (`0x6001A526`), initializes sample params (`0x6002DEEC`), pushes sample metadata to Core 1 via IPC `0xFFFA` (`0x60096510` → `0x60096548` → `0x6002D1AC` → `0x60019F36`), binds via `fw_bind_pad_wav` (`0x600299A4`, default `W1`) or non-destructive WMT bind (`W2..4`), and marks/syncs the clip (`0x6001A1A2`, `0x60046434`).

---

## 13. Button Navigation Mode (Hands-Free VALUE Dial Alternative)

Implemented as a standalone, optional Core 0 feature in [`src/button_nav.c`](src/button_nav.c) using its own verified zero-padded SDRAM cave (`0x602DA600..0x602DAE7F`, 0 incoming references in stock, non-overlapping with `CAVE-01` and `CHOP-CAVE-0..3`).

### 13.1 Verified ROM Key & LED Maps

Extracted from the MC-101 v1.82 ROM key-name table (`0x602CABA4`), LED-name table (`0x602CAC44`), and 48-entry LED descriptor table (`0x601D0554`, all 4 LEDs verified `count = 1`, hardware blink `mode = 3`, full brightness `color = 0xFF` from `0x602CDCBC`):

| Physical Button | Key ID | LED ID | Behavior in Button Nav Mode |
| :--- | :---: | :---: | :--- |
| `SHIFT` | `0x00` | `0x00` | Unchanged (`SHIFT + <` exits Nav Mode; `SHIFT + TEMPO` → `SHIFT + ENTER`) |
| `<` (`MEAS_L`) | `0x03` | `0x03` | Synthetic `EV_DIAL(0, -1)` + hold auto-repeat; LED blinks |
| `>` (`MEAS_R`) | `0x04` | `0x04` | Hold standalone 600 ms to enter; synthetic `EV_DIAL(0, +1)` + auto-repeat; LED blinks |
| `TEMPO` | `0x0F` | `0x0F` | Rewritten to `KEY_ENTER (0x11)` on down & up; LED blinks |
| `EXIT` | `0x10` | `0x10` | Unchanged; LED blinks |
| `ENTER` (`VALUE` press) | `0x11` | — | Unchanged |

### 13.2 Memory Map & Patch Sites (5 Active Sites)

| Site ID | Address | Length | Role |
| :--- | :--- | ---: | :--- |
| `NAV-RAM` *(BSS)* | `0x602DA600..0x602DA6FF` | 256 B | Zero-init `NavState g_nav` pinned at `0x602DA600` via `.nav_state` (build-time asserted) |
| `NAV-CODE` | `0x602DA700` | ~620 B | Compiled `src/button_nav.c` (`nav_tick_and_drain`, `nav_dispatch_event`) |
| `NAV-LED-TRAMP` | `0x602DAE40` | 40 B | `tramp_nav_led_override`: if `g_nav.active` and `led_id ∈ {3, 4, 15, 16}`, force `mode = 3`, `color = 0xFF` |
| `NAV-TICK-HOOK` | `0x6002EC24` | 4 B | Replaces `bl 0x6001de38` in the 50 ms main UI task loop with `bl nav_tick_and_drain` (600 ms hold detection via `fw_get_ms` `0x6001CC50` + 320 ms / 85 ms auto-repeat posting `EV_DIAL` via `0x6001D974`) |
| `NAV-DISPATCH-HOOK` | `0x6001DE66` | 4 B | Replaces `bl 0x6001da18` in the central UI event drainer with `bl nav_dispatch_event` (intercepts before any screen or global key handler; checks global pressed-key bitmap `0x605C40B0[0..5]` so combos like `SHIFT+>`, `SEQ+>`, `SEL+>` pass through untouched) |
| `NAV-LED-HOOK` | `0x6001E6B8` | 4 B | Replaces `fw_set_led` prologue (`push {r4-r6, lr}; mov r5, r1`) with `b.w tramp_nav_led_override` → `0x6001E6BC`; on `SHIFT + <` exit, clears LEDs `3, 4, 15, 16` then calls `fw_led_refresh_all(0x605C4E10)` (`0x60097A02`) |
