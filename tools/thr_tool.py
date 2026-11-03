#!/usr/bin/env python3
"""
thr_tool.py - back up, verify, and flash Yamaha THR main firmware over USB MIDI.

One file. The only runtime dependency is mido (plus python-rtmidi for real
ports). The firmware codec is a Python port of midtobin.lua and bintomid.c
from https://github.com/michaelforney/thr10, so there is no Lua or C
toolchain to install and nothing to compile.

    pip install mido python-rtmidi

Commands:
    selftest            prove the codec round-trips, no amp needed
    ports               list MIDI ports
    dump                read firmware off the amp into a verified backup
    pack                turn a .bin into a flashable update file
    inspect             examine any update file without sending it
    flash               send an update file with correct timing
    status              show what the workspace has proven so far

Read the safety notes with:  python thr_tool.py notes
"""

import argparse
import hashlib
import json
import os
import struct
import sys
import time
from datetime import datetime, timezone

try:
    import mido
except ImportError:
    mido = None

# ----------------------------------------------------------------------------
# Protocol constants, taken from the reference tools.
# ----------------------------------------------------------------------------

YAMAHA = bytes([0x43, 0x7D])
T_ERASE, T_MAIN, T_ROMR, T_CSUM = 0x30, 0x40, 0x50, 0x70
FLASH_SECTION_MAIN = 0x02          # DTAm. Section 0 holds the bootloader.
BLOCK_BYTES = 448                  # payload per DTA1MAIN message
NUM_SENTINEL = 0x3FFF              # fixed field, not a block count
ERASE_GAP_MS = 16000               # the amp is erasing, do not send during this
BLOCK_GAP_MS = 50
TICKS_PER_BEAT = 500
TEMPO_US = 500000                  # together these make 1 tick == 1 ms

DTA1ROMR = [0x43, 0x7D, T_ROMR, 0x44, 0x54, 0x41, 0x31,
            0x52, 0x4F, 0x4D, 0x52, 0x02]

STATE_FILE = "thr_workspace.json"
CONFIRM_FLASH = "FLASH"
CONFIRM_OVERRIDE = "I HAVE NO WAY BACK"


class Fail(Exception):
    """A checked condition failed. Always fatal, never swallowed."""


def die(msg):
    print("\nSTOP: %s" % msg, file=sys.stderr)
    sys.exit(1)


def ok(msg):
    print("  [ok]   %s" % msg)


def warn(msg):
    print("  [warn] %s" % msg)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------
# Workspace state. This is what stops you cross-flashing before the drill.
# ----------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as fh:
            return json.load(fh)
    return {}


def save_state(state):
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)


# ----------------------------------------------------------------------------
# Codec: sysex message stream <-> raw firmware image.
# Ported from midtobin.lua and bintomid.c.
# ----------------------------------------------------------------------------

