# Practical Guide 5: The Complete Disaster Recovery & Unbricking Manual

A complete, field-tested troubleshooting and hardware recovery guide to revive a frozen or bricked Yamaha THR amplifier under any circumstance.

---

## 1. Understanding What Can Go Wrong

When flashing firmware, issues generally fall into two categories:

| Failure Level | Symptoms | Root Cause | Recovery Method |
|---|---|---|---|
| **Level 1: Soft Failure** | Flashing was interrupted, USB disconnected mid-write, or power dropped. Screen is black or shows incomplete boot. | Incomplete binary written to Flash Section 2 (DTAm). | **Level 1 Soft Recovery** (Button combination re-entry, no tools needed). |
| **Level 2: Hard Failure** | Firmware with an invalid instruction or Thumb state error was flashed. Microcontroller crashes immediately on boot. Display is frozen/black, and the button update sequence fails to enter Update Mode. | CPU enters an instruction fault trap before button polling tasks initialize. | **Level 2 Hardware Recovery** (External SPI EEPROM clip to `IC11`, 100% guaranteed unbricking). |

---

## 2. Level 1: Soft Recovery (No Hardware Tools Needed)

Because of the architectural design of the Yamaha THR:
- The secondary bootloader containing the USB updater (**DTAb**) lives in **Section 1 (`0x02000100` to `0x0200FFFF`)**.
- Flashing firmware over USB MIDI **only erases Section 2 (`0x02010000` onward)**.
- **The updater itself is never erased during updates.**

### The Soft Recovery Steps:
*(Note: `TAP: TIME` and `TUNER` are the exact same physical button!)*
1. Turn the amplifier power switch **OFF**.
2. Disconnect the USB cable and wait 10 seconds.
3. Press and hold the **`TAP: TIME / HOLD: TUNER`** button.
4. While holding the button down, flip the power switch **ON** until the LED display illuminates.
5. Within the next 4 seconds, **press the `TAP: TIME / HOLD: TUNER` button 5 times rapidly**.
6. After about 6 seconds, the amplifier soft-reboots into Update Mode and displays a solid **`U`**.
7. Reconnect the USB cable.
8. Flash your clean factory backup:
   ```powershell
   python tools/thr_tool.py flash --port THR --file factory_backup.mid
   ```
9. Once `E`, `n`, `d` appears, power cycle the amplifier. Your unit is restored!

---

## 3. Level 2: Hard Recovery (Hardware SPI EEPROM Unbricking)

If experimental machine code causes an invalid instruction trap on power-up, the CPU hangs before checking the physical buttons. In this scenario, the button combination will not respond.

### Why This Method Always Works:
During early power-on reset, the hardware bootloader inspects the onboard 256-byte SPI EEPROM:
- If byte offset **`0x02`** contains `0x00`, the CPU tries to boot the main firmware (DTAm).
- If byte offset **`0x02`** contains **`0x01`**, the CPU **bypasses the broken firmware entirely** and immediately boots directly into the secondary bootloader, displaying a solid **`U`**!

By connecting an external SPI programmer clip to `IC11` and writing `0x01` to offset `0x02`, you can force any frozen THR back into Update Mode!

---

## 4. Required Hardware Tools

You do not need to desolder any components. All you need is:
1. **A CH341A USB SPI Programmer** (available for $5–$10 on Amazon, eBay, or AliExpress) OR a Raspberry Pi / Arduino with SPI pins.
2. **An SOIC-8 Test Clip** (often bundled with the CH341A).
3. The official Yamaha 15V AC power adapter.

---

## 5. Board Layout & Pinout of `IC11`

Open the top chassis of the amplifier. Near the central microcontroller, locate `IC11` (marked Renesas `R1EX25002` or `25020` / `25040`):

```
                 IC11 (Renesas R1EX25002) Pinout
                           +---+-+---+
           Pin 1: /CS   ---| 1     8 |-- Pin 8: VCC (LEAVE DISCONNECTED!)
           Pin 2: MISO  ---| 2     7 |-- Pin 7: /HOLD (Tied high on PCB)
           Pin 3: /WP   ---| 3     6 |-- Pin 6: SCK
           Pin 4: GND   ---| 4     5 |-- Pin 5: MOSI
                           +---------+
```

