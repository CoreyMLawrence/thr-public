#!/usr/bin/env python3
"""
thr_map.py - the differential parameter mapper.

Finds out which live command address controls which byte of the settings
block, with no listening required:

    1. read the settings block (baseline)
    2. send one parameter command to one address
    3. read the block again and diff it against the baseline
    4. put the amp back by sending the baseline block
    5. repeat for every address

Nothing here writes to flash. Everything is undone by a power cycle, and the
mapper also restores the baseline after every single probe.

    python thr_map.py selftest            offline, no amp: prove the diff logic
    python thr_map.py control             probe the KNOWN addresses, check offsets
    python thr_map.py sweep               control first, then every address 0..127
    python thr_map.py sweep --from 7 --to 15   just a range

Before running control or sweep:
    - amp booted NORMALLY (not update mode), on its AC adapter
    - physical VOLUME knob low, guitar unplugged or muted
    - THR Editor closed (it holds the port)

Gates, enforced in code:
    - no heartbeat, no send. The bootloader has no heartbeat, and in update
      mode message type 0x30 means ERASE. A live heartbeat proves we are
      talking to the running firmware.
    - every block read is checked for length, header and checksum. A checksum
      alone cannot catch inserted zeros (see 09-failures-and-fixes.md §7).
    - sweep refuses to run unless the positive control passes first.
    - after every probe the baseline is restored and read back. If it does not
      come back identical, the run stops.

Results go to map/ next to this script: a raw JSONL log of every probe and a
MAP.md summary.

Requires thr_live.py in the same folder, and mido + python-rtmidi for the amp.
"""
import argparse
import datetime
import json
import os
import random
import sys
import time

import thr_live as L

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "map")

EXPECTED_HEADER = bytes([0x43, 0x7D, 0x00, 0x02, 0x0C, 0x44, 0x54, 0x41, 0x31,
                         0x41, 0x6C, 0x6C, 0x50, 0x00, 0x00, 0x7F, 0x7F])

# Known address -> body offset, from 04/05 of the knowledge base. Used as the
# positive control: if the mapper cannot rediscover these, it cannot be trusted
# to discover anything else.
CONTROL = {
    0x01: 146,   # gain
    0x02: 147,   # master
    0x03: 148,   # bass
    0x04: 149,   # middle
    0x05: 150,   # treble
    0x06: 151,   # cabinet
    0x11: 162,   # comp stomp sustain
    0x12: 163,   # comp stomp output
}

# Default probe values. Both are quiet and valid for any 0..100 control, and
# they differ from each other, so a field that already holds one of them
# still shows up under the other.
DEFAULT_VALUES = [5, 11]

# The amp broadcasts F0 43 7D 30 41 30 02 04 F7 about twice a second. It is a
# periodic status message, not a reply, so it is recorded separately.
STATUS_PREFIX = bytes([0x43, 0x7D, 0x30, 0x41, 0x30])
ECHO_PREFIX = bytes(L.CMD)

SETTLE = 0.15          # seconds between a command and the read that follows
READ_TIMEOUT = 2.0
HEARTBEAT_MAX_AGE = 3.0


class MapperError(Exception):
    pass


def hexs(b):
    return " ".join("%02X" % x for x in b)


def validate_block(d):
    """Length, header, checksum. Raises MapperError on any failure."""
    if len(d) != L.DUMP_LEN:
        raise MapperError("block is %d bytes, expected %d. Refusing to trust "
                          "its offsets." % (len(d), L.DUMP_LEN))
    if bytes(d[:L.PAYLOAD_AT]) != EXPECTED_HEADER:
        raise MapperError("block header is wrong: %s" % hexs(d[:L.PAYLOAD_AT]))
    if L.yamaha_checksum(d[L.CHK_FROM:-1]) != d[-1]:
        raise MapperError("block checksum mismatch")
    return bytes(d)


def param_msg(addr, value):
    """One address byte plus a 14-bit value, the format every PARAMS entry uses."""
    return L.CMD + [addr] + L.midi_int(value)


