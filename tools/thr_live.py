#!/usr/bin/env python3
"""
thr_live.py - talk to a THR in NORMAL operation, over the same SysEx channel
the THR Editor uses.

This writes nothing to flash. It sets live parameters only, so a power cycle
undoes everything it does. The amp must be booted normally, NOT in update mode.

    python thr_live.py listen                 read the heartbeat, identify the amp
    python thr_live.py amp aco                select an amp model
    python thr_live.py amp 6                  same thing by index
    python thr_live.py models                 list what the firmware knows
    python thr_live.py watch                  log everything the amp sends

Protocol from the sysex_tones project (github.com/SysExTones/sysex_tones),
which documented the THR10 parameter format:

    command   F0 43 7D 10 41 30 01 <addr-hi> <addr-lo> <value> F7
    heartbeat F0 43 7D 60 44 54 41 <model>   F7     (sent by the amp, ~2/sec)

Requires: pip install mido python-rtmidi
"""
import argparse
import sys
import time

try:
    import mido
except ImportError:
    mido = None

# F0 43 7D 10 41 30 01 -- leading F0 is added by mido
CMD = [0x43, 0x7D, 0x10, 0x41, 0x30, 0x01]
HEARTBEAT = bytes([0x43, 0x7D, 0x60, 0x44, 0x54, 0x41])

# The THR10/THR5 model list, from the reference project.
AMPS = ["Clean", "Crunch", "Lead", "BritHi", "Modern", "Bass", "Aco", "Flat"]
PANEL = 5                      # the THR5 knob only reaches the first five

# The THR5A is an acoustic amp with its own voicings, so the list above does
# not describe it. Nobody has published its internal order, and the indices
# are what matter, so positions are reported by number until confirmed.
AMPS_5A = None


def amp_name(idx, model_id=None):
    """Label an amp index, honestly, for whichever firmware is loaded."""
    if model_id == 0x34:
        if AMPS_5A and idx < len(AMPS_5A):
            return AMPS_5A[idx]
        return "panel position %d" % (idx + 1) if idx < PANEL else "beyond the panel"
    if idx < len(AMPS):
        return AMPS[idx]
    return "beyond the model list"
CABS = ["US4x12", "US2x12", "Brit4x12", "Brit2x12", "1x12", "4x10", "None"]

MODELS = {0x30: "THR5", 0x31: "THR10", 0x32: "THR10X",
          0x33: "THR10C", 0x34: "THR5A"}

ADDR = {"amp": (0x00, 0x00), "cab": (0x06, 0x00)}

