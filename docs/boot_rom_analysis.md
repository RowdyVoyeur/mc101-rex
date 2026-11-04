# Roland BMC / ESC2 Silicon Boot ROM Analysis

**Target Platform**: Roland MC-101 Groovebox (Roland BMC / ESC2 SoC)  
**Binary Dump**: [`vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin`](vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin)  
**Dump Timestamp**: 2026-11-01 21:00  
**Extraction Method**: Zero-freeze Hardware DMA Extraction across AXI Matrix (DMAC1 Channel 1)  

---

## 1. Executive Summary

We have successfully located, probed, and completely dumped the **on-chip silicon Mask Boot ROM** of the Roland BMC (ESC2) system-on-chip.

| Attribute | Specification |
|---|---|
| **Physical Memory Base** | `0x01200000` |
| **Physical Memory Limit** | `0x01203FFF` |
| **Total ROM Size** | **16,384 bytes** (16.0 KB / 0x4000) |
| **Architecture** | ARMv7E-M (Cortex-M4 Thumb-2) |
| **SHA-256 Checksum** | `742b1dd61d07509d8c72a1c7bcf3a44b9707e72d31543e3256415eb4307e60d5` |
| **Output File** | [`vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin`](vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin) |

---

## 2. Boot Vector Table (`0x01200000`)

The silicon Boot ROM contains a native ARM Cortex-M vector table starting at `0x01200000`:

| Vector # | Offset | Vector Value | Target / Handler Name | Description |
|---|---|---|---|---|
| **0** | `+0x00` | `0x01060000` | Initial Stack Pointer (MSP) | Points into Core 0 ITCM Scratch (`0x01060000`) |
| **1** | `+0x04` | `0x012000D1` | **Reset Handler** | Initial silicon boot entry point |
| **2** | `+0x08` | `0x012000E5` | NMI Handler | Infinite loop trap (`b .`) |
| **3** | `+0x0C` | `0x012000E7` | HardFault Handler | Infinite loop trap (`b .`) |
| **4** | `+0x10` | `0x012000E9` | MemManage Handler | Infinite loop trap (`b .`) |
| **5** | `+0x14` | `0x012000EB` | BusFault Handler | Infinite loop trap (`b .`) |
| **6** | `+0x18` | `0x012000ED` | UsageFault Handler | Infinite loop trap (`b .`) |
| **7..10** | `+0x1C`..`+0x28` | `0x00000000` | Reserved | Zero padding |
| **11** | `+0x2C` | `0x012000EF` | SVCall Handler | Infinite loop trap (`b .`) |
| **12** | `+0x30` | `0x012000F1` | DebugMon Handler | Infinite loop trap (`b .`) |
| **13** | `+0x34` | `0x00000000` | Reserved | Zero padding |
| **14** | `+0x38` | `0x012000F3` | PendSV Handler | Infinite loop trap (`b .`) |
| **15** | `+0x3C` | `0x012000F5` | SysTick Handler | Infinite loop trap (`b .`) |

---

## 3. Silicon Reset Flow & Boot Mode Detection

### 3.1 Bootstrap Sequence (`0x012000D0`)
1. **Control Register Initialization**:
   ```arm
   0x012000D0:  mov.w   r0, #0
   0x012000D4:  msr     CPSR_f, r0
   0x012000D8:  msr     CONTROL, r0
   0x012000DC:  isb     sy
   ```
2. **Priority Grouping Setup**:
   Loads `0xE000ED0C` (`AIRCR`), sets priority grouping key `0x05FA` and `PRIGROUP=3`.
3. **Hardware Strapping Pin Sampling (`0x01200128`)**:
   Reads hardware strapping register at **`0x40026040`** (latched from physical SoC pins on the rising edge of `RESET_L` via Power-On Reset / POR circuitry):
   ```arm
   0x01200128:  ldr   r0, [r0, #64]       @ Read 0x40026040 (latched strapping pins)
   0x0120012A:  and.w r4, r0, #14         @ Extract bits [3:1]
   0x0120012E:  lsls  r0, r0, #26         @ Test bit 5 (strap modifier)
   0x01200130:  bpl.n 0x01200136          @ If bit 5 == 0, keep r4
   0x01200132:  subs  r4, r4, #4          @ If bit 5 == 1, r4 = r4 - 4
   0x01200134:  sxtb  r4, r4
   ```

