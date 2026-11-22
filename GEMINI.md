# AGENTS.md: Rules & Safety Guidelines for AI Coding Assistants

This repository develops tools, reverse-engineers protocols, and creates custom firmware patches for physical Yamaha THR desktop guitar amplifiers (specifically the **Yamaha THR5 and THR5A**).

If you are an AI assistant (such as Claude, ChatGPT, Cursor, Copilot, Gemini, or Antigravity) assisting a user in this codebase, you **must strictly adhere to the safety boundaries, hardware facts, and verification protocols defined in this document**.

The target hardware has no dual-bank boot failover. A single invalid instruction in boot-critical code paths will freeze the physical hardware on power-up.

---

## 1. Verified Hardware Facts & Scope Boundaries

Always adhere to these verified physical facts. Never hallucinate or generalize beyond them:
1. **Physical Testing Scope:**
   - All physical hardware teardowns, EEPROM hookups, and test runs in this project were conducted on a physical **Yamaha THR5A**.
   - We empirically proved that official factory stock **THR5 (Version 2 electric)** firmware boots and runs natively on the THR5A hardware without hardware modifications.
   - **Do NOT claim that the physical hardware of the THR10, THR10C, or THR10X is identical.** The THR10 series has a distinctly different physical form factor (different chassis, 5 user preset memory buttons, extra tone knobs, and an 8-position selector dial). While the software container format (DTAm/DTAb) and SysEx protocol are shared across the family, our verified circuit specifications apply **strictly to the THR5 and THR5A platform**.
2. **Single Front Panel Button:**
   - On the Yamaha THR chassis, `TAP: TIME` and `TUNER` are **the exact same physical push-button**. There is only one button (`PANEL_BUTTON_TAPTEMPO`).
   - Tapping it sets delay tempo. Holding it toggles the tuner.
3. **Hardware Update Mode Sequence (`U`):**
   - Start with power **OFF**.
   - Press and hold the **`TAP: TIME / HOLD: TUNER`** button.
   - Turn power **ON** while holding the button until the LED display lights up.
   - Within 4 seconds, **press the `TAP: TIME / HOLD: TUNER` button 5 times rapidly**.
   - After about 6 seconds, the amplifier soft-reboots into Update Mode, displaying a solid **`U`**.
4. **Onboard Non-Volatile EEPROM (`IC11`):**
   - Chip: Renesas `R1EX25002` (256-byte SPI EEPROM, SOIC-8).
   - Pin 1 (`/CS`), Pin 2 (`MISO`), Pin 4 (`GND`), Pin 5 (`MOSI`), Pin 6 (`SCK`).
   - Writing byte **`0x01` to offset `0x02`** forces the hardware directly into Update Mode (`U`) on next boot, providing a 100% reliable hardware unbricking path.
   - **MANDATORY HARDWARE POWER RULE:** When connecting an external programmer (e.g. CH341A) to `IC11`, **Pin 8 (`VCC`) MUST BE LEFT DISCONNECTED**. Power the amplifier with its official **15V AC adapter** to prevent back-powering digital rails.

---

## 2. Absolute Prohibitions for AI Agents

* **NEVER modify Flash Section 0 or Section 1 (`0x02000000` to `0x0200FFFF`).** These sections contain the primary bootloader and secondary USB updater (DTAb).
* **NEVER execute an indirect register branch (`BX Rm` or `BLX Rm`) to an even address.** On ARM7TDMI, Bit[0] MUST be 1 (`addr | 1`) to preserve Thumb execution mode. Branching to an even address forces 32-bit ARM mode on 16-bit Thumb code, causing an immediate `INVSTATE` CPU instruction trap on boot!
* **NEVER insert branches or hooks into Task 4 dial polling loops that do not converge on `0x0202C490` (`0x4D86`).**
* **NEVER hook `0x0201E6F4` (global `set_led`) to remap model LEDs.** That is the global hardware LED driver. Hooking it inadvertently redirects tuner pitch indicators (LEDs 5, 6, 7) into the Clean, Crunch, and Lead faceplate LEDs. Model LED remapping must be placed strictly in the dial rotation handler (`0x0202BF28`) and preset recall routine (`0x0201E530`).
* **NEVER propose flashing while running on battery power.** Always mandate the official 15V AC adapter.
* **NEVER propose flashing an unverified binary.** All 4 Pre-Flash Safety Gates must be satisfied.

---

## 3. The 4 Mandatory Pre-Flash Safety Gates

Before advising any user to flash a modified binary or container:

