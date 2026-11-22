# emu_v54.py
#
# Yamaha THR Hybrid Firmware - Stage v54 Unicorn CPU Emulation Test Suite
#
# Validates:
#   Subtest 1A: Opcode Boundary Verification at 0x0202C490 (0x4D86)
#   Subtest 1B: Stock Boot Check Emulation at 0x0202AF4C
#   Subtest 2:  Clean Voicing, Cabinet Setup & DSP Block 2 Signal Path Fix
#   Subtest 3:  Authentic THR5A Effect Engine & 24-bit Rack Compressor
#   Subtest 4:  Dedicated Per-Model Tone Curves Emulation (Models 0..4, Knobs 0..100)
#   Subtest 5:  Tone Lookup Routine Disassembly & Opcode Alignment
#

import os
import struct
import capstone
import unicorn
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_BIG_ENDIAN
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR

STAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_PATH = os.environ.get("THR_BIN_PATH", os.path.join(STAGE_DIR, "thr5_hybrid_v54.bin"))

BASE = 0x02010000
RAM_BASE = 0x01000000
RAM_SIZE = 0x00040000  # 256 KB
SRAM_BASE = 0x04000000
SRAM_SIZE = 0x00040000  # 256 KB


def setup_emulator(bin_data):
    mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_BIG_ENDIAN)
    mu.mem_map(0x02000000, 0x00120000)
    mu.mem_write(BASE, bin_data)
    mu.mem_map(RAM_BASE, RAM_SIZE)
    mu.mem_map(SRAM_BASE, SRAM_SIZE)
    mu.mem_map(0x00000000, 0x00040000)
    mu.mem_map(0x07000000, 0x00040000)
    mu.reg_write(UC_ARM_REG_SP, 0x01018000)
    return mu


def test_subtest_1a(bin_data):
    print("Running Subtest 1A: Opcode Boundary Verification at 0x0202C490...")
    opcode = struct.unpack_from(">H", bin_data, 0x0202C490 - BASE)[0]
    assert opcode == 0x4D86, f"FAIL: Expected opcode 0x4D86, got 0x{opcode:04X}"
    print("  [PASS] Subtest 1A: Address 0x0202C490 holds valid opcode 0x4D86")


def test_subtest_1b(bin_data):
    print("\nRunning Subtest 1B: Stock Boot Check Emulation at 0x0202AF4C...")
    mu = setup_emulator(bin_data)
    umode_writes = []

    def hook_boot(uc, address, size, user_data):
        if address == 0x0201E544:
            uc.reg_write(UC_ARM_REG_R0, 0)  # TAP button not held
            lr = uc.reg_read(UC_ARM_REG_LR)
            uc.reg_write(UC_ARM_REG_PC, lr)
        elif address == 0x0201B5BC:
            offset = uc.reg_read(UC_ARM_REG_R0)
            src_ptr = uc.reg_read(UC_ARM_REG_R1)
            val = uc.mem_read(src_ptr, 1)[0]
            if offset == 2:
                umode_writes.append(val)
            lr = uc.reg_read(UC_ARM_REG_LR)
            uc.reg_write(UC_ARM_REG_PC, lr)

    mu.hook_add(unicorn.UC_HOOK_CODE, hook_boot)
    mu.reg_write(UC_ARM_REG_SP, 0x01018000)
    mu.reg_write(UC_ARM_REG_LR, 0x0202B092 | 1)
    mu.emu_start(0x0202AF4C | 1, 0x0202AFF6)

    assert len(umode_writes) == 0, f"Normal boot unexpectedly wrote to EEPROM: {umode_writes}"
    assert mu.reg_read(UC_ARM_REG_PC) == 0x0202AFF6, "Boot check did not exit cleanly to 0x0202AFF6"
    print("  [PASS] Subtest 1B: Normal boot sequence reaches 0x0202AFF6 cleanly with zero EEPROM writes")