# ---------------------------------------------------------------------------
# Transports. Both expose the same four methods, so the mapping logic below
# cannot tell a real amp from the fake one.
# ---------------------------------------------------------------------------

class RealAmp:
    def __init__(self, port):
        if L.mido is None:
            raise MapperError("mido is not installed. pip install mido python-rtmidi")
        inp, out = L.find(port)
        self.inp = L.mido.open_input(inp)
        self.out = L.mido.open_output(out)
        self.names = (inp, out)
        self.model_id = None
        self.last_beat = 0.0
        self.unsolicited = []
        self.status = set()

    def close(self):
        self.inp.close()
        self.out.close()

    def _pump(self, want_block=False, timeout=0.0):
        """Drain input. Track heartbeats. Return a block if one arrives."""
        end = time.monotonic() + timeout
        while True:
            m = self.inp.poll()
            if m is None:
                if time.monotonic() >= end:
                    return None
                time.sleep(0.003)
                continue
            if m.type != "sysex":
                continue
            d = bytes(m.data)
            if d.startswith(L.HEARTBEAT) and len(d) > len(L.HEARTBEAT):
                self.model_id = d[len(L.HEARTBEAT)]
                self.last_beat = time.monotonic()
                continue
            if want_block and len(d) >= 200:
                return d
            if d.startswith(STATUS_PREFIX):
                self.status.add(hexs(d))
                continue
            self.unsolicited.append(hexs(d))

    def heartbeat_ok(self):
        self._pump()
        if time.monotonic() - self.last_beat <= HEARTBEAT_MAX_AGE:
            return True
        self._pump(timeout=HEARTBEAT_MAX_AGE)
        return time.monotonic() - self.last_beat <= HEARTBEAT_MAX_AGE

    def send(self, msg):
        self.out.send(L.mido.Message("sysex", data=msg))

    def read_block(self):
        self._pump()
        self.send(L.settings_request(0x31))
        d = self._pump(want_block=True, timeout=READ_TIMEOUT)
        if d is None:
            raise MapperError("no settings block came back")
        return validate_block(d)

    def take_unsolicited(self):
        u, self.unsolicited = self.unsolicited, []
        return u


class FakeAmp:
    """A simulated amp for the self-test. Planted behaviour:
       - the known control addresses map to their known offsets
       - address 0x00 clamps the amp index to the panel (like the real one)
       - address 0x07 maps to body 152, an 'undiscovered' single byte
       - address 0x19 is a 14-bit field at body 170..171 (address + 145, as on the real amp)
       - body 260 flickers on every read (a volatile byte, must be ignored)
       - broken=True: commands are ignored (the control must then FAIL)
       - misalign=True: reads come back with two extra zeros (must be refused)
       - silent=True: no heartbeat (sends must be refused)
    """
    def __init__(self, baseline, broken=False, misalign=False, silent=False):
        self.block = bytearray(baseline)
        self.broken, self.misalign, self.silent = broken, misalign, silent
        self.model_id = None if silent else 0x34
        self.names = ("fake in", "fake out")
        self.sent = 0

    def close(self):
        pass

    def heartbeat_ok(self):
        return not self.silent

    def _fix(self):
        self.block[-1] = L.yamaha_checksum(self.block[L.CHK_FROM:-1])

    def send(self, msg):
        self.sent += 1
        if self.broken:
            return
        if list(msg[:len(L.CMD)]) == L.CMD and len(msg) == len(L.CMD) + 3:
            addr, hi, lo = msg[len(L.CMD):]
            value = (hi << 7) | lo                # inverse of midi_int
            if addr == 0x00:
                self.block[145] = min(value, 4)
            elif addr in CONTROL:
                self.block[CONTROL[addr]] = min(value, 100)
            elif addr == 0x07:
                self.block[152] = value & 0x7F
            elif addr == 0x19:
                self.block[170], self.block[171] = hi, lo
            self._fix()
        elif len(msg) == L.DUMP_LEN and bytes(msg[:L.PAYLOAD_AT]) == EXPECTED_HEADER:
            self.block = bytearray(msg)            # settings-block load
            self._fix()

    def read_block(self):
        self.block[260] = random.randint(0, 0x7F)
        self._fix()
        d = bytes(self.block)
        if self.misalign:
            d = d[:20] + b"\x00\x00" + d[20:]
        return validate_block(d)

    def take_unsolicited(self):
        return []


