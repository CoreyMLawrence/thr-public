#!/usr/bin/env python3
"""
thr_lcd.py - High-Level Hardware 16x2 LCD UI Engine for Yamaha THR Companion
=============================================================================
Provides AI coding agents, background daemons, and firmware tools with an
immediate, expressive interface to the physical 16x2 I2C display.

Features:
- Visual animated progress & loading bars for flashing, dumping, and builds.
- Dedicated 3-phase flashing progress bars (Erase, Streaming, Completion).
- Live amp status & model preset cards.
- Fallback resilience: Uses localhost HTTP API or direct I2C smbus driver.
"""

import sys
import os
import time
import json
import urllib.request

LCD_API_URL = "http://localhost/api"


def _post(endpoint, payload):
    try:
        url = f"{LCD_API_URL}/{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        # Fallback to direct driver if HTTP daemon is down or unreachable
        try:
            from lcd_driver import LCDController
            _ctrl = LCDController()
            if endpoint == "display":
                _ctrl.display(payload.get("line1", ""), payload.get("line2", ""), align=payload.get("align", "left"))
            elif endpoint == "clear":
                _ctrl.clear()
            elif endpoint == "backlight":
                _ctrl.set_backlight(payload.get("backlight", True))
        except Exception:
            pass
    return None


def set_text(line1="", line2="", align="left"):
    """Display arbitrary text across Line 1 and Line 2 (16 chars each)."""
    return _post("display", {"line1": str(line1)[:16], "line2": str(line2)[:16], "align": align})


# Common alias for compatibility
write_lines = set_text


def render_progress_bar(pct, width=14):
    """
    Renders an ASCII progress bar enclosed in brackets.
    Example for width=14: '[=======>     ]'
    """
    pct = max(0, min(100, int(pct)))
    filled = int(round((pct / 100.0) * width))
    if filled == 0 and pct > 0:
        filled = 1
    if filled >= width:
        bar = "=" * width
    else:
        bar = "=" * filled + ">" + " " * (width - filled - 1)
    return f"[{bar[:width]}]"


def render_terminal_bar(current, total, width=28):
    """Renders a rich ASCII progress bar string for terminal output."""
    if total <= 0:
        total = 1
    pct = max(0.0, min(100.0, (current / total) * 100.0))
    filled = int(round((pct / 100.0) * width))
    if filled >= width:
        bar = "=" * width
    else:
        bar = "=" * filled + ">" + " " * (width - filled - 1)
    return f"[{bar[:width]}] {pct:5.1f}%"


def show_progress(current, total, title="Progress", status_line=None):
    """
    Renders an ASCII loading bar on Line 2 with percentage on Line 1.
    Example:
        Line 1: Flashing:  65%
        Line 2: [=======>    ]
    """
    if total <= 0:
        total = 1
    pct = max(0, min(100, int((current / total) * 100)))
    bar_str = render_progress_bar(pct, width=14)
    l1 = f"{title[:10]}: {pct:>3}%"
    l2 = status_line[:16] if status_line else bar_str
    return set_text(l1, l2)


def show_flash_erase(elapsed_sec, total_sec=16.0):
    """
    Renders Phase 1 (NOR Flash Erase) progress bar on the 16x2 LCD.
    Example:
        Line 1: Erase:  12s  25%
        Line 2: [===>        ]
    """
    pct = min(100, int((elapsed_sec / total_sec) * 100))
    remaining = max(0, int(round(total_sec - elapsed_sec)))
    bar_str = render_progress_bar(pct, width=14)
    l1 = f"Erase: {remaining:>2}s {pct:>3}%"
    return set_text(l1, bar_str)


def show_flash_streaming(current_block, total_blocks=2341, elapsed=0.0, rate=0.0):
    """
    Renders Phase 2 (Firmware Streaming) progress bar on the 16x2 LCD.
    Example:
        Line 1: Flash:  65%  24s
        Line 2: [========>   ]
    """
    if total_blocks <= 0:
        total_blocks = 1
    pct = min(100, int((current_block / total_blocks) * 100))
    bar_str = render_progress_bar(pct, width=14)
    l1 = f"Flash: {pct:>3}% {int(elapsed):>3}s"
    return set_text(l1, bar_str)


def show_flash_done():
    """Renders Phase 3 (Flash Complete) alert on the 16x2 LCD."""
    flash_alert(times=2, delay=0.15)
    return set_text("Flash Complete!", "Please Reboot")


def show_flash_error(err="Error"):
    """Renders flash failure alert on the 16x2 LCD."""
    flash_alert(times=3, delay=0.1)
    return set_text("FLASH ERROR!", str(err)[:16])


def show_status(title, detail=""):
    """Formats a clean title and detail message."""
    return set_text(title.center(16), detail.center(16))


def show_amp_model(bank_name, model_name, cab=""):
    """
    Displays active amp model information in hardware format.
    Example:
        Line 1: [#] Clean (EG)
        Line 2: Cab: 1x12 Deluxe
    """
    l1 = f"{bank_name} {model_name}"[:16]
    l2 = f"Cab: {cab}"[:16] if cab else "Authentic Tone"[:16]
    return set_text(l1, l2)


def show_flashing(current_block, total_blocks=2341, phase="Streaming"):
    """Optimized progress renderer for firmware streaming."""
    return show_flash_streaming(current_block, total_blocks)


def clear():
    """Clears the LCD display."""
    return _post("clear", {})


def set_backlight(state=True):
    """Enables or disables LCD backlight."""
    return _post("backlight", {"backlight": bool(state)})


def flash_alert(times=2, delay=0.15):
    """Flashes the LCD backlight to indicate completion or alert."""
    for _ in range(times):
        set_backlight(False)
        time.sleep(delay)
        set_backlight(True)
        time.sleep(delay)


if __name__ == "__main__":
    print("Testing thr_lcd demo sequences...")
    show_status("THR Companion", "Testing Bar...")
    time.sleep(0.5)
    for i in range(0, 101, 10):
        show_flash_streaming(i, 100, elapsed=i * 0.1)
        time.sleep(0.1)
    show_flash_done()
    print("Demo complete!")