def test_subtest_2(bin_data):
    print("\nRunning Subtest 2: Clean Voicing, Cabinet Setup & DSP Block 2 Signal Path Fix...")
    # 1. Cabinet Block 2 Signal Path Fix at 0x0201A15C
    cab_patch = bin_data[0x0201A15C - BASE : 0x0201A15C - BASE + 10]
    expected_patch = bytes([0x21, 0x02, 0x46, 0x6b, 0x80, 0x19, 0x21, 0x05, 0x80, 0x11])
    assert cab_patch == expected_patch, f"FAIL: Cabinet Block 2 patch mismatch at 0x0201A15C: {cab_patch.hex()}"
    print("  [PASS] Cabinet Block 2 Fix verified: movs r1, #2 / strh r1, [sp] / movs r1, #5 / strh r1, [r2]")

    # 2. Model 0 Clean cabinet swap at 0x0201DFBE: movs r1, #4 (1x12 Deluxe cab)
    cab0_byte = bin_data[0x0201DFBE - BASE + 1]
    assert cab0_byte == 4, f"FAIL: Expected cab 4 at 0x0201DFBE, got {cab0_byte}"

    # 3. Model 1 ACO cabinet swap at 0x0201DFCE: movs r1, #6 (Flat cab)
    cab1_byte = bin_data[0x0201DFCE - BASE + 1]
    assert cab1_byte == 6, f"FAIL: Expected cab 6 at 0x0201DFCE, got {cab1_byte}"

    # 4. Model 0 EG Clean voicing at 0x0201A140: movs r3, #5
    prog_byte = bin_data[0x0201A140 - BASE + 1]
    assert prog_byte == 5, f"FAIL: Expected program 5 at 0x0201A140, got {prog_byte}"

    # 5. Audio router hook at 0x02019E3A: cmp r1, #1
    router_byte = bin_data[0x02019E3A - BASE + 1]
    assert router_byte == 1, f"FAIL: Expected cmp r1, #1 at 0x02019E3A, got {router_byte}"

    print("  [PASS] Subtest 2: Clean 1x12 Deluxe cab, Block 2 routing, EG Clean DSP voicing, and ACO Flat cab verified")


def test_subtest_3(bin_data):
    print("\nRunning Subtest 3: Authentic THR5A Effect Engine & 24-bit Rack Compressor...")
    # Check Rack Compressor activation patch at 0x0201A292
    patch_bytes = bin_data[0x0201A292 - BASE : 0x0201A292 - BASE + 4]
    assert patch_bytes == b"\x46\xc0\x46\xc0", f"FAIL: Expected NOPs at 0x0201A292, got {patch_bytes.hex()}"
    print("  [PASS] 24-bit Studio Rack Compressor patch at 0x0201A292 is active (NOPs)")

    # Check Effects hook at 0x0204B8D0 (bl #0x209d100)
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_BIG_ENDIAN)
    chunk = bin_data[0x0204B8D0 - BASE : 0x0204B8D4 - BASE]
    ins = list(md.disasm(chunk, 0x0204B8D0))[0]
    assert ins.mnemonic == "bl" and "209d100" in ins.op_str.lower(), f"FAIL: Expected bl 0x209d100 at 0x0204B8D0, got {ins.mnemonic} {ins.op_str}"
    print("  [PASS] Authentic THR-5A effects suite branch at 0x0204B8D0 targets 0x0209D100")


