/**
 * Yamaha THR SysEx Protocol Engine
 * Handles message encoding, decoding, checksum calculation, parameter addresses, and factory presets.
 */

const THR = {
  // Manufacturer & Model Constants
  MANUFACTURER_ID: 0x43, // Yamaha
  GROUP_ID: 0x7D,

  // Message Types
  MSG_PARAM: 0x10,     // Host <-> Amp single parameter
  MSG_REQ_BLOCK: 0x20, // Host -> Amp request settings block
  MSG_SYSTEM: 0x30,    // Host <-> Amp system settings
  MSG_BLOCK: 0x00,     // Amp -> Host (and Host -> Amp) full settings block
  MSG_HEARTBEAT: 0x60, // Amp -> Host heartbeat (~2/sec)

  // Hardware Model IDs from Heartbeat
  MODELS: {
    0x30: { name: "THR5", desc: "Yamaha THR5 (or Hybrid V23)" },
    0x31: { name: "THR10", desc: "Yamaha THR10 Classic" },
    0x32: { name: "THR10X", desc: "Yamaha THR10X High Gain" },
    0x33: { name: "THR10C", desc: "Yamaha THR10C Classic Vintage" },
    0x34: { name: "THR5A", desc: "Yamaha THR5A Acoustic" }
  },

  // Unified Amp Models (Electric, Acoustic & Studio in Harmony)
  ALL_MODELS: [
    { id: 0, name: "Clean", category: "electric", tag: "Fender Twin style clean sparkle", badge: "ELECTRIC", icon: "✨", unlocked: false },
    { id: 1, name: "Crunch", category: "electric", tag: "Vox AC30 chime & edge-of-breakup", badge: "ELECTRIC", icon: "🎸", unlocked: false },
    { id: 2, name: "Lead", category: "electric", tag: "Marshall Plexi classic roar", badge: "ELECTRIC", icon: "🔥", unlocked: false },
    { id: 3, name: "Brit Hi", category: "electric", tag: "Marshall JCM800 high gain punch", badge: "ELECTRIC", icon: "⚡", unlocked: false },
    { id: 4, name: "Modern", category: "electric", tag: "Mesa Dual Rectifier wall of gain", badge: "ELECTRIC", icon: "🤘", unlocked: false },
    { id: 5, name: "Bass", category: "electric", tag: "Ampeg SVT clean punchy tube bass", badge: "BASS", icon: "🎻", unlocked: true },
    { id: 6, name: "ACO", category: "acoustic", tag: "Acoustic mic simulation (condenser profile)", badge: "ACOUSTIC", icon: "🌿", unlocked: true },
    { id: 7, name: "Flat", category: "acoustic", tag: "Flat linear studio monitor / FRFR voicing", badge: "FLAT", icon: "🎛️", unlocked: true },
    { id: 8, name: "Pure DI", category: "acoustic", tag: "Complete DSP bypass (zero coloration)", badge: "BYPASS", icon: "🔌", unlocked: true }
  ],
  get AMPS_THR5() { return this.ALL_MODELS; },
  get AMPS_THR5A() { return this.ALL_MODELS; },

  // Speaker Cabinets
  CABINETS: [
    { id: 0, name: "US 4x12", desc: "American oversized 4x12 with V30s" },
    { id: 1, name: "US 2x12", desc: "American open-back 2x12" },
    { id: 2, name: "Brit 4x12", desc: "British 4x12 angled vintage stack" },
    { id: 3, name: "Brit 2x12", desc: "British 2x12 combo cabinet" },
    { id: 4, name: "1x12", desc: "Compact 1x12 open-back" },
    { id: 5, name: "4x10", desc: "Tweed style 4x10 punchy cabinet" },
    { id: 6, name: "Direct / Bypass", desc: "No cabinet simulation (Studio DI / Acoustic)" }
  ],

  // Yamaha Modular DSP Coprocessor Blocks (Direct Register Access via F0 43 10 47)
  DSP_BLOCKS: {
    0: { name: "Input & Preamp", code: "PRE", desc: "Analog input stage, ADC calibration, input pad and gain scaling" },
    1: { name: "Amp Modeling & Master Voicing", code: "AMP", desc: "Virtual tube modeling jump table, non-linear distortion curves and master speaker EQ (Setting 0x02)" },
    2: { name: "Tone Stack & EQ", code: "EQ", desc: "Passive/Active 3-Band tone stack filter network and tone shaping" },
    3: { name: "Dynamics & Compressor", code: "COMP", desc: "VCA/Opto dynamic compressor, threshold, discrete attack, release, and knee" },
    4: { name: "VCM Vintage Modulation", code: "MOD", desc: "Virtual Circuitry Modeling phaser, flanger, chorus, tremolo and LFO oscillators" },
    5: { name: "Stereo Delay", code: "DLY", desc: "High-resolution digital delay buffer, feedback network, damping filters" },
    6: { name: "Yamaha SREV2 Studio Reverb", code: "REV", desc: "Yamaha Spatial Reverb 2: 14 early reflection taps, pre-delay, room diffusion and HF damping" },
    7: { name: "Cabinet & Spatializer", code: "CAB", desc: "Speaker cabinet impulse simulation, stereo imaging spread and 20-band acoustic tuning bank" }
  },

  // Apple-grade Room Presence Profiles powered by Yamaha SREV2 DSP Coprocessor
  ROOM_PRESENCE_PROFILES: {
    studio: {
      id: "studio",
      name: "Studio Direct",
      tag: "Tight & Dry",
      desc: "Laser-focused studio acoustic, tight transient punch for recording and fast tracking",
      preDelay: 0,
      erLevel: 0x0000,
      diffusion: 0x1200,
      hfDamping: 0x6000
    },
    room: {
      id: "room",
      name: "In The Room",
      tag: "Natural 3D Combo",
      desc: "Natural acoustic air and dimension of a real guitar amplifier playing right in front of you",
      preDelay: 20,
      erLevel: 0x2800,
      diffusion: 0x3800,
      hfDamping: 0x4500
    },
    stadium: {
      id: "stadium",
      name: "Stadium Bloom",
      tag: "Arena Soundstage",
      desc: "Huge expansive stage ambiance with decoupled 45ms pre-delay that lets notes bloom without mud",
      preDelay: 45,
      erLevel: 0x4C00,
      diffusion: 0x6200,
      hfDamping: 0x3000
    }
  },

  // Wire Parameter Addresses
  ADDR: {
    // Amp & EQ
    AMP_MODEL: 0x00,
    GAIN: 0x01,
    MASTER: 0x02,
    BASS: 0x03,
    MIDDLE: 0x04,
    TREBLE: 0x05,
    CABINET: 0x06,

    // Compressor
    COMP_TYPE: 0x10, // 0: Stomp, 1: Rack
    COMP_SUSTAIN: 0x11, // Stomp Sustain (0-100) or Rack Threshold (14-bit)
    COMP_OUTPUT: 0x12, // Stomp Output (0-100)
    RACK_ATTACK: 0x13,
    RACK_RELEASE: 0x14,
    RACK_RATIO: 0x15, // 0..5
    RACK_KNEE: 0x16, // 0..2
    RACK_OUTPUT: 0x17, // 14-bit (0-600)
    COMP_BYPASS: 0x1F, // 0 = ON, 127 = OFF

    // Modulation
    MOD_TYPE: 0x20, // 0: Chorus, 1: Flanger, 2: Tremolo, 3: Phaser
    MOD_SPEED: 0x21,
    MOD_DEPTH: 0x22,
    MOD_MIX: 0x23,
    MOD_FEEDBACK: 0x24,
    MOD_SPREAD: 0x25,
    MOD_BYPASS: 0x2F, // 0 = ON, 127 = OFF

    // Delay
    DELAY_TIME: 0x31, // 14-bit (1-9999)
    DELAY_FEEDBACK: 0x33,
    DELAY_HIGHCUT: 0x34, // 14-bit (1000-16001)
    DELAY_LOWCUT: 0x36,  // 14-bit (21-8000)
    DELAY_LEVEL: 0x38,
    DELAY_BYPASS: 0x3F, // 0 = ON, 127 = OFF

    // Reverb
    REVERB_TYPE: 0x40, // 0: Hall, 1: Room, 2: Plate, 3: Spring
    REVERB_TIME: 0x41, // 14-bit (3-200) or Spring Amount (byte)
    REVERB_FILTER: 0x42, // Spring filter
    REVERB_PREDELAY: 0x43, // 14-bit (1-2000)
    REVERB_LOWCUT: 0x45, // 14-bit
    REVERB_HIGHCUT: 0x47, // 14-bit
    REVERB_HIGHRATIO: 0x49, // 1-10
    REVERB_LOWRATIO: 0x4A,  // 1-14
    REVERB_LEVEL: 0x4B,
    REVERB_BYPASS: 0x4F, // 0 = ON, 127 = OFF

    // Noise Gate
    GATE_TYPE: 0x50, // 0
    GATE_THRESHOLD: 0x51, // 0-100
    GATE_RELEASE: 0x52, // 0-100
    GATE_BYPASS: 0x5F  // 0 = ON, 127 = OFF
  },

  // 14-bit integer fields that send high and low bytes
  WIDE_FIELDS: new Set([0x17, 0x31, 0x34, 0x36, 0x41, 0x43, 0x45, 0x47]),

  /**
   * Calculate Yamaha 7-bit checksum:
   * sum of bytes, 2's complement modulo 128
   */
  checksum(bytes) {
    let sum = 0;
    for (let i = 0; i < bytes.length; i++) {
      sum += bytes[i];
    }
    return ((~sum) + 1) & 0x7F;
  },

  /**
   * Build a single parameter message:
   * F0 43 7D 10 41 30 01 <addr> <hi> <lo> F7
   */
  encodeParam(addr, val, isWide = false) {
    let hi = 0;
    let lo = 0;
    if (isWide || THR.WIDE_FIELDS.has(addr)) {
      hi = (val >> 7) & 0x7F;
      lo = val & 0x7F;
    } else {
      hi = 0;
      lo = Math.max(0, Math.min(127, val)) & 0x7F;
    }
    return new Uint8Array([
      0xF0, 0x43, 0x7D, 0x10, 0x41, 0x30, 0x01,
      addr & 0x7F, hi, lo,
      0xF7
    ]);
  },

  /**
   * Build a system command message:
   * F0 43 7D 30 41 30 <setting> <value> F7
   */
  encodeSystem(setting, val) {
    return new Uint8Array([
      0xF0, 0x43, 0x7D, 0x30, 0x41, 0x30,
      setting & 0x7F, val & 0x7F,
      0xF7
    ]);
  },

  /**
   * Build a settings block request:
   * F0 43 7D 20 44 54 41 31 41 6C 6C 50 F7
   */
  encodeSettingsRequest(modelByte = 0x31) {
    return new Uint8Array([
      0xF0, 0x43, 0x7D, 0x20,
      0x44, 0x54, 0x41, modelByte & 0x7F, // 'D','T','A', <model>
      0x41, 0x6C, 0x6C, 0x50, // 'A','l','l','P'
      0xF7
    ]);
  },

  /**
   * Build a preferences request (Wide Stereo & Tube Lamp state query):
   * F0 43 7D 20 44 54 41 31 50 52 45 46 F7 ('D','T','A','1','P','R','E','F')
   */
  encodePreferencesRequest(modelByte = 0x31) {
    return new Uint8Array([
      0xF0, 0x43, 0x7D, 0x20,
      0x44, 0x54, 0x41, modelByte & 0x7F,
      0x50, 0x52, 0x45, 0x46,
      0xF7
    ]);
  },

  /**
   * Build a Yamaha Modular DSP Protocol batch frame:
   * F0 43 10 47 <byte3> 07 <blockId> [addr_hi, addr_mid, addr_lo, val_hi, val_mid, val_lo]... F7
   * Allows writing 1 to 8 16-bit register parameters directly to hardware DSP coprocessor.
   */
  encodeModularDspBatch(blockId, params) {
    if (!params || params.length === 0) return null;
    const count = Math.min(params.length, 8);
    const byte3 = (((count - 1) & 0x1F) << 2) | 1;
    const byte4 = 0x07;
    const byte5 = blockId & 0x7F;
    const payload = [0xF0, 0x43, 0x10, 0x47, byte3, byte4, byte5];
    for (let i = 0; i < count; i++) {
      const p = params[i];
      const addr = p.addr ?? p[0];
      const val = p.val ?? p[1];
      payload.push(
        (addr >> 14) & 3,
        (addr >> 7) & 0x7F,
        addr & 0x7F,
        (val >> 14) & 3,
        (val >> 7) & 0x7F,
        val & 0x7F
      );
    }
    payload.push(0xF7);
    return new Uint8Array(payload);
  },

  /**
   * Decode an incoming SysEx message
   */
  decodeMessage(bytes) {
    if (!bytes || bytes.length < 5) return null;
    if (bytes[0] !== 0xF0 || bytes[bytes.length - 1] !== 0xF7) return null;

    // Check for Yamaha Modular DSP Protocol: F0 43 10 47 ...
    if (bytes[1] === 0x43 && bytes[2] === 0x10 && bytes[3] === 0x47) {
      if (bytes.length < 14) return null;
      const b3 = bytes[4];
      if ((b3 & 3) !== 1) return null;
      const count = ((b3 >> 2) & 0x1F) + 1;
      const blockId = bytes[6];
      const params = [];
      for (let i = 0; i < count; i++) {
        const idx = 4 + 3 + i * 6;
        if (idx + 5 >= bytes.length - 1) break;
        const addr = ((bytes[idx] & 3) << 14) | ((bytes[idx + 1] & 0x7F) << 7) | (bytes[idx + 2] & 0x7F);
        const val = ((bytes[idx + 3] & 3) << 14) | ((bytes[idx + 4] & 0x7F) << 7) | (bytes[idx + 5] & 0x7F);
        params.push({ addr, val });
      }
      return {
        type: "modular_dsp",
        blockId: blockId,
        count: count,
        params: params
      };
    }

    if (bytes[1] !== 0x43 || bytes[2] !== 0x7D) return null;

    const type = bytes[3];

    // Heartbeat: F0 43 7D 60 44 54 41 <model> F7
    if (type === THR.MSG_HEARTBEAT) {
      if (bytes[4] === 0x44 && bytes[5] === 0x54 && bytes[6] === 0x41) {
        return {
          type: "heartbeat",
          modelId: bytes[7],
          modelInfo: THR.MODELS[bytes[7]] || { name: "THR (Unknown)", desc: "Yamaha THR" }
        };
      }
    }

    // System setting broadcast: F0 43 7D 30 41 30 <setting> <value> F7
    if (type === THR.MSG_SYSTEM && bytes.length >= 9) {
      return {
        type: "system",
        setting: bytes[6],
        value: bytes[7]
      };
    }

    // Parameter broadcast: F0 43 7D 10 41 30 01 <addr> <hi> <lo> F7
    if (type === THR.MSG_PARAM && bytes.length >= 11) {
      const addr = bytes[7];
      const hi = bytes[8];
      const lo = bytes[9];
      const value = (hi << 7) | lo;
      return {
        type: "param",
        addr: addr,
        rawHi: hi,
        rawLo: lo,
        value: value
      };
    }

    // Settings block: 276 bytes on the wire
    if (type === THR.MSG_BLOCK && bytes.length === 276) {
      // Body is bytes[1:-1] (274 bytes)
      const body = bytes.slice(1, 275);
      // Checksum is verified over body[5:-1]
      const calcCsum = THR.checksum(body.slice(5, 273));
      const receivedCsum = body[273];
      const isValid = (calcCsum === receivedCsum);

      const ampModel = body[145];
      const cabinet = body[151];

      // Extract patch name (body[17..80])
      let nameBytes = [];
      for (let i = 17; i < 81; i++) {
        if (body[i] === 0) break;
        nameBytes.push(body[i]);
      }
      const patchName = String.fromCharCode(...nameBytes);

      return {
        type: "settings_block",
        valid: isValid,
        rawBytes: bytes,
        body: body,
        patchName: patchName,
        ampModel: ampModel,
        cabinet: cabinet,
        gain: body[146],
        master: body[147],
        bass: body[148],
        middle: body[149],
        treble: body[150],

        // Compressor
        compType: body[161],
        compSustain: body[162],
        compOutput: body[163],
        rackThreshold: (body[162] << 7) | body[163],
        rackAttack: body[164],
        rackRelease: body[165],
        rackRatio: body[166],
        rackKnee: body[167],
        rackOutput: (body[168] << 7) | body[169],
        compBypass: body[176],

        // Modulation
        modType: body[177],
        modSpeed: body[178],
        modDepth: body[179],
        modMix: body[180],
        modFeedback: body[181],
        modSpread: body[182],
        modBypass: body[192],

        // Delay
        delayTime: (body[194] << 7) | body[195],
        delayFeedback: body[196],
        delayHighCut: (body[197] << 7) | body[198],
        delayLowCut: (body[199] << 7) | body[200],
        delayLevel: body[201],
        delayBypass: body[208],

        // Reverb
        reverbType: body[209],
        reverbTime: (body[210] << 7) | body[211],
        springAmount: body[210],
        springFilter: body[211],
        reverbPreDelay: (body[212] << 7) | body[213],
        reverbLowCut: (body[214] << 7) | body[215],
        reverbHighCut: (body[216] << 7) | body[217],
        reverbHighRatio: body[218],
        reverbLowRatio: body[219],
        reverbLevel: body[220],
        reverbBypass: body[224],

        // Noise Gate
        gateThreshold: body[226],
        gateRelease: body[227],
        gateBypass: body[240]
      };
    }

    return { type: "unknown", raw: bytes };
  },

  /**
   * Create an initial blank settings block template with standard header & trailer
   */
  createBlankBlock() {
    const block = new Uint8Array(276);
    block[0] = 0xF0;
    // Header (17 bytes)
    const header = [0x43, 0x7D, 0x00, 0x02, 0x0C, 0x44, 0x54, 0x41, 0x31, 0x41, 0x6C, 0x6C, 0x50, 0x00, 0x00, 0x7F, 0x7F];
    for (let i = 0; i < header.length; i++) {
      block[1 + i] = header[i];
    }
    // Default effect bypass flags (all off by default)
    block[1 + 176] = 127; // Comp off
    block[1 + 192] = 127; // Mod off
    block[1 + 208] = 127; // Delay off
    block[1 + 224] = 127; // Reverb off
    block[1 + 240] = 127; // Gate off

    // Default tone values
    block[1 + 145] = 0;   // Clean
    block[1 + 146] = 50;  // Gain
    block[1 + 147] = 50;  // Master
    block[1 + 148] = 50;  // Bass
    block[1 + 149] = 50;  // Middle
    block[1 + 150] = 50;  // Treble
    block[1 + 151] = 4;   // 1x12 Cab

    // Trailing F7
    block[275] = 0xF7;
    return block;
  },

  /**
   * Prepare a modified settings block with an unlocked model index and updated checksum.
   * This is the "second door" that completely bypasses the hardware model clamp.
   */
  buildModelBlock(currentBlock, newModelIndex, newCabIndex = null) {
    let block;
    if (currentBlock && currentBlock.length === 276) {
      block = new Uint8Array(currentBlock);
    } else {
      block = THR.createBlankBlock();
    }

    // Set model index at body offset 145 (wire index 146)
    block[146] = newModelIndex & 0x7F;

    if (newCabIndex !== null) {
      block[152] = newCabIndex & 0x7F;
    }

    // Calculate checksum over body[5:-1] (which corresponds to wire indices 6 to 273)
    const bodySlice = block.subarray(6, 274);
    block[274] = THR.checksum(bodySlice);

    return block;
  }
};

