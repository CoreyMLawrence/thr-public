# Yamaha THR Reverse Engineering: Further Discoveries and Related Work

## Purpose and Context

Michael Forney's [`michaelforney/thr10`](https://github.com/michaelforney/thr10) is an important reference for anyone studying Yamaha THR firmware. Published in 2014–2016, it demonstrated that the Yamaha THR10 main application firmware (DTAm) could be dumped over USB MIDI SysEx, modified, and reflashed without replacing the primary bootloader (DTAb). The repository also includes useful C and Lua tooling, symbol notes for the THR10C `ver104c_20120803` build, and a practical example of adding a button-combination hook in `patch.c`.

This document is intended as a companion for readers who have reviewed Forney's work and want to explore related investigations carried out on THR5 and THR5A firmware. It records observations, experiments, and tools that extend the same general line of inquiry into hardware compatibility, DSP behavior, persistent settings, recovery, validation, and user interfaces. It is not intended as a ranking of projects or as a replacement for Forney's documentation.

## Areas for Further Exploration

The topics below may be useful starting points when moving from the THR10C examples in Forney's repository to other hardware revisions and firmware builds.

### 1. Firmware Interoperability and Platform Compatibility

Experiments with physical Yamaha THR5A hardware found that official THR5 (Version 2 electric) firmware boots and operates on the device without hardware modification. The experiments suggest that the microcontroller peripherals, Flash layout, audio codec I2S connections, potentiometer ADCs, and DSP coprocessor registers are shared across these firmware distributions.

Device identity and behavior—including heartbeat SysEx identity (`0x30` for THR5 and `0x34` for THR5A), default model tables, and rotary-switch names—appear to be controlled by software tables in `DTAm`. This makes cross-model firmware behavior an interesting area for careful, device-specific testing.

### 2. Settings-Block SysEx Behavior

Forney's repository provides a useful foundation for understanding Yamaha's USB MIDI SysEx flashing protocol. Additional work examined the live parameter and settings paths used after firmware has started:

1. The parameter command path (`F0 43 7D 10 41 30 01 <param> <val> F7`) applies validation to model indices.
2. The settings-block path (`F0 43 7D 20 44 54 41 31 ... 00 ... F7`) loads a complete amplifier state into memory.

In the firmware examined here, the settings-block loader does not apply the same range checks to the amp-model byte (offset 128) and cabinet-model byte (offset 134). Carefully constructed settings blocks can therefore select additional DSP models already present in the image, including Bass, Acoustic, Flat, and alternate VCM voicings. This is a useful example of how different control paths can expose different behavior without changing the ROM.

### 3. Rotary Selector and Model-Bank Experiments

The THR5 rotary control was examined as a continuous quadrature or gray-code input polled by Task 4. In the stock firmware, a signed modulo-5 helper at `0x020171CC` and associated wrap logic constrain the visible model range.

An experimental in-place patch changed the arithmetic to support ten positions, with the following bank layout:

- Positions 0–4: Clean, Crunch, Lead, Brit Hi, and Modern
- Positions 5–9: Acoustic Sim, Condenser, Dynamic, Tube, and Nylon

The associated wrap points examined were `0x0202C474` and `0x0202C4E2`. These experiments may be of interest to readers studying how physical controls, model tables, and firmware bounds interact.

### 4. DSP Coprocessor Dispatch

Forney identified a high-level `dsp_command(union dsp_command *cmd)` entry point at `0x203D988` in the THR10C build. Further tracing in THR5 firmware followed the command flow toward a lower-level dispatcher identified as `FUN_020184E6(coproc, block, param, val)`.

The observed block organization was:

- Block 0: Preamp and model DSP algorithm loading
- Block 1: Master tone curves, chassis EQ, and speaker voicing
- Block 2: Speaker cabinet emulation
- Block 3: Modulation effects
- Block 4: Delay and reverb
- Block 5: Compressor dynamics
- Block 6: Noise gate dynamics

This provides another route for investigating the relationship between high-level SysEx commands, firmware routines, and the coprocessor's audio blocks.

### 5. Compressor and Dynamics Experiments

The THR5 firmware examination included Compressor Type 1, described in the THR5A material as a 24-bit studio rack compressor. A conditional check near `0x0201A292` was tested, and a `NOP` patch (`46C0`) allowed the related execution path to be reached.

A 37-row dynamics curve from `thr5a_stock.bin` was also examined and placed at `0x0209D668`, with a connection to output ID `0x97`. These experiments may help researchers compare the dynamics paths available in electric and acoustic-oriented firmware images.

### 6. Tone-Stack Processing and Low-Frequency Response

