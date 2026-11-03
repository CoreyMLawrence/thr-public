/**
 * Yamaha THR Web Studio - Application Controller
 * Manages Web MIDI I/O, state synchronization, interactive knobs, and preset management.
 */

// Application State
const state = {
  midiAccess: null,
  midiInput: null,
  midiOutput: null,
  connected: false,
  detectedModel: null,
  chassis: "THR5", // "THR5" or "THR5A"
  lastHeartbeatTime: 0,
  heartbeatInterval: null,
  
  // Current 276-byte settings block cached from amp
  currentBlock: null,

  // Live Parameters Mirror
  params: {
    ampModel: 0,
    gain: 50,
    master: 50,
    bass: 50,
    middle: 50,
    treble: 50,
    cabinet: 4,

    // Compressor
    compOn: false,
    compType: 0, // 0: Stomp, 1: Rack
    compSustain: 40,
    compOutput: 40,
    rackThreshold: 200,
    rackAttack: 65,
    rackRelease: 65,
    rackRatio: 0,
    rackKnee: 1,
    rackOutput: 200,

    // Noise Gate
    gateOn: true,
    gateThreshold: 50,
    gateRelease: 50,

    // Modulation
    modOn: false,
    modType: 0, // 0 Chorus, 1 Flanger, 2 Tremolo, 3 Phaser
    modSpeed: 30,
    modDepth: 40,
    modMix: 35,
    modManual: 22,
    modFeedback: 50,
    modSpread: 80,

    // Delay
    delayOn: false,
    delayTime: 350,
    delayFeedback: 30,
    delayHighCut: 8000,
    delayLowCut: 80,
    delayLevel: 30,

    // Reverb
    reverbOn: false,
    reverbType: 0, // 0 Hall, 1 Room, 2 Plate, 3 Spring
    reverbTime: 30,
    reverbPreDelay: 20,
    reverbLowCut: 95,
    reverbHighCut: 6500,
    reverbLevel: 35,
    springAmount: 40,
    springFilter: 50,

    // System & Performance
    wideStereo: true,
    tubeLamp: true,
    preserveEffects: true,
    voicing: 4,
    tubeWarmth: 60,
    roomPresence: "studio",
    autoBloom: false,
    morphFactor: 0
  },

  // Track physical knob positions sent by amp
  physicalKnobs: new Map()
};

// UI Elements & Controls Registry
const UI = {
  knobs: new Map(),
  toastTimeout: null
};

// -----------------------------------------------------------------------------
// Initialization & Startup
// -----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  initUI();
  initPresets();
  setupEventListeners();

  // Try auto-connecting to Web MIDI immediately
  initWebMIDI(false);
});

// -----------------------------------------------------------------------------
// Web MIDI API Connection & SysEx Transceiver
// -----------------------------------------------------------------------------
async function initWebMIDI(userTriggered = false) {
  const connText = document.getElementById("conn-text");
  const connPill = document.getElementById("conn-pill");
  const btnConnect = document.getElementById("btn-connect");

  if (!navigator.requestMIDIAccess) {
    connText.textContent = "Web MIDI Not Supported (Use Chrome/Edge)";
    connPill.classList.remove("connected");
    if (userTriggered) {
      showToast("Web MIDI is not supported on this browser. Please open in Google Chrome or Microsoft Edge.", true);
    }
    return;
  }

  try {
    connText.textContent = "Connecting to MIDI...";
    state.midiAccess = await navigator.requestMIDIAccess({ sysex: true });
    
    // Listen for device plug / unplug events
    state.midiAccess.onstatechange = (e) => {
      handleMIDIStateChange(e);
    };

    scanForAmp();
  } catch (err) {
    console.error("MIDI Access Error:", err);
    connText.textContent = "MIDI Permission Denied";
    connPill.classList.remove("connected");
    if (userTriggered) {
      showToast("SysEx MIDI permission is required to talk to the Yamaha THR amp.", true);
    }
  }
}

function scanForAmp() {
  const connText = document.getElementById("conn-text");
  const connPill = document.getElementById("conn-pill");
  const btnConnect = document.getElementById("btn-connect");

  let foundInput = null;
  let foundOutput = null;

  // Search inputs
  for (const [id, input] of state.midiAccess.inputs) {
    const name = input.name || "";
    if (name.includes("THR") || name.includes("Yamaha")) {
      foundInput = input;
      break;
    }
  }

  // Search outputs
  for (const [id, output] of state.midiAccess.outputs) {
    const name = output.name || "";
    if (name.includes("THR") || name.includes("Yamaha")) {
      foundOutput = output;
      break;
    }
  }

  if (foundInput && foundOutput) {
    attachAmpPorts(foundInput, foundOutput);
  } else {
    state.connected = false;
    connText.textContent = "THR Amp Not Detected - Connect USB";
    connPill.classList.remove("connected");
    btnConnect.textContent = "Scan Again";
    btnConnect.classList.remove("connected");
  }
}

function attachAmpPorts(input, output) {
  state.midiInput = input;
  state.midiOutput = output;
  state.connected = true;

  const connText = document.getElementById("conn-text");
  const connPill = document.getElementById("conn-pill");
  const btnConnect = document.getElementById("btn-connect");

  connText.textContent = `Connected: ${output.name}`;
  connPill.classList.add("connected");
  btnConnect.textContent = "Amp Connected";
  btnConnect.classList.add("connected");

  // Listen for incoming messages from the physical amp
  state.midiInput.onmidimessage = handleIncomingMIDIMessage;

  // Watch for heartbeats to confirm live communication
  if (state.heartbeatInterval) clearInterval(state.heartbeatInterval);
  state.heartbeatInterval = setInterval(() => {
    const now = Date.now();
    if (state.lastHeartbeatTime && now - state.lastHeartbeatTime > 3000) {
      connText.textContent = `${output.name} (Waiting for Heartbeat)`;
      connPill.classList.remove("connected");
    }
  }, 2000);

  // Request the full settings block from the amp to synchronize our UI
  sendSettingsRequest();
  setTimeout(() => sendPreferencesRequest(), 150);
  showToast(`Connected to ${output.name}! Ready to control.`, false);
}

function handleMIDIStateChange(e) {
  if (e.port && (e.port.name.includes("THR") || e.port.name.includes("Yamaha"))) {
    scanForAmp();
  }
}

// -----------------------------------------------------------------------------
// Incoming SysEx Parser & 2-Way Sync Engine
// -----------------------------------------------------------------------------
function handleIncomingMIDIMessage(event) {
  const bytes = event.data;
  const decoded = THR.decodeMessage(bytes);
  if (!decoded) return;

  if (decoded.type === "heartbeat") {
    state.lastHeartbeatTime = Date.now();
    const connPill = document.getElementById("conn-pill");
    const connText = document.getElementById("conn-text");
    connPill.classList.add("connected");

    if (state.detectedModel !== decoded.modelId) {
      state.detectedModel = decoded.modelId;
      connText.textContent = `Connected: ${decoded.modelInfo.name} (Direct Sync)`;
    }
  }

  // Live Settings Block received from Amp
  else if (decoded.type === "settings_block" && decoded.valid) {
    state.currentBlock = new Uint8Array(decoded.rawBytes);
    applySettingsBlockToUI(decoded);
  }

  // Single Parameter broadcast (from physical knob movements on the amp)
  else if (decoded.type === "param") {
    handlePhysicalKnobMovement(decoded.addr, decoded.value);
  }

  // System settings broadcast (Wide Stereo, Tube Lamp, Speaker Voicing)
  else if (decoded.type === "system") {
    if (decoded.setting === 0x00) {
      state.params.wideStereo = (decoded.value === 0); // 0 = enabled on amp
      const toggle = document.getElementById("toggle-wide-stereo");
      if (toggle) toggle.classList.toggle("active", state.params.wideStereo);
    } else if (decoded.setting === 0x01) {
      state.params.tubeLamp = (decoded.value === 0); // 0 = enabled on amp
      const toggle = document.getElementById("toggle-tube-lamp");
      if (toggle) toggle.classList.toggle("active", state.params.tubeLamp);
    } else if (decoded.setting === 0x02) {
      state.params.voicing = decoded.value;
      const select = document.getElementById("select-voicing");
      if (select) select.value = String(decoded.value);
    }
  }

  // Modular DSP Protocol message received
  else if (decoded.type === "modular_dsp") {
    const trafficLog = document.getElementById("dsp-traffic-log");
    if (trafficLog) {
      trafficLog.textContent = `[RX] Block ${decoded.blockId} (${decoded.count} parameters received)`;
    }
  }
}

