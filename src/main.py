"""
Entry point for ReRe. Loads settings, applies stealth/config, registers hotkeys, starts GUI.
Zero persistent logging; traceback only in dev. Release all keys on exit.
"""

import sys

import customtkinter as ctk

from src import config
from src.controllers.playback_controller import PlaybackController
from src.gui import AppGui
from src import utils
from src import settings_manager
from src import input_backend

_DEV_MODE = getattr(sys, "frozen", False) is False


def _excepthook(typ, value, tb) -> None:
    if _DEV_MODE and tb is not None:
        import traceback
        traceback.print_exception(typ, value, tb)
    sys.__excepthook__(typ, value, tb)


def main() -> None:
    sys.excepthook = _excepthook
    settings = settings_manager.load_settings()
    ctk.set_appearance_mode(settings.get("theme", "Dark"))
    override = (settings.get("macros_dir_override") or "").strip()
    config.set_macros_dir(override if override else None)
    config.update_from_settings(settings)
    input_backend.set_stealth_options(
        config.get_insert_nulls(),
        config.get_use_qpc_time(),
        config.get_input_mix_ratio(),
    )

    controller = PlaybackController()
    gui = AppGui(controller, on_settings_saved=lambda: None)
    emergency_hook = None
    recording_hooks: tuple = (None, None)
    key_spammer_hooks: tuple = (None, None)
    mouse_clicker_hooks: tuple = (None, None)

    def register_hotkeys() -> None:
        nonlocal emergency_hook, recording_hooks, key_spammer_hooks, mouse_clicker_hooks
        utils.unregister_hotkey(emergency_hook)
        utils.unregister_recording_hotkeys(recording_hooks)
        utils.unregister_recording_hotkeys(key_spammer_hooks)
        utils.unregister_recording_hotkeys(mouse_clicker_hooks)
        s = settings_manager.load_settings()
        config.update_from_settings(s)
        input_backend.set_stealth_options(
            config.get_insert_nulls(),
            config.get_use_qpc_time(),
            config.get_input_mix_ratio(),
        )
        emergency_hook = utils.register_emergency_hotkey(
            s.get("emergency_hotkey") or config.EMERGENCY_HOTKEY,
            lambda: gui._root.after(0, gui._handle_emergency_stop),
        )
        start_k = s.get("start_recording_hotkey", "f9")
        stop_k = s.get("stop_recording_hotkey", "f10")
        recording_hooks = utils.register_recording_hotkeys(
            start_k, stop_k, controller.start_recording, controller.stop_recording
        )
        ks_start = s.get("key_spammer_start_hotkey", "f7")
        ks_stop = s.get("key_spammer_stop_hotkey", "f8")
        key_spammer_hooks = utils.register_key_spammer_hotkeys(
            ks_start, ks_stop, gui.trigger_key_spammer_start, gui.trigger_key_spammer_stop
        )
        mc_start = s.get("mouse_clicker_start_hotkey", "f5")
        mc_stop = s.get("mouse_clicker_stop_hotkey", "f6")
        mouse_clicker_hooks = utils.register_mouse_clicker_hotkeys(
            mc_start, mc_stop, gui.trigger_mouse_clicker_start, gui.trigger_mouse_clicker_stop
        )

    register_hotkeys()
    gui.set_on_settings_saved(register_hotkeys)
    try:
        gui.run()
    finally:
        utils.unregister_hotkey(emergency_hook)
        utils.unregister_recording_hotkeys(recording_hooks)
        utils.unregister_recording_hotkeys(key_spammer_hooks)
        utils.unregister_recording_hotkeys(mouse_clicker_hooks)
        input_backend.release_all_keys()


if __name__ == "__main__":
    main()
