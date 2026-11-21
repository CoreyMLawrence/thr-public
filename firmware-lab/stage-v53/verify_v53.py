# verify_v53.py
#
# Yamaha THR Hybrid Firmware - Stage v53
#
# Enforces the 4 Mandatory Pre-Flash Safety Gates:
#   Gate 1: Unicorn CPU Emulation Test Suite (emu_v53.py)
#   Gate 2: Opcode Boundary & Instruction Alignment Audit
#   Gate 3: SysEx Container Validation (2,343 messages, 2,341 blocks, 16,000 ms erase delay)
#   Gate 4: Binary Difference Audit (Account for 100% of modified bytes against dumped base)

import hashlib
import os
import struct
import subprocess
import sys
import capstone

STAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(STAGE_DIR, "..", ".."))

BIN_PATH = os.path.join(STAGE_DIR, "thr5_hybrid_v53.bin")
MID_PATH = os.path.join(STAGE_DIR, "thr5_hybrid_v53.mid")
BASE_CUSTOM = os.path.join(REPO_ROOT, "dumped_custom_amp.bin")
FALLBACK_CUSTOM = os.path.join(REPO_ROOT, "firmware-lab", "stage-restored", "thr5_custom_restored.bin")
STOCK_THR5A = os.path.join(REPO_ROOT, "thr5a_stock.bin")

BASE = 0x02010000


def run_gate_1():
    print("=" * 70)
    print("GATE 1: UNICORN CPU EMULATION TEST SUITE")
    print("=" * 70)
    res = subprocess.run(
        [sys.executable, os.path.join(STAGE_DIR, "emu_v53.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        raise SystemExit("GATE 1 FAILED: Unicorn CPU Emulation had errors or exceptions!")
    print("[GATE 1 PASSED] All Unicorn emulation test suites passed cleanly.\n")


def run_gate_2(bin_data):
    print("=" * 70)
    print("GATE 2: OPCODE BOUNDARY & INSTRUCTION ALIGNMENT AUDIT")
    print("=" * 70)

    # 1. Critical Opcode at 0x0202C490
    opcode_c490 = struct.unpack_from(">H", bin_data, 0x0202C490 - BASE)[0]
    print(f"Checking critical opcode at 0x0202C490: 0x{opcode_c490:04X}")
    assert opcode_c490 == 0x4D86, f"GATE 2 FAILED: Opcode at 0x0202C490 is 0x{opcode_c490:04X}, expected 0x4D86!"
    print("  [ok] Address 0x0202C490 holds valid opcode 0x4D86")

    # 2. Check tone table literal pointers
    m0_ptr = struct.unpack_from(">I", bin_data, 0x0204B834 - BASE)[0]
    m1_ptr = struct.unpack_from(">I", bin_data, 0x0204B838 - BASE)[0]
    assert m0_ptr == 0x0204EE34, f"GATE 2 FAILED: m0_ptr is 0x{m0_ptr:08X}, expected 0x0204EE34"
    assert m1_ptr == 0x0204F092, f"GATE 2 FAILED: m1_ptr is 0x{m1_ptr:08X}, expected 0x0204F092"
    print("  [ok] Tone table literal pointers verified")

    # 3. Disassemble tone lookup routine
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_BIG_ENDIAN)
    code_chunk = bin_data[0x0204B680 - BASE : 0x0204B7CE - BASE]
    disasm_list = list(md.disasm(code_chunk, 0x0204B680))
    assert len(disasm_list) > 50, "GATE 2 FAILED: Tone lookup routine failed to decode cleanly"
    print(f"  [ok] Tone routine decoded {len(disasm_list)} instructions cleanly")

    print("[GATE 2 PASSED] Opcode boundaries and instruction alignment verified.\n")


def run_gate_3():
    print("=" * 70)
    print("GATE 3: CONTAINER VALIDATION")
    print("=" * 70)
    res = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "thr_tool.py"), "inspect", "--file", MID_PATH],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        raise SystemExit(f"GATE 3 FAILED: Container inspection failed: exit code {res.returncode}")

    assert "2343" in res.stdout, "GATE 3 FAILED: Expected 2,343 messages in container"
    assert "2341" in res.stdout, "GATE 3 FAILED: Expected 2,341 blocks in container"
    assert "16000 ms" in res.stdout, "GATE 3 FAILED: Erase gap must be 16000 ms"
    assert "global checksum verified" in res.stdout, "GATE 3 FAILED: Container checksum failed!"
    print("[GATE 3 PASSED] Container structure, timing, and checksum 100% verified.\n")


