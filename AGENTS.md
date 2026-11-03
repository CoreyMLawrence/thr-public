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