# ---------------------------------------------------------------------------
# The mapper
# ---------------------------------------------------------------------------

class Mapper:
    def __init__(self, amp, log=None, settle=SETTLE):
        self.amp = amp
        self.log = log
        self.settle = settle
        self.baseline = None
        self.volatile = set()

    def gate(self):
        if not self.amp.heartbeat_ok():
            raise MapperError("no heartbeat from the amp. Refusing to send. Is it "
                              "booted normally, not in update mode?")

    def capture_baseline(self, reads=4):
        self.gate()
        blocks = [self.amp.read_block() for _ in range(reads)]
        self.baseline = blocks[0]
        self.volatile = {i for i in range(len(self.baseline) - 1)
                         if len({b[i] for b in blocks}) > 1}
        return self.baseline

    def diff(self, block):
        return [(i, self.baseline[i], block[i])
                for i in range(len(block) - 1)          # skip the checksum
                if i not in self.volatile and block[i] != self.baseline[i]]

    def restore(self):
        self.amp.send(list(self.baseline))
        time.sleep(self.settle)
        back = self.amp.read_block()
        if self.diff(back):
            # one retry, then stop hard
            self.amp.send(list(self.baseline))
            time.sleep(self.settle * 2)
            back = self.amp.read_block()
            left = self.diff(back)
            if left:
                raise MapperError("baseline did not restore; still differs at %s. "
                                  "Stopping. Power-cycle the amp to reset."
                                  % ", ".join(str(i) for i, _, _ in left))

    def probe(self, addr, values):
        result = {"addr": addr, "values": {}, "unsolicited": []}
        for v in values:
            self.gate()
            self.amp.send(param_msg(addr, v))
            time.sleep(self.settle)
            after = self.amp.read_block()
            changes = self.diff(after)
            result["values"][v] = [{"offset": i, "payload": i - L.PAYLOAD_AT,
                                    "was": a, "now": b} for i, a, b in changes]
            result["unsolicited"] += self.amp.take_unsolicited()
            if changes:
                self.restore()
        if self.log:
            self.log.write(json.dumps(result) + "\n")
            self.log.flush()
        return result

    def control(self, values=DEFAULT_VALUES, say=print):
        """Rediscover every known address. Returns True only if all match."""
        ok = True
        for addr, want in sorted(CONTROL.items()):
            r = self.probe(addr, values)
            hit = {c["offset"] for cs in r["values"].values() for c in cs}
            good = want in hit
            extra = sorted(hit - {want})
            say("  0x%02X -> expect body %d: %s%s"
                % (addr, want, "PASS" if good else "FAIL, saw %s" % (sorted(hit) or "nothing"),
                   "  (also moved %s)" % extra if good and extra else ""))
            ok = ok and good
        return ok



# ---------------------------------------------------------------------------
# Pass 2: ranges, types, loader
# ---------------------------------------------------------------------------

RANGE_VALUES = [0, 127, 16383]   # below, at and above any 7-bit or 14-bit range
WINDOW_END = 0x5F                # sweep 1: 0x60+ moves nothing in the block

# blocks whose meaning changes with a type selector: name, type address,
# type values, the addresses that belong to the block
TYPE_BLOCKS = [
    ("amp",    0x00, range(5), range(0x01, 0x10)),
    ("comp",   0x10, range(2), range(0x11, 0x20)),
    ("mod",    0x20, range(4), range(0x21, 0x30)),
    ("reverb", 0x40, range(4), range(0x41, 0x50)),
]
TYPE_NAMES = {"amp": ["panel 1", "panel 2", "panel 3", "panel 4", "panel 5"],
              "comp": L.COMP_TYPES, "mod": L.MOD_TYPES, "reverb": L.REVERB_TYPES}


def body_of(addr):
    return L.PAYLOAD_AT + 128 + addr


