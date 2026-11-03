# Practical Guide 2: Extracting Your Factory Firmware

How to extract a complete binary backup of your amplifier's factory firmware directly over USB MIDI without any hardware modifications or soldering.

---

## Why You Must Extract Your Firmware First

Before attempting any modification, **always create a clean backup of your factory firmware**. 

Yamaha only provides download packages for a few select models on their website (such as the standard THR5/THR10 V2). If you own a **THR5A**, **THR10C**, or **THR10X**, Yamaha does not provide standalone ROM download files. Having your own factory dump ensures you can always restore your amplifier to factory-original condition.

---

## Step 1: Boot into Hardware Update Mode (`U`)

### The Official Update Mode Sequence:
1. Turn the amplifier power switch **OFF**.
2. **Press and hold the `TAP: TIME / HOLD: TUNER` button.**
3. While holding the button down, flip the power switch **ON**.
4. Continue holding the button until the LED display illuminates.
5. Within the next 4 seconds, **press the `TAP: TIME / HOLD: TUNER` button 5 times rapidly**.
6. After about 6 seconds, the amplifier will perform an internal soft-reboot into Update Mode, and the LED screen will display a solid **`U`**!

---

## Step 2: Extract the Firmware via USB MIDI

1. Ensure the USB cable is connected to your computer.
2. In your terminal, run the `dump` command:

```powershell
python tools/thr_tool.py dump --port THR --out factory_backup.mid
```

### What to Expect During the Dump:
- The script sends the `DTA1ROMR` dump request trigger to the amplifier.
- The amplifier immediately starts transmitting sequential MIDI SysEx blocks.
- A progress display tracks all 2,343 messages.
- The entire dump takes approximately **2.5 minutes**.
- When complete, you will see:
  ```text
  [+] Read complete: 2,343 messages received.
  [+] Checksum verified: DTA1CSUM matches DTAm memory!
  [+] Saved MIDI update container to: factory_backup.mid
  ```

---

## Step 3: Extract into a Raw Executable Binary (`.bin`)

To inspect, disassemble, or patch the code, extract the raw 1 MiB binary from the MIDI container:

```powershell
python tools/thr_tool.py extract --file factory_backup.mid --out factory_backup.bin
```

### Verification:
Verify the extracted file size:
```powershell
# File size MUST be exactly 1,048,576 bytes (1 MiB)
Get-Item factory_backup.bin | Select-Object Length
```

### Compute SHA-256 Checksum:
```powershell
Get-FileHash factory_backup.bin -Algorithm SHA256
```

### Known Official Factory Hashes:
- **THR5 Stock V2 (Electric):** `a502d43aaccb8062a0cb657400032e7c04dd9e37ff30f413b0267d782de3d753`
- **THR5A Stock (Acoustic):** `4d4719740db8f1217127f23c3fb0406cad5b74f8a7421a7e2db8d5c158cf7f3e`
- **THR10C Stock (`ver104c`):** `b08a90c2a6ea4b0c2ab17bde10754b29641f1503eafd62015519af36feef239c`

> [!IMPORTANT]
> Make a copy of `factory_backup.bin` and `factory_backup.mid`, rename them to something like `MY_AMP_GOLDEN_STOCK.bin`, and store them safely. This is your lifetime emergency restore image!