### 3.2 Hardware Boot Mode Decoding Matrix

```
                       [ Cold Power-On Reset ]
                                  │
                       Read Pin Strap 0x40026040
                                  │
         ┌──────────────┬─────────┴─────────┬──────────────┐
         ▼              ▼                   ▼              ▼
     [Mode 4]        [Mode 6]            [Mode 8]       [Mode 10]
   QSPI Flash    USB "UD Writer"     USB "UD Boot"      UART ISP
   Normal Boot    Factory Flasher     RAM Execution    Serial Shell
 (Magic "BMC ")   (PID: 0x018F)       (PID: 0x0190)    (0x40021000)
```

| Strapping Register (`0x40026040`) | Mode Value (`r4`) | Subroutine | Boot Mode | Primary Function / Protocol |
|---|---|---|---|---|
| `Bit 5 = 0, Bits [3:1] = 2` *or* `Bit 5 = 1, Bits [3:1] = 4` | **`4`** | `0x012001F8` | **QSPI Flash Boot (Normal)** | Reads 24-byte (6-word) `'BMC '` header from physical flash offset 0, evaluates crypto flags, loads `App0` from `0x00002000` into ITCM `0x01000000`, remaps, and resets. |
| `Bit 5 = 0, Bits [3:1] = 3` *or* `Bit 5 = 1, Bits [3:1] = 5` | **`6`** | `0x012001A8` | **USB "UD Writer" Mode** | USB CDC-ACM (`0x0582:0x018F`). Listens for `"BUDW"` packets. Factory In-System SPI Flash programmer. |
| `Bit 5 = 0, Bits [3:1] = 4` *or* `Bit 5 = 1, Bits [3:1] = 6` | **`8`** | `0x012001AC` | **USB "UD Boot" Mode** | USB CDC-ACM (`0x0582:0x0190`). Listens for `"BUDB"` packets. Direct RAM code injection & execution without touching flash. |
| `Bit 5 = 0, Bits [3:1] = 5` *or* `Bit 5 = 1, Bits [3:1] = 7` | **`10`** | `0x012001B6` | **UART Serial Boot (ISP Shell)** | Primary UART (`0x40021000`). 16-command ISP monitor shell for flash/RAM read/write/erase and execution. |
| *Any other combination* | *Other* | `0x0120018A` | **Sleep / Halt Mode** | Sets `SLEEPONEXIT` on `0xE000ED10`, loops in `WFI`. |

---

### 3.3 Detailed Breakdown of Silicon Boot Modes