1. **Gate 1 — CPU Emulation:** Verify with Unicorn CPU emulation that the execution path from reset through Task 4 dial loops and preset recalls runs with zero invalid instruction traps or CPU exceptions.
2. **Gate 2 — Opcode Boundary Verification:** Disassemble modified regions. Ensure 16-bit and 32-bit Thumb alignment. Verify all register branch targets have Bit[0] set to 1. Verify address `0x0202C490` holds valid opcode `0x4D86`.
3. **Gate 3 — SMF Container Validation:** Validate the `.mid` container using `thr_tool.py inspect`:
   - Exactly 2,343 MIDI SysEx events.
   - Exactly 2,341 payload blocks carrying 448 bytes payload (512 bytes SysEx).
   - Exact 16,000 ms pre-erase delay.
   - Global DTAm cumulative checksum match.
4. **Gate 4 — Binary Difference Audit:** Compare the patched `.bin` against pristine factory stock and account for 100% of modified bytes.

---

## 4. Tool Execution Reference for AI Agents

All tools are written in Python 3 and require `mido` and `python-rtmidi`. Always use exact arguments:

```powershell
# 1. List connected MIDI ports:
python tools/thr_tool.py ports

# 2. Self-test the firmware codec (no amp needed):
python tools/thr_tool.py selftest

# 3. Dump running firmware from hardware in Update Mode ('U'):
python tools/thr_tool.py dump --port THR --out factory_backup.mid

# 4. Extract raw 1 MiB binary from a .mid update container:
python tools/thr_tool.py extract --file factory_backup.mid --out factory_backup.bin

# 5. Apply relocatable patch recipe to raw binary:
python tools/patch_template.py factory_backup.bin my_patched_fw.bin

# 6. Package patched raw binary into a flashable .mid container:
python tools/thr_tool.py pack --bin my_patched_fw.bin --out my_patched_fw.mid

# 7. Inspect and validate .mid container structure:
python tools/thr_tool.py inspect --file my_patched_fw.mid

# 8. Flash validated container to amplifier in Update Mode ('U'):
python tools/thr_tool.py flash --port THR --file my_patched_fw.mid

# 9. Real-time parameter monitor in normal play mode:
python tools/thr_live.py listen
```

---

## 5. Web Studio Status Notice

The browser application in `web-studio/` is an **unfinished, experimental beta proof-of-concept**. It was built to demonstrate reverse-engineered SysEx control and settings-block model injection. Do not present it as a finished commercial product.

---

## 6. Physical 16x2 LCD Screen Directives for AI Agents

This hardware host is equipped with an attached **16x2 I2C LCD character screen** (at address `0x3F`) running directly via `http://localhost/api` (and Python helper `thr_lcd.py`).

> [!IMPORTANT]
> **CORE USER DIRECTIVE FOR ALL AI AGENTS:**
> **The screen MUST be used as a verbose communication method with the user as much as possible.**
> Never leave the physical screen blank, stale, or static. Treat it as your real-time hardware status and telemetry display for Corey across every task.

### Mandatory Rules for Screen Usage:
1. **Verbose Real-Time Action Feedback:**
   Whenever an agent runs builds, analyses, tests, firmware dumps, flash cycles, or parameter monitors, actively push progress updates to the screen:
   - **Code Analysis / Inspections:** `thr_lcd.set_text("Analyzing Tone", "Scanning M0..M4")`
   - **Firmware Compilation:** `thr_lcd.set_text("Building v53...", "Patching Tables")`
   - **Safety Gate Verification:** `thr_lcd.set_text("Verifying Gates", "Gate 1: Emulate")`
   - **Waiting for Hardware / User Action:** `thr_lcd.set_text("Waiting for [U]", "Hold TAP & Power")`
   - **Pre-Flash Alerts:** `thr_lcd.flash_alert(times=2); thr_lcd.set_text("Pre-Flash OK", "Ready to Stream")`
   - **Task Completion:** `thr_lcd.set_text("Task Complete!", "All Checks Pass")`

2. **Visual Progress & Loading Bars:**
   - **Never output raw silent delays.** Every long-running operation (flash erase, block streaming, ROM dumping, multi-suite emulation) must render a dynamic progress bar on Line 2 with percentage and elapsed time on Line 1.
   - Example 16x2 display layout:
     ```text
     Flash:  65%  24s
     [========>     ]
     ```
   - Use dedicated helpers in `thr_lcd.py`:
     ```python
     import thr_lcd
     thr_lcd.show_flash_erase(elapsed_sec, total_sec=16.0)
     thr_lcd.show_flash_streaming(current_block, total_blocks=2341, elapsed=elapsed_sec)
     thr_lcd.show_flash_done()
     ```

3. **Tool Integration:**
   - All newly authored automation scripts, flashers, watchers, and bench tools must import `thr_lcd` and update the physical screen dynamically.

