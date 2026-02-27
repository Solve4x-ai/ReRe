"""
Profile management for ReRe.

Stores named profiles in %APPDATA%\\ReRe\\profiles.json.
Each profile contains:
- settings: snapshot of settings_manager.load_settings()
- quick_actions: snapshot of Quick Actions UI state (intervals, counts, checkboxes, etc.).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from src import config


PROFILES_PATH = os.path.join(config.APPDATA_DIR, "profiles.json")


def load_profiles() -> Dict[str, Dict[str, Any]]:
    """Load all profiles from disk. Returns {} if none exist or on error."""
    if not os.path.isfile(PROFILES_PATH):
        return {}
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data  # type: ignore[return-value]
    except Exception:
        pass
    return {}


def save_profiles(profiles: Dict[str, Dict[str, Any]]) -> None:
    """Persist profiles to disk."""
    try:
        os.makedirs(config.APPDATA_DIR, exist_ok=True)
        with open(PROFILES_PATH, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2)
    except Exception:
        # Profiles are convenience only; failure to save should not crash app.
        pass