#### 1. Mode 4: QSPI Flash Boot (Normal Production Mode)
* **Trigger**: Strapping pins evaluate to `r4 == 4`.
* **Execution Flow (`0x012001F8`)**:
  1. Clears on-chip QSPI driver state RAM (`0x40010000`).
  2. Sets bit 24 of System Control register `0x40054000`.
  3. Reads **24 bytes (6 words)** (`movs r5, #24` at `0x01200218`) from SPI flash address `0x00000000` into stack `[sp, #0x0C..#0x20]`.
  4. Checks for container signature **`"BMC "`** (`0x20434D42` at `sp + 0x0C`):
     - **No Fallback**: If the signature does **not** match, it enters an infinite halt trap (`0x01200234: b .`).
  5. Passes Word 4 (`[sp, #0x1C]`) to `0x01203A8E`, configuring the **System PLL (`0x40054000`)** from the 12 MHz crystal and setting `SystemCoreClock` (`180,000,000`) at `0x40026030`.
  6. If extended parameters are flagged (bits 28–31 of Word 5), queries the flash chip's JEDEC Standard **SFDP** parameter tables (`"SFDP"` signature at `0x01200F6C` / `0x01202280`) to automatically configure fast read opcodes (Quad I/O `0xEB` or Dual I/O `0xBB`) and dummy cycle counts.
  7. Sets destination RAM address `r5 = 0x01000000` (Core 0 ITCM, `0x0120027A`).
  8. Evaluates crypto flags in Word 5 (`[sp, #0x20]`):
     - **Unencrypted Path** (`Word 5 & 1 == 0`): calls `0x01202CA8` to DMA-read plaintext `App0` from Flash offset `0x00002000` directly into ITCM `0x01000000`.
     - **Encrypted Path** (`Word 5 & 1 == 1`):
       - Mode `(Word 5 >> 8) & 0xFF`: `0 = Single-DES`, `1 = 2-Key 3DES`, `2 = 3-Key 3DES`.
       - Key index `(Word 5 >> 16) & 0xFF`: indexes 24-byte key entries at `0x012023B0 + key_idx * 24`.
       - Calls `rom_cipher_setup` (`0x01202604`) and `rom_flash_read_decrypted` (`0x01202C94`) to DMA-read and decrypt `App0` from Flash offset `0x00002000` into ITCM `0x01000000`.
  9. Calls `0x012025CC` (`[0x40051050] = 1`, remapping ITCM `0x01000000` to `0x00000000`), then triggers a soft reset via `0x012025EA` into `App0`.
  10. `App0` in turn initializes external SDRAM (`0x60000000`), reads the `App1_Main` container from QSPI0 offset `0x000C0060`, decrypts it into SDRAM `0x60000000`, and jumps to `0x60000000`.

#### 1.1 Hardware DES/3DES Cipher Architecture (`0x40020000`)
The Boot ROM interacts with an on-chip hardware block cipher peripheral supporting both encryption and decryption:
- **`0x40020000`**: Hardware Cipher Input FIFO (written via DMAC0 Channel 2).
- **`0x40020200`**: Hardware Cipher Output FIFO (read via DMAC0 Channel 1).
- **`0x40020400`–`0x40020414`**: Key Registers (K1, K2, K3).
- **`0x40020420`**: Cipher Control Register. Bit 0 controls direction (`0 = Encrypt`, `1 = Decrypt`, bit-band alias `0x42408400`).
- **Exported ROM APIs**:
  - `rom_cipher_setup` at `0x01202605` (exported at `0x01203F64`).
  - `rom_cipher_dma_buffer` at `0x0120283B` (exported at `0x01203F68`). Supports arbitrary memory-to-memory hardware DMA encryption and decryption.

#### 2. Mode 6: USB "UD Writer" Mode (Factory SPI Flash Programmer)
* **Trigger**: Strapping pins evaluate to `r4 == 6`.
* **USB Interface**:
  * Relocates vector table to Core 0 ITCM (`VTOR = 0x01050000`) and enables USB IRQs 20, 107, 108.
  * Enumerates as a USB CDC-ACM Virtual COM port:
    * **Vendor ID (VID)**: `0x0582` (Roland Corporation)
    * **Product ID (PID)**: `0x018F`
    * **Device Descriptor**: Communications & CDC Control (`0x02, 0x00, 0x00`)
    * **Manufacturer**: `"Roland"` (UTF-16LE)
    * **Product**: `"UD Writer"` (UTF-16LE)
    * **Buffer Address**: Uses SRAM staging buffer at `0x20020000`.
* **Capabilities & Protocol (`BUDW`)**:
  * Listens for binary packets starting with magic header **`"BUDW"`** (`0x57445542`).
  * Packet parameters:
    * `+0x04`: Destination SPI flash write offset.
    * `+0x08`: Byte count.
    * `+0x10`: Target chip select (QSPI 0 vs QSPI 1).
    * `+0x14`: SPI transfer width (Single, Dual, or Quad SPI).
  * Automatically handles SPI Flash block erases and multi-page writes.
  * Verifies flash contents against incoming stream and sends ASCII status:
    * `Verify:OK.\r\n` (`0x01203E14`)
    * `Verify:NG.\r\n` (`0x01203E20`)
  * Can issue a soft reset (`AIRCR = 0x05FA0005`) after programming.

