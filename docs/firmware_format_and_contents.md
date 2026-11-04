# Roland MC-101 / RPG69 Firmware Update Format & Extracted Contents Analysis

## 1. Overview & System Context

This document details the reverse engineering findings for the system firmware update files of the **Roland MC-101 Groovebox** (System Version **1.82**, Build **14423**, dated **2023-05-17**). 

The MC-101 and its sibling the MC-707 are powered by Roland's proprietary BMC / ESC2 sound engine platform running a multi-core ARM Cortex-M architecture. The firmware update package is organized by processor core and target flash memory partition:

* **Hardware Platform Identifier**: `RPG69` (Roland project code for MC-101 / MC-707 hardware series)
* **Core & Target Partition Scheme**:
  * **`C0`** = Core 0 (Main Host / OS CPU)
  * **`C1`** = Core 1 (Sound Engine / Zen-Core DSP Coprocessor)
  * **`A`** = Application executable image
  * **`C`** = Content / QSPI Flash filesystem image

| File (`vendor/`) | Size (Bytes) | Role | Primary Format |
| :--- | :--- | :--- | :--- |
| `RPG69_C0A_up.bin` | 3,499,600 | Core 0 Main Application Firmware (`App1_Main`) | Encrypted Executable Container |
| `RPG69_C0C_up.bin` | 8,388,576 (8 MiB) | Core 0 Flash Storage (PCM Tones, Kits, Project Init) | Roland QSPI Filesystem Image |
| `RPG69_C1A_up.bin` | 4,194,144 (4 MiB) | Core 1 Sound Engine Executables (`idm1`, `sdram1`) | Roland QSPI Filesystem Image |
| `RPG69_C1C_up.bin` | 4,194,144 (4 MiB) | Core 1 Synthesis Resources (Patches, Waves, Metronome) | Roland QSPI Filesystem Image |

---

## 2. Common Update Container Trailer Format

All update files conclude with an identical **52-byte (`0x34`) metadata trailer**:

```
[ ... Payload or QSPI Archive Data ... ]
[ 4-byte CRC-32 (LE) ] [ 48-byte ASCII Build Identification String ]
```

1. **CRC-32 Checksum (`offset: -0x34 .. -0x30`)**:
   * Standard 32-bit Little-Endian IEEE 802.3 CRC (`poly=0xEDB88320`, initial `0xFFFFFFFF`, inverted output).
   * Computed over all bytes preceding the CRC field (`data[:-0x34]`).
   * Validated bit-accurately across all four binaries.
2. **Build Identification String (`offset: -0x30 .. end`, 48 bytes ASCII)**:
   * Fixed-width ASCII string declaring manufacturer, hardware ID, partition, firmware version, build number, and build timestamp:
     * `RPG69_C0A_up.bin`: `Roland RPG69_C0AVER.1.82-BLD.14423 0517 22 54 58`
     * `RPG69_C0C_up.bin`: `Roland RPG69_C0CVER.1.82-BLD.14423 0517 22 55 00`
     * `RPG69_C1A_up.bin`: `Roland RPG69_C1AVER.1.82-BLD.14423 0517 22 49 32`
     * `RPG69_C1C_up.bin`: `Roland RPG69_C1CVER.1.82-BLD.14423 0517 22 49 32`

---

## 3. Roland QSPI Filesystem Container Specification

Files `RPG69_C0C_up.bin`, `RPG69_C1A_up.bin`, and `RPG69_C1C_up.bin` use a proprietary flat archive format designed for direct mapping or unpacking into external QSPI NOR flash storage.

### 3.1 Container Header Layout

| Offset Range | Length | Field Name | Description |
| :--- | :--- | :--- | :--- |
| `0x0000 - 0x0003` | 4 B | `payload_len` | Size of QSPI image including CRC, up to the 48-byte trailer string (`len(file) - 48`) |
| `0x0004 - 0x001F` | 28 B | `padding` | Zero padding |
| `0x0020 - 0x0023` | 4 B | `magic` | ASCII `"QSPI"` (`0x51 0x53 0x50 0x49`) |
| `0x0024 - 0x0027` | 4 B | `header_size` | Offset from `0x20` to data or TOC parameters (`0x00000020` = 32) |
| `0x0028 - 0x002B` | 4 B | `entry_size` | Size of each TOC entry in bytes (`0x00000020` = 32 bytes) |
| `0x002C - 0x002F` | 4 B | `num_files` | Number of files indexed in this QSPI image |
| `0x0030 - ...` | $N \times 32$ B | `toc_entries` | Array of $N$ Table of Contents entries |