---

## 7. Flashing Protocol, Progress Bars & Fast-Flash Timing Rules

Flashing physical Yamaha THR hardware requires strict adherence to container structure, timing safety, and live telemetry:

### 1. Step-by-Step Flashing Protocol with Progress Bars:
Every firmware flasher (e.g. `thr_tool.py flash` or stage flasher `flash_*.py`) must render a structured, 3-phase progress display on **both the terminal AND the physical 16x2 LCD**:
- **Step 1/3: NOR Flash Sector Erase (16.0s)**
  - Send `DTA1ERASE` message.
  - Display animated countdown and progress bar on terminal and LCD (`thr_lcd.show_flash_erase`).
  - Terminal: `[Step 1/3] Erase NOR Flash: [====================] 100% | 16.0s / 16.0s [COMPLETE]`
  - LCD: `Line 1: Erase:  12s  25%` | `Line 2: [===>        ]`
- **Step 2/3: Streaming Payload Blocks (2,341 blocks)**
  - Stream `DTA1MAIN` payload blocks at defined block interval.
  - Update progress bar, transfer rate (blocks/sec), elapsed time, and ETA every 10–15 blocks on terminal and LCD (`thr_lcd.show_flash_streaming`).
  - Terminal: `[Step 2/3] Stream Payload:  [============>       ]  65% | 1521/2341 (22.8s, 31.4 blk/s, ETA: 12.2s)`
  - LCD: `Line 1: Flash:  65%  23s` | `Line 2: [=========>   ]`
- **Step 3/3: Checksum Terminator & Completion**
  - Send `DTA1CSUM` terminator.
  - LCD: `thr_lcd.show_flash_done()` (flashes backlight twice, displays `Flash Complete!` / `Please Reboot`).
  - Terminal: Prompt user to observe `E - n - d` looping on the THR 7-segment display and power cycle.

### 2. Fast-Flash Timing Rules:
- **`ERASE_GAP_MS` MUST ALWAYS BE 16,000 ms (16 seconds).** Never reduce, shorten, or strip this delay. The onboard NOR flash requires 16 seconds to safely erase Section 2 sectors. Sending data during erase corrupts flash.
- **`BLOCK_GAP_MS` CAN BE SET AS LOW AS 15 ms (Fast Flash).** Factory Yamaha tools use 50 ms per block (~133s total send time). We empirically verified that 15 ms per block streams cleanly with zero block dropouts, reducing total transmission time to **~51 seconds** (over 2.5× faster).
- `thr_tool.py pack` supports `--gap-ms <ms>` (default 50, fast 15).

---

## 8. Tone Curve Architecture & Acoustic Voicing Calibration

The Yamaha THR tone stack uses model-specific lookup tables rather than generic software filters:

1. **Table Structure & Sizing:**
   - Each model has a dedicated 606-byte table ($101 \times 6$ bytes: 101 positions 0%..100%).
   - Each entry contains three big-endian 16-bit integers:
     - `+0`: **Bass** (`CC 0x83` in DSP)
     - `+2`: **Middle** (`CC 0x84` in DSP)
     - `+4`: **Treble** (`CC 0x85` in DSP)
   - Jump table at `0x0204B680` reads model index `r0` (0..4), loads tone table pointer from literal pool (`0x0204B834`..`0x0204B844`), and calls `FUN_0201D1D4` for Bass, Mid, and Treble.

2. **Acoustic vs. Electric Tone Behavior:**
   - **Authentic THR-5A Acoustic Curves (Condenser `0x0205087A`, EG Clean `0x0205061C`):**
     - **0% (Counter-Clockwise):** Low 60, Mid 35, High 30 (Warm body resonance, gentle high roll-off).
     - **50% (Noon):** Low 50, Mid 50, High 50 (Flat reference response).
     - **100% (Fully Clockwise):** Low 55, Mid 60, High 100 (Full acoustic air/sparkle, tight controlled bass).
   - **Electric Curves (Stock Crunch `0x0204F092`, Clean `0x0204EE34`):**
     - Electric Crunch intentionally boosts Lows up to **89** to simulate speaker cabinet thump.
     - Electric Clean boosts Lows up to **100**.
     - **Crucial Rule:** Never leave electric tone tables on acoustic models (e.g. Model 1 ACO), or bass will run away into boomy feedback when the Tone knob is cranked.

---

## 9. Live Parameter Telemetry, Inverted Switches & Blend Zones

When building monitors, daemons (`thr_detector.py`), or companion UIs:

