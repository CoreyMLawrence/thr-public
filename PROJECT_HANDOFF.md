# Yamaha THR Firmware Engineering: Project Master Handoff & Knowledge Base
## For Subsequent AI Coding Assistants & Firmware Engineers

---

## 1. Project Mission & Context

This repository (`c:\Users\corey\thr`) houses the complete reverse-engineering suite, custom hybrid firmware pipeline, diagnostics bench, and zero-install Web MIDI Studio for the **Yamaha THR series** desktop guitar amplifiers (specifically focusing on the **THR5**, **THR5A**, and cross-compatibility with the **THR10**, **THR10C**, and **THR10X**).

The primary engineering goal of this project is to synthesize a **Unified Hybrid Firmware** running on the compact 5-position THR5 hardware that seamlessly combines:
1. Authentic **Electric VCM Models** (Clean, Crunch, Lead, Brit Hi, Modern from THR5 / THR10).
2. Authentic **Acoustic Microphone Voicings** (EG Clean, Condenser, Dynamic, Tube, Nylon from THR5A).
3. Studio dynamics processing (authentic 24-bit Rack Compressor and acoustic plate/hall reverbs).
4. Continuous 10-position rotary model selection with dual-lap front-panel LED indicators and active bank display on the 7-segment screen.

The physical test hardware is an active **Yamaha THR-5A** running in live bench testing connected via USB. We have empirically verified that the factory stock THR5 (V2 electric) firmware runs natively on this unit. We make no claims regarding physical circuit identity on the THR10, THR10C, or THR10X models.

---

## 2. Hardware Architecture & Silicon Specifications

```
+-----------------------------------------------------------------------------------+
|                                 YAMAHA THR-5 / THR-5A                             |
|                                                                                   |
|  +--------------------+      +--------------------+      +---------------------+  |
|  | Analog Front End   | ---> | AKM AK4556 Stereo  | ---> | Yamaha DSP          |  |
|  | Guitar + Aux In    |      | 24-bit Audio Codec |      | Coprocessor YMW808  |  |
|  +--------------------+      +--------------------+      +----------+----------+  |
|                                                                     ^             |
|                                                                     | Control Bus |
|  +------------------------------------------------------------------+----------+  |
|  | Main Controller: Renesas / ARM7TDMI Core (Big-Endian)                       |  |
|  |                                                                             |  |
|  | - 2 MiB Parallel NOR Flash (Base Address: 0x02000000)                       |  |
|  |   * Section 0 (0x02000000 - 0x020000FF): First-stage primary bootloader     |  |
|  |   * Section 1 (0x02000100 - 0x0200FFFF): Secondary bootloader / updater     |  |
|  |     (DTAb - shows 'U' on display, handles USB MIDI flashing)                |  |
|  |   * Section 2 (0x02010000 - 0x0210FFFF): Main Application Firmware (DTAm)   |  |
|  |                                                                             |  |
|  | - Onboard SPI EEPROM: Renesas R1EX25002 (256 Bytes, IC11)                   |  |
|  |   * Stores startup preset, speaker voicing, wide stereo, tube glow lamp     |  |
|  |   * Pin 1 (CS), Pin 2 (MISO), Pin 4 (GND), Pin 5 (MOSI), Pin 6 (SCK)        |  |
|  +-----------------------------------------------------------------------------+  |
|         |                                                      |                  |
|         v                                                      v                  |
|  +--------------------+                              +---------------------+      |
|  | AK4556 DAC Output  | ---> Stereo Power Amp --->   | Twin 3.1" Speakers  |      |
|  | + Headphone Jack   |      (Class-D 5W + 5W)       | & Headphone Out     |      |
|  +--------------------+                              +---------------------+      |
+-----------------------------------------------------------------------------------+
```

