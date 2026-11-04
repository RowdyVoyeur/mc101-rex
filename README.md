# Roland MC-101 Firmware & Hardware Reverse Engineering (v1.82)

Reverse engineering documentation, firmware analysis tools, and memory dumper payloads for the Roland MC-101 groovebox (symmetrical dual-core ARM Cortex-M4 architecture: Core 0 host processor and Core 1 sound engine).

---

## Prerequisites

- **Python 3** with `capstone` and `pycryptodomex`:
  ```bash
  pip install capstone pycryptodomex
  ```
- **ARM GNU Toolchain** (`arm-none-eabi-as`, `arm-none-eabi-ld`, `arm-none-eabi-objcopy`):
  ```bash
  sudo apt install binutils-arm-none-eabi gcc-arm-none-eabi
  ```

---

## Setup & Building the Patched Firmware

### 1. Download Stock Firmware Update
Download the official **MC-101 System Program Version 1.82** archive (`mc101_sys_v182.zip`) from Roland:
- [Roland MC-101 Updates & Drivers](https://www.roland.com/global/support/by_product/mc-101/updates_drivers/)

### 2. Extract into Vendor Directory
Create the target directory and extract the archive:
```bash
mkdir -p vendor/mc101_sys_v182
unzip mc101_sys_v182.zip -d vendor/mc101_sys_v182/
```

Verify that the vendor directory contains the update binaries:
- `vendor/mc101_sys_v182/RPG69_C0A_up.bin`
- `vendor/mc101_sys_v182/RPG69_C0C_up.bin`
- `vendor/mc101_sys_v182/RPG69_C1A_up.bin`
- `vendor/mc101_sys_v182/RPG69_C1C_up.bin`

### 3. Generate the Patched Image
Run the firmware patcher:
```bash
python3 tools/patch_reader_firmware.py
```

This assembles `src/sysex_hook.s`, injects the SysEx memory and QSPI dumper hook into the unused ITCM padding of `RPG69_C1A_up.bin`, updates the QSPI TOC entry checksum, and recalculates the CRC-32 trailer.

The resulting patched update file is written to:
```
build/RPG69_C1A_up.bin
```

---

## Installing on the Device

To install the patched Core 1 sound engine image onto the MC-101:

1. Copy `build/RPG69_C1A_up.bin` to the root directory of an SD card.
2. Insert the SD card into the MC-101 while powered off.
3. Hold `[SHIFT]` and power on the MC-101 to enter update mode (`==== update ====`).
4. The on-screen prompts will show the progress of the update.

---

## Extracting Memory and ROM Dumps

Once the MC-101 is running the patched firmware, connect the device to your PC via USB and ensure it is powered on in normal operating mode (with the USB driver set to Generic / Vendor mode that exposes USB-MIDI).

Ensure you have access to the ALSA RawMIDI device (typically `/dev/snd/midiC1D0`).

### 1. Extract the Silicon Mask Boot ROM (16 KB)
The on-chip Boot ROM is mapped at `0x01200000 - 0x01203FFF`:
```bash
python3 tools/sysex_dump_client.py --target bootrom --out vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin --no-resume
```
Expected SHA-256 hash:
`2ac61a90d721a87753917c49fde45df2703e03fdaf6301adb00456093759d0b2`

### 2. Extract Physical SPI Flash Sector 0 (768 KB)
Physical Flash Sector 0 contains the Stage 1 bootloader (`BMC 0.10`), device calibration, individual ID code, and Stage 2 update binary (`App0_UPD`):
```bash
python3 tools/sysex_dump_client.py --dump-sector0
```
This dumps 786,432 bytes directly to:
`vendor/mc101_sys_v182/dumps/physical_sector0_768k.bin`

---

## Unpacking and Decrypting Vendor Firmware

### 1. Extract All Four Containers
Unpack all stock vendor update containers (`vendor/mc101_sys_v182/*.bin`) into subdirectories under `vendor/mc101_sys_v182/extracts`:

```bash
python3 tools/unpack_roland_update.py
```

This unpacks each container and generates manifest metadata:
- `vendor/mc101_sys_v182/extracts/RPG69_C0A/`: Core 0 host processor application container (`header.bin`, `App1_Main.enc`, `footer.bin`, `manifest.json`)
- `vendor/mc101_sys_v182/extracts/RPG69_C0C/`: System samples, PCM sound expansions, and instruments (`init.lzs`, `tone_*.bin`, `kit_*.bin`, `inst_*.bin`, `manifest.json`)
- `vendor/mc101_sys_v182/extracts/RPG69_C1A/`: Core 1 sound engine executable components (`idm1.bin`, `sdram1.bin`, `manifest.json`)
- `vendor/mc101_sys_v182/extracts/RPG69_C1C/`: Metronome samples, synth tone wavepools, and preset filters (`wpf_*.bin`, `spf_*.bin`, `manifest.json`)

### 2. Decrypt App1_Main.enc
After extracting the containers and dumping the Silicon Mask Boot ROM (`vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin`), decrypt the encrypted Core 0 payload (`App1_Main.enc`):

```bash
python3 tools/decrypt_c0a.py \
    --input vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main.enc \
    --bootrom vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin \
    --output vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin
```

This dynamically derives the 3DES cryptographic key from the Silicon Boot ROM master key table (offset `0x012023B0`, slot index `0xB6` latched from `header.bin`) without hardcoding keys in the source code, producing a pristine decrypted ARM binary (3,499,440 bytes) matching live SDRAM execution.

---

## Unpacking and Decrypting Physical Flash Sector 0

Once Sector 0 has been extracted to `vendor/mc101_sys_v182/dumps/physical_sector0_768k.bin`, unpack its 4 primary regions and decrypt the embedded `App0_UPD` recovery updater:

```bash
python3 tools/unpack_sector0.py
```

This extracts into `vendor/mc101_sys_v182/extracts/sector0/`:
1. `part1_reset_vectors.bin`: Initial Cortex-M4 vector table and bootstrap stub (8 KB)
2. `part2_app0_bootloader.bin`: Primary unencrypted bootloader `RPG69_C0L` (`BMC 0.10`, 16.25 KB)
3. `part3_App0_UPD_up.bin`: Encrypted recovery updater container `RPG69_C0U` (198.9 KB)
4. `part4_indiv_code.bin`: Unit serial number, board ID, and hardware ADC calibration block (64 KB)

The script then unpacks `part3_App0_UPD_up.bin` into `vendor/mc101_sys_v182/extracts/sector0/App0_UPD/` (`header.bin`, `App0_UPD.enc`, `footer.bin`) and decrypts the payload using the Silicon Boot ROM key table at slot index `0xB5`, generating `App0_UPD_decrypted.bin` (198,736 bytes).

---

## Building Patched Core 0 Firmware (Custom LCD Boot Splash)

After unpacking containers and decrypting `App1_Main.enc` to `vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin`, you can generate a patched, unencrypted Core 0 update container:

```bash
python3 tools/patch_boot_string.py
```

This tool:
1. Patches the LCD boot splash format string at offset `0x0004F1C4` (from `"        Ver.%4s"` to `"r/MC707 Ver.%4s"`).
2. Recalculates the internal payload CRC-32 token (Word 20).
3. Packages the modified binary into an **unencrypted Roland update container** using control word `0x00000000` (which instructs the bootloader to bypass hardware 3DES cipher decryption and DMA-load the code directly into SDRAM).
4. Recalculates the container trailer IEEE 802.3 CRC-32 and writes the ready-to-flash update file to:
   ```
   build/RPG69_C0A_up.bin
   ```

To flash this custom Core 0 host build onto the device, copy `build/RPG69_C0A_up.bin` to the root of an SD card, insert it into the MC-101, hold `[SHIFT]`, and power on into update mode.

---

## License

Copyright 2026 Ed Coffey

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.

