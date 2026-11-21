#!/usr/bin/env python3
"""
thr_detector.py - Always-On Yamaha THR Hardware Connection & Mode Detector Daemon
================================================================================
Features:
- Monitors USB MIDI connections continuously to detect Yamaha THR amplifiers.
- Automatically distinguishes UPDATE MODE ('U') from NORMAL PLAY MODE.
- Completely non-blocking asynchronous LCD rendering thread: MIDI loop runs at
  full bus speed with ZERO latency.
- Dedicated Tone Knob Macro Handler: Translates simultaneous Bass/Mid/Treble
  updates into an accurate, unified physical Tone knob percentage.
- Full Effect & Spatial Engine Telemetry:
  * Modulation: Chorus, Flanger, Tremolo, Phaser with individual parameter depth.
  * Delay / Reverb: Delay, Spring Reverb, Hall Reverb, and Dly/Rev dual modes.
- Seamless recovery from connects, disconnects, power cycles, and mode transitions.
"""

import os
import sys
import time
import json
import signal
import threading

# Ensure local module directory is in path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import thr_lcd

try:
    import mido
except ImportError:
    mido = None

# Protocol constants
CMD = [0x43, 0x7D, 0x10, 0x41, 0x30, 0x01]
HEARTBEAT_PREFIX = bytes([0x43, 0x7D, 0x60, 0x44, 0x54, 0x41])

# Model names for Corey's custom hybrid firmware (Position 0 Clean tuned with 5A Cab, Position 1 ACO)
CUSTOM_AMPS = {
    0: "Clean",
    1: "ACO Acoustic",
    2: "Lead",
    3: "Brit Hi-Gain",
    4: "Modern Hi",
    5: "Bass",
    6: "Aco",
    7: "Flat",
}

CABINETS = [
    "US 4x12",
    "US 2x12",
    "Brit 4x12",
    "Brit 2x12",
    "1x12 Deluxe",
    "4x10",
    "Flat (None)",
]

MODELS_MAP = {
    0x30: "THR5",
    0x31: "THR10",
    0x32: "THR10X",
    0x33: "THR10C",
    0x34: "THR5A",
}

MOD_NAMES = {
    0: "Chorus",
    1: "Flanger",
    2: "Tremolo",
    3: "Phaser",
}

REVERB_NAMES = {
    0: "Hall",
    1: "Room",
    2: "Plate",
    3: "Spring",
}

DUMP_TAG = [0x44, 0x54, 0x41]  # "DTA"
ALLP = [0x41, 0x6C, 0x6C, 0x50]  # "AllP"
PAYLOAD_AT = 17
AMP_AT = PAYLOAD_AT + 128
CAB_AT = PAYLOAD_AT + 134

# Load tone curves for Tone knob reverse lookup
TONE_CURVES = {}
tone_json_path = os.path.join(BASE_DIR, "tone_curves.json")
if os.path.exists(tone_json_path):
    try:
        with open(tone_json_path, "r") as f:
            raw_curves = json.load(f)
            TONE_CURVES = {int(k): v for k, v in raw_curves.items()}
    except Exception as e:
        print(f"[!] Warning loading tone curves: {e}")

running = True


def sig_handler(signum, frame):
    global running
    print(f"\n[!] Caught signal {signum}. Shutting down THR detector cleanly...")
    running = False


signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