### Critical Silicon Facts
- **Processor:** ARM7TDMI-S running in **Big-Endian** mode (`armeb`). All multi-byte integers, pointers, and Thumb branch instructions are big-endian in memory.
- **Instruction Set:** Mixed 32-bit ARM (exception vectors) and 16-bit / 32-bit Thumb (`Thumb-1` / `Thumb-2` branch instructions).
- **Flash Protection Boundary:** Flashing over USB MIDI writes strictly to Section 2 (DTAm, `0x02010000`–`0x0210FFFF`). The primary bootloader (`0x02000000`–`0x020000FF`) and secondary bootloader (`0x02000100`–`0x0200FFFF`) are write-protected against normal MIDI erase cycles.
- **Firmware Cross-Compatibility:** Live testing on physical **THR5A** hardware proved that the official factory stock **THR5 (Version 2 electric)** firmware boots and executes natively with zero hardware modification. The SoC, memory map, peripheral addresses, codec I2S lines, and DSP register interfaces are completely shared between the builds. Device personality (heartbeat SysEx identity `0x30` vs `0x34`) is governed by software tables in DTAm.

---

## 3. Firmware Memory Map & Critical Functions Catalog

Base memory mapping for DTAm starts at `0x02010000`:

| Address Range | Purpose / Contents |
|---|---|
| `0x02010000`–`0x020100FF` | ARM Exception Vectors & Reset Handlers |
| `0x02010100`–`0x0204FFFF` | Core Operating System, Drivers, MIDI, SysEx, Task Scheduler |
| `0x02050000`–`0x0205FFFF` | Factory Preset Tables, Knob Response Curves, UI Lookup Tables |
| `0x02060000`–`0x0208645B` | Yamaha DSP Binary Microcode Image (loaded to coprocessor on boot) |
| `0x0208645C`–`0x02096F8B` | Initialized DSP Data (`.data.dsp`) |
| `0x0209D000`–`0x0210FFCF` | Unused Flash Padding (`0xFF`), Custom Code Injection Area |
| `0x0210FFD0`–`0x0210FFFF` | Firmware Build Signature & Version String (48 bytes) |

### Key Firmware Function Offsets (Thumb Addresses)

```c
/* DSP Coprocessor Command Dispatcher
 * Parameters:
 *   r0: coprocessor ID (usually 0)
 *   r1: block ID (0=model, 1=master tone/chassis, 2=cab, 3=mod, 4=delay/rev, 5=comp, 6=gate)
 *   r2: parameter index
 *   r3: parameter value (16-bit)
 */
int FUN_020184E6(int coproc, int block, int param, int val);

/* Hardware Front Panel LED Driver
 * Parameters:
 *   r0: LED ID
 *       THR5:  0=Clean, 1=Crunch, 2=Lead, 3=Brit Hi, 4=Modern
 *              5=Tuner Left Triangle (Flat)
 *              6=Tuner Center Dot (In-Tune Green)
 *              7=Tuner Right Triangle (Sharp)
 *              8=Tap Tempo Lamp, 9=Tube Glow Lamps
 *       THR10: 0..7=Amp Models, 8..10=Tuner LEDs
 *   r1: State (0 = ON, 1 = OFF) - Note inverted logic in hardware driver!
 */
void FUN_0201E6F4(int led_id, int state);

/* 7-Segment Screen Control
 * Parameters:
 *   r0: Display column/mode (0 = default status display)
 *   r1: Sharp '#' symbol enable (1 = illuminated, 0 = blank)
 */
void FUN_0201E1F0(int mode, int sharp_on);

/* Analog Potentiometer Cache Invalidation
 * Calling this function immediately forces the firmware to clear cached ADC
 * potentiometer values and reload all 11 physical knob positions live.
 */
void FUN_0201E83C(void);

/* Signed Modulo Helper for Rotary Dial (Stock 18-byte routine at 0x020171CC)
 * Stock firmware computes r0 % 5.
 * Replaced in-place with signed modulo-10 arithmetic for 10-position dial expansion.
 */
int FUN_020171CC(int pos);

/* EEPROM Controller Functions */
int FUN_0201B40C(int offset, unsigned char *dst, int len);  /* EEPROM Read */
int FUN_0201B5BC(int offset, unsigned char *src, int len);  /* EEPROM Write */

/* Critical Loop Convergence Address in Task 4
 * ALL branch targets and loop ends in the Task 4 dial polling loop MUST converge
 * on this exact address containing valid Thumb opcode 0x4D86 (ldr r5, [pc, #0x218]).
 */
#define TASK4_CONVERGENCE_ADDR  0x0202C490
```

---

