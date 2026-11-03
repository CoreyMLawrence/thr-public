# Practical Guide 1: Tooling & Environment Setup

A quick, 3-minute setup guide to connect your Yamaha THR amplifier to your computer and verify MIDI communication.

---

## 1. System Requirements

- **Operating System:** Windows 10/11, macOS 10.14+, or any modern Linux distribution.
- **Python:** Python 3.8 or newer installed on your machine.
- **Hardware:**
  - Any Yamaha THR desktop amplifier (THR5, THR5A, THR10, THR10C, THR10X).
  - Standard USB Type-A to Type-B cable (standard printer-style USB cable).
  - Official Yamaha 15V DC power supply (strongly recommended over battery power).

---

## 2. Installing Python Dependencies

Open your terminal (PowerShell, Command Prompt, or bash) and install the two required MIDI libraries:

```powershell
pip install mido python-rtmidi
```

> [!TIP]
> **Windows Users:** The Yamaha THR is a USB Audio Class 1.0 device. Windows automatically recognizes it without requiring third-party drivers. If you have the official Yamaha USB MIDI driver installed, that works too.

---

## 3. Connecting Your Amplifier

1. Connect the USB cable between your computer and the USB port on the back of the THR.
2. Turn the amplifier **ON**.
3. Verify connection by running the live MIDI listener:

```powershell
python tools/thr_live.py listen
```

### Expected Output:
```text
[+] Searching for Yamaha THR MIDI ports...
[+] Connected to In: THR5-1 0 | Out: THR5-1 1
[+] Listening for real-time MIDI events. Turn physical knobs to test...
```

4. **Test Physical Knobs:**
   Turn the **GAIN** or **BASS** knob on your amplifier. You will see real-time SysEx events streaming in your terminal:
   ```text
   <message sysex=(240, 67, 125, 16, 65, 48, 1, 1, 0, 75, 247)> (Gain set to 75)
   <message sysex=(240, 67, 125, 16, 65, 48, 1, 3, 0, 50, 247)> (Bass set to 50)
   ```

If you see these messages, your tooling is **100% operational** and ready for firmware extraction or live tweaking! Press `Ctrl+C` to exit.