#### 3. Mode 8: USB "UD Boot" Mode (Direct RAM Loader & Execution)
* **Trigger**: Strapping pins evaluate to `r4 == 8`.
* **USB Interface**:
  * Relocates vector table to ITCM (`VTOR = 0x01050000`).
  * Enumerates as a USB CDC-ACM Virtual COM port:
    * **Vendor ID (VID)**: `0x0582` (Roland Corporation)
    * **Product ID (PID)**: `0x0190`
    * **Manufacturer**: `"Roland"` (UTF-16LE)
    * **Product**: `"UD Boot"` (UTF-16LE)
* **Capabilities & Protocol (`BUDB`)**:
  * Listens for binary packets starting with magic header **`"BUDB"`** (`0x42445542`).
  * Packet parameters:
    * `+0x04`: Target load address in memory (e.g. ITCM `0x01000000` or SRAM `0x20000000`).
    * `+0x08`: Payload byte length.
    * `+0x0C`: **Target execution entry point address**.
  * **Capabilities**:
    * Directly stages unencrypted code into RAM over USB without modifying external SPI flash.
    * Unconditionally writes the target entry point to `0x40010154`, sets ready flag `[0x40010150] = 1`, cleanly shuts down USB IRQs, and branches via `0x01200044` to execute the uploaded code with full privileged ARM permissions.

#### 4. Mode 10: UART Serial Boot Mode (Serial ISP / Command Shell)
* **Trigger**: Strapping pins evaluate to `r4 == 10`.
* **Hardware Setup**:
  * Relocates vectors to ITCM (`VTOR = 0x01050000`).
  * Initializes primary on-chip UART controller at **`0x40021000`** with 16-level FIFO.
  * Automatically sets baud divisor from `[0x40026044]` bits [1:0] (stores `0xFF80 + 20 + bits[1:0]` in divisor register `0x40021010`).
  * Enables UART RX/TX interrupts (IRQs 24/25).
* **Capabilities & Command Table (`TBB` Table at `0x01202DF0`)**:
  Implements a 16-command interactive In-System Programming (ISP) engine:

| Opcode | Handler | Capability / Function |
|---|---|---|
| **`0x01`** | `0x01202E04` | **System Reset**: Writes `0x05FA0005` to `AIRCR` (`0xE000ED0C`) to reboot SoC. |
| **`0x02`** | `0x01202E14` | **Call / Exec**: Branches (`bx r3`) to arbitrary 32-bit address with 3 arguments (`r0`, `r1`, `r2`). |
| **`0x03`** | `0x01202E22` | **Set Address**: Sets base memory target pointer for subsequent read/write. |
| **`0x04` / `0x05`** | `0x01202E2A` | **Memory / Flash Read**: Dumps memory blocks out through UART TX FIFO. |
| **`0x06`** | `0x01202E6E` | **Memory / Flash Write**: Writes received byte payload into specified memory or flash address. |
| **`0x07`** | `0x01202E8E` | **Clock / Pin Configuration**: Selects SPI chip select / clock prescaler. |
| **`0x08`** | `0x01202E9A` | **Query Status**: Reads status byte / error flags. |
| **`0x09`** | `0x01202EA2` | **Flash Erase**: Sends block / sector / chip erase commands to SPI flash. |
| **`0x0A`** | `0x01202EC0` | **Read JEDEC ID**: Reads connected SPI Flash manufacturer/device ID (`0x9F`). |
| **`0x0D`** | `0x01202EF4` | **QSPI Configure**: Programs SFDP timing, dummy cycles, and bus mode. |
| **`0x0E`** | `0x01202ED0` | **QSPI Init**: Initializes SPI controller channel. |
| **`0x0F`** | `0x01202F2A` | **QSPI Reset**: Clears and reinitializes QSPI controller registers. |