function applySettingsBlockToUI(b) {
  // Preamp & Tone Stack
  state.params.ampModel = b.ampModel;
  state.params.cabinet = b.cabinet;
  state.params.gain = b.gain;
  state.params.master = b.master;
  state.params.bass = b.bass;
  state.params.middle = b.middle;
  state.params.treble = b.treble;

  // Compressor
  state.params.compType = b.compType;
  state.params.compSustain = b.compSustain;
  state.params.compOutput = b.compOutput;
  state.params.rackThreshold = b.rackThreshold;
  state.params.rackAttack = b.rackAttack;
  state.params.rackRelease = b.rackRelease;
  state.params.rackRatio = b.rackRatio;
  state.params.rackKnee = b.rackKnee;
  state.params.rackOutput = b.rackOutput;
  state.params.compOn = (b.compBypass === 0);

  // Modulation
  state.params.modType = b.modType;
  state.params.modSpeed = b.modSpeed;
  state.params.modDepth = b.modDepth;
  state.params.modMix = b.modMix;
  state.params.modFeedback = b.modFeedback;
  state.params.modSpread = b.modSpread;
  state.params.modOn = (b.modBypass === 0);

  // Delay
  state.params.delayTime = b.delayTime;
  state.params.delayFeedback = b.delayFeedback;
  state.params.delayHighCut = b.delayHighCut;
  state.params.delayLowCut = b.delayLowCut;
  state.params.delayLevel = b.delayLevel;
  state.params.delayOn = (b.delayBypass === 0);

  // Reverb
  state.params.reverbType = b.reverbType;
  state.params.reverbTime = b.reverbTime;
  state.params.springAmount = b.springAmount;
  state.params.springFilter = b.springFilter;
  state.params.reverbPreDelay = b.reverbPreDelay;
  state.params.reverbLowCut = b.reverbLowCut;
  state.params.reverbHighCut = b.reverbHighCut;
  state.params.reverbHighRatio = b.reverbHighRatio;
  state.params.reverbLowRatio = b.reverbLowRatio;
  state.params.reverbLevel = b.reverbLevel;
  state.params.reverbOn = (b.reverbBypass === 0);

  // Gate
  state.params.gateThreshold = b.gateThreshold;
  state.params.gateRelease = b.gateRelease;
  state.params.gateOn = (b.gateBypass === 0);

  // Update live patch name
  if (b.patchName && b.patchName.trim()) {
    updateLivePatchName(b.patchName.trim());
  } else {
    const modelObj = THR.ALL_MODELS.find(m => m.id === b.ampModel);
    updateLivePatchName(modelObj ? modelObj.name : `Model ${b.ampModel}`);
  }

  updateFullUI();
  showToast("Fully synchronized live tone from amp!", false);
}

function handlePhysicalKnobMovement(addr, value) {
  state.physicalKnobs.set(addr, value);

  switch (addr) {
    // Amp & Tone Stack
    case THR.ADDR.AMP_MODEL:
      state.params.ampModel = value;
      updateModelUI();
      break;
    case THR.ADDR.GAIN:
      state.params.gain = value;
      updateKnob(THR.ADDR.GAIN, value);
      break;
    case THR.ADDR.MASTER:
      state.params.master = value;
      updateKnob(THR.ADDR.MASTER, value);
      break;
    case THR.ADDR.BASS:
      state.params.bass = value;
      updateKnob(THR.ADDR.BASS, value);
      break;
    case THR.ADDR.MIDDLE:
      state.params.middle = value;
      updateKnob(THR.ADDR.MIDDLE, value);
      break;
    case THR.ADDR.TREBLE:
      state.params.treble = value;
      updateKnob(THR.ADDR.TREBLE, value);
      break;
    case THR.ADDR.CABINET:
      state.params.cabinet = value;
      updateCabUI();
      break;

    // Compressor
    case THR.ADDR.COMP_TYPE:
      state.params.compType = value;
      updateCompTypeUI();
      buildCompUI();
      break;
    case THR.ADDR.COMP_SUSTAIN:
      if (state.params.compType === 0) {
        state.params.compSustain = value;
        updateKnob(THR.ADDR.COMP_SUSTAIN, value);
      } else {
        state.params.rackThreshold = value;
        updateKnob(THR.ADDR.COMP_SUSTAIN, value);
      }
      break;
    case THR.ADDR.COMP_OUTPUT:
      state.params.compOutput = value;
      updateKnob(THR.ADDR.COMP_OUTPUT, value);
      break;
    case THR.ADDR.RACK_ATTACK:
      state.params.rackAttack = value;
      updateKnob(THR.ADDR.RACK_ATTACK, value);
      break;
    case THR.ADDR.RACK_RELEASE:
      state.params.rackRelease = value;
      updateKnob(THR.ADDR.RACK_RELEASE, value);
      break;
    case THR.ADDR.RACK_OUTPUT:
      state.params.rackOutput = value;
      updateKnob(THR.ADDR.RACK_OUTPUT, value);
      break;
    case THR.ADDR.COMP_BYPASS:
      state.params.compOn = (value === 0);
      updateCompBypassUI();
      break;

    // Modulation
    case THR.ADDR.MOD_TYPE:
      state.params.modType = value;
      updateModTypeUI();
      buildModUI();
      break;
    case THR.ADDR.MOD_SPEED:
      state.params.modSpeed = value;
      updateKnob(THR.ADDR.MOD_SPEED, value);
      break;
    case THR.ADDR.MOD_DEPTH:
      state.params.modDepth = value;
      updateKnob(THR.ADDR.MOD_DEPTH, value);
      break;
    case THR.ADDR.MOD_MIX:
      state.params.modMix = value;
      updateKnob(THR.ADDR.MOD_MIX, value);
      break;
    case THR.ADDR.MOD_FEEDBACK:
      state.params.modFeedback = value;
      updateKnob(THR.ADDR.MOD_FEEDBACK, value);
      break;
    case THR.ADDR.MOD_SPREAD:
      state.params.modSpread = value;
      updateKnob(THR.ADDR.MOD_SPREAD, value);
      break;
    case THR.ADDR.MOD_BYPASS:
      state.params.modOn = (value === 0);
      document.getElementById("btn-mod-power")?.classList.toggle("active", state.params.modOn);
      break;

    // Delay
    case THR.ADDR.DELAY_TIME:
      state.params.delayTime = value;
      updateKnob(THR.ADDR.DELAY_TIME, value);
      break;
    case THR.ADDR.DELAY_FEEDBACK:
      state.params.delayFeedback = value;
      updateKnob(THR.ADDR.DELAY_FEEDBACK, value);
      break;
    case THR.ADDR.DELAY_HIGHCUT:
      state.params.delayHighCut = value;
      updateKnob(THR.ADDR.DELAY_HIGHCUT, value);
      break;
    case THR.ADDR.DELAY_LOWCUT:
      state.params.delayLowCut = value;
      updateKnob(THR.ADDR.DELAY_LOWCUT, value);
      break;
    case THR.ADDR.DELAY_LEVEL:
      state.params.delayLevel = value;
      updateKnob(THR.ADDR.DELAY_LEVEL, value);
      break;
    case THR.ADDR.DELAY_BYPASS:
      state.params.delayOn = (value === 0);
      document.getElementById("btn-delay-power")?.classList.toggle("active", state.params.delayOn);
      break;

    // Reverb
    case THR.ADDR.REVERB_TYPE:
      state.params.reverbType = value;
      updateReverbTypeUI();
      buildReverbUI();
      break;
    case THR.ADDR.REVERB_TIME:
      if (state.params.reverbType === 3) {
        state.params.springAmount = value;
        updateKnob(THR.ADDR.REVERB_TIME, value);
      } else {
        state.params.reverbTime = value;
        updateKnob(THR.ADDR.REVERB_TIME, value);
      }
      break;
    case THR.ADDR.REVERB_FILTER:
      state.params.springFilter = value;
      updateKnob(THR.ADDR.REVERB_FILTER, value);
      break;
    case THR.ADDR.REVERB_PREDELAY:
      state.params.reverbPreDelay = value;
      updateKnob(THR.ADDR.REVERB_PREDELAY, value);
      break;
    case THR.ADDR.REVERB_LOWCUT:
      state.params.reverbLowCut = value;
      updateKnob(THR.ADDR.REVERB_LOWCUT, value);
      break;
    case THR.ADDR.REVERB_HIGHCUT:
      state.params.reverbHighCut = value;
      updateKnob(THR.ADDR.REVERB_HIGHCUT, value);
      break;
    case THR.ADDR.REVERB_LEVEL:
      state.params.reverbLevel = value;
      updateKnob(THR.ADDR.REVERB_LEVEL, value);
      break;
    case THR.ADDR.REVERB_BYPASS:
      state.params.reverbOn = (value === 0);
      document.getElementById("btn-reverb-power")?.classList.toggle("active", state.params.reverbOn);
      break;

    // Gate
    case THR.ADDR.GATE_THRESHOLD:
      state.params.gateThreshold = value;
      updateKnob(THR.ADDR.GATE_THRESHOLD, value);
      break;
    case THR.ADDR.GATE_RELEASE:
      state.params.gateRelease = value;
      updateKnob(THR.ADDR.GATE_RELEASE, value);
      break;
    case THR.ADDR.GATE_BYPASS:
      state.params.gateOn = (value === 0);
      updateGateBypassUI();
      break;
  }
}

// -----------------------------------------------------------------------------
// Outgoing MIDI Transmission
// -----------------------------------------------------------------------------
function sendSysEx(bytes) {
  if (!state.midiOutput || !state.connected) {
    console.warn("Cannot send SysEx: MIDI output not connected");
    return false;
  }
  try {
    state.midiOutput.send(bytes);
    return true;
  } catch (err) {
    console.error("Error sending SysEx:", err);
    return false;
  }
}

function sendParam(addr, val, isWide = false) {
  const msg = THR.encodeParam(addr, val, isWide);
  sendSysEx(msg);
}

function sendSystem(setting, val) {
  const msg = THR.encodeSystem(setting, val);
  sendSysEx(msg);
}

function sendSettingsRequest() {
  const msg = THR.encodeSettingsRequest(0x31);
  sendSysEx(msg);
}

function sendPreferencesRequest() {
  const msg = THR.encodePreferencesRequest(0x31);
  sendSysEx(msg);
}