class DisplayState:
    """Thread-safe state container decoupling MIDI reception from LCD rendering."""

    def __init__(self):
        self.lock = threading.Lock()
        self.override_l1 = None
        self.override_l2 = None

        self.model_title = "THR Companion"
        self.amp_idx = 0
        self.amp_name = "Clean"
        self.cab_idx = 4
        self.cab_name = "1x12 Deluxe"

        self.gain = 50
        self.master = 50
        self.bass = 50
        self.mid = 50
        self.treble = 50

        self.comp_on = False
        self.mod_type = 0
        self.mod_on = False
        self.delay_on = False
        self.reverb_on = False
        self.reverb_type = 0

        self.knob_line = None
        self.last_knob_time = 0

    def set_override(self, l1, l2):
        with self.lock:
            self.override_l1 = l1
            self.override_l2 = l2

    def clear_override(self):
        with self.lock:
            self.override_l1 = None
            self.override_l2 = None

    def get_dly_rev_label(self, val=None):
        lvl = f": {val}%" if val is not None else ""
        if not self.delay_on and not self.reverb_on:
            return "Dly/Rev: OFF"
        if self.delay_on and self.reverb_on:
            return f"Dly/Rev{lvl}"
        if self.delay_on and not self.reverb_on:
            return f"Delay{lvl}"
        if self.reverb_on and not self.delay_on:
            rname = REVERB_NAMES.get(self.reverb_type, "Hall")
            tag = f"{rname} Rev{lvl}"
            return tag if len(tag) <= 16 else f"{rname}{lvl}"
        return "Dly/Rev"

    def get_lines(self):
        with self.lock:
            if self.override_l1 is not None and self.override_l2 is not None:
                return self.override_l1[:16], self.override_l2[:16]

            l1 = f"{self.model_title}: {self.amp_name}"[:16]

            now = time.monotonic()
            if self.knob_line and (now - self.last_knob_time) < 3.0:
                l2 = self.knob_line[:16]
            else:
                self.knob_line = None
                l2 = f"Cab: {self.cab_name}"[:16]

            return l1, l2


state = DisplayState()


def lcd_worker_thread():
    """Background worker that pushes display updates without blocking the MIDI loop."""
    last_drawn = (None, None)
    while running:
        time.sleep(0.04)  # 25 Hz poll
        l1, l2 = state.get_lines()
        if (l1, l2) != last_drawn:
            thr_lcd.set_text(l1, l2)
            last_drawn = (l1, l2)


def lookup_tone_position(amp_idx, b, m, t):
    """Calculates the single Tone knob percentage (0..100%) from Bass, Mid, Treble."""
    curve = TONE_CURVES.get(amp_idx)
    if not curve:
        curve = TONE_CURVES.get(0)
    if not curve:
        # Fallback approximation
        return int(max(0, min(100, (t * 0.6) + (m * 0.2) + ((100 - b) * 0.2))))

    best_k = min(
        range(101),
        key=lambda k: (b - curve[k][0]) ** 2
        + (m - curve[k][1]) ** 2
        + (t - curve[k][2]) ** 2,
    )
    return best_k


def find_thr_midi_ports():
    """Finds available Yamaha THR MIDI ports."""
    if mido is None:
        return None, None
    try:
        inputs = [
            n
            for n in mido.get_input_names()
            if "midi through" not in n.lower()
            and ("thr" in n.lower() or "yamaha" in n.lower())
        ]
        outputs = [
            n
            for n in mido.get_output_names()
            if "midi through" not in n.lower()
            and ("thr" in n.lower() or "yamaha" in n.lower())
        ]
        inp = inputs[0] if inputs else None
        out = outputs[0] if outputs else None
        return inp, out
    except Exception as e:
        log(f"Error querying MIDI ports: {e}")
        return None, None


def request_settings_block(port_out, port_in, model_id=0x31, timeout=0.6):
    """Requests current settings block from amp to inspect active preset."""
    if not port_out or not port_in:
        return None
    try:
        while port_in.poll() is not None:
            pass

        req = [0x43, 0x7D, 0x20] + DUMP_TAG + [model_id] + ALLP
        port_out.send(mido.Message("sysex", data=req))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and running:
            msg = port_in.poll()
            if msg is None:
                time.sleep(0.005)
                continue
            if msg.type == "sysex":
                d = bytes(msg.data)
                if not d.startswith(HEARTBEAT_PREFIX) and len(d) >= 200:
                    return d
    except Exception as e:
        log(f"Settings block request error: {e}")
    return None