// Curated Factory Presets (pure amp & tone stack voicings - leaves effects untouched)
const THR_PRESETS = [
  {
    name: "Studio Clean 1x12",
    category: "Clean",
    model: 0, // Clean (Fender Twin)
    cabinet: 4, // 1x12
    gain: 55,
    master: 65,
    bass: 50,
    middle: 55,
    treble: 60,
    tubeWarmth: 55
  },
  {
    name: "Texas Blues Grit",
    category: "Crunch",
    model: 1, // Crunch (Vox AC30)
    cabinet: 1, // US 2x12
    gain: 68,
    master: 55,
    bass: 55,
    middle: 62,
    treble: 58,
    tubeWarmth: 70
  },
  {
    name: "Sunset 80s Lead",
    category: "Lead",
    model: 2, // Lead (Marshall Plexi)
    cabinet: 2, // Brit 4x12
    gain: 80,
    master: 50,
    bass: 50,
    middle: 60,
    treble: 65,
    tubeWarmth: 85
  },
  {
    name: "British Roar 800",
    category: "Overdrive & High Gain",
    model: 3, // Brit Hi (Marshall JCM800)
    cabinet: 2, // Brit 4x12
    gain: 75,
    master: 50,
    bass: 58,
    middle: 65,
    treble: 55,
    tubeWarmth: 75
  },
  {
    name: "Dual Rectifier Chug",
    category: "Overdrive & High Gain",
    model: 4, // Modern (Mesa Rectifier)
    cabinet: 0, // US 4x12
    gain: 82,
    master: 45,
    bass: 65,
    middle: 42,
    treble: 62,
    tubeWarmth: 80
  },
  {
    name: "Motown Punch Bass",
    category: "Bass",
    model: 5, // Bass (Ampeg SVT)
    cabinet: 5, // 4x10
    gain: 45,
    master: 70,
    bass: 68,
    middle: 55,
    treble: 40,
    tubeWarmth: 60
  },
  {
    name: "Acoustic Air",
    category: "Acoustic & Studio",
    model: 6, // ACO (Acoustic Sim)
    cabinet: 6, // Direct / Bypass
    gain: 60,
    master: 65,
    bass: 52,
    middle: 48,
    treble: 65,
    tubeWarmth: 40
  },
  {
    name: "Flat Studio Monitor",
    category: "Acoustic & Studio",
    model: 7, // Flat Linear Response
    cabinet: 6, // Direct / Bypass
    gain: 50,
    master: 60,
    bass: 50,
    middle: 50,
    treble: 50,
    tubeWarmth: 50
  },
  {
    name: "Pure Studio DI",
    category: "Acoustic & Studio",
    model: 8, // Pure DI Bypass
    cabinet: 6, // Direct / Bypass
    gain: 50,
    master: 70,
    bass: 50,
    middle: 50,
    treble: 50,
    tubeWarmth: 50
  }
];

// Export for browser or node
if (typeof module !== "undefined" && module.exports) {
  module.exports = { THR, THR_PRESETS };
}