/**
 * Send a Yamaha Modular DSP Protocol batch update:
 * Writes directly to the hardware DSP coprocessor registers.
 */
let lfoInterval = null;
let lfoPhase = 0;

function sendModularDspBatch(blockId, params) {
  const msg = THR.encodeModularDspBatch(blockId, params);
  if (!msg) return false;
  sendSysEx(msg);

  const trafficLog = document.getElementById("dsp-traffic-log");
  if (trafficLog) {
    const hexStr = Array.from(msg).map(b => b.toString(16).toUpperCase().padStart(2, "0")).join(" ");
    trafficLog.textContent = `[TX] ${hexStr} (${msg.length} bytes -> Block ${blockId})`;
  }
  return true;
}

function toggleLfoStream() {
  const btn = document.getElementById("btn-dsp-lfo-toggle");
  const status = document.getElementById("dsp-lfo-status");
  if (lfoInterval) {
    clearInterval(lfoInterval);
    lfoInterval = null;
    if (btn) btn.textContent = "▶ Start 60Hz Stream";
    if (status) {
      status.textContent = "Idle";
      status.style.color = "var(--text-muted)";
    }
    showToast("60Hz Continuous LFO Stream Stopped.", false);
  } else {
    if (!state.midiOutput) {
      showToast("Amp not connected! Connect via USB MIDI first.", true);
      return;
    }
    lfoPhase = 0;
    if (btn) btn.textContent = "⏹ Stop 60Hz Stream";
    if (status) {
      status.textContent = "Active (60 FPS)";
      status.style.color = "var(--led-green)";
    }
    showToast("Streaming 60Hz continuous register updates over Web MIDI...", false);
    lfoInterval = setInterval(() => {
      lfoPhase += 0.08;
      // Smooth sinusoidal sweep between 0x1000 and 0x7000
      const sweepVal = Math.round(0x4000 + Math.sin(lfoPhase) * 0x3000);
      sendModularDspBatch(1, [{ addr: 0x1C54, val: sweepVal }]);
    }, 16);
  }
}

/**
 * Unlocks or switches amp model on the fly.
 * Bypasses the hardware clamp by sending a 276-byte settings block with recomputed checksum.
 */
function setAmpModel(modelIndex) {
  state.params.ampModel = modelIndex;
  updateModelUI();

  // If acoustic or direct monitor model selected (ACO 6, Flat 7, Pure DI 8), auto-select Direct / Bypass cabinet
  if (modelIndex >= 6 && state.params.cabinet !== 6) {
    state.params.cabinet = 6; // Direct / Bypass
    updateCabUI();
  } else if (modelIndex < 6 && state.params.cabinet === 6) {
    state.params.cabinet = 4; // 1x12 default for electric
    updateCabUI();
  }

  // Build and send the unlocked settings block
  const block = THR.buildModelBlock(state.currentBlock, modelIndex, state.params.cabinet);

  // Preserve active effect pedals and dialed parameters in block
  if (state.params.preserveEffects) {
    block[177] = state.params.compOn ? 0 : 127;
    block[193] = state.params.modOn ? 0 : 127;
    block[209] = state.params.delayOn ? 0 : 127;
    block[225] = state.params.reverbOn ? 0 : 127;
    block[241] = state.params.gateOn ? 0 : 127;

    block[162] = state.params.compType & 0x7F;
    block[163] = state.params.compSustain & 0x7F;
    block[164] = state.params.compOutput & 0x7F;

    block[178] = state.params.modType & 0x7F;
    block[179] = state.params.modSpeed & 0x7F;
    block[180] = state.params.modDepth & 0x7F;
    block[181] = state.params.modMix & 0x7F;

    block[195] = (state.params.delayTime >> 7) & 0x7F;
    block[196] = state.params.delayTime & 0x7F;
    block[197] = state.params.delayFeedback & 0x7F;
    block[202] = state.params.delayLevel & 0x7F;

    block[210] = state.params.reverbType & 0x7F;
    block[211] = (state.params.reverbTime >> 7) & 0x7F;
    block[212] = state.params.reverbTime & 0x7F;
    block[213] = (state.params.reverbPreDelay >> 7) & 0x7F;
    block[214] = state.params.reverbPreDelay & 0x7F;
    block[221] = state.params.reverbLevel & 0x7F;

    block[227] = state.params.gateThreshold & 0x7F;
    block[228] = state.params.gateRelease & 0x7F;

    // Recalculate checksum over body[5:-1] (wire indices 6 to 273)
    block[274] = THR.checksum(block.subarray(6, 274));
  }

  state.currentBlock = block;
  sendSysEx(block);

  const modelObj = THR.ALL_MODELS.find(m => m.id === modelIndex);
  const modelName = modelObj ? modelObj.name : `Model ${modelIndex}`;
  updateLivePatchName(modelName);
  showToast(`Switched Amp Model to: ${modelName}`, false);
}

function updateLivePatchName(name) {
  const el = document.getElementById("live-patch-name");
  if (el && name) {
    el.textContent = name;
  }
}

function setCabinet(cabIndex) {
  state.params.cabinet = cabIndex;
  updateCabUI();
  sendParam(THR.ADDR.CABINET, cabIndex);

  const cabName = THR.CABINETS[cabIndex]?.name || `Cabinet ${cabIndex}`;
  showToast(`Selected Cabinet: ${cabName}`, false);
}

// -----------------------------------------------------------------------------
// Apple-Grade Musician Performance & Stage Tools
// -----------------------------------------------------------------------------
function initStagePresets() {
  const row = document.getElementById("stage-tiles-row");
  if (!row) return;
  row.innerHTML = "";

  const stageRigs = [
    { name: "Velvet Clean", icon: "🌟", presetIdx: 0 },
    { name: "Texas Blues", icon: "🎸", presetIdx: 1 },
    { name: "Sunset Lead", icon: "🔥", presetIdx: 2 },
    { name: "Modern Chug", icon: "⚡", presetIdx: 4 },
    { name: "Acoustic Air", icon: "🌿", presetIdx: 6 },
    { name: "Studio DI", icon: "🎛️", presetIdx: 8 }
  ];

  stageRigs.forEach((rig, idx) => {
    const btn = document.createElement("button");
    btn.className = `stage-tile ${idx === 0 ? "active" : ""}`;
    btn.innerHTML = `<span class="stage-tile-icon">${rig.icon}</span><span>${rig.name}</span>`;
    btn.onclick = () => {
      document.querySelectorAll(".stage-tile").forEach(t => t.classList.remove("active"));
      btn.classList.add("active");
      if (THR_PRESETS[rig.presetIdx]) {
        applyPreset(THR_PRESETS[rig.presetIdx]);
        showToast(`Loaded Stage Rig: ${rig.name}`, false);
      }
    };
    row.appendChild(btn);
  });
}

function initPerformanceControls() {
  // 1. Musical Solo Boost Toggle
  const btnSolo = document.getElementById("btn-solo-boost");
  if (btnSolo) {
    btnSolo.onclick = toggleSoloBoost;
  }

  // 2. Room Presence Inline Acoustic Space Pills (in Reverb Card)
  const pills = document.querySelectorAll(".presence-pill-inline");
  pills.forEach(pill => {
    pill.onclick = () => {
      const presenceId = pill.dataset.presence;
      applyRoomPresence(presenceId);
    };
  });
}

function toggleSoloBoost() {
  state.params.soloBoost = !state.params.soloBoost;
  const btn = document.getElementById("btn-solo-boost");
  if (btn) btn.classList.toggle("active", state.params.soloBoost);

  if (state.params.soloBoost) {
    state.params.soloBoostSaved = {
      gain: state.params.gain,
      middle: state.params.middle,
      treble: state.params.treble,
      delayLevel: state.params.delayLevel,
      delayOn: state.params.delayOn
    };

    const boostedGain = Math.min(100, state.params.gain + 12);
    const boostedMid = Math.min(100, state.params.middle + 15);
    const boostedTreble = Math.min(100, state.params.treble + 5);

    state.params.gain = boostedGain;
    state.params.middle = boostedMid;
    state.params.treble = boostedTreble;

    sendParam(THR.ADDR.GAIN, boostedGain);
    sendParam(THR.ADDR.MIDDLE, boostedMid);
    sendParam(THR.ADDR.TREBLE, boostedTreble);
    updateKnob(THR.ADDR.GAIN, boostedGain);
    updateKnob(THR.ADDR.MIDDLE, boostedMid);
    updateKnob(THR.ADDR.TREBLE, boostedTreble);

    // Subtle lead delay bloom if off
    if (!state.params.delayOn) {
      state.params.delayOn = true;
      document.getElementById("btn-delay-power")?.classList.add("active");
      sendParam(THR.ADDR.DELAY_BYPASS, 0);
      if (state.params.delayLevel < 20) {
        state.params.delayLevel = 26;
        sendParam(THR.ADDR.DELAY_LEVEL, 26);
        updateKnob(THR.ADDR.DELAY_LEVEL, 26);
      }
    }

    showToast("🔥 Solo Boost Engaged: +4 dB Singing Mid Lift & Lead Presence", false);
  } else {
    if (state.params.soloBoostSaved) {
      const s = state.params.soloBoostSaved;
      state.params.gain = s.gain;
      state.params.middle = s.middle;
      state.params.treble = s.treble;
      state.params.delayLevel = s.delayLevel;
      state.params.delayOn = s.delayOn;

      sendParam(THR.ADDR.GAIN, s.gain);
      sendParam(THR.ADDR.MIDDLE, s.middle);
      sendParam(THR.ADDR.TREBLE, s.treble);
      sendParam(THR.ADDR.DELAY_LEVEL, s.delayLevel);
      sendParam(THR.ADDR.DELAY_BYPASS, s.delayOn ? 0 : 127);

      updateKnob(THR.ADDR.GAIN, s.gain);
      updateKnob(THR.ADDR.MIDDLE, s.middle);
      updateKnob(THR.ADDR.TREBLE, s.treble);
      updateKnob(THR.ADDR.DELAY_LEVEL, s.delayLevel);
      document.getElementById("btn-delay-power")?.classList.toggle("active", s.delayOn);
    }
    showToast("Solo Boost Off: Restored dialed-in rhythm tone", false);
  }
}