def parse_echoes(raw):
    """Parameter messages the amp sent on its own: [(addr, value)]."""
    out = []
    for h in raw:
        b = bytes(int(x, 16) for x in h.split())
        if b.startswith(ECHO_PREFIX) and len(b) == len(ECHO_PREFIX) + 3:
            a, hi, lo = b[len(ECHO_PREFIX):]
            out.append((a, (hi << 7) | lo))
    return out


def range_probe(m, addr):
    """Send 0, 127, 16383 to one address. Work out width, range, side effects."""
    at = body_of(addr)
    seen, side, echoes = {}, set(), []
    for v in RANGE_VALUES:
        m.gate()
        m.amp.send(param_msg(addr, v))
        time.sleep(m.settle)
        b = m.amp.read_block()
        ch = m.diff(b)
        seen[v] = (b[at], b[at + 1] if at + 1 < len(b) - 1 else None)
        side |= {i for i, _, _ in ch if i not in (at, at + 1)}
        echoes += parse_echoes(m.amp.take_unsolicited())
        if ch:
            m.restore()
    lo_moved = any(s[1] is not None and s[1] != m.baseline[at + 1] for s in seen.values())
    width = 2 if lo_moved else 1
    dec = (lambda s: (s[0] << 7) | s[1]) if width == 2 else (lambda s: s[0])
    lo_v, hi_v = dec(seen[0]), dec(seen[16383])
    full = 16383 if width == 2 else 127
    if lo_v == 0 and hi_v == full:
        kind = "raw"
    else:
        kind = "clamped"
    r = {"addr": addr, "body": at, "width": width, "min": lo_v, "max": hi_v,
         "mid": dec(seen[127]), "kind": kind, "baseline": dec((m.baseline[at], m.baseline[at + 1])),
         "side_effects": sorted(side), "echoes": echoes}
    if m.log:
        m.log.write(json.dumps({"pass": "range", **r}) + "\n")
        m.log.flush()
    return r


def fmt_range(r):
    s = "%s  width %d  " % ("0x%02X" % r["addr"], r["width"])
    if r["kind"] == "raw":
        s += "RAW, stores anything (0..%d)" % r["max"]
    else:
        s += "CLAMPED to %d..%d" % (r["min"], r["max"])
    if r["side_effects"]:
        s += "  also moves %s" % r["side_effects"]
    if r["echoes"]:
        s += "  amp says %s" % ", ".join("0x%02X=%d" % e for e in r["echoes"][:4])
    return s


def type_pass(m, say=print):
    """For each type of each typed block: record the defaults the amp loads,
    then range-probe every address in the block under that type."""
    original = m.baseline
    out = []
    try:
        for name, taddr, tvals, addrs in TYPE_BLOCKS:
            for t in tvals:
                m.baseline = original
                m.gate()
                m.amp.send(param_msg(taddr, t))
                time.sleep(m.settle * 3)
                sub = m.amp.read_block()
                echoes = parse_echoes(m.amp.take_unsolicited())
                loaded = [(i, original[i], sub[i]) for i, _, _ in
                          [(i, 0, 0) for i in range(len(sub) - 1)] if sub[i] != original[i]]
                m.baseline = sub
                tname = TYPE_NAMES[name][t] if t < len(TYPE_NAMES[name]) else str(t)
                say("\n[%s = %d, %s]  type switch changed body %s%s"
                    % (name, t, tname, [i for i, _, _ in loaded] or "nothing",
                       "  amp says %s" % ", ".join("0x%02X=%d" % e for e in echoes) if echoes else ""))
                rows = []
                for a in addrs:
                    r = range_probe(m, a)
                    rows.append(r)
                    say("  " + fmt_range(r))
                out.append({"block": name, "type": t, "type_name": tname,
                            "switch_changed": loaded, "switch_echoes": echoes, "fields": rows})
                m.baseline = sub
                m.amp.send(list(original))
                time.sleep(m.settle)
    finally:
        m.baseline = original
        m.restore()
    return out


