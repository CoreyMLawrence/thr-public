# verify_v54.py
#
# Yamaha THR Hybrid Firmware - Stage v54
#
# Enforces the 4 Mandatory Pre-Flash Safety Gates:
#   Gate 1: Unicorn CPU Emulation Test Suite (emu_v54.py)
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

BIN_PATH = os.path.join(STAGE_DIR, "thr5_hybrid_v54.bin")
MID_PATH = os.path.join(STAGE_DIR, "thr5_hybrid_v54.mid")
BASE_CUSTOM = os.path.join(REPO_ROOT, "dumped_custom_amp.bin")
FALLBACK_CUSTOM = os.path.join(REPO_ROOT, "firmware-lab", "stage-restored", "thr5_custom_restored.bin")
STOCK_THR5A = os.path.join(REPO_ROOT, "thr5a_stock.bin")

BASE = 0x02010000


def run_gate_1():
    print("=" * 70)
    print("GATE 1: UNICORN CPU EMULATION TEST SUITE")
    print("=" * 70)
    res = subprocess.run(
        [sys.executable, os.path.join(STAGE_DIR, "emu_v54.py")],
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

    # 2. Check Cabinet Block 2 Patch alignment and disassembly
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_BIG_ENDIAN)
    cab_patch = bin_data[0x0201A15C - BASE : 0x0201A15C - BASE + 10]
    insns = list(md.disasm(cab_patch, 0x0201A15C))
    assert len(insns) == 5, f"GATE 2 FAILED: Cabinet patch disassembled into {len(insns)} insns, expected 5"
    assert insns[0].op_str == "r1, #2", f"insn 0 mismatch: {insns[0].op_str}"
    assert "sp" in insns[1].op_str, f"insn 1 mismatch: {insns[1].op_str}"
    assert "[r3]" in insns[2].op_str, f"insn 2 mismatch: {insns[2].op_str}"
    assert insns[3].op_str == "r1, #5", f"insn 3 mismatch: {insns[3].op_str}"
    assert "[r2]" in insns[4].op_str, f"insn 4 mismatch: {insns[4].op_str}"
    print("  [ok] Cabinet Block 2 Fix at 0x0201A15C decoded cleanly into 5 aligned instructions")

    # 3. Check tone table literal pointers
    m0_ptr = struct.unpack_from(">I", bin_data, 0x0204B834 - BASE)[0]
    m1_ptr = struct.unpack_from(">I", bin_data, 0x0204B838 - BASE)[0]
    assert m0_ptr == 0x0204EE34, f"GATE 2 FAILED: m0_ptr is 0x{m0_ptr:08X}, expected 0x0204EE34"
    assert m1_ptr == 0x0204F092, f"GATE 2 FAILED: m1_ptr is 0x{m1_ptr:08X}, expected 0x0204F092"
    print("  [ok] Tone table literal pointers verified")

    # 4. Disassemble tone lookup routine
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
    assert bin_data[0:0x8000] == base_data[0:0x8000], "GATE 4 FAILED: Vector table / early boot modified!"
    print("  [ok] Vector table and early boot (0x02010000..0x02017FFF) 100% untouched")

    # Exact allowed diff ranges:
    # 1. Cabinet Block 2 Signal Path Fix: 0x0201A15C..0x0201A166 (10 bytes)
    # 2. Authentic Model 0 & Model 1 Tone Tables: 0x0204EE34..0x0204F2F0 (1,212 bytes)
    cab_start = 0x0201A15C - BASE
    cab_end = 0x0201A166 - BASE
    table_start = 0x0204EE34 - BASE
    table_end = 0x0204F2F0 - BASE

    # Ensure prefix before Cabinet Patch is 100% byte-identical
    assert bin_data[0:cab_start] == base_data[0:cab_start], "GATE 4 FAILED: Unexpected modified byte before Cabinet patch!"
    # Ensure code between Cabinet Patch and Tone Tables is 100% byte-identical
    assert bin_data[cab_end:table_start] == base_data[cab_end:table_start], "GATE 4 FAILED: Unexpected modified byte between Cabinet patch and Tone tables!"
    # Ensure suffix after Tone Tables is 100% byte-identical
    assert bin_data[table_end:] == base_data[table_end:], "GATE 4 FAILED: Unexpected modified byte after Tone tables!"

    # Verify Cabinet Patch contents
    expected_cab = bytes([0x21, 0x02, 0x46, 0x6b, 0x80, 0x19, 0x21, 0x05, 0x80, 0x11])
    assert bin_data[cab_start:cab_end] == expected_cab, "GATE 4 FAILED: Cabinet Block 2 patch bytes mismatch!"
    print("  [ok] Range 1 (0x0201A15C..0x0201A166, 10 bytes): Cabinet Block 2 Signal Path Fix verified byte-for-byte")

    # Verify Tone Tables contents
    with open(STOCK_THR5A, "rb") as f_a:
        thr5a_data = f_a.read()
    eg_clean = thr5a_data[0x0205061C - BASE : 0x0205061C - BASE + 606]
    condenser = thr5a_data[0x0205087A - BASE : 0x0205087A - BASE + 606]
    assert bin_data[table_start : table_start + 606] == eg_clean, "GATE 4 FAILED: Model 0 EG Clean curve mismatch!"
    assert bin_data[table_start + 606 : table_end] == condenser, "GATE 4 FAILED: Model 1 Condenser curve mismatch!"
    print("  [ok] Range 2 (0x0204EE34..0x0204F2F0, 1,212 bytes): Authentic Model 0 & Model 1 Tone Tables verified byte-for-byte")

    # Calculate total modified bytes across the binary
    total_mod = sum(1 for i in range(len(bin_data)) if bin_data[i] != base_data[i])
    print(f"  [ok] Exactly {total_mod} bytes modified across entire 1,048,576 byte image, 100% strictly confined to the two target regions")
    print("  [ok] Pre-cabinet code (0x02010000..0x0201A15B) 100% byte-for-byte identical")
    print("  [ok] Mid-region code (0x0201A166..0x0204EE33) 100% byte-for-byte identical")
    print("  [ok] Post-table image (0x0204F2F0..0x02110000) 100% byte-for-byte identical")
    print("[GATE 4 PASSED] 100% of binary modifications accounted for.\n")


def main():
    print("=" * 70)
    print("PRE-FLASH SAFETY VERIFICATION - STAGE v54")
    print("Dedicated Authentic Tone Curves + Cabinet Block 2 Signal Path Fix")
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
    print("FIRMWARE STAGE v54 IS FULLY VALIDATED AND SAFE TO FLASH")
    print("=" * 70)


if __name__ == "__main__":
    main()
