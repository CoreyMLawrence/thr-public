# Practical Guide 4: Pre-Flight Verification & Flashing

How to verify your patched firmware before flashing, and the safe, step-by-step procedure to flash physical Yamaha THR hardware over USB MIDI.

---

## 1. The Pre-Flight Safety Checklist

Before flashing any binary to real hardware, verify these three essential rules:

```
[ ] 1. Power Supply: Amp is plugged into the official 15V AC adapter (NOT running on AA batteries!).
[ ] 2. Knobs at Zero: Turn all VOLUME, GAIN, and GUITAR output knobs to zero.
[ ] 3. Container Validation: Container passes thr_tool.py verification with zero errors.
```

> [!WARNING]
> **NEVER flash firmware while running on AA battery power!**
> If batteries drop below operating voltage mid-write, the flash cycle will fail, leaving the device in an incomplete state. Always use the 15V AC power supply.

---

## 2. Inspecting & Validating Your MIDI Update Container

Run the inspection tool against your generated `.mid` file to verify its structure before sending:

```powershell
python tools/thr_tool.py inspect --file my_custom_firmware.mid
```

### Expected Output:
```text
file: my_custom_firmware.mid
  messages:   2343
  blocks:     2341
  image size: 1048576 bytes (1.00 MiB)
  erase gap:  16000 ms
  send time:  133 s
  [ok]   global checksum verified
no problems found
```

---

## 3. Step-by-Step Flashing Procedure

### Step 1: Put the Amplifier into Update Mode (`U`)
*(Note: `TAP: TIME` and `TUNER` are the exact same physical button!)*
1. Flip the power switch **OFF**.
2. Press and hold the **`TAP: TIME / HOLD: TUNER`** button.
3. Turn the power switch **ON** while continuing to hold the button until the LED display lights up.
4. Within the next 4 seconds, **press the `TAP: TIME / HOLD: TUNER` button 5 times rapidly**.
5. After about 6 seconds, the amp reboots internally into Update Mode and displays a solid **`U`**.

### Step 2: Start the Flashing Script
Connect the USB cable and run the flash command (specifying `--port THR` or the name reported by `python tools/thr_tool.py ports`):

```powershell
python tools/thr_tool.py flash --port THR --file my_custom_firmware.mid
```

---

## 4. What Happens on the Hardware Display

Watch the single-character LED display on top of the amplifier during the 2.5-minute process:

```
Phase 1: Erase (16 Seconds)          Phase 2: Write (2 Minutes)           Phase 3: Complete
      +-------+                            +-------+                            +-------+
      | <   > |                            |   *   |                            | E n d |
      +-------+                            +-------+                            +-------+
  Both orange tuning                 Green in-tune center dot             Display scrolls 'E', 'n', 'd'
triangles stay lit solid.            flashes rapidly as blocks            in an endless loop. Flash is
Flash sectors are being erased.      are written to NOR Flash.            100% complete and verified!
```

---

## 5. Completing the Update

1. Once the display shows `E`, `n`, `d`, flip the amplifier's power switch **OFF**.
2. Wait 5 seconds.
3. Turn the power switch **ON**.
4. The amplifier will boot up into your new custom firmware immediately!
