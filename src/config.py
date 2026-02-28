"""
Constants and scan-code map for ReRe.
Scan codes only (never VK_ codes). Windows Set 1 make codes for SendInput KEYEVENTF_SCANCODE.
"""

import os

# --- Application ---
APP_NAME = "ReRe"
APP_VERSION = "1.1.0"

# --- Storage ---
APPDATA_DIR = os.path.join(os.getenv("APPDATA", ""), "ReRe")
MACROS_DIR = os.path.join(APPDATA_DIR, "macros")
_macros_dir_override: str | None = None


def get_macros_dir() -> str:
    return _macros_dir_override if _macros_dir_override else MACROS_DIR


def set_macros_dir(path: str | None) -> None:
    global _macros_dir_override
    _macros_dir_override = path or None

# --- Playback ---
PLAYBACK_SPEED_MIN = 0.5
PLAYBACK_SPEED_MAX = 3.0
PLAYBACK_SPEED_DEFAULT = 1.0

# --- Randomization (when toggle enabled); overridden by settings ---
RANDOMIZE_TIME_MS_MIN = 5
RANDOMIZE_TIME_MS_MAX = 15
RANDOMIZE_MOUSE_PX_MIN = 1
RANDOMIZE_MOUSE_PX_MAX = 4
_rand_time_ms_min = RANDOMIZE_TIME_MS_MIN
_rand_time_ms_max = RANDOMIZE_TIME_MS_MAX
_rand_px_min = RANDOMIZE_MOUSE_PX_MIN
_rand_px_max = RANDOMIZE_MOUSE_PX_MAX


def get_randomize_time_ms_min() -> float:
    return _rand_time_ms_min


def get_randomize_time_ms_max() -> float:
    return _rand_time_ms_max


def get_randomize_mouse_px_min() -> int:
    return _rand_px_min


def get_randomize_mouse_px_max() -> int:
    return _rand_px_max


_humanization_intensity = 0  # 0=off, 1=low, 2=medium, 3=high, 4=paranoid
_advanced_humanization_enabled = True
_input_mix_ratio = 1.0
_insert_nulls = False
_use_qpc_time = False


def get_humanization_intensity() -> int:
    return _humanization_intensity


def get_advanced_humanization_enabled() -> bool:
    return _advanced_humanization_enabled


def get_input_mix_ratio() -> float:
    return _input_mix_ratio


def get_insert_nulls() -> bool:
    return _insert_nulls


def get_use_qpc_time() -> bool:
    return _use_qpc_time


def update_from_settings(settings: dict) -> None:
    global _rand_time_ms_min, _rand_time_ms_max, _rand_px_min, _rand_px_max
    global _humanization_intensity, _advanced_humanization_enabled, _input_mix_ratio, _insert_nulls, _use_qpc_time
    _rand_time_ms_min = int(settings.get("randomize_time_ms_min", RANDOMIZE_TIME_MS_MIN))
    _rand_time_ms_max = int(settings.get("randomize_time_ms_max", RANDOMIZE_TIME_MS_MAX))
    _rand_px_min = int(settings.get("randomize_mouse_px_min", RANDOMIZE_MOUSE_PX_MIN))
    _rand_px_max = int(settings.get("randomize_mouse_px_max", RANDOMIZE_MOUSE_PX_MAX))
    _humanization_intensity = int(settings.get("humanization_intensity", 0))
    _advanced_humanization_enabled = bool(settings.get("advanced_humanization_enabled", True))
    _input_mix_ratio = float(settings.get("input_mix_ratio", 0.85))
    _insert_nulls = bool(settings.get("insert_nulls", False))
    _use_qpc_time = bool(settings.get("use_qpc_time", False))


# --- Emergency stop ---
EMERGENCY_HOTKEY = "ctrl+shift+f12"

# --- Quick Actions: interval up to 10 minutes ---
KEY_SPAM_INTERVAL_MS_MIN = 50
KEY_SPAM_INTERVAL_MS_MAX = 600_000
KEY_SPAM_INTERVAL_MS_DEFAULT = 200
KEY_SPAM_COUNT_MIN = 10
KEY_SPAM_COUNT_MAX = 9999
MOUSE_CLICK_INTERVAL_MS_MIN = 50
MOUSE_CLICK_INTERVAL_MS_MAX = 600_000
MOUSE_CLICK_INTERVAL_MS_DEFAULT = 200

# --- Input backend ---
MOUSE_DELTA_PACKET_MAX = 12  # max px per relative move packet (8-12)
MOUSE_DELTA_PACKET_MIN = 8

# --- Humanization / anti-detection (overridden by settings) ---
HUMANIZATION_GAUSSIAN_MS_LO = 3
HUMANIZATION_GAUSSIAN_MS_HI = 18
HUMANIZATION_KEY_HOLD_MS_LO = 50
HUMANIZATION_KEY_HOLD_MS_HI = 180
HUMANIZATION_DRIFT_PCT = 0.04
HUMANIZATION_DRIFT_PERIOD_MIN = 5 * 60.0
HUMANIZATION_DRIFT_PERIOD_MAX = 30 * 60.0
HUMANIZATION_MICRO_PAUSE_MS_LO = 150
HUMANIZATION_MICRO_PAUSE_MS_HI = 450
HUMANIZATION_MICRO_PAUSE_EVERY_LO = 8
HUMANIZATION_MICRO_PAUSE_EVERY_HI = 25
HUMANIZATION_MICRO_PAUSE_PROB_LO = 0.03
HUMANIZATION_MICRO_PAUSE_PROB_HI = 0.07
INPUT_MIX_SCANCODE_RATIO = 0.85
MOUSEEVENTF_ABSOLUTE = 0x8000