def decode_stream(messages):
    """messages: list of sysex payloads WITHOUT the F0/F7 framing.

    Returns (firmware_bytes, report dict). Raises Fail on any inconsistency.
    """
    out = bytearray()
    running = 0
    next_block = 0
    saw_erase = False
    saw_csum = False

    for n, m in enumerate(messages):
        if m[:2] != YAMAHA:
            raise Fail("message %d is not a Yamaha 43 7D sysex" % n)
        kind = m[2]

        if kind == T_ERASE:
            if m[3:12] != b"DTA1ERASE":
                raise Fail("message %d: type 30 but not DTA1ERASE" % n)
            if len(m) != 13:
                raise Fail("message %d: DTA1ERASE is %d bytes, expected 13" % (n, len(m)))
            if m[12] != FLASH_SECTION_MAIN:
                raise Fail("message %d: erase targets flash section %d, expected %d. "
                           "Refusing: section 0 is the bootloader."
                           % (n, m[12], FLASH_SECTION_MAIN))
            saw_erase = True

        elif kind == T_MAIN:
            if m[5:13] != b"DTA1MAIN":
                raise Fail("message %d: type 40 but not DTA1MAIN" % n)
            declared = m[3] * 128 + m[4]
            if declared != len(m) - 6:
                raise Fail("message %d: declared size %d, actual %d"
                           % (n, declared, len(m) - 7))
            if sum(m[5:]) & 0x7F:
                raise Fail("message %d: block checksum failed" % n)
            block = m[13] * 128 + m[14]
            if block != next_block:
                raise Fail("message %d: block %d out of order, expected %d"
                           % (n, block, next_block))
            next_block = block + 1
            if m[15] * 128 + m[16] != NUM_SENTINEL:
                raise Fail("message %d: sentinel is %04X, expected %04X"
                           % (n, m[15] * 128 + m[16], NUM_SENTINEL))
            body = len(m) - 18
            if body % 8:
                raise Fail("message %d: payload %d bytes, not a multiple of 8"
                           % (n, body))
            remaining = body // 8 * 7 & ~7
            i = 17
            while i <= len(m) - 2:
                take = min(7, remaining)
                if take <= 0:
                    break
                group = bytearray(m[i:i + take])
                high = m[i + 7]
                for j in range(len(group)):
                    b = group[j] | (high << (j + 1) & 0x80)
                    group[j] = b
                    running = (running + b) & 0x7F
                out += group
                remaining -= len(group)
                i += 8

        elif kind == T_CSUM:
            if m[3:11] != b"DTA1CSUM":
                raise Fail("message %d: type 70 but not DTA1CSUM" % n)
            if len(m) != 12:
                raise Fail("message %d: DTA1CSUM is %d bytes, expected 12" % (n, len(m)))
            total = (running + m[11]) & 0x7F
            if total != 0:
                raise Fail("GLOBAL CHECKSUM FAILED (got %d, expected 0). "
                           "The image is corrupt or incomplete." % total)
            saw_csum = True

        else:
            raise Fail("message %d: unknown type %02X" % (n, kind))

    if not saw_csum:
        raise Fail("no DTA1CSUM terminator. The stream is truncated.")

    return bytes(out), {
        "blocks": next_block,
        "bytes": len(out),
        "had_erase": saw_erase,
    }


def encode_stream(firmware):
    """Returns a list of (delay_ms, sysex_payload) with F0/F7 stripped."""
    msgs = [(0, bytes([0x43, 0x7D, T_ERASE]) + b"DTA1ERASE"
             + bytes([FLASH_SECTION_MAIN]))]
    running = 0
    delay = ERASE_GAP_MS

    for block, off in enumerate(range(0, len(firmware), BLOCK_BYTES)):
        data = firmware[off:off + BLOCK_BYTES]
        body = bytearray()
        for i in range(0, len(data), 7):
            high = 0
            for j in range(7):
                b = data[i + j] if i + j < len(data) else 0
                body.append(b & 0x7F)
                high |= (b & 0x80) >> (j + 1)
            body.append(high)

        declared = 12 + (len(data) + 6) // 7 * 8
        head = bytes([0x43, 0x7D, T_MAIN, declared >> 7 & 0x7F, declared & 0x7F])
        tail = (b"DTA1MAIN"
                + bytes([block >> 7 & 0x7F, block & 0x7F])
                + bytes([NUM_SENTINEL >> 7 & 0x7F, NUM_SENTINEL & 0x7F])
                + bytes(body))
        msg = head + tail + bytes([(~(sum(tail) & 0x7F) + 1) & 0x7F])
        running = (running + (sum(data) & 0x7F)) & 0x7F
        msgs.append((delay, msg))
        delay = BLOCK_GAP_MS

    msgs.append((BLOCK_GAP_MS,
                 bytes([0x43, 0x7D, T_CSUM]) + b"DTA1CSUM"
                 + bytes([(~running + 1) & 0x7F])))
    return msgs


# ----------------------------------------------------------------------------
# Standard MIDI File in and out. midtobin.lua only reads SMF, never raw .syx,
# so everything this tool writes is SMF.
# ----------------------------------------------------------------------------

