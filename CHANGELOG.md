# Changelog

## [1.0.0] – V1.0 Official Checkpoint

**Known working checkpoint** for the first stable release.

### Summary
- **App name:** ReRe (with quirky Re logo)
- **Storage:** `%APPDATA%\ReRe\` (macros, settings)
- **Intervals:** Key spammer and mouse clicker support up to **10 minutes** (600,000 ms)
- **Theme:** Light / Dark / System – all settings (including theme) remembered on next launch
- **Randomization:** Uses saved min/max from Settings; minimum 0.5 ms jitter when enabled (reduces machine-like patterns)
- **Live recording:** Macro Recorder tab shows each key, mouse click, move, and duration as you record
- **Custom hotkeys:** Start/Stop recording hotkeys (default F9/F10) – set via “Record key” in Settings; saved and used on next run
- **Anti‑cheat considerations:** SendInput only (user-mode, no kernel driver); scan codes + relative mouse; optional timing/mouse jitter; no injection or hooks for playback

### How to tag this as V1.0
```bash
git add -A
git commit -m "ReRe v1.0.0: rename, logo, 10min interval, theme fix, live events, custom hotkeys, settings persistence"
git tag -a v1.0.0 -m "ReRe v1.0.0 official release"
git push origin main --tags
```

### Build installer
Run `run_as_admin.bat` to start the app as admin. Build the installer with `build.bat` (output: `installer\Output\ReRe_Setup_v1.0.exe`).