def loader_pass(m, first=L.PAYLOAD_AT, last=L.DUMP_LEN - 2, say=print):
    """Poke each zero byte of the block through the settings LOADER and read back.
    Tells us which bytes the firmware keeps, resets, or reacts to."""
    out = []
    for off in range(first, last + 1):
        if m.baseline[off] != 0:
            continue
        v = 0x41 if off < L.PAYLOAD_AT + 64 else 1      # 'A' in the name field
        body = bytearray(m.baseline)
        body[off] = v
        body[-1] = L.yamaha_checksum(body[L.CHK_FROM:-1])
        m.gate()
        m.amp.send(list(body))
        time.sleep(m.settle)
        b = m.amp.read_block()
        echoes = parse_echoes(m.amp.take_unsolicited())
        other = [(i, x, y) for i, x, y in m.diff(b) if i != off]
        if b[off] == v:
            res = "kept"
        elif b[off] == 0:
            res = "reset to 0"
        else:
            res = "changed to %d" % b[off]
        r = {"offset": off, "payload": off - L.PAYLOAD_AT, "sent": v, "read": b[off],
             "result": res, "side_effects": other, "echoes": echoes}
        out.append(r)
        if m.log:
            m.log.write(json.dumps({"pass": "loader", **r}) + "\n")
            m.log.flush()
        if res != "kept" or other or echoes:
            say("  body %3d  %s%s%s" % (off, res,
                "  also moved %s" % [i for i, _, _ in other] if other else "",
                "  amp says %s" % echoes if echoes else ""))
        m.restore()
    kept = [r["offset"] for r in out if r["result"] == "kept"]
    say("  %d of %d zero bytes kept exactly as sent" % (len(kept), len(out)))
    return out

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def known_name(offset):
    p = offset - L.PAYLOAD_AT
    for off, name, size in L.FIELDS:
        if off <= p < off + size:
            return name
    return ""


def write_map(results, mapper, amp, path, started):
    lines = ["# THR live parameter map", "",
             "Generated by `thr_map.py sweep`. Every row is a measured result: "
             "the command `F0 43 7D 10 41 30 01 <addr> <v-hi> <v-lo> F7` was sent, "
             "the settings block re-read, and the bytes that changed recorded. "
             "Raw data is in `map_log.jsonl` beside this file.", "",
             "- run started: %s" % started,
             "- amp heartbeat model id: %s" % ("0x%02X (%s)" % (
                 amp.model_id, L.MODELS.get(amp.model_id, "?")) if amp.model_id is not None else "none"),
             "- ports: %s / %s" % amp.names,
             "- volatile bytes excluded from diffs: %s" % (
                 ", ".join(str(i) for i in sorted(mapper.volatile)) or "none"),
             "- baseline block (body, 274 bytes):", "", "```"]
    b = mapper.baseline
    for i in range(0, len(b), 16):
        lines.append("%3d  %s" % (i, hexs(b[i:i + 16])))
    lines += ["```", "", "## Addresses that moved a byte", "",
              "| addr | value sent | body offset | payload offset | was -> now | known field |",
              "|---|---|---|---|---|---|"]
    quiet = []
    for r in results:
        rows = [(v, c) for v, cs in r["values"].items() for c in cs]
        if not rows:
            quiet.append(r["addr"])
            continue
        for v, c in rows:
            lines.append("| 0x%02X | %s | %d | %d | %d -> %d | %s |"
                         % (r["addr"], v, c["offset"], c["payload"], c["was"], c["now"],
                            known_name(c["offset"]) or "**unknown**"))
    lines += ["", "## Addresses with no visible effect on the block", "",
              ", ".join("0x%02X" % a for a in quiet) or "none", "",
              "No effect in the block does not mean no effect on the sound. "
              "A command can act on the DSP without being stored in the patch. "
              "These are candidates for a listening pass, not proven dead.", ""]
    noisy = [r for r in results if r["unsolicited"]]
    if noisy:
        lines += ["## Addresses that made the amp send something back", ""]
        for r in noisy:
            lines.append("- 0x%02X: %s" % (r["addr"], "; ".join(r["unsolicited"][:4])))
        lines.append("")
    open(path, "w", encoding="utf-8").write("\n".join(lines))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def load_baseline_file(path):
    raw = open(path, "rb").read()
    if raw[:1] != b"\xF0" or raw[-1:] != b"\xF7":
        raise MapperError("%s is not a complete sysex message" % path)
    return validate_block(raw[1:-1])