function applyRoomPresence(presenceId) {
  state.params.roomPresence = presenceId;

  // Update UI Pills in Reverb Card
  document.querySelectorAll(".presence-pill-inline").forEach(p => {
    p.classList.toggle("active", p.dataset.presence === presenceId);
  });

  const profile = THR.ROOM_PRESENCE_PROFILES[presenceId];
  if (!profile) return;

  // Send atomic batch write directly to DSP Block 6 (SREV2 Reverb) once (no timer flooding)
  sendModularDspBatch(6, [
    { addr: 0x2055DE4, val: profile.erLevel },
    { addr: 0x2055E00, val: profile.preDelay }
  ]);

  // Ensure reverb is active
  if (!state.params.reverbOn) {
    state.params.reverbOn = true;
    document.getElementById("btn-reverb-power")?.classList.add("active");
    sendParam(THR.ADDR.REVERB_BYPASS, 0);
  }

  // Sync state reverb pre-delay and update knob
  state.params.reverbPreDelay = profile.preDelay;
  sendParam(THR.ADDR.REVERB_PREDELAY, profile.preDelay, true);
  updateKnob(THR.ADDR.REVERB_PREDELAY, profile.preDelay);

  showToast(`Acoustic Space: ${profile.name} (${profile.desc})`, false);
}

function initUI() {
  initPerformanceControls();
  initStagePresets();
  buildModelSelectorUI();
  buildCabinetUI();
  buildPreampKnobs();
  buildRackProcessors();
}

function buildModelSelectorUI() {
  const grid = document.getElementById("model-button-grid");
  if (!grid) return;
  grid.innerHTML = "";

  const allModels = THR.ALL_MODELS;
  const filtered = allModels.filter(m => {
    if (state.params.modelFilter === "electric") return m.category === "electric";
    if (state.params.modelFilter === "acoustic") return m.category === "acoustic";
    return true;
  });

  filtered.forEach(m => {
    const btn = document.createElement("button");
    btn.className = `model-btn ${state.params.ampModel === m.id ? "active" : ""}`;
    btn.dataset.modelId = m.id;
    btn.onclick = () => setAmpModel(m.id);

    btn.innerHTML = `
      <span class="model-btn-badge ${m.category === "acoustic" ? "unlocked" : ""}">${m.badge || "MODEL"}</span>
      <div class="model-btn-name">${m.icon} ${m.name}</div>
      <div class="model-btn-desc">${m.tag}</div>
    `;
    grid.appendChild(btn);
  });

  drawModelDial();
}

function drawModelDial() {
  const models = THR.ALL_MODELS;
  const svg = document.getElementById("model-dial-svg");
  const cx = 140, cy = 95;
  const numModels = models.length;

  // Compute angles for models across an arc of -135deg to +135deg
  const startAngle = -130;
  const endAngle = 130;
  const step = (endAngle - startAngle) / (numModels - 1);

  let html = "";

  // Draw background ring and tick marks
  models.forEach((m, i) => {
    const angle = startAngle + i * step;
    const rad = (angle * Math.PI) / 180;
    
    // Ticks
    const x1 = cx + 50 * Math.sin(rad);
    const y1 = cy - 50 * Math.cos(rad);
    const x2 = cx + 60 * Math.sin(rad);
    const y2 = cy - 60 * Math.cos(rad);

    // Label coordinates
    const lx = cx + 76 * Math.sin(rad);
    const ly = cy - 76 * Math.cos(rad);

    const isActive = (state.params.ampModel === m.id);
    const tickClass = `dial-tick ${isActive ? "active" : ""} ${m.unlocked ? "unlocked-tick" : ""}`;
    const lblClass = `dial-lbl ${isActive ? "active" : ""} ${m.unlocked ? "unlocked-lbl" : ""}`;

    html += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" class="${tickClass}"/>`;
    
    // Label anchor adjustment
    let anchor = "middle";
    if (Math.sin(rad) < -0.2) anchor = "end";
    else if (Math.sin(rad) > 0.2) anchor = "start";

    html += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" class="${lblClass}" text-anchor="${anchor}" dominant-baseline="middle" onclick="setAmpModel(${m.id})">${m.name}</text>`;
  });

  // Calculate current pointer angle
  const currentIndex = models.findIndex(m => m.id === state.params.ampModel);
  const currentAngle = currentIndex >= 0 ? (startAngle + currentIndex * step) : 0;
  const curRad = (currentAngle * Math.PI) / 180;

  // Knob Body (Vintage hardware look with knurling and pointer)
  html += `
    <g class="dial-knob-group">
      <circle cx="${cx}" cy="${cy}" r="40" class="dial-knob-circle"/>
  `;

  for (let k = 0; k < 36; k++) {
    const knurlAngle = (k * 10 * Math.PI) / 180;
    const kx1 = cx + 36 * Math.sin(knurlAngle);
    const ky1 = cy - 36 * Math.cos(knurlAngle);
    const kx2 = cx + 40 * Math.sin(knurlAngle);
    const ky2 = cy - 40 * Math.cos(knurlAngle);
    html += `<line x1="${kx1.toFixed(1)}" y1="${ky1.toFixed(1)}" x2="${kx2.toFixed(1)}" y2="${ky2.toFixed(1)}" class="dial-knurl"/>`;
  }

  html += `
      <circle cx="${cx}" cy="${cy}" r="30" class="dial-face"/>
      <!-- Pointer -->
      <line x1="${(cx + 8 * Math.sin(curRad)).toFixed(1)}" y1="${(cy - 8 * Math.cos(curRad)).toFixed(1)}" 
            x2="${(cx + 28 * Math.sin(curRad)).toFixed(1)}" y2="${(cy - 28 * Math.cos(curRad)).toFixed(1)}" 
            class="dial-pointer-line"/>
      <circle cx="${(cx + 32 * Math.sin(curRad)).toFixed(1)}" cy="${(cy - 32 * Math.cos(curRad)).toFixed(1)}" r="2.8" class="dial-pointer-dot"/>
    </g>
  `;

  svg.innerHTML = html;
}

function updateModelUI() {
  drawModelDial();
  const buttons = document.querySelectorAll(".model-btn");
  buttons.forEach(btn => {
    btn.classList.toggle("active", parseInt(btn.dataset.modelId) === state.params.ampModel);
  });
}

function buildCabinetUI() {
  const grid = document.getElementById("cab-grid");
  grid.innerHTML = "";

  THR.CABINETS.forEach(cab => {
    const card = document.createElement("div");
    card.className = `cab-card ${state.params.cabinet === cab.id ? "active" : ""}`;
    card.dataset.cabId = cab.id;
    card.title = cab.desc;
    card.onclick = () => setCabinet(cab.id);

    card.innerHTML = `
      <div class="cab-icon">${getCabSvgIcon(cab.id)}</div>
      <div class="cab-name">${cab.name}</div>
    `;
    grid.appendChild(card);
  });
}

function updateCabUI() {
  const cards = document.querySelectorAll(".cab-card");
  cards.forEach(card => {
    card.classList.toggle("active", parseInt(card.dataset.cabId) === state.params.cabinet);
  });
}