### 3.2 TOC Entry Layout (32 Bytes per file)

```
0x00           0x0F 0x10       0x13 0x14       0x17 0x18       0x1B 0x1C       0x1F
+------------------+---------------+---------------+---------------+---------------+
|  Filename (16 B) | Offset (4 B)  | Length (4 B)  | Checksum(4 B) | Reserved(4 B) |
+------------------+---------------+---------------+---------------+---------------+
```

* **`Filename` (`0x00..0x0F`, 16 bytes)**: ASCII string. If shorter than 16 bytes, it is null-padded. If 16 bytes long, there is no null terminator (e.g., `tone_pcmx_cmn.bi` corresponds to `tone_pcmx_cmn.bin`, `kit_pcmx_rpg68.b` corresponds to `kit_pcmx_rpg68.bin`).
* **`Offset` (`0x10..0x13`, uint32 LE)**: Absolute byte offset from start of `.bin` file where file data begins (aligned to flash block/page boundaries, typically 4 KB `0x1000`).
* **`Length` (`0x14..0x17`, uint32 LE)**: Exact file size in bytes.
* **`Checksum` (`0x18..0x1B`, uint32 LE)**: 16-bit block verification checksum (referenced in system diagnostic logs as `CSum = %04Xh`).
* **`Reserved` (`0x1C..0x1F`, uint32 LE)**: Reserved (`0x00000000`).

---

## 4. Roland App1 Executable Container Specification (`RPG69_C0A_up.bin`)

`RPG69_C0A_up.bin` is the main host system executable for Core 0.

### 4.1 Header Structure (96 Bytes = `0x60`)

| Offset Range | Length | Value / Content | Description |
| :--- | :--- | :--- | :--- |
| `0x0000 - 0x000F` | 16 B | `"App1_Main\0\0\0..."` | Target module name |
| `0x0010 - 0x001F` | 16 B | `"2023/05/17 22:54"` | Build date and time |
| `0x0020 - 0x0027` | 8 B | `"0.010001"` | Internal module version |
| `0x0028 - 0x002B` | 4 B | `0x60000000` | Flash target base address (external memory-mapped Flash) |
| `0x002C - 0x002F` | 4 B | `0x00000000` | Reserved |
| `0x0030 - 0x0033` | 4 B | `0x000c0040` | Execution / jump address or image entry offset |
| `0x0034 - 0x003F` | 12 B | `0xFF` repeated | Reserved / padding |
| `0x0040 - 0x0043` | 4 B | `0x000c0060` | Offset to payload body |
| `0x0044 - 0x0047` | 4 B | `0x003565b0` (3,499,440 B) | Encrypted payload size |
| `0x0048 - 0x004B` | 4 B | `0x60000000` | Destination base address |
| `0x004C - 0x004F` | 4 B | `0x00000000` | Reserved |
| `0x0050 - 0x0053` | 4 B | `0x513fc2d9` | Header hash / payload integrity token |
| `0x0054 - 0x0057` | 4 B | `0xb6020001` | Architecture / execution flags |
| `0x0058 - 0x005F` | 8 B | `0x00000000`, `0xFFFFFFFF` | Terminator |

### 4.2 In-Depth Cryptographic Analysis

#### 4.2.1 Why it is NOT a Simple / Single XOR Scheme
1. **Direct Decryption Test**:
   * Assuming the dominant recurring 8-byte block `6b 4c 9a 85 2c 73 28 31` represents 8 zero bytes (`00` padding) or 8 `FF` bytes, XORing the payload with either key yields completely pseudorandom data:
     * Byte entropy remains unchanged at **`7.9973 bits/byte`**.
     * Zero valid ARM Cortex vector tables or Thumb instructions appear.
     * Zero readable ASCII text strings are revealed.