def cmd_selftest(args):
    base = load_baseline_file(os.path.join(HERE, "settings.syx"))
    fails = 0

    def check(name, cond):
        nonlocal fails
        print("  %-58s %s" % (name, "ok" if cond else "FAILED"))
        fails += 0 if cond else 1

    print("selftest: fake amp, real THR5A baseline from settings.syx\n")

    amp = FakeAmp(base)
    m = Mapper(amp, settle=0)
    m.capture_baseline()
    check("volatile byte 260 detected and excluded", 260 in m.volatile)
    check("positive control passes on a working amp",
          m.control(say=lambda s: None))
    r7 = m.probe(0x07, DEFAULT_VALUES)
    check("planted unknown 0x07 found at body 152",
          all(any(c["offset"] == 152 for c in cs) for cs in r7["values"].values()))
    r19 = m.probe(0x19, [300])
    check("planted 14-bit 0x19 found at body 170 and 171",
          {c["offset"] for c in r19["values"][300]} == {170, 171})
    r0 = m.probe(0x00, [6])
    check("amp index clamp visible (sent 6, block shows 4)",
          any(c["offset"] == 145 and c["now"] == 4 for c in r0["values"][6]))
    rq = m.probe(0x30, DEFAULT_VALUES)
    check("inert address 0x30 reports nothing", not any(rq["values"].values()))
    check("baseline restored after all probes", not m.diff(amp.read_block()))

    ra = range_probe(m, 0x01)
    check("range: gain reads CLAMPED 0..100, width 1",
          ra["kind"] == "clamped" and (ra["min"], ra["max"], ra["width"]) == (0, 100, 1))
    rr = range_probe(m, 0x07)
    check("range: planted 0x07 reads RAW 0..127", rr["kind"] == "raw" and rr["max"] == 127)
    rw = range_probe(m, 0x19)
    check("range: planted 0x19 reads width 2, RAW 0..16383",
          rw["width"] == 2 and rw["max"] == 16383)
    lp = loader_pass(m, first=150, last=160, say=lambda s: None)
    check("loader: fake amp keeps every poked byte",
          lp and all(r["result"] == "kept" for r in lp))
    check("baseline restored after range and loader passes", not m.diff(amp.read_block()))

    print("\nplanted faults, each must be caught:\n")
    m2 = Mapper(FakeAmp(base, broken=True), settle=0)
    m2.capture_baseline()
    check("control FAILS when the amp ignores commands",
          not m2.control(say=lambda s: None))
    try:
        Mapper(FakeAmp(base, misalign=True), settle=0).capture_baseline()
        check("misaligned block (two extra zeros) refused", False)
    except MapperError:
        check("misaligned block (two extra zeros) refused", True)
    silent = FakeAmp(base, silent=True)
    try:
        Mapper(silent, settle=0).capture_baseline()
        check("no heartbeat -> nothing sent", False)
    except MapperError:
        check("no heartbeat -> nothing sent", silent.sent == 0)
    bad = bytearray(base)
    bad[150] ^= 1
    try:
        validate_block(bytes(bad))
        check("corrupted byte refused by checksum", False)
    except MapperError:
        check("corrupted byte refused by checksum", True)

    print("\n%s" % ("ALL PASSED" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


def open_real(args):
    amp = RealAmp(args.port)
    print("ports: in=%r out=%r" % amp.names)
    return amp


def cmd_control(args):
    amp = open_real(args)
    try:
        m = Mapper(amp)
        m.capture_baseline()
        print("heartbeat: 0x%02X (%s)" % (amp.model_id, L.MODELS.get(amp.model_id, "?")))
        print("baseline captured, volatile bytes: %s\n"
              % (sorted(m.volatile) or "none"))
        ok = m.control()
        print("\n%s" % ("CONTROL PASSED. The mapper sees what the amp does."
                        if ok else "CONTROL FAILED. Do not trust a sweep."))
        return 0 if ok else 1
    finally:
        amp.close()


def cmd_sweep(args):
    values = [int(v, 0) for v in args.values.split(",")]
    os.makedirs(OUT_DIR, exist_ok=True)
    started = datetime.datetime.now().isoformat(timespec="seconds")
    stamp = started.replace(":", "").replace("-", "")
    log_path = os.path.join(OUT_DIR, "map_log_%s.jsonl" % stamp)
    md_path = os.path.join(OUT_DIR, "MAP_%s.md" % stamp)

    amp = open_real(args)
    results = []
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            m = Mapper(amp, log=log)
            m.capture_baseline()
            print("heartbeat: 0x%02X (%s)" % (amp.model_id, L.MODELS.get(amp.model_id, "?")))
            print("volatile bytes: %s\n" % (sorted(m.volatile) or "none"))
            print("positive control:")
            if not m.control(values):
                print("\nCONTROL FAILED. Sweep not run.")
                return 1
            print("\nsweeping 0x%02X..0x%02X with values %s\n"
                  % (args.start, args.end, values))
            for addr in range(args.start, args.end + 1):
                r = m.probe(addr, values)
                results.append(r)
                hit = sorted({c["offset"] for cs in r["values"].values() for c in cs})
                tag = ""
                if hit:
                    names = [known_name(o) or "UNKNOWN" for o in hit]
                    tag = "  -> body %s  %s" % (hit, names)
                print("  0x%02X%s%s" % (addr, tag,
                                        "  [amp replied]" if r["unsolicited"] else ""))
    except MapperError as e:
        print("\nSTOPPED: %s" % e)
    finally:
        amp.close()
        if results:
            write_map(results, m, amp, md_path, started)
            print("\nwrote %s\n      %s" % (md_path, log_path))
    return 0


def write_deep(path, amp, m, started, ranges, types, loader):
    L_ = ["# THR deep map: ranges, types, loader", "",
          "Generated by `thr_map.py deep`. Every line is measured on the amp. "
          "Raw data is in the JSONL file with the same timestamp.", "",
          "- run started: %s" % started,
          "- heartbeat model id: 0x%02X (%s)" % (amp.model_id, L.MODELS.get(amp.model_id, "?")),
          "- periodic status broadcasts seen: %s" % (", ".join(sorted(getattr(amp, "status", []))) or "none"),
          "", "## How to read this", "",
          "- **CLAMPED a..b**: the firmware limited the value. It has a range for this "
          "field, so it is a real parameter, and a..b is the slider range.",
          "- **RAW**: the firmware stored whatever was sent. Either the field has no "
          "limit, or it is unused storage. Needs a listening check.",
          "- **width 2**: a 14-bit field, high byte at the address, low byte after it.",
          "- **amp says**: parameter messages the amp broadcast on its own after the write.",
          "", "## Pass A: every address, current patch", "",
          "| addr | body | payload | width | result | baseline | side effects | amp says |",
          "|---|---|---|---|---|---|---|---|"]
    for r in ranges:
        res = "RAW 0..%d" % r["max"] if r["kind"] == "raw" else "**CLAMPED %d..%d**" % (r["min"], r["max"])
        L_.append("| 0x%02X | %d | %d | %d | %s | %d | %s | %s |" % (
            r["addr"], r["body"], r["body"] - L.PAYLOAD_AT, r["width"], res, r["baseline"],
            r["side_effects"] or "", ", ".join("0x%02X=%d" % e for e in r["echoes"])))
    L_ += ["", "## Pass B: per type", ""]
    for t in types:
        L_ += ["### %s = %d (%s)" % (t["block"], t["type"], t["type_name"]), "",
               "Switching to this type changed body %s. Amp broadcast: %s." % (
                   [i for i, _, _ in t["switch_changed"]] or "nothing",
                   ", ".join("0x%02X=%d" % e for e in t["switch_echoes"]) or "nothing"), "",
               "| addr | width | result | value after switch |", "|---|---|---|---|"]
        for r in t["fields"]:
            res = "RAW 0..%d" % r["max"] if r["kind"] == "raw" else "**CLAMPED %d..%d**" % (r["min"], r["max"])
            L_.append("| 0x%02X | %d | %s | %d |" % (r["addr"], r["width"], res, r["baseline"]))
        L_.append("")
    L_ += ["## Pass C: settings loader, every zero byte", "",
           "Each zero byte was set (to 0x41 'A' in the name field, 1 elsewhere) and "
           "loaded as a whole block, then read back.", ""]
    groups = {}
    for r in loader:
        groups.setdefault(r["result"], []).append(r["offset"])
    for res, offs in sorted(groups.items()):
        L_.append("- **%s**: %d bytes: %s" % (res, len(offs), compress(offs)))
    odd = [r for r in loader if r["side_effects"] or r["echoes"]]
    if odd:
        L_ += ["", "Loader writes with side effects:", ""]
        for r in odd:
            L_.append("- body %d: moved %s, amp says %s" % (
                r["offset"], [i for i, _, _ in r["side_effects"]], r["echoes"]))
    open(path, "w", encoding="utf-8").write("\n".join(L_) + "\n")


def compress(nums):
    """[1,2,3,7,8] -> '1-3, 7-8'"""
    out, i = [], 0
    nums = sorted(nums)
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else "%d-%d" % (nums[i], nums[j]))
        i = j + 1
    return ", ".join(out) or "none"


def cmd_deep(args):
    os.makedirs(OUT_DIR, exist_ok=True)
    started = datetime.datetime.now().isoformat(timespec="seconds")
    stamp = started.replace(":", "").replace("-", "")
    log_path = os.path.join(OUT_DIR, "deep_log_%s.jsonl" % stamp)
    md_path = os.path.join(OUT_DIR, "DEEP_%s.md" % stamp)
    amp = open_real(args)
    ranges, types, loader = [], [], []
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            m = Mapper(amp, log=log)
            m.capture_baseline()
            print("heartbeat: 0x%02X (%s)" % (amp.model_id, L.MODELS.get(amp.model_id, "?")))
            print("positive control:")
            if not m.control():
                print("CONTROL FAILED. Nothing else run.")
                return 1
            if "a" in args.passes:
                print("\n== pass A: ranges, 0x00..0x%02X ==" % WINDOW_END)
                for a in range(0x00, WINDOW_END + 1):
                    r = range_probe(m, a)
                    ranges.append(r)
                    print("  " + fmt_range(r))
            if "b" in args.passes:
                print("\n== pass B: every type of every typed block ==")
                types = type_pass(m)
            if "c" in args.passes:
                print("\n== pass C: settings loader, byte by byte ==")
                loader = loader_pass(m)
            final = m.amp.read_block()
            print("\nfinal state %s the starting patch"
                  % ("matches" if not m.diff(final) else "DIFFERS FROM"))
    except MapperError as e:
        print("\nSTOPPED: %s" % e)
    finally:
        amp.close()
        write_deep(md_path, amp, m, started, ranges, types, loader)
        print("\nwrote %s\n      %s" % (md_path, log_path))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="THR")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("selftest", help="offline proof of the diff logic").set_defaults(fn=cmd_selftest)
    sub.add_parser("control", help="rediscover the known addresses").set_defaults(fn=cmd_control)
    p = sub.add_parser("sweep", help="control, then map every address")
    p.add_argument("--from", dest="start", type=lambda v: int(v, 0), default=0x00)
    p.add_argument("--to", dest="end", type=lambda v: int(v, 0), default=0x7F)
    p.add_argument("--values", default=",".join(str(v) for v in DEFAULT_VALUES),
                   help="comma-separated probe values, default 5,11")
    p.set_defaults(fn=cmd_sweep)
    p = sub.add_parser("deep", help="ranges, per-type fields, and the loader")
    p.add_argument("--passes", default="abc", help="any of a (ranges) b (types) c (loader)")
    p.set_defaults(fn=cmd_deep)
    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1
    try:
        return args.fn(args)
    except MapperError as e:
        print("\nSTOPPED: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
