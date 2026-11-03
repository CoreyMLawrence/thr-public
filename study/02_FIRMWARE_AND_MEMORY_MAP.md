# Chapter 2: Firmware Architecture & Memory Map

A complete reference on flash memory organization, bootloader separation, firmware symbols, and ARM execution boundaries on the Yamaha THR.

---

## 1. Flash NOR Organization & Protection Boundaries

The 2 MiB Parallel NOR Flash is mapped at base address `0x02000000`:

```
0x02000000 +-------------------------------------------------------+
           | Section 0: First-Stage Bootloader (256 Bytes)         | -> READ-ONLY / PROTECTED
0x02000100 +-------------------------------------------------------+
           | Section 1: Secondary Bootloader / Updater (DTAb)      | -> READ-ONLY / PROTECTED
           | (~64 KiB) Displays 'U' on screen, handles USB MIDI    |
0x02010000 +-------------------------------------------------------+
           | Section 2: Main Application Firmware (DTAm)           | -> ERASED & WRITTEN
           | (~1 MiB) Full operating system, DSP microcode,        |    DURING FIRMWARE
           | tone stacks, UI event loops, effects tables           |    UPDATES
0x0210FFD0 +-------------------------------------------------------+
           | Firmware Build Signature & Metadata (48 Bytes)        |
0x0210FFFF +-------------------------------------------------------+
```

### Safety Implication: The Bootloader Firewall
When flashing firmware updates over USB MIDI:
- The secondary bootloader (DTAb) **only erases Section 2 (`0x02010000` to `0x0210FFFF`)**.
- Section 0 and Section 1 are physically bypassed during normal MIDI erase commands.
- Therefore, the USB MIDI updater itself cannot be overwritten by a standard MIDI update file. Even if an update process is interrupted, the hardware can re-enter Update Mode (`U`) provided Section 1 remains intact.

---

## 2. Main Application Firmware (DTAm) Memory Layout

The DTAm binary (`1,048,576 bytes` / `1 MiB`) executes in memory from base address `0x02010000`:

| Memory Range | Section Name | Size | Contents & Purpose |
|---|---|---|---|
| `0x02010000`–`0x0201003F` | `.vectors` | 64 Bytes | ARM Exception Vectors (Reset, Undefined Instruction, SWI, Prefetch Abort, Data Abort, IRQ, FIQ). |
| `0x02010040`–`0x0204FFFF` | `.text` | ~260 KiB | Core application logic, FreeRTOS scheduler, USB Audio/MIDI drivers, Task 4 UI polling, SysEx parser. |
| `0x02050000`–`0x0205FFFF` | `.rodata` | ~64 KiB | Preset tables, potentiometer ADC conversion curves, character fonts. |
| `0x02060000`–`0x0208645B` | `.dsp_blob` | ~153 KiB | Proprietary Yamaha DSP coprocessor microcode binary, uploaded to coprocessor during boot. |
| `0x0208645C`–`0x02096F8B` | `.data.dsp` | ~66 KiB | Initialized DSP model parameters, filter coefficients, and routing matrices. |
| `0x0209D000`–`0x0210FFCF` | `.patch_zone` | ~460 KiB | Unused Flash padding (initialized to `0xFF`). The ideal location for custom hooks, tone curves, and patch routines. |
| `0x0210FFD0`–`0x0210FFFF` | `.fwinfo` | 48 Bytes | Build timestamp, hardware target string, and firmware version signature. |

---

## 3. Authoritative Firmware Symbols & Internal Functions

All addresses below are Thumb execution targets (add `+1` to address when referencing via function pointer):

```c
/* Low-Level DSP Coprocessor Dispatcher
 * Directly manipulates internal hardware registers on the YMW808 coprocessor.
 * r0: Coprocessor ID (0 = Main Audio DSP)
 * r1: Block ID (0=Model, 1=Master EQ/Voicing, 2=Cab, 3=Mod, 4=Dly/Rev, 5=Comp, 6=Gate)
 * r2: Parameter Index within block
 * r3: Parameter Value (16-bit integer)
 */
int FUN_020184E6(int coproc, int block, int param, int val);

/* Front Panel LED Hardware Driver
 * r0: LED ID (THR5: 0=Clean, 1=Crunch, 2=Lead, 3=Brit Hi, 4=Modern,
 *                   5=Flat Arrow, 6=In-Tune Dot, 7=Sharp Arrow, 8=Tap Lamp)
 * r1: State (0 = ON, 1 = OFF) - Inverted active-low hardware driver!
 */
void FUN_0201E6F4(int led_id, int state);

/* 7-Segment Screen '#' Symbol Driver
 * Controls the sharp indicator on the single-character hardware display.
 * r0: Display column/mode (0 = standard status mode)
 * r1: State (1 = illuminated, 0 = blank)
 */
void FUN_0201E1F0(int mode, int sharp_on);

/* Analog Potentiometer Cache Invalidation
 * Forces the firmware to clear shadow ADC values for all 11 potentiometers,
 * immediately reading physical knob positions on next poll.
 */
void FUN_0201E83C(void);

/* Signed Modulo-5 Dial Helper (Stock routine at 0x020171CC)
 * 18-byte assembly routine calculating r0 % 5. Replaced in-place with
 * signed modulo-10 arithmetic for 10-position continuous rotary expansion.
 */
int FUN_020171CC(int dial_position);

/* EEPROM Controller Read / Write Functions */
int FUN_0201B40C(int eeprom_offset, unsigned char *dst_buf, int length);
int FUN_0201B5BC(int eeprom_offset, unsigned char *src_buf, int length);

/* Task 4 Dial Polling Hook Site
 * Task 4 continuously polls the rotary model selector and branches here.
 */
#define ADDR_TASK4_DIAL_HANDLER     0x0202BF28

/* Task 4 Convergence Opcode
 * All dial polling branches MUST converge on 0x0202C490 with opcode 0x4D86.
 */
#define ADDR_TASK4_CONVERGENCE      0x0202C490
#define OPCODE_TASK4_CONVERGENCE    0x4D86  // ldr r5, [pc, #0x218]

/* Rack Compressor Restriction Check
 * NOPing this 16-bit check enables Compressor Type 1 (24-bit studio Rack Compressor).
 */
#define ADDR_COMPRESSOR_CHECK       0x0201A292
```

---

## 4. Assembly & Thumb Execution Rules

1. **Instruction Alignment:** All 16-bit Thumb opcodes must be aligned on 2-byte boundaries. All 32-bit data literals in pool tables (`LDR Rd, [PC, #offset]`) must be aligned on 4-byte boundaries.
2. **Branch Offset Calculation:**
   A Thumb `BL` (Branch with Link) is encoded as two 16-bit instructions:
   ```python
   disp = target_addr - (source_addr + 4)
   hi = 0xF000 | ((disp >> 12) & 0x7FF)
   lo = 0xF800 | ((disp >> 1) & 0x7FF)
   ```
3. **Preserving Register State:**
   Hooks must strictly preserve all scratch registers (`R0`–`R3`) and status flags unless intentionally modifying return values. Functions calling other subroutines must push and pop `LR`/`PC` (`PUSH {R4, LR}` ... `POP {R4, PC}`).