---

### 3.4 Why the `[SHIFT]` Boot Updater Is NOT in Boot ROM
A key reverse-engineering milestone was determining why holding `[SHIFT]` at power-on boots the SD Card firmware updater (`= UPDATE =`) even when Core 0 flash is corrupt, while `vendor/mc101_sys_v182/dumps/bootrom_full_16k.bin` contains zero SD card or button code:
1. **Power-On Reset Latching**: The strapping register `0x40026040` is latched strictly by hardware pull resistors on the PCB at the rising edge of reset. Front panel buttons (scanned by the Sub-CPU) do not alter `0x40026040`.
2. **Flash Partition Architecture**: The SPI flash contains an uncorrupted first-stage bootloader partition (`App0`, located between `0x00000000` and `0x000C0000`).
3. **Execution Chain**:
   - Silicon Boot ROM boots in Mode 4 from `0x00000000`.
   - `App0` initializes the front panel button scanner / Sub-CPU link.
   - If `[SHIFT]` is held, `App0` branches directly into the SD Card update loader (`= UPDATE =`), completely bypassing the encrypted Core 0 main application (`App1_Main` at `0x000C0000`).

---

## 4. QSPI Bootloader Analysis (`0x012001F8`)

### 4.1 Physical SPI Flash Sector 0 Header (`'BMC '`)
At power-on, the Boot ROM reads 24 words (96 bytes) from physical SPI Flash offset `0x00000000`:

```arm
0x0120021A:  strd    r0, r5, [sp]         @ Flash offset = 0, length = 0x18 words (96 B)
0x01200220:  str     r0, [sp, #8]         @ Buffer = sp + 0x0C
0x01200228:  bl      0x0120196A           @ Read from SPI Flash
0x0120022C:  ldr     r1, =0x20434D42      @ Magic ASCII 'BMC '
0x0120022E:  ldr     r0, [sp, #0x0C]      @ Word 0 of Flash Header
0x01200230:  cmp     r0, r1
0x01200232:  beq     0x01200236
0x01200234:  b       0x01200234           @ HANGS in infinite loop if Word 0 != 'BMC '
```

### 4.2 Decoded 24-Word Physical Flash Header Format

| Word # | Offset in Header | Name | Description in Boot ROM |
|---|---|---|---|
| **0** | `+0x00` | **Magic** | Must be ASCII `'BMC '` (`0x20434D42`), otherwise CPU enters infinite loop `b .` |
| **1** | `+0x04` | Reserved | Reserved / ignored by bootloader |
| **2** | `+0x08` | **Source Offset** | 32-bit physical Flash source address for binary payload |
| **3** | `+0x0C` | **Payload Length** | 32-bit byte size of binary payload |
| **4** | `+0x10` | **Hardware Model ID** | Checked at `0x01200238` against hardware strap register `0x40054000` |
| **5** | `+0x14` | **Crypto Control Word** | Controls SFDP profile, execution flags, and encryption mode |

### 4.3 Branching Logic on Word 5 (Crypto Control Word)

1. **SFDP / Timing Profile**:
   ```arm
   0x01200242:  tst.w    r0, #0x0F000000      @ Check bits [27:24]
   0x01200246:  beq      0x01200278           @ Skip SFDP if zero
   0x01200264:  bl       0x012021EA           @ Execute JEDEC SFDP configuration
   ```

2. **Decryption Enable Check**:
   ```arm
   0x01200278:  ldr      r0, [sp, #0x20]      @ Load Word 5 from header
   0x0120027A:  mov.w    r5, #0x01000000      @ Destination: Core 0 ITCM (0x01000000)
   0x0120027E:  lsls     r0, r0, #28          @ Test bits [3:0]
   0x01200280:  beq      0x012002CC           @ IF ZERO: Direct Unencrypted Boot!
   ```