2. **Avalanche / Non-Linearity Proof (Half-Block Independence Test)**:
   * In any stream cipher or periodic XOR cipher where $C_i = P_i \oplus K_i$, encryption is independent per byte and word. In compiled ARM binaries, isolated 32-bit zero words (`00 00 00 00`) are pervasive (e.g., `mov r0, #0`, pointer alignment, null pointers).
   * If `6b 4c 9a 85 2c 73 28 31` were an 8-byte XOR key:
     * Any 32-bit zero word at an $8n$ boundary would produce `6b 4c 9a 85` regardless of the subsequent 4 bytes.
     * Any 32-bit zero word at an $8n+4$ boundary would produce `2c 73 28 31` regardless of the preceding 4 bytes.
   * **Empirical Verification across all 437,430 blocks**:
     * Occurrences of `6b 4c 9a 85` at $8n$: exactly **39,814**.
     * Occurrences of `2c 73 28 31` at $8n+4$: exactly **39,814**.
     * Occurrences of `6b 4c 9a 85` alone without `2c 73 28 31`: **0**.
     * Occurrences of `2c 73 28 31` alone without `6b 4c 9a 85`: **0**.
   * **Conclusion**: Altering a single bit anywhere within the 64-bit block completely diffuses across all 8 bytes (strict avalanche effect). This proves mathematically that the scheme is a **true 64-bit block cipher**, not a byte- or word-level XOR scheme.

#### 4.2.2 Mode of Operation: Electronic Codebook (ECB)
* In chaining or counter modes (CBC, CFB, OFB, CTR), $C_i = E_K(P_i \oplus C_{i-1})$ or $C_i = P_i \oplus E_K(\text{IV} + i)$, meaning identical plaintext blocks produce distinct pseudorandom ciphertext blocks.
* In `App1_Main.enc`, identical plaintext blocks produce identical ciphertext blocks throughout the entire 3.5 MB file:
  * Over 31.4% of all 8-byte blocks are repeats: the 437,430 total blocks condense to only **299,952 unique blocks**.
  * Top recurring blocks:
    * `6b 4c 9a 85 2c 73 28 31`: 39,814 occurrences (9.10% of the image — uncompressed `0x00` padding).
    * `fe 8c ca b9 36 3a d6 3c`: 1,897 occurrences (0.43% — repeated `0xFF` or common opcode/table sequence).
    * `45 0c eb bd 5b b9 a8 8e`: 1,611 occurrences (0.37%).
    * `e4 cf 9c e1 41 b5 d2 25`: 952 occurrences (0.22%).
    * `50 a4 69 6c a1 14 ae 30`: 799 occurrences (0.18%).

#### 4.2.3 Spatial Density & Execution Profile
Because the image is encrypted in **ECB mode without prior compression**, the density of the zero-padding block reveals the internal section layout of the firmware binary:

| Region | Zero Blocks | % of Region | Inferred ELF Section / Purpose |
| :--- | :--- | :--- | :--- |
| `0 KB - 512 KB` | 2 | ~0.0% | Executable machine code (`.text`), highly varied Thumb-2 opcodes |
| `512 KB - 768 KB` | 2,683 | 8.2% | Code / read-only jump tables and struct alignment |
| `768 KB - 1792 KB` | 0 | 0.0% | Dense binary assets or secondary code routines |
| `1792 KB - 2816 KB` | 5,828 | ~5.7% | Read-only data (`.rodata`), initialized structures (`.data`) |
| `2816 KB - 3072 KB` | 20,828 | **63.6%** | Massive BSS / zero-initialized buffer tables |
| `3072 KB - 3417 KB` | 10,473 | ~23.5% | End-of-flash alignment and unwritten sector padding |

#### 4.2.4 Hardware Decryption Context & Memory Architecture
* The Roland BMC (ESC2) system-on-chip features an on-die mask ROM bootloader.
* Physical QSPI0 Flash (`32 MB`, `0x00000000`–`0x01FFFFFF`) is partitioned as:
  * `0x00000000`: 24-byte Silicon Boot ROM master boot record.
  * `0x00002000`: `App0` (first-stage bootloader).
  * `0x00040000`: Partition 1.
  * `0x000B0000`: 256-byte `"IndivCodeIndivCo"` unit calibration/serial block.
  * `0x000C0000`: Partition 2 = `RPG69_C0A_up.bin` (`App1_Main`), flashed verbatim starting at `0x000C0000`.
