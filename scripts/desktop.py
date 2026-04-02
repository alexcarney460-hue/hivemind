#!/usr/bin/env python3
"""Desktop Control Module — gives Claude eyes and hands.

Capabilities:
  - Screenshot capture (full screen or region)
  - Mouse click, move, drag
  - Keyboard typing and hotkeys
  - Window management (find, focus, resize)
  - Screen text extraction (OCR)
  - GUI element detection

Uses pyautogui for control, PIL for screenshots, and optional pytesseract for OCR.
"""

import json
import sys
import os
import subprocess
import base64
import time
from datetime import datetime

# Lazy imports — only load heavy deps when needed
_pyautogui = None
_pil = None


def get_pyautogui():
    global _pyautogui
    if _pyautogui is None:
        try:
            import pyautogui
            pyautogui.FAILSAFE = True  # Move mouse to corner to abort
            pyautogui.PAUSE = 0.3
            _pyautogui = pyautogui
        except ImportError:
            print("pyautogui not installed. Run: pip install pyautogui", file=sys.stderr)
            sys.exit(1)
    return _pyautogui


def get_pil():
    global _pil
    if _pil is None:
        try:
            from PIL import Image
            _pil = Image
        except ImportError:
            print("Pillow not installed. Run: pip install Pillow", file=sys.stderr)
            sys.exit(1)
    return _pil


SCREENSHOT_DIR = os.path.expanduser("~/.openclaw/workspace/hivemind-screenshots")


def screenshot(region=None, save=True):
    """Capture screenshot. Returns file path."""
    pag = get_pyautogui()
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    filepath = os.path.join(SCREENSHOT_DIR, f"screen-{ts}.png")

    img = pag.screenshot(region=region)
    if save:
        img.save(filepath)
    return filepath


def screenshot_base64(region=None):
    """Capture screenshot and return as base64 for inline display."""
    import io
    pag = get_pyautogui()
    img = pag.screenshot(region=region)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def click(x, y, button="left", clicks=1):
    """Click at coordinates."""
    pag = get_pyautogui()
    pag.click(x, y, button=button, clicks=clicks)
    return {"action": "click", "x": x, "y": y, "button": button}


def double_click(x, y):
    """Double click at coordinates."""
    pag = get_pyautogui()
    pag.doubleClick(x, y)
    return {"action": "double_click", "x": x, "y": y}


def right_click(x, y):
    """Right click at coordinates."""
    pag = get_pyautogui()
    pag.rightClick(x, y)
    return {"action": "right_click", "x": x, "y": y}


def move_to(x, y, duration=0.3):
    """Move mouse to coordinates."""
    pag = get_pyautogui()
    pag.moveTo(x, y, duration=duration)
    return {"action": "move", "x": x, "y": y}


def drag_to(x, y, duration=0.5, button="left"):
    """Drag from current position to coordinates."""
    pag = get_pyautogui()
    pag.dragTo(x, y, duration=duration, button=button)
    return {"action": "drag", "x": x, "y": y}


def type_text(text, interval=0.02):
    """Type text at current cursor position."""
    pag = get_pyautogui()
    pag.typewrite(text, interval=interval)
    return {"action": "type", "length": len(text)}


def hotkey(*keys):
    """Press key combination (e.g., hotkey('ctrl', 'c'))."""
    pag = get_pyautogui()
    pag.hotkey(*keys)
    return {"action": "hotkey", "keys": list(keys)}


def press(key, presses=1):
    """Press a single key."""
    pag = get_pyautogui()
    pag.press(key, presses=presses)
    return {"action": "press", "key": key}


def scroll(clicks, x=None, y=None):
    """Scroll at position. Positive = up, negative = down."""
    pag = get_pyautogui()
    pag.scroll(clicks, x=x, y=y)
    return {"action": "scroll", "clicks": clicks}


def get_screen_size():
    """Get screen resolution."""
    pag = get_pyautogui()
    w, h = pag.size()
    return {"width": w, "height": h}


