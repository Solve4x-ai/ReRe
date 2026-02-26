"""
Load/save app settings to %APPDATA%\\ReRe\\settings.json.
Theme, macro path override, run on startup, hotkey, randomization bounds.
"""

import json
import os

from src import config


SETTINGS_PATH = os.path.join(config.APPDATA_DIR, "settings.json")

DEFAULTS = {
    "theme": "Dark",
    "macros_dir_override": "",
    "run_on_startup": False,
    "emergency_hotkey": config.EMERGENCY_HOTKEY,
    "start_recording_hotkey": "f9",
    "stop_recording_hotkey": "f10",
    "key_spammer_start_hotkey": "f7",
    "key_spammer_stop_hotkey": "f8",
    "mouse_clicker_start_hotkey": "f5",
    "mouse_clicker_stop_hotkey": "f6",
    "randomize_time_ms_min": config.RANDOMIZE_TIME_MS_MIN,
    "randomize_time_ms_max": config.RANDOMIZE_TIME_MS_MAX,
    "randomize_mouse_px_min": config.RANDOMIZE_MOUSE_PX_MIN,
    "randomize_mouse_px_max": config.RANDOMIZE_MOUSE_PX_MAX,
    "always_on_top": False,
    "antidetect_profile": "safe",
    "advanced_humanization_enabled": True,
    "humanization_intensity": 0,
    "input_mix_ratio": 0.85,
    "insert_nulls": False,
    "use_qpc_time": False,
    "obfuscate_process_name": False,
    "generic_window_title": "",
    "start_in_overlay_mode": False,
    "overlay_toggle_hotkey": "ctrl+alt+o",
    "overlay_opacity": 1.0,
    "overlay_click_through": False,
}

# Anti-detection profile presets (applied when profile changes to non-Custom)
PROFILE_PRESETS = {
    "safe": {"advanced_humanization_enabled": True, "humanization_intensity": 0, "insert_nulls": False, "use_qpc_time": False},
    "aggressive": {"advanced_humanization_enabled": True, "humanization_intensity": 2, "insert_nulls": True, "use_qpc_time": True},
    "stealth": {"advanced_humanization_enabled": True, "humanization_intensity": 4, "insert_nulls": True, "use_qpc_time": True},
    "custom": {},
}


def load_settings() -> dict:
    if not os.path.isfile(SETTINGS_PATH):
        return dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = dict(DEFAULTS)
        for k, v in data.items():
            if k in out:
                out[k] = v
        return out
    except Exception:
        return dict(DEFAULTS)


def save_settings(settings: dict) -> None:
    os.makedirs(config.APPDATA_DIR, exist_ok=True)
    to_save = {k: settings.get(k, DEFAULTS.get(k)) for k in DEFAULTS}
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(to_save, f, indent=2)
    if to_save.get("macros_dir_override"):
        config.set_macros_dir(to_save["macros_dir_override"])
    else:
        config.set_macros_dir(None)
    config.update_from_settings(to_save)
