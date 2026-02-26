"""
Replaceable input backend: ctypes bindings to user32.dll SendInput.
Scan codes only (KEYEVENTF_SCANCODE). Mouse: relative deltas in 8-12 px packets.
Optional: 85/15 input mix, null SendInput, QueryPerformanceCounter time (Settings).
"""

import ctypes
from ctypes import wintypes

# --- Constants from Windows API ---
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

# Load user32 and kernel32 for QPC
user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
QueryPerformanceCounter = kernel32.QueryPerformanceCounter
QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_int64)]
QueryPerformanceCounter.restype = wintypes.BOOL

# --- Structures ---
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


# SendInput C signature: UINT SendInput(UINT nInputs, LPINPUT pInputs, int cbSize);
SendInput = user32.SendInput
SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
SendInput.restype = wintypes.UINT

# sizeof(INPUT) for cbSize
sizeof_INPUT = ctypes.sizeof(INPUT)

# Stealth: insert 1-2 null SendInput between real events (Settings)
_insert_nulls = False
_use_qpc = False
_mix_ratio = 1.0
_stealth_rng = __import__("random").Random()


def _get_time_field() -> int:
    if _use_qpc:
        t = ctypes.c_int64()
        if QueryPerformanceCounter(ctypes.byref(t)):
            val = t.value & 0xFFFFFFFF
            try:
                from src import humanization_report
                humanization_report.report_qpc_used(True, val)
            except Exception:
                pass
            return val
    return 0


def _maybe_insert_nulls() -> None:
    if not _insert_nulls:
        return
    count = _stealth_rng.randint(1, 2)
    try:
        from src import humanization_report
        humanization_report.report_insert_nulls(count)
    except Exception:
        pass
    for _ in range(count):
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = 0
        inp.union.mi.dy = 0
        inp.union.mi.mouseData = 0
        inp.union.mi.dwFlags = 0
        inp.union.mi.time = _get_time_field()
        inp.union.mi.dwExtraInfo = None
        SendInput(1, ctypes.byref(inp), sizeof_INPUT)


def set_stealth_options(insert_nulls: bool = False, use_qpc: bool = False, mix_ratio: float = 1.0) -> None:
    global _insert_nulls, _use_qpc, _mix_ratio
    _insert_nulls = insert_nulls
    _use_qpc = use_qpc
    _mix_ratio = max(0.0, min(1.0, mix_ratio))


def _get_scan_code_and_flags(sc: int) -> tuple[int, int]:
    """Return (wScan, dwFlags) for KEYBDINPUT. Extended keys have high byte 0xE0."""
    if sc > 0xFF:
        return (sc & 0xFF, KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY)
    return (sc, KEYEVENTF_SCANCODE)


def _use_extended_or_normal(sc: int) -> tuple[int, int]:
    """85% scan-code only; 15% force extended or mix (per Settings mix_ratio)."""
    w_scan, flags = _get_scan_code_and_flags(sc)
    if _mix_ratio >= 1.0 or _stealth_rng.random() < _mix_ratio:
        return (w_scan, flags)
    if _stealth_rng.random() < 0.5 and sc <= 0xFF:
        return (w_scan, flags | KEYEVENTF_EXTENDEDKEY)
    return (w_scan, flags)


def key_down(sc: int) -> bool:
    """Send key down for scan code sc. Returns True if SendInput succeeded."""
    _maybe_insert_nulls()
    w_scan, flags = _use_extended_or_normal(sc)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = w_scan
    inp.union.ki.dwFlags = flags
    inp.union.ki.time = _get_time_field()
    inp.union.ki.dwExtraInfo = None
    return SendInput(1, ctypes.byref(inp), sizeof_INPUT) == 1


def key_up(sc: int) -> bool:
    """Send key up for scan code sc."""
    _maybe_insert_nulls()
    w_scan, flags = _use_extended_or_normal(sc)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = w_scan
    inp.union.ki.dwFlags = flags | KEYEVENTF_KEYUP
    inp.union.ki.time = _get_time_field()
    inp.union.ki.dwExtraInfo = None
    return SendInput(1, ctypes.byref(inp), sizeof_INPUT) == 1


def key_press(sc: int) -> bool:
    """Key down then key up."""
    return key_down(sc) and key_up(sc)


def mouse_move_relative(dx: int, dy: int) -> bool:
    """Send one relative mouse move. Caller should chunk large deltas into 8-12 px packets."""
    _maybe_insert_nulls()
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = dx
    inp.union.mi.dy = dy
    inp.union.mi.mouseData = 0
    inp.union.mi.dwFlags = MOUSEEVENTF_MOVE
    inp.union.mi.time = _get_time_field()
    inp.union.mi.dwExtraInfo = None
    return SendInput(1, ctypes.byref(inp), sizeof_INPUT) == 1


def send_mouse_move(dx: int, dy: int) -> bool:
    """Alias for one relative move (used by natural path player)."""
    return mouse_move_relative(dx, dy)


def mouse_move_relative_chunked(dx: int, dy: int, max_step: int = 12) -> bool:
    """Split dx, dy into packets of at most max_step pixels (8-12). Returns True if all sent."""
    while dx != 0 or dy != 0:
        step_x = max(-max_step, min(max_step, dx)) if dx else 0
        step_y = max(-max_step, min(max_step, dy)) if dy else 0
        if step_x == 0 and step_y == 0:
            if dx != 0:
                step_x = 1 if dx > 0 else -1
            if dy != 0:
                step_y = 1 if dy > 0 else -1
        if not mouse_move_relative(step_x, step_y):
            return False
        dx -= step_x
        dy -= step_y
    return True


def mouse_button_down(flags: int) -> bool:
    """flags: MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_RIGHTDOWN, or MOUSEEVENTF_MIDDLEDOWN."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = 0
    inp.union.mi.dy = 0
    inp.union.mi.mouseData = 0
    inp.union.mi.dwFlags = flags
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = None
    return SendInput(1, ctypes.byref(inp), sizeof_INPUT) == 1


def mouse_button_up(flags: int) -> bool:
    """flags: MOUSEEVENTF_LEFTUP, MOUSEEVENTF_RIGHTUP, or MOUSEEVENTF_MIDDLEUP."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = 0
    inp.union.mi.dy = 0
    inp.union.mi.mouseData = 0
    inp.union.mi.dwFlags = flags
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = None
    return SendInput(1, ctypes.byref(inp), sizeof_INPUT) == 1


def mouse_scroll(delta: int) -> bool:
    """delta: positive = wheel up, negative = wheel down. WHEEL_DELTA is 120."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = 0
    inp.union.mi.dy = 0
    inp.union.mi.mouseData = delta
    inp.union.mi.dwFlags = MOUSEEVENTF_WHEEL
    inp.union.mi.time = _get_time_field()
    inp.union.mi.dwExtraInfo = None
    return SendInput(1, ctypes.byref(inp), sizeof_INPUT) == 1


def release_all_keys() -> None:
    """Release any held keys (scan codes we might have pressed). Call on emergency stop / exit."""
    from src import config
    for _sc in config.SCAN_CODES.values():
        key_up(_sc)