* During normal boot, the Silicon Boot ROM loads `App0` into Core 0 ITCM (`0x01000000`). `App0` initializes external SDRAM (`0x60000000`–`0x61FFFFFF`), reads the `App1_Main` container from QSPI0 offset `0x000C0060`, decrypts the payload into SDRAM at `0x60000000` via the on-chip bidirectional DMA DES/3DES engine (`0x40020000`), and jumps to `0x60000000`.
* **Important Hardware CRC-32 Verification**: Function `0x6004F46C` in Core 0 verifies Partition 2 by streaming `payload_len + 0x6C = 0x35661C` bytes into the Hardware CRC32 peripheral (`0x40105000`) and matching against the IEEE 802.3 CRC-32 word (`0x0BF5EF97`) at `+0x35661C`. Any custom container packaged without a matching dynamic CRC-32 is rejected.
* **Plaintext Dump Analysis**: The dumped image [`vendor/mc101_sys_v182/dumps/c0_flash_full_clean_3.5mb.bin`](vendor/mc101_sys_v182/dumps/c0_flash_full_clean_3.5mb.bin) reflects runtime SDRAM state:
  - *Verification*: All 39,814 zero blocks in the executable/rodata segments were restored using the verified ciphertext block `6b 4c 9a 85 2c 73 28 31`.
  - *Runtime Mutation*: The writable `.data` segment (`0x602C99F4`–`0x6031279C`) contains post-boot RTOS variables, and the copy region load tail (`0x6031279C`–`0x603565B0`, containing the `.itcm`, `.sram_data`, and `0xE0043000` images) was wiped by the CRT0 `.bss` zero-init loop.

#### 4.2.5 Decryption Architecture & Tooling
The firmware payload is decrypted using 3-Key Triple-DES (3DES-ECB) with the hardware key material extracted from Silicon Boot ROM key slot `0xB6` (`0x012034C0`). Decryption is handled cleanly by [`tools/decrypt_c0a.py`](tools/decrypt_c0a.py), producing bit-perfect plaintext identical to live runtime memory. For full mathematical details on key ordering and bus word inversion, see [`docs/core0_boot_and_memory_architecture.md`](docs/core0_boot_and_memory_architecture.md).

---

## 5. Extracted Contents Inventory

All contents have been extracted into `vendor/mc101_sys_v182/extracts/` using `tools/unpack_roland_update.py`.

### 5.1 `vendor/mc101_sys_v182/extracts/RPG69_C0A/` (Main Host Application)

* **`header.bin`** (96 B): Raw binary container header.
* **`App1_Main.enc`** (3,499,440 B): The encrypted main application firmware payload.
* **`footer.bin`** (64 B): Trailer containing the 4-byte CRC-32 and ASCII build stamp.
* **`manifest.json`**: Structural metadata and parsed header fields.

### 5.2 `vendor/mc101_sys_v182/extracts/RPG69_C0C/` (Host QSPI Content - 12 Files)

Contains Zen-Core sample mappings, tone presets, drum kits, and initial system project state.

| Filename | Offset | Size (Bytes) | Checksum | Description |
| :--- | :--- | :--- | :--- | :--- |
| `tone_pcmx_cmn.bin` | `0x00001000` | 1,198,624 | `0x5dfe` | Core PCM tone definitions (e.g., "Piano 1", EP, etc.) |
| `tone_pcmEx_ky022.bin` | `0x00126000` | 749,116 | `0x88e0` | Expansion tone parameters (Set KY022) |
| `tone_pcmEx_rpg68.bin` | `0x001dd000` | 292,156 | `0xf02a` | Expansion tone parameters (MC-707 / RPG68 compatibility) |
| `tone_pcmEx_slgnd.bin` | `0x00225000` | 208,924 | `0xd425` | Expansion tone parameters (Slgnd synth bank) |
| `tone_pcmEx_snsyn.bin` | `0x00259000` | 1,809,916 | `0xcad4` | SuperNATURAL / Synth expansion tone parameters |
| `tone_pcmEx_i5080.bin` | `0x00413000` | 1,462,300 | `0xf781` | Integra-7 / XV-5080 legacy sound bank definitions |
| `kit_pcmx_cmn.bin` | `0x00579000` | 246,304 | `0x771a` | Common drum kit mapping definitions |
| `inst_pcmx_cmn.bin` | `0x005b6000` | 153,616 | `0xaa74` | Instrument preset definitions |
| `kit_pcmx_rpg68.bin` | `0x005dc000` | 196,384 | `0xb4d6` | RPG68-specific drum kit presets |
| `inst_pcmx_rpg68.bin` | `0x0060c000` | 1,552 | `0x2930` | RPG68-specific instrument definitions |
| `qspi_ver_def.h` | `0x0060d000` | 123 | `0x5235` | ASCII C-macro header defining parameter & QSPI version tags |
| `init.lzs` | `0x0060e000` | 969,045 | `0x6be9` | LZS-compressed factory default MC-101/MC-707 project (`PRJ5`/`MC77`) |

