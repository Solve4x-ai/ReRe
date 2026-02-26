"""
JSON serialization to %APPDATA%\\GameMacroTool\\macros.
Ensure directory exists; list macros for GUI; filename <-> display name.
"""

import json
import os

from src import config


def ensure_macros_dir() -> str:
    d = config.get_macros_dir()
    os.makedirs(d, exist_ok=True)
    return d


def _safe_filename(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in " _-")
    return safe.strip() or "macro"


def save_macro(name: str, events: list[dict]) -> str:
    d = ensure_macros_dir()
    base = _safe_filename(name)
    path = os.path.join(d, base + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"name": name, "events": events}, f, indent=2)
    return path


def load_macro(path_or_name: str) -> tuple[str, list[dict]] | None:
    ensure_macros_dir()
    if os.path.isabs(path_or_name) and os.path.isfile(path_or_name):
        p = path_or_name
    else:
        base = _safe_filename(path_or_name)
        p = os.path.join(config.get_macros_dir(), base + ".json")
        if not p.endswith(".json"):
            p = p + ".json"
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        events = data.get("events", [])
        name = data.get("name", os.path.splitext(os.path.basename(p))[0])
    elif isinstance(data, list):
        events = data
        name = os.path.splitext(os.path.basename(p))[0]
    else:
        return None
    if events:
        return (name, events)
    return None


def list_macros() -> list[tuple[str, str]]:
    """Returns list of (display_name, file_path)."""
    d = ensure_macros_dir()
    result = []
    for f in os.listdir(d):
        if f.endswith(".json"):
            path = os.path.join(d, f)
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    name = data.get("name", os.path.splitext(f)[0]) if isinstance(data, dict) else os.path.splitext(f)[0]
                except Exception:
                    name = os.path.splitext(f)[0]
                result.append((name, path))
    result.sort(key=lambda x: x[0].lower())
    return result


def get_macro_info(path: str) -> dict | None:
    """Return dict with name, path, event_count, duration_sec, created (mtime)."""
    result = load_macro(path)
    if result is None:
        return None
    name, events = result
    event_count = len(events)
    duration_sec = 0.0
    if events:
        ts = [e.get("t", 0) for e in events]
        duration_sec = max(ts) - min(ts) if ts else 0.0
    try:
        created = os.path.getmtime(path)
    except OSError:
        created = 0
    return {
        "name": name,
        "path": path,
        "event_count": event_count,
        "duration_sec": duration_sec,
        "created": created,
    }
