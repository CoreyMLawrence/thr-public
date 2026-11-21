# flash_v53.py
#
# Yamaha THR Hybrid Firmware - Stage v53 Flash Runner
#
# Enforces the 4 Pre-Flash Safety Gates and guides the flashing process to physical hardware.

import hashlib
import os
import subprocess
import sys
import time

try:
    import mido
except ImportError:
    mido = None

STAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(STAGE_DIR, "..", ".."))

MID_PATH = os.path.join(STAGE_DIR, "thr5_hybrid_v53.mid")
BIN_PATH = os.path.join(STAGE_DIR, "thr5_hybrid_v53.bin")
VERIFY_SCRIPT = os.path.join(STAGE_DIR, "verify_v53.py")


def main():
    print("=" * 70)
    print("YAMAHA THR FIRMWARE FLASHER - STAGE v53")
    print("Dedicated Authentic THR-5A Acoustic & EG Clean Tone Curves")
    print("=" * 70)

    # 1. Enforce 4 Pre-Flash Safety Gates
    print("Enforcing 4 Pre-Flash Safety Gates via verify_v53.py...")
    res = subprocess.run([sys.executable, VERIFY_SCRIPT], capture_output=True, text=True, cwd=REPO_ROOT)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        raise SystemExit("ABORT: Pre-Flash Safety Gates failed! Refusing to flash.")
    print("[ok] All 4 Pre-Flash Safety Gates verified cleanly.\n")

    # 2. Check AC Power Safety Rule
    print("CRITICAL HARDWARE SAFETY CHECK:")
    print("  * Is the official 15V AC power adapter connected?")
    print("  * NEVER flash on battery power (low voltage causes flash write aborts).")
    print("-" * 70)

    # 3. Detect connected MIDI ports
    thr_ports = []
    if mido:
        for p in mido.get_output_names():
            if "midi through" not in p.lower() and ("thr" in p.lower() or "yamaha" in p.lower()):
                thr_ports.append(p)

    if not thr_ports:
        print("[!] No Yamaha THR MIDI output ports detected.")
        print("    If the amp is in normal mode or update mode, ensure the USB cable is securely connected.")
        print("\nTo enter Update Mode ('U'):")
        print("  1. Turn amplifier power OFF.")
        print("  2. Press and hold the 'TAP: TIME / HOLD: TUNER' button.")
        print("  3. Turn power ON while holding the button.")
        print("  4. Within 4 seconds, tap the 'TAP: TIME / HOLD: TUNER' button 5 times rapidly.")
        print("  5. The screen will display 'U'.")
        print(f"\nOnce in 'U' mode, run:")
        print(f"  python3 thr_tool.py flash --port THR --file {MID_PATH}")
        return

    print(f"Detected THR port: {thr_ports[0]}")
    print("\nReady to flash when amp is in Update Mode 'U'.")
    print(f"To execute flash command:")
    print(f"  python3 thr_tool.py flash --port THR --file {MID_PATH}")


if __name__ == "__main__":
    main()