### 5.3 `vendor/mc101_sys_v182/extracts/RPG69_C1A/` (Sound Engine Application - 2 Files)

Contains uncompressed, unencrypted executable ARM code for the Zen-Core synthesis DSP engine.

| Filename | Offset | Size (Bytes) | Checksum | Architecture / Execution Details |
| :--- | :--- | :--- | :--- | :--- |
| `idm1.bin` | `0x00001000` | 241,796 | `0x348c` | **Internal Memory (ITCM) Boot Image**: ARM Cortex-M Vector table at offset `0x20` (Initial SP: `0x200a91c8` in SRAM; Reset Vector: `0x01100de5` in Thumb mode) |
| `sdram1.bin` | `0x0003d000` | 3,709,724 | `0x1dbd` | **Sound Engine & Synth Firmware**: 3.7 MB unencrypted ARM executable loaded into SDRAM. Includes the complete Zen-Core voice architecture, MFX processors, and diagnostic shell (`CQSPIDrv`, `QSPIDump`, `EZUtilRenderer`, etc.) |

### 5.4 `vendor/mc101_sys_v182/extracts/RPG69_C1C/` (Sound Engine Content - 16 Files)

Contains synthesis patch frameworks (`spf`), wavetables (`wpf`), and audio assets.

| Filename | Offset | Size (Bytes) | Checksum | Description |
| :--- | :--- | :--- | :--- | :--- |
| `wromInfo_KY022.bin` | `0x00001000` | 64 | `0x0203` | Wave-ROM configuration table |
| `tone_pcmx_test.bin` | `0x00002000` | 4,324 | `0xa6ce` | Calibration / self-test tone data |
| `metronome.bin` | `0x00004000` | 6,408 | `0x1958` | Audio PCM samples for system metronome clicks |
| `kit_pcmx_metro.bin` | `0x00006000` | 3,360 | `0x37a7` | Metronome sound kit mapping |
| `inst_pcmx_metro.bin` | `0x00007000` | 6,080 | `0x203f` | Metronome instrument definitions |
| `spf_muse_cmn.bin` | `0x00009000` | 261,968 | `0x552a` | Common sound patch framework (Muse sound engine) |
| `wpf_muse_cmn.bin` | `0x00049000` | 174,880 | `0x7589` | Common wavetable synthesis definitions |
| `spf_muse_snsyn.bin` | `0x00074000` | 97,136 | `0x5ed4` | SuperNATURAL synth patch framework |
| `wpf_muse_snsyn.bin` | `0x0008c000` | 82,368 | `0x7738` | SuperNATURAL synth wavetables |
| `spf_muse_ax_jd.bin` | `0x000a1000` | 168,672 | `0x3413` | AX / JD synth engine patch framework |
| `wpf_muse_ax_jd.bin` | `0x000cb000` | 113,968 | `0x3177` | AX / JD wavetables |
| `spf_muse_rpg68.bin` | `0x000e7000` | 231,232 | `0xa2fc` | RPG68 / MC-707 synthesis patch framework |
| `wpf_muse_rpg68.bin` | `0x00120000` | 148,528 | `0xac04` | RPG68 / MC-707 wavetables |
| `spf_muse_metro.bin` | `0x00145000` | 3,568 | `0x99be` | Metronome patch framework |
| `wpf_muse_metro.bin` | `0x00146000` | 496 | `0x7d08` | Metronome wavetables |
| `qspi_ver_def.h` | `0x00147000` | 123 | `0x5235` | Version header (identical to C0C copy) |

---

## 6. Workspace Tools & Extraction Reproduction

The extraction tool is located at [`tools/unpack_roland_update.py`](tools/unpack_roland_update.py).

To re-run the complete extraction process:

```bash
python3 tools/unpack_roland_update.py
```