# Parameter map from the sysex_tones project. Each entry is
#   name: (address bytes, kind, low, high)
# kind "fixed" carries its value in the address itself, "byte" appends one
# 7-bit byte, and "int" appends a 14-bit value split across two bytes.
PARAMS = {
    # switches and type selectors
    "comp":       ([0x1F, 0x00], "switch", 0, 0),
    "comp.type":  ([0x10, 0x00], "byte", 0, 1),      # 0 Stomp, 1 Rack
    "mod":        ([0x2F, 0x00], "switch", 0, 0),
    "mod.type":   ([0x20, 0x00], "byte", 0, 3),      # Chorus Flanger Tremolo Phaser
    "delay":      ([0x3F, 0x00], "switch", 0, 0),
    "reverb":     ([0x4F, 0x00], "switch", 0, 0),
    "reverb.type":([0x40, 0x00], "byte", 0, 3),      # Hall Room Plate Spring
    "gate":       ([0x5F, 0x00], "switch", 0, 0),

    # amp controls
    "gain":       ([0x01, 0x00], "byte", 0, 100),
    "master":     ([0x02, 0x00], "byte", 0, 100),
    "bass":       ([0x03, 0x00], "byte", 0, 100),
    "middle":     ([0x04, 0x00], "byte", 0, 100),
    "treble":     ([0x05, 0x00], "byte", 0, 100),

    # compressor, Stomp mode
    "comp.sustain":  ([0x11, 0x00], "byte", 0, 100),
    "comp.output":   ([0x12, 0x00], "byte", 0, 100),
    # compressor, Rack mode
    "rack.threshold":([0x11], "int", 0, 600),
    "rack.attack":   ([0x13, 0x00], "byte", 0, 100),
    "rack.release":  ([0x14, 0x00], "byte", 0, 100),
    "rack.ratio":    ([0x15, 0x00], "byte", 0, 5),
    "rack.knee":     ([0x16, 0x00], "byte", 0, 2),
    "rack.output":   ([0x17], "int", 0, 600),

    # modulation
    "mod.speed":   ([0x21, 0x00], "byte", 0, 100),
    "mod.depth":   ([0x22, 0x00], "byte", 0, 100),
    "mod.mix":     ([0x23, 0x00], "byte", 0, 100),
    "mod.manual":  ([0x22, 0x00], "byte", 0, 100),
    "mod.feedback":([0x24, 0x00], "byte", 0, 100),
    "mod.spread":  ([0x25, 0x00], "byte", 0, 100),

    # delay
    "delay.time":     ([0x31], "int", 1, 9999),
    "delay.feedback": ([0x33, 0x00], "byte", 0, 100),
    "delay.highcut":  ([0x34], "int", 1000, 16001),
    "delay.lowcut":   ([0x36], "int", 21, 8000),
    "delay.level":    ([0x38, 0x00], "byte", 0, 100),

    # reverb
    "reverb.time":      ([0x41], "int", 3, 200),
    "reverb.amount":    ([0x41, 0x00], "byte", 0, 100),
    "reverb.filter":    ([0x42, 0x00], "byte", 0, 100),
    "reverb.pre":       ([0x43], "int", 1, 2000),
    "reverb.lowcut":    ([0x45], "int", 21, 8000),
    "reverb.highcut":   ([0x47], "int", 1000, 16001),
    "reverb.highratio": ([0x49, 0x00], "byte", 1, 10),
    "reverb.lowratio":  ([0x4A, 0x00], "byte", 1, 14),
    "reverb.level":     ([0x4B, 0x00], "byte", 0, 100),

    # noise gate
    "gate.threshold": ([0x51, 0x00], "byte", 0, 100),
    "gate.release":   ([0x52, 0x00], "byte", 0, 100),
}

COMP_TYPES = ["Stomp", "Rack"]
MOD_TYPES = ["Chorus", "Flanger", "Tremolo", "Phaser"]
REVERB_TYPES = ["Hall", "Room", "Plate", "Spring"]

# system commands use a different prefix
SYS = [0x43, 0x7D, 0x30, 0x41, 0x30]
SYSTEM = {"wide": [0x00], "lamp": [0x01]}


def token(name):
    import re
    return re.sub(r"\s+\d+$", "", (name or "").strip()) or (name or "")


def find(substr):
    if mido is None:
        sys.exit("mido is not installed. Run: pip install mido python-rtmidi")
    ins, outs = mido.get_input_names(), mido.get_output_names()
    def match(names, q):
        hits = [n for n in names if q.lower() in n.lower()]
        if not hits:
            hits = [n for n in names if token(q).lower() in n.lower()]
        if len(hits) > 1:
            thr = [n for n in hits if "thr" in n.lower()]
            if len(thr) == 1:
                return thr
        return hits
    i, o = match(ins, substr), match(outs, substr)
    if not i or not o:
        sys.exit("No port matching %r.\n  Inputs: %s\n  Outputs: %s"
                 % (substr, ", ".join(ins) or "none", ", ".join(outs) or "none"))
    return i[0], o[0]


def cmd_listen(args):
    inp, _ = find(args.port)
    print("Listening on %s for up to %.0fs." % (inp, args.timeout))
    print("The amp must be booted NORMALLY, not in update mode.\n")
    seen = {}
    with mido.open_input(inp) as pi:
        end = time.monotonic() + args.timeout
        while time.monotonic() < end:
            m = pi.poll()
            if m is None:
                time.sleep(0.005)
                continue
            if m.type != "sysex":
                continue
            d = bytes(m.data)
            if d.startswith(HEARTBEAT) and len(d) > len(HEARTBEAT):
                mid = d[len(HEARTBEAT)]
                seen[mid] = seen.get(mid, 0) + 1
                if seen[mid] == 1:
                    print("  heartbeat -> model id 0x%02X  (%s)"
                          % (mid, MODELS.get(mid, "unrecognised")))
    if not seen:
        print("  No heartbeat. Either the amp is in update mode, another app holds")
        print("  the port, or this firmware does not emit one.")
        return 1
    print("\n  %d heartbeat(s). The amp identifies itself as: %s"
          % (sum(seen.values()),
             ", ".join("0x%02X (%s)" % (k, MODELS.get(k, "unrecognised")) for k in seen)))
    return 0


