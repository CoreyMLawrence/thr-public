# Chapter 11: Python Tooling & Automation Guide

A practical user guide for the cross-platform command-line tools included in the `tools/` directory.

---

## 1. Prerequisites & Environment Setup

All tools are written in standard Python 3.8+ and require `mido` and `python-rtmidi` for USB MIDI communication:

```powershell
pip install mido python-rtmidi
```

---

## 2. Firmware Container Utility: `thr_tool.py`

`thr_tool.py` is the primary utility for extracting, unpacking, packing, validating, and flashing firmware.

### Command Reference

#### 1. Extract Firmware from Physical Amplifier (`dump`)
Extracts the amplifier's currently running DTAm firmware over USB MIDI:
1. Boot the amp into Update Mode (`U`): Turn power ON while holding the `TAP: TIME / HOLD: TUNER` button, then press it 5 times rapidly within 4 seconds. After 6 seconds, the display shows `U`.
2. Run:
   ```powershell
   python tools/thr_tool.py dump --port THR --out my_firmware.mid
   ```
   *Execution takes approximately 2.5 minutes while the amp streams 2,343 SysEx messages.*

#### 2. Extract Raw Binary Image (`extract`)
Converts the `.mid` container into a raw 1,048,576-byte (`1 MiB`) executable binary image:
```powershell
python tools/thr_tool.py extract --file my_firmware.mid --out my_firmware.bin
```

#### 3. Package Raw Binary into MIDI Container (`pack`)
Packages a modified `.bin` firmware file into a Standard MIDI File (`.mid`) update container with 16,000 ms pre-erase delay, 2,341 blocks, and global checksum:
```powershell
python tools/thr_tool.py pack --bin modified_fw.bin --out modified_fw.mid
```

#### 4. Validate MIDI Container Structure (`inspect`)
Validates that a `.mid` container conforms to all timing, checksum, and structure requirements:
```powershell
python tools/thr_tool.py inspect --file modified_fw.mid
```

#### 5. Flash Firmware Update to Physical Hardware (`flash`)
Flashes the target `.mid` container to the amplifier over USB MIDI:
1. Boot the amp into Update Mode (`U`).
2. Run:
   ```powershell
   python tools/thr_tool.py flash --port THR --file modified_fw.mid
   ```
3. The LED display will show the tuning triangles during the 16-second erase phase, then the green dot will flash during the 2-minute write phase. Upon completion, the screen displays `E`, `n`, `d`.

---

## 3. Real-Time MIDI Monitor & Control: `thr_live.py`

`thr_live.py` provides real-time bidirectional communication with an amplifier running in normal mode.

### Live Parameter Sniffer (`listen`)
Monitors all incoming parameter changes as you turn physical knobs:
```powershell
python tools/thr_live.py listen
```

### Real-Time Parameter Adjustment (`set`)
Sends a single volatile parameter command (`SubID 0x10`) to active RAM:
```powershell
# Set Gain (Param 0x01) to 75
python tools/thr_live.py set 0x01 75

# Set Master Volume (Param 0x02) to 50
python tools/thr_live.py set 0x02 50
```

### Non-Volatile Preference Toggle (`set-pref`)
Sends a system preference command (`SubID 0x30`) that writes directly to EEPROM:
```powershell
# Toggle Wide Stereo: 1 = On, 0 = Off
python tools/thr_live.py set-pref wide_stereo 1

# Toggle Tube Glow Amber Lamps: 1 = On, 0 = Off
python tools/thr_live.py set-pref tube_lamp 1

# Set Speaker Voicing Curve (Setting 0x02): 0x28 to 0x40
python tools/thr_live.py set-pref speaker_voicing 0x30
```

---

## 4. Settings Block Decoder: `thr_map.py`

Decodes the active 276-byte bulk state packet from the connected amplifier into human-readable parameters:
```powershell
python tools/thr_map.py dump
```
Outputs model name, gain, tone stack positions, cabinet emulation type, active modulation, delay times, and noise gate threshold.

---

## 5. Developer Patch Boilerplate: `patch_template.py`

An extensible starter script demonstrating how to assemble relocatable Thumb machine code and apply patches to an extracted `.bin` file without requiring an external GCC cross-compiler:
```powershell
python tools/patch_template.py factory_backup.bin my_custom_firmware.bin
```
Features built-in helpers for:
- Safe Flash-to-file offset calculation (`addr - 0x02010000`).
- Computing 32-bit Thumb `BL` relative branch offsets.
- Assembling conditional branches (`BNE`, `BEQ`, `BGT`, `BLT`).
- Binary integrity tracking with SHA-256 hashes before and after modification.
- Automated next-step guidance for container packaging via `thr_tool.py pack`.