The script will:
1. Verify the 32-bit CRC against the data payload of each package.
2. Unpack individual components into `vendor/mc101_sys_v182/extracts/<PARTITION_NAME>/`.
3. Output a machine-readable `manifest.json` in each folder containing parsed headers, byte offsets, and checksum values.

---

## 7. Physical Flash Memory Map & On-Chip Hardware Mapping

Live hardware probing with zero-freeze DMA client sweeps (`tools/sysex_dump_client.py`) confirmed that the MC-101 contains **48 MB total raw SPI NOR flash** across two physical Macronix chips:

### 7.1 Master Flash Chip Allocation Table

| Container Image | Physical Chip | Flash Address Range | Memory-Mapped AXI Address | Payload Size on Flash | Format & System Role |
|---|---|---|---|---|---|
| *(Silicon Header & App0)* | **Chip 0** (32 MB) | `0x00000000` – `0x000C0000` | N/A (Loaded to ITCM `0x01000000`) | 786,432 B (768 KB) | **Sector 0 & App0 Recovery**: Factory bootloader and hardware descriptor. Untouched during updates. |
| **`RPG69_C0A_up.bin`** | **Chip 0** (32 MB) | `0x000C0000` – `0x004165B0` | `0x000C0000` (Decrypted to SDRAM `0x60000000`) | 3,499,440 B (~3.34 MB) | **Core 0 OS & Main Runtime** (`App1_Main`). Encrypted binary (3DES-ECB). |
| *(Blank Erased Gap)* | **Chip 0** (32 MB) | `0x004165B0` – `0x00FFFFFF` | Open Bus | 12,491,344 B (11.91 MB) | Confirmed 100% factory erased (`0xFFFFFFFF`). Headroom for future OS expansion. |
| **`RPG69_C0C_up.bin`** | **Chip 0** (32 MB) | `0x01000000` – `0x017FFFB0` | `0x01000000` (QSPI0 FS) | 8,388,528 B (~8.00 MB) | **Core 0 Sound Assets**: Roland QSPI archive containing 12 PCM instrument banks and default project (`init.lzs`). |
| *(RPG68 SYS Descriptor)* | **Chip 0** (32 MB) | `0x01800000` – `0x0180007F` | `0x01800000` | 128 B | Hardware partition definition header (`RPG68 SYS`). |
| *(Blank Erased Top)* | **Chip 0** (32 MB) | `0x01800080` – `0x01FFFFFF` | Open Bus | 8,388,480 B (7.99 MB) | Confirmed 100% factory erased (`0xFFFFFFFF`). |
| **`RPG69_C1A_up.bin`** | **Chip 1** (16 MB) | `0x00000000` – `0x003FFF30` | `0x0C000000` – `0x0C3FFF30` | 4,194,096 B (~4.00 MB) | **Core 1 Sound Engine**: Roland QSPI archive containing `idm1.bin` (ITCM code) and `sdram1.bin` (SDRAM DSP engine). |
| **`RPG69_C1C_up.bin`** | **Chip 1** (16 MB) | `0x00400000` – `0x007FFF30` | `0x0C400000` – `0x0C7FFF30` | 4,194,096 B (~4.00 MB) | **Core 1 Synthesizer Wavetables**: Roland QSPI archive containing 16 ZEN-Core wavetable collections and patch definitions. |
| *(Blank Erased / Exp)* | **Chip 1** (16 MB) | `0x00800000` – `0x00FFFFFF` | `0x0C800000` – `0x0CFFFFFF` | 8,388,608 B (8.00 MB) | Confirmed 100% factory erased (`0xFFFFFFFF`). Includes empty reservation windows for ZEN-Core Wave Expansions `WV0` and `WV1`. |

### 7.2 Storage Utilization Summary
* **Total Physical Flash Capacity**: **48.0 MB** (Chip 0: 32 MB + Chip 1: 16 MB)
* **Occupied by Firmware & Content**: **20.1 MB** (41.9%)
* **Confirmed Factory Erased Space (`0xFF`)**: **27.9 MB** (58.1%)
* **Direct AXI Mapping**: Chip 1 is permanently mapped to `0x0C000000`–`0x0CFFFFFF` on the ESC2 internal AXI bus matrix, enabling Core 1 and DMAC1 to fetch code and samples directly without driver overhead or FIFO arbitration conflicts.
