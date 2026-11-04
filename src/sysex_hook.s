/*
 * Copyright 2026 Ed Coffey
 *
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

.syntax unified
.thumb
.cpu cortex-m4

/*
 * Core 1 SysEx & Memory Dumper Hook for Roland MC-101 / ESC2 SoC
 *
 * Injected into idm1.bin zero padding at 0x0113B04C.
 * Intercepts MIDI Note 127 messages to provide arbitrary AXI memory dumping,
 * physical QSPI flash reading, fault-tolerant safe bus probing, and Core 0 inspection.
 */

.global hook_entry
hook_entry:
    @ Maintain 8-byte stack alignment: 8 registers * 4 bytes = 32 bytes
    push.w  {r4, r5, r6, r7, r8, r9, r10, lr}

    @ 1. Opcode: Note On (9)
    ubfx    r1, r0, #12, #4
    cmp     r1, #9
    bne     pass_through

    @ 2. Pitch: Note 127
    ubfx    r1, r0, #16, #8
    cmp     r1, #127
    bne     pass_through

    @ Extract velocity [0..127]
    ubfx    r2, r0, #24, #8

    @ Check command velocities
    cmp     r2, #15
    beq     cmd_set_addr
    cmp     r2, #20
    beq     cmd_sysex_slice
    cmp     r2, #21
    beq     cmd_probe_dma_regs
    cmp     r2, #22
    beq     cmd_test_dma_c1
    cmp     r2, #23
    beq     cmd_test_dma_c0_identity
    cmp     r2, #24
    beq     cmd_safe_probe_chunk
    cmp     r2, #25
    beq     cmd_read_sys_regs
    cmp     r2, #26
    beq     cmd_dma_probe_chunk
    cmp     r2, #27
    beq     cmd_core0_inspect
    cmp     r2, #28
    beq     cmd_qspi_read_chunk

    @ Check if this is an address latch nibble (vel in 32..47)
    subs    r1, r2, #32
    cmp     r1, #15
    bhi     pass_through          @ Not a command and not an address nibble

    @ Process address nibble (r1 in 0..15)
    ldr     r3, =g_addr_bytes_left
    ldr     r2, [r3]
    cbz     r2, pass_through      @ Not currently latching address

    subs    r2, #1
    str     r2, [r3]              @ bytes_left -= 1

    ldr     r3, =g_addr_latch
    ldr     r0, [r3]
    lsls    r0, r0, #4
    orrs    r0, r0, r1
    str     r0, [r3]
    cbnz    r2, done_pop

    @ 8th nibble: commit address
    bic.w   r0, r0, #3            @ word align
    ldr     r3, =g_current_ptr
    str     r0, [r3]

done_pop:
    pop.w   {r4, r5, r6, r7, r8, r9, r10, pc}

pass_through:
    pop.w   {r4, r5, r6, r7, r8, r9, r10, lr}
    b.w     RXDT_ENQUEUE_WORD

cmd_set_addr:
    ldr     r3, =g_addr_latch
    movs    r0, #0
    movs    r1, #8                @ 8 nibbles
    stmia   r3!, {r0, r1}         @ latch = 0, bytes_left = 8
    b       done_pop

cmd_sysex_slice:
    ldr     r3, =g_current_ptr
    ldr     r4, [r3]              @ r4 = current read address (e.g. 0x60000000)
    mov     r8, r4                @ data source pointer
    adds    r0, r4, #64
    str     r0, [r3]              @ advance pointer for next slice
    bl      send_sysex_packet
    b       done_pop

