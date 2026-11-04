# Roland MC-101 Hardware Memory & Bus Probe Results

**Date Generated**: 2026-11-01 18:06:03

## Summary Table

| Target Region | Base Address | Status | Faults (out of 14) | First 4 Words Read / Observations | Description |
|---|---|---|---|---|---|
| Range A: ITCM Base / Vector Table | `0x00000000` | ✅ ONLINE | 0/14 | `200A91C8 01100DE5 01100E55 0113B43D` | Core 1 Vector Table & ITCM Base |
| Range A: ITCM Middle | `0x00020000` | ✅ ONLINE | 0/14 | `428868A1 B662D301 68A0BD10 E7FA60E0` | Core 1 ITCM Midpoint (128 KB) |
| Range A: ITCM Upper Boundary | `0x0003FFC0` | ✅ ONLINE | 0/14 | `3D56FE9A 76AEC601 A783EABE F0E75BB1` | Core 1 ITCM Upper Boundary (256 KB limit) |
| Range B: Silicon Boot ROM | `0x01200000` | ✅ ONLINE | 0/14 | `01060000 012000D1 012000E5 012000E7` | On-chip Silicon Boot ROM (16 KB, SFDP, UD Boot) |
| Range B: Boot ROM Boundary | `0x01204000` | ⚠️ TIMEOUT | 14/14 | `[UNMAPPED / TIMEOUT]` | Confirms Mask ROM decode ends strictly at 16 KB (0x01203FFF) |
| Range B: Core 0 ITCM Base | `0x01000000` | ✅ ONLINE | 0/14 | `01050800 60000001 01005D9D 01005D9F` | Core 0 Vector Table & ITCM Base (512 KB) |
| Range B: Core 0 / Shared Boot Seg | `0x01140000` | ✅ ONLINE | 0/14 | `00000000 0114077C 01140000 DA3776D0` | Auxiliary boot segment / interconnect mailbox |
| Range B: Chip 1 Direct AXI Aperture | `0x0C000000` | ✅ ONLINE | 0/14 | `003FFF30 00000000 00000000 00000000` | Direct AXI mapping of 16 MB Chip 1 NOR Flash (`C1A` at 0x0C000000) |
| Range C: SYSCTRL / CRM | `0x40000000` | ✅ ONLINE | 0/14 | `00000000 00000000 00000000 00000000` | System Controller / Clock / Reset Management |
| Range C: DMAC1 Controller | `0x40001000` | ✅ ONLINE | 0/14 | `80000000 00000000 00000000 00000000` | SoC DMA Controller Channel Registers |
| Range C: Reserved / Peripheral | `0x40003000` | ✅ ONLINE | 0/14 | `00000000 00000000 00000000 00000000` | System Peripheral / Bridge |
| Range C: Cipher Engine Registers | `0x40030000` | ✅ ONLINE | 0/14 | `80000000 00000000 00000000 00000000` | Hardware cryptographic / cipher engine |
| Range C: System Info & IndivCode | `0x40004000` | ✅ ONLINE | 0/14 | `00000011 007F0500 007F0500 007F0500` | System Info, "1.82-BLD.144", IndivCode security registers |
| Range C: System Config Interconnect | `0x40005000` | ✅ ONLINE | 0/14 | `00000018 00000400 000060C0 00000000` | System config / bus interconnect (0x60000000 flash remap) |
| Range C: QSPI0 Memory Controller | `0x40010000` | ✅ ONLINE | 0/14 | `40010090 00000000 00000000 00000000` | QSPI0 Flash Controller (Dual CS, 4.09MB boundary) |
| Range C: QSPI1 Memory Controller | `0x40020000` | ✅ ONLINE | 0/14 | `00000000 00000000 00000000 00000000` | QSPI1 Flash Controller |
| Range C: Aux Memory Controller 1 | `0x40024000` | ✅ ONLINE | 0/14 | `0000D2F0 00000000 00000003 00000000` | Auxiliary memory controller 0x40024000 |
| Range C: Aux Memory Controller 2 | `0x40026000` | ✅ ONLINE | 0/14 | `00010131 00000000 00000000 00000000` | Auxiliary memory controller 0x40026000 |
| Range D: Shared SDRAM Core 0 Exec | `0x60000000` | ✅ ONLINE | 0/14 | `680148AE 02FFF64F 0102EA01 EA414AAC` | Decrypted QSPI Flash CRT0 & App1_Main |
| Range D: Shared SDRAM Core 1 Exec | `0x61000000` | ✅ ONLINE | 0/14 | `F802F000 FA26F07D E890A00A 44820C00` | Core 1 `sdram1.bin` ZEN-Core Engine entry point |
| Range D: Shared SDRAM 32MB Mirror | `0x62000000` | ✅ ONLINE | 0/14 | `680148AE 02FFF64F 0102EA01 EA414AAC` | Exact wrap-around mirror of 0x60000000 (32 MB physical SDRAM) |
| Range D: Shared SDRAM 32MB Mirror | `0x63000000` | ✅ ONLINE | 0/14 | `F802F000 FA26F07D E890A00A 44820C00` | Exact wrap-around mirror of 0x61000000 (32 MB physical SDRAM) |
| Range E: Unpopulated Bus Window | `0x80000000` | ⚠️ FLOATING | 0/14 | `FFFFFFFF FFFFFFFF FFFFFFFF FFFFFFFF` | Unpopulated bus aperture (floating pull-ups, not SDRAM) |