def cmd_watch(args):
    inp, _ = find(args.port)
    print("Logging every sysex message from %s. Ctrl-C to stop.\n" % inp)
    try:
        with mido.open_input(inp) as pi:
            while True:
                m = pi.poll()
                if m is None:
                    time.sleep(0.005)
                    continue
                if m.type != "sysex":
                    continue
                d = bytes(m.data)
                tag = ""
                if d.startswith(HEARTBEAT):
                    tag = "  <- heartbeat, model 0x%02X %s" % (
                        d[len(HEARTBEAT)], MODELS.get(d[len(HEARTBEAT)], "?"))
                print("F0 %s F7%s" % (" ".join("%02X" % b for b in d), tag))
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def cmd_models(args):
    print("Amp models known to this firmware:\n")
    for i, name in enumerate(AMPS):
        where = "on the THR5 knob" if i < PANEL else "SysEx only on a THR5"
        print("  %d  %-7s  %s" % (i, name, where))
    print("\nCabinets (SysEx only, the THR5 has no cab control):\n")
    for i, name in enumerate(CABS):
        print("  %d  %s" % (i, name))
    print("\n  python %s amp aco" % sys.argv[0])
    return 0


# ---------------------------------------------------------------------------
# Bulk settings block. A separate code path from the parameter command, which
# is why it is worth trying when the parameter command clamps.
#   276 bytes = 18 header + 256 payload + 1 checksum + F7
#   checksum  = ((~sum(bytes[6:-2])) + 1) & 0x7F
#   amp index at payload offset 128, cabinet at 134
# ---------------------------------------------------------------------------

DUMP_PREFIX = [0x43, 0x7D, 0x00, 0x02, 0x0C]          # after F0
DUMP_TAG = [0x44, 0x54, 0x41]                          # "DTA"
ALLP = [0x41, 0x6C, 0x6C, 0x50]                        # "AllP"
DUMP_POSTFIX = [0x00, 0x00, 0x7F, 0x7F]
CHK_FROM = 5          # payloads here exclude F0, so the C offset of 6 is 5
PAYLOAD_AT = 17       # ditto: 18 header bytes minus the F0
AMP_AT = PAYLOAD_AT + 128
CAB_AT = PAYLOAD_AT + 134
DUMP_LEN = 274        # 276 on the wire minus the F0 and F7 mido strips


def yamaha_checksum(data):
    return ((~sum(data)) + 1) & 0x7F


def settings_request(model_id):
    return [0x43, 0x7D, 0x20] + DUMP_TAG + [model_id] + ALLP


def cmd_settings(args):
    inp, out = find(args.port)
    mid = int(args.model, 0) if args.model else None

    got = None
    # 0x31 is part of the request format, not a model selector: it is what a
    # THR5 build answers to. The others are kept as fallbacks.
    for candidate in ([mid] if mid is not None else [0x31, 0x30, 0x34]):
        req = settings_request(candidate)
        print("requesting with model byte 0x%02X: F0 %s F7"
              % (candidate, " ".join("%02X" % b for b in req)))
        with mido.open_input(inp) as pi, mido.open_output(out) as po:
            while pi.poll() is not None:
                pass
            po.send(mido.Message("sysex", data=req))
            end = time.monotonic() + 2.5
            while time.monotonic() < end:
                m = pi.poll()
                if m is None:
                    time.sleep(0.004)
                    continue
                if m.type != "sysex":
                    continue
                d = bytes(m.data)
                if d.startswith(HEARTBEAT):
                    continue
                print("  reply, %d bytes on the wire" % (len(d) + 2))
                if len(d) >= 200:
                    got = d
                    break
        if got:
            break
        print("  no settings block")

    if not got:
        print("\nNo settings block came back. Either this firmware does not answer "
              "the request, or the model byte is wrong. Try --model 0x31.")
        return 1

    print()
    if len(got) != DUMP_LEN:
        print("  note: %d bytes, expected %d. Offsets below may be shifted."
              % (len(got), DUMP_LEN))
    chk_ok = len(got) >= 2 and yamaha_checksum(got[CHK_FROM:-1]) == got[-1]
    print("  checksum: %s" % ("verified" if chk_ok else "MISMATCH, treat with care"))
    if len(got) > AMP_AT:
        a, c = got[AMP_AT], got[CAB_AT] if len(got) > CAB_AT else None
        print("  amp index %d (%s)" % (a, AMPS[a] if a < len(AMPS) else "out of range"))
        if c is not None:
            print("  cab index %d (%s)" % (c, CABS[c] if c < len(CABS) else "out of range"))
        name = bytes(got[PAYLOAD_AT:PAYLOAD_AT + 64]).split(b"\x00")[0]
        print("  patch name: %r" % name.decode("ascii", "replace"))

    open(args.out, "wb").write(bytes([0xF0]) + got + b"\xF7")
    print("\n  saved %s (%d bytes on the wire)" % (args.out, len(got) + 2))
    print("  next: python %s poke --file %s --offset %d --value 6"
          % (sys.argv[0], args.out, AMP_AT))
    return 0