function getCabSvgIcon(index) {
  const spk = (x, y, r) => `<circle cx="${x}" cy="${y}" r="${r}" fill="#2a2e3b" stroke="#3e4454" stroke-width="1"/><circle cx="${x}" cy="${y}" r="${(r * 0.4).toFixed(1)}" fill="#f3a93c"/>`;
  const box = (x, y, w, h, rx = 2) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="#161820" stroke="#444a5d" stroke-width="1.5"/>`;

  switch (index) {
    case 0: // US 4x12
      return `<svg viewBox="0 0 44 36">${box(3, 2, 38, 32)}${spk(13, 10, 5.5)}${spk(31, 10, 5.5)}${spk(13, 24, 5.5)}${spk(31, 24, 5.5)}</svg>`;
    case 1: // US 2x12
      return `<svg viewBox="0 0 44 36">${box(2, 8, 40, 20)}${spk(13, 18, 6.5)}${spk(31, 18, 6.5)}</svg>`;
    case 2: // Brit 4x12
      return `<svg viewBox="0 0 44 36"><path d="M4 34 V9 L10 3 H34 L40 9 V34 Z" fill="#161820" stroke="#f3a93c" stroke-width="1.5"/>${spk(14, 12, 5)}${spk(30, 12, 5)}${spk(14, 25, 5.5)}${spk(30, 25, 5.5)}</svg>`;
    case 3: // Brit 2x12
      return `<svg viewBox="0 0 44 36">${box(2, 8, 40, 20)}<rect x="4" y="10" width="36" height="16" fill="none" stroke="#f3a93c" stroke-width="0.8"/>${spk(13, 18, 6)}${spk(31, 18, 6)}</svg>`;
    case 4: // 1x12
      return `<svg viewBox="0 0 44 36">${box(8, 4, 28, 28)}${spk(22, 18, 9)}</svg>`;
    case 5: // 4x10
      return `<svg viewBox="0 0 44 36">${box(7, 1, 30, 34)}${spk(16, 9, 4.5)}${spk(28, 9, 4.5)}${spk(16, 24, 4.5)}${spk(28, 24, 4.5)}</svg>`;
    default: // None / Bypass
      return `<svg viewBox="0 0 44 36">${box(8, 5, 28, 26)}<line x1="12" y1="27" x2="32" y2="9" stroke="#ff4b4b" stroke-width="2.2" stroke-linecap="round"/></svg>`;
  }
}

// -----------------------------------------------------------------------------
// Interactive SVG Rotary Knob Component
// -----------------------------------------------------------------------------
function createKnob({ addr, label, min = 0, max = 100, step = 1, value = 50, onChange, isWide = false }) {
  const container = document.createElement("div");
  container.className = "knob-control";

  const wrap = document.createElement("div");
  wrap.className = "knob-svg-wrap";
  wrap.tabIndex = 0;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 60 60");
  svg.setAttribute("class", "knob-svg");

  const cx = 30, cy = 30, r = 21;
  const startAngle = -135;
  const endAngle = 135;
  const totalAngle = endAngle - startAngle;

  // Arc path generator
  function describeArc(x, y, radius, startDeg, endDeg) {
    const startRad = ((startDeg - 90) * Math.PI) / 180;
    const endRad = ((endDeg - 90) * Math.PI) / 180;
    const x1 = x + radius * Math.cos(startRad);
    const y1 = y + radius * Math.sin(startRad);
    const x2 = x + radius * Math.cos(endRad);
    const y2 = y + radius * Math.sin(endRad);
    const largeArcFlag = endDeg - startDeg <= 180 ? "0" : "1";
    return `M ${x1} ${y1} A ${radius} ${radius} 0 ${largeArcFlag} 1 ${x2} ${y2}`;
  }

  // Static Background Track
  const bgPath = describeArc(cx, cy, r, startAngle, endAngle);
  svg.innerHTML = `
    <circle cx="${cx}" cy="${cy}" r="17" class="knob-bg-circle"/>
    <path d="${bgPath}" class="knob-track-arc"/>
    <path class="knob-value-arc" id="knob-arc-${addr}"/>
    <line class="knob-pointer" id="knob-ptr-${addr}"/>
    <line class="knob-ghost-pointer" id="knob-ghost-${addr}" style="display: none;"/>
  `;

  const lbl = document.createElement("div");
  lbl.className = "knob-label";
  lbl.textContent = label;

  const readout = document.createElement("div");
  readout.className = "knob-readout";
  readout.id = `knob-val-${addr}`;
  readout.textContent = value;

  wrap.appendChild(svg);
  container.appendChild(wrap);
  container.appendChild(lbl);
  container.appendChild(readout);

  let curVal = value;

  function render(v) {
    curVal = Math.max(min, Math.min(max, v));
    const pct = (curVal - min) / (max - min);
    const deg = startAngle + pct * totalAngle;

    // Value Arc
    const valArc = svg.querySelector(`#knob-arc-${addr}`);
    if (valArc) {
      if (pct > 0.001) {
        valArc.setAttribute("d", describeArc(cx, cy, r, startAngle, deg));
      } else {
        valArc.setAttribute("d", "");
      }
    }

    // Pointer line
    const ptr = svg.querySelector(`#knob-ptr-${addr}`);
    if (ptr) {
      const rad = (deg * Math.PI) / 180;
      ptr.setAttribute("x1", (cx + 5 * Math.sin(rad)).toFixed(1));
      ptr.setAttribute("y1", (cy - 5 * Math.cos(rad)).toFixed(1));
      ptr.setAttribute("x2", (cx + 14 * Math.sin(rad)).toFixed(1));
      ptr.setAttribute("y2", (cy - 14 * Math.cos(rad)).toFixed(1));
    }

    // Ghost indicator (shows physical hardware position if different)
    const ghost = svg.querySelector(`#knob-ghost-${addr}`);
    if (ghost) {
      const physVal = state.physicalKnobs.get(addr);
      if (physVal !== undefined && Math.abs(physVal - curVal) > 2) {
        const physPct = (physVal - min) / (max - min);
        const physDeg = startAngle + physPct * totalAngle;
        const pRad = (physDeg * Math.PI) / 180;
        ghost.setAttribute("x1", (cx + 6 * Math.sin(pRad)).toFixed(1));
        ghost.setAttribute("y1", (cy - 6 * Math.cos(pRad)).toFixed(1));
        ghost.setAttribute("x2", (cx + 16 * Math.sin(pRad)).toFixed(1));
        ghost.setAttribute("y2", (cy - 16 * Math.cos(pRad)).toFixed(1));
        ghost.style.display = "block";
      } else {
        ghost.style.display = "none";
      }
    }

    readout.textContent = Math.round(curVal);
  }

  // Pointer Drag Interaction
  let dragging = false;
  let startY = 0;
  let startVal = 0;

  wrap.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    wrap.setPointerCapture(e.pointerId);
    dragging = true;
    startY = e.clientY;
    startVal = curVal;
  });

  wrap.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dy = startY - e.clientY;
    const range = max - min;
    const sensitivity = e.shiftKey ? 1000 : 200; // Shift for fine adjustment
    const delta = (dy / sensitivity) * range;
    const newVal = Math.max(min, Math.min(max, Math.round(startVal + delta)));
    if (newVal !== curVal) {
      render(newVal);
      if (onChange) onChange(newVal);
    }
  });

  const stopDrag = () => { dragging = false; };
  wrap.addEventListener("pointerup", stopDrag);
  wrap.addEventListener("pointercancel", stopDrag);

  // Wheel interaction
  wrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    const d = e.deltaY < 0 ? step : -step;
    const newVal = Math.max(min, Math.min(max, curVal + d));
    if (newVal !== curVal) {
      render(newVal);
      if (onChange) onChange(newVal);
    }
  }, { passive: false });

  // Double click reset to center
  wrap.addEventListener("dblclick", () => {
    const center = Math.round((min + max) / 2);
    render(center);
    if (onChange) onChange(center);
  });

  render(value);

  const knobObj = {
    addr,
    container,
    setValue: (v) => render(v),
    getValue: () => curVal
  };

  UI.knobs.set(addr, knobObj);
  return container;
}

function updateKnob(addr, val) {
  const k = UI.knobs.get(addr);
  if (k) k.setValue(val);
}

// -----------------------------------------------------------------------------
// Preamp & Independent 3-Band Tone Stack Builder
// -----------------------------------------------------------------------------
function buildPreampKnobs() {
  const row = document.getElementById("preamp-knobs");
  row.innerHTML = "";

  const controls = [
    { addr: THR.ADDR.GAIN, label: "Gain", value: state.params.gain, onChange: (v) => { state.params.gain = v; sendParam(THR.ADDR.GAIN, v); } },
    { addr: THR.ADDR.MASTER, label: "Master", value: state.params.master, onChange: (v) => { state.params.master = v; sendParam(THR.ADDR.MASTER, v); } },
    { addr: THR.ADDR.BASS, label: "Bass", value: state.params.bass, onChange: (v) => { state.params.bass = v; sendParam(THR.ADDR.BASS, v); } },
    { addr: THR.ADDR.MIDDLE, label: "Middle", value: state.params.middle, onChange: (v) => { state.params.middle = v; sendParam(THR.ADDR.MIDDLE, v); } },
    { addr: THR.ADDR.TREBLE, label: "Treble", value: state.params.treble, onChange: (v) => { state.params.treble = v; sendParam(THR.ADDR.TREBLE, v); } },
    {
      addr: "tubeWarmth",
      label: "Tube Sag",
      value: state.params.tubeWarmth ?? 60,
      onChange: (v) => {
        state.params.tubeWarmth = v;
        const voicingCurve = Math.min(4, Math.floor(v / 25));
        sendSystem(0x02, voicingCurve);
        const sagVal = Math.round(0x2000 + (v / 100) * 0x4000);
        sendModularDspBatch(1, [{ addr: 0x1C54, val: sagVal }]);
      }
    }
  ];

  controls.forEach(c => row.appendChild(createKnob(c)));
}

// -----------------------------------------------------------------------------
// Rack Processors Builder (Compressor, Noise Gate, Mod, Delay, Reverb)
// -----------------------------------------------------------------------------
function buildRackProcessors() {
  buildCompUI();
  buildGateUI();
  buildModUI();
  buildDelayUI();
  buildReverbUI();
}