---

## 6. Wiring Diagram (CH341A to `IC11`)

Attach the SOIC-8 test clip to `IC11` and connect to the programmer:

| `IC11` Pin | Signal Name | Connect to CH341A |
|---|---|---|
| **Pin 1** | `/CS` (Chip Select) | Pin 1 (CS) |
| **Pin 2** | `MISO` (Data Out) | Pin 2 (MISO) |
| **Pin 4** | `GND` (Ground) | Pin 4 (GND) |
| **Pin 5** | `MOSI` (Data In) | Pin 5 (MOSI) |
| **Pin 6** | `SCK` (Clock) | Pin 6 (CLK) |
| **Pin 8** | **`VCC` (3.3V Power)** | **DO NOT CONNECT! LEAVE OPEN!** |

```
    +-----------------------------------------------------------+
    | CH341A USB Programmer                                     |
    |                                                           |
    |  Pin 1 (CS)   -----------------------------> IC11 Pin 1   |
    |  Pin 2 (MISO) -----------------------------> IC11 Pin 2   |
    |  Pin 4 (GND)  -----------------------------> IC11 Pin 4   |
    |  Pin 5 (MOSI) -----------------------------> IC11 Pin 5   |
    |  Pin 6 (SCK)  -----------------------------> IC11 Pin 6   |
    |                                                           |
    |  Pin 8 (VCC)  ---> [DISCONNECTED!]                        |
    +-----------------------------------------------------------+
```

> [!CAUTION]
> **CRITICAL HARDWARE SAFETY RULE:**
> **DO NOT connect Pin 8 (`VCC`)** to the programmer's power output!
> Powering the chip via USB programmer back-feeds power into the amplifier's 3.3V power rails, causing USB overcurrent shutdowns and risking damage to the SoC.
> **Leave Pin 8 disconnected and power the amplifier using its own 15V AC adapter.**

---

## 7. Step-by-Step Hardware Unbricking Walkthrough

### Step 1: Connect Clip & Power Up
1. Attach the SOIC-8 clip firmly onto `IC11`. Verify pins 1, 2, 4, 5, and 6 are aligned. Ensure Pin 8 is NOT connected to programmer power.
2. Plug the CH341A programmer into your computer's USB port.
3. Plug the official 15V AC adapter into the amplifier and turn the power switch **ON**.

### Step 2: Read & Backup EEPROM
Open your programmer utility (such as **AsProgrammer**, **Flashrom**, or **NeoProgrammer**):
1. Select IC type: `SPI EEPROM` $\rightarrow$ `25020` or `25040` (256 bytes).
2. Click **Read IC**.
3. Save the read contents as `eeprom_backup.bin`.

### Step 3: Arm the Boot Sentinel Byte
1. Open `eeprom_backup.bin` in any hex editor (e.g. HxD or VS Code hex editor).
2. Look at byte offset **`0x02`** (the 3rd byte from the beginning):
   ```text
   Offset:  00 01 02 03 04 05 ...
   Data:    00 00 00 00 00 00 ...
                  ^^
                  Change this byte from 00 to 01!
   ```
3. Change byte `0x02` from `0x00` $\rightarrow$ **`0x01`**.
4. Save the modified file as `eeprom_armed.bin`.

### Step 4: Write Armed Image Back to `IC11`
1. In your programmer software, open `eeprom_armed.bin`.
2. Click **Write IC** / **Program**.
3. Verify that the write succeeded.

### Step 5: Power On to Solid `U` & Reflash
1. Turn the amplifier's power switch **OFF**.
2. Disconnect the programmer and remove the SOIC-8 clip from `IC11`.
3. Connect your standard USB cable between the amplifier and your computer.
4. Turn the amplifier power switch **ON**.
5. **The display will instantly illuminate with a solid `U`!**
6. Open your terminal and flash your verified stock backup:
   ```powershell
   python tools/thr_tool.py flash --port THR --file factory_backup.mid
   ```
7. Wait 2.5 minutes until `E`, `n`, `d` loops on the screen.
8. Power cycle the amplifier. Your unit is 100% restored and fully working!
