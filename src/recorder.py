"""
Recording with high-resolution timestamps (time.perf_counter()).
Uses pynput for capture only. Output: list of event dicts with relative deltas.
Mouse movement stored as relative deltas (current pos - last pos).
Supports optional on_event callback for live UI display.
"""

import threading
import time
from typing import Callable

from pynput import keyboard, mouse

from src import config


class Recorder:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._start_time: float = 0.0
        self._keyboard_listener: keyboard.Listener | None = None
        self._mouse_listener: mouse.Listener | None = None
        self._last_mouse_pos: tuple[int, int] | None = None
        self._lock = threading.Lock()
        self._on_event_callback: Callable[[dict], None] | None = None

    def set_on_event_callback(self, cb: Callable[[dict], None] | None) -> None:
        self._on_event_callback = cb

    def _emit(self, ev: dict) -> None:
        if self._on_event_callback:
            try:
                self._on_event_callback(dict(ev))
            except Exception:
                pass

    def start(self) -> None:
        self._events = []
        self._start_time = time.perf_counter()
        self._last_mouse_pos = None

        def on_press(key: keyboard.Key | keyboard.KeyCode) -> None:
            t = time.perf_counter() - self._start_time
            key_name = self._key_to_name(key)
            if key_name is None:
                return
            with self._lock:
                ev = {"type": config.EVENT_KEY_DOWN, "t": t, "key": key_name}
                self._events.append(ev)
                self._emit(ev)

        def on_release(key: keyboard.Key | keyboard.KeyCode) -> None:
            t = time.perf_counter() - self._start_time
            key_name = self._key_to_name(key)
            if key_name is None:
                return
            with self._lock:
                ev = {"type": config.EVENT_KEY_UP, "t": t, "key": key_name}
                self._events.append(ev)
                self._emit(ev)

        def on_move(x: int, y: int) -> None:
            t = time.perf_counter() - self._start_time
            with self._lock:
                if self._last_mouse_pos is not None:
                    dx = x - self._last_mouse_pos[0]
                    dy = y - self._last_mouse_pos[1]
                    if dx != 0 or dy != 0:
                        ev = {"type": config.EVENT_MOUSE_MOVE, "t": t, "dx": dx, "dy": dy}
                        self._events.append(ev)
                        self._emit(ev)
                self._last_mouse_pos = (x, y)

        def on_click(x: int, y: int, button: mouse.Button, pressed: bool) -> None:
            t = time.perf_counter() - self._start_time
            btn_name = str(button)
            ev_type = config.EVENT_MOUSE_BUTTON_DOWN if pressed else config.EVENT_MOUSE_BUTTON_UP
            with self._lock:
                ev = {"type": ev_type, "t": t, "button": btn_name}
                self._events.append(ev)
                self._emit(ev)

        def on_scroll(x: int, y: int, dx: int, dy: int) -> None:
            t = time.perf_counter() - self._start_time
            with self._lock:
                ev = {"type": config.EVENT_MOUSE_SCROLL, "t": t, "dy": dy}
                self._events.append(ev)
                self._emit(ev)

        self._keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._mouse_listener = mouse.Listener(
            on_move=on_move,
            on_click=on_click,
            on_scroll=on_scroll,
        )
        self._keyboard_listener.start()
        self._mouse_listener.start()

    def _key_to_name(self, key: keyboard.Key | keyboard.KeyCode) -> str | None:
        if hasattr(key, "char") and key.char is not None:
            return key.char.lower() if isinstance(key.char, str) else None
        if hasattr(key, "name"):
            return key.name.lower() if key.name else None
        return None

    def stop(self) -> list[dict]:
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
            self._keyboard_listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
        with self._lock:
            return list(self._events)
