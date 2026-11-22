# flash_v53.py
#
# Yamaha THR Hybrid Firmware - Stage v53 Flash Runner
#
# Enforces the 4 Pre-Flash Safety Gates and streams thr5_hybrid_v53.mid
# to the amplifier in Update Mode 'U' with 15ms block timing (~51s total).

import hashlib
import os
import subprocess
import sys
import time

try:
    import mido
except ImportError:
    print("mido required: pip install mido python-rtmidi", file=sys.stderr)
    sys.exit(1)

STAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(STAGE_DIR, "..", ".."))
sys.path.insert(0, REPO_ROOT)

import thr_tool

try:
    import thr_lcd
except ImportError:
    thr_lcd = None

MID_PATH = os.path.join(STAGE_DIR, "thr5_hybrid_v53.mid")
BIN_PATH = os.path.join(STAGE_DIR, "thr5_hybrid_v53.bin")
VERIFY_SCRIPT = os.path.join(STAGE_DIR, "verify_v53.py")

EXPECTED_BIN_SHA = "cc2e92b87e47f768eb2f74da4dfd5b244bd8eb24f43d12491cea138f35d1197a"
EXPECTED_MID_SHA = "81554abb811b04d8b316f1356c192a9f65bc9710835d7e75c06718a62dfcd00f"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def lcd_status(line1, line2):
    if thr_lcd:
        try:
            thr_lcd.write_lines(line1, line2)
        except Exception:
            pass


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

    # 2. Check binary & container SHA-256
    bin_sha = sha256_file(BIN_PATH)
    mid_sha = sha256_file(MID_PATH)
    assert bin_sha == EXPECTED_BIN_SHA, f"Binary SHA mismatch: {bin_sha}"
    assert mid_sha == EXPECTED_MID_SHA, f"Container SHA mismatch: {mid_sha}"
    print(f"[ok] Target binary verified:    {BIN_PATH} (SHA: {bin_sha[:16]}...)")
    print(f"[ok] Target container verified: {MID_PATH} (SHA: {mid_sha[:16]}...)")

    # 3. Validate container structure
    _, report, gaps, problems = thr_tool.validate_update_file(MID_PATH, quiet=True)
    if problems:
        for p in problems:
            print(f"  [warn] {p}", file=sys.stderr)
        raise SystemExit("ABORT: Validation problems found in SMF container")

    payloads, gaps = thr_tool.read_smf(MID_PATH)
    total = len(payloads)
    assert total == 2343, f"Expected 2343 messages, got {total}"
    assert report["blocks"] == 2341, f"Expected 2341 blocks, got {report['blocks']}"
    assert gaps[1] == 16000, f"Expected 16,000ms erase gap, got {gaps[1]}ms"
    print(f"[ok] Container structure verified: {total} messages, {report['blocks']} blocks, 16s erase gap, {gaps[2]}ms block gap\n")

    # 4. Resolve Yamaha THR MIDI Output Port
    port_name = None
    for _ in range(10):
        hits = [
            n for n in mido.get_output_names()
            if "midi through" not in n.lower() and ("thr" in n.lower() or "yamaha" in n.lower())
        ]
        if hits:
            port_name = hits[0]
            break
        time.sleep(0.5)

    if not port_name:
        raise SystemExit("ERROR: No Yamaha THR MIDI output port detected. Is USB connected?")

    print(f"[ok] Target MIDI Port: {port_name}")

    # 5. Stop thr-detector during transmission to ensure exclusive port access
    print("\nPausing thr-detector service for exclusive MIDI bus bandwidth...")
    subprocess.run(["systemctl", "stop", "thr-detector.service"], check=False)

    print("\n" + "=" * 70)
    print("BEGINNING TRANSMISSION TO YAMAHA THR HARDWARE")
    print("CRITICAL: DO NOT DISCONNECT USB OR TURN POWER OFF DURING FLASH!")
    print("=" * 70)
    sys.stdout.flush()

    total_blocks = total - 2
    sent = 0
    start = time.monotonic()
    try:
        with mido.open_output(port_name) as out:
            # Step 1: Send Erase command and track 16s erase progress
            print("\n[Step 1/3] Sending ERASE command to NOR flash...")
            out.send(mido.Message("sysex", data=list(payloads[0])))
            sent += 1

            erase_wait = gaps[1] / 1000.0 if len(gaps) > 1 else 16.0
            erase_start = time.monotonic()
            while True:
                e_elapsed = time.monotonic() - erase_start
                if e_elapsed >= erase_wait:
                    break
                pct = min(100.0, (e_elapsed / erase_wait) * 100.0)
                bar = thr_lcd.render_terminal_bar(e_elapsed, erase_wait, width=24) if thr_lcd else f"[{int(pct):>3}%]"
                rem = max(0.0, erase_wait - e_elapsed)
                print(f"  Erase NOR Flash: {bar} | {e_elapsed:4.1f}s / {erase_wait:4.1f}s ({rem:4.1f}s rem)", end="\r", flush=True)
                if thr_lcd:
                    thr_lcd.show_flash_erase(e_elapsed, erase_wait)
                time.sleep(0.15)

            full_bar = "[========================] 100.0%"
            print(f"  Erase NOR Flash: {full_bar} | {erase_wait:4.1f}s / {erase_wait:4.1f}s [ERASE COMPLETE]")
            if thr_lcd:
                thr_lcd.show_flash_erase(erase_wait, erase_wait)

            # Step 2: Stream firmware payload blocks
            print("\n[Step 2/3] Streaming firmware blocks to amplifier (15ms timing)...")
            block_start = time.monotonic()
            for i in range(1, total - 1):
                wait = gaps[i] / 1000.0
                if wait > 0:
                    time.sleep(wait)

                out.send(mido.Message("sysex", data=list(payloads[i])))
                sent += 1

                blk_idx = i
                b_elapsed = time.monotonic() - block_start
                if blk_idx % 15 == 0 or blk_idx == total_blocks:
                    pct = (blk_idx / total_blocks) * 100.0
                    rate = blk_idx / b_elapsed if b_elapsed > 0 else 0
                    eta = (total_blocks - blk_idx) / rate if rate > 0 else 0
                    bar = thr_lcd.render_terminal_bar(blk_idx, total_blocks, width=24) if thr_lcd else f"[{int(pct):>3}%]"
                    print(f"  Stream Payload:  {bar} | {blk_idx}/{total_blocks} ({b_elapsed:4.1f}s, {rate:4.1f} blk/s, ETA: {eta:4.1f}s)", end="\r", flush=True)
                    if thr_lcd:
                        thr_lcd.show_flash_streaming(blk_idx, total_blocks, elapsed=b_elapsed, rate=rate)

            print(f"\n  Stream Payload:  {full_bar} | {total_blocks}/{total_blocks} [STREAM COMPLETE]")

            # Step 3: Checksum terminator
            print("\n[Step 3/3] Sending checksum terminator & verifying...")
            if thr_lcd:
                thr_lcd.set_text("Finalizing...", "Verifying CSUM")
            csum_wait = gaps[total - 1] / 1000.0 if gaps[total - 1] > 0 else 0.015
            time.sleep(csum_wait)
            out.send(mido.Message("sysex", data=list(payloads[total - 1])))
            sent += 1
            print(f"  Checksum Verify: {full_bar} [CHECKSUM OK]")

        elapsed_total = time.monotonic() - start
        print("\n" + "=" * 70)
        print(f"[COMPLETE] Flash transmission finished cleanly in {elapsed_total:.1f}s!")
        print("Watch for 'E - n - d' looping on the amp display, then power cycle.")
        print("=" * 70)
        if thr_lcd:
            thr_lcd.show_flash_done()

    except Exception as exc:
        print(f"\n[!] FLASH TRANSMISSION ERROR: {exc}", file=sys.stderr)
        print("DO NOT POWER CYCLE. Re-enter update mode and retry immediately.", file=sys.stderr)
        if thr_lcd:
            thr_lcd.show_flash_error("Flash Error")
        raise
    finally:
        # Restart thr-detector service
        subprocess.run(["systemctl", "start", "thr-detector.service"], check=False)


if __name__ == "__main__":
    main()