cmd_probe_dma_regs:
    @ =========================================================================
    @ Step 1: Probe DMA Controller Registers (0x40001000)
    @ Safely reads 0x40001000, 0x40001004, 0x40001020, 0x40001024, 0x40001028, 0x4000102C
    @ Returns register snapshot via SysEx. No DMA writes performed.
    @ =========================================================================
    ldr     r4, =0x40001000
    ldr     r1, =0x2001F040       @ Report buffer in SRAM

    ldr     r0, [r4, #0x00]       @ Global control (0x40001000)
    str     r0, [r1, #0]
    ldr     r0, [r4, #0x04]       @ Status / config (0x40001004)
    str     r0, [r1, #4]
    ldr     r0, [r4, #0x20]       @ Channel 1 control (0x40001020)
    str     r0, [r1, #8]
    ldr     r0, [r4, #0x24]       @ Channel 1 status (0x40001024)
    str     r0, [r1, #12]
    ldr     r0, [r4, #0x28]       @ Channel 1 dest (0x40001028)
    str     r0, [r1, #16]
    ldr     r0, [r4, #0x2C]       @ Channel 1 src (0x4000102C)
    str     r0, [r1, #20]

    ldr     r0, =0x53474552       @ ASCII "REGS" in little-endian ('R','E','G','S')
    str     r0, [r1, #24]

    @ Pad remaining words
    movs    r0, #0
    movs    r2, #9
    adds    r3, r1, #28
pad_regs_loop:
    str     r0, [r3], #4
    subs    r2, #1
    bne     pad_regs_loop

    ldr     r4, =0x40001000       @ Packet address header
    ldr     r8, =0x2001F040       @ Data buffer
    bl      send_sysex_packet
    b       done_pop

cmd_test_dma_c1:
    @ =========================================================================
    @ Step 2: DMA Write to Shared SRAM (0x2001F100)
    @ Tests if the SoC DMA Engine can transfer data from SRAM to SRAM across the bus.
    @ Source: Shared SRAM (0x2001F000)
    @ Destination: Shared SRAM (0x2001F100)
    @ Core 0 is completely untouched.
    @ =========================================================================
    @ 1. Prepare known test pattern in Shared SRAM (0x2001F000)
    ldr     r1, =0x2001F000
    ldr     r0, =0xA1B2C3D4
    str     r0, [r1, #0]
    ldr     r0, =0x11223344
    str     r0, [r1, #4]
    ldr     r0, =0x55667788
    str     r0, [r1, #8]
    ldr     r0, =0xDEADBEEF
    str     r0, [r1, #12]

    @ Fill remaining 12 words with recognizable sequence
    movs    r2, #12
    adds    r3, r1, #16
fill_c1_sram_loop:
    adds    r0, #0x100
    str     r0, [r3], #4
    subs    r2, #1
    bne     fill_c1_sram_loop

    @ 2. Zero out destination buffer at 0x2001F100
    ldr     r1, =0x2001F100
    movs    r0, #0
    movs    r2, #16
zero_c1_scratch:
    str     r0, [r1], #4
    subs    r2, #1
    bne     zero_c1_scratch

    @ 3. Check and ensure DMA engine is enabled (DO NOT RESET ENGINE!)
    ldr     r4, =0x40001000
    ldr     r0, [r4, #0x00]
    tst.w   r0, #0x80000000
    itt     eq
    orreq   r0, r0, #0x80000000
    streq   r0, [r4, #0x00]       @ Set enable bit only if not already set

    @ 4. Program Channel 1 for transfer to SRAM destination
    ldr     r0, =0x2001F000       @ Src: SRAM test pattern (0x40001028 = SOURCE)
    str     r0, [r4, #0x28]
    ldr     r0, =0x2001F100       @ Dest: Shared SRAM (0x4000102C = DESTINATION)
    str     r0, [r4, #0x2C]

    mov.w   r0, #0x18000000       @ 64-byte burst command
    str     r0, [r4, #0x24]

    ldr     r0, =0xA0FF0000       @ Transfer count: 1 burst of 64 bytes (0xA0FF0000 + count - 1)
    str     r0, [r4, #0x20]       @ Arm & trigger DMA transfer!

    dsb     sy

    @ 5. Poll DMA completion (bits 18:16 == 0x50000)
    ldr     r5, =1000000
poll_c1_dma:
    ldr     r0, [r4, #0x24]
    and.w   r1, r0, #0x70000
    cmp.w   r1, #0x50000
    beq     c1_dma_done
    subs    r5, #1
    bne     poll_c1_dma
    movs    r6, #2                @ Status 2: Timeout
    b       read_c1_dma_result

c1_dma_done:
    movs    r6, #1                @ Status 1: Completed

    @ Clear channel status bits [18:16]
    ldr     r0, [r4, #0x24]
    bic     r0, r0, #0x70000
    str     r0, [r4, #0x24]

read_c1_dma_result:
    @ 6. Read back directly from 0x2001F100
    ldr     r0, =0x2001F100
    ldr     r7, [r0, #0]          @ Word 0 readback (Expected: 0xA1B2C3D4)
    ldr     r8, [r0, #12]         @ Word 3 readback (Expected: 0xDEADBEEF)

    @ Store diagnostic summary into SRAM response slice at 0x2001F040
    ldr     r1, =0x2001F040
    str     r6, [r1, #0]          @ Status (1 = OK, 2 = Timeout)
    str     r7, [r1, #4]          @ Word 0 readback
    str     r8, [r1, #8]          @ Word 3 readback
    ldr     r0, =0x4D443143       @ ASCII "C1DM" in little-endian ('C','1','D','M')
    str     r0, [r1, #12]

    @ Copy remaining readback words from 0x2001F100 into report
    ldr     r0, =0x2001F100
    adds    r0, #16
    adds    r1, #16
    movs    r2, #12
copy_c1_report:
    ldr     r3, [r0], #4
    str     r3, [r1], #4
    subs    r2, #1
    bne     copy_c1_report

    @ Transmit 64-byte result via SysEx
    ldr     r4, =0x2001F100       @ Report address
    ldr     r8, =0x2001F040       @ Data buffer
    bl      send_sysex_packet
    b       done_pop

cmd_test_dma_c0_identity:
    @ =========================================================================
    @ Step 3: DMA Write to Core 0 ITCM Unused Scratch / Padding (0x01060000)
    @ Statically confirmed that 0x01060000 is 100% ZEROES in live Core 0 ITCM.
    @ Core 0 stack is at 0x01050800 (growing downwards); 0x01060000 is far above.
    @ Tests if DMA bus master writes test pattern into Core 0 ITCM.
    @ =========================================================================
    @ 1. Prepare test pattern in Shared SRAM buffer (0x2001F000)
    ldr     r1, =0x2001F000
    ldr     r0, =0xA1B2C3D4
    str     r0, [r1, #0]
    ldr     r0, =0x11223344
    str     r0, [r1, #4]
    ldr     r0, =0x55667788
    str     r0, [r1, #8]
    ldr     r0, =0xDEADBEEF
    str     r0, [r1, #12]

    movs    r2, #12
    adds    r3, r1, #16
fill_c0_sram_loop:
    adds    r0, #0x100
    str     r0, [r3], #4
    subs    r2, #1
    bne     fill_c0_sram_loop

    @ 2. Ensure DMA engine is enabled (DO NOT RESET ENGINE!)
    ldr     r4, =0x40001000
    ldr     r0, [r4, #0x00]
    tst.w   r0, #0x80000000
    itt     eq
    orreq   r0, r0, #0x80000000
    streq   r0, [r4, #0x00]

    @ 3. Program Channel 1 for transfer to Core 0 ITCM Scratch (0x01060000)
    ldr     r0, =0x2001F000       @ Src: SRAM buffer with test pattern (0x40001028 = SOURCE)
    str     r0, [r4, #0x28]
    ldr     r0, =0x01060000       @ Dest: Core 0 ITCM Scratch (0x4000102C = DESTINATION)
    str     r0, [r4, #0x2C]

    mov.w   r0, #0x18000000       @ 64-byte burst command
    str     r0, [r4, #0x24]

    ldr     r0, =0xA0FF0000       @ Transfer count: 1 burst of 64 bytes (0xA0FF0000 + count - 1)
    str     r0, [r4, #0x20]       @ Arm & trigger DMA transfer!

    dsb     sy

    @ 4. Poll DMA completion
    ldr     r5, =1000000
poll_c0_identity:
    ldr     r0, [r4, #0x24]
    and.w   r1, r0, #0x70000
    cmp.w   r1, #0x50000
    beq     c0_identity_done
    subs    r5, #1
    bne     poll_c0_identity
    movs    r6, #2                @ Status 2: Timeout
    b       read_c0_identity_result

c0_identity_done:
    movs    r6, #1                @ Status 1: Completed

    @ Clear channel status bits [18:16]
    ldr     r0, [r4, #0x24]
    bic     r0, r0, #0x70000
    str     r0, [r4, #0x24]

read_c0_identity_result:
    @ 5. Read back Word 0 and Word 3 directly from Core 0 ITCM (0x01060000)
    ldr     r0, =0x01060000
    ldr     r7, [r0, #0]          @ Word 0 readback (Expected: 0xA1B2C3D4)
    ldr     r8, [r0, #12]         @ Word 3 readback (Expected: 0xDEADBEEF)

    @ Store diagnostic summary into SRAM response slice at 0x2001F040
    ldr     r1, =0x2001F040
    str     r6, [r1, #0]          @ Status (1 = OK, 2 = Timeout)
    str     r7, [r1, #4]          @ Word 0 readback
    str     r8, [r1, #8]          @ Word 3 readback
    ldr     r0, =0x44493043       @ ASCII "C0ID" in little-endian ('C','0','I','D')
    str     r0, [r1, #12]

    @ Copy remaining readback words from 0x01060000 into report
    ldr     r0, =0x01060000
    adds    r0, #16
    adds    r1, #16
    movs    r2, #12
copy_c0_id_report:
    ldr     r3, [r0], #4
    str     r3, [r1], #4
    subs    r2, #1
    bne     copy_c0_id_report

    @ Transmit 64-byte result via SysEx
    ldr     r4, =0x01060000       @ Report address
    ldr     r8, =0x2001F040       @ Data buffer
    bl      send_sysex_packet
    b       done_pop

cmd_safe_probe_chunk:
    push.w  {r4, r5, r6, r7, r8, r9, sl, fp, lr}
    ldr.w   r4, =0xE000ED08       @ VTOR address
    ldr     r5, [r4]              @ Active Vector Table Base (0x00000000 or 0x01100000)
    ldr     r6, [r5, #12]         @ Original HardFault vector (+0x0C)
    ldr     r7, [r5, #16]         @ Original MemManage vector (+0x10)
    ldr.w   r8, [r5, #20]         @ Original BusFault vector (+0x14)
    ldr.w   r9, =0xE000ED24       @ SHCSR address
    ldr.w   sl, [r9]              @ Original SHCSR value

    @ Hook HardFault, MemManage, BusFault vectors with trap_fault_handler
    ldr.w   r0, =trap_fault_handler
    orr.w   r0, r0, #1            @ Thumb bit
    str     r0, [r5, #12]
    str     r0, [r5, #16]
    str     r0, [r5, #20]

    @ Enable USGFAULTENA, BUSFAULTENA, MEMFAULTENA in SHCSR
    ldr.w   r0, [r9]
    orr.w   r0, r0, #0x70000
    str.w   r0, [r9]

    @ Enable interrupts for fault trapping
    mrs     ip, PRIMASK
    push    {ip}
    cpsie   i

    @ CCR: Disable unaligned access traps
    ldr.w   r0, =0xE000ED14
    ldr     r1, [r0]
    push    {r0, r1}
    orr.w   r1, r1, #2
    str     r1, [r0]
    dsb     sy
    isb     sy

    ldr.w   fp, =g_current_ptr
    ldr.w   r4, [fp]              @ Base address to probe
    ldr     r1, =0x2001F040       @ Report buffer
    movs    r2, #0                @ Word index [0..13]
    movs    r3, #0                @ Fault bitmap accumulator

safe_probe_loop:
    push    {r1, r2, r3}
    add.w   r1, r4, r2, lsl #2    @ Target word address
    bl      safe_read_word        @ r0 = read value, r2 = fault flag (1=fault, 0=ok)
    mov     ip, r0
    mov     r0, r2
    pop     {r1, r2, r3}
    str.w   ip, [r1, r2, lsl #2]  @ Store word
    cbz     r0, safe_probe_next
    movs    r0, #1
    lsls    r0, r2
    orrs    r3, r0                @ Set bit in fault bitmap

safe_probe_next:
    adds    r2, #1
    cmp     r2, #14
    bne     safe_probe_loop

    str     r3, [r1, #56]         @ word 14 = fault bitmap
    ldr     r0, =0x42525053       @ word 15 = 'S','P','R','B' ("SPRB")
    str     r0, [r1, #60]

    @ Restore CCR
    pop     {r0, r1}
    str     r1, [r0]

    @ Restore PRIMASK
    pop     {ip}
    msr     PRIMASK, ip

    @ Restore vectors and SHCSR
    str     r6, [r5, #12]
    str     r7, [r5, #16]
    str.w   r8, [r5, #20]
    str.w   sl, [r9]
    dsb     sy
    isb     sy

    adds.w  r0, r4, #64
    str.w   r0, [fp]              @ Advance pointer

    ldr.w   r8, =0x2001F040
    bl      send_sysex_packet

    pop.w   {r4, r5, r6, r7, r8, r9, sl, fp, lr}
    b       done_pop

safe_read_word:
    push    {r3, lr}
    ldr     r3, =g_probe_faulted
    movs    r0, #0
    str     r0, [r3]
    ldr     r3, =g_trap_active
    movs    r0, #1
    str     r0, [r3]
    dsb     sy
    isb     sy
probe_insn:
    ldr.w   r0, [r1]
    dsb     sy
    isb     sy
    ldr     r3, =g_trap_active
    movs    r1, #0
    str     r1, [r3]
    ldr     r3, =g_probe_faulted
    ldr     r2, [r3]              @ r2 = 0 (OK)
    pop     {r3, pc}

probe_fault_return:
    ldr     r3, =g_trap_active
    movs    r1, #0
    str     r1, [r3]
    ldr     r0, =0xBAADF00D       @ r0 = 0xBAADF00D
    movs    r2, #1                @ r2 = 1 (Fault)
    pop     {r3, pc}

trap_fault_handler:
    tst.w   lr, #4
    ite     eq
    mrseq   r0, MSP
    mrsne   r0, PSP
    ldr     r1, =g_trap_active
    ldr     r2, [r1]
    cbz     r2, trap_unhandled
    @ Clear fault flags in CFSR and HFSR
    ldr     r1, =0xE000ED28
    mvn.w   r2, #0
    str     r2, [r1]
    ldr     r1, =0xE000ED2C
    str     r2, [r1]
    @ Adjust return PC on stack to probe_fault_return
    ldr     r2, =probe_fault_return
    orr.w   r2, r2, #1
    str     r2, [r0, #24]         @ Stacked PC
    ldr     r1, =g_trap_active
    movs    r2, #0
    str     r2, [r1]
    dsb     sy
    isb     sy
    bx      lr
trap_unhandled:
    b       trap_unhandled

cmd_read_sys_regs:
    ldr     r1, =0x2001F040       @ Report buffer
    ldr     r2, =0xE000ED00       @ SCB base
    ldr     r0, [r2, #0x00]       @ CPUID
    str     r0, [r1, #0]
    ldr     r0, [r2, #0x08]       @ VTOR
    str     r0, [r1, #4]
    ldr     r0, [r2, #0x24]       @ SHCSR
    str     r0, [r1, #8]
    ldr     r0, [r2, #0x28]       @ CFSR
    str     r0, [r1, #12]
    ldr     r0, [r2, #0x2C]       @ HFSR
    str     r0, [r1, #16]
    ldr     r0, [r2, #0x34]       @ MMFAR
    str     r0, [r1, #20]
    ldr     r0, [r2, #0x38]       @ BFAR
    str     r0, [r1, #24]
    ldr     r2, =0xE000EF90       @ TCM base
    ldr     r0, [r2, #0x00]       @ ITCMCR
    str     r0, [r1, #28]
    ldr     r0, [r2, #0x04]       @ DTCMCR
    str     r0, [r1, #32]
    ldr     r0, [r2, #0x08]       @ AHBPCR
    str     r0, [r1, #36]
    ldr     r0, [r2, #0x0C]       @ CACR
    str     r0, [r1, #40]
    ldr     r2, =0xE000ED14       @ CCR
    ldr     r0, [r2]
    str     r0, [r1, #44]
    movs    r0, #0
    str     r0, [r1, #48]
    str     r0, [r1, #52]
    str     r0, [r1, #56]
    ldr     r0, =0x47455253       @ 'S','R','E','G' ("SREG")
    str     r0, [r1, #60]
    ldr     r4, =0xE000ED00
    ldr.w   r8, =0x2001F040
    bl      send_sysex_packet
    b       done_pop

cmd_dma_probe_chunk:
    ldr     r1, =0x2001F100
    movs    r0, #0
    movs    r2, #16
zero_dma_buf:
    str.w   r0, [r1], #4
    subs    r2, #1
    bne     zero_dma_buf

    ldr     r4, =0x40001000       @ DMAC1 base
    ldr     r0, [r4]
    tst.w   r0, #0x80000000
    itt     eq
    orreq.w r0, r0, #0x80000000
    streq   r0, [r4]

    ldr     r3, =g_current_ptr
    ldr     r0, [r3]              @ Target source address
    str     r0, [r4, #0x28]       @ Source address
    ldr     r1, =0x2001F100       @ Shared SRAM bounce buffer
    str     r1, [r4, #0x2C]       @ Dest address
    mov.w   r0, #0x18000000       @ 64-byte burst
    str     r0, [r4, #0x24]
    ldr     r0, =0xA0FF0000
    str     r0, [r4, #0x20]       @ Trigger DMA
    dsb     sy

    ldr     r5, =500000
poll_dma_probe:
    ldr     r0, [r4, #0x24]
    and.w   r1, r0, #0x70000
    cmp.w   r1, #0x50000
    beq     dma_probe_done
    subs    r5, #1
    bne     poll_dma_probe
    movs    r0, #0
    str     r0, [r4, #0x20]
    str     r0, [r4, #0x24]
    movs    r6, #2                @ Timeout / Fault
    b       report_dma_probe

dma_probe_done:
    movs    r6, #1                @ Complete / Online
    ldr     r0, [r4, #0x24]
    bic.w   r0, r0, #0x70000
    str     r0, [r4, #0x24]

report_dma_probe:
    ldr     r1, =0x2001F040       @ Report buffer
    ldr     r0, =0x2001F100
    movs    r2, #14
copy_dma_report:
    ldr.w   r3, [r0], #4
    str.w   r3, [r1], #4
    subs    r2, #1
    bne     copy_dma_report
    str     r6, [r1, #0]          @ Status code
    ldr     r0, =0x42525044       @ 'D','P','R','B' ("DPRB")
    str     r0, [r1, #4]

    ldr     r3, =g_current_ptr
    ldr     r4, [r3]
    adds.w  r0, r4, #64
    str     r0, [r3]

    ldr.w   r8, =0x2001F040
    bl      send_sysex_packet
    b       done_pop

cmd_core0_inspect:
    @ =========================================================================
    @ Direct Core 0 System Register Inspection via SysTick Vector Hook
    @ Reads Core 0 CPUID (0xE000ED00), VTOR, ICSR, ITCMCR, DTCMCR, AHBPCR
    @ =========================================================================
    @ Clear destination buffer (0x2001F040)
    ldr     r1, =0x2001F040
    movs    r0, #0
    movs    r2, #16
zero_inspect_buf:
    str     r0, [r1], #4
    subs    r2, #1
    bne     zero_inspect_buf

    @ Ensure DMAC1 engine is enabled
    ldr     r6, =0x40001000       @ DMAC1 Base
    ldr     r0, [r6, #0]
    tst.w   r0, #0x80000000
    itt     eq
    orreq   r0, r0, #0x80000000
    streq   r0, [r6, #0]

    @ Check if inspect hook is already installed (code 2)
    ldr     r1, =g_c0_hook_installed
    ldr     r0, [r1]
    cmp     r0, #2
    beq     inspect_already_installed

    @ Step A. DMA 64-byte payload to Core 0 ITCM (0x01060000)
    ldr     r0, =c0_inspect_payload_template
    ldr     r1, =0x2001F100       @ SRAM staging buffer
    movs    r2, #16               @ 16 words = 64 bytes
copy_c0_inspect:
    ldr     r3, [r0], #4
    str     r3, [r1], #4
    subs    r2, #1
    bne     copy_c0_inspect

    ldr     r0, =0x2001F100       @ Src: SRAM
    str     r0, [r6, #0x28]
    ldr     r0, =0x01060000       @ Dest: Core 0 ITCM Scratch
    str     r0, [r6, #0x2C]
    mov.w   r0, #0x18000000       @ 64-byte burst
    str     r0, [r6, #0x24]
    ldr     r0, =0xA0FF0000       @ 1 burst = 64 bytes
    str     r0, [r6, #0x20]       @ Trigger DMA!

    ldr     r5, =500000
poll_dma_inspect_itcm:
    ldr     r0, [r6, #0x24]
    and.w   r1, r0, #0x70000
    cmp.w   r1, #0x50000
    beq     dma_inspect_itcm_done
    subs    r5, #1
    bne     poll_dma_inspect_itcm
    movs    r7, #2                @ Error 2: DMA to ITCM Timeout
    b       report_c0_inspect

dma_inspect_itcm_done:
    ldr     r0, [r6, #0x24]
    bic     r0, r0, #0x70000
    str     r0, [r6, #0x24]

    @ Step B. DMA 64-byte vector table block to Core 0 ITCM (0x01000000)
    ldr     r0, =c0_vtor_template
    ldr     r1, =0x2001F100       @ SRAM staging buffer
    movs    r2, #16               @ 16 words = 64 bytes
copy_vtor_inspect:
    ldr     r3, [r0], #4
    str     r3, [r1], #4
    subs    r2, #1
    bne     copy_vtor_inspect

    ldr     r0, =0x2001F100       @ Src: SRAM
    str     r0, [r6, #0x28]
    ldr     r0, =0x01000000       @ Dest: Core 0 Vector Table Base
    str     r0, [r6, #0x2C]
    mov.w   r0, #0x18000000       @ 64-byte burst
    str     r0, [r6, #0x24]
    ldr     r0, =0xA0FF0000       @ 1 burst = 64 bytes
    str     r0, [r6, #0x20]       @ Trigger DMA!

    ldr     r5, =500000
poll_dma_inspect_hook:
    ldr     r0, [r6, #0x24]
    and.w   r1, r0, #0x70000
    cmp.w   r1, #0x50000
    beq     dma_inspect_hook_done
    subs    r5, #1
    bne     poll_dma_inspect_hook
    movs    r7, #2                @ Error 2: DMA Hook Timeout
    b       report_c0_inspect

dma_inspect_hook_done:
    ldr     r0, [r6, #0x24]
    bic     r0, r0, #0x70000
    str     r0, [r6, #0x24]

    @ Mark inspect hook installed (2)
    ldr     r1, =g_c0_hook_installed
    movs    r0, #2
    str     r0, [r1]

inspect_already_installed:
    @ Step C. Trigger Core 0 execution
    ldr     r1, =0x2001F03C
    ldr     r0, =0xDEADBEEF
    str     r0, [r1]

    @ Poll for Core 0 to complete
    ldr     r5, =5000000
    ldr     r1, =0x2001F03C
poll_c0_inspect_done:
    ldr     r0, [r1]
    cbz     r0, c0_inspect_ok
    subs    r5, #1
    bne     poll_c0_inspect_done
    movs    r7, #3                @ Error 3: Core 0 Exec Timeout
    b       report_c0_inspect

c0_inspect_ok:
    movs    r7, #1                @ Status 1: Success!
    ldr     r5, =0x2001F040
    ldr     r0, =0x4B4F3043       @ 'C','0','O','K'
    str     r0, [r5, #28]         @ word 7 = 'C0OK'

report_c0_inspect:
    ldr     r5, =0x2001F040
    str     r7, [r5, #56]         @ word 14 = status (1 = OK, 2 = DMA timeout, 3 = Exec timeout)
    ldr     r0, =0x50523043       @ 'C','0','R','P' -> "C0RP"
    str     r0, [r5, #60]         @ word 15 = 'C0RP'

    @ Transmit 64 bytes via SysEx (reported address = 0x01060000)
    ldr     r4, =0x01060000
    mov     r8, r5
    bl      send_sysex_packet
    b       done_pop

.align 2
c0_inspect_payload_template:
    .word   0x490BB53F, 0x4A0B6808, 0xD10D4290, 0x6802480A
    .word   0x68446883, 0x0504F101, 0xF500C51C, 0xE8907024
    .word   0xC51C001C, 0x60082000, 0x403FE8BD, 0xF00CF8DF
    .word   0x2001F03C, 0xDEADBEEF, 0xE000ED00, 0x01005FA5

cmd_qspi_read_chunk:
    @ =========================================================================
    @ Direct Physical SPI Flash Read via Core 0 Task Hook (Pathway 2)
    @ Core 0 executes 0x6002053C in Task 7 ("SendDT1") thread context.
    @ =========================================================================
    ldr     r3, =g_current_ptr
    ldr     r4, [r3]              @ Flash Byte Address to read (e.g. 0x00000000)

    @ Clear destination buffer (0x2001F040)
    ldr     r1, =0x2001F040
    movs    r0, #0
    movs    r2, #16
zero_dest_buf:
    str     r0, [r1], #4
    subs    r2, #1
    bne     zero_dest_buf

    @ Ensure DMAC1 engine is enabled
    ldr     r6, =0x40001000       @ DMAC1 Base
    ldr     r0, [r6, #0]
    tst.w   r0, #0x80000000
    itt     eq
    orreq   r0, r0, #0x80000000
    streq   r0, [r6, #0]

    @ Check if hook is already installed
    ldr     r1, =g_c0_hook_installed
    ldr     r0, [r1]
    cmp     r0, #1
    beq     hook_already_installed

    @ -------------------------------------------------------------------------
    @ Install Hook: Step A. DMA 64-byte payload to Core 0 ITCM (0x01060000)
    @ -------------------------------------------------------------------------
    ldr     r0, =c0_task_payload_template
    ldr     r1, =0x2001F100       @ SRAM staging buffer
    movs    r2, #16               @ 16 words = 64 bytes
copy_c0_payload:
    ldr     r3, [r0], #4
    str     r3, [r1], #4
    subs    r2, #1
    bne     copy_c0_payload

    ldr     r0, =0x2001F100       @ Src: SRAM
    str     r0, [r6, #0x28]
    ldr     r0, =0x01060000       @ Dest: Core 0 ITCM Scratch
    str     r0, [r6, #0x2C]
    mov.w   r0, #0x18000000       @ 64-byte burst
    str     r0, [r6, #0x24]
    ldr     r0, =0xA0FF0000       @ 1 burst = 64 bytes
    str     r0, [r6, #0x20]       @ Trigger DMA!

    ldr     r5, =500000
poll_dma_itcm:
    ldr     r0, [r6, #0x24]
    and.w   r1, r0, #0x70000
    cmp.w   r1, #0x50000
    beq     dma_itcm_done
    subs    r5, #1
    bne     poll_dma_itcm
    movs    r7, #1                @ Error 1: DMA to ITCM Timeout
    b       report_c0_qspi

dma_itcm_done:
    ldr     r0, [r6, #0x24]
    bic     r0, r0, #0x70000
    str     r0, [r6, #0x24]

    @ -------------------------------------------------------------------------
    @ Install Hook: Step B. DMA 64-byte vector table block to Core 0 ITCM (0x01000000)
    @ Updates Vector 15 (SysTick) to point to 0x01060001
    @ -------------------------------------------------------------------------
    ldr     r0, =c0_vtor_template
    ldr     r1, =0x2001F100       @ SRAM staging buffer
    movs    r2, #16               @ 16 words = 64 bytes
copy_vtor_hook:
    ldr     r3, [r0], #4
    str     r3, [r1], #4
    subs    r2, #1
    bne     copy_vtor_hook

    ldr     r0, =0x2001F100       @ Src: SRAM
    str     r0, [r6, #0x28]
    ldr     r0, =0x01000000       @ Dest: Core 0 Vector Table Base
    str     r0, [r6, #0x2C]
    mov.w   r0, #0x18000000       @ 64-byte burst
    str     r0, [r6, #0x24]
    ldr     r0, =0xA0FF0000       @ 1 burst = 64 bytes
    str     r0, [r6, #0x20]       @ Trigger DMA!

    ldr     r5, =500000
poll_dma_hook:
    ldr     r0, [r6, #0x24]
    and.w   r1, r0, #0x70000
    cmp.w   r1, #0x50000
    beq     dma_hook_done
    subs    r5, #1
    bne     poll_dma_hook
    movs    r7, #2                @ Error 2: DMA Hook Timeout
    b       report_c0_qspi

dma_hook_done:
    ldr     r0, [r6, #0x24]
    bic     r0, r0, #0x70000
    str     r0, [r6, #0x24]

    @ Mark hook installed
    ldr     r1, =g_c0_hook_installed
    movs    r0, #1
    str     r0, [r1]

hook_already_installed:
    @ -------------------------------------------------------------------------
    @ Execute Flash Read: Set descriptor & trigger flag. SysTick executes within 1ms!
    @ -------------------------------------------------------------------------
    @ Prepare descriptor at 0x2001F080 (desc.flash_addr, desc.length, desc.ram_dest)
    ldr     r1, =0x2001F080
    str     r4, [r1, #0]          @ desc.flash_addr = r4
    movs    r0, #64
    str     r0, [r1, #4]          @ desc.length = 64
    ldr     r0, =0x2001F040
    str     r0, [r1, #8]          @ desc.ram_dest = 0x2001F040

    @ Set trigger flag in SRAM
    ldr     r1, =0x2001F03C
    ldr     r0, =0xDEADBEEF
    str     r0, [r1]

    @ Poll for Core 0 SysTick hook to complete the flash read (~100 ms timeout)
    ldr     r5, =5000000
    ldr     r1, =0x2001F03C
poll_c0_task_done:
    ldr     r0, [r1]
    ldr     r2, =0xDEADBEEF
    cmp     r0, r2
    bne     c0_task_read_done
    subs    r5, #1
    bne     poll_c0_task_done
    movs    r7, #4                @ Error 4: SysTick execution timeout
    b       report_c0_qspi

c0_task_read_done:
    mov     r7, r0                @ Save return status (0 = success)

report_c0_qspi:
    cmp     r7, #0
    beq     c0_qspi_ok
    ldr     r5, =0x2001F040
    ldr     r0, =0xBAAD0000
    orrs    r0, r7
    str     r0, [r5, #56]         @ word 14 = 0xBAAD000x
    ldr     r0, =0x45525251       @ 'Q','R','R','E' -> "QRRE"
    str     r0, [r5, #60]

c0_qspi_ok:
    @ Advance pointer
    ldr     r3, =g_current_ptr
    adds    r0, r4, #64
    str     r0, [r3]

    @ Transmit 64 bytes via SysEx
    ldr     r8, =0x2001F040
    bl      send_sysex_packet
    b       done_pop

.align 2
c0_task_payload_template:
    .word   0x401FE92D, 0x68084907, 0x42904A07, 0x4807D106
    .word   0x22084907, 0x47984B07, 0x60084902, 0x401FE8BD
    .word   0xF014F8DF, 0x2001F03C, 0xDEADBEEF, 0x40010000
    .word   0x2001F080, 0x01024AE3, 0x01005FA5, 0x00000000

.align 2
c0_vtor_template:
    .word   0x01050800, 0x60000001, 0x01005D9D, 0x01005D9F
    .word   0x01005DA1, 0x01005DA3, 0x01005DA5, 0x00000000
    .word   0x00000000, 0x00000000, 0x00000000, 0x01005F05
    .word   0x01005DA9, 0x00000000, 0x01005DCD, 0x01060001

send_sysex_packet:
    @ =========================================================================
    @ Common Roland DT1 SysEx Packet Transmitter
    @ Inputs:
    @   r4: 32-bit address for packet header
    @   r8: pointer to 64 bytes of data to transmit
    @ =========================================================================
    push    {r4, r5, r6, r7, r8, r9, r10, lr}
    ldr     r5, =g_sysex_buf
    mov     r9, r5                @ r9 = start of buffer for length calculation

    @ 1. Roland SysEx Header (8 bytes): F0 41 10 00 00 00 5E 12
    movs    r0, #0xF0
    strb    r0, [r5], #1
    movs    r0, #0x41             @ Roland ID
    strb    r0, [r5], #1
    movs    r0, #0x10             @ Device ID 17
    strb    r0, [r5], #1
    movs    r0, #0x00
    strb    r0, [r5], #1
    strb    r0, [r5], #1
    strb    r0, [r5], #1
    movs    r0, #0x5E             @ Model MC-101
    strb    r0, [r5], #1
    movs    r0, #0x12             @ Command DT1 (Data Set)
    strb    r0, [r5], #1

    @ Accumulator for Roland checksum (over address + data nibbles)
    movs    r7, #0

    @ 2. 8 Address Nibbles (MSB first: bits 28..31, 24..27, ..., 0..3)
    movs    r6, #8
syx_addr_loop:
    subs    r6, #1
    lsls    r1, r6, #2            @ r1 = shift count (28, 24, ..., 0)
    lsrs    r0, r4, r1
    ands    r0, #0x0F
    strb    r0, [r5], #1
    adds    r7, r0
    cmp     r6, #0
    bne     syx_addr_loop

    @ 3. 64 Data Bytes -> 128 Nibbles (high nibble, low nibble)
    movs    r6, #0
syx_data_loop:
    ldrb    r10, [r8, r6]         @ load byte from buffer at r8
    @ High nibble:
    lsrs    r0, r10, #4
    ands    r0, #0x0F
    strb    r0, [r5], #1
    adds    r7, r0
    @ Low nibble:
    ands    r0, r10, #0x0F
    strb    r0, [r5], #1
    adds    r7, r0

    adds    r6, #1
    cmp     r6, #64               @ 64 data bytes per chunk
    bne     syx_data_loop

    @ 4. Roland Checksum: (128 - (acc & 0x7F)) & 0x7F
    ands    r0, r7, #0x7F
    rsbs    r0, r0, #128
    ands    r0, #0x7F
    strb    r0, [r5], #1

    @ 5. End of Exclusive (0xF7)
    movs    r0, #0xF7
    strb    r0, [r5], #1

    @ 6. Convert 146-byte SysEx message into UMDW packets (Route 2 = USB-MIDI)
    @ and enqueue into TXDT (0x20097930).
    mov     r4, r9                @ r4 = byte pointer
    movs    r6, #146              @ r6 = bytes remaining

syx_umdw_loop:
    cmp     r6, #3
    bls     syx_umdw_residual

    ldrb    r0, [r4], #1          @ Byte 0
    ldrb    r1, [r4], #1          @ Byte 1
    ldrb    r2, [r4], #1          @ Byte 2

    @ UMDW word: Type 4 (SysEx Body), Route 2 (USB-MIDI) -> 0x24
    movs    r3, #0x24
    orr.w   r3, r3, r0, lsl #8
    orr.w   r3, r3, r1, lsl #16
    orr.w   r3, r3, r2, lsl #24
    mov     r0, r3
    bl      call_txdt_enqueue

    subs    r6, #3
    b       syx_umdw_loop

syx_umdw_residual:
    @ For 146 bytes: 146 = 48 * 3 + 2 bytes left (r6 == 2)
    cmp     r6, #2
    bne     syx_check_res1

    ldrb    r0, [r4], #1          @ Byte 0 (checksum)
    ldrb    r1, [r4], #1          @ Byte 1 (0xF7)
    @ UMDW word: Type 6 (SysEx End2), Route 2 -> 0x26
    movs    r3, #0x26
    orr.w   r3, r3, r0, lsl #8
    orr.w   r3, r3, r1, lsl #16
    mov     r0, r3
    bl      call_txdt_enqueue
    b       syx_signal_done

syx_check_res1:
    cmp     r6, #1
    bne     syx_signal_done

    ldrb    r0, [r4], #1          @ 0xF7
    @ UMDW word: Type 5 (SysEx End1), Route 2 -> 0x25
    movs    r3, #0x25
    orr.w   r3, r3, r0, lsl #8
    mov     r0, r3
    bl      call_txdt_enqueue

syx_signal_done:
    @ Signal Core 0 EXACTLY ONCE to drain TXDT to USB
    movs    r0, #2
    bl      TRIGGER_IPC_IRQ
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}

.align 2
.global c0_trampoline_template
c0_trampoline_template:
    push    {r0, r1}
    ldr     r0, =0x2001F080
    ldr     r1, =0x1010C0DE
    str     r1, [r0]
    pop     {r0, r1}
    ldr.w   pc, c0_trampoline_target
.align 2
c0_trampoline_target:
    .word   0
.ltorg
c0_trampoline_template_end:

call_txdt_enqueue:
    push    {r1, r2, r3, lr}
    bl      TXDT_ENQUEUE_WORD
    pop     {r1, r2, r3, pc}

.align 2
.global g_current_ptr
.global g_addr_latch
.global g_addr_bytes_left
.global g_trap_active
.global g_probe_faulted
.global g_c0_hook_installed

g_current_ptr:      .word 0
g_addr_latch:       .word 0
g_addr_bytes_left:  .word 0
g_trap_active:      .word 0
g_probe_faulted:    .word 0
g_c0_hook_installed: .word 0

.align 2
.global g_sysex_buf
g_sysex_buf:        .space 256

.align 2
.global g_c1_dma_scratch
g_c1_dma_scratch:   .space 64
