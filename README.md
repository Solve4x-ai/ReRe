# ReRe (GameMacroTool)

Professional, installable Windows macro recorder and player for reliable input automation in protected modern games. Uses low-level SendInput (scan codes + relative mouse deltas) for maximum compatibility with anti-cheat systems.

## Features

- **Record** keyboard and mouse with high-resolution timestamps
- **Play back** macros deterministically at 0.5×–3.0× speed
- **Save/load** macros to `%APPDATA%\GameMacroTool\macros`
- **Randomization** toggle: ±5–15 ms timing, ±1–4 px mouse noise
- **Emergency stop** global hotkey: Ctrl+Shift+F12
- Dark-themed tkinter GUI with status bar

## Run from source

Requires Python 3.11+, Windows.

```bash
pip install -r requirements.txt
python -m src.main
```

Run from the repository root so that `src` is the package.

## Build installer

1. Install dependencies and build the app with PyInstaller:
   ```bash
   build.bat
   ```
2. Requires **Inno Setup 6** at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`.
3. Installer output: `installer\Output\GameMacroTool_Setup.exe`.

The installer creates Start Menu and Desktop shortcuts with “Run as administrator”.

## Where macros are stored

Macros are saved and loaded from:

`%APPDATA%\GameMacroTool\macros`

(e.g. `C:\Users\<You>\AppData\Roaming\GameMacroTool\macros`).
