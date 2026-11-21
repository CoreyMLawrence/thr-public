# Yamaha THR Hybrid Firmware - Stage v53
=========================================
## Dedicated Authentic THR-5A Acoustic & EG Clean Tone Curves

- **Build Date:** November 21, 2026
- **Base Firmware:** Corey's Dumped Custom Firmware (`dumped_custom_amp.bin` / `thr5_custom_restored.bin`)
- **Binary Output:** `thr5_hybrid_v53.bin` (1,048,576 bytes)
- **Container Output:** `thr5_hybrid_v53.mid` (2,343 SysEx messages, 2,341 payload blocks, 16,000 ms pre-erase delay)
- **Reference Acoustic Base:** Authentic Yamaha THR-5A Factory Firmware (`thr5a_stock.bin`)

---

## 1. Executive Summary & Root Cause Analysis

### The Phenomenon Observed
During live parameter testing on dial position 1 (`ACO Acoustic Sim`), sweeping the single front-panel Tone knob clockwise caused the **Bass** value to climb upwards from 50 all the way to **89**. On dial position 0 (`Clean`), sweeping the Tone knob caused Bass to peak at **100**.

### The Root Cause
Teardown of the dumped custom firmware revealed that while Corey had successfully transplanted:
1. The authentic THR-5A DSP audio routing hook (`0x02019E3A` pointing to Coprocessor 5),
2. The acoustic Flat cabinet bypass (`0x0201DFCE`),
3. The 1x12 Deluxe Reverb cabinet (`0x0201DFBE`),
4. The 24-bit Studio Rack Compressor (`0x0201A292`), and
5. The full THR-5A effects suite (`0x0209D100`),

...the **Tone curve lookup tables** in the base firmware were still pointing to the factory electric THR-5 tables:
- **Model 0 (Clean):** Pointed to `0x0204EE34` (Stock Electric Clean curve) -> $k=0$ `(53, 45, 37)` $\to$ $k=50$ `(50, 60, 69)` $\to$ $k=100$ `(100, 73, 75)`.
- **Model 1 (ACO):** Pointed to `0x0204F092` (Stock Electric Crunch curve) -> $k=0$ `(50, 26, 50)` $\to$ $k=50$ `(61, 35, 65)` $\to$ $k=100$ `(89, 75, 71)`.

In an electric high-gain crunch amp, Yamaha intentionally boosts low-end resonance as the tone control opens up to simulate cabinet thump. But on an acoustic guitar amplifier or acoustic microphone model, this causes acoustic boomy feedback and uncontrolled low-frequency mud!

---

## 2. The Authentic THR-5A Acoustic Tone Engineering

In genuine factory Yamaha THR-5A acoustic firmware (`thr5a_stock.bin`):
- **Model 1 (Acoustic 1 - Condenser Mic, `0x0205087A`):**
  - **Knob = 0% (Counter-Clockwise):** Low 60, Mid 35, High 30. (Warm, full body, gentle high roll-off).
  - **Knob = 50% (Noon / 12 O'Clock):** Low 50, Mid 50, High 50. (Perfect flat studio reference response).
  - **Knob = 100% (Fully Clockwise):** Low 55, Mid 60, High 100. (Air, sparkle, and open acoustic presence without low-end runaway).
- **Model 0 (EG Clean, `0x0205061C`):**
  - **Knob = 0%:** Low 60, Mid 35, High 20.
  - **Knob = 50%:** Low 50, Mid 45, High 40.
  - **Knob = 100%:** Low 55, Mid 60, High 70. (Eliminates the 100% electric bass spike).

---

## 3. What Stage v53 Changes

In `thr5_hybrid_v53.bin`:
1. **Model 1 Tone Table at `0x0204F092` (ROM offset `0x0003F092`, 606 bytes):**
   - In-place replacement with authentic THR-5A Condenser curve from `thr5a_stock.bin` (`0x0205087A`).
2. **Model 0 Tone Table at `0x0204EE34` (ROM offset `0x0003EE34`, 606 bytes):**
   - In-place replacement with authentic THR-5A EG Clean curve from `thr5a_stock.bin` (`0x0205061C`).
3. **Models 2..4 (Lead, Brit Hi, Modern):**
   - 100% untouched stock electric curves preserved for rock punch.
4. **Section 0 & 1 (`0x02000000`–`0x0200FFFF`):**
   - 100% byte-for-byte untouched.
5. **Exact Diff Footprint:**
   - Exactly 1,212 bytes modified (strictly the two 606-byte tone tables). Zero bytes modified elsewhere.

---

## 4. Verification & Pre-Flash Safety Gates

All 4 Pre-Flash Safety Gates are verified via `python3 verify_v53.py`:
- **Gate 1 (Unicorn CPU Emulation):** Passed. Stock boot reaches `0x0202AFF6` with 0 EEPROM writes; Modulo 5 helper verified; Tone lookup routine across all models (0..4) and knob values (0..100) produces exact acoustic and electric DSP values with zero CPU exceptions.
- **Gate 2 (Opcode Boundary & Alignment Audit):** Passed. Critical opcode at `0x0202C490` verified as `0x4D86`; Tone table literal pointers and instructions verified.
- **Gate 3 (Container Validation):** Passed. Exactly 2,343 SysEx messages, 2,341 blocks, 16,000 ms pre-erase delay, global checksum match.
- **Gate 4 (Binary Difference Audit):** Passed. 100% of modified bytes accounted for within tone table boundaries.

---

## 5. How to Flash

1. **Safety First:** Confirm the official 15V AC power adapter is plugged in.
2. **Boot into Update Mode (`U`):**
   - Turn amplifier power **OFF**.
   - Press and hold the **`TAP: TIME / HOLD: TUNER`** button.
   - Turn power **ON** while continuing to hold the button.
   - Within 4 seconds, tap **`TAP: TIME / HOLD: TUNER`** **5 times rapidly**.
   - Wait ~6 seconds; the LED display will show **`U`**.
3. **Run the Flash Tool:**
   ```bash
   python3 thr_tool.py flash --port THR --file firmware-lab/stage-v53/thr5_hybrid_v53.mid
   ```
4. **Reboot:** When flashing completes (display shows end of update), cycle power OFF and back ON into normal play mode.
