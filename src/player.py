"""
Deterministic playback engine. Uses input_backend only.
At 1.0x with humanization OFF: identical replay. With humanization: HumanizationEngine + natural mouse path.
"""

import math
import time

from src import config
from src import input_backend
from src import utils


def _ease_in_out(t: float) -> float:
    """Smooth acceleration/deceleration."""
    if t <= 0 or t >= 1:
        return t
    return t * t * (3.0 - 2.0 * t)


def _catmull_rom(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    """Catmull-Rom spline segment."""
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3
    )


def _natural_mouse_path(
    dx: int, dy: int,
    num_control: int,
    max_step: int,
    rng: object,
    add_micro_corrections: bool = True,
) -> list[tuple[int, int]]:
    """Convert linear (dx,dy) into 4-8 control point curve; ease in/out; 1-3 micro-corrections; return list of (dx,dy) packets (max max_step)."""
    if dx == 0 and dy == 0:
        return []
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1:
        return [(dx, dy)]
    n = max(4, min(8, num_control))
    # Control points along the line with slight perpendicular noise
    ctrl_x = [0.0]
    ctrl_y = [0.0]
    for i in range(1, n):
        t = i / (n - 1)
        # Slight perpendicular offset for curve
        perp_x = -dy / length if length else 0
        perp_y = dx / length if length else 0
        noise = (rng.uniform(-2, 2) if add_micro_corrections and i < n - 1 else 0) * (length / 50.0 + 1)
        ctrl_x.append(dx * t + perp_x * noise)
        ctrl_y.append(dy * t + perp_y * noise)
    ctrl_x.append(float(dx))
    ctrl_y.append(float(dy))
    # Sample with ease in/out; num samples scales with length
    num_samples = max(4, int(length / 4) + 1)
    points: list[tuple[float, float]] = []
    for i in range(num_samples + 1):
        t_raw = i / num_samples
        t_ease = _ease_in_out(t_raw)
        seg = t_ease * (n - 1)
        idx = min(int(seg), n - 2)
        u = seg - idx
        p0x = ctrl_x[max(0, idx - 1)]
        p1x, p2x = ctrl_x[idx], ctrl_x[idx + 1]
        p3x = ctrl_x[min(n - 1, idx + 2)]
        p0y = ctrl_y[max(0, idx - 1)]
        p1y, p2y = ctrl_y[idx], ctrl_y[idx + 1]
        p3y = ctrl_y[min(n - 1, idx + 2)]
        x = _catmull_rom(p0x, p1x, p2x, p3x, u)
        y = _catmull_rom(p0y, p1y, p2y, p3y, u)
        points.append((x, y))
    # Convert to delta segments (max max_step)
    out: list[tuple[int, int]] = []
    px, py = 0.0, 0.0
    for (x, y) in points:
        dx_seg = int(round(x - px))
        dy_seg = int(round(y - py))
        px, py = x, y
        if dx_seg == 0 and dy_seg == 0:
            continue
        # Chunk into max_step packets
        while dx_seg != 0 or dy_seg != 0:
            step_x = max(-max_step, min(max_step, dx_seg)) if dx_seg else 0
            step_y = max(-max_step, min(max_step, dy_seg)) if dy_seg else 0
            if step_x == 0 and step_y == 0:
                step_x = 1 if dx_seg > 0 else (-1 if dx_seg < 0 else 0)
                step_y = 1 if dy_seg > 0 else (-1 if dy_seg < 0 else 0)
            out.append((step_x, step_y))
            dx_seg -= step_x
            dy_seg -= step_y
    return out


