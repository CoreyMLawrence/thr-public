#!/usr/bin/env python3
"""
thr_lcd.py - High-Level Hardware 16x2 LCD UI Engine for Yamaha THR Companion
=============================================================================
Provides AI coding agents, background daemons, and firmware tools with an
immediate, expressive interface to the physical 16x2 I2C display.

Features:
- Visual animated progress & loading bars for flashing, dumping, and builds.
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
    
    # 14 chars inside the brackets [ ... ]
    bar_width = 14
    filled = int(round((pct / 100.0) * bar_width))
    if filled == 0 and pct > 0:
        filled = 1

    bar = "=" * filled
    if filled < bar_width:
        bar += ">" + " " * (bar_width - filled - 1)
    else:
        bar = "=" * bar_width
    bar_str = f"[{bar}]"[:16]

    l1 = f"{title[:10]}: {pct:>3}%"
    l2 = status_line[:16] if status_line else bar_str
    return set_text(l1, l2)

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
    pct = int((current_block / total_blocks) * 100)
    l1 = f"{phase[:9]}: {pct:>3}%"
    
    bar_width = 14
    filled = int(round((pct / 100.0) * bar_width))
    bar = "=" * filled + (">" if filled < bar_width else "")
    bar = bar.ljust(bar_width)
    bar_str = f"[{bar}]"[:16]
    return set_text(l1, bar_str)

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
    show_status("THR Companion", "Initializing...")
    time.sleep(1.0)
    for i in range(0, 101, 10):
        show_progress(i, 100, title="Loading", status_line=None)
        time.sleep(0.15)
    flash_alert(2)
    show_amp_model("[#]", "Clean 1x12", "Deluxe")
    print("Demo complete!")
