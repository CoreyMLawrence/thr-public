# Chapter 8: EEPROM Memory Map & Hardware Unbricking

A complete guide to the 256-byte non-volatile SPI EEPROM, persistent configuration parameters, and the hardware unbricking protocol for recovering frozen hardware.

---

## 1. Onboard Non-Volatile Memory: Renesas R1EX25002 (`IC11`)

Persistent configuration is maintained on an onboard Renesas `R1EX25002` SPI Serial EEPROM labeled `IC11`:

```
           Renesas R1EX25002 (IC11) Pinout
                 +---+-+---+
           /CS --| 1     8 |-- VCC (LEAVE DISCONNECTED DURING EXTERNAL FLASHING!)
          MISO --| 2     7 |-- /HOLD
           /WP --| 3     6 |-- SCK
           GND --| 4     5 |-- MOSI
                 +---------+
```

### Key Technical Specs
- **Capacity:** 2,048 bits (256 Bytes).
- **Organization:** 32 pages of 8 bytes each.
- **Clock Frequency:** Up to 5 MHz SPI.
- **Disassembly Drivers:** `FUN_0201B40C` (EEPROM Read) and `FUN_0201B5BC` (EEPROM Write).

---

## 2. Complete 256-Byte EEPROM Memory Map

Through reverse-engineering and live flash tracing, every functional byte in the 256-byte memory space has been cataloged:

| Byte Offset (`hex`) | Offset (`dec`) | Size | Name / Parameter | Description & Valid Values |
|---|---|---|---|---|
| `0x00` | 0 | 1 Byte | **Startup Model Index** | Default amplifier model loaded on cold boot (`0x00`–`0x09`). |
| `0x01` | 1 | 1 Byte | **Wide Stereo State** | Extended stereo soundstage (`0x00` = Off, `0x01` = On). |
| **`0x02`** | 2 | 1 Byte | **Hardware Boot Sentinel** | Normal Boot = `0x00`. **Forced Update Mode = `0x01`**. |
| `0x03` | 3 | 1 Byte | **Tube Glow Lamps** | Amber simulated tube glow LEDs (`0x00` = Off, `0x01` = On). |
| `0x04` | 4 | 1 Byte | **Preset Slot 1 Active State** | User channel preset slot 1 state. |
| `0x05` | 5 | 1 Byte | **Preset Slot 2 Active State** | User channel preset slot 2 state. |
| `0x06` | 6 | 1 Byte | **Preset Slot 3 Active State** | User channel preset slot 3 state. |
| `0x07` | 7 | 1 Byte | **Preset Slot 4 Active State** | User channel preset slot 4 state. |
| `0x08` | 8 | 1 Byte | **Preset Slot 5 Active State** | User channel preset slot 5 state. |
| `0x09` | 9 | 1 Byte | **Master Speaker Voicing** | Setting `0x02` acoustic resonance curve (`0x28` to `0x40`). |
| `0x0A`–`0x1F` | 10–31 | 22 Bytes | **System Calibration** | Factory potentiometer center calibration and ADC offsets. |
| `0x20`–`0xFE` | 32–254 | 223 Bytes | **User Preset Data** | Stored user parameter blocks (Gain, Master, Tone, Effects). |
| `0xFF` | 255 | 1 Byte | **Factory Verification Byte** | Sentinel checked on power-up to confirm valid factory calibration. |

---

## 3. Emergency Hardware Unbricking Protocol

If an invalid opcode, bad pointer, or Thumb state error freezes the amplifier on power-up before USB MIDI initializes, the physical TAP/TUNER update button combination may become unresponsive.

Because the secondary bootloader (DTAb) in Flash Section 1 remains permanently intact, you can recover the amplifier **100% of the time without desoldering any chip**.

### 3.1 The Magic Byte (`Offset 0x02 = 0x01`)
During early boot, the primary bootloader checks EEPROM offset `0x02`:
- If `data[0x02] == 0x00`: Jumps to main application DTAm (`0x02010000`).
- If `data[0x02] == 0x01`: **Bypasses DTAm completely and jumps directly into the secondary bootloader DTAb**, illuminating a solid `U` on the display!

### 3.2 Wiring to an External Programmer (CH341A / Raspberry Pi / Arduino)

```
           +---------------------------------------------+
           | CH341A USB Programmer                       |
           |                                             |
           |  Pin 1 (CS)   ------------------> IC11 Pin 1|
           |  Pin 2 (MISO) ------------------> IC11 Pin 2|
           |  Pin 4 (GND)  ------------------> IC11 Pin 4|
           |  Pin 5 (MOSI) ------------------> IC11 Pin 5|
           |  Pin 6 (SCK)  ------------------> IC11 Pin 6|
           |                                             |
           |  Pin 8 (VCC)  ---> [LEAVE DISCONNECTED!]   |
           +---------------------------------------------+
```

> [!CAUTION]
> **MANDATORY POWER RULE:**
> **NEVER connect Pin 8 (`VCC`)** to the external programmer's power rail!
> Connecting 3.3V or 5V from USB will back-feed current into the amplifier's digital power plane, tripping USB overcurrent protection and risking SoC damage.
> **Power the amplifier with its own official 15V AC adapter.**

### 3.3 Recovery Sequence
1. Attach SOIC-8 test clip to `IC11` pins 1, 2, 4, 5, and 6 (Pin 8 left open).
2. Plug in the amplifier's 15V AC adapter and turn the power switch ON.
3. Use programmer software (AsProgrammer, Flashrom, or `minipro`):
   - Select chip: `25020` / `25040` (256-byte SPI EEPROM).
   - Read EEPROM and save `eeprom_backup.bin`.
4. In a hex editor, set byte offset `0x02` to `0x01`. Save as `eeprom_armed.bin`.
5. Flash `eeprom_armed.bin` back to `IC11`.
6. Turn amplifier power OFF and remove the programmer clip.
7. Turn amplifier power ON. The display immediately displays **`U`** (Update Mode).
8. Connect USB cable to PC and run `python tools/thr_tool.py flash <verified_firmware.mid>`.
9. The green dot will flash while the firmware is written. When done, `E`, `n`, `d` loops on the display.
10. Power cycle the amplifier to return to full normal operation.