## Detailed Word Dumps for Active Regions

### Range A: ITCM Base / Vector Table (`0x00000000`)
- **Description**: Core 1 Vector Table & ITCM Base
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x00000000): 0x200A91C8 (537563592)
+0x04 (0x00000004): 0x01100DE5 (17829349)
+0x08 (0x00000008): 0x01100E55 (17829461)
+0x0C (0x0000000C): 0x0113B43D (18068541)
+0x10 (0x00000010): 0x0113B43D (18068541)
+0x14 (0x00000014): 0x0113B43D (18068541)
+0x18 (0x00000018): 0x01100E5D (17829469)
+0x1C (0x0000001C): 0x00000000 (0)
+0x20 (0x00000020): 0x00000000 (0)
+0x24 (0x00000024): 0x00000000 (0)
+0x28 (0x00000028): 0x00000000 (0)
+0x2C (0x0000002C): 0x01100E5F (17829471)
+0x30 (0x00000030): 0x01100E61 (17829473)
+0x34 (0x00000034): 0x00000000 (0)
```

### Range A: ITCM Middle (`0x00020000`)
- **Description**: Core 1 ITCM Midpoint (128 KB)
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x00020000): 0x428868A1 (1116235937)
+0x04 (0x00020004): 0xB662D301 (3059929857)
+0x08 (0x00020008): 0x68A0BD10 (1755364624)
+0x0C (0x0002000C): 0xE7FA60E0 (3891945696)
+0x10 (0x00020010): 0x680A491C (1745504540)
+0x14 (0x00020014): 0x429A684B (1117415499)
+0x18 (0x00020018): 0x2000BF04 (536919812)
+0x1C (0x0002001C): 0xB6724770 (3060942704)
+0x20 (0x00020020): 0x684B4A19 (1749764633)
+0x24 (0x00020024): 0x70025CD2 (1879203026)
+0x28 (0x00020028): 0x1C406848 (473983048)
+0x2C (0x0002002C): 0x0008F3C0 (586688)
+0x30 (0x00020030): 0x68886048 (1753768008)
+0x34 (0x00020034): 0x60881E40 (1619533376)
```