## 4. Complete 256-Byte EEPROM Memory Map & Hardware Unbricking

The onboard EEPROM is `IC11` (Renesas `R1EX25002` 256-byte SPI EEPROM). Disassembly of `0x0201B40C` and `0x0201B5BC` established the full non-volatile memory layout:

| EEPROM Offset | Size | Function / Description |
|---|---|---|
| `0x00` | 1 Byte | **Startup Amp Model:** Model index loaded on power-up (`0x00`–`0x09`). |
| `0x01` | 1 Byte | **Wide Stereo:** Extended stereo imaging (`0x00` = Off, `0x01` = On). |
| `0x02` | 1 Byte | **Boot Mode Sentinel:** Normal Boot = `0x00`. **Forced Update Mode = `0x01`**. |
| `0x03` | 1 Byte | **Tube Glow Lamps:** Simulated vacuum tube amber LEDs (`0x00` = Off, `0x01` = On). |
| `0x04`–`0x08` | 5 Bytes | **Preset Slot State:** Active preset states for user slots 1 through 5. |
| `0x09` | 1 Byte | **Master Speaker Voicing Curve:** Setting `0x02` (`0x28` to `0x40`). Tunes acoustic resonance. |
| `0x0A`–`0x1F` | 22 Bytes | Preset parameter blocks and calibration offsets. |
| `0x20`–`0xFE` | 223 Bytes | Factory calibration, volume curves, user-stored channel blocks. |
| `0xFF` | 1 Byte | **Factory Verification Sentinel:** Checked on power-up for EEPROM integrity. |

### Emergency Hardware Unbricking Guide

If an invalid firmware crashes the ARM processor on boot before USB MIDI initializes:
```
           R1EX25002 (IC11) Pinout (SOIC-8)
                 +---+-+---+
           /CS --| 1     8 |-- VCC (LEAVE DISCONNECTED!)
          MISO --| 2     7 |-- /HOLD
           /WP --| 3     6 |-- SCK
           GND --| 4     5 |-- MOSI
                 +---------+
```

1. **Hardware Setup:** Connect a CH341A USB programmer (or Raspberry Pi / Arduino) to `IC11` using a test clip or micro test leads:
   - Pin 1 (`/CS`) $\rightarrow$ Programmer CS
   - Pin 2 (`MISO`) $\rightarrow$ Programmer MISO
   - Pin 4 (`GND`) $\rightarrow$ Programmer GND
   - Pin 5 (`MOSI`) $\rightarrow$ Programmer MOSI
   - Pin 6 (`SCK`) $\rightarrow$ Programmer CLK
2. **POWER SAFETY WARNING:** **DO NOT connect Pin 8 (`VCC`)** to the programmer's 3.3V/5V pin! Powering `VCC` from USB triggers motherboard back-powering and overcurrent trips. Power the amplifier with its official **15V AC adapter**.
3. **Force Update Mode:**
   - Read EEPROM with programmer software (e.g. AsProgrammer or `minipro`).
   - Backup the 256 bytes to disk (`eeprom_backup.bin`).
   - Change byte at offset **`0x02`** from `0x00` to **`0x01`**.
   - Write back to `IC11`.