3. **Branch A: Encrypted Execution Path (Bits [3:0] != 0)**:
   - `0x012002AE: bl 0x01202604`: Programs hardware cryptographic keys into `0x40020400` / `0x40020200` using slot index from bits `[23:16]` and mode from bits `[15:8]`.
   - `0x012002C6: bl 0x01202C94`: Validates cryptographic signature token.
   - Core 0 executes in-place via hardware on-the-fly decryption (XIP).

4. **Branch B: Unencrypted Direct DMA Boot Path (Bits [3:0] == 0)**:
   - Skips `0x01202604` (cipher keys remain uninitialized).
   - Skips `0x01202C94` (no signature check).
   - `0x012002DC: bl 0x0120196A`: DMA-reads payload directly from SPI Flash (`Word 2`) into Core 0 ITCM (`0x01000000`).
   - `0x012002E2: bl 0x012025CC`: Sets boot status flag in `0x40051050`.
   - `0x012002E6: bl 0x012025EA`: Triggers soft reset via `AIRCR` (`0xE000ED0C`) to boot Core 0 with `VTOR = 0x01000000`.

---

## 5. Critical Distinction: 'BMC ' Sector 0 vs 'App1_Main' Container

`RPG69_C0A_up.bin` is **NOT** physical Flash Sector 0. It is an update container for the `App1_Main` partition written to SPI flash offset `0x000C0000`:
- **`RPG69_C0A_up.bin` Header**: Starts with `"App1_Main"`, Word 21 is `0xB6020001` (at `+0x54`), Word 20 is `0x513FC2D9`.
- **Silicon Boot ROM Header**: Reads from `0x00000000`, requires magic `'BMC '` at `+0x00`, reads control word from Word 5 (`+0x14`).
- Physical SPI Flash Sector 0 resides at `0x00000000`–`0x000BFFFF` (`physical_sector0_768k.bin`). Updating `RPG69_C0A_up.bin` updates the `App1_Main` partition at `0x000C0000`, but does not alter physical Sector 0.
- For complete end-to-end memory map and interaction analysis, see the master reference: [`docs/system_architecture_and_boot_flow.md`](docs/system_architecture_and_boot_flow.md).

---

## 6. Cryptographic Evaluation & Master Key Table

### 6.1 Master Key Setup Subroutine (`0x01202604`)
During Mode 4 (QSPI Boot), if Word 5 bits `[3:0] != 0`, the Boot ROM calls `0x01202604`:
- Takes key slot index in bits `[23:16]` and mode flags in bits `[15:8]`.
- Programs the hardware DES/Triple-DES key registers at `0x40020400` / `0x40020200`.
- Programs the OTFDEC decryption address boundary registers (configured via `0x0120283A`).

### 6.2 Cryptographic Key Derivation: The 3DES Master Key Table (`0x012023B0`)
- **Key Table Location**: The Boot ROM maintains the 24-byte-per-slot 3DES master key table starting at **`0x012023B0`**.
- **Table Indexing**:
  $$\text{Key Address} = 0x012023B0 + (\text{Key Index} \times 24)$$
  For `RPG69_C0A_up.bin` (Key Index `0xB6` = 182), the 24-byte slice is located at **`0x012034C0`**.
- **Why Naive Searches Failed**:
  1. The cipher is **3-Key 3DES (Triple DES)**, not Single DES.
  2. The hardware DES peripheral in decrypt mode reverses key order ($K_1 = [w_4, w_5], K_2 = [w_2, w_3], K_3 = [w_0, w_1]$).
  3. The hardware AXI DMA FIFO requires 32-bit word swapping ($[W_1 : W_0]$) for each 64-bit DES block.
- **Verification**: Decrypting `vendor/mc101_sys_v182/RPG69_C0A_up.bin` yields [`vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin`](vendor/mc101_sys_v182/extracts/RPG69_C0A/App1_Main_decrypted.bin) with a **100.0000% bit-perfect match** against live SDRAM text and live ITCM fast code, while restoring all pre-boot `.data` and `.itcm` load regions.