### Range A: ITCM Upper Boundary (`0x0003FFC0`)
- **Description**: Core 1 ITCM Upper Boundary (256 KB limit)
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x0003FFC0): 0x3D56FE9A (1029111450)
+0x04 (0x0003FFC4): 0x76AEC601 (1991165441)
+0x08 (0x0003FFC8): 0xA783EABE (2810440382)
+0x0C (0x0003FFCC): 0xF0E75BB1 (4041694129)
+0x10 (0x0003FFD0): 0x273B8BAB (658213803)
+0x14 (0x0003FFD4): 0x08999234 (144282164)
+0x18 (0x0003FFD8): 0xC6D9A85B (3336153179)
+0x1C (0x0003FFDC): 0xF54F3815 (4115609621)
+0x20 (0x0003FFE0): 0xCBDB978C (3420166028)
+0x24 (0x0003FFE4): 0x9433520B (2486391307)
+0x28 (0x0003FFE8): 0x1892B73F (412268351)
+0x2C (0x0003FFEC): 0x6F0CC24E (1863107150)
+0x30 (0x0003FFF0): 0xF48DB71D (4102928157)
+0x34 (0x0003FFF4): 0x0A8B976C (176920428)
```

### Range C: SYSCTRL / CRM (`0x40000000`)
- **Description**: System Controller / Clock / Reset Management
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x40000000): 0x00000000 (0)
+0x04 (0x40000004): 0x00000000 (0)
+0x08 (0x40000008): 0x00000000 (0)
+0x0C (0x4000000C): 0x00000000 (0)
+0x10 (0x40000010): 0x00000001 (1)
+0x14 (0x40000014): 0x00000000 (0)
+0x18 (0x40000018): 0x00000000 (0)
+0x1C (0x4000001C): 0x00000000 (0)
+0x20 (0x40000020): 0x055FF00F (90173455)
+0x24 (0x40000024): 0x055FF00F (90173455)
+0x28 (0x40000028): 0x055FF00F (90173455)
+0x2C (0x4000002C): 0x055FF00F (90173455)
+0x30 (0x40000030): 0x055FF00F (90173455)
+0x34 (0x40000034): 0x055FF00F (90173455)
```

### Range C: DMAC1 Controller (`0x40001000`)
- **Description**: SoC DMA Controller Channel Registers
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x40001000): 0x80000000 (2147483648)
+0x04 (0x40001004): 0x00000000 (0)
+0x08 (0x40001008): 0x00000000 (0)
+0x0C (0x4000100C): 0x00000000 (0)
+0x10 (0x40001010): 0x13800000 (327155712)
+0x14 (0x40001014): 0x0A800000 (176160768)
+0x18 (0x40001018): 0x40004090 (1073758352)
+0x1C (0x4000101C): 0x6073BE24 (1618198052)
+0x20 (0x40001020): 0x00800000 (8388608)
+0x24 (0x40001024): 0x0A000000 (167772160)
+0x28 (0x40001028): 0x400621CC (1074143692)
+0x2C (0x4000102C): 0x603A4A9C (1614432924)
+0x30 (0x40001030): 0x00800000 (8388608)
+0x34 (0x40001034): 0x09000000 (150994944)
```

### Range C: System Config Interconnect (`0x40005000`)
- **Description**: System config / bus interconnect
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x40005000): 0x00000018 (24)
+0x04 (0x40005004): 0x00000400 (1024)
+0x08 (0x40005008): 0x000060C0 (24768)
+0x0C (0x4000500C): 0x00000000 (0)
+0x10 (0x40005010): 0x00000100 (256)
+0x14 (0x40005014): 0x00000001 (1)
+0x18 (0x40005018): 0x00000900 (2304)
+0x1C (0x4000501C): 0x00000000 (0)
+0x20 (0x40005020): 0x00000920 (2336)
+0x24 (0x40005024): 0x00000000 (0)
+0x28 (0x40005028): 0x00000920 (2336)
+0x2C (0x4000502C): 0x00000000 (0)
+0x30 (0x40005030): 0x00000900 (2304)
+0x34 (0x40005034): 0x00000000 (0)
```

### Range C: QSPI0 Memory Controller (`0x40010000`)
- **Description**: QSPI0 Flash Controller (OTFDEC boundary registers)
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x40010000): 0x40010090 (1073807504)
+0x04 (0x40010004): 0x00000000 (0)
+0x08 (0x40010008): 0x00000000 (0)
+0x0C (0x4001000C): 0x00000000 (0)
+0x10 (0x40010010): 0x00000000 (0)
+0x14 (0x40010014): 0x00000001 (1)
+0x18 (0x40010018): 0x00000000 (0)
+0x1C (0x4001001C): 0x00000000 (0)
+0x20 (0x40010020): 0x00000000 (0)
+0x24 (0x40010024): 0x00000000 (0)
+0x28 (0x40010028): 0x40004000 (1073758208)
+0x2C (0x4001002C): 0x42080000 (1107820544)
+0x30 (0x40010030): 0x40001000 (1073745920)
+0x34 (0x40010034): 0x00000000 (0)
```

### Range C: QSPI1 Memory Controller (`0x40020000`)
- **Description**: QSPI1 Flash Controller
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x40020000): 0x00000000 (0)
+0x04 (0x40020004): 0x00000000 (0)
+0x08 (0x40020008): 0x00000000 (0)
+0x0C (0x4002000C): 0x00000000 (0)
+0x10 (0x40020010): 0x00000000 (0)
+0x14 (0x40020014): 0x00000000 (0)
+0x18 (0x40020018): 0x00000000 (0)
+0x1C (0x4002001C): 0x00000000 (0)
+0x20 (0x40020020): 0x00000000 (0)
+0x24 (0x40020024): 0x00000000 (0)
+0x28 (0x40020028): 0x00000000 (0)
+0x2C (0x4002002C): 0x00000000 (0)
+0x30 (0x40020030): 0x00000000 (0)
+0x34 (0x40020034): 0x00000000 (0)
```