function buildCompUI() {
  const row = document.getElementById("comp-knobs");
  row.innerHTML = "";

  if (state.params.compType === 0) {
    // Stomp Mode
    row.appendChild(createKnob({
      addr: THR.ADDR.COMP_SUSTAIN,
      label: "Sustain",
      value: state.params.compSustain,
      onChange: (v) => { state.params.compSustain = v; sendParam(THR.ADDR.COMP_SUSTAIN, v); }
    }));
    row.appendChild(createKnob({
      addr: THR.ADDR.COMP_OUTPUT,
      label: "Output",
      value: state.params.compOutput,
      onChange: (v) => { state.params.compOutput = v; sendParam(THR.ADDR.COMP_OUTPUT, v); }
    }));
  } else {
    // Studio Rack Mode
    row.appendChild(createKnob({
      addr: THR.ADDR.COMP_SUSTAIN,
      label: "Threshold",
      min: 0, max: 600,
      value: state.params.rackThreshold,
      isWide: true,
      onChange: (v) => { state.params.rackThreshold = v; sendParam(THR.ADDR.COMP_SUSTAIN, v, true); }
    }));
    row.appendChild(createKnob({
      addr: THR.ADDR.RACK_ATTACK,
      label: "Attack",
      value: state.params.rackAttack,
      onChange: (v) => { state.params.rackAttack = v; sendParam(THR.ADDR.RACK_ATTACK, v); }
    }));
    row.appendChild(createKnob({
      addr: THR.ADDR.RACK_RELEASE,
      label: "Release",
      value: state.params.rackRelease,
      onChange: (v) => { state.params.rackRelease = v; sendParam(THR.ADDR.RACK_RELEASE, v); }
    }));
    row.appendChild(createKnob({
      addr: THR.ADDR.RACK_OUTPUT,
      label: "Rack Out",
      min: 0, max: 600,
      value: state.params.rackOutput,
      isWide: true,
      onChange: (v) => { state.params.rackOutput = v; sendParam(THR.ADDR.RACK_OUTPUT, v, true); }
    }));
  }
}

function buildGateUI() {
  const row = document.getElementById("gate-knobs");
  row.innerHTML = "";

  row.appendChild(createKnob({
    addr: THR.ADDR.GATE_THRESHOLD,
    label: "Threshold",
    value: state.params.gateThreshold,
    onChange: (v) => { state.params.gateThreshold = v; sendParam(THR.ADDR.GATE_THRESHOLD, v); }
  }));
  row.appendChild(createKnob({
    addr: THR.ADDR.GATE_RELEASE,
    label: "Release",
    value: state.params.gateRelease,
    onChange: (v) => { state.params.gateRelease = v; sendParam(THR.ADDR.GATE_RELEASE, v); }
  }));
}

function buildModUI() {
  const row = document.getElementById("mod-knobs");
  row.innerHTML = "";

  row.appendChild(createKnob({
    addr: THR.ADDR.MOD_SPEED,
    label: "Speed",
    value: state.params.modSpeed,
    onChange: (v) => { state.params.modSpeed = v; sendParam(THR.ADDR.MOD_SPEED, v); }
  }));
  row.appendChild(createKnob({
    addr: THR.ADDR.MOD_DEPTH,
    label: "Depth",
    value: state.params.modDepth,
    onChange: (v) => { state.params.modDepth = v; sendParam(THR.ADDR.MOD_DEPTH, v); }
  }));
  row.appendChild(createKnob({
    addr: THR.ADDR.MOD_MIX,
    label: "Mix",
    value: state.params.modMix,
    onChange: (v) => { state.params.modMix = v; sendParam(THR.ADDR.MOD_MIX, v); }
  }));
}

function buildDelayUI() {
  const row = document.getElementById("delay-knobs");
  row.innerHTML = "";

  row.appendChild(createKnob({
    addr: THR.ADDR.DELAY_TIME,
    label: "Time (ms)",
    min: 1, max: 9999, step: 10,
    value: state.params.delayTime,
    isWide: true,
    onChange: (v) => { state.params.delayTime = v; sendParam(THR.ADDR.DELAY_TIME, v, true); }
  }));
  row.appendChild(createKnob({
    addr: THR.ADDR.DELAY_FEEDBACK,
    label: "Feedback",
    value: state.params.delayFeedback,
    onChange: (v) => { state.params.delayFeedback = v; sendParam(THR.ADDR.DELAY_FEEDBACK, v); }
  }));
  row.appendChild(createKnob({
    addr: THR.ADDR.DELAY_LEVEL,
    label: "Level",
    value: state.params.delayLevel,
    onChange: (v) => { state.params.delayLevel = v; sendParam(THR.ADDR.DELAY_LEVEL, v); }
  }));
}

function buildReverbUI() {
  const row = document.getElementById("reverb-knobs");
  row.innerHTML = "";

  if (state.params.reverbType === 3) {
    // Spring Mode
    row.appendChild(createKnob({
      addr: THR.ADDR.REVERB_TIME,
      label: "Amount",
      value: state.params.springAmount,
      onChange: (v) => { state.params.springAmount = v; sendParam(THR.ADDR.REVERB_TIME, v); }
    }));
    row.appendChild(createKnob({
      addr: THR.ADDR.REVERB_FILTER,
      label: "Filter",
      value: state.params.springFilter,
      onChange: (v) => { state.params.springFilter = v; sendParam(THR.ADDR.REVERB_FILTER, v); }
    }));
  } else {
    // Hall, Room, Plate Modes
    row.appendChild(createKnob({
      addr: THR.ADDR.REVERB_TIME,
      label: "Time",
      min: 3, max: 200,
      value: state.params.reverbTime,
      isWide: true,
      onChange: (v) => { state.params.reverbTime = v; sendParam(THR.ADDR.REVERB_TIME, v, true); }
    }));
    row.appendChild(createKnob({
      addr: THR.ADDR.REVERB_PREDELAY,
      label: "Pre-Delay",
      min: 1, max: 2000, step: 5,
      value: state.params.reverbPreDelay,
      isWide: true,
      onChange: (v) => { state.params.reverbPreDelay = v; sendParam(THR.ADDR.REVERB_PREDELAY, v, true); }
    }));
    row.appendChild(createKnob({
      addr: THR.ADDR.REVERB_LEVEL,
      label: "Level",
      value: state.params.reverbLevel,
      onChange: (v) => { state.params.reverbLevel = v; sendParam(THR.ADDR.REVERB_LEVEL, v); }
    }));
  }
}

// Bypass and Power State Updaters
function updateCompBypassUI() {
  document.getElementById("btn-comp-power").classList.toggle("active", state.params.compOn);
}

function updateGateBypassUI() {
  document.getElementById("btn-gate-power").classList.toggle("active", state.params.gateOn);
}

function updateFullUI() {
  updateModelUI();
  updateCabUI();

  // Update knobs
  updateKnob(THR.ADDR.GAIN, state.params.gain);
  updateKnob(THR.ADDR.MASTER, state.params.master);
  updateKnob(THR.ADDR.BASS, state.params.bass);
  updateKnob(THR.ADDR.MIDDLE, state.params.middle);
  updateKnob(THR.ADDR.TREBLE, state.params.treble);
  updateKnob("tubeWarmth", state.params.tubeWarmth ?? 60);

  // Update Processors
  updateCompBypassUI();
  updateGateBypassUI();
  document.getElementById("btn-mod-power").classList.toggle("active", state.params.modOn);
  document.getElementById("btn-delay-power").classList.toggle("active", state.params.delayOn);
  document.getElementById("btn-reverb-power").classList.toggle("active", state.params.reverbOn);

  buildCompUI();
  buildModUI();
  buildDelayUI();
  buildReverbUI();
}

// -----------------------------------------------------------------------------
// Presets Manager
// -----------------------------------------------------------------------------
function initPresets() {
  const dropdown = document.getElementById("preset-dropdown");
  dropdown.innerHTML = `<option value="" disabled selected>Select a Curated Tone...</option>`;

  // Load Built-in Presets
  THR_PRESETS.forEach((p, idx) => {
    const opt = document.createElement("option");
    opt.value = `factory_${idx}`;
    opt.textContent = `${p.name} [${p.category}]`;
    dropdown.appendChild(opt);
  });

  // Load User Saved Presets from localStorage
  const userPresets = getUserPresets();
  if (userPresets.length > 0) {
    const group = document.createElement("optgroup");
    group.label = "User Presets";
    userPresets.forEach((p, idx) => {
      const opt = document.createElement("option");
      opt.value = `user_${idx}`;
      opt.textContent = p.name;
      group.appendChild(opt);
    });
    dropdown.appendChild(group);
  }

  dropdown.onchange = () => {
    const val = dropdown.value;
    if (val.startsWith("factory_")) {
      const idx = parseInt(val.split("_")[1]);
      applyPreset(THR_PRESETS[idx]);
    } else if (val.startsWith("user_")) {
      const idx = parseInt(val.split("_")[1]);
      applyPreset(userPresets[idx]);
    }
  };
}

function getUserPresets() {
  try {
    return JSON.parse(localStorage.getItem("thr_user_presets") || "[]");
  } catch (e) {
    return [];
  }
}

function saveUserPreset(preset) {
  const list = getUserPresets();
  list.push(preset);
  localStorage.setItem("thr_user_presets", JSON.stringify(list));
  initPresets();
  showToast(`Saved preset "${preset.name}"!`, false);
}

