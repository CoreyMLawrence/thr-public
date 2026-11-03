# Chapter 7: Rotary Encoder & UI Subsystem Expansion

A technical breakdown of Task 4 potentiometer/encoder polling, signed modulo-10 continuous arithmetic, 7-segment display manipulation, and the hardware LED isolation fix.

---

## 1. Physical Rotary Selector: An Endless Quadrature Encoder

Many users assume the 5-position model selector on the THR5 is a traditional stepped 5-pole rotary switch. 

### The Physical Reality
In reality, the component is a **continuous optical/mechanical quadrature encoder**. 
- It does not have hard physical stops; it can be rotated continuously clockwise or counter-clockwise indefinitely.
- The factory firmware artificially clamped the selector to 5 positions in software using a signed modulo-5 helper at `0x020171CC` and clamp bounds in Task 4.

---

## 2. Expanding to 10 Continuous Positions: The Modulo-10 Helper

To create a dual-bank hybrid amplifier with 10 distinct models (5 Electric VCM + 5 Acoustic Voicings), we replaced the factory 18-byte modulo-5 helper at `0x020171CC` *in-place* with an optimized signed modulo-10 arithmetic routine:

```arm
Address: 0x020171CC (18 Bytes Total)
    cmp     r0, #0          ; Check if dial position is negative (counter-clockwise wrap)
    bge     check_upper     ; If positive or zero, skip forward
    adds    r0, r0, #10     ; Wrap negative index back into 0..9 range
check_upper:
    cmp     r0, #10         ; Check if dial position exceeded 9 (clockwise wrap)
    blt     done            ; If within range, exit
    subs    r0, r0, #10     ; Wrap overflow back into 0..9 range
done:
    bx      lr              ; Return with normalized index in r0
    nop                     ; 2-byte alignment padding (0x46C0)
```

### Updating Task 4 Dial Clamping Limits
1. **Clockwise Clamp (`0x0202C474`):**
   Patched from `cmp r0, #5` (`0x2805`) to `cmp r0, #10` (`0x280A`).
2. **Counter-Clockwise Clamp (`0x0202C4E2`):**
   Patched from `movs r0, #4` (`0x2004`) to `movs r0, #9` (`0x2009`).

### The Resulting 10-Position Rotary Map

| Rotary Position | Active Model | Model Bank | Display '#' | Front Faceplate LED |
|---|---|---|---|---|
| **0** | Clean (EG Clean Voicing) | Electric Bank | **ON** | CLEAN LED |
| **1** | Crunch | Electric Bank | **ON** | CRUNCH LED |
| **2** | Lead | Electric Bank | **ON** | LEAD LED |
| **3** | Brit Hi | Electric Bank | **ON** | BRIT HI LED |
| **4** | Modern | Electric Bank | **ON** | MODERN LED |
| **5** | Acoustic Sim | Acoustic Bank | **OFF** | CLEAN LED |
| **6** | Condenser Mic | Acoustic Bank | **OFF** | CRUNCH LED |
| **7** | Dynamic Mic | Acoustic Bank | **OFF** | LEAD LED |
| **8** | Tube Mic | Acoustic Bank | **OFF** | BRIT HI LED |
| **9** | Nylon Mic | Acoustic Bank | **OFF** | MODERN LED |

Rotating clockwise past Position 9 wraps smoothly back to Position 0 (Clean). Rotating counter-clockwise past Position 0 wraps smoothly back to Position 9 (Nylon).

---

## 3. Programmatic 7-Segment Screen Control: The '#' Symbol

The THR front panel features a single-character 7-segment display alongside pitch dots and directional tuning triangles.
Through disassembly of `FUN_0201E1F0`, we discovered that the sharp (`#`) segment can be driven programmatically independently of the alphanumeric character:

```c
/* FUN_0201E1F0(int mode, int sharp_on) */
FUN_0201E1F0(0, 1);  // Illuminates '#' segment
FUN_0201E1F0(0, 0);  // Extinguishes '#' segment
```

We integrated calls to this function directly into the central model dispatcher:
- Whenever a model between 0 and 4 is engaged, `#` lights up on the screen, signaling **Electric Bank**.
- Whenever a model between 5 and 9 is engaged, `#` turns off, signaling **Acoustic Bank**.

---

## 4. Hardware LED Isolation: Solving the Tuner Quirk

### Physical Hardware LED Mapping
Front panel LEDs are driven through `FUN_0201E6F4(int led_id, int state)`. The physical mapping differences between hardware chassis are critical:

```
+-------------------------------------------------------------------------------+
| Logical ID | THR5 Physical Output                | THR10 Physical Output      |
|------------+-------------------------------------+----------------------------|
| 0          | CLEAN LED                           | CLEAN LED                  |
| 1          | CRUNCH LED                          | CRUNCH LED                 |
| 2          | LEAD LED                            | LEAD LED                   |
| 3          | BRIT HI LED                         | BRIT HI LED                |
| 4          | MODERN LED                          | MODERN LED                 |
| 5          | Tuner Left Triangle (Flat)          | BASS LED                   |
| 6          | Tuner Center Dot (In-Tune Green)    | ACO LED                    |
| 7          | Tuner Right Triangle (Sharp)        | FLAT LED                   |
| 8          | Tap Tempo Status Lamp               | Tuner Left Triangle        |
+-------------------------------------------------------------------------------+
```

### The Root Cause of the Tuner Quirk
In early hybrid prototypes, to remap model LEDs 5..9 onto physical faceplate LEDs 0..4 (Clean..Modern), an intercept hook was placed inside `FUN_0201E6F4`:
```arm
; FLAWED HOOK IN GLOBAL LED DRIVER:
subs    r0, r0, #5    ; BUG: 5 -> 0 (Clean), 6 -> 1 (Crunch), 7 -> 2 (Lead)!
```
Because the hardware tuner pitch detection calls `set_led(5)`, `set_led(6)`, and `set_led(7)` to light the tuning triangles and in-tune green dot, this hook subtracted 5, causing the Clean, Crunch, and Lead faceplate LEDs to flash with the guitar notes during tuning!

### The Compartmentalized Fix
In the refined architecture:
1. **`FUN_0201E6F4` is kept 100% factory stock.** The global hardware LED driver is completely unhooked.
2. **Model LED Modulo-5 logic is compartmentalized** exclusively to the two routines that select models:
   - Task 4 Dial Routine at `0x0202BF28`
   - Preset Recall Routine at `0x0201E530`
3. **Clear loops at `0x0202BF22` and `0x0201E52A`** are strictly clamped to `cmp r4, #5`, ensuring the loop only clears model LEDs 0..4 and never touches tuner LEDs 5..7.

---

## 5. Live Potentiometer Tracking: `FUN_0201E83C`

When switching between models on physical hardware, analog potentiometers (Gain, Master, Bass, Middle, Treble) can suffer from "parameter jumps" if the firmware assumes the knobs have not moved.

By calling native cache invalidation routine `FUN_0201E83C` inside the model change handler:
- The firmware clears its cached shadow ADC buffers.
- On the very next Task 4 polling pass, all 11 potentiometers are immediately sampled and applied live to the newly selected model, eliminating sudden volume bursts or tone jumps.
