#!/usr/bin/env python3
"""
patch_template.py - Developer Starting Boilerplate for Yamaha THR Firmware Patching
Part of the Yamaha THR Open Reverse Engineering & Tooling Suite

This script serves as an extensible starting template for developers wishing to create
custom firmware modifications for Yamaha THR amplifiers. It provides lightweight
Thumb-1 assembly helpers, Flash address translation, and binary verification without
requiring an external ARM GCC cross-compiler.

Typical Workflow:
1. Extract factory binary from MIDI backup:
   python tools/thr_tool.py extract --file factory_backup.mid --out factory_backup.bin

2. Apply your custom patches:
   python tools/patch_template.py factory_backup.bin my_custom_firmware.bin

3. Package into a flashable MIDI container:
   python tools/thr_tool.py pack --bin my_custom_firmware.bin --out my_custom_firmware.mid

4. Validate the container before flashing:
   python tools/thr_tool.py inspect --file my_custom_firmware.mid
"""

import struct
import hashlib
import sys
import os

# Base execution address of the main application (DTAm) in NOR Flash memory
BASE_ADDRESS = 0x02010000


class ThumbAssembler:
    """
    Lightweight Thumb-1 / Thumb-2 helper for generating small machine code patches
    without requiring an external cross-compiler.
    """
    def __init__(self, base_addr):
        self.base = base_addr
        self.code = bytearray()
        self.labels = {}
        self.fixups = []

    def label(self, name):
        """Mark a jump label location."""
        self.labels[name] = len(self.code)

    def emit16(self, val):
        """Emit a 16-bit big-endian Thumb instruction."""
        self.code.extend(struct.pack(">H", val))

    def emit32(self, val):
        """Emit a 32-bit big-endian Thumb instruction."""
        self.code.extend(struct.pack(">I", val))

    def align(self, n=4):
        """Align code buffer with NOP instructions."""
        while (self.base + len(self.code)) % n != 0:
            self.emit16(0x46C0)  # NOP

    def b_cond(self, cond, label_name):
        """Emit a conditional branch placeholder for later resolution."""
        site = self.base + len(self.code)
        self.fixups.append(("b_cond", site, cond, label_name))
        self.emit16(0)

    def bl(self, target):
        """Emit a 32-bit Thumb BL (branch with link) pair."""
        site = self.base + len(self.code)
        d = target - (site + 4)
        hi = 0xF000 | ((d >> 12) & 0x7FF)
        lo = 0xF800 | ((d >> 1) & 0x7FF)
        self.emit16(hi)
        self.emit16(lo)

    def resolve(self):
        """Resolve all branch targets and return compiled bytes."""
        buf = bytearray(self.code)
        for kind, site, p1, p2 in self.fixups:
            offset = site - self.base
            if kind == "b_cond":
                target = self.base + self.labels[p2]
                disp = (target - (site + 4)) >> 1
                if not (-128 <= disp <= 127):
                    raise ValueError(f"Branch out of range: {disp}")
                opcode = 0xD000 | (p1 << 8) | (disp & 0xFF)
                buf[offset : offset + 2] = struct.pack(">H", opcode)
        return bytes(buf)


def addr_to_offset(addr: int) -> int:
    """Convert a runtime ARM Flash memory address to a 0-indexed file offset."""
    if addr < BASE_ADDRESS:
        raise ValueError(f"Address 0x{addr:08X} is below DTAm base 0x{BASE_ADDRESS:08X}")
    return addr - BASE_ADDRESS


# ==============================================================================
# Example Customization Functions
# These demonstrate how to modify firmware bytes. Developers can adapt or replace
# these functions with their own custom logic.
# ==============================================================================

def example_patch_rotary_bounds(fw: bytearray):
    """
    Demonstration Example: Adjusting rotary encoder limits in Task 4.
    
    In the factory THR5 firmware, Task 4 clamps rotary dial indexes using:
    - 0x0202C474: cmp r0, #5 (0x2805) - Upper clockwise bound
    - 0x0202C4E2: movs r0, #4 (0x2004) - Lower counter-clockwise clamp
    
    This example shows how modifying these comparison opcodes adjusts
    how the rotary dial wraps around internal slots.
    """
    offset_cw = addr_to_offset(0x0202C474)
    offset_ccw = addr_to_offset(0x0202C4E2)
    
    # Verify expected stock bytes before patching
    if fw[offset_cw : offset_cw + 2] == bytes.fromhex("2805"):
        print(f"  [i] Found expected stock clockwise clamp at 0x0202C474")
    if fw[offset_ccw : offset_ccw + 2] == bytes.fromhex("2004"):
        print(f"  [i] Found expected stock counter-clockwise clamp at 0x0202C4E2")


def example_patch_standalone_default(fw: bytearray):
    """
    Demonstration Example: Configuring standalone boot behavior.
    
    While effects like dynamics/compressor can be enabled over USB MIDI via
    Yamaha's THR Editor, in standalone mode the compact THR5 initializes them
    conditionally at address 0x0201A292.
    
    Replacing the conditional check with a NOP (0x46C0) demonstrates how
    standalone boot states can be customized.
    """
    target_addr = 0x0201A292
    offset = addr_to_offset(target_addr)
    print(f"  [i] Target offset for standalone default check: 0x{offset:06X} (Addr: 0x{target_addr:08X})")


# ==============================================================================
# Main Entry Point
# ==============================================================================

def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python tools/patch_template.py <input_factory.bin> <output_patched.bin>")
        print()
        print("Description:")
        print("  Extensible starter boilerplate for creating custom Yamaha THR firmware patches.")
        return 1

    in_file = sys.argv[1]
    out_file = sys.argv[2]

    if not os.path.isfile(in_file):
        print(f"[-] Error: Input file not found: {in_file}")
        return 1

    with open(in_file, "rb") as f:
        fw = bytearray(f.read())

    in_sha = hashlib.sha256(fw).hexdigest()
    print(f"Loaded firmware: {len(fw):,} bytes")
    print(f"Input SHA-256:   {in_sha}")

    if len(fw) != 1048576:
        print(f"[!] Warning: Expected 1,048,576 bytes (1 MiB), got {len(fw):,} bytes.")

    print("\n--- Applying Custom Patches ---")
    
    # --------------------------------------------------------------------------
    # Call your custom patch functions here:
    # --------------------------------------------------------------------------
    example_patch_rotary_bounds(fw)
    example_patch_standalone_default(fw)

    # Note: To apply actual byte modifications, modify `fw[offset : offset + len]`
    # directly or write a function that alters specific instruction bytes.
    # --------------------------------------------------------------------------

    out_sha = hashlib.sha256(fw).hexdigest()
    with open(out_file, "wb") as f:
        f.write(fw)

    print("\n--- Summary ---")
    print(f"[+] Output written: {out_file}")
    print(f"Output SHA-256:    {out_sha}")
    if in_sha == out_sha:
        print("[i] Notice: Input and output SHA-256 match (no bytes were altered in this run).")
        print("    Customize the example functions in patch_template.py to apply your edits.")
    else:
        print("[+] Binary successfully customized!")

    print("\nNext steps:")
    print(f"  1. Package into MIDI container:")
    print(f"     python tools/thr_tool.py pack --bin {out_file} --out {os.path.splitext(out_file)[0]}.mid")
    print(f"  2. Validate container structure:")
    print(f"     python tools/thr_tool.py inspect --file {os.path.splitext(out_file)[0]}.mid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