4. **Recovery Flash:**
   - Power cycle the amplifier. The CPU reads `0x01` at offset `0x02` during early boot, immediately jumping into the secondary bootloader (DTAb) and showing solid `U` on the LED display.
   - Run [flash_v42.py](file:///c:/Users/corey/thr/firmware-lab/flash_v42.py) or [stage-v52/flash_v52.py](file:///c:/Users/corey/thr/firmware-lab/stage-v52/flash_v52.py) to flash verified firmware over USB in ~136 seconds.

---

## 5. The Stage v42 "Golden Baseline" Architecture

Stage v42 ([build_v42.py](file:///c:/Users/corey/thr/firmware-lab/build_v42.py), [thr5_hybrid_v42.bin](file:///c:/Users/corey/thr/firmware-lab/stage-v42/thr5_hybrid_v42.bin)) is the **certified golden baseline**. It is completely stable, sounds phenomenal, and has zero audio anomalies.

### Why Stage v42 Works Perfectly:
1. **10 Authentic Models across 2 Banks:**
   - **Bank 1 — Electric (Models 0..4):**
     - `0`: Clean (Authentic THR5A EG Clean voicing + 1x12 cab)
     - `1`: Crunch (Stock THR5 Crunch)
     - `2`: Lead (Stock THR5 Lead)
     - `3`: Brit Hi (Stock THR5 Brit Hi)
     - `4`: Modern (Stock THR5 Modern)
   - **Bank 2 — Acoustic (Models 5..9):**
     - `5`: Acoustic Sim (Acoustic with EG Clean tone curve)
     - `6`: Condenser Mic (Authentic THR5A Condenser voicing)
     - `7`: Dynamic Mic (Authentic THR5A Dynamic voicing)
     - `8`: Tube Mic (Authentic THR5A Tube voicing)
     - `9`: Nylon Mic (Authentic THR5A Nylon voicing)
2. **Continuous Rotary Dial Arithmetic:**
   - Replaces stock modulo 5 helper at `0x020171CC` in-place with signed modulo 10 arithmetic.
   - Clockwise rotation wraps from 9 $\rightarrow$ 0; counter-clockwise wraps from 0 $\rightarrow$ 9.
3. **Tone Stack EQ Shaping:**
   - Injects the THR5A EG Clean tone stack at `0x0209EA40`, totally eliminating the annoying 100 Hz clean bass spike while preserving rock punch on models 1–4.
4. **24-Bit Rack Compressor Enabled:**
   - NOPs out restriction check at `0x0201A292`. Injects authentic 37-row THR5A dynamics lookup table at `0x0209D668`.
5. **Screen '#' Symbol Bank Display:**
   - Bank 1 (Electric, 0..4): `#` is illuminated via `FUN_0201E1F0(0, 1)`.
   - Bank 2 (Acoustic, 5..9): `#` is extinguished via `FUN_0201E1F0(0, 0)`.
6. **Live Potentiometer Tracking:**
   - Model dispatcher calls `FUN_0201E83C` on every transition, updating knob positions without jumps.

---

## 6. The Tuner Quirk: Root Cause Analysis & Stage v52 Solution

### The Quirk Observed in Stage v42:
When engaging the tuner in Stage v42, note pitch detection operated normally on the single-digit 7-segment display (showing note letter), but the directional pitch indicators (Flat $\blacktriangleleft$, In-Tune $\bullet$, Sharp $\blacktriangleright$) unexpectedly lit up the faceplate model LEDs (Clean, Crunch, Lead)!

### Root Cause Analysis:
1. `FUN_0201E6F4` is the **Global LED Driver**: `set_led(led_id, state)`.
2. On the **THR5 hardware**, LED IDs are mapped as:
   - `0`: Clean LED
   - `1`: Crunch LED
   - `2`: Lead LED
   - `3`: Brit Hi LED
   - `4`: Modern LED
   - **`5`:** Tuner Flat Triangle ($\blacktriangleleft$)
   - **`6`:** Tuner In-Tune Green Dot ($\bullet$)
   - **`7`:** Tuner Sharp Triangle ($\blacktriangleright$)
3. In Stage v42, to support a second bank of models (5..9), `FUN_0201E6F6` was hooked to `led_remap_stub`:
   ```arm
   cmp   r0, #5
   blo   not_model
   subs  r0, r0, #5    ; BUG: Maps 5->0, 6->1, 7->2!
   not_model:
   ...
   ```
   Whenever the tuner updated pitch display by calling `set_led(5)`, `set_led(6)`, or `set_led(7)`, the hook subtracted 5, redirecting tuner signals directly into LEDs 0, 1, and 2!

### The Compartmentalized Fix in Stage v52:
In Stage v52 ([build_v52.py](file:///c:/Users/corey/thr/firmware-lab/stage-v52/build_v52.py)):
1. **`0x0201E6F4` was restored to 100% FACTORY STOCK.** The global LED driver is completely unhooked. Tuner calls to `set_led(5/6/7)` execute natively without any interference.
2. **Model LED Remapping was Compartmentalized:**
   Model index modulo-5 logic was moved exclusively to the two routines that actually select models:
   - Task 4 Rotary Dial Handler at `0x0202BF28`
   - Preset Recall Handler `FUN_0201E4C0` at `0x0201E530`
3. **Clear Loops Clamped:**
   Before turning on a model LED, the stock code runs a loop clearing all model LEDs. In stock, this loop cleared `r4 < 5`. We verified that both clear loops (`0x0202BF22` and `0x0201E52A`) are clamped to `cmp r4, #5` so they never touch tuner LEDs 5..7.

---

## 7. The Fatal ARM Architecture Trap: Why Stage v50 Froze

> [!CAUTION]
> **MANDATORY ARM CORTEX-M / THUMB BRANCHING RULE:**
> Any branch or function call performed via register (`bx Rm` or `blx Rm`) **MUST have Bit[0] set to 1** to denote Thumb execution state!
> Branching to an **even address** (Bit[0] = 0) forces the processor into ARM state. Because the THR microcontroller executes Thumb code at these vectors, entering ARM state triggers an immediate `INVSTATE` UsageFault / HardFault, freezing the CPU instantly on boot!

In Stage v50, an experimental audio router was spliced:
```python
# FATAL FLAW IN STAGE v50:
addr_geq_gain = 0x02019E42  # EVEN ADDRESS (Bit 0 = 0)
asm.emit16(0x4718)          # bx r3 -> IMMEDIATE CPU HARDFAULT!
```
This single instruction froze the device on boot, requiring EEPROM unbricking.
**The Safe Solution:**
Always ensure target addresses for `bx` have Bit[0] set (`addr | 1`), or use `mov pc, reg` which does not switch instruction states on ARM7TDMI.

---

## 8. The 4 Mandatory Pre-Flash Safety Gates

Every proposed firmware build MUST pass all 4 gates before touching hardware:

```
+-------------------------------------------------------------------------------+
|                      THE 4 MANDATORY PRE-FLASH SAFETY GATES                   |
|                                                                               |
|  [GATE 1: CPU Emulation]  --> Unicorn Engine runs 5 test suites               |
|                               (Boot, Dial, Knob Sweep, Tuner, Presets)        |
|                               Must exit with ZERO CPU exceptions.             |
|                                                                               |
|  [GATE 2: Opcode Audit]   --> Disassemble all modified regions.               |
|                               Verify 32-bit Thumb instruction alignment.      |
|                               Verify 0x0202C490 holds valid opcode 0x4D86.    |
|                                                                               |
|  [GATE 3: Container Test] --> thr_tool.py validates SMF container:            |
|                               Exactly 2,343 messages, 2,341 blocks,           |
|                               global checksum match, 16,000 ms erase delay.   |
|                                                                               |
|  [GATE 4: Binary Diff]    --> Compare against reference stock.                |
|                               Account for 100% of modified bytes.             |
+-------------------------------------------------------------------------------+
```

---

## 9. Next Steps & Recommended Action Plan for Fresh Session

When starting the next conversation:

1. **Verify Stage v52 on Hardware:**
   - Confirm Stage v52 is loaded. Test the tuner: verify the orange triangles ($\blacktriangleleft, \blacktriangleright$) and green dot ($\bullet$) appear strictly on the screen, and the faceplate LEDs (Clean, Crunch, Lead) remain completely unlit during tuning.
   - Verify all 10 models switch cleanly and sound identical to Stage v42.
2. **If Continuing from Golden Stage v42:**
   - If the user prefers to stay on Stage v42 as the base, apply *only* the compartmentalized tuner fix from Stage v52 (`build_v52.py` Section 6) into `build_v42.py`.
3. **Expanding to THR10C / THR10X Models:**
   - To integrate Boutique, Deluxe, Class A (from THR10C) or Power I, Brown I (from THR10X):
     - **DO NOT** attempt runtime DSP code swapping or splicing audio gain routers (as attempted in v48).
     - **DO** use the Settings-Block Dual-Door SysEx mechanism or inject model parameter block tables into `.data.dsp` space (`0x0208645C`), leaving audio router functions `0x02019E00`–`0x0201A500` strictly stock.
4. **Tooling Reference:**
   - Flashing: `python firmware-lab/stage-v53/flash_v53.py` or `python thr_tool.py flash --port THR --file <file.mid>`.
   - Live MIDI Monitor: `python thr_live.py listen` or `systemctl status thr-detector.service`.
   - Web Studio: Launch `docs/index.html` or open [`https://coreymlawrence.github.io/thr/`](https://coreymlawrence.github.io/thr/).

---

## 10. Stage v53 Engineering Handoff & Permanent Operational Directives

### 1. Mandatory Physical 16x2 LCD Screen Directives
- **Host Hardware:** 16x2 I2C LCD character screen at `0x3F` (`http://localhost/api` via `thr_lcd.py`).
- **Core User Rule:** **The screen MUST be used as a verbose communication method with the user as much as possible.**
- Never leave the screen static or blank. Every operation (inspections, builds, safety gate audits, dumping, flashing, and monitoring) must output real-time progress and status to the screen.

### 2. Flashing Progress Bar Protocol & Fast-Flash Timing
- **Visual Progress Bars:** Flashers (`thr_tool.py flash` and `flash_v53.py`) render structured 3-phase progress on **both terminal and physical LCD**:
  - `[Step 1/3]` Erase NOR Flash (16.0s): Animated progress bar on LCD (`show_flash_erase`) and terminal.
  - `[Step 2/3]` Stream Payload Blocks (2,341 blocks): Dynamic bar with %, elapsed time, blk/s rate, ETA on LCD (`show_flash_streaming`) and terminal.
  - `[Step 3/3]` Finalize Checksum: Backlight alert pulse on LCD (`show_flash_done`), prompt user to reboot upon looping `E - n - d`.
- **Fast-Flash Timing Rules:**
  - `ERASE_GAP_MS` **MUST ALWAYS BE 16,000 ms (16s)**. Never reduce erase timing (risks flash write aborts).
  - `BLOCK_GAP_MS` **CAN BE SAFELY SET DOWN TO 15 ms** (factory default 50 ms), slashing flash time from 133s down to **~51s** with zero block dropouts.

### 3. Dedicated Tone Curve Architecture & Acoustic Calibration
- Tone controls use model-specific 606-byte lookup tables ($101 \times 6$ bytes: Bass `0x83`, Mid `0x84`, Treble `0x85`).
- On genuine THR-5A:
  - Acoustic 1 Condenser (`0x0205087A`): Tone 0% is warm body (`60, 35, 30`), Tone 50% is flat (`50, 50, 50`), Tone 100% is sparkling treble (`55, 60, 100`) without low-end runaway.
  - EG Clean (`0x0205061C`): Tone 0% (`60, 35, 20`) $\to$ 50% (`50, 45, 40`) $\to$ 100% (`55, 60, 70`).
- Electric Crunch (`0x0204F092`) intentionally boosts lows to 89 for cabinet thump; never leave electric curves on acoustic models.
- Stage v53 installed authentic Condenser curve on Model 1 (ACO) and EG Clean curve on Model 0 (Clean).

### 4. Hardware Telemetry & Detector Daemon Fixes
- **Inverted Switches:** Bypass switches are inverted (`0` = Active/ON, `127` = Bypassed/OFF) across Compressor (`0x10`), Modulation (`0x20`), Delay (`0x30`), and Reverb (`0x40`).
- **Effect Blending:** Knob 5 blends Compressor + Chorus; Knob 3 blends Delay + Reverb. Detectors must check both bypass state and knob zone to correctly display dual effects (`CMP+CHO`, `DLY+REV`) and erase inactive ones.
- **Batched Tone Draining:** Drain `port_in.iter_pending()` to coalesce Bass/Mid/Treble updates into a single LCD pass (`L:XX M:YY H:ZZ`) with zero flicker.

### 5. Hardware Connection Modes: Tuner Mode vs. Update Mode ('U')
- **The Problem:** When the user engages Tuner Mode on the amp (holding `TAP: TIME / HOLD: TUNER`), Yamaha's `DTAm` main firmware suspends periodic heartbeat SysEx (`F0 43 7D 60 44 54 41...`) to prioritize pitch calculation. Previous detector versions naively assumed "no heartbeats = Update Mode", mistakenly displaying `THR in [U] Mode! Ready to Flash`. Conversely, when in Update Mode ('U'), sending `DTA1ROMR` returns `DTA1ERASE` first as a preamble before `DTA1MAIN`; previous versions checked only for `b"DTA1MAIN"` and therefore misclassified Update Mode as Tuner Mode!
- **The Solution (Two-Way Active Probing & Preamble Detection):**
  1. In **Update Mode ('U')**, the secondary bootloader (`DTAb`) is running. It answers `DTA1ROMR` (`F0 43 7D 50 44 54 41 31 52 4F 4D 52 02 F7`) with `DTA1ERASE` followed by `DTA1MAIN` data blocks. Checking for `b"DTA1ERASE"` or `b"DTA1MAIN"` or `b"DTA1"` confirms **Update Mode ('U')**.
  2. In **Tuner Mode**, the main application firmware (`DTAm`) is running. It produces **zero replies** to `DTA1ROMR`.
  3. When heartbeats cease while the port is connected, `thr_detector.py` sends a lightweight `DTA1ROMR` probe:
     - If `DTA1ERASE` / `DTA1MAIN` is returned: Confirms **Update Mode ('U')** $\to$ LCD shows `THR in [U] Mode!` / `Ready to Flash`.
     - If no reply is returned: Confirms **Tuner Mode** $\to$ LCD shows `THR5: Tuner Mode` / `Muted / Tuning..` (alternating with `Tap to Exit`).
  4. Tapping `TAP/TUNER` or touching any knob exits tuner mode: heartbeats or parameter change messages (`CMD`) resume, and `thr_detector.py` immediately clears the override and resumes Normal Play Mode.

---

## 6. Breakthrough Discovery: Clean Signal Path Architecture & Stage v54 Solution

### The Harsh Highs Quirk on Clean:
When playing on Model 0 Clean, users observed a piercing, razor-sharp digital fizz in the high frequencies (5 kHz – 20 kHz) that sounded abrasive unless heavily rolled off.

### Root Cause Analysis in Firmware Disassembly:
1. **THR DSP Block Architecture:**
   - **DSP Block 4:** Electric Preamp Simulation
   - **DSP Block 5:** Acoustic Coprocessor Simulation
   - **DSP Block 2:** Speaker Cabinet Simulation (1x12 Deluxe, 2x12 British, 4x12, etc.)
2. In `dumped_custom_amp.bin` at `0x0201A104` (`FUN_0201A104`, Clean setup):
   - Local stack variable `local_38` (`[sp]`) holds the target DSP Block passed to `FUN_0203FA58`.
   - At `0x0201A15C`:
     ```arm
     movs r1, #5
     mov  r3, sp
     strh r1, [r2]   ; cab index = 5 (1x12 Deluxe)
     strh r1, [r3]   ; WRITES 5 TO [sp] (DSP Block Parameter) INSTEAD OF 2!
     ```
   - **The Bug:** `[sp]` was written as 5. `FUN_0203FA58` attempted to load the cabinet simulation into **Block 5**, completely bypassing **DSP Block 2**!
   - As a result, Model 0 Clean was running with **ZERO speaker cabinet emulation**. Unfiltered guitar preamp distortion and fizz was sent directly to the power amp with no 1x12 speaker cone low-pass filtering.

### The Stage v54 Solution:
At file offset `0x00A15C`, Stage v54 applies the 10-byte patch:
`21 02 46 6b 80 19 21 05 80 11`
Disassembles to:
```arm
movs r1, #2        ; DSP Block 2 (Cabinet Block)
mov  r3, sp
strh r1, [r3]      ; [sp] = 2 (Enables Cabinet Simulation in Block 2!)
movs r1, #5        ; Cab 5 (1x12 Deluxe)
strh r1, [r2]      ; *r2 = 5 (Cabinet Index 5)
```
- **Result:** DSP Block 2 is now actively loaded with the 1x12 Deluxe cabinet impulse response, filtering high frequencies above 4.5 kHz and delivering rich, warm, authentic Fender Deluxe Reverb tone.
- **Combined with Authentic Tone Curves:**
  - Model 0 (Clean): Authentic THR-5A EG Clean curve (`0x0205061C` -> `0x0204EE34`).
  - Model 1 (ACO): Authentic THR-5A Acoustic Condenser curve (`0x0205087A` -> `0x0204F092`).
  - Models 2..4: Preserved electric curves.



