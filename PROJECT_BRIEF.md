# Project Brief: ReRe

Professional, installable Windows application for reliable input automation in protected modern games. Uses low-level SendInput (scan codes + relative mouse deltas) for maximum compatibility with anti-cheat systems.

## Design Principles

- Strict modular separation: GUI, input backend, recorder, player, storage are independent and replaceable.
- Deterministic playback at 1.0× speed with humanization toggle OFF; high-resolution timing with `time.perf_counter()`.
- Thread-safe state transitions; emergency stop joins threads cleanly and releases all keys.
- GUI only dispatches commands; all heavy work in dedicated controllers.

## MVP Features

- Real-time macro recorder (keyboard + mouse), precise delta-based relative mouse movement.
- Save/load macros to `%APPDATA%\ReRe\macros`.
- Playback speed 0.5×–3.0× and randomization/humanization (Gaussian jitter, drift, micro-pauses when enabled).
- Global emergency stop hotkey; custom start/stop recording hotkeys.
- Professional customtkinter GUI with Quick Actions, Macro Recorder, Library, Settings.

## Technology Stack

- Python 3.11+; customtkinter; ctypes → user32.dll SendInput; pynput (capture only); keyboard library; time.perf_counter(); json; Inno Setup 6; PyInstaller --onedir --uac-admin.

## Critical Rules

- **Input backend:** Scan codes only (optional 85/15 mix with extended/absolute when stealth); mouse in relative deltas, 8–12 px max per packet.
- **Recording/playback:** Timestamps with time.perf_counter(); events as list of dicts; deterministic at 1.0× when humanization OFF; HumanizationEngine seeded per macro when ON.
- **Concurrency:** Central PlaybackController; states IDLE, RECORDING, PLAYING, PAUSED; emergency stop releases all keys.

---

## Anti-Detection Implementation (Applied)

### HumanizationEngine (src/utils.py)
- Gaussian jitter ±3–18 ms per event (configurable); variable key hold 50–180 ms; session drift ±4% over 5–30 min; micro-pauses 150–450 ms every 8–25 events (prob 3–7%). Seeded per macro load; deterministic at 1.0× with toggle OFF.

### Natural Mouse Path (src/player.py)
- Mouse movement: 4–8 control-point Catmull-Rom spline, ease-in/out, 1–3 micro-corrections ±2–6 px perpendicular; packets 8–12 px max; uses only input_backend.send_mouse_move() (relative).

### Variable Input Mix (src/input_backend.py)
- Settings: 85% scan-code SendInput, 15% mixed extended/absolute; 1–2 null SendInput between events; INPUT time field from QueryPerformanceCounter when enabled.

### Build Pipeline (build.bat)
- PyInstaller --onedir --key=RandomKey --distpath=dist, hidden-imports, optional UPX and Nuitka comments.

### Runtime
- Generic/configurable window title; sys.excepthook (no traceback in release); release_all_keys on exit and emergency stop; stealth options applied from Settings.

### Settings Tab
- Anti-Detection Profile (Safe/Aggressive/Stealth/Custom); Enable Advanced Humanization; Humanization intensity (Low–Paranoid); Insert nulls; Use QPC time; Obfuscate process name; Generic window title.

### Installer (installer/setup.iss)
- Comment for code-signing; optional install to %ProgramFiles%\SystemUtilities.

### Emergency & Logging
- Emergency stop releases all keys; zero persistent logging; traceback only in dev (non-frozen).

## Phase 2 (architecture-ready)

Macro segment looping; pause/resume; pixel-color wait; game HWND profile (only send when game foreground); Arduino HID; Windows Background Service wrapper.
