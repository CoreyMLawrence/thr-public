# Practical Guide 3: Standalone Hardware Customization & Patching

How to customize your Yamaha THR amplifier's physical hardware behavior directly on the chassis—without needing a computer connected.

---

## 1. Understanding Standalone vs. Computer Control

Before modifying firmware, it is essential to understand what firmware patching is—and what it is not.

### Computer Control (USB MIDI)
When your THR is plugged into a PC or Mac running Yamaha's official **THR Editor** application (or our open-source `thr_live.py` / Web Studio tools), you already have deep access to the DSP engine. Over USB MIDI, you can:
- Toggle compressor algorithms (both vintage Stompbox and Studio Rack modes).
- Change noise gate thresholds.
- Select alternative speaker cabinet simulations.
- Fine-tune modulation speeds, delay times, and reverb parameters.

### Standalone Hardware Customization (Firmware Patching)
The limitation of computer control is that the moment you disconnect the USB cable and carry the amplifier to your couch, rehearsal, or stage, you are entirely reliant on the **physical hardware controls** on the amplifier's top plate.

On compact models like the **THR5 and THR5A**, the physical chassis has no buttons or knobs for the compressor, noise gate, or cabinet selection, and the physical rotary model dial only navigates factory-assigned positions.

**Firmware patching is about physical chassis customization.** It allows you to:
1. **Change standalone hardware behavior:** Reprogram how the physical rotary selector dial, knobs, and buttons respond.
2. **Set permanent standalone defaults:** Hardwire your preferred DSP states (such as active dynamics processing, custom EQ voicings, or bypassed cabinet emulation) so the amplifier sounds exactly how you want it to on power-up, completely standalone without a computer.
3. **Bypass internal stages for external gear:** Customize the signal path (for example, bypassing speaker emulation when routing the headphone/line output into an external power amplifier or recording interface).

---

## 2. The Extensible Developer Boilerplate: `patch_template.py`

Rather than providing an opinionated, pre-baked mod that alters your amplifier in ways you might not want, this repository provides `tools/patch_template.py` as an **extensible starting boilerplate**.

The template contains clean, tested Python helper routines for:
- Mapping Flash memory addresses (`0x02010000` base) to raw binary file offsets.
- Assembling 16-bit and 32-bit Thumb instructions without requiring an external ARM GCC toolchain.
- Safely resolving relative branch targets (`B`, `BNE`, `BEQ`, `BL`).
- Verifying binary integrity with SHA-256 checksums before and after modification.

You can inspect and extend this script to build your own custom modifications.

---

## 3. Customization Examples (Demonstrations)

The following examples demonstrate how specific physical behaviors can be adjusted in the firmware.

### Example A: Customizing Rotary Selector Behavior & Limits
**Concept:** On the physical chassis, the model selector is a continuous quadrature rotary encoder read by RTOS Task 4. The firmware uses signed comparisons to bound the model index.

In Task 4's rotary polling loop:
- Clockwise clamp at `0x0202C474` (File offset: `0x01C474`): Stock instruction `28 05` (`cmp r0, #5`) checks if the model index has reached the upper boundary.
- Counter-clockwise clamp at `0x0202C4E2` (File offset: `0x01C4E2`): Stock instruction `20 04` (`movs r0, #4`) clamps the lower boundary.

By altering these comparison constants in `patch_template.py`, a developer can adjust how the physical rotary selector navigates internal model slots or wrap-around boundaries.

### Example B: Customizing Standalone Boot Defaults (Dynamics / Compressor)
**Concept:** While the studio rack compressor algorithm is accessible over USB MIDI from Yamaha's THR Editor, in standalone mode the compact THR5 initializes with the compressor inactive unless commanded over USB.

In the firmware's dynamics initialization routine (`0x0201A290`):
- Address: `0x0201A292` (File offset: `0x00A292`)
- The stock routine checks model flags before engaging specific dynamics paths.
- By replacing conditional checks with a 16-bit `NOP` instruction (`0x46C0`), developers can configure the physical amplifier to initialize with their preferred dynamics processing active by default when turned on without a computer.

### Example C: Speaker Cabinet Simulation Bypass
**Concept:** When connecting the THR's line/headphone output into a real guitar cabinet or an audio interface running custom IR (impulse response) loader plugins, the built-in speaker cabinet simulation can cause a "double-cabinet" muffled sound.

- The cabinet emulation block is DSP Block 2.
- While you can set Cabinet to bypass (Flat) over USB MIDI using `python tools/thr_live.py set 0x06 6`, you can also configure the firmware's standalone initialization at `0x0201AF88` to boot directly into Flat cabinet mode for dedicated direct-recording rigs.

---

## 4. Step-by-Step Patching Workflow

### Step 1: Extract Raw Binary from Your Factory Backup
Use `thr_tool.py extract` to obtain the raw 1 MiB binary from your factory `.mid` backup:
```powershell
python tools/thr_tool.py extract --file factory_backup.mid --out factory_backup.bin
```

### Step 2: Review and Customize `patch_template.py`
Open `tools/patch_template.py` in an editor. Review the example functions, enable or adjust the modifications you wish to test, and run the script:
```powershell
python tools/patch_template.py factory_backup.bin my_custom_firmware.bin
```

Expected output:
```text
Loaded firmware: 1,048,576 bytes (SHA-256: ...)
[+] Applied custom patch routines
[+] Saved patched binary to my_custom_firmware.bin (SHA-256: ...)
[!] Next step: Package into MIDI container with `python tools/thr_tool.py pack --bin <in.bin> --out <out.mid>`
```

### Step 3: Package into a Flashing Container
Package your modified `.bin` into a Standard MIDI File container using `thr_tool.py pack`:
```powershell
python tools/thr_tool.py pack --bin my_custom_firmware.bin --out my_custom_firmware.mid
```

This utility automatically:
1. Inserts the exact 16,000 ms NOR Flash pre-erase gap.
2. Partitions the binary into 2,341 blocks (448 bytes payload / 512 bytes SysEx).
3. Computes the cumulative Yamaha DTAm checksum.
4. Appends the `DTA1CSUM` terminator.

### Step 4: Validate the Container Structure
Run `thr_tool.py inspect` to confirm the container satisfies all structure requirements before flashing:
```powershell
python tools/thr_tool.py inspect --file my_custom_firmware.mid
```

Once validated, proceed to **[Guide 4: Pre-Flight Verification & Flashing](VERIFY_AND_FLASH.md)** to safely test and install your firmware!
