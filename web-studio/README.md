# Yamaha THR Web Studio & Amp Unlocker (Beta)

> [!WARNING]
> **DEVELOPMENT STATUS: UNFINISHED EXPERIMENTAL BETA**
> This web application is currently an **unfinished, experimental proof-of-concept**. It was built to demonstrate and validate the reverse-engineered live SysEx protocols, settings-block injection, and bidirectional Web MIDI control discovered during this study. It is **not** a finished or polished commercial application. While functional for testing and tone tweaking, UI quirks may exist. Community contributions and refinements are very welcome!

A zero-install web application that directly connects to any Yamaha THR amplifier (THR5, THR5A, THR10, THR10C, THR10X) over USB using the **Web MIDI API**.

No files, drivers, or software installation required from users. Plug the amp into the computer with a standard USB cable, open the webpage, and start playing.

---

## What It Unlocks

1. **Hidden Amp Models (Settings Block Injection):**
   * **THR5 / V2:** Unlocks the hidden **Bass (slot 5)**, **Acoustic Simulation (slot 6)**, and **Flat (slot 7)** modes built into the hardware DSP that the physical 5-position rotary knob cannot reach.
   * **THR5A:** Unlocks the hidden **ACO (slot 6)** simulation mode.
   * Dynamically generates the 276-byte Yamaha Settings Block and recomputes the 7-bit checksum on the fly, completely bypassing the hardware panel clamp.

2. **Independent 3-Band Tone Stack:**
   * Replaces the physical amp's single, compromised `TONE` knob with independent **Bass**, **Middle**, and **Treble** controls (0 to 100).

3. **Discrete Cabinet Simulator:**
   * Select from all 7 Yamaha DSP cabinet models with speaker diagrams:
     * **US 4x12** (American vintage stack)
     * **US 2x12** (American open back)
     * **Brit 4x12** (British angled stack)
     * **Brit 2x12** (British vintage combo)
     * **1x12** (Single open back)
     * **4x10** (Tweed vintage punch)
     * **Direct / Bypass** (No cabinet emulation, clean DI for acoustic or external IRs)

4. **Studio Compressor (Completely Unlocked):**
   * **Stomp Mode:** Sustain and Output controls (transparent guitar pedal compression).
   * **Studio Rack Mode:** Vintage studio rack compressor with Threshold, Attack, Release, Ratio, Knee, and Output controls.

5. **Studio Noise Gate:**
   * Threshold and Release controls with glowing power bypass switch.

6. **Expanded Modulation, Delay & Reverb:**
   * Chorus, Flanger, Tremolo, and Phaser with individual Speed, Depth, Mix, Manual, and Feedback controls.
   * Studio Delay with millisecond readout and interactive **Tap Tempo**.
   * Hall, Room, Plate, and Spring Reverbs with decay time, pre-delay, and tone filters.

7. **Hardware System Controls:**
   * Wide Stereo Imaging toggle.
   * Simulated Tube Glow illumination lamp toggle.

8. **Tone Presets:**
   * Curated built-in tones for Electric, Acoustic, Bass, Crunch, High Gain, and Ambient styles.
   * Save, load, export, and import unlimited custom presets in the browser via `localStorage`.

---

## Quick Start

### 100% Client-Side Static App (Zero Python Required)
1. Open [`index.html`](index.html) in your browser (Google Chrome or Microsoft Edge recommended).
2. Plug in your Yamaha THR amp via USB and power it on in normal mode.
3. Click **"Connect Amp"** when prompted to allow Web MIDI access.
4. The web application will immediately detect the amp and sync its parameters.

### Deploying to the Web
The `thr-web` folder is completely static (HTML, CSS, JavaScript). You can host it directly on:
* **GitHub Pages**
* **Vercel**
* **Netlify**
* **Cloudflare Pages**

Once hosted on any HTTPS URL, any user in the world can plug in their THR5 or THR5A and control it immediately with zero downloads or installs.

---

## Browser Compatibility

* **Google Chrome** (Windows, macOS, Linux, ChromeOS, Android) - Recommended
* **Microsoft Edge** (Windows, macOS) - Recommended
* **Brave Browser**
* **Opera**

*Note: Web MIDI SysEx is currently only supported in Chromium-based browsers.*