def cmd_poke(args):
    """Change one byte in a saved settings block, fix the checksum, send it."""
    raw = bytearray(open(args.file, "rb").read())
    if raw[0] != 0xF0 or raw[-1] != 0xF7:
        sys.exit("%s is not a complete sysex message." % args.file)
    body = raw[1:-1]                      # strip F0 and F7, as mido wants
    off, val = args.offset, args.value
    if not 0 <= off < len(body):
        sys.exit("offset out of range, the body is %d bytes" % len(body))
    if not 0 <= val <= 0x7F:
        sys.exit("value must be 0..127, MIDI data bytes are 7-bit")

    was = body[off]
    body[off] = val
    body[-1] = yamaha_checksum(body[CHK_FROM:-1])
    what = "offset %d: %d -> %d" % (off, was, val)
    if off == AMP_AT:
        what += "  (amp index %d -> %d)" % (was, val)
    print("file:    %s" % args.file)
    print("change:  %s" % what)
    print("checksum recomputed: 0x%02X" % body[-1])
    if args.save:
        open(args.save, "wb").write(bytes([0xF0]) + bytes(body) + b"\xF7")
        print("saved:   %s" % args.save)
    return raw_send(args, list(body), "bulk settings load, " + what)


def cmd_raw(args):
    """Send arbitrary sysex, for experiments. F0 and F7 are optional."""
    txt = args.hex.replace(",", " ").replace("0x", " ")
    try:
        b = [int(x, 16) for x in txt.split()]
    except ValueError:
        sys.exit("could not parse %r as hex bytes" % args.hex)
    if b and b[0] == 0xF0:
        b = b[1:]
    if b and b[-1] == 0xF7:
        b = b[:-1]
    if any(x > 0x7F for x in b):
        sys.exit("data bytes must be 0..127 inside a sysex message")
    return raw_send(args, b, "raw sysex, %d data bytes" % len(b))


# Known payload offsets, from the reference project's decoder. Body offsets are
# these plus PAYLOAD_AT, because mido strips the leading F0.
FIELDS = [
    (0,   "patch name", 64),
    (128, "amp model", 1),
    (129, "gain", 1), (130, "master", 1), (131, "bass", 1),
    (132, "middle", 1), (133, "treble", 1),
    (134, "cabinet", 1),
    (144, "comp type", 1), (149, "comp ratio", 1), (150, "comp knee", 1),
    (159, "comp bypass", 1),
    (160, "mod type", 1), (175, "mod bypass", 1),
    (191, "delay bypass", 1),
    (207, "reverb bypass", 1),
]