Forney's cabinet-bypass example is a useful reference point for studying the THR signal path. Additional analysis examined a per-model tone-curve processor near `0x0209EA40` after observing a pronounced low-frequency response around 100 Hz in the THR5 Clean model when used with full-range speakers or headphones.

The experimental firmware loaded THR5A Clean and acoustic tone-stack tables from `0x0209E100` for selected models. The resulting response was evaluated as a way to study model-specific bass, middle, and treble shaping.

### 7. EEPROM Layout and Recovery Research

The repository's firmware-flashing guidance provides important context for considering recovery procedures. Separate analysis examined the onboard Renesas `R1EX25002` SPI EEPROM (`IC11`) and routines near `0x0201B40C` (read) and `0x0201B5BC` (write).

The following locations were identified for further testing:

- `0x00`: Startup boot model index
- `0x01`: Wide Stereo state
- `0x02`: Hardware update mode or boot-state flag
- `0x03`: Simulated tube-glow lamp state
- `0x04`–`0x08`: User preset selectors
- `0x09`: Master speaker-voicing curve
- `0xFF`: Factory calibration sentinel

A recovery procedure was also documented for devices that no longer initialize USB MIDI: an external SPI programmer can be connected to the relevant EEPROM pins, and writing `0x01` to offset `0x02` may select secondary-bootloader Update Mode on the next startup. This procedure should be treated as hardware work requiring appropriate safety precautions and independent verification.

### 8. Potentiometer Cache Invalidation

The THR firmware maintains cached analog control values to avoid abrupt changes when recalling presets. During model-selector experiments, the cache behavior was examined through `FUN_0201E83C`.

Calling this routine after a model change caused the firmware to resample the physical controls, which helped keep the knobs responsive when moving between model banks. This is a useful detail for anyone studying preset recall and control-state synchronization.

### 9. Display and LED Control

Forney's use of tuner LEDs demonstrates how the front-panel indicators can provide compact status feedback. Additional work examined the 7-segment display routine `FUN_0201E1F0`, including independent control of the `#` segment:

- `FUN_0201E1F0(0, 1)` illuminates `#`
- `FUN_0201E1F0(0, 0)` blanks `#`

An experimental interface used this segment to distinguish electric and acoustic model banks.

The THR5/THR5A LED mapping was also documented as follows:

- Model LEDs: 0–4
- Tuner LEDs: 5 (`TUNE_LEFT`), 6 (`TUNE_CENTER`), and 7 (`TUNE_RIGHT`)

The shared LED routine at `0x0201E6F4` was left unchanged after testing showed that remapping it could affect tuner indicators. Model LED handling was instead kept in the model-switch and preset-recall paths near `0x0202BF28` and `0x0201E530`.

### 10. Pre-Flash Validation and Emulation

Forney's documented checksum and file-verification practices are a useful baseline for responsible flashing. The later experimental workflow added several automated checks before producing a MIDI flash file:

1. **CPU emulation:** Unicorn-based tests exercise boot, dial, knob-sweep, tuner, and preset-recall paths.
2. **Opcode boundaries:** Modified regions are disassembled and checked for instruction alignment and expected control-flow behavior.
3. **MIDI container validation:** SysEx message counts, payload blocks, checksums, and the pre-erase delay are verified.
4. **Binary difference audit:** Modified bytes are accounted for against the factory image.

These checks are intended to complement, not replace, careful backups, hardware-specific testing, and the recovery knowledge described above.

### 11. Browser-Based MIDI Interface

Forney's C, Lua, and ALSA-oriented command-line tools remain valuable for understanding the data path and for scripted workflows. A separate `thr-web/` application explored a browser-based interface using Web MIDI, with features including:

- Two-way parameter synchronization
- Visual knob and slider state
- Preset backup and restore
- Cabinet selection
- Access to selected extended settings such as Wide Stereo, tube-lamp state, and speaker voicing
- GitHub Pages deployment at [`https://coreymlawrence.github.io/thr/`](https://coreymlawrence.github.io/thr/)

This offers a different interaction model for readers who want to experiment with the same MIDI-controlled device from a modern browser.

## Closing Note

Michael Forney's work established a clear and practical path into Yamaha THR firmware research. The investigations collected here follow that path across different THR hardware, firmware builds, and research questions. Readers familiar with `michaelforney/thr10` may find the most useful connections in the shared SysEx format, firmware patching model, DSP command flow, front-panel controls, and the care required when modifying and reflashing embedded devices.

The findings in this document are experimental and hardware-specific. Firmware images, addresses, EEPROM behavior, and recovery procedures should be independently checked against the exact device and build under study.