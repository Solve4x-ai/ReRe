"""
Thread-safe playback controller: state machine and concurrency control.
States: IDLE, RECORDING, PLAYING, PAUSED.
Key spammer and mouse clicker run in separate threads; emergency stop stops all.
"""

import threading
import time
from typing import Callable

from src import config
from src import input_backend
from src.recorder import Recorder
from src.player import Player
from src import utils


class State:
    IDLE = "idle"
    RECORDING = "recording"
    PLAYING = "playing"
    PAUSED = "paused"


# Mouse flags for clicker (left/right down and up)
_LEFT_DOWN = 0x0002
_LEFT_UP = 0x0004
_RIGHT_DOWN = 0x0008
_RIGHT_UP = 0x0010


class PlaybackController:
    def __init__(self, on_state_change: Callable[[str], None] | None = None):
        self._state = State.IDLE
        self._state_lock = threading.RLock()
        self._on_state_change = on_state_change or (lambda _: None)

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._recorder = Recorder()
        self._player: Player | None = None
        self._player_thread: threading.Thread | None = None
        self._recorded_events: list[dict] = []

        self._key_spam_stop = threading.Event()
        self._key_spam_thread: threading.Thread | None = None
        self._mouse_clicker_stop = threading.Event()
        self._mouse_clicker_thread: threading.Thread | None = None
        self._live_event_callback: Callable[[dict], None] | None = None
        self._last_key_interval_ms: float | None = None
        self._last_mouse_interval_ms: float | None = None

    def get_state(self) -> str:
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: str) -> None:
        with self._state_lock:
            if self._state != new_state:
                self._state = new_state
                self._on_state_change(new_state)

    def set_live_event_callback(self, cb: Callable[[dict], None] | None) -> None:
        self._live_event_callback = cb

    def start_recording(self, on_event_callback: Callable[[dict], None] | None = None) -> None:
        with self._state_lock:
            if self._state != State.IDLE:
                return
            self._set_state(State.RECORDING)
        self._recorder.set_on_event_callback(on_event_callback or self._live_event_callback)
        self._recorder.start()

    def stop_recording(self) -> list[dict]:
        with self._state_lock:
            if self._state != State.RECORDING:
                return []
        events = self._recorder.stop()
        self._recorded_events = events
        self._set_state(State.IDLE)
        return events

    def start_playback(
        self,
        events: list[dict] | None = None,
        speed: float = 1.0,
        randomize: bool = False,
    ) -> None:
        to_play = events if events is not None else self._recorded_events
        if not to_play:
            return
        with self._state_lock:
            if self._state != State.IDLE:
                return
            self._stop_event.clear()
            self._pause_event.clear()
            self._set_state(State.PLAYING)
        self._player = Player(to_play, speed=speed, randomize=randomize)
        self._player_thread = threading.Thread(
            target=self._run_playback,
            daemon=True,
        )
        self._player_thread.start()

    def _run_playback(self) -> None:
        assert self._player is not None
        try:
            self._player.play(stop_event=self._stop_event, pause_event=self._pause_event)
        finally:
            self._set_state(State.IDLE)
            self._player_thread = None
            self._player = None

    def pause(self) -> None:
        with self._state_lock:
            if self._state != State.PLAYING:
                return
            self._set_state(State.PAUSED)
        self._pause_event.set()

    def resume(self) -> None:
        with self._state_lock:
            if self._state != State.PAUSED:
                return
            self._set_state(State.PLAYING)
        self._pause_event.clear()

    def stop_playback(self) -> None:
        self._stop_event.set()
        if self._player_thread is not None and self._player_thread.is_alive():
            self._player_thread.join(timeout=2.0)
        with self._state_lock:
            if self._state in (State.PLAYING, State.PAUSED):
                self._set_state(State.IDLE)

    def emergency_stop(self) -> None:
        self.stop_key_spammer()
        self.stop_mouse_clicker()
        current = self.get_state()
        if current == State.RECORDING:
            self.stop_recording()
        elif current in (State.PLAYING, State.PAUSED):
            self.stop_playback()
        try:
            from src import input_backend
            input_backend.release_all_keys()
        except Exception:
            pass

    def start_key_spammer(
        self,
        key_name: str,
        tap_not_hold: bool,
        interval_ms: int,
        count: int | None,
        randomize: bool = False,
    ) -> None:
        sc = config.SCAN_CODES.get(key_name.lower().strip())
        if sc is None:
            return
        self._key_spam_stop.clear()
        self._key_spam_thread = threading.Thread(
            target=self._run_key_spammer,
            args=(sc, tap_not_hold, interval_ms, count, randomize),
            daemon=True,
        )
        self._key_spam_thread.start()

    def _run_key_spammer(
        self,
        sc: int,
        tap_not_hold: bool,
        interval_ms: int,
        count: int | None,
        randomize: bool,
    ) -> None:
        if tap_not_hold:
            n = 0
            while not self._key_spam_stop.is_set():
                if count is not None and n >= count:
                    break
                input_backend.key_down(sc)
                input_backend.key_up(sc)
                n += 1
                jitter = utils.randomize_time_ms() if randomize else 0
                actual_ms = interval_ms + jitter
                self._last_key_interval_ms = actual_ms
                delay_sec = max(0.001, actual_ms / 1000.0)
                end = time.perf_counter() + delay_sec
                while time.perf_counter() < end and not self._key_spam_stop.is_set():
                    time.sleep(0.001)
        else:
            input_backend.key_down(sc)
            try:
                while not self._key_spam_stop.is_set():
                    time.sleep(0.05)
            finally:
                input_backend.key_up(sc)
        self._key_spam_thread = None

    def stop_key_spammer(self) -> None:
        self._key_spam_stop.set()
        if self._key_spam_thread is not None and self._key_spam_thread.is_alive():
            self._key_spam_thread.join(timeout=1.0)
        self._key_spam_thread = None
        self._key_spam_stop.clear()
        self._last_key_interval_ms = None

    def get_last_key_interval_ms(self) -> float | None:
        return self._last_key_interval_ms

    def is_key_spammer_running(self) -> bool:
        return self._key_spam_thread is not None and self._key_spam_thread.is_alive()

    def start_mouse_clicker(
        self,
        left_not_right: bool,
        interval_ms: int,
        count: int | None,
        randomize: bool = False,
    ) -> None:
        self._mouse_clicker_stop.clear()
        down = _LEFT_DOWN if left_not_right else _RIGHT_DOWN
        up = _LEFT_UP if left_not_right else _RIGHT_UP
        self._mouse_clicker_thread = threading.Thread(
            target=self._run_mouse_clicker,
            args=(down, up, interval_ms, count, randomize),
            daemon=True,
        )
        self._mouse_clicker_thread.start()

    def _run_mouse_clicker(
        self,
        down_flag: int,
        up_flag: int,
        interval_ms: int,
        count: int | None,
        randomize: bool,
    ) -> None:
        n = 0
        while not self._mouse_clicker_stop.is_set():
            if count is not None and n >= count:
                break
            input_backend.mouse_button_down(down_flag)
            input_backend.mouse_button_up(up_flag)
            n += 1
            jitter = utils.randomize_time_ms() if randomize else 0
            actual_ms = interval_ms + jitter
            self._last_mouse_interval_ms = actual_ms
            delay_sec = max(0.001, actual_ms / 1000.0)
            end = time.perf_counter() + delay_sec
            while time.perf_counter() < end and not self._mouse_clicker_stop.is_set():
                time.sleep(0.001)
        self._mouse_clicker_thread = None

    def stop_mouse_clicker(self) -> None:
        self._mouse_clicker_stop.set()
        if self._mouse_clicker_thread is not None and self._mouse_clicker_thread.is_alive():
            self._mouse_clicker_thread.join(timeout=1.0)
        self._mouse_clicker_thread = None
        self._mouse_clicker_stop.clear()
        self._last_mouse_interval_ms = None

    def get_last_mouse_interval_ms(self) -> float | None:
        return self._last_mouse_interval_ms

    def is_mouse_clicker_running(self) -> bool:
        return self._mouse_clicker_thread is not None and self._mouse_clicker_thread.is_alive()

    def get_recorded_events(self) -> list[dict]:
        return list(self._recorded_events)

    def set_recorded_events(self, events: list[dict]) -> None:
        self._recorded_events = list(events)