def get_mouse_position():
    """Get current mouse position."""
    pag = get_pyautogui()
    x, y = pag.position()
    return {"x": x, "y": y}


def find_on_screen(image_path, confidence=0.8):
    """Find an image on screen. Returns coordinates or None."""
    pag = get_pyautogui()
    try:
        location = pag.locateOnScreen(image_path, confidence=confidence)
        if location:
            center = pag.center(location)
            return {"x": center.x, "y": center.y, "found": True}
    except Exception as e:
        return {"found": False, "error": str(e)}
    return {"found": False}


def get_active_window():
    """Get info about the active window."""
    pag = get_pyautogui()
    try:
        win = pag.getActiveWindow()
        if win:
            return {
                "title": win.title,
                "left": win.left,
                "top": win.top,
                "width": win.width,
                "height": win.height
            }
    except Exception:
        pass
    # Fallback: use PowerShell
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "(Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object ProcessName, MainWindowTitle | ConvertTo-Json)"],
            capture_output=True, text=True, timeout=5
        )
        return json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}


def list_windows():
    """List all visible windows."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object Id, ProcessName, MainWindowTitle | ConvertTo-Json"],
            capture_output=True, text=True, timeout=5
        )
        return json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}


def focus_window(title_substring):
    """Bring a window to front by title match."""
    try:
        ps_cmd = f"""
        $w = Get-Process | Where-Object {{$_.MainWindowTitle -like '*{title_substring}*'}} | Select-Object -First 1
        if ($w) {{
            $sig = '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);'
            Add-Type -MemberDefinition $sig -Name Win -Namespace Native
            [Native.Win]::SetForegroundWindow($w.MainWindowHandle)
            Write-Output "Focused: $($w.MainWindowTitle)"
        }} else {{
            Write-Output "Window not found"
        }}
        """
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=5
        )
        return {"result": result.stdout.strip()}
    except Exception as e:
        return {"error": str(e)}


def ocr_screen(region=None):
    """Extract text from screen using OCR."""
    try:
        import pytesseract
        pag = get_pyautogui()
        img = pag.screenshot(region=region)
        text = pytesseract.image_to_string(img)
        return {"text": text.strip()}
    except ImportError:
        return {"error": "pytesseract not installed. Run: pip install pytesseract"}
    except Exception as e:
        return {"error": str(e)}


# === CLI interface — called from Claude Code hooks/commands ===

ACTIONS = {
    "screenshot": lambda args: screenshot(
        region=tuple(args["region"]) if "region" in args else None
    ),
    "click": lambda args: click(args["x"], args["y"], args.get("button", "left")),
    "double_click": lambda args: double_click(args["x"], args["y"]),
    "right_click": lambda args: right_click(args["x"], args["y"]),
    "move": lambda args: move_to(args["x"], args["y"]),
    "drag": lambda args: drag_to(args["x"], args["y"]),
    "type": lambda args: type_text(args["text"]),
    "hotkey": lambda args: hotkey(*args["keys"]),
    "press": lambda args: press(args["key"], args.get("presses", 1)),
    "scroll": lambda args: scroll(args["clicks"], args.get("x"), args.get("y")),
    "screen_size": lambda args: get_screen_size(),
    "mouse_position": lambda args: get_mouse_position(),
    "find_image": lambda args: find_on_screen(args["image"], args.get("confidence", 0.8)),
    "active_window": lambda args: get_active_window(),
    "list_windows": lambda args: list_windows(),
    "focus_window": lambda args: focus_window(args["title"]),
    "ocr": lambda args: ocr_screen(
        region=tuple(args["region"]) if "region" in args else None
    ),
}


def main():
    """CLI: python desktop.py '{"action": "screenshot"}' """
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: desktop.py '{\"action\": \"...\", ...}'"}))
        sys.exit(1)

    try:
        args = json.loads(sys.argv[1])
        action = args.pop("action")
        if action not in ACTIONS:
            print(json.dumps({"error": f"Unknown action: {action}. Available: {list(ACTIONS.keys())}"}))
            sys.exit(1)
        result = ACTIONS[action](args)
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