### Range C: Aux Memory Controller 1 (`0x40024000`)
- **Description**: Auxiliary memory controller 0x40024000
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x40024000): 0x0000D2F0 (54000)
+0x04 (0x40024004): 0x00000000 (0)
+0x08 (0x40024008): 0x00000003 (3)
+0x0C (0x4002400C): 0x00000000 (0)
+0x10 (0x40024010): 0x00000000 (0)
+0x14 (0x40024014): 0x00000000 (0)
+0x18 (0x40024018): 0x0000D2F0 (54000)
+0x1C (0x4002401C): 0x00000000 (0)
+0x20 (0x40024020): 0x00000000 (0)
+0x24 (0x40024024): 0xFFFFFFFF (4294967295)
+0x28 (0x40024028): 0x00000020 (32)
+0x2C (0x4002402C): 0x00000000 (0)
+0x30 (0x40024030): 0x00000000 (0)
+0x34 (0x40024034): 0x00000000 (0)
```

### Range C: Aux Memory Controller 2 (`0x40026000`)
- **Description**: Auxiliary memory controller 0x40026000
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x40026000): 0x00010131 (65841)
+0x04 (0x40026004): 0x00000000 (0)
+0x08 (0x40026008): 0x00000000 (0)
+0x0C (0x4002600C): 0x00000000 (0)
+0x10 (0x40026010): 0x00000111 (273)
+0x14 (0x40026014): 0x00000000 (0)
+0x18 (0x40026018): 0x00000000 (0)
+0x1C (0x4002601C): 0x00000000 (0)
+0x20 (0x40026020): 0x00000000 (0)
+0x24 (0x40026024): 0x00000000 (0)
+0x28 (0x40026028): 0x00000000 (0)
+0x2C (0x4002602C): 0x00000000 (0)
+0x30 (0x40026030): 0x0ABA9500 (180000000)
+0x34 (0x40026034): 0x00000000 (0)
```

### Range C: Reserved / Peripheral Bridge (`0x40003000`)
- **Description**: System Peripheral / Bridge
- **Fault Bitmap**: `0x0000`
```
+0x00 (0x40003000): 0x00000000 (0)
+0x04 (0x40003004): 0x00000000 (0)
+0x08 (0x40003008): 0x00000000 (0)
+0x0C (0x4000300C): 0x00000000 (0)
+0x10 (0x40003010): 0x00000000 (0)
+0x14 (0x40003014): 0x00000000 (0)
+0x18 (0x40003018): 0x00000000 (0)
+0x1C (0x4000301C): 0x00000000 (0)
+0x20 (0x40003020): 0x00000000 (0)
+0x24 (0x40003024): 0x00000000 (0)
+0x28 (0x40003028): 0x00000000 (0)
+0x2C (0x4000302C): 0x00000000 (0)
+0x30 (0x40003030): 0x00000000 (0)
+0x34 (0x40003034): 0x00000000 (0)
```

### Range C: System Info & Security / IndivCode (`0x40004000` – `0x400040EC`)
- **Description**: Silicon Info, Build Strings, and Individual Security Code Block
- **Fault Bitmap**: `0x0000` (Word range `+0x00` through `+0xEC` active)
- **Key Discoveries**:
  - `+0x14`: `'R'`, `+0x20`: `'r'`
  - `+0x90`–`+0xAC`: Firmware Build String: `"1.82-BLD.144 23 0517 22 54 58"` (Build timestamp 2023-05-17 22:54:58)
  - `+0xB0`–`+0xB4`: Memory subsystem labels: `"qspi"`, `"pcmx"`
  - `+0xC0`–`+0xCC`: Security signature: `"IndivCodeIndivCode"`
  - `+0xD0`: `0x000B0100`, `+0xD4`: `0x0000FFFF` (Hardware security & configuration bits)
  - **Peripheral Boundary**: Register decode ends strictly at `0x400040EC` (240 bytes). Access at `0x400040F0` stalls APB bridge (`PREADY` undriven).

