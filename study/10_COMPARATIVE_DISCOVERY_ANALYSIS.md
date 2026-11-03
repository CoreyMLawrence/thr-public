# Yamaha THR Reverse Engineering: Discovery Map

## What this page is for

Michael Forney's [`michaelforney/thr10`](https://github.com/michaelforney/thr10) is a useful starting point for Yamaha THR firmware research. This page is organized for readers who have explored that work and want a simple way to follow related THR5 and THR5A investigations in this repository.

The short summaries below answer three questions:

1. **What was investigated?**
2. **Where is the detailed evidence?**
3. **What can I read or run next?**

For the practical workflow, start with the repository's [README](../README.md), then use the [tooling quickstart](../guides/QUICKSTART_TOOLING.md), [firmware extraction guide](../guides/EXTRACTING_FIRMWARE.md), and [pre-flight flashing guide](../guides/VERIFY_AND_FLASH.md). The [disaster recovery guide](../guides/DISASTER_RECOVERY.md) should be read before experimenting with hardware recovery.

## Start here: the discovery map

| Discovery | In one sentence | Detailed chapter | Useful next step |
|---|---|---|---|
| THR5 and THR5A firmware compatibility | Software tables appear to account for important model and identity differences across related hardware. | [Chapter 1: Hardware & Silicon](01_HARDWARE_AND_SILICON.md) | [Extract a factory firmware image](../guides/EXTRACTING_FIRMWARE.md) before comparing builds. |
| Firmware layout and symbols | The DTAm application, memory regions, and Thumb execution rules provide the map for safe analysis. | [Chapter 2: Firmware & Memory Map](02_FIRMWARE_AND_MEMORY_MAP.md) | Review [custom patching](../guides/CREATING_CUSTOM_PATCHES.md) and [patch boilerplate](../tools/patch_template.py). |
| Two live SysEx paths | Parameter commands and settings blocks take different paths through the running firmware. | [Chapter 3: Live SysEx & Dual-Door Protocol](03_LIVE_SYSEX_AND_DUAL_DOOR_PROTOCOL.md) | Try the [live MIDI tooling](11_TOOLING_AND_AUTOMATION_GUIDE.md) or inspect [`thr_live.py`](../tools/thr_live.py). |
| DSP block dispatch | A lower-level dispatcher connects firmware commands to model, tone, cabinet, effects, and dynamics blocks. | [Chapter 4: DSP Coprocessor](04_DSP_COPROCESSOR_AND_AUDIO_PIPELINE.md) | Follow the [DSP block directory](04_DSP_COPROCESSOR_AND_AUDIO_PIPELINE.md#2-dsp-algorithmic-block-directory). |
| Tone-stack behavior | Model-specific tone shaping helps explain the low-frequency response observed on the THR5 Clean model. | [Chapter 5: Tone Stack](05_TONE_STACK_AND_FREQUENCY_RESPONSE.md) | See the [tone-stack injection hook](05_TONE_STACK_AND_FREQUENCY_RESPONSE.md#3-the-engineering-solution-the-eg-clean-tone-stack). |
| Compressor and effects paths | The effects engine contains separate stompbox, rack-compressor, modulation, delay, reverb, and gate paths. | [Chapter 6: Effects Engine](06_EFFECTS_ENGINE_AND_RACK_COMPRESSOR.md) | Compare live control with the [`thr_params.json`](../tools/thr_params.json) parameter map. |
| Ten-position rotary experiments | The rotary input, model limits, display, LEDs, and knob cache can be studied as one UI subsystem. | [Chapter 7: Rotary Encoder & UI](07_ROTARY_ENCODER_AND_UI_EXPANSION.md) | Start with [custom rotary patches](../guides/CREATING_CUSTOM_PATCHES.md#example-a-customizing-rotary-selector-behavior--limits). |
| EEPROM and recovery | Persistent preferences and the update-mode sentinel are documented alongside a hardware recovery procedure. | [Chapter 8: EEPROM & Recovery](08_EEPROM_MAP_AND_HARDWARE_RECOVERY.md) | Read the [disaster recovery manual](../guides/DISASTER_RECOVERY.md) before touching `IC11`. |
| Automated safety checks | Emulation, opcode checks, MIDI-container validation, and binary auditing form a pre-flash review chain. | [Chapter 9: Safety Gates](09_SAFETY_GATES_AND_CPU_EMULATION.md) | Run the checks described in the [pre-flight guide](../guides/VERIFY_AND_FLASH.md). |
| Python tooling | The repository includes utilities for containers, live MIDI, settings blocks, and patch creation. | [Chapter 11: Tooling & Automation](11_TOOLING_AND_AUTOMATION_GUIDE.md) | Begin with the [tooling quickstart](../guides/QUICKSTART_TOOLING.md). |
| Browser-based control | The Web MIDI Studio provides a browser interface for live parameters and selected persistent settings. | [Chapter 12: Web MIDI Studio](12_WEB_MIDI_STUDIO_ARCHITECTURE.md) | Read the [web-studio README](../web-studio/README.md), then explore [`app.js`](../web-studio/app.js) and [`thr-protocol.js`](../web-studio/thr-protocol.js). |

## A guided reading path

### 1. Understand the hardware and firmware boundary

Start with [Chapter 1](01_HARDWARE_AND_SILICON.md) for the THR5/THR5A hardware context. Then read [Chapter 2](02_FIRMWARE_AND_MEMORY_MAP.md) to understand the DTAm application, protected regions, symbols, and Thumb code.

If you are working with your own amplifier, use the [firmware extraction guide](../guides/EXTRACTING_FIRMWARE.md) before making any changes. The extraction workflow gives you a known-good image for later comparison and recovery.

### 2. Learn the two control surfaces

[Chapter 3](03_LIVE_SYSEX_AND_DUAL_DOOR_PROTOCOL.md) explains the live MIDI protocol, the settings-block structure, and the two paths used to change amplifier state. The same concepts appear in:

- [`thr_live.py`](../tools/thr_live.py), for interactive MIDI commands
- [`thr_map.py`](../tools/thr_map.py), for decoding settings blocks
- [Chapter 11](11_TOOLING_AND_AUTOMATION_GUIDE.md), for command examples
- [Chapter 12](12_WEB_MIDI_STUDIO_ARCHITECTURE.md), for browser-side protocol handling

### 3. Follow a signal from the model selector into the DSP

Read [Chapter 4](04_DSP_COPROCESSOR_AND_AUDIO_PIPELINE.md) for the DSP blocks and the `FUN_020184E6` dispatcher. Then follow the two specialized branches:

- [Chapter 5](05_TONE_STACK_AND_FREQUENCY_RESPONSE.md) for tone shaping and frequency response
- [Chapter 6](06_EFFECTS_ENGINE_AND_RACK_COMPRESSOR.md) for compressor, modulation, delay, reverb, and gate behavior

The [custom patching guide](../guides/CREATING_CUSTOM_PATCHES.md) shows how these observations become standalone firmware experiments.

### 4. Study the physical controls and persistent state

[Chapter 7](07_ROTARY_ENCODER_AND_UI_EXPANSION.md) connects the rotary selector, display, LEDs, and potentiometer tracking. [Chapter 8](08_EEPROM_MAP_AND_HARDWARE_RECOVERY.md) covers the separate persistent state stored in EEPROM.

For software-only experiments, use the [live MIDI monitor](11_TOOLING_AND_AUTOMATION_GUIDE.md#3-real-time-midi-monitor--control-thr_livepy). For hardware recovery, read both [Chapter 8](08_EEPROM_MAP_AND_HARDWARE_RECOVERY.md) and the [disaster recovery manual](../guides/DISASTER_RECOVERY.md).

### 5. Validate before flashing

[Chapter 9](09_SAFETY_GATES_AND_CPU_EMULATION.md) explains the four checks used before producing a flash container. The operational sequence is in the [pre-flight verification guide](../guides/VERIFY_AND_FLASH.md):

1. Extract and preserve the factory image.
2. Apply a focused patch with [`patch_template.py`](../tools/patch_template.py).
3. Validate the generated MIDI container.
4. Flash only after the checks pass.

## Discovery details by topic

### Hardware compatibility

The compatibility experiments concern shared silicon, memory layout, peripherals, and software-controlled device identity. Read [Chapter 1](01_HARDWARE_AND_SILICON.md), then compare the firmware organization in [Chapter 2](02_FIRMWARE_AND_MEMORY_MAP.md).

**Explore next:** [extract a factory image](../guides/EXTRACTING_FIRMWARE.md) and use the [firmware container tools](11_TOOLING_AND_AUTOMATION_GUIDE.md#2-firmware-container-utility-thr_toolpy).

### SysEx settings and model access

The settings-block investigation focuses on the difference between the validated parameter path and the larger state-loading path. The byte layout, checksum, and non-volatile preference path are documented in [Chapter 3](03_LIVE_SYSEX_AND_DUAL_DOOR_PROTOCOL.md).

**Explore next:** decode a settings block with [`thr_map.py`](../tools/thr_map.py), then inspect the corresponding message handling in [`thr-protocol.js`](../web-studio/thr-protocol.js).

### DSP and audio behavior

The DSP work is easiest to follow in order: [dispatcher and block directory](04_DSP_COPROCESSOR_AND_AUDIO_PIPELINE.md), [tone stack](05_TONE_STACK_AND_FREQUENCY_RESPONSE.md), then [effects and compressor](06_EFFECTS_ENGINE_AND_RACK_COMPRESSOR.md).

**Explore next:** use the [parameter map](../tools/thr_params.json) to connect named controls to the live protocol.

### Rotary selector and front-panel UI

The ten-position rotary experiment is documented together with the display segment, LED isolation, and knob-cache behavior in [Chapter 7](07_ROTARY_ENCODER_AND_UI_EXPANSION.md). This keeps the physical input, model selection, and user feedback in one place.

**Explore next:** [Example A in the patching guide](../guides/CREATING_CUSTOM_PATCHES.md#example-a-customizing-rotary-selector-behavior--limits), then the model-selection logic in [`patch_template.py`](../tools/patch_template.py).

### EEPROM and recovery

The EEPROM map and update-mode sentinel are in [Chapter 8](08_EEPROM_MAP_AND_HARDWARE_RECOVERY.md). The hands-on wiring, backup, and reflash procedure is separated into the [disaster recovery manual](../guides/DISASTER_RECOVERY.md) so the research notes and operational instructions remain easy to distinguish.

**Explore next:** review the [recovery prerequisites](../guides/DISASTER_RECOVERY.md#4-required-hardware-tools) before connecting an external programmer.

### Safety and reproducibility

The validation work is collected in [Chapter 9](09_SAFETY_GATES_AND_CPU_EMULATION.md), while the repeatable workflow is split across the [patching guide](../guides/CREATING_CUSTOM_PATCHES.md) and [pre-flight guide](../guides/VERIFY_AND_FLASH.md).

**Explore next:** [Chapter 11](11_TOOLING_AND_AUTOMATION_GUIDE.md) for the exact utilities and command paths used by the workflow.

### Browser interface

The browser work is described in [Chapter 12](12_WEB_MIDI_STUDIO_ARCHITECTURE.md). The implementation is in [`web-studio/`](../web-studio/), with protocol handling in [`thr-protocol.js`](../web-studio/thr-protocol.js), application behavior in [`app.js`](../web-studio/app.js), and setup notes in the [web-studio README](../web-studio/README.md).

**Explore next:** compare the browser message flow with [`thr_live.py`](../tools/thr_live.py) to see the same device behavior from two interfaces.

## Relationship to Michael Forney's work

Forney's repository is a useful reference for the THR10C firmware-dumping, patching, and MIDI-flashing workflow. The links above point to investigations on other THR hardware and to later questions about DSP routing, persistent settings, UI behavior, validation, and browser tooling.

The most direct points of connection are:

- [Firmware extraction and flashing](../guides/EXTRACTING_FIRMWARE.md) and [pre-flight verification](../guides/VERIFY_AND_FLASH.md)
- [Live SysEx framing and checksums](03_LIVE_SYSEX_AND_DUAL_DOOR_PROTOCOL.md)
- [Firmware symbols and Thumb execution](02_FIRMWARE_AND_MEMORY_MAP.md)
- [Custom patch creation](../guides/CREATING_CUSTOM_PATCHES.md)

The findings remain experimental and build-specific. Check the exact hardware, firmware image, addresses, and recovery procedure before applying any result to a different device.