def cmd_report(args):
    """One read-only pass that collects everything worth knowing, to paste."""
    print("=" * 68)
    print("THR REPORT")
    print("=" * 68)

    if mido is None:
        print("mido not installed")
        return 1
    print("\n[ports]")
    try:
        for n in mido.get_input_names():
            print("  in   %s" % n)
        for n in mido.get_output_names():
            print("  out  %s" % n)
    except Exception as e:
        print("  MIDI backend unavailable (%s). Run: pip install python-rtmidi"
              % type(e).__name__)
        return 1

    try:
        inp, out = find(args.port)
    except SystemExit as e:
        print("\n%s" % e)
        return 1
    print("  using in=%r out=%r" % (inp, out))

    print("\n[heartbeat]")
    seen = {}
    with mido.open_input(inp) as pi:
        end = time.monotonic() + 4
        while time.monotonic() < end:
            m = pi.poll()
            if m is None:
                time.sleep(0.004)
                continue
            if m.type == "sysex":
                d = bytes(m.data)
                if d.startswith(HEARTBEAT) and len(d) > len(HEARTBEAT):
                    seen[d[len(HEARTBEAT)]] = seen.get(d[len(HEARTBEAT)], 0) + 1
    model_id = None
    if seen:
        for k, v in seen.items():
            print("  model id 0x%02X (%s), %d beats"
                  % (k, MODELS.get(k, "unrecognised"), v))
        model_id = sorted(seen, key=lambda k: -seen[k])[0]
    else:
        print("  none. Amp in update mode, port held elsewhere, or no heartbeat.")

    print("\n[settings block]")
    got = None
    for cand in [0x31, 0x30, 0x34]:
        with mido.open_input(inp) as pi, mido.open_output(out) as po:
            while pi.poll() is not None:
                pass
            po.send(mido.Message("sysex", data=settings_request(cand)))
            end = time.monotonic() + 2.0
            while time.monotonic() < end:
                m = pi.poll()
                if m is None:
                    time.sleep(0.004)
                    continue
                if m.type == "sysex":
                    d = bytes(m.data)
                    if not d.startswith(HEARTBEAT) and len(d) >= 200:
                        got = d
                        print("  request byte 0x%02X answered, %d bytes on the wire"
                              % (cand, len(d) + 2))
                        break
                    if not d.startswith(HEARTBEAT):
                        print("  request byte 0x%02X: short reply, %d bytes"
                              % (cand, len(d) + 2))
        if got:
            break
        print("  request byte 0x%02X: no block" % cand)

    if not got:
        print("  no settings block available")
        return 1

    ok = yamaha_checksum(got[CHK_FROM:-1]) == got[-1]
    print("  header    %s" % " ".join("%02X" % b for b in got[:PAYLOAD_AT]))
    print("  checksum  0x%02X %s" % (got[-1], "verified" if ok else "MISMATCH"))
    print("  data bytes %d, payload starts at body offset %d"
          % (len(got), PAYLOAD_AT))

    print("\n[decoded fields]   body offset = payload + %d" % PAYLOAD_AT)
    for off, name, size in FIELDS:
        b = PAYLOAD_AT + off
        if b + size > len(got):
            continue
        if size > 1:
            raw = bytes(got[b:b + size]).split(b"\x00")[0]
            print("  %-4d %-14s %r" % (b, name, raw.decode("ascii", "replace")))
        else:
            v = got[b]
            extra = ""
            if name == "amp model":
                extra = "  %s" % amp_name(v, model_id)
            elif name == "cabinet":
                extra = "  %s" % (CABS[v] if v < len(CABS) else "OUT OF RANGE")
            elif name.endswith("bypass"):
                extra = "  %s" % ("off" if v else "on")
            elif name == "comp type":
                extra = "  %s" % (COMP_TYPES[v] if v < len(COMP_TYPES) else "?")
            elif name == "mod type":
                extra = "  %s" % (MOD_TYPES[v] if v < len(MOD_TYPES) else "?")
            elif name == "reverb type":
                extra = "  %s" % (REVERB_TYPES[v] if v < len(REVERB_TYPES) else "?")
            print("  %-4d %-14s %3d  0x%02X%s" % (b, name, v, v, extra))

    print("\n[full block, body only, %d bytes]" % len(got))
    for i in range(0, len(got), 16):
        print("  %3d  %s" % (i, " ".join("%02X" % b for b in got[i:i + 16])))

    open(args.out, "wb").write(bytes([0xF0]) + got + b"\xF7")
    print("\n  saved %s" % args.out)

    print("\n[clamp test: run these and listen after each]")
    if model_id == 0x34:
        print("  This is the acoustic firmware. The THR10 names do not apply,")
        print("  so positions 1-5 are your panel and 6-8 are past it.")
    for i in range(8):
        print("  python %s poke --file %s --offset %d --value %d   # %s"
              % (sys.argv[0], args.out, AMP_AT, i, amp_name(i, model_id)))
    print("\n[parameter-command comparison, expected to clamp]")
    print("  python %s amp 6" % sys.argv[0])
    print("=" * 68)
    return 0