### Range C: System Config Interconnect Extended (`0x40005038` – `0x400050A4`)
- **Description**: Extended bus routing and aperture remap registers
- **Fault Bitmap**: `0x0000`
```
+0x38: 0x00000720
+0x3C: 0x00000080
+0x40: 0x00000310
+0x44: 0x00008300
+0x48: 0x000001FF
+0x4C: 0x00000200
+0x50: 0x000040E6
+0x58: 0x00002000
+0x60: 0x00000F0C
+0x6C: 0x00000002
+0x70: 0x0000C007
+0x80: 0x0000003F
+0x84: 0x0000002A
```

### Range C: QSPI0 Flash Controller Extended (`0x40010038` – `0x4001014C`)
- **Description**: Complete dual-chip-select QSPI flash controller profiles
- **Fault Bitmap**: `0x0000`
- **Register Map**:
  - `+0x44`: `0x00416638` (Total Flash boundary: 4,286,008 bytes ~ 4.09 MB)
  - `+0x48`: `0x400100E0` (Chip Select 1 profile pointer)
  - `+0x70`: `0x40032000`, `+0x74`: `0x42640000`, `+0x78`: `0x40030000` (Links to auxiliary cipher engine)
  - **Chip Select 0 Profile (`0x40010090` – `0x400100DC`)**:
    - `+0x90`: `0x000000C2` (Macronix Manufacturer ID)
    - `+0x98`: `0x000000EB` (Fast Read Quad I/O Opcode)
    - `+0xA0`: `0x00000006` (Write Enable Opcode)
    - `+0xB0`: `0x00000100` (Page Program: 256 bytes)
    - `+0xCC`: `0x00010000` (Block Size: 64 KB)
    - `+0xD0`: `0x000000D8` (Block Erase 64KB Opcode)
  - **Chip Select 1 Profile (`0x400100E0` – `0x4001012C`)**:
    - `+0xE0`: `0x000000C2`
    - `+0xE8`: `0x000000EB`
    - `+0xF0`: `0x00000006`
    - `+0x100`: `0x00000100`
    - `+0x11C`: `0x00010000`
    - `+0x120`: `0x000000D8`
```


---

## Key Hardware Findings & Architectural Realities

1. **Core 1 CPU Core**:
   - `CPUID` read via `--read-sys-regs`: `0x410FC241` (**ARM Cortex-M4 r0p1**). Core 1 is an ARM Cortex-M4, not a Cortex-M7.
   - Core 1 uses Harvard bus separation (ICode/DCode for ITCM below `0x20000000`, System Bus for SRAM/peripherals). Direct CPU `ldr` instructions to unmapped addresses in the ITCM window (such as `0x0007FFC0`) trigger immediate CPU bus lockups.
2. **Core 0 CPU Core**:
   - `CPUID` read via inter-core SysTick dynamic code injection (`--core0-inspect`): `0x410FC241` (**ARM Cortex-M4 r0p1**).
   - Core 0 is also an ARM Cortex-M4 r0p1. The Roland BMC / ESC2 SoC is a symmetrical dual-core ARM Cortex-M4 architecture.
   - Verified registers: `CPUID = 0x410FC241`, `VTOR = 0x01000000`, `ICSR = 0x0040000F` (active SysTick exception), `ITCMCR = 0`, `DTCMCR = 0`, `AHBPCR = 0`, `CACR = 0`.
3. **APB Bridge Boundaries**:
   - The System Info block at `0x40004000` decodes strictly from `0x40004000` to `0x400040EC`. Accessing `0x400040F0` permanently undrives `PREADY` and stalls the APB bridge.
   - `0x40030000` requires specific clocking / enable flags; un-clocked direct access stalls the APB bus bridge.
4. **Hardware-Safe Probing Methodology**:
   - Using DMAC1 Channel 1 (`cmd_dma_probe_chunk` / Velocity 26) across the AXI matrix eliminates all risk of CPU bus lockups, enabling safe sweeps of unknown peripheral spaces with automatic 2.5 ms software timeouts.