def read_smf(path):
    """Returns (payloads, gaps_ms). Hand-rolled so `inspect` works without mido."""
    data = open(path, "rb").read()
    if data[:4] != b"MThd":
        raise Fail("%s is not a Standard MIDI File (no MThd). "
                   "Raw .syx captures must be converted first." % path)
    hlen = struct.unpack(">I", data[4:8])[0]
    _, _, division = struct.unpack(">HHH", data[8:8 + 6])
    pos = 8 + hlen
    tempo = TEMPO_US
    payloads, gaps, pending_ticks = [], [], 0

    def varint(i):
        v = 0
        while True:
            c = data[i]
            i += 1
            v = (v << 7) | (c & 0x7F)
            if not c & 0x80:
                return v, i

    while pos < len(data) and data[pos:pos + 4] == b"MTrk":
        tlen = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        pos += 8
        end = pos + tlen
        partial = b""
        while pos < end:
            delta, pos = varint(pos)
            pending_ticks += delta
            status = data[pos]
            pos += 1
            if status in (0xF0, 0xF7):
                ln, pos = varint(pos)
                chunk = data[pos:pos + ln]
                pos += ln
                partial = chunk if status == 0xF0 else partial + chunk
                if partial.endswith(b"\xF7"):
                    payloads.append(partial[:-1])
                    gaps.append(pending_ticks * (tempo / 1000.0) / division)
                    pending_ticks = 0
                    partial = b""
            elif status == 0xFF:
                meta = data[pos]
                pos += 1
                ln, pos = varint(pos)
                if meta == 0x51:
                    tempo = int.from_bytes(data[pos:pos + 3], "big")
                pos += ln
            else:
                raise Fail("unexpected MIDI status %02X at offset %d" % (status, pos))
        pos = end
    if not payloads:
        raise Fail("%s contains no sysex messages" % path)
    return payloads, gaps


def write_smf(path, timed):
    """timed: list of (delay_ms, payload). Writes 1 tick == 1 ms."""
    def varint(n):
        out = bytearray([n & 0x7F])
        n >>= 7
        while n:
            out.insert(0, (n & 0x7F) | 0x80)
            n >>= 7
        return bytes(out)

    track = bytearray()
    track += b"\x00\xFF\x51\x03" + TEMPO_US.to_bytes(3, "big")
    for delay, payload in timed:
        body = payload + b"\xF7"
        track += varint(int(round(delay))) + b"\xF0" + varint(len(body)) + body
    track += b"\x00\xFF\x2F\x00"

    with open(path, "wb") as fh:
        fh.write(b"MThd" + struct.pack(">IHHH", 6, 0, 1, TICKS_PER_BEAT))
        fh.write(b"MTrk" + struct.pack(">I", len(track)) + bytes(track))


# ----------------------------------------------------------------------------
# Shared validation
# ----------------------------------------------------------------------------

def validate_update_file(path, quiet=False):
    payloads, gaps = read_smf(path)
    firmware, report = decode_stream(payloads)
    problems = []

    if not report["had_erase"]:
        problems.append("no DTA1ERASE. This file will not flash anything.")
    if len(payloads) < 3:
        problems.append("only %d messages. This is not a firmware image." % len(payloads))
    if len(gaps) > 1 and gaps[1] < ERASE_GAP_MS * 0.6:
        problems.append("gap after DTA1ERASE is %.0f ms, expected about %d ms. "
                        "Timing has been stripped. Sending this will write "
                        "into a flash that is still erasing."
                        % (gaps[1], ERASE_GAP_MS))
    if report["bytes"] % 8:
        problems.append("image is %d bytes, not a multiple of 8. The decoder "
                        "rounds the final block down and may drop trailing bytes."
                        % report["bytes"])

    if not quiet:
        print("  messages:   %d" % len(payloads))
        print("  blocks:     %d" % report["blocks"])
        print("  image size: %d bytes (%.2f MiB)"
              % (report["bytes"], report["bytes"] / 1048576.0))
        print("  erase gap:  %.0f ms" % (gaps[1] if len(gaps) > 1 else 0))
        print("  send time:  %.0f s" % (sum(gaps) / 1000.0))
        ok("global checksum verified")
    return firmware, report, gaps, problems


def require_mido():
    if mido is None:
        die("mido is not installed. Run: pip install mido python-rtmidi")


def resolve_port(substr, kind):
    names = mido.get_input_names() if kind == "input" else mido.get_output_names()
    hits = [n for n in names if substr.lower() in n.lower()]
    if not hits:
        die("no %s port matching %r.\n  Available: %s" % (kind, substr, names))
    if len(hits) > 1:
        die("%r matches several %s ports: %s" % (substr, kind, hits))
    return hits[0]