# --- Event types (for serialization) ---
EVENT_KEY_DOWN = "key_down"
EVENT_KEY_UP = "key_up"
EVENT_MOUSE_MOVE = "mouse_move"
EVENT_MOUSE_BUTTON_DOWN = "mouse_down"
EVENT_MOUSE_BUTTON_UP = "mouse_up"
EVENT_MOUSE_SCROLL = "mouse_scroll"

# --- Scan code dictionary (key name -> scan code, Set 1 make codes) ---
# Letters A-Z: 0x1E-0x2C (A-L), 0x2C-0x32 (Z-M), 0x10-0x1C (Q-P)
# Numbers 1-0: 0x02-0x0B
# Function keys F1-F12: 0x3B-0x44
# Special keys: Escape, Tab, Enter, Space, etc.
SCAN_CODES = {
    "escape": 0x01,
    "1": 0x02,
    "2": 0x03,
    "3": 0x04,
    "4": 0x05,
    "5": 0x06,
    "6": 0x07,
    "7": 0x08,
    "8": 0x09,
    "9": 0x0A,
    "0": 0x0B,
    "-": 0x0C,
    "=": 0x0D,
    "backspace": 0x0E,
    "tab": 0x0F,
    "q": 0x10,
    "w": 0x11,
    "e": 0x12,
    "r": 0x13,
    "t": 0x14,
    "y": 0x15,
    "u": 0x16,
    "i": 0x17,
    "o": 0x18,
    "p": 0x19,
    "[": 0x1A,
    "]": 0x1B,
    "enter": 0x1C,
    "ctrl": 0x1D,
    "a": 0x1E,
    "s": 0x1F,
    "d": 0x20,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "j": 0x24,
    "k": 0x25,
    "l": 0x26,
    ";": 0x27,
    "'": 0x28,
    "`": 0x29,
    "shift": 0x2A,
    "\\": 0x2B,
    "z": 0x2C,
    "x": 0x2D,
    "c": 0x2E,
    "v": 0x2F,
    "b": 0x30,
    "n": 0x31,
    "m": 0x32,
    ",": 0x33,
    ".": 0x34,
    "/": 0x35,
    "right_shift": 0x36,
    "num*": 0x37,
    "alt": 0x38,
    "space": 0x39,
    "caps_lock": 0x3A,
    "f1": 0x3B,
    "f2": 0x3C,
    "f3": 0x3D,
    "f4": 0x3E,
    "f5": 0x3F,
    "f6": 0x40,
    "f7": 0x41,
    "f8": 0x42,
    "f9": 0x43,
    "f10": 0x44,
    "num_lock": 0x45,
    "scroll_lock": 0x46,
    "num7": 0x47,
    "num8": 0x48,
    "num9": 0x49,
    "num-": 0x4A,
    "num4": 0x4B,
    "num5": 0x4C,
    "num6": 0x4D,
    "num+": 0x4E,
    "num1": 0x4F,
    "num2": 0x50,
    "num3": 0x51,
    "num0": 0x52,
    "num.": 0x53,
    "f11": 0x57,
    "f12": 0x58,
    "right_control": 0xE01D,
    "right_alt": 0xE038,
    "home": 0xE047,
    "up": 0xE048,
    "page_up": 0xE049,
    "left": 0xE04B,
    "right": 0xE04D,
    "end": 0xE04F,
    "down": 0xE050,
    "page_down": 0xE051,
    "insert": 0xE052,
    "delete": 0xE053,
    "num_enter": 0xE01C,
    "num/": 0xE035,
}

# Mouse button names to SendInput flags (for playback we use MOUSEINPUT.dwFlags)
# Left=0x0001, Right=0x0002, Middle=0x0004
MOUSE_BUTTON_FLAGS_DOWN = {
    "Button.left": 0x0002,    # MOUSEEVENTF_LEFTDOWN
    "Button.right": 0x0008,   # MOUSEEVENTF_RIGHTDOWN
    "Button.middle": 0x0020,   # MOUSEEVENTF_MIDDLEDOWN
}

MOUSE_BUTTON_FLAGS_UP = {
    "Button.left": 0x0004,    # MOUSEEVENTF_LEFTUP
    "Button.right": 0x0010,   # MOUSEEVENTF_RIGHTUP
    "Button.middle": 0x0040,   # MOUSEEVENTF_MIDDLEUP
}

# Pynput key names that differ from our SCAN_CODES keys
PYNPUT_KEY_ALIASES = {
    "ctrl_l": "ctrl",
    "ctrl_r": "right_control",
    "shift_l": "shift",
    "shift_r": "right_shift",
    "alt_l": "alt",
    "alt_r": "right_alt",
    "cmd": "ctrl",
    "cmd_l": "ctrl",
    "cmd_r": "right_control",
}
