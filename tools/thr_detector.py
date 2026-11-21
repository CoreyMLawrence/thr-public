#!/usr/bin/env python3
"""
thr_detector.py - Always-On Yamaha THR Hardware Connection & Mode Detector Daemon
================================================================================
Monitors USB MIDI connections continuously to detect Yamaha THR amplifiers:
- Identifies whether the amp is booted in UPDATE MODE ('U') or NORMAL PLAY MODE.
- Confirms connection state and drives the physical 16x2 I2C LCD screen with
  real-time status, active presets, and live knob telemetry.
- Seamlessly handles connects, disconnects, power cycles, and mode transitions.
- Runs continuously as a systemd daemon (thr-detector.service).
"""

import os
import sys
import time
import signal

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

DUMP_TAG = [0x44, 0x54, 0x41]  # "DTA"
ALLP = [0x41, 0x6C, 0x6C, 0x50]  # "AllP"
PAYLOAD_AT = 17
AMP_AT = PAYLOAD_AT + 128
CAB_AT = PAYLOAD_AT + 134

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


def request_settings_block(port_out, port_in, model_id=0x31, timeout=0.8):
    """Requests current settings block from amp to inspect active preset."""
    if not port_out or not port_in:
        return None
    try:
        # Drain queue
        while port_in.poll() is not None:
            pass

        req = [0x43, 0x7D, 0x20] + DUMP_TAG + [model_id] + ALLP
        port_out.send(mido.Message("sysex", data=req))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and running:
            msg = port_in.poll()
            if msg is None:
                time.sleep(0.01)
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
    log("Watching for Normal Play Mode and Update Mode ('U')...")
    log("=" * 60)

    # Initialize LCD to waiting state
    thr_lcd.set_text("THR Companion", "Detector Online")
    time.sleep(1.0)
    thr_lcd.set_text("THR Companion", "Waiting for Amp")

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
                thr_lcd.set_text("THR Companion", "Waiting for Amp")
                last_state = "WAITING"
                state_wait_count = 0

            state_wait_count += 1
            # Subtle animated dot every 10 seconds to indicate heartbeat
            if state_wait_count % 10 == 0:
                dots = "." * ((state_wait_count // 10) % 4)
                thr_lcd.set_text("THR Companion", f"Waiting for Amp{dots}")

            time.sleep(1.0)
            continue

        # ---------------------------------------------------------
        # Case B: THR MIDI Port Detected! Probe connection mode.
        # ---------------------------------------------------------
        log(f"[+] THR hardware port discovered: {port_in_name}")
        thr_lcd.set_text("THR Detected!", "Checking Mode...")

        port_in = None
        port_out = None
        try:
            port_in = mido.open_input(port_in_name)
            if port_out_name:
                try:
                    port_out = mido.open_output(port_out_name)
                except Exception as eo:
                    log(f"Warning: could not open output port {port_out_name}: {eo}")

            # Drain any old pending messages
            while port_in.poll() is not None:
                pass

            # Listen for up to 2.5 seconds to see if heartbeats arrive
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

            # If no heartbeats arrived within 2.5s, the amp is in UPDATE MODE ('U')!
            if detected_mode is None:
                detected_mode = "UPDATE"

            # -----------------------------------------------------
            # Mode 1: UPDATE MODE ('U')
            # -----------------------------------------------------
            if detected_mode == "UPDATE":
                last_state = "UPDATE"
                log("[!] >>> YAMAHA THR DETECTED IN UPDATE MODE ('U') <<<")
                log("    DTAb bootloader active. Amp is ready to flash or dump.")

                # Confirmed Connection Notification
                thr_lcd.set_text("THR Connected!", "Mode: Update [U]")
                time.sleep(1.5)
                thr_lcd.set_text("THR in [U] Mode!", "Ready to Flash")

                u_timer = 0
                while running:
                    # Check if port is still connected
                    p_in_chk, _ = find_thr_midi_ports()
                    if not p_in_chk:
                        log("[-] THR disconnected from Update Mode.")
                        break

                    # Check if amp unexpectedly rebooted into normal mode
                    msg = port_in.poll()
                    if msg and msg.type == "sysex" and bytes(msg.data).startswith(HEARTBEAT_PREFIX):
                        log("[+] Heartbeat detected in U-mode loop. Transitioning to Normal Play Mode...")
                        detected_mode = "NORMAL"
                        data = bytes(msg.data)
                        if len(data) > len(HEARTBEAT_PREFIX):
                            detected_model_id = data[len(HEARTBEAT_PREFIX)]
                        break

                    # Alternate display every 6 seconds: "Ready to Flash" <-> "Firmware Lab"
                    u_timer += 1
                    if u_timer % 12 == 0:
                        thr_lcd.set_text("THR in [U] Mode!", "Firmware Lab")
                    elif u_timer % 6 == 0:
                        thr_lcd.set_text("THR in [U] Mode!", "Ready to Flash")

                    time.sleep(0.5)

                if detected_mode == "UPDATE":
                    # Device disconnected
                    continue

            # -----------------------------------------------------
            # Mode 2: NORMAL PLAY MODE
            # -----------------------------------------------------
            model_name = MODELS_MAP.get(detected_model_id, "THR5")
            mid_val = detected_model_id if detected_model_id is not None else 0
            last_state = "NORMAL"
            log(f"[+] >>> YAMAHA THR DETECTED IN NORMAL PLAY MODE <<<")
            log(f"    Hardware Identity: {model_name} (0x{mid_val:02X})")

            # Confirmed Connection Notification on Screen
            thr_lcd.set_text(f"{model_name} Connected!", "Mode: Normal Play")
            time.sleep(1.5)

            current_amp_idx = 0
            current_cab_idx = 4  # Default 1x12 Deluxe for custom firmware
            current_amp_name = CUSTOM_AMPS.get(current_amp_idx, "Clean")
            current_cab_name = CABINETS[current_cab_idx]

            # In case output port was not ready initially, re-probe
            if not port_out:
                _, p_out_retry = find_thr_midi_ports()
                if p_out_retry:
                    try:
                        port_out = mido.open_output(p_out_retry)
                    except Exception:
                        pass

            # Query settings block for initial state if output port is available
            if port_out:
                cand_ids = [0x31, mid_val or 0x30, 0x34]
                block = None
                for cid in cand_ids:
                    block = request_settings_block(port_out, port_in, model_id=cid, timeout=0.6)
                    if block:
                        break

                if block and len(block) > CAB_AT:
                    current_amp_idx = block[AMP_AT]
                    current_cab_idx = block[CAB_AT]
                    current_amp_name = CUSTOM_AMPS.get(current_amp_idx, f"Model {current_amp_idx}")
                    current_cab_name = (
                        CABINETS[current_cab_idx]
                        if current_cab_idx < len(CABINETS)
                        else f"Cab {current_cab_idx}"
                    )
                    log(f"    Initial Patch: {current_amp_name} | Cabinet: {current_cab_name}")

            # Display on 16x2 LCD
            thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Cab: {current_cab_name}")

            last_heartbeat = time.monotonic()
            last_knob_time = 0

            # Normal Mode Event Loop
            while running:
                msg = port_in.poll()

                # Timeout & idle handling
                if msg is None:
                    now = time.monotonic()
                    # If heartbeats stop for > 4.5 seconds, verify if port is alive
                    if now - last_heartbeat > 4.5:
                        p_chk, _ = find_thr_midi_ports()
                        if not p_chk:
                            log("[-] THR disconnected or powered off.")
                            break
                        else:
                            log("[?] Heartbeats ceased. Possible reboot into U-mode or mode switch.")
                            break

                    # Revert knob value display back to Cabinet name after 3 seconds of inactivity
                    if last_knob_time > 0 and (now - last_knob_time) > 3.0:
                        last_knob_time = 0
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Cab: {current_cab_name}")

                    time.sleep(0.01)
                    continue

                if msg.type != "sysex":
                    continue

                d = bytes(msg.data)

                # Process Heartbeat
                if d.startswith(HEARTBEAT_PREFIX):
                    last_heartbeat = time.monotonic()
                    continue

                # Process Parameter Echoes (Knob turns, Model switch, FX toggles)
                if d.startswith(bytes(CMD)) and len(d) >= 8:
                    addr = d[6]
                    val = (d[7] << 7) | d[8] if len(d) >= 9 else d[7]

                    if addr == 0x00:
                        # Amp Model Rotary Switch
                        current_amp_idx = val
                        current_amp_name = CUSTOM_AMPS.get(val, f"Model {val}")
                        log(f"[KNOB] Model Selector -> {current_amp_name} (Pos {val})")
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Cab: {current_cab_name}")

                    elif addr == 0x06:
                        # Cabinet selection
                        current_cab_idx = val
                        current_cab_name = (
                            CABINETS[val] if val < len(CABINETS) else f"Cab {val}"
                        )
                        log(f"[KNOB] Cabinet -> {current_cab_name}")
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Cab: {current_cab_name}")

                    elif addr == 0x01:
                        last_knob_time = time.monotonic()
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Gain: {val}%")
                        log(f"[KNOB] Gain: {val}%")

                    elif addr == 0x02:
                        last_knob_time = time.monotonic()
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Master: {val}%")
                        log(f"[KNOB] Master: {val}%")

                    elif addr == 0x03:
                        last_knob_time = time.monotonic()
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Bass: {val}%")
                        log(f"[KNOB] Bass: {val}%")

                    elif addr == 0x04:
                        last_knob_time = time.monotonic()
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Middle: {val}%")
                        log(f"[KNOB] Middle: {val}%")

                    elif addr == 0x05:
                        last_knob_time = time.monotonic()
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Treble: {val}%")
                        log(f"[KNOB] Treble: {val}%")

                    elif addr == 0x1F:
                        last_knob_time = time.monotonic()
                        comp_txt = "ON (Rack 24b)" if val else "OFF"
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Comp: {comp_txt}")
                        log(f"[KNOB] Compressor: {comp_txt}")

                    elif addr == 0x2F:
                        last_knob_time = time.monotonic()
                        mod_txt = "ON" if val else "OFF"
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Modulation: {mod_txt}")
                        log(f"[KNOB] Modulation: {mod_txt}")

                    elif addr == 0x3F:
                        last_knob_time = time.monotonic()
                        del_txt = "ON" if val else "OFF"
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Delay: {del_txt}")
                        log(f"[KNOB] Delay: {del_txt}")

                    elif addr == 0x4F:
                        last_knob_time = time.monotonic()
                        rev_txt = "ON" if val else "OFF"
                        thr_lcd.set_text(f"{model_name}: {current_amp_name}", f"Reverb: {rev_txt}")
                        log(f"[KNOB] Reverb: {rev_txt}")

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
            thr_lcd.set_text("THR Disconnected", "Waiting for Amp")
            time.sleep(1.0)
            thr_lcd.set_text("THR Companion", "Waiting for Amp")
            last_state = "WAITING"
            time.sleep(1.0)

    # Clean shutdown
    thr_lcd.set_text("THR Companion", "Standby")
    log("[*] THR Detector Daemon stopped.")


if __name__ == "__main__":
    run_detector()