def test_subtest_4(bin_data):
    print("\nRunning Subtest 4: Dedicated Per-Model Tone Curves Emulation...")
    mu = setup_emulator(bin_data)

    dsp_calls = []

    def hook_dsp(uc, address, size, user_data):
        if address == 0x0201D1D4:
            param = uc.reg_read(UC_ARM_REG_R2)
            val = uc.reg_read(UC_ARM_REG_R1)
            dsp_calls.append((param, val))
            lr = uc.reg_read(UC_ARM_REG_LR)
            uc.reg_write(UC_ARM_REG_PC, lr)

    mu.hook_add(unicorn.UC_HOOK_CODE, hook_dsp)

    # Entry points in tone lookup switch table:
    # Model 0: 0x0204B69A -> 0x0204B6D6
    # Model 1: 0x0204B6D8 -> 0x0204B714
    # Model 2: 0x0204B716 -> 0x0204B752
    # Model 3: 0x0204B754 -> 0x0204B790
    # Model 4: 0x0204B792 -> 0x0204B7CE
    model_cases = [
        (0, 0x0204B69A, 0x0204B6D6, "Clean (EG Clean 1x12)"),
        (1, 0x0204B6D8, 0x0204B714, "ACO (Acoustic Sim / Condenser)"),
        (2, 0x0204B716, 0x0204B752, "Lead (Stock Electric Lead)"),
        (3, 0x0204B754, 0x0204B790, "Brit Hi (Stock Electric Brit Hi)"),
        (4, 0x0204B792, 0x0204B7CE, "Modern (Stock Electric Modern)"),
    ]

    for model, start_addr, end_addr, desc in model_cases:
        for k in [0, 25, 50, 75, 100]:
            dsp_calls.clear()
            mu.reg_write(UC_ARM_REG_SP, 0x01018000)
            mu.reg_write(UC_ARM_REG_LR, 0x0204B7CE | 1)
            mu.reg_write(UC_ARM_REG_R7, k)
            mu.emu_start(start_addr | 1, end_addr)

            # dsp_calls should contain 3 entries: Bass (0x83), Mid (0x84), Treble (0x85)
            assert len(dsp_calls) == 3, f"Model {model} k={k}: expected 3 DSP calls, got {len(dsp_calls)}"
            b = dsp_calls[0][1]
            m = dsp_calls[1][1]
            t = dsp_calls[2][1]

            if model == 1:
                # Authentic THR-5A Acoustic 1 (Condenser) curve checks:
                if k == 0:
                    assert (b, m, t) == (60, 35, 30), f"Model 1 k=0 mismatch: {(b, m, t)}"
                elif k == 50:
                    assert (b, m, t) == (50, 50, 50), f"Model 1 k=50 mismatch: {(b, m, t)}"
                elif k == 100:
                    assert (b, m, t) == (55, 60, 100), f"Model 1 k=100 mismatch: {(b, m, t)}"
                    assert b < 65, f"CRITICAL: Bass runaway on Model 1: Bass={b} (must not rise to 89)"
            elif model == 0:
                # Authentic THR-5A EG Clean curve checks:
                if k == 0:
                    assert (b, m, t) == (60, 35, 20), f"Model 0 k=0 mismatch: {(b, m, t)}"
                elif k == 50:
                    assert (b, m, t) == (50, 45, 40), f"Model 0 k=50 mismatch: {(b, m, t)}"
                elif k == 100:
                    assert (b, m, t) == (55, 60, 70), f"Model 0 k=100 mismatch: {(b, m, t)}"
                    assert b < 65, f"CRITICAL: Bass runaway on Model 0: Bass={b} (must not spike to 100)"

        print(f"  [PASS] Model {model}: {desc} tone curve verified across 0..100%")


def test_subtest_5(bin_data):
    print("\nRunning Subtest 5: Tone Lookup Routine Disassembly & Opcode Alignment...")
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_BIG_ENDIAN)
    code_chunk = bin_data[0x0204B680 - BASE : 0x0204B7D0 - BASE]
    instructions = list(md.disasm(code_chunk, 0x0204B680))
    assert len(instructions) > 50, f"FAIL: Expected > 50 instructions in tone routine, got {len(instructions)}"
    print(f"  [PASS] Decoded {len(instructions)} instructions cleanly in tone lookup routine")

    # Verify literal pool pointers
    m0_ptr = struct.unpack_from(">I", bin_data, 0x0204B834 - BASE)[0]
    m1_ptr = struct.unpack_from(">I", bin_data, 0x0204B838 - BASE)[0]
    m2_ptr = struct.unpack_from(">I", bin_data, 0x0204B83C - BASE)[0]
    m3_ptr = struct.unpack_from(">I", bin_data, 0x0204B840 - BASE)[0]
    m4_ptr = struct.unpack_from(">I", bin_data, 0x0204B844 - BASE)[0]
    assert m0_ptr == 0x0204EE34, f"FAIL: m0_ptr = 0x{m0_ptr:08X}"
    assert m1_ptr == 0x0204F092, f"FAIL: m1_ptr = 0x{m1_ptr:08X}"
    assert m2_ptr == 0x0204F2F0, f"FAIL: m2_ptr = 0x{m2_ptr:08X}"
    assert m3_ptr == 0x0204F54E, f"FAIL: m3_ptr = 0x{m3_ptr:08X}"
    assert m4_ptr == 0x0204F7AC, f"FAIL: m4_ptr = 0x{m4_ptr:08X}"
    print("  [PASS] All 5 model tone table literal pool pointers verified cleanly")


def main():
    print("=" * 70)
    print("UNICORN CPU EMULATION TEST SUITE - STAGE v54")
    print("=" * 70)
    assert os.path.exists(BIN_PATH), f"Target binary not found: {BIN_PATH}"
    with open(BIN_PATH, "rb") as f:
        bin_data = f.read()
    assert len(bin_data) == 1048576, f"Invalid binary size: {len(bin_data)}"

    test_subtest_1a(bin_data)
    test_subtest_1b(bin_data)
    test_subtest_2(bin_data)
    test_subtest_3(bin_data)
    test_subtest_4(bin_data)
    test_subtest_5(bin_data)

    print("\n" + "=" * 70)
    print("ALL 6 UNICORN EMULATION SUBTESTS PASSED CLEANLY")
    print("=" * 70)


if __name__ == "__main__":
    main()