function applyPreset(p) {
  state.params.gain = p.gain ?? 50;
  state.params.master = p.master ?? 50;
  state.params.bass = p.bass ?? 50;
  state.params.middle = p.middle ?? 50;
  state.params.treble = p.treble ?? 50;
  state.params.cabinet = p.cabinet ?? (p.model >= 6 ? 6 : 4);
  if (p.tubeWarmth !== undefined) {
    state.params.tubeWarmth = p.tubeWarmth;
  }

  // Only apply effects if preserveEffects is turned off
  if (!state.params.preserveEffects) {
    if (p.comp) {
      state.params.compOn = p.comp.on;
      state.params.compType = p.comp.type ?? 0;
      state.params.compSustain = p.comp.sustain ?? 40;
      state.params.compOutput = p.comp.output ?? 40;
    }
    if (p.gate) {
      state.params.gateOn = p.gate.on;
      state.params.gateThreshold = p.gate.threshold ?? 50;
      state.params.gateRelease = p.gate.release ?? 50;
    }
    if (p.mod) {
      state.params.modOn = p.mod.on;
      state.params.modType = p.mod.type ?? 0;
      state.params.modSpeed = p.mod.speed ?? 30;
      state.params.modDepth = p.mod.depth ?? 40;
      state.params.modMix = p.mod.mix ?? 35;
    }
    if (p.delay) {
      state.params.delayOn = p.delay.on;
      state.params.delayTime = p.delay.time ?? 350;
      state.params.delayFeedback = p.delay.feedback ?? 30;
      state.params.delayLevel = p.delay.level ?? 30;
    }
    if (p.reverb) {
      state.params.reverbOn = p.reverb.on;
      state.params.reverbType = p.reverb.type ?? 0;
      state.params.reverbTime = p.reverb.time ?? 30;
      state.params.reverbPreDelay = p.reverb.pre ?? 20;
      state.params.reverbLevel = p.reverb.level ?? 35;
    }
  }

  updateLivePatchName(p.name);
  setAmpModel(p.model);

  // Send single parameters
  setTimeout(() => {
    sendParam(THR.ADDR.CABINET, state.params.cabinet);
    sendParam(THR.ADDR.GAIN, state.params.gain);
    sendParam(THR.ADDR.MASTER, state.params.master);
    sendParam(THR.ADDR.BASS, state.params.bass);
    sendParam(THR.ADDR.MIDDLE, state.params.middle);
    sendParam(THR.ADDR.TREBLE, state.params.treble);

    if (!state.params.preserveEffects) {
      // Comp
      sendParam(THR.ADDR.COMP_TYPE, state.params.compType);
      sendParam(THR.ADDR.COMP_SUSTAIN, state.params.compSustain);
      sendParam(THR.ADDR.COMP_OUTPUT, state.params.compOutput);
      sendParam(THR.ADDR.COMP_BYPASS, state.params.compOn ? 0 : 127);

      // Gate
      sendParam(THR.ADDR.GATE_THRESHOLD, state.params.gateThreshold);
      sendParam(THR.ADDR.GATE_RELEASE, state.params.gateRelease);
      sendParam(THR.ADDR.GATE_BYPASS, state.params.gateOn ? 0 : 127);

      // Mod
      sendParam(THR.ADDR.MOD_TYPE, state.params.modType);
      sendParam(THR.ADDR.MOD_SPEED, state.params.modSpeed);
      sendParam(THR.ADDR.MOD_DEPTH, state.params.modDepth);
      sendParam(THR.ADDR.MOD_MIX, state.params.modMix);
      sendParam(THR.ADDR.MOD_BYPASS, state.params.modOn ? 0 : 127);

      // Delay
      sendParam(THR.ADDR.DELAY_TIME, state.params.delayTime, true);
      sendParam(THR.ADDR.DELAY_FEEDBACK, state.params.delayFeedback);
      sendParam(THR.ADDR.DELAY_LEVEL, state.params.delayLevel);
      sendParam(THR.ADDR.DELAY_BYPASS, state.params.delayOn ? 0 : 127);

      // Reverb
      sendParam(THR.ADDR.REVERB_TYPE, state.params.reverbType);
      sendParam(THR.ADDR.REVERB_TIME, state.params.reverbTime, true);
      sendParam(THR.ADDR.REVERB_PREDELAY, state.params.reverbPreDelay, true);
      sendParam(THR.ADDR.REVERB_LEVEL, state.params.reverbLevel);
      sendParam(THR.ADDR.REVERB_BYPASS, state.params.reverbOn ? 0 : 127);
    }

    updateFullUI();
    showToast(`Loaded Preset: ${p.name}`, false);
  }, 120);
}

// -----------------------------------------------------------------------------
// Tap Tempo Logic
// -----------------------------------------------------------------------------
let tapTimes = [];
function handleTapTempo() {
  const now = Date.now();
  tapTimes.push(now);
  if (tapTimes.length > 4) tapTimes.shift();

  if (tapTimes.length >= 2) {
    const diffs = [];
    for (let i = 1; i < tapTimes.length; i++) {
      diffs.push(tapTimes[i] - tapTimes[i - 1]);
    }
    const avgDiff = Math.round(diffs.reduce((a, b) => a + b) / diffs.length);
    if (avgDiff >= 20 && avgDiff <= 2000) {
      state.params.delayTime = avgDiff;
      updateKnob(THR.ADDR.DELAY_TIME, avgDiff);
      sendParam(THR.ADDR.DELAY_TIME, avgDiff, true);
      showToast(`Tap Tempo: ${avgDiff} ms`, false);
    }
  }
}