def preflight_prompt():
    print("\n  Before continuing, confirm all of these:")
    print("    - the amp shows a solid U on the display")
    print("    - the amp is on its AC adapter, NOT batteries")
    print("    - the USB cable is direct, not through a hub")
    print("    - no other MIDI application is open")
    print("    - your computer will not sleep for the next 5 minutes")
    return input("\n  Type %s to send, anything else to abort: " % CONFIRM_FLASH).strip()


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def cmd_selftest(args):
    print("Self-test: codec round-trip with synthetic firmware. No amp involved.\n")
    import random
    failures = 0
    for size in (0x100000, 0x80000, 0x40000, BLOCK_BYTES, BLOCK_BYTES * 3 + 8):
        random.seed(size)
        fw = bytes(random.getrandbits(8) for _ in range(size))
        timed = encode_stream(fw)
        write_smf(".selftest.mid", timed)
        payloads, gaps = read_smf(".selftest.mid")
        back, report = decode_stream(payloads)
        good = (back == fw
                and len(gaps) > 1 and abs(gaps[1] - ERASE_GAP_MS) < 1
                and report["blocks"] == (size + BLOCK_BYTES - 1) // BLOCK_BYTES)
        print("  %-10d bytes  %5d msgs  %s"
              % (size, len(payloads), "PASS" if good else "FAIL"))
        failures += not good

    print("\n  Negative tests (each of these must be caught):")
    random.seed(9)
    fw = bytes(random.getrandbits(8) for _ in range(BLOCK_BYTES * 4))
    base = encode_stream(fw)

    def expect_fail(label, payloads):
        try:
            decode_stream(payloads)
        except Fail as exc:
            print("    caught  %-22s %s" % (label, str(exc)[:52]))
            return 0
        print("    MISSED  %s" % label)
        return 1

    plain = [p for _, p in base]
    corrupt = list(plain)
    corrupt[2] = corrupt[2][:30] + bytes([corrupt[2][30] ^ 0x01]) + corrupt[2][31:]
    failures += expect_fail("flipped bit", corrupt)
    failures += expect_fail("truncated stream", plain[:-1])
    failures += expect_fail("dropped block", plain[:2] + plain[3:])
    bad_section = list(plain)
    bad_section[0] = bad_section[0][:12] + bytes([0x00])
    failures += expect_fail("erase targets section 0", bad_section)

    stripped = [(0, p) for p in plain]
    write_smf(".selftest2.mid", stripped)
    _, _, _, problems = validate_update_file(".selftest2.mid", quiet=True)
    if any("Timing has been stripped" in p for p in problems):
        print("    caught  %-22s stripped timing flagged" % "no erase gap")
    else:
        print("    MISSED  no erase gap")
        failures += 1

    for tmp in (".selftest.mid", ".selftest2.mid"):
        if os.path.exists(tmp):
            os.remove(tmp)

    print("\n%s" % ("ALL CHECKS PASSED" if not failures else "%d FAILURES" % failures))
    return 1 if failures else 0


def cmd_ports(args):
    require_mido()
    print("inputs:")
    for n in mido.get_input_names():
        print("  %s" % n)
    print("outputs:")
    for n in mido.get_output_names():
        print("  %s" % n)
    return 0


def cmd_dump(args):
    require_mido()
    state = load_state()
    inp = resolve_port(args.port, "input")
    out = resolve_port(args.port, "output")
    print("input:  %s\noutput: %s\n" % (inp, out))
    print("The amp must be showing a solid U. Nothing is written by this command.")
    if input("Press Enter to request the dump, or Ctrl-C to abort: ") is None:
        return 1

    captured, started, done = [], None, False
    with mido.open_input(inp) as port_in, mido.open_output(out) as port_out:
        while port_in.poll() is not None:
            pass
        req = list(DTA1ROMR)
        req[-1] = args.section
        port_out.send(mido.Message("sysex", data=req))
        print("\nsent DTA1ROMR (flash section %d). Expect up to 2.5 minutes of blocks."
              % args.section)
        last = time.monotonic()
        while time.monotonic() - last < args.timeout:
            msg = port_in.poll()
            if msg is None:
                time.sleep(0.002)
                continue
            last = time.monotonic()
            if msg.type != "sysex":
                continue
            if started is None:
                started = last
                print("  first block received")
            captured.append(bytes(msg.data))
            if len(captured) % 100 == 0:
                print("  %d messages" % len(captured), end="\r", flush=True)
            if b"DTA1CSUM" in captured[-1]:
                done = True
                break

    print()
    if not captured:
        die("the bootloader did not answer DTA1ROMR.\n"
            "  Nothing was written. Confirm the solid U and the port, then retry.\n"
            "  If it never answers, this amp cannot be backed up and you should\n"
            "  not cross-flash it.")
    print("captured %d messages in %.0fs\n" % (len(captured), time.monotonic() - started))
    if not done:
        die("no DTA1CSUM terminator. The dump is incomplete. Retry.")

    raw = args.out
    write_smf(raw, [(0, p) for p in captured])
    ok("wrote %s" % raw)

    if args.section != FLASH_SECTION_MAIN:
        print("  (not decoding: the codec only understands section %d)"
              % FLASH_SECTION_MAIN)
        return 0
    try:
        firmware, report = decode_stream(captured)
    except Fail as exc:
        die("the capture did not decode: %s\n"
            "  Keep %s anyway and send it to the thr10 project." % (exc, raw))
    ok("global checksum verified")

    binpath = os.path.splitext(raw)[0] + ".bin"
    open(binpath, "wb").write(firmware)
    ok("wrote %s (%d bytes, %d blocks)" % (binpath, len(firmware), report["blocks"]))
    if len(firmware) % 8:
        warn("image size is not a multiple of 8. Trailing bytes may be missing.")

    if args.section != FLASH_SECTION_MAIN:
        print("\n  Section %d archived. Workspace state left unchanged, since "
              "only section %d is the main firmware."
              % (args.section, FLASH_SECTION_MAIN))
        return 0
    state["dump_mid"] = raw
    state["dump_bin"] = binpath
    state["dump_sha"] = sha256(binpath)
    state["dump_size"] = len(firmware)
    state["drill_passed"] = False
    save_state(state)
    print("\n  sha256 %s" % state["dump_sha"])
    print("\nCopy both files to a second physical disk now, then run:")
    print("  python %s pack --bin %s --out restore.mid" % (sys.argv[0], binpath))
    return 0


def cmd_pack(args):
    state = load_state()
    firmware = open(args.bin, "rb").read()
    if not firmware:
        die("%s is empty" % args.bin)
    print("source: %s (%d bytes)" % (args.bin, len(firmware)))
    if state.get("dump_bin") and sha256(args.bin) != state.get("dump_sha"):
        warn("this is not the image this workspace dumped")

    write_smf(args.out, encode_stream(firmware))
    ok("wrote %s" % args.out)

    print("\nverifying the round trip:")
    back, _, _, problems = validate_update_file(args.out)
    if back != firmware:
        die("ROUND TRIP MISMATCH. %s does not reproduce %s. Do not flash it."
            % (args.out, args.bin))
    ok("byte-identical to %s" % args.bin)
    for p in problems:
        warn(p)

    if sha256(args.bin) == state.get("dump_sha"):
        state["restore_mid"] = args.out
        state["restore_sha"] = sha256(args.out)
        save_state(state)
        ok("registered as this workspace's restore image")
    return 0


def cmd_inspect(args):
    print("file: %s" % args.file)
    _, _, _, problems = validate_update_file(args.file)
    for p in problems:
        warn(p)
    print("\n%s" % ("no problems found" if not problems
                    else "%d problem(s) above" % len(problems)))
    return 1 if problems else 0


def cmd_flash(args):
    require_mido()
    state = load_state()
    print("file: %s" % args.file)
    _, report, gaps, problems = validate_update_file(args.file)
    for p in problems:
        warn(p)
    if problems and not args.force:
        die("refusing to send a file with problems. Fix them, or pass --force "
            "if you understand each one.")

    is_restore = state.get("restore_sha") and sha256(args.file) == state["restore_sha"]
    if is_restore:
        print("\n  This is your own backup. Sending it restores the amp.")
    else:
        print("\n  This is a FOREIGN image, not your backup.")
        if not state.get("drill_passed"):
            die("the restore drill has not passed in this workspace.\n"
                "  Flash your own backup first and confirm the amp still works.\n"
                "  That is the only thing proving you can undo this.\n"
                "    python %s flash --file %s"
                % (sys.argv[0], state.get("restore_mid", "restore.mid")))
        print("  Restore drill passed %s." % state["drill_passed"])
        print("  After this, %s is your only way back."
              % state.get("restore_mid", "your restore image"))
        if input("  Type %r to continue: " % CONFIRM_OVERRIDE).strip() != CONFIRM_OVERRIDE:
            die("aborted")

    port = resolve_port(args.port, "output")
    print("\noutput: %s" % port)
    if preflight_prompt() != CONFIRM_FLASH:
        die("aborted, nothing sent")

    payloads, gaps = read_smf(args.file)
    sent, start = 0, time.monotonic()
    try:
        with mido.open_output(port) as out:
            for i, payload in enumerate(payloads):
                wait = gaps[i] / 1000.0
                if wait > 1:
                    print("\n  waiting %.0fs for the erase, do not touch the amp" % wait)
                if wait:
                    time.sleep(wait)
                out.send(mido.Message("sysex", data=list(payload)))
                sent += 1
                if sent % 50 == 0:
                    print("  %d/%d  %.0fs" % (sent, len(payloads),
                                              time.monotonic() - start),
                          end="\r", flush=True)
    except KeyboardInterrupt:
        die("INTERRUPTED after %d/%d messages. Do NOT power cycle.\n"
            "  Re-enter update mode and send the whole file again."
            % (sent, len(payloads)))

    print("\nsent %d/%d messages in %.0fs" % (sent, len(payloads),
                                              time.monotonic() - start))
    if sent != len(payloads):
        die("SHORT SEND. Do not power cycle. Re-enter update mode and retry.")
    print("\n  Watch for E - n - d looping on the display, then power cycle.")

    if is_restore:
        elapsed = time.monotonic() - start
        expected = sum(gaps) / 1000.0
        print("\n  Drill review. A pass needs evidence the flash really ran,")
        print("  not just an amp that still works. It already had this firmware.")
        if elapsed < expected * 0.8:
            warn("took %.0fs, expected about %.0fs. The write may not have run."
                 % (elapsed, expected))
        else:
            ok("elapsed %.0fs, consistent with a real write" % elapsed)

        phases = [
            ("tuning triangles for roughly 16 seconds (erase)", "erase"),
            ("a flashing green dot afterwards (write)", "write"),
            ("E - n - d looping at the end", "end"),
            ("normal operation after a power cycle, all models and effects", "boot"),
        ]
        answers = {}
        for question, key in phases:
            answers[key] = input("    Did you see %s? [yes/no] "
                                 % question).strip().lower() == "yes"
        if all(answers.values()):
            state["drill_passed"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            state["drill_seconds"] = round(elapsed)
            save_state(state)
            ok("restore drill recorded as passed")
            print("\n  Recommended: confirm the flash is bit-exact with")
            print("    python %s verify --port %s" % (sys.argv[0], args.port))
        else:
            state["drill_passed"] = False
            save_state(state)
            missing = [k for k, v in answers.items() if not v]
            warn("drill NOT recorded (missing: %s). Do not cross-flash."
                 % ", ".join(missing))
    return 0


def cmd_verify(args):
    """Re-dump the amp and compare against the recorded backup."""
    require_mido()
    state = load_state()
    if not state.get("dump_sha"):
        die("no backup recorded in this workspace. Run dump first.")

    inp = resolve_port(args.port, "input")
    out = resolve_port(args.port, "output")
    print("Re-reading the amp to compare against the recorded backup.")
    print("Nothing is written. The amp must show a solid U.\n")
    input("Press Enter to continue, or Ctrl-C to abort: ")

    captured, done = [], False
    with mido.open_input(inp) as pi, mido.open_output(out) as po:
        while pi.poll() is not None:
            pass
        po.send(mido.Message("sysex", data=DTA1ROMR))
        last = time.monotonic()
        while time.monotonic() - last < args.timeout:
            msg = pi.poll()
            if msg is None:
                time.sleep(0.002)
                continue
            last = time.monotonic()
            if msg.type != "sysex":
                continue
            captured.append(bytes(msg.data))
            if len(captured) % 100 == 0:
                print("  %d messages" % len(captured), end="\r", flush=True)
            if b"DTA1CSUM" in captured[-1]:
                done = True
                break
    print()
    if not done:
        die("re-read did not complete. Try again before drawing conclusions.")

    firmware, _ = decode_stream(captured)
    fresh = hashlib.sha256(firmware).hexdigest()
    print("  recorded: %s" % state["dump_sha"])
    print("  on amp:   %s" % fresh)
    if fresh == state["dump_sha"]:
        ok("bit-exact match. The amp holds exactly what your backup contains.")
        return 0
    warn("MISMATCH. The amp does not hold your recorded backup.")
    print("  If you have not flashed anything, your backup is unreliable.")
    print("  If you just cross-flashed, this is expected.")
    return 1


def cmd_extract(args):
    """Decode any update file to a raw firmware image and identify it."""
    print("file: %s" % args.file)
    firmware, report, gaps, problems = validate_update_file(args.file)
    for p in problems:
        warn(p)
    open(args.out, "wb").write(firmware)
    ok("wrote %s" % args.out)
    print("\n  sha256 %s" % hashlib.sha256(firmware).hexdigest())

    # .fwinfo sits in the last 0x30 bytes of DTAm (rom 0x210FFD0, base 0x2010000)
    tail = firmware[-0x30:]
    printable = "".join(chr(c) if 32 <= c < 127 else "." for c in tail)
    print("\n  build info (last 0x30 bytes):")
    print("    %s" % printable)
    if b"DTAm" in tail:
        ok("DTAm identifier present, this is a main firmware image")
    else:
        warn("no DTAm identifier in the tail. Layout may differ from the THR10.")

    trailing = len(firmware) - len(firmware.rstrip(b"\xFF"))
    print("\n  trailing 0xFF padding: %d bytes (%.0f KiB free)"
          % (trailing, trailing / 1024.0))
    return 0


def cmd_status(args):
    state = load_state()
    if not state:
        print("no workspace yet. Start with: python %s dump --port THR" % sys.argv[0])
        return 0
    rows = [
        ("dump (.mid)", state.get("dump_mid", "-")),
        ("dump (.bin)", state.get("dump_bin", "-")),
        ("dump sha256", state.get("dump_sha", "-")),
        ("image size", state.get("dump_size", "-")),
        ("restore image", state.get("restore_mid", "-")),
        ("drill passed", state.get("drill_passed") or "NO"),
        ("last updated", state.get("updated", "-")),
    ]
    for k, v in rows:
        print("  %-14s %s" % (k, v))
    for path in (state.get("dump_bin"), state.get("restore_mid")):
        if path and not os.path.exists(path):
            warn("%s is missing from disk" % path)
    if state.get("dump_bin") and os.path.exists(state["dump_bin"]):
        if sha256(state["dump_bin"]) != state["dump_sha"]:
            warn("%s no longer matches its recorded sha256" % state["dump_bin"])
    print("\n  cross-flash allowed: %s" % ("yes" if state.get("drill_passed") else "NO"))
    return 0


def cmd_notes(args):
    print(__doc__)
    print("""
Safety notes
------------
The update protocol carries no model identifier. The bootloader cannot tell
a THR5 image from a THR5A image, so nothing will stop you writing the wrong
one. The only guard is the backup you take first.

DTA1ERASE targets flash section 2, which is the main firmware (DTAm). The
bootloader lives in section 0 and is not touched, so a failed or interrupted
write should leave update mode reachable. This tool refuses to send any file
whose erase message names a section other than 2.

Yamaha has never published firmware for the THR5A. If you cross-flash it,
your own dump is the only restore image that exists anywhere.

Run on the AC adapter. A battery dying mid-write is the one failure this
tool cannot help with.

Order: selftest, dump, pack, flash your own restore image, confirm the amp
is normal, and only then flash anything else.
""")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Back up, verify and flash Yamaha THR main firmware.")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    sub.add_parser("ports").set_defaults(fn=cmd_ports)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("notes").set_defaults(fn=cmd_notes)

    p = sub.add_parser("dump")
    p.add_argument("--port", required=True, help="substring of the THR port name")
    p.add_argument("--out", default="thr_stock.mid")
    p.add_argument("--timeout", type=float, default=30.0,
                   help="seconds of silence before giving up")
    p.add_argument("--section", type=lambda v: int(v, 0), default=2,
                   help="flash section to read (2 = DTAm main firmware, the "
                        "default; other values are exploratory and read-only)")
    p.set_defaults(fn=cmd_dump)

    p = sub.add_parser("pack")
    p.add_argument("--bin", required=True)
    p.add_argument("--out", default="restore.mid")
    p.set_defaults(fn=cmd_pack)

    p = sub.add_parser("inspect")
    p.add_argument("--file", required=True)
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser("verify")
    p.add_argument("--port", required=True)
    p.add_argument("--timeout", type=float, default=30.0)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("extract")
    p.add_argument("--file", required=True, help="an update .mid")
    p.add_argument("--out", required=True, help="raw .bin to write")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("flash")
    p.add_argument("--port", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--force", action="store_true",
                   help="send despite validation problems")
    p.set_defaults(fn=cmd_flash)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1
    try:
        return args.fn(args)
    except Fail as exc:
        die(str(exc))
    except FileNotFoundError as exc:
        die(str(exc))


if __name__ == "__main__":
    sys.exit(main())
