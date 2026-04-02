---
description: Control the desktop — screenshot, click, type, find windows, OCR. Gives Claude eyes and hands.
argument-hint: "screenshot | click [x] [y] | type [text] | windows | focus [title] | ocr"
allowed-tools: ["Bash", "Read"]
---

# Desktop Control

Parse `$ARGUMENTS` and execute desktop actions via the desktop.py module.

**Module:** `~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py`

## Commands

### `/desktop screenshot`
Take a screenshot and display it:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "screenshot"}'
```
Then use the Read tool to display the saved screenshot image.

### `/desktop click [x] [y]`
Click at screen coordinates:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "click", "x": $X, "y": $Y}'
```

### `/desktop double-click [x] [y]`
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "double_click", "x": $X, "y": $Y}'
```

### `/desktop right-click [x] [y]`
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "right_click", "x": $X, "y": $Y}'
```

### `/desktop type [text]`
Type text at current cursor position:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "type", "text": "$TEXT"}'
```

### `/desktop hotkey [keys...]`
Press a key combo (e.g., ctrl c):
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "hotkey", "keys": ["$KEY1", "$KEY2"]}'
```

### `/desktop press [key]`
Press a single key:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "press", "key": "$KEY"}'
```

### `/desktop windows`
List all open windows:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "list_windows"}'
```

### `/desktop focus [title]`
Bring a window to the front by title match:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "focus_window", "title": "$TITLE"}'
```

### `/desktop ocr`
Extract text from current screen:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "ocr"}'
```

### `/desktop mouse`
Get current mouse position:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "mouse_position"}'
```

### `/desktop size`
Get screen resolution:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/desktop.py '{"action": "screen_size"}'
```

## Workflow: See → Decide → Act
1. Take screenshot: `/desktop screenshot` 
2. Claude reads the screenshot (visual) and understands the UI
3. Decide what to click/type based on what's visible
4. Execute: `/desktop click 500 300` or `/desktop type hello`
5. Screenshot again to verify the action worked

## Dependencies
Requires: `pip install pyautogui Pillow`
Optional OCR: `pip install pytesseract` (+ Tesseract binary)

## Safety
pyautogui.FAILSAFE is ON — move mouse to any screen corner to abort.