def midi_int(i):
    """14-bit value split into two 7-bit bytes, as the THR expects."""
    v = ((i & 0x3F80) << 1) | (i & 0x007F)
    return [(v >> 8) & 0xFF, v & 0xFF]


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def raw_send(args, msg, what):
    print("sending: F0 %s F7" % " ".join("%02X" % b for b in msg))
    print("meaning: %s" % what)
    if args.dry_run:
        print("\ndry run. Nothing sent, and no MIDI backend needed.")
        return 0
    _, out = find(args.port)
    print("port:    %s" % out)
    with mido.open_output(out) as po:
        po.send(mido.Message("sysex", data=msg))
    print("\nSent. This is a live parameter only, so a power cycle undoes it.")
    print("Nothing was written to flash.")
    return 0


def cmd_set(args):
    key = args.param.lower()
    if key not in PARAMS:
        near = [k for k in PARAMS if key.split(".")[0] in k]
        sys.exit("Unknown parameter %r.%s\n  Run 'params' for the full list."
                 % (args.param, "\n  Did you mean: " + ", ".join(sorted(near)) if near else ""))
    addr, kind, lo, hi = PARAMS[key]
    raw = args.value

    if kind == "switch":
        on = raw.lower() in ("on", "1", "true", "yes")
        off = raw.lower() in ("off", "0", "false", "no")
        if not (on or off):
            sys.exit("%s takes on or off." % key)
        return raw_send(args, CMD + addr + [0x00 if on else 0x7F],
                        "%s %s" % (key, "on" if on else "off"))

    # named values for the type selectors
    names = {"comp.type": COMP_TYPES, "mod.type": MOD_TYPES,
             "reverb.type": REVERB_TYPES}.get(key)
    if names and not raw.lstrip("-").isdigit():
        low = [n.lower() for n in names]
        if raw.lower() not in low:
            sys.exit("%s takes one of: %s" % (key, ", ".join(names)))
        val = low.index(raw.lower())
    else:
        try:
            val = int(raw)
        except ValueError:
            sys.exit("%s takes a number between %d and %d." % (key, lo, hi))

    capped = clamp(val, lo, hi)
    note = "" if capped == val else "  (clamped from %d)" % val
    if names:
        note += "  = " + names[capped] if capped < len(names) else ""

    if kind == "int":
        return raw_send(args, CMD + addr + midi_int(capped),
                        "set %s to %d%s" % (key, capped, note))
    return raw_send(args, CMD + addr + [capped],
                    "set %s to %d%s" % (key, capped, note))


def cmd_params(args):
    print("Live parameters. Switches take on/off, the rest take a number.\n")
    groups = {}
    for k, (a, kind, lo, hi) in sorted(PARAMS.items()):
        groups.setdefault(k.split(".")[0], []).append((k, kind, lo, hi))
    for g in sorted(groups):
        print("  %s" % g)
        for k, kind, lo, hi in groups[g]:
            rng = "on | off" if kind == "switch" else "%d..%d" % (lo, hi)
            print("    %-18s %-10s %s" % (k, kind, rng))
        print()
    print("  Named values: comp.type %s | mod.type %s | reverb.type %s"
          % (" ".join(COMP_TYPES), " ".join(MOD_TYPES), " ".join(REVERB_TYPES)))
    print("\n  python %s set comp on" % sys.argv[0])
    print("  python %s set comp.sustain 70" % sys.argv[0])
    return 0


def cmd_system(args):
    if args.name.lower() not in SYSTEM:
        sys.exit("Unknown system setting. Try: %s" % ", ".join(SYSTEM))
    on = args.value.lower() in ("on", "1", "true", "yes")
    return raw_send(args, SYS + SYSTEM[args.name.lower()] + [0x00 if on else 0x01],
                    "%s %s" % (args.name, "on" if on else "off"))