class Player:
    def __init__(
        self,
        events: list[dict],
        speed: float = 1.0,
        randomize: bool = False,
    ) -> None:
        self._events = list(events)
        self._speed = max(config.PLAYBACK_SPEED_MIN, min(config.PLAYBACK_SPEED_MAX, speed))
        self._randomize = randomize
        seed = hash(tuple(id(e) for e in events[:32])) % (2**32) if events else 0
        intensity = config.get_humanization_intensity()
        intensity_scale = [0.0, 0.4, 0.7, 1.0, 1.5][max(0, min(4, intensity))]
        self._engine = utils.HumanizationEngine(seed=seed, intensity_scale=intensity_scale) if randomize and config.get_advanced_humanization_enabled() else None
        if self._engine:
            utils.set_humanization_engine(self._engine)
        else:
            utils.set_humanization_engine(None)

    def play(
        self,
        stop_event: object | None = None,
        pause_event: object | None = None,
    ) -> None:
        if not self._events:
            return
        stop = stop_event
        pause = pause_event
        last_t = 0.0
        for ev in self._events:
            if stop is not None and getattr(stop, "is_set", lambda: False)():
                break
            while pause is not None and getattr(pause, "is_set", lambda: False)():
                time.sleep(0.02)
                if stop is not None and getattr(stop, "is_set", lambda: False)():
                    return
            t = ev.get("t", 0.0)
            delay = t - last_t
            if delay > 0:
                if self._randomize and self._engine:
                    delay += self._engine.delay_jitter_ms() / 1000.0
                    delay *= self._engine.drift_factor()
                elif self._randomize:
                    delay += utils.randomize_time_ms() / 1000.0
                delay /= self._speed
                end_sleep = time.perf_counter() + delay
                while time.perf_counter() < end_sleep:
                    if stop is not None and getattr(stop, "is_set", lambda: False)():
                        return
                    while pause is not None and getattr(pause, "is_set", lambda: False)():
                        time.sleep(0.02)
                        if stop is not None and getattr(stop, "is_set", lambda: False)():
                            return
                    time.sleep(0.001)
                if self._randomize and self._engine and self._engine.should_micro_pause():
                    pause_ms = self._engine.micro_pause_ms() / 1000.0 / self._speed
                    time.sleep(max(0, pause_ms))
            last_t = t
            self._dispatch(ev)
        utils.set_humanization_engine(None)

    def _dispatch(self, ev: dict) -> None:
        ev_type = ev.get("type", "")
        if ev_type == config.EVENT_KEY_DOWN:
            sc = self._key_to_scan_code(ev.get("key"))
            if sc is not None:
                input_backend.key_down(sc)
        elif ev_type == config.EVENT_KEY_UP:
            sc = self._key_to_scan_code(ev.get("key"))
            if sc is not None:
                input_backend.key_up(sc)
        elif ev_type == config.EVENT_MOUSE_MOVE:
            dx = ev.get("dx", 0)
            dy = ev.get("dy", 0)
            if self._randomize and self._engine:
                dx += self._engine.randomize_mouse_px()
                dy += self._engine.randomize_mouse_px()
            elif self._randomize:
                dx += utils.randomize_mouse_px()
                dy += utils.randomize_mouse_px()
            if config.get_advanced_humanization_enabled() and self._randomize and self._engine:
                rng = self._engine._rng
                path = _natural_mouse_path(dx, dy, num_control=4 + rng.randint(0, 4), max_step=config.MOUSE_DELTA_PACKET_MAX, rng=rng)
                for sx, sy in path:
                    input_backend.send_mouse_move(sx, sy)
            else:
                input_backend.mouse_move_relative_chunked(dx, dy, max_step=config.MOUSE_DELTA_PACKET_MAX)
        elif ev_type == config.EVENT_MOUSE_BUTTON_DOWN:
            flags = config.MOUSE_BUTTON_FLAGS_DOWN.get(ev.get("button"))
            if flags is not None:
                input_backend.mouse_button_down(flags)
        elif ev_type == config.EVENT_MOUSE_BUTTON_UP:
            flags = config.MOUSE_BUTTON_FLAGS_UP.get(ev.get("button"))
            if flags is not None:
                input_backend.mouse_button_up(flags)
        elif ev_type == config.EVENT_MOUSE_SCROLL:
            dy = ev.get("dy", 0)
            if dy != 0:
                input_backend.mouse_scroll(dy * 120)

    def _key_to_scan_code(self, key: str | None) -> int | None:
        if key is None:
            return None
        k = key.lower().strip()
        k = config.PYNPUT_KEY_ALIASES.get(k, k)
        return config.SCAN_CODES.get(k)