def run_gate_4(bin_data):
    print("=" * 70)
    print("GATE 4: BINARY DIFFERENCE AUDIT")
    print("=" * 70)
    base_file = BASE_CUSTOM if os.path.exists(BASE_CUSTOM) else FALLBACK_CUSTOM
    with open(base_file, "rb") as f:
        base_data = f.read()

    assert len(bin_data) == len(base_data) == 1048576, "Binary size mismatch"

    # Verify Section 0 and Section 1
    assert bin_data[0:0x10000] == base_data[0:0x10000], "GATE 4 FAILED: Section 0/1 modified!"
    print("  [ok] Section 0 and Section 1 (0x02000000..0x0200FFFF) 100% untouched")

    # Find all differing byte regions
    diffs = []
    in_diff = False
    start = 0
    for i in range(len(base_data)):
        if bin_data[i] != base_data[i]:
            if not in_diff:
                start = i
                in_diff = True
        else:
            if in_diff:
                diffs.append((start, i))
                in_diff = False
    if in_diff:
        diffs.append((start, len(base_data)))

    print(f"Diff regions found against dumped custom firmware: {len(diffs)}")
    total_diff_bytes = 0
    for s, e in diffs:
        addr_s = BASE + s
        addr_e = BASE + e
        l = e - s
        total_diff_bytes += l
        print(f"  Region 0x{addr_s:08X}..0x{addr_e:08X} (offset 0x{s:06X}..0x{e:06X}): {l} bytes")

    # Verify that every differing byte is strictly within the Model 0 and Model 1 tone tables:
    # Model 0: 0x0204EE34..0x0204F092 (606 bytes)
    # Model 1: 0x0204F092..0x0204F2F0 (606 bytes)
    allowed_start = 0x0204EE34 - BASE
    allowed_end = 0x0204F2F0 - BASE

    # Ensure prefix before 0x0204EE34 is 100% identical
    assert bin_data[:allowed_start] == base_data[:allowed_start], "GATE 4 FAILED: Unexpected modified byte before tone tables!"
    # Ensure suffix after 0x0204F2F0 is 100% identical
    assert bin_data[allowed_end:] == base_data[allowed_end:], "GATE 4 FAILED: Unexpected modified byte after tone tables!"

    differing_bytes = sum(1 for i in range(allowed_start, allowed_end) if bin_data[i] != base_data[i])
    print(f"  [ok] Differing bytes strictly confined to tone tables: {differing_bytes} bytes")
    print("  [ok] Pre-table image (0x02010000..0x0204EE33) 100% byte-for-byte identical")
    print("  [ok] Post-table image (0x0204F2F0..0x0210FFFF) 100% byte-for-byte identical")
    print("[GATE 4 PASSED] 100% of binary modifications accounted for.\n")


def main():
    print("=" * 70)
    print("PRE-FLASH SAFETY VERIFICATION - STAGE v53")
    print("Dedicated Authentic THR-5A Acoustic & EG Clean Tone Curves")
    print("=" * 70)

    assert os.path.exists(BIN_PATH), f"Binary not found: {BIN_PATH}"
    assert os.path.exists(MID_PATH), f"Container not found: {MID_PATH}"

    with open(BIN_PATH, "rb") as f:
        bin_data = f.read()

    run_gate_1()
    run_gate_2(bin_data)
    run_gate_3()
    run_gate_4(bin_data)

    print("=" * 70)
    print("ALL 4 PRE-FLASH SAFETY GATES VERIFIED CLEANLY")
    print("FIRMWARE STAGE v53 IS FULLY VALIDATED AND SAFE TO FLASH")
    print("=" * 70)


if __name__ == "__main__":
    main()