1. **Inverted Bypass Switches:**
   - On the Yamaha THR SysEx protocol, bypass switches are **inverted**:
     - `0` = **Active / Engaged / ON**
     - `127` = **Bypassed / Disengaged / OFF**
   - Applies to Compressor bypass (`0x10`), Modulation bypass (`0x20`), Delay bypass (`0x30`), and Reverb bypass (`0x40`).

2. **Knob Blending Zones:**
   - **Knob 5 (Effect):** Blends Compressor (0..50%) and Chorus (50..100%). Around 40..60%, both effects can be active simultaneously (`CMP+CHO`).
   - **Knob 3 (Dly/Rev):** Blends Delay (0..50%) and Reverb (50..100%). Around 40..60%, both effects can be active simultaneously (`DLY+REV`).
   - Telemetry must check both bypass state AND knob zone so inactive effects are properly erased from the display.

3. **Parameter Addresses:**
   - **Reverb Level:** Listens on `0x4B` for Hall/Plate (THR5A) and `0x41` for Spring (THR5).
   - **Delay Level:** Strictly on `0x38`.
   - **Chorus Mix:** Strictly on `0x23`.
   - **Rack Compressor Threshold:** Raw values sweep from 500 (0% min comp) down to 350 (100% max comp). Normalize to 0..100%.

4. **Tone Draining & LCD Formatting:**
   - Coalesce rapid Tone updates by draining `port_in.iter_pending()` in a single pass.
   - Display Tone parameters in Low $\to$ Mid $\to$ High order: `L:XX M:YY H:ZZ` (16 characters, zero flicker).

---

## 10. Hardware Connection Modes: Distinguishing Tuner Mode vs. Update Mode ('U')

Software and daemons (`thr_detector.py`) must never assume that "silence on MIDI means Update Mode". On the Yamaha THR platform, three distinct connection states exist:

### 1. The Three Operating States:
| State | Active Firmware | 7-Seg Display | Periodic Heartbeat? | Responds to `DTA1ROMR`? | Audio State | How to Exit |
|---|---|---|---|---|---|---|
| **Normal Play** | `DTAm` (Main App) | Preset # or Model | **Yes** (`43 7D 60 44 54 41...`) | No | Active | Hold TAP/TUNER or Power Off |
| **Tuner Mode** | `DTAm` (Main App) | Note (`A`,`b`,`C`...) / `--` | **No** (Suspended for pitch detection) | **No** (DTAb not running) | **Muted** | Tap `TAP/TUNER` (resumes heartbeats) |
| **Update Mode ('U')** | `DTAb` (Bootloader) | Solid `U` | **No** (Never sends heartbeats) | **Yes** (Streams `DTA1MAIN`) | Uninitialized | Power Cycle or Flash Firmware |

### 2. Physical Button Operation:
- **`TAP: TIME` and `TUNER` are the exact same physical button.**
- **During Normal Operation:** Holding the button for ~1.5s engages the chromatic guitar tuner. The amp mutes audio and suspends heartbeat broadcasts to give 100% priority to pitch detection. Tapping it again un-mutes audio and immediately restores heartbeats.
- **At Power-On:** Holding the button while turning power ON (and pressing 5 times rapidly) triggers a reboot into the secondary bootloader (`DTAb`), displaying `U`.

### 3. Active Two-Way Probing Algorithm:
When a THR MIDI port is present but heartbeats are absent:
1. Send `DTA1ROMR` bootloader inquiry (`[0x43, 0x7D, 0x50, 0x44, 0x54, 0x41, 0x31, 0x52, 0x4F, 0x4D, 0x52, 0x02]`).
2. Listen for up to 300 ms:
   - If a SysEx packet containing `b"DTA1MAIN"` arrives: The amp is running `DTAb`. Classify as **UPDATE MODE ('U')**.
   - If NO packet arrives: The amp is running `DTAm` with tuner engaged. Classify as **TUNER MODE**.
3. **In-Flight Normal Play Monitoring:** If heartbeats pause for > 3.5s while the USB connection remains intact:
   - Probe `DTA1ROMR`: if no answer, immediately transition display to `THR5: Tuner Mode` / `Muted / Tuning..`.
   - When the user taps `TAP/TUNER` to exit tuner, heartbeats resume. The daemon clears the display override immediately without dropping ports or re-initializing.

### 4. Mandatory 16x2 LCD UI Presentation:
- **When Tuner Mode is active:**
  - `Line 1:` `THR5: Tuner Mode`
  - `Line 2:` `Muted / Tuning..` (alternating with `Tap to Exit     `)
- **When Update Mode ('U') is active:**
  - `Line 1:` `THR in [U] Mode!`
  - `Line 2:` `Ready to Flash` (alternating with `Firmware Lab`)


