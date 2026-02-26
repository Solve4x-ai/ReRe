"""
Randomization and humanization: HumanizationEngine plus hotkey registration.
Deterministic at 1.0x with humanization toggle OFF (no engine used).
"""

import math
import random
import time
from typing import Callable

from src import config


# --- HumanizationEngine: Gaussian jitter, key hold, drift, micro-pauses ---

class HumanizationEngine:
    """Seeded per macro load when humanization on; deterministic replay at 1.0x with toggle off."""

    def __init__(self, seed: int | None = None, intensity_scale: float = 1.0) -> None:
        self._rng = random.Random(seed)
        self._intensity = max(0.0, min(2.0, intensity_scale))
        self._event_count = 0
        self._session_start = time.perf_counter()
        self._drift_phase = self._rng.random() * 2 * math.pi

    def _scale(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self._intensity

    def delay_jitter_ms(self) -> float:
        """Gaussian-like jitter ±3–18 ms (configurable), mean 0."""
        lo = self._scale(config.HUMANIZATION_GAUSSIAN_MS_LO, config.HUMANIZATION_GAUSSIAN_MS_HI * 0.5)
        hi = self._scale(config.HUMANIZATION_GAUSSIAN_MS_HI * 0.5, config.HUMANIZATION_GAUSSIAN_MS_HI)
        sigma = (lo + hi) / 4.0
        j = self._rng.gauss(0, sigma)
        return max(-hi, min(hi, j))

    def key_hold_ms(self) -> float:
        """Variable key hold 50–180 ms random per press."""
        lo = config.HUMANIZATION_KEY_HOLD_MS_LO
        hi = config.HUMANIZATION_KEY_HOLD_MS_HI
        return self._rng.uniform(lo, hi) * self._intensity * 0.5 + (1 - self._intensity * 0.5) * (lo + hi) / 2

    def drift_factor(self) -> float:
        """Session-wide drift ±4% over 5–30 min. Returns multiplier ~0.96–1.04."""
        period = self._rng.uniform(
            config.HUMANIZATION_DRIFT_PERIOD_MIN,
            config.HUMANIZATION_DRIFT_PERIOD_MAX,
        )
        elapsed = time.perf_counter() - self._session_start
        phase = self._drift_phase + 2 * math.pi * elapsed / period
        return 1.0 + config.HUMANIZATION_DRIFT_PCT * math.sin(phase) * self._intensity

    def should_micro_pause(self) -> bool:
        """Occasional micro-pause every 8–25 events with prob 3–7%."""
        self._event_count += 1
        every = self._rng.randint(
            config.HUMANIZATION_MICRO_PAUSE_EVERY_LO,
            config.HUMANIZATION_MICRO_PAUSE_EVERY_HI,
        )
        if self._event_count % every != 0:
            return False
        prob = self._scale(
            config.HUMANIZATION_MICRO_PAUSE_PROB_LO,
            config.HUMANIZATION_MICRO_PAUSE_PROB_HI,
        )
        return self._rng.random() < prob

    def micro_pause_ms(self) -> float:
        """Duration of micro-pause 150–450 ms."""
        return self._rng.uniform(
            config.HUMANIZATION_MICRO_PAUSE_MS_LO,
            config.HUMANIZATION_MICRO_PAUSE_MS_HI,
        )

    def randomize_time_ms(self) -> float:
        """Jitter for delay (uses engine when advanced humanization on)."""
        return self.delay_jitter_ms()

    def randomize_mouse_px(self) -> int:
        """Mouse pixel noise (uses config range, scaled by intensity)."""
        lo = config.get_randomize_mouse_px_min()
        hi = config.get_randomize_mouse_px_max()
        px = self._rng.randint(lo, hi)
        return px if self._rng.random() < 0.5 else -px


# --- Legacy module-level API: use config/simple RNG when engine not used ---

def randomize_time_ms() -> float:
    """Return random jitter in ms. Uses HumanizationEngine when advanced humanization on and seed set; else config."""
    if config.get_advanced_humanization_enabled() and _global_engine is not None:
        return _global_engine.randomize_time_ms()
    lo = max(0.5, config.get_randomize_time_ms_min())
    hi = max(lo, config.get_randomize_time_ms_max())
    ms = random.uniform(lo, hi)
    return ms if random.random() < 0.5 else -ms


def randomize_mouse_px() -> int:
    """Return random pixel noise. Uses HumanizationEngine when set; else config."""
    if _global_engine is not None:
        return _global_engine.randomize_mouse_px()
    lo = config.get_randomize_mouse_px_min()
    hi = config.get_randomize_mouse_px_max()
    px = random.randint(lo, hi)
    return px if random.random() < 0.5 else -px


_global_engine: HumanizationEngine | None = None


def set_humanization_engine(engine: HumanizationEngine | None) -> None:
    global _global_engine
    _global_engine = engine


def get_humanization_engine() -> HumanizationEngine | None:
    return _global_engine


def register_emergency_hotkey(hotkey: str | None, callback: Callable[[], None]) -> object:
    """Register global hotkey for emergency stop (exits app). Returns hook; call .unhook() to remove."""
    key = (hotkey or config.EMERGENCY_HOTKEY).strip().lower()
    try:
        import keyboard as kb
        return kb.add_hotkey(key, callback)
    except Exception:
        return None


def unregister_hotkey(hook: object) -> None:
    if hook is not None and hasattr(hook, "unhook"):
        try:
            hook.unhook()
        except Exception:
            pass


def register_recording_hotkeys(
    start_hotkey: str,
    stop_hotkey: str,
    on_start: Callable[[], None],
    on_stop: Callable[[], None],
) -> tuple[object | None, object | None]:
    """Register start/stop recording hotkeys. Returns (start_hook, stop_hook)."""
    try:
        import keyboard as kb
        h1 = kb.add_hotkey(start_hotkey, on_start)
        h2 = kb.add_hotkey(stop_hotkey, on_stop)
        return (h1, h2)
    except Exception:
        return (None, None)


def unregister_recording_hotkeys(hooks: tuple[object | None, object | None]) -> None:
    for h in hooks:
        unregister_hotkey(h)


def register_key_spammer_hotkeys(
    start_hotkey: str,
    stop_hotkey: str,
    on_start: Callable[[], None],
    on_stop: Callable[[], None],
) -> tuple[object | None, object | None]:
    """Register start/stop key spammer hotkeys. Returns (start_hook, stop_hook)."""
    try:
        import keyboard as kb
        h1 = kb.add_hotkey(start_hotkey, on_start)
        h2 = kb.add_hotkey(stop_hotkey, on_stop)
        return (h1, h2)
    except Exception:
        return (None, None)


def register_mouse_clicker_hotkeys(
    start_hotkey: str,
    stop_hotkey: str,
    on_start: Callable[[], None],
    on_stop: Callable[[], None],
) -> tuple[object | None, object | None]:
    """Register start/stop mouse clicker hotkeys. Returns (start_hook, stop_hook)."""
    try:
        import keyboard as kb
        h1 = kb.add_hotkey(start_hotkey, on_start)
        h2 = kb.add_hotkey(stop_hotkey, on_stop)
        return (h1, h2)
    except Exception:
        return (None, None)


def get_foreground_hwnd() -> int | None:
    """Return foreground window HWND or None. Requires pywin32."""
    try:
        import win32gui
        return win32gui.GetForegroundWindow()
    except Exception:
        return None


def is_game_foreground(saved_hwnd: int | None) -> bool:
    """True if foreground window matches saved_hwnd (or any if saved_hwnd is None)."""
    fg = get_foreground_hwnd()
    if fg is None:
        return True
    if saved_hwnd is None:
        return True
    return fg == saved_hwnd