// -----------------------------------------------------------------------------
// Event Listeners Setup
// -----------------------------------------------------------------------------
function setupEventListeners() {
  document.getElementById("btn-connect").onclick = () => initWebMIDI(true);
  document.getElementById("btn-sync-amp").onclick = () => {
    sendSettingsRequest();
    showToast("Requested full settings block from amp...", false);
  };

  // Tap Tempo Button
  document.getElementById("btn-tap-tempo").onclick = handleTapTempo;

  // Model Category Filter Buttons
  const filterButtons = document.querySelectorAll("#model-filter-selector .seg-btn");
  filterButtons.forEach(btn => {
    btn.onclick = () => {
      filterButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.params.modelFilter = btn.dataset.filter;
      buildModelSelectorUI();
    };
  });

  // Power switches for bypass toggling
  document.getElementById("btn-comp-power").onclick = () => {
    state.params.compOn = !state.params.compOn;
    updateCompBypassUI();
    sendParam(THR.ADDR.COMP_BYPASS, state.params.compOn ? 0 : 127);
  };

  document.getElementById("btn-gate-power").onclick = () => {
    state.params.gateOn = !state.params.gateOn;
    updateGateBypassUI();
    sendParam(THR.ADDR.GATE_BYPASS, state.params.gateOn ? 0 : 127);
  };

  document.getElementById("btn-mod-power").onclick = () => {
    state.params.modOn = !state.params.modOn;
    document.getElementById("btn-mod-power").classList.toggle("active", state.params.modOn);
    sendParam(THR.ADDR.MOD_BYPASS, state.params.modOn ? 0 : 127);
  };

  document.getElementById("btn-delay-power").onclick = () => {
    state.params.delayOn = !state.params.delayOn;
    document.getElementById("btn-delay-power").classList.toggle("active", state.params.delayOn);
    sendParam(THR.ADDR.DELAY_BYPASS, state.params.delayOn ? 0 : 127);
  };

  document.getElementById("btn-reverb-power").onclick = () => {
    state.params.reverbOn = !state.params.reverbOn;
    document.getElementById("btn-reverb-power").classList.toggle("active", state.params.reverbOn);
    sendParam(THR.ADDR.REVERB_BYPASS, state.params.reverbOn ? 0 : 127);
  };

  // Compressor Type Selector
  const compButtons = document.querySelectorAll("#comp-type-selector .seg-btn");
  compButtons.forEach(btn => {
    btn.onclick = () => {
      compButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.params.compType = parseInt(btn.dataset.type);
      sendParam(THR.ADDR.COMP_TYPE, state.params.compType);
      buildCompUI();
    };
  });

  // Reverb Type Selector
  const revButtons = document.querySelectorAll("#reverb-type-selector .seg-btn");
  revButtons.forEach(btn => {
    btn.onclick = () => {
      revButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.params.reverbType = parseInt(btn.dataset.type);
      sendParam(THR.ADDR.REVERB_TYPE, state.params.reverbType);
      buildReverbUI();
    };
  });

  // Modulation Type Selector
  const modButtons = document.querySelectorAll("#mod-type-selector .seg-btn");
  modButtons.forEach(btn => {
    btn.onclick = () => {
      modButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.params.modType = parseInt(btn.dataset.type);
      sendParam(THR.ADDR.MOD_TYPE, state.params.modType);
      buildModUI();
    };
  });

  // System Hardware Toggles
  const wideToggle = document.getElementById("toggle-wide-stereo");
  wideToggle.classList.toggle("active", state.params.wideStereo);
  wideToggle.onclick = () => {
    state.params.wideStereo = !state.params.wideStereo;
    wideToggle.classList.toggle("active", state.params.wideStereo);
    sendSystem(0x00, state.params.wideStereo ? 0 : 1);
  };

  const lampToggle = document.getElementById("toggle-tube-lamp");
  lampToggle.classList.toggle("active", state.params.tubeLamp);
  lampToggle.onclick = () => {
    state.params.tubeLamp = !state.params.tubeLamp;
    lampToggle.classList.toggle("active", state.params.tubeLamp);
    sendSystem(0x01, state.params.tubeLamp ? 0 : 1);
  };

  // Lock FX Toggle Button
  const btnLockFx = document.getElementById("btn-toggle-lock-fx");
  if (btnLockFx) {
    btnLockFx.onclick = () => {
      state.params.preserveEffects = !state.params.preserveEffects;
      btnLockFx.classList.toggle("active", state.params.preserveEffects);
      const textSpan = document.getElementById("lock-fx-text");
      if (textSpan) {
        textSpan.textContent = state.params.preserveEffects ? "Effects Locked" : "Effects Unlocked";
      }
      showToast(state.params.preserveEffects 
        ? "🔒 Effects Locked: Presets only change amp & tone stack" 
        : "🔓 Effects Unlocked: Presets will apply effects", false);
    };
  }

  const voicingSelect = document.getElementById("select-voicing");
  if (voicingSelect) {
    voicingSelect.onchange = (e) => {
      const val = parseInt(e.target.value);
      state.params.voicing = val;
      sendSystem(0x02, val);
      showToast(`Speaker Voicing set to Curve ${val} (Saved in EEPROM)`, false);
    };
  }

  // Light Show Easter Egg Trigger
  const btnLightShow = document.getElementById("btn-light-show");
  if (btnLightShow) {
    btnLightShow.onclick = triggerLightShow;
  }

  // Modular DSP Console Event Listeners
  const dspHeader = document.getElementById("header-modular-dsp");
  const dspBody = document.getElementById("modular-dsp-body");
  const dspToggleIcon = document.getElementById("dsp-toggle-icon");
  if (dspHeader && dspBody) {
    dspHeader.onclick = () => {
      const isHidden = dspBody.style.display === "none";
      dspBody.style.display = isHidden ? "block" : "none";
      if (dspToggleIcon) dspToggleIcon.style.transform = isHidden ? "rotate(180deg)" : "rotate(0deg)";
    };
  }

  // Quick Macros
  const btnDry = document.getElementById("btn-dsp-srev2-dry");
  if (btnDry) {
    btnDry.onclick = () => {
      sendModularDspBatch(6, [{ addr: 0x2055DE4, val: 0x0000 }, { addr: 0x2055E00, val: 0x0000 }]);
      showToast("SREV2 Studio Reverb: Pre-Delay & Early Reflections Set to Studio Dry (0ms)", false);
    };
  }

  const btnSpacious = document.getElementById("btn-dsp-srev2-spacious");
  if (btnSpacious) {
    btnSpacious.onclick = () => {
      sendModularDspBatch(6, [{ addr: 0x2055DE4, val: 0x002D }, { addr: 0x2055E00, val: 0x0010 }]);
      showToast("SREV2 Studio Reverb: Pre-Delay 45ms & 14 Extended ER Taps Latch Applied!", false);
    };
  }

  const btnLfoToggle = document.getElementById("btn-dsp-lfo-toggle");
  if (btnLfoToggle) {
    btnLfoToggle.onclick = toggleLfoStream;
  }

  const btnFilterDeep = document.getElementById("btn-dsp-filter-deep");
  if (btnFilterDeep) {
    btnFilterDeep.onclick = () => {
      sendModularDspBatch(7, [{ addr: 0x1C54, val: 0x4270 }, { addr: 0x1C56, val: 0x4370 }]);
      showToast("Acoustic Filter Bank: Deep Resonance Poles (60Hz / 240Hz) Injected", false);
    };
  }

  const btnFilterAir = document.getElementById("btn-dsp-filter-air");
  if (btnFilterAir) {
    btnFilterAir.onclick = () => {
      sendModularDspBatch(7, [{ addr: 0x1C54, val: 0x44B4 }, { addr: 0x1C56, val: 0x4534 }]);
      showToast("Acoustic Filter Bank: Air Resonance Poles (1440Hz / 2880Hz) Injected", false);
    };
  }

  // Manual Register Batch Injector
  const btnDspSend = document.getElementById("btn-dsp-send");
  if (btnDspSend) {
    btnDspSend.onclick = () => {
      const blockId = parseInt(document.getElementById("dsp-block-select").value) || 0;
      const addrStr = document.getElementById("dsp-reg-addr").value.trim();
      const valStr = document.getElementById("dsp-reg-val").value.trim();
      const addr = addrStr.startsWith("0x") || addrStr.startsWith("0X") ? parseInt(addrStr, 16) : parseInt(addrStr, 10);
      const val = valStr.startsWith("0x") || valStr.startsWith("0X") ? parseInt(valStr, 16) : parseInt(valStr, 10);
      if (isNaN(addr) || isNaN(val)) {
        showToast("Invalid register address or value (use hex like 0x1C54 or integer)", true);
        return;
      }
      sendModularDspBatch(blockId, [{ addr, val }]);
      showToast(`Batch Frame Injected to Block ${blockId}: Addr 0x${addr.toString(16).toUpperCase()}, Val 0x${val.toString(16).toUpperCase()}`, false);
    };
  }

  // Save Preset Action
  document.getElementById("btn-save-preset").onclick = () => {
    const name = prompt("Enter a name for this custom tone preset:", "My Custom Tone");
    if (name && name.trim()) {
      saveUserPreset({
        name: name.trim(),
        model: state.params.ampModel,
        cabinet: state.params.cabinet,
        gain: state.params.gain,
        master: state.params.master,
        bass: state.params.bass,
        middle: state.params.middle,
        treble: state.params.treble,
        comp: { on: state.params.compOn, type: state.params.compType, sustain: state.params.compSustain, output: state.params.compOutput },
        gate: { on: state.params.gateOn, threshold: state.params.gateThreshold, release: state.params.gateRelease },
        mod: { on: state.params.modOn, type: state.params.modType, speed: state.params.modSpeed, depth: state.params.modDepth, mix: state.params.modMix },
        delay: { on: state.params.delayOn, time: state.params.delayTime, feedback: state.params.delayFeedback, level: state.params.delayLevel },
        reverb: { on: state.params.reverbOn, type: state.params.reverbType, time: state.params.reverbTime, pre: state.params.reverbPreDelay, level: state.params.reverbLevel }
      });
    }
  };

  // Export Presets Action
  document.getElementById("btn-export-presets").onclick = () => {
    const data = JSON.stringify(getUserPresets(), null, 2);
    const blob = new Blob([data], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `thr_user_presets_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Import Presets Action
  const importInput = document.getElementById("import-file");
  document.getElementById("btn-import-presets").onclick = () => importInput.click();
  importInput.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const imported = JSON.parse(evt.target.result);
        if (Array.isArray(imported)) {
          const current = getUserPresets();
          const merged = [...current, ...imported];
          localStorage.setItem("thr_user_presets", JSON.stringify(merged));
          initPresets();
          showToast(`Imported ${imported.length} presets!`, false);
        }
      } catch (err) {
        showToast("Invalid JSON presets file", true);
      }
    };
    reader.readAsText(file);
  };
}

// -----------------------------------------------------------------------------
// Toast Messages
// -----------------------------------------------------------------------------
function showToast(msg, isError = false) {
  const el = document.getElementById("toast-msg");
  if (!el) return;
  el.textContent = msg;
  el.className = `toast-msg show ${isError ? "error" : "success"}`;

  if (UI.toastTimeout) clearTimeout(UI.toastTimeout);
  UI.toastTimeout = setTimeout(() => {
    el.className = "toast-msg";
  }, 3200);
}

// -----------------------------------------------------------------------------
// Light Show Easter Egg Sequence
// -----------------------------------------------------------------------------
let lightShowActive = false;

function triggerLightShow() {
  if (lightShowActive) return;
  lightShowActive = true;

  const originalLamp = state.params.tubeLamp;
  const originalStereo = state.params.wideStereo;

  showToast("✨ Vacuum Tube Light Show Running...", false);
  document.body.classList.add("light-show-active");

  const steps = [
    // Strobe burst 1
    { lamp: 1, stereo: 1, delay: 80 },
    { lamp: 0, stereo: 0, delay: 80 },
    { lamp: 1, stereo: 1, delay: 80 },
    { lamp: 0, stereo: 0, delay: 80 },
    // Alternating pulse
    { lamp: 1, stereo: 0, delay: 110 },
    { lamp: 0, stereo: 1, delay: 110 },
    { lamp: 1, stereo: 0, delay: 110 },
    { lamp: 0, stereo: 1, delay: 110 },
    // Breathing pulse
    { lamp: 1, stereo: 1, delay: 260 },
    { lamp: 0, stereo: 0, delay: 180 },
    { lamp: 1, stereo: 1, delay: 350 },
    { lamp: 0, stereo: 0, delay: 180 },
    // Rapid finish
    { lamp: 1, stereo: 1, delay: 70 },
    { lamp: 0, stereo: 0, delay: 70 },
    { lamp: 1, stereo: 1, delay: 70 },
    { lamp: 0, stereo: 0, delay: 70 },
    { lamp: 1, stereo: 1, delay: 300 }
  ];

  let currentStep = 0;
  function runStep() {
    if (currentStep >= steps.length) {
      // Restore user original states (0 = ON, 1 = OFF on hardware)
      sendSystem(0x01, originalLamp ? 0 : 1);
      sendSystem(0x00, originalStereo ? 0 : 1);
      const lampToggle = document.getElementById("toggle-tube-lamp");
      if (lampToggle) lampToggle.classList.toggle("active", originalLamp);
      const wideToggle = document.getElementById("toggle-wide-stereo");
      if (wideToggle) wideToggle.classList.toggle("active", originalStereo);
      document.body.classList.remove("light-show-active");
      lightShowActive = false;
      showToast("✨ Light Show Complete! Restored original tube lamp settings.", false);
      return;
    }
    const s = steps[currentStep++];
    sendSystem(0x01, s.lamp);
    sendSystem(0x00, s.stereo ? 0 : 1);
    setTimeout(runStep, s.delay);
  }

  runStep();
}
