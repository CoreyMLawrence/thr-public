# Yamaha THR Custom Firmware - Stage v54
## Dedicated Authentic Tone Curves + Cabinet Block 2 Signal Path Fix

### 1. Breakthrough Discovery: Clean Signal Path Root Cause
When examining `dumped_custom_amp.bin` to investigate harsh high frequencies on Model 0 Clean, disassembly of the Clean model initialization routine (`FUN_0201A104` at file offset `0x00A104` / RAM `0x0201A104`) revealed a critical bug in the DSP signal routing.

#### The THR DSP Architecture:
- **DSP Block 4:** Electric Preamp Simulation
- **DSP Block 5:** Acoustic Coprocessor Simulation
- **DSP Block 2:** Speaker Cabinet Simulation (1x12 Deluxe, 2x12 British, 4x12, etc.)

#### The Bug in `dumped_custom_amp.bin`:
At file offset `0x00A15C`:
```arm
0x0201A15C:  movs r1, #5         ; r1 = 5 (intended Cab 5: 1x12 Deluxe)
0x0201A15E:  mov  r3, sp
0x0201A160:  strh r1, [r2]       ; writes 5 to cab index (*DAT_0201a1d8)
0x0201A162:  strh r1, [r3]       ; WRITES 5 TO [sp] (DSP Block Parameter)!
0x0201A164:  movs r1, #5
...
0x0201A17C:  mov  r0, sp
0x0201A17E:  bl   #0x203fa58     ; FUN_0203FA58 loads cabinet into DSP block [sp]
```
In stock Yamaha electric firmware (`thr5_stock.bin`), Cab 2 (2x12 British) was used, so `r1 = 2` was written to both `[r2]` (cab index) and `[r3]` (DSP block 2).
When an earlier developer modified the instruction to `movs r1, #5` to select Cab 5 (1x12 Deluxe), `strh r1, [r3]` inadvertently instructed `FUN_0203FA58` to load the cabinet simulation into **DSP Block 5** instead of **DSP Block 2**!

As a result:
- **DSP Block 2 (Cabinet Block) was NEVER initialized!**
- Model 0 Clean had **ZERO speaker cabinet emulation**.
- The raw, unfiltered preamp distortion and digital fizz (5 kHz – 20 kHz) was blasting directly through the speakers without any 1x12 speaker cone low-pass filtering.
- When an authentic, brighter tone curve was applied, the missing cabinet filter made the highs piercingly abrasive.

---

### 2. The Stage v54 Signal Path Fix
At file offset `0x00A15C`, Stage v54 applies the following 10-byte patch:
```
Raw bytes: 21 02 46 6b 80 19 21 05 80 11
```
Which disassembles cleanly to:
```arm
0x0201A15C:  movs r1, #2         ; r1 = 2 (DSP Block 2 = Cabinet Block!)
0x0201A15E:  mov  r3, sp
0x0201A160:  strh r1, [r3]       ; [sp] = 2 (Engages Cabinet Block 2!)
0x0201A162:  movs r1, #5         ; r1 = 5 (Cab 5 = 1x12 Deluxe)
0x0201A164:  strh r1, [r2]       ; *r2 = 5 (Cabinet Index 5)
```
- **Result:** DSP Block 2 is now properly instantiated with the 1x12 Deluxe cabinet impulse response, rolling off harsh frequencies above 4.5 kHz naturally and restoring warm, authentic Fender Deluxe Reverb tone.

---

### 3. Dedicated Authentic Tone Curves
- **Model 0 (Clean):** Authentic THR-5A EG Clean curve (`0x0205061C` -> `0x0204EE34`).
  - Warm low end, neutral mids, smooth treble (Bass 60->50->55, Mid 35->45->60, Treble 20->40->70).
- **Model 1 (ACO):** Authentic THR-5A Acoustic 1 Condenser curve (`0x0205087A` -> `0x0204F092`).
  - Studio condenser response (Bass 60->50->55, Mid 35->50->60, Treble 30->50->100).
- **Models 2..4 (Lead, Brit Hi, Modern):** Stock THR5 electric tone curves preserved byte-for-byte.

---

### 4. Binary & Container Specifications
- **Target Binary:** `thr5_hybrid_v54.bin` (1,048,576 bytes)
  - `SHA-256`: `b08997f5189f28cf9fe1a4feb955cc069303b4ba1886610ade6203cd6c3640e8`
- **MIDI SMF Container:** `thr5_hybrid_v54.mid` (1,252,286 bytes)
  - `SHA-256`: `98947140a49d62b4594cdb729a6cf53ec7801643f24c606c8d30db48445093e0`
  - Total SysEx Messages: 2,343
  - Data Blocks: 2,341
  - Erase Delay: 16,000 ms (strict NOR flash erase delay)
  - Block Gap: 15 ms (accelerated flash timing, ~51s total transmission)

---

### 5. Verification & Safety Gates
All 4 Pre-Flash Safety Gates verified 100% cleanly:
1. **Gate 1 (Unicorn Emulation):** All 6 subtests passed cleanly (subtest 1A, 1B, 2, 3, 4, 5).
2. **Gate 2 (Opcode Audit):** Critical opcode `0x4D86` at `0x0202C490`, cabinet patch alignment, tone routine disassembly verified.
3. **Gate 3 (Container Audit):** 2,343 messages, 2,341 blocks, 16.0s erase gap, global checksum verified.
4. **Gate 4 (Diff Audit):** Exactly 594 bytes modified across 1MB image, 100% strictly confined to Cabinet patch (10 bytes) and tone tables (1,212 bytes). Vector table and early boot 100% untouched.