def run_detector():
    global running
    log("=" * 60)
    log("Yamaha THR Always-On Detector Daemon Initializing")
    log("Non-blocking Asynchronous Display Engine Active")
    log("=" * 60)

    # Start the decoupled LCD rendering worker
    lcd_thread = threading.Thread(target=lcd_worker_thread, daemon=True)
    lcd_thread.start()

    state.set_override("THR Companion", "Detector Online")
    time.sleep(1.0)
    state.set_override("THR Companion", "Waiting for Amp")

    last_state = None
    state_wait_count = 0

    while running:
        port_in_name, port_out_name = find_thr_midi_ports()

        # ---------------------------------------------------------
        # Case A: No THR MIDI Port Found (Amp disconnected or off)
        # ---------------------------------------------------------
        if not port_in_name:
            if last_state != "WAITING":
                log("[-] Amp disconnected. Watching for connection...")
                state.set_override("THR Companion", "Waiting for Amp")
                last_state = "WAITING"
                state_wait_count = 0

            state_wait_count += 1
            if state_wait_count % 10 == 0:
                dots = "." * ((state_wait_count // 10) % 4)
                state.set_override("THR Companion", f"Waiting for Amp{dots}")

            time.sleep(1.0)
            continue

        # ---------------------------------------------------------
        # Case B: THR MIDI Port Detected! Probe connection mode.
        # ---------------------------------------------------------
        log(f"[+] THR hardware port discovered: {port_in_name}")
        state.set_override("THR Detected!", "Checking Mode...")

        port_in = None
        port_out = None
        try:
            port_in = mido.open_input(port_in_name)
            if port_out_name:
                try:
                    port_out = mido.open_output(port_out_name)
                except Exception as eo:
                    log(f"Warning: could not open output port {port_out_name}: {eo}")

            while port_in.poll() is not None:
                pass

            detected_mode = None
            detected_model_id = None
            t_start = time.monotonic()

            while time.monotonic() - t_start < 2.5 and running:
                msg = port_in.poll()
                if msg is None:
                    time.sleep(0.01)
                    continue

                if msg.type == "sysex":
                    data = bytes(msg.data)
                    if data.startswith(HEARTBEAT_PREFIX):
                        detected_mode = "NORMAL"
                        if len(data) > len(HEARTBEAT_PREFIX):
                            detected_model_id = data[len(HEARTBEAT_PREFIX)]
                        break

            if detected_mode is None:
                detected_mode = "UPDATE"

            # -----------------------------------------------------
            # Mode 1: UPDATE MODE ('U')
            # -----------------------------------------------------
            if detected_mode == "UPDATE":
                last_state = "UPDATE"
                log("[!] >>> YAMAHA THR DETECTED IN UPDATE MODE ('U') <<<")
                log("    DTAb bootloader active. Amp is ready to flash or dump.")

                state.set_override("THR Connected!", "Mode: Update [U]")
                time.sleep(1.5)
                state.set_override("THR in [U] Mode!", "Ready to Flash")

                u_timer = 0
                while running:
                    p_in_chk, _ = find_thr_midi_ports()
                    if not p_in_chk:
                        log("[-] THR disconnected from Update Mode.")
                        break

                    msg = port_in.poll()
                    if msg and msg.type == "sysex" and bytes(msg.data).startswith(HEARTBEAT_PREFIX):
                        log("[+] Heartbeat detected in U-mode loop. Transitioning to Normal Play Mode...")
                        detected_mode = "NORMAL"
                        data = bytes(msg.data)
                        if len(data) > len(HEARTBEAT_PREFIX):
                            detected_model_id = data[len(HEARTBEAT_PREFIX)]
                        break

                    u_timer += 1
                    if u_timer % 12 == 0:
                        state.set_override("THR in [U] Mode!", "Firmware Lab")
                    elif u_timer % 6 == 0:
                        state.set_override("THR in [U] Mode!", "Ready to Flash")

                    time.sleep(0.5)

                if detected_mode == "UPDATE":
                    continue

            # -----------------------------------------------------
            # Mode 2: NORMAL PLAY MODE
            # -----------------------------------------------------
            model_name = MODELS_MAP.get(detected_model_id, "THR5")
            mid_val = detected_model_id if detected_model_id is not None else 0
            last_state = "NORMAL"
            log(f"[+] >>> YAMAHA THR DETECTED IN NORMAL PLAY MODE <<<")
            log(f"    Hardware Identity: {model_name} (0x{mid_val:02X})")

            state.set_override(f"{model_name} Connected!", "Mode: Normal Play")
            time.sleep(1.5)

            # Initialize model title and defaults
            state.model_title = model_name
            state.amp_idx = 0
            state.cab_idx = 4
            state.amp_name = CUSTOM_AMPS.get(0, "Clean")
            state.cab_name = CABINETS[4]

            if not port_out:
                _, p_out_retry = find_thr_midi_ports()
                if p_out_retry:
                    try:
                        port_out = mido.open_output(p_out_retry)
                    except Exception:
                        pass

            # Query initial settings block
            if port_out:
                cand_ids = [0x31, mid_val or 0x30, 0x34]
                block = None
                for cid in cand_ids:
                    block = request_settings_block(port_out, port_in, model_id=cid, timeout=0.6)
                    if block:
                        break

                if block and len(block) > CAB_AT:
                    state.amp_idx = block[AMP_AT]
                    state.cab_idx = block[CAB_AT]
                    state.amp_name = CUSTOM_AMPS.get(state.amp_idx, f"Model {state.amp_idx}")
                    state.cab_name = (
                        CABINETS[state.cab_idx]
                        if state.cab_idx < len(CABINETS)
                        else f"Cab {state.cab_idx}"
                    )
                    state.gain = block[PAYLOAD_AT + 129]
                    state.master = block[PAYLOAD_AT + 130]
                    state.bass = block[PAYLOAD_AT + 131]
                    state.mid = block[PAYLOAD_AT + 132]
                    state.treble = block[PAYLOAD_AT + 133]

                    # Effects initial state
                    if len(block) > PAYLOAD_AT + 208:
                        state.comp_on = bool(block[PAYLOAD_AT + 159] == 0)
                        state.mod_type = block[PAYLOAD_AT + 160]
                        state.mod_on = bool(block[PAYLOAD_AT + 175] == 0)
                        state.delay_on = bool(block[PAYLOAD_AT + 191] == 0)
                        state.reverb_type = block[PAYLOAD_AT + 208]
                        state.reverb_on = bool(block[PAYLOAD_AT + 207] == 0)

                    log(f"    Initial Patch: {state.amp_name} | Cabinet: {state.cab_name}")

            # Clear override so normal live status cards are drawn
            state.clear_override()

            last_heartbeat = time.monotonic()

            # Zero-Latency MIDI Polling Loop
            while running:
                msg = port_in.poll()

                if msg is None:
                    now = time.monotonic()
                    if now - last_heartbeat > 4.5:
                        p_chk, _ = find_thr_midi_ports()
                        if not p_chk:
                            log("[-] THR disconnected or powered off.")
                            break
                        else:
                            log("[?] Heartbeats ceased. Possible reboot into U-mode or mode switch.")
                            break
                    time.sleep(0.002)
                    continue

                if msg.type != "sysex":
                    continue

                d = bytes(msg.data)

                # Process Heartbeat
                if d.startswith(HEARTBEAT_PREFIX):
                    last_heartbeat = time.monotonic()
                    continue

                # Process Parameter Echoes (SysEx CMD 0x43 0x7D 0x10 ...)
                if d.startswith(bytes(CMD)) and len(d) >= 8:
                    addr = d[6]
                    val = (d[7] << 7) | d[8] if len(d) >= 9 else d[7]
                    now = time.monotonic()

                    # 1. Amp Model Rotary Knob
                    if addr == 0x00:
                        state.amp_idx = val
                        state.amp_name = CUSTOM_AMPS.get(val, f"Model {val}")
                        log(f"[KNOB] Model Selector -> {state.amp_name} (Pos {val})")

                    # 2. Cabinet
                    elif addr == 0x06:
                        state.cab_idx = val
                        state.cab_name = (
                            CABINETS[val] if val < len(CABINETS) else f"Cab {val}"
                        )
                        state.knob_line = f"Cab: {state.cab_name}"
                        state.last_knob_time = now
                        log(f"[KNOB] Cabinet -> {state.cab_name}")

                    # 3. Gain
                    elif addr == 0x01:
                        state.gain = val
                        state.knob_line = f"Gain: {val}%"
                        state.last_knob_time = now
                        log(f"[KNOB] Gain -> {val}%")

                    # 4. Master
                    elif addr == 0x02:
                        state.master = val
                        state.knob_line = f"Master: {val}%"
                        state.last_knob_time = now
                        log(f"[KNOB] Master -> {val}%")

                    # 5. Tone Knob (Bass 0x03, Mid 0x04, Treble 0x05)
                    elif addr in (0x03, 0x04, 0x05):
                        if addr == 0x03:
                            state.bass = val
                        elif addr == 0x04:
                            state.mid = val
                        elif addr == 0x05:
                            state.treble = val

                        # Compute unified physical Tone knob percentage
                        k = lookup_tone_position(state.amp_idx, state.bass, state.mid, state.treble)
                        if k is not None:
                            state.knob_line = f"Tone: {k}%"
                            log(f"[KNOB] Tone -> {k}% (B:{state.bass} M:{state.mid} T:{state.treble})")
                        else:
                            state.knob_line = f"Tone: {val}%"
                            log(f"[KNOB] Tone -> {val}%")
                        state.last_knob_time = now

                    # 6. Compressor (0x10, 0x11, 0x12, 0x1F)
                    elif addr == 0x1F:
                        state.comp_on = bool(val)
                        state.knob_line = "Comp: ON (Rack)" if val else "Comp: OFF"
                        state.last_knob_time = now
                        log(f"[KNOB] Compressor Switch -> {'ON' if val else 'OFF'}")

                    elif addr == 0x10:
                        state.knob_line = f"Comp: {'Rack' if val else 'Stomp'}"
                        state.last_knob_time = now
                        log(f"[KNOB] Comp Type -> {'Rack' if val else 'Stomp'}")

                    elif addr in (0x11, 0x12):
                        state.comp_on = True
                        state.knob_line = f"Comp: {val}%"
                        state.last_knob_time = now
                        log(f"[KNOB] Comp Param -> {val}%")

                    # 7. EFFECT / Modulation (0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x2F)
                    elif addr == 0x20:
                        state.mod_type = val
                        state.mod_on = True
                        name = MOD_NAMES.get(val, "Chorus")
                        state.knob_line = f"{name}: Active"
                        state.last_knob_time = now
                        log(f"[KNOB] Effect Type -> {name}")

                    elif addr == 0x2F:
                        state.mod_on = bool(val)
                        name = MOD_NAMES.get(state.mod_type, "Chorus")
                        state.knob_line = f"{name}: ON" if val else "Effect: OFF"
                        state.last_knob_time = now
                        log(f"[KNOB] Effect Switch -> {'ON' if val else 'OFF'}")

                    elif addr in (0x21, 0x22, 0x23, 0x24, 0x25):
                        state.mod_on = True
                        name = MOD_NAMES.get(state.mod_type, "Chorus")
                        state.knob_line = f"{name}: {val}%"
                        state.last_knob_time = now
                        log(f"[KNOB] {name} Level -> {val}%")

                    # 8. Delay (0x31, 0x33, 0x34, 0x36, 0x38, 0x3F)
                    elif addr == 0x3F:
                        state.delay_on = bool(val)
                        state.knob_line = state.get_dly_rev_label()
                        state.last_knob_time = now
                        log(f"[KNOB] Delay Switch -> {'ON' if val else 'OFF'}")

                    elif addr in (0x31, 0x33, 0x38):
                        state.delay_on = True
                        state.knob_line = state.get_dly_rev_label(val)
                        state.last_knob_time = now
                        log(f"[KNOB] Delay Level -> {val}%")

                    # 9. Reverb (0x40, 0x41, 0x42, 0x43, 0x4F)
                    elif addr == 0x40:
                        state.reverb_type = val
                        state.reverb_on = True
                        rname = REVERB_NAMES.get(val, "Hall")
                        state.knob_line = state.get_dly_rev_label()
                        state.last_knob_time = now
                        log(f"[KNOB] Reverb Type -> {rname}")

                    elif addr == 0x4F:
                        state.reverb_on = bool(val)
                        state.knob_line = state.get_dly_rev_label()
                        state.last_knob_time = now
                        log(f"[KNOB] Reverb Switch -> {'ON' if val else 'OFF'}")

                    elif addr in (0x41, 0x42):
                        state.reverb_on = True
                        state.knob_line = state.get_dly_rev_label(val)
                        state.last_knob_time = now
                        log(f"[KNOB] Reverb Amount -> {val}%")

        except Exception as err:
            log(f"[-] Port I/O event: {err}")
        finally:
            if port_in:
                try:
                    port_in.close()
                except Exception:
                    pass
            if port_out:
                try:
                    port_out.close()
                except Exception:
                    pass

        # Disconnected state reset
        if running:
            state.set_override("THR Disconnected", "Waiting for Amp")
            time.sleep(1.0)
            state.set_override("THR Companion", "Waiting for Amp")
            last_state = "WAITING"
            time.sleep(1.0)

    # Clean shutdown
    state.set_override("THR Companion", "Standby")
    log("[*] THR Detector Daemon stopped.")


if __name__ == "__main__":
    run_detector()