def send(args, hi, lo, value, what):
    msg = CMD + [hi, lo, value]
    print("sending: F0 %s F7" % " ".join("%02X" % b for b in msg))
    print("meaning: %s" % what)
    if args.dry_run:
        print("\ndry run. Nothing sent, and no MIDI backend needed.")
        return 0
    _, out = find(args.port)       # only touch MIDI when actually sending
    print("port:    %s" % out)
    with mido.open_output(out) as po:
        po.send(mido.Message("sysex", data=msg))
    print("\nSent. This is a live parameter only, so a power cycle undoes it.")
    print("Nothing was written to flash.")
    return 0


def cmd_amp(args):
    v = args.value
    if v.isdigit():
        idx = int(v)
    else:
        low = [a.lower() for a in AMPS]
        if v.lower() not in low:
            sys.exit("Unknown model %r. Try: %s" % (v, ", ".join(AMPS)))
        idx = low.index(v.lower())
    if not 0 <= idx <= 0x7F:
        sys.exit("value out of range")
    if idx >= len(AMPS):
        print("Note: index %d is past the %d models this firmware lists. The amp "
              "may ignore it.\n" % (idx, len(AMPS)))
    name = AMPS[idx] if idx < len(AMPS) else "index %d" % idx
    extra = "" if idx < PANEL else "  (not reachable from the THR5 panel)"
    return send(args, *ADDR["amp"], idx, "select amp model %d, %s%s" % (idx, name, extra))


def cmd_cab(args):
    v = args.value
    if v.isdigit():
        idx = int(v)
    else:
        low = [c.lower() for c in CABS]
        if v.lower() not in low:
            sys.exit("Unknown cabinet %r. Try: %s" % (v, ", ".join(CABS)))
        idx = low.index(v.lower())
    name = CABS[idx] if idx < len(CABS) else "index %d" % idx
    return send(args, *ADDR["cab"], idx, "select cabinet %d, %s" % (idx, name))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="THR", help="substring of the THR port name")
    ap.add_argument("--dry-run", action="store_true", help="print bytes, send nothing")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("listen", help="read the heartbeat and identify the amp")
    p.add_argument("--timeout", type=float, default=6.0)
    p.set_defaults(fn=cmd_listen)

    sub.add_parser("watch", help="log every sysex message the amp sends").set_defaults(fn=cmd_watch)
    sub.add_parser("models", help="list the amp models and cabinets").set_defaults(fn=cmd_models)

    p = sub.add_parser("amp", help="select an amp model by name or index")
    p.add_argument("value")
    p.set_defaults(fn=cmd_amp)

    p = sub.add_parser("cab", help="select a speaker cabinet by name or index")
    p.add_argument("value")
    p.set_defaults(fn=cmd_cab)

    p = sub.add_parser("set", help="set any live parameter, e.g. set comp on")
    p.add_argument("param")
    p.add_argument("value")
    p.set_defaults(fn=cmd_set)

    sub.add_parser("params", help="list every parameter and its range").set_defaults(fn=cmd_params)

    p = sub.add_parser("system", help="wide stereo or the tube lamp: system wide on")
    p.add_argument("name")
    p.add_argument("value")
    p.set_defaults(fn=cmd_system)

    p = sub.add_parser("settings", help="request the whole 256-byte settings block")
    p.add_argument("--out", default="settings.syx")
    p.add_argument("--model", default=None, help="model byte, e.g. 0x30; tries several by default")
    p.set_defaults(fn=cmd_settings)

    p = sub.add_parser("poke", help="change one byte in a saved block and send it back")
    p.add_argument("--file", required=True)
    p.add_argument("--offset", type=lambda v: int(v, 0), required=True)
    p.add_argument("--value", type=lambda v: int(v, 0), required=True)
    p.add_argument("--save", default=None, help="also write the modified block here")
    p.set_defaults(fn=cmd_poke)

    p = sub.add_parser("report", help="one read-only pass collecting everything")
    p.add_argument("--out", default="settings.syx")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("raw", help='send arbitrary sysex, e.g. raw "43 7D 10 41 30 01 00 01 06"')
    p.add_argument("hex")
    p.set_defaults(fn=cmd_raw)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
