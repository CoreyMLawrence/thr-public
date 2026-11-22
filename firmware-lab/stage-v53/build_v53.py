# build_v53.py
#
# Yamaha THR Custom Firmware - Stage v53
#
# Dedicated Authentic THR-5A Acoustic & EG Clean Tone Curves
#
# Upgrades Corey's dumped custom firmware (dumped_custom_amp.bin) by installing:
# 1. Model 1 (ACO - Acoustic Sim): Authentic THR-5A Acoustic 1 (Condenser) tone curve (0x0205087A)
#    - Replaces the electric Crunch curve (0x0204F092) where Bass rose to 89.
#    - Yamaha authentic curve: warm low-end (Bass 60, Mid 35, Treble 30) at 0,
#      perfect flat EQ (Bass 50, Mid 50, Treble 50) at noon (50),
#      and sparkling acoustic clarity (Treble 100, Bass 55, Mid 60) at max (100).
#
# 2. Model 0 (Clean - EG Clean 1x12): Authentic THR-5A EG Clean tone curve (0x0205061C)
#    - Replaces the electric Clean curve (0x0204EE34) where Bass spiked to 100.
#    - Yamaha authentic curve: Bass 60/Mid 35/Treble 20 at 0 -> Bass 50/Mid 45/Treble 40 at 50 -> Bass 55/Mid 60/Treble 70 at 100.
#
# 3. Models 2..4 (Lead, Brit Hi, Modern): Stock THR5 electric tone curves preserved byte-for-byte.
#
# 4. Retains 100% of Corey's restored features:
#    - 24-bit Studio Rack Compressor patch (0x0201A292).
#    - Authentic THR5A Effects suite (Chorus, Delay, Plate Reverb) at 0x0209D100.
#    - Acoustic DSP routing (Coprocessor 5) and Flat cabinet on ACO.
#    - 1x12 Deluxe Reverb cabinet on Clean.

import hashlib
import os
import struct
import subprocess
import sys

STAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(STAGE_DIR, "..", ".."))

BASE = 0x02010000
STOCK_THR5A = os.path.join(REPO_ROOT, "thr5a_stock.bin")
BASE_CUSTOM = os.path.join(REPO_ROOT, "dumped_custom_amp.bin")
FALLBACK_CUSTOM = os.path.join(REPO_ROOT, "firmware-lab", "stage-restored", "thr5_custom_restored.bin")

OUT_BIN = os.path.join(STAGE_DIR, "thr5_hybrid_v53.bin")
OUT_MID = os.path.join(STAGE_DIR, "thr5_hybrid_v53.mid")

EXPECTED_BASE_SHA = "9a93a7dcd952d0b78be72a908218944a5cf1d8b4709e265edcf6dd05991e0feb"
EXPECTED_THR5A_SHA = "4d4719740db8f1217127f23c3fb0406cad5b74f8a7421a7e2db8d5c158cf7f3e"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("=" * 70)
    print("BUILDING YAMAHA THR HYBRID FIRMWARE - STAGE v53")
    print("Dedicated Authentic THR-5A Acoustic & EG Clean Tone Curves")
    print("=" * 70)

    # 1. Resolve base custom firmware
    custom_path = BASE_CUSTOM if os.path.exists(BASE_CUSTOM) else FALLBACK_CUSTOM
    assert os.path.exists(custom_path), f"Base custom firmware not found at {custom_path}"
    base_sha = sha256_file(custom_path)
    print(f"Base Firmware: {custom_path} (SHA: {base_sha[:16]}...)")
    assert base_sha == EXPECTED_BASE_SHA, f"Unexpected base SHA: {base_sha}"

    # 2. Resolve stock THR5A
    assert os.path.exists(STOCK_THR5A), f"Stock THR5A not found at {STOCK_THR5A}"
    thr5a_sha = sha256_file(STOCK_THR5A)
    print(f"Stock THR-5A:  {STOCK_THR5A} (SHA: {thr5a_sha[:16]}...)")
    assert thr5a_sha == EXPECTED_THR5A_SHA, f"Unexpected THR5A SHA: {thr5a_sha}"

    with open(custom_path, "rb") as f:
        fw = bytearray(f.read())
    with open(STOCK_THR5A, "rb") as f:
        thr5a = f.read()

    assert len(fw) == 1048576, f"Invalid base size: {len(fw)}"
    assert len(thr5a) == 1048576, f"Invalid thr5a size: {len(thr5a)}"

    # 3. Extract Authentic Tone Curves from THR5A
    # THR5A EG Clean curve at 0x0205061C (offset 0x4061C), 606 bytes
    eg_clean_offset = 0x0205061C - BASE
    eg_clean_curve = thr5a[eg_clean_offset : eg_clean_offset + 606]
    assert len(eg_clean_curve) == 606, f"Invalid EG Clean curve length: {len(eg_clean_curve)}"

    # THR5A Acoustic 1 Condenser curve at 0x0205087A (offset 0x4087A), 606 bytes
    condenser_offset = 0x0205087A - BASE
    condenser_curve = thr5a[condenser_offset : condenser_offset + 606]
    assert len(condenser_curve) == 606, f"Invalid Condenser curve length: {len(condenser_curve)}"

    # 4. Patch Tone Tables in place
    # Model 0: 0x0204EE34 (offset 0x3EE34) -> THR-5A EG Clean Curve
    dest_m0_offset = 0x0204EE34 - BASE
    print(f"Patching Model 0 Tone Table at 0x0204EE34 (offset 0x{dest_m0_offset:05X}) with THR-5A EG Clean curve...")
    fw[dest_m0_offset : dest_m0_offset + 606] = eg_clean_curve

    # Model 1: 0x0204F092 (offset 0x3F092) -> THR-5A Acoustic 1 (Condenser) Curve
    dest_m1_offset = 0x0204F092 - BASE
    print(f"Patching Model 1 Tone Table at 0x0204F092 (offset 0x{dest_m1_offset:05X}) with THR-5A Condenser curve...")
    fw[dest_m1_offset : dest_m1_offset + 606] = condenser_curve

    # 5. Sanity check: Ensure Section 0 and Section 1 are untouched
    with open(custom_path, "rb") as f:
        orig = f.read()
    assert fw[0:0x10000] == orig[0:0x10000], "CRITICAL ERROR: Section 0/1 modified!"
    print("[ok] Section 0 and Section 1 (0x02000000..0x0200FFFF) 100% byte-for-byte identical to base.")

    # 6. Write output binary
    with open(OUT_BIN, "wb") as f:
        f.write(fw)
    out_sha = sha256_file(OUT_BIN)
    print(f"Generated binary: {OUT_BIN}")
    print(f"Binary Size:      {len(fw):,} bytes")
    print(f"SHA-256:          {out_sha}")

    # 7. Package into MIDI update container (.mid) with 15ms fast flash block gap (16s erase gap preserved)
    print("\nPackaging .mid container with thr_tool.py pack (--gap-ms 15)...")
    pack_cmd = [
        sys.executable,
        os.path.join(REPO_ROOT, "thr_tool.py"),
        "pack",
        "--bin",
        OUT_BIN,
        "--out",
        OUT_MID,
        "--gap-ms",
        "15",
    ]
    res = subprocess.run(pack_cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        raise SystemExit(f"Packaging failed: exit code {res.returncode}")

    mid_sha = sha256_file(OUT_MID)
    print(f"Generated container: {OUT_MID}")
    print(f"Container SHA-256:   {mid_sha}")
    print("\n[SUCCESS] Stage v53 build complete.")


if __name__ == "__main__":
    main()
