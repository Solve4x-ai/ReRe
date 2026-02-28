"""
Professional customtkinter GUI: Key Presser, Mouse Clicker, Macro Recorder, Macro Library, Settings.
Toolbar with state badge, always-on-top, transparency, and emergency stop (exits app).
"""

import os
import sys
import time
from datetime import datetime

import ctypes
from ctypes import wintypes
import tkinter.simpledialog as simpledialog

import customtkinter as ctk

from src import config
from src import profile_manager

# --- Window transparency (layered + alpha) ---
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x02
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0001
SWP_NOSIZE = 0x0002
SWP_FRAMECHANGED = 0x0020
SWP_NOZORDER = 0x0004

# Redraw constants for ghosting fix
RDW_INVALIDATE = 0x0001
RDW_UPDATENOW = 0x0100
RDW_ALLCHILDREN = 0x0080
RDW_ERASE = 0x0004

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
user32.SetWindowLongW.restype = wintypes.LONG
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, ctypes.c_ulong, ctypes.c_byte, ctypes.c_ulong]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.InvalidateRect.restype = wintypes.BOOL
user32.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
user32.RedrawWindow.restype = wintypes.BOOL


def get_hwnd(root: ctk.CTk) -> wintypes.HWND:
    """Get HWND from tkinter/CTk root for Win32 layered-window APIs."""
    return wintypes.HWND(root.winfo_id())


# Transparency: 0 = solid (alpha 1.0), max 0.95 = most transparent (alpha 0.05, never fully invisible)
TRANSPARENCY_MAX = 0.95


def transparency_to_alpha(transparency: float) -> float:
    """Convert transparency slider value (0 = solid, TRANSPARENCY_MAX = most transparent) to window alpha."""
    t = max(0.0, min(TRANSPARENCY_MAX, float(transparency)))
    return 1.0 - t


from src.controllers.playback_controller import PlaybackController, State
from src import macro_storage
from src import settings_manager

# Visual style (theme-aware: light, dark)
COLOR_ACCENT = "#00FF9D"
COLOR_DANGER = "#FF2D55"
COLOR_CARD = ("#E8E8E8", "#2A2A2A")  # light mode, dark mode

# Preset color profiles (accent color); key = settings["color_profile"]
COLOR_PROFILES = {
    "green": ("#00FF9D", "#00CC7D"),
    "blue": ("#00A2FF", "#0080CC"),
    "purple": ("#B366FF", "#8C52CC"),
    "amber": ("#FFB020", "#CC8C1A"),
}


def _accent_text_color(profile_id: str) -> str:
    """Text color on accent buttons (black for light accents, white for dark)."""
    return "#000" if profile_id in ("green", "amber") else "#fff"
COLOR_BORDER = ("#ccc", "#333")
MIN_WIDTH = 616   # ~33% narrower than original 920
MIN_HEIGHT = 700
INTERVAL_MAX_MS = 600_000  # 10 minutes


class AppGui:
    def __init__(self, controller: PlaybackController, on_settings_saved: callable = None) -> None:
        self._controller = controller
        self._on_settings_saved = on_settings_saved or (lambda: None)
        self._current_macro_path: str | None = None
        self._current_macro_name: str | None = None
        self._settings = settings_manager.load_settings()
        self._profiles = profile_manager.load_profiles()
        self._current_profile: str | None = None
        self._apply_macros_dir_override()
        self._recorded_count_var: ctk.StringVar | None = None
        self._progress_var: ctk.DoubleVar | None = None
        self._progress_bar: ctk.CTkProgressBar | None = None
        self._state_badge: ctk.CTkLabel | None = None
        self._status_var: ctk.StringVar | None = None
        self._playback_progress_job: str | None = None
        self._window_transparency = float(self._settings.get("window_transparency", 0.0))
        self._configure_after_id: str | None = None
        self._last_configure_size: tuple[int, int] | None = None
        self._transparency_slider: ctk.CTkSlider | None = None
        self._always_on_top_var: ctk.BooleanVar | None = None
        self._quick_key_selected: str = "space"
        self._quick_key_display: ctk.CTkButton | None = None
        self._key_dropdown_container: ctk.CTkFrame | None = None

        # Force dark theme only
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
        self._root = ctk.CTk()
        self._root.attributes("-topmost", False)
        self._apply_window_title()
        self._root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._root.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}")
        self._root.resizable(False, False)
        self._root.after(200, self._center_window)

        self._controller._on_state_change = self._on_state_change
        self._controller.set_live_event_callback(self._on_recorder_live_event)
        self._build_toolbar()
        self._build_tabs()
        self._build_status_bar()
        self._update_state_badge()
        self._update_always_on_top()
        self._set_window_icon()
        self._root.bind("<Configure>", self._on_configure)
        self._apply_initial_transparency()
        self._apply_color_profile()

    def _on_configure(self, event) -> None:
        """Trigger a redraw only when the window is resized to avoid ghosting and drag jitter."""
        try:
            size = (event.width, event.height)
        except Exception:
            size = None

        # Only react to real size changes (ignore pure move events)
        if size is not None:
            if self._last_configure_size == size:
                return
            self._last_configure_size = size

        if self._configure_after_id:
            self._root.after_cancel(self._configure_after_id)
        # Slightly longer delay to coalesce rapid resize events
        self._configure_after_id = self._root.after(50, self._force_full_redraw)

    def _force_full_redraw(self) -> None:
        """Full redraw of window and all children (fixes ghosting with layered window)."""
        self._configure_after_id = None
        try:
            hwnd = get_hwnd(self._root)
            user32.RedrawWindow(
                hwnd, None, None,
                RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN | RDW_ERASE,
            )
            # Let Tk handle painting in its normal event loop; just flush pending geometry/layout.
            self._root.update_idletasks()
        except Exception:
            pass

    def _apply_initial_transparency(self) -> None:
        """Apply saved window transparency and topmost on startup."""
        try:
            alpha = transparency_to_alpha(self._window_transparency)
            self._root.attributes("-alpha", alpha)
        except Exception:
            pass

    def _on_transparency_changed(self, value: float) -> None:
        """Apply transparency: 0 = solid, higher = more transparent (capped so window never fully invisible)."""
        self._window_transparency = max(0.0, min(TRANSPARENCY_MAX, float(value)))
        try:
            alpha = transparency_to_alpha(self._window_transparency)
            self._root.attributes("-alpha", alpha)
        except Exception:
            pass

    def _apply_macros_dir_override(self) -> None:
        override = self._settings.get("macros_dir_override", "").strip()
        if override and os.path.isdir(override):
            config.set_macros_dir(override)
        else:
            config.set_macros_dir(None)

    def _restrict_entry_to_digits(self, entry: ctk.CTkEntry) -> None:
        """Allow only digits in entry; strip any other characters on key release."""

        def on_key(_event) -> None:
            try:
                s = entry.get()
                digits = "".join(c for c in s if c.isdigit())
                if digits != s:
                    entry.delete(0, "end")
                    entry.insert(0, digits)
            except Exception:
                pass

        entry.bind("<KeyRelease>", on_key)

    def _center_window(self) -> None:
        self._root.update_idletasks()
        w, h = self._root.winfo_width(), self._root.winfo_height()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self._root.geometry(f"+{x}+{y}")

    def _update_always_on_top(self) -> None:
        top = self._settings.get("always_on_top", False)
        self._root.attributes("-topmost", bool(top))
        self._root.update_idletasks()
        if top:
            self._root.lift()

    def _apply_window_title(self) -> None:
        generic = (self._settings.get("generic_window_title") or "").strip()
        if generic:
            self._root.title(generic)
        elif self._settings.get("obfuscate_process_name"):
            import random as _r
            titles = ["System Monitor", "Windows Service", "Local Server", "Background Tasks"]
            self._root.title(_r.choice(titles))
        else:
            self._root.title(f"{config.APP_NAME}  v{config.APP_VERSION}")

    def _set_window_icon(self) -> None:
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base, "assets", "rere_logo.png")
            if os.path.isfile(icon_path):
                from PIL import Image, ImageTk
                img = Image.open(icon_path)
                self._icon_photo = ImageTk.PhotoImage(img)
                self._root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

    def _record_hotkey(self, label: str, entry: ctk.CTkEntry) -> None:
        entry.delete(0, "end")
        entry.insert(0, "...")
        dialog = ctk.CTkToplevel(self._root)
        dialog.title("Record hotkey")
        dialog.geometry("320x100")
        dialog.transient(self._root)
        ctk.CTkLabel(dialog, text=f"Press ONE key for {label}…").pack(pady=12, padx=12)
        ctk.CTkLabel(dialog, text="(focus this window, then press a single key)").pack(pady=(0, 8))
        dialog.grab_set()

        def capture() -> None:
            try:
                import keyboard as kb
                key = kb.read_key(suppress=True)
                if key:
                    key = str(key).strip().lower()
                self._root.after(0, lambda: self._apply_recorded_hotkey(dialog, entry, key or ""))
            except Exception:
                self._root.after(0, lambda: self._apply_recorded_hotkey(dialog, entry, ""))
        import threading
        threading.Thread(target=capture, daemon=True).start()

    def _apply_recorded_hotkey(self, dialog: ctk.CTkToplevel, entry: ctk.CTkEntry, key: str) -> None:
        try:
            dialog.grab_release()
            dialog.destroy()
        except Exception:
            pass
        entry.delete(0, "end")
        if key:
            entry.insert(0, key)

    def _on_recorder_live_event(self, ev: dict) -> None:
        """Append one line to live events display (thread-safe via after)."""
        t = ev.get("t", 0)
        typ = ev.get("type", "")
        if typ == "key_down":
            line = f"+{t:.2f}s   key_down   {ev.get('key', '')}\n"
        elif typ == "key_up":
            line = f"+{t:.2f}s   key_up     {ev.get('key', '')}\n"
        elif typ == "mouse_move":
            line = f"+{t:.2f}s   move       dx={ev.get('dx', 0)} dy={ev.get('dy', 0)}\n"
        elif typ == "mouse_down":
            line = f"+{t:.2f}s   mouse_down {ev.get('button', '')}\n"
        elif typ == "mouse_up":
            line = f"+{t:.2f}s   mouse_up   {ev.get('button', '')}\n"
        elif typ == "mouse_scroll":
            line = f"+{t:.2f}s   scroll     dy={ev.get('dy', 0)}\n"
        else:
            line = f"+{t:.2f}s   {typ}\n"
        if getattr(self, "_live_events_text", None):
            self._root.after(0, lambda: self._append_live_event(line))

    def _append_live_event(self, line: str) -> None:
        if not getattr(self, "_live_events_text", None):
            return
        self._live_events_text.configure(state="normal")
        self._live_events_text.insert("end", line)
        self._live_events_text.see("end")
        self._live_events_text.configure(state="disabled")

    def _build_toolbar(self) -> None:
        toolbar = ctk.CTkFrame(self._root, fg_color=COLOR_CARD, corner_radius=8, height=52)
        toolbar.pack(fill="x", padx=10, pady=(10, 6))
        toolbar.pack_propagate(False)

        title = ctk.CTkLabel(toolbar, text=config.APP_NAME, font=ctk.CTkFont(size=18, weight="bold"))
        title.pack(side="left", padx=12, pady=10)

        self._state_badge = ctk.CTkLabel(
            toolbar, text="Idle", font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_CARD, text_color=COLOR_ACCENT, corner_radius=6, padx=12, pady=4
        )
        self._state_badge.pack(side="left", padx=8, pady=8)

        # Toolbar-level profile selector (quick profile switching)
        profile_names = sorted(self._profiles.keys()) if getattr(self, "_profiles", None) else []
        if profile_names:
            self._toolbar_profile_combo = ctk.CTkComboBox(
                toolbar,
                values=profile_names,
                width=180,
                state="readonly",
                command=self._on_profile_selected,
            )
            initial = self._current_profile or profile_names[0]
            self._toolbar_profile_combo.set(initial)
        else:
            self._toolbar_profile_combo = ctk.CTkComboBox(
                toolbar,
                values=["No profiles"],
                width=180,
                state="disabled",
            )
            self._toolbar_profile_combo.set("No profiles")
        self._toolbar_profile_combo.pack(side="right", padx=8, pady=10)

        self._toolbar_save_btn = ctk.CTkButton(
            toolbar, text="Save", width=70, height=28,
            fg_color=COLOR_ACCENT, text_color="#000",
            command=self._handle_toolbar_save_profile,
        )
        self._toolbar_save_btn.pack(side="right", padx=4, pady=10)
        if not profile_names:
            self._toolbar_save_btn.configure(state="disabled")

        self._always_on_top_var = ctk.BooleanVar(value=bool(self._settings.get("always_on_top", False)))
        self._always_on_top_cb = ctk.CTkCheckBox(
            toolbar, text="Always on top", variable=self._always_on_top_var, command=self._on_always_on_top_changed
        )
        self._always_on_top_cb.pack(side="right", padx=8, pady=10)

        win_row = ctk.CTkFrame(self._root, fg_color="transparent")
        win_row.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(win_row, text="Transparency:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        def on_transparency_slider(v: float) -> None:
            self._update_transparency_label(v)
            self._on_transparency_changed(v)

        self._transparency_slider = ctk.CTkSlider(
            win_row, from_=0.0, to=TRANSPARENCY_MAX, number_of_steps=19, width=140, command=on_transparency_slider
        )
        self._transparency_slider.set(self._settings.get("window_transparency", 0.0))
        self._update_transparency_label(self._transparency_slider.get())
        self._transparency_slider.pack(side="left", padx=(0, 8))
        self._transparency_label = ctk.CTkLabel(win_row, text="0%", font=ctk.CTkFont(size=12), width=48)
        self._transparency_label.pack(side="left", padx=(0, 16))
        self._on_transparency_changed(self._transparency_slider.get())

    def _handle_toolbar_save_profile(self) -> None:
        """Overwrite current profile with current settings (no need to open Settings tab)."""
        name = getattr(self, "_current_profile", None) or (getattr(self, "_toolbar_profile_combo", None) and self._toolbar_profile_combo.get())
        if not name or name == "No profiles" or name not in getattr(self, "_profiles", {}):
            return
        snapshot = {
            "settings": dict(self._settings),
            "quick_actions": self._collect_quick_actions_state(),
        }
        self._profiles[name] = snapshot
        profile_manager.save_profiles(self._profiles)

    def _on_color_profile_selected(self, profile_id: str) -> None:
        if profile_id not in COLOR_PROFILES:
            return
        self._settings["color_profile"] = profile_id
        settings_manager.save_settings(self._settings)
        self._apply_color_profile()
        for pid, btn in getattr(self, "_color_profile_buttons", []):
            fg, hover = COLOR_PROFILES.get(pid, (COLOR_ACCENT, "#00CC7D"))
            if pid == profile_id:
                btn.configure(fg_color=fg, hover_color=hover, text_color="#000" if pid in ("green", "amber") else "#fff")
            else:
                btn.configure(fg_color="#3a3a3a", hover_color=hover, text_color="#fff")

    def _get_accent_colors(self) -> tuple[str, str, str]:
        """Return (fg, hover, text_on_accent) for current color profile."""
        profile_id = self._settings.get("color_profile", "green")
        fg, hover = COLOR_PROFILES.get(profile_id, (COLOR_ACCENT, "#00CC7D"))
        return fg, hover, _accent_text_color(profile_id)

    def _apply_color_profile(self) -> None:
        """Apply accent color from current color profile to all accent widgets."""
        profile_id = self._settings.get("color_profile", "green")
        fg, hover = COLOR_PROFILES.get(profile_id, (COLOR_ACCENT, "#00CC7D"))
        text_on_accent = _accent_text_color(profile_id)
        try:
            if getattr(self, "_tabview", None):
                self._tabview.configure(segmented_button_selected_color=fg, segmented_button_selected_hover_color=hover)
            if getattr(self, "_state_badge", None):
                self._state_badge.configure(text_color=fg)
            if getattr(self, "_toolbar_save_btn", None):
                self._toolbar_save_btn.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_always_on_top_cb", None):
                self._always_on_top_cb.configure(fg_color=fg, hover_color=hover)
            if getattr(self, "_transparency_slider", None):
                self._transparency_slider.configure(progress_color=fg, button_color=fg, button_hover_color=hover)
            if getattr(self, "_key_countdown_bar", None):
                self._key_countdown_bar.configure(progress_color=fg)
            if getattr(self, "_human_labels", None):
                for lbl in self._human_labels.values():
                    lbl.configure(text_color=fg)
            if getattr(self, "_quick_key_display", None):
                self._quick_key_display.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_quick_tap_hold", None):
                self._quick_tap_hold.configure(selected_color=fg, selected_hover_color=hover)
            if getattr(self, "_quick_key_interval_slider", None):
                self._quick_key_interval_slider.configure(progress_color=fg, button_color=fg, button_hover_color=hover)
            if getattr(self, "_quick_key_count_infinite", None):
                self._quick_key_count_infinite.configure(fg_color=fg, hover_color=hover)
            if getattr(self, "_quick_key_interval_display", None):
                self._quick_key_interval_display.configure(text_color=fg)
            if getattr(self, "_quick_speed", None):
                self._quick_speed.configure(progress_color=fg, button_color=fg, button_hover_color=hover)
            if getattr(self, "_quick_randomize", None):
                self._quick_randomize.configure(fg_color=fg, hover_color=hover)
            if getattr(self, "_quick_key_toggle_btn", None):
                if "Stop" not in (self._quick_key_toggle_btn.cget("text") or ""):
                    self._quick_key_toggle_btn.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_quick_mouse_btn", None):
                self._quick_mouse_btn.configure(selected_color=fg, selected_hover_color=hover)
            if getattr(self, "_quick_mouse_single_repeat", None):
                self._quick_mouse_single_repeat.configure(selected_color=fg, selected_hover_color=hover)
            if getattr(self, "_quick_mouse_interval_slider", None):
                self._quick_mouse_interval_slider.configure(progress_color=fg, button_color=fg, button_hover_color=hover)
            if getattr(self, "_quick_mouse_count_infinite", None):
                self._quick_mouse_count_infinite.configure(fg_color=fg, hover_color=hover)
            if getattr(self, "_quick_mouse_interval_display", None):
                self._quick_mouse_interval_display.configure(text_color=fg)
            if getattr(self, "_quick_mouse_toggle_btn", None):
                if "Stop" not in (self._quick_mouse_toggle_btn.cget("text") or ""):
                    self._quick_mouse_toggle_btn.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_btn_record", None):
                self._btn_record.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_btn_save_macro", None):
                self._btn_save_macro.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_btn_library_play", None):
                self._btn_library_play.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_btn_save_settings", None):
                self._btn_save_settings.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_btn_profile_save_as", None):
                self._btn_profile_save_as.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_btn_profile_overwrite", None):
                self._btn_profile_overwrite.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            for btn in getattr(self, "_settings_record_key_buttons", []):
                btn.configure(fg_color=fg, hover_color=hover, text_color=text_on_accent)
            if getattr(self, "_adv_human_cb", None):
                self._adv_human_cb.configure(fg_color=fg, hover_color=hover)
            if getattr(self, "_intensity_slider", None):
                self._intensity_slider.configure(progress_color=fg, button_color=fg, button_hover_color=hover)
            if getattr(self, "_insert_nulls_cb", None):
                self._insert_nulls_cb.configure(fg_color=fg, hover_color=hover)
            if getattr(self, "_use_qpc_cb", None):
                self._use_qpc_cb.configure(fg_color=fg, hover_color=hover)
            if getattr(self, "_obfuscate_cb", None):
                self._obfuscate_cb.configure(fg_color=fg, hover_color=hover)
            if callable(getattr(self, "_update_humanization_features_cb", None)):
                self._update_humanization_features_cb()
        except Exception:
            pass

    def _on_always_on_top_changed(self) -> None:
        self._settings["always_on_top"] = bool(self._always_on_top_var.get())
        self._update_always_on_top()

    def _handle_emergency_stop(self) -> None:
        """Stop all actions and exit the application completely."""
        self._controller.emergency_stop()
        sys.exit(0)

    def _update_transparency_label(self, value: float) -> None:
        if getattr(self, "_transparency_label", None):
            pct = int(round(max(0, min(TRANSPARENCY_MAX, value)) * 100))
            self._transparency_label.configure(text=f"{pct}%")

    def _build_tabs(self) -> None:
        self._tabview = ctk.CTkTabview(self._root, fg_color=COLOR_CARD, corner_radius=8)
        self._tabview.pack(fill="both", expand=True, padx=10, pady=6)

        self._tabview.add("Key Presser")
        self._tabview.add("Mouse Clicker")
        self._tabview.add("Macro Recorder")
        self._tabview.add("Macro Library")
        self._tabview.add("Settings")
        self._tabview.set("Key Presser")

        self._build_key_presser_tab(self._tabview.tab("Key Presser"))
        self._build_mouse_clicker_tab(self._tabview.tab("Mouse Clicker"))
        self._build_recorder_tab(self._tabview.tab("Macro Recorder"))
        self._build_library_tab(self._tabview.tab("Macro Library"))
        self._build_settings_tab(self._tabview.tab("Settings"))

    def _build_key_presser_tab(self, parent: ctk.CTkFrame) -> None:
        # Top row: global options
        shared = ctk.CTkFrame(parent, fg_color="transparent")
        shared.pack(fill="x", padx=10, pady=(10, 6))
        self._quick_randomize = ctk.CTkCheckBox(shared, text="Global randomization (micro-jitter)")
        self._quick_randomize.pack(side="left", padx=(0, 20))

        # Two-column layout: left = Key Presser card, right = Humanization (last applied)
        content_row = ctk.CTkFrame(parent, fg_color="transparent")
        content_row.pack(fill="both", expand=True, padx=10, pady=6)

        key_frame = ctk.CTkFrame(content_row, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color="#333")
        key_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ctk.CTkLabel(key_frame, text="Key Presser", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))

        self._key_names = sorted(
            config.SCAN_CODES.keys(),
            key=lambda x: (x not in ["space", "enter", "shift", "ctrl", "alt"], x),
        )
        key_selector_row = ctk.CTkFrame(key_frame, fg_color="transparent")
        key_selector_row.pack(fill="x", padx=12, pady=4)
        key_row = ctk.CTkFrame(key_selector_row, fg_color="transparent")
        key_row.pack(side="left")
        ctk.CTkLabel(key_row, text="Key:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        self._quick_key_display = ctk.CTkButton(
            key_row,
            text=f"{self._quick_key_selected} ▾",
            width=100,
            command=self._toggle_key_dropdown,
        )
        self._quick_key_display.pack(side="left")

        # Inline dropdown to the right of the button (uses empty space, avoids bottom cut-off)
        self._key_dropdown_container = ctk.CTkFrame(
            key_selector_row, fg_color=COLOR_CARD, corner_radius=6, border_width=1, border_color="#333", width=160, height=140
        )
        self._key_dropdown_container.pack_propagate(False)
        dropdown_sf = ctk.CTkScrollableFrame(self._key_dropdown_container, width=152, height=132, fg_color="transparent")
        dropdown_sf.pack(fill="both", expand=True, padx=4, pady=4)
        for name in self._key_names:
            btn = ctk.CTkButton(
                dropdown_sf,
                text=name,
                width=140,
                height=24,
                font=ctk.CTkFont(size=11),
                command=lambda n=name: self._select_key(n),
            )
            btn.pack(anchor="w", padx=2, pady=1)

        tap_hold = ctk.CTkSegmentedButton(key_frame, values=["Tap", "Hold"])
        tap_hold.pack(anchor="w", padx=12, pady=4)
        tap_hold.set("Tap")

        ctk.CTkLabel(key_frame, text="Interval (ms): 50 – 600000 (10 min)").pack(anchor="w", padx=12, pady=(8, 0))
        key_interval_entry = ctk.CTkEntry(key_frame, width=80, placeholder_text="200")
        key_interval_entry.insert(0, "200")
        key_interval_entry.pack(anchor="w", padx=12, pady=2)
        self._restrict_entry_to_digits(key_interval_entry)
        key_interval = ctk.CTkSlider(key_frame, from_=50, to=INTERVAL_MAX_MS, number_of_steps=599, width=200,
                                      command=lambda v: (key_interval_entry.delete(0, "end"), key_interval_entry.insert(0, str(int(v)))))
        key_interval.set(200)
        key_interval.pack(anchor="w", padx=12, pady=2)

        ctk.CTkLabel(key_frame, text="Count: infinite or 10–9999").pack(anchor="w", padx=12, pady=(8, 0))
        key_count_infinite = ctk.CTkCheckBox(key_frame, text="Infinite")
        key_count_infinite.pack(anchor="w", padx=12, pady=2)
        key_count_infinite.select()
        key_count_entry = ctk.CTkEntry(key_frame, width=80, placeholder_text="100")
        key_count_entry.insert(0, "100")
        key_count_entry.pack(anchor="w", padx=12, pady=2)
        self._restrict_entry_to_digits(key_count_entry)

        key_interval_display_var = ctk.StringVar(value="Last interval: — ms")
        self._quick_key_interval_display = ctk.CTkLabel(key_frame, textvariable=key_interval_display_var, font=ctk.CTkFont(size=13, weight="bold"), text_color=COLOR_ACCENT)
        self._quick_key_interval_display.pack(anchor="w", padx=12, pady=(4, 0))

        # Countdown progress bar: fills as next key press approaches
        key_countdown_row = ctk.CTkFrame(key_frame, fg_color="transparent")
        key_countdown_row.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(key_countdown_row, text="Next press", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 8))
        self._key_countdown_progress_var = ctk.DoubleVar(value=0.0)
        self._key_countdown_bar = ctk.CTkProgressBar(
            key_countdown_row,
            variable=self._key_countdown_progress_var,
            width=220,
            height=8,
            corner_radius=4,
            fg_color="#1a1a1a",
            progress_color=COLOR_ACCENT,
        )
        self._key_countdown_bar.pack(side="left", fill="x", expand=True)

        key_toggle_btn = ctk.CTkButton(
            key_frame, text="Start Spamming", fg_color=COLOR_ACCENT, hover_color="#00CC7D", text_color="#000",
            command=self._toggle_key_spammer
        )
        key_toggle_btn.pack(pady=12, padx=12, fill="x")
        key_toggle_btn.configure(cursor="hand2")
        self._quick_tap_hold = tap_hold
        self._quick_key_interval_slider = key_interval
        self._quick_key_interval_entry = key_interval_entry
        self._quick_key_count_infinite = key_count_infinite
        self._quick_key_count_entry = key_count_entry
        self._quick_key_toggle_btn = key_toggle_btn
        self._quick_key_interval_display_var = key_interval_display_var

        # Humanization (last applied): single column on the right
        human_frame = ctk.CTkFrame(content_row, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color="#333", width=180)
        human_frame.pack(side="right", fill="y", padx=0)
        human_frame.pack_propagate(False)
        ctk.CTkLabel(human_frame, text="Humanization (last applied)", font=ctk.CTkFont(weight="bold", size=11)).pack(anchor="w", padx=10, pady=(10, 6))
        self._human_labels: dict[str, ctk.CTkLabel] = {}
        human_items = [
            ("delay_jitter", "Delay jitter:"),
            ("key_hold", "Key hold:"),
            ("drift", "Drift:"),
            ("micro_pause", "Micro-pause:"),
            ("insert_nulls", "Nulls:"),
            ("qpc", "QPC:"),
        ]
        for key, label_text in human_items:
            row = ctk.CTkFrame(human_frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=label_text, font=ctk.CTkFont(size=10), width=85, anchor="w").pack(side="left")
            lbl = ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=10), text_color=COLOR_ACCENT)
            lbl.pack(side="left")
            self._human_labels[key] = lbl
        self._poll_humanization_report()

    def _build_mouse_clicker_tab(self, parent: ctk.CTkFrame) -> None:
        """Mouse Clicker tab: auto-clicker controls only."""
        mouse_frame = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color="#333")
        mouse_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(mouse_frame, text="Mouse Clicker", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))

        mouse_btn = ctk.CTkSegmentedButton(mouse_frame, values=["Left Click", "Right Click"])
        mouse_btn.pack(anchor="w", padx=12, pady=4)
        mouse_btn.set("Left Click")

        mouse_single_repeat = ctk.CTkSegmentedButton(mouse_frame, values=["Single click", "Repeat"])
        mouse_single_repeat.pack(anchor="w", padx=12, pady=4)
        mouse_single_repeat.set("Single click")

        ctk.CTkLabel(mouse_frame, text="Interval (ms): 50 – 600000 (10 min)").pack(anchor="w", padx=12, pady=(8, 0))
        mouse_interval_entry = ctk.CTkEntry(mouse_frame, width=80, placeholder_text="200")
        mouse_interval_entry.insert(0, "200")
        mouse_interval_entry.pack(anchor="w", padx=12, pady=2)
        self._restrict_entry_to_digits(mouse_interval_entry)
        mouse_interval = ctk.CTkSlider(mouse_frame, from_=50, to=INTERVAL_MAX_MS, number_of_steps=599, width=200,
                                       command=lambda v: (mouse_interval_entry.delete(0, "end"), mouse_interval_entry.insert(0, str(int(v)))))
        mouse_interval.set(200)
        mouse_interval.pack(anchor="w", padx=12, pady=2)

        ctk.CTkLabel(mouse_frame, text="Count: infinite or 10–9999").pack(anchor="w", padx=12, pady=(8, 0))
        mouse_count_infinite = ctk.CTkCheckBox(mouse_frame, text="Infinite")
        mouse_count_infinite.pack(anchor="w", padx=12, pady=2)
        mouse_count_infinite.select()
        mouse_count_entry = ctk.CTkEntry(mouse_frame, width=80, placeholder_text="100")
        mouse_count_entry.insert(0, "100")
        mouse_count_entry.pack(anchor="w", padx=12, pady=2)
        self._restrict_entry_to_digits(mouse_count_entry)

        mouse_interval_display_var = ctk.StringVar(value="Last interval: — ms")
        self._quick_mouse_interval_display = ctk.CTkLabel(mouse_frame, textvariable=mouse_interval_display_var, font=ctk.CTkFont(size=13, weight="bold"), text_color=COLOR_ACCENT)
        self._quick_mouse_interval_display.pack(anchor="w", padx=12, pady=(4, 0))
        mouse_toggle_btn = ctk.CTkButton(
            mouse_frame, text="Start Clicking", fg_color=COLOR_ACCENT, hover_color="#00CC7D", text_color="#000",
            command=self._toggle_mouse_clicker
        )
        mouse_toggle_btn.pack(pady=12, padx=12, fill="x")
        mouse_toggle_btn.configure(cursor="hand2")
        self._quick_mouse_btn = mouse_btn
        self._quick_mouse_single_repeat = mouse_single_repeat
        self._quick_mouse_interval_slider = mouse_interval
        self._quick_mouse_interval_entry = mouse_interval_entry
        self._quick_mouse_count_infinite = mouse_count_infinite
        self._quick_mouse_count_entry = mouse_count_entry
        self._quick_mouse_toggle_btn = mouse_toggle_btn
        self._quick_mouse_interval_display_var = mouse_interval_display_var

    # (Key picker now uses the inline dropdown; no separate dialog needed.)

    def _poll_humanization_report(self) -> None:
        try:
            from src import humanization_report
            r = humanization_report.get_report()
        except Exception:
            r = {}
        def fmt(v: object) -> str:
            if v is None:
                return "—"
            if isinstance(v, bool):
                return "yes" if v else "no"
            if isinstance(v, (int, float)):
                if isinstance(v, float) and abs(v) < 1e-6 and v != 0:
                    return f"{v:+.2f}"
                return str(v)
            return str(v)
        if getattr(self, "_human_labels", None):
            jitter = r.get("delay_jitter_ms")
            self._human_labels["delay_jitter"].configure(text=f"{jitter:+.2f} ms" if jitter is not None else "—")
            key_hold = r.get("variable_key_hold_ms")
            self._human_labels["key_hold"].configure(text=f"{fmt(key_hold)} ms" if key_hold is not None else "—")
            drift = r.get("drift_factor")
            if drift is not None:
                pct = (drift - 1.0) * 100
                self._human_labels["drift"].configure(text=f"{pct:+.2f}% (×{drift:.3f})")
            else:
                self._human_labels["drift"].configure(text="—")
            mp = r.get("micro_pause_ms")
            self._human_labels["micro_pause"].configure(text=f"{mp:.0f} ms" if mp is not None else "—")
            nulls = r.get("insert_nulls_count")
            self._human_labels["insert_nulls"].configure(text=str(nulls) if nulls is not None else "—")
            qpc = r.get("qpc_used")
            qpc_time = r.get("qpc_time_value")
            if qpc and qpc_time is not None:
                self._human_labels["qpc"].configure(text=f"yes (0x{int(qpc_time) & 0xFFFFFFFF:08X})")
            elif qpc is False:
                self._human_labels["qpc"].configure(text="no")
            else:
                self._human_labels["qpc"].configure(text="—")
        self._root.after(350, self._poll_humanization_report)

    def _parse_interval(self, slider: ctk.CTkSlider, entry: ctk.CTkEntry, lo: int, hi: int, default: int) -> int:
        try:
            v = int(entry.get().strip())
            return max(lo, min(hi, v))
        except ValueError:
            return max(lo, min(hi, int(slider.get())))

    def _parse_count(self, infinite_cb: ctk.CTkCheckBox, entry: ctk.CTkEntry) -> int | None:
        if infinite_cb.get():
            return None
        try:
            return max(10, min(9999, int(entry.get().strip())))
        except ValueError:
            return 100

    # --- Profiles: capture/apply full configuration snapshots ---

    def _collect_quick_actions_state(self) -> dict:
        """Collect current Quick Actions state for profile snapshots."""
        state: dict = {}
        try:
            state["quick_randomize"] = bool(self._quick_randomize.get())
            state["quick_speed"] = float(self._quick_speed.get())
            state["key_name"] = getattr(self, "_quick_key_selected", "space")
            state["tap_hold"] = self._quick_tap_hold.get()
            state["key_interval"] = self._parse_interval(
                self._quick_key_interval_slider, self._quick_key_interval_entry,
                config.KEY_SPAM_INTERVAL_MS_MIN, config.KEY_SPAM_INTERVAL_MS_MAX, 200,
            )
            state["key_count_infinite"] = bool(self._quick_key_count_infinite.get())
            key_count = self._parse_count(self._quick_key_count_infinite, self._quick_key_count_entry)
            state["key_count"] = 0 if key_count is None else int(key_count)
            state["mouse_button"] = self._quick_mouse_btn.get()
            state["mouse_mode"] = self._quick_mouse_single_repeat.get()
            state["mouse_interval"] = self._parse_interval(
                self._quick_mouse_interval_slider, self._quick_mouse_interval_entry,
                config.MOUSE_CLICK_INTERVAL_MS_MIN, config.MOUSE_CLICK_INTERVAL_MS_MAX, 200,
            )
            state["mouse_count_infinite"] = bool(self._quick_mouse_count_infinite.get())
            mouse_count = self._parse_count(self._quick_mouse_count_infinite, self._quick_mouse_count_entry)
            state["mouse_count"] = 0 if mouse_count is None else int(mouse_count)
        except Exception:
            pass
        return state

    def _apply_quick_actions_state(self, state: dict) -> None:
        """Apply Quick Actions state from a profile without starting anything."""
        try:
            if "quick_randomize" in state:
                if state["quick_randomize"]:
                    self._quick_randomize.select()
                else:
                    self._quick_randomize.deselect()
            if "quick_speed" in state and getattr(self, "_quick_speed", None):
                val = float(state["quick_speed"])
                self._quick_speed.set(val)
            key_name = state.get("key_name")
            if key_name and key_name in getattr(self, "_key_names", []):
                self._quick_key_selected = key_name
                if getattr(self, "_quick_key_display", None):
                    self._quick_key_display.configure(text=f"{key_name} ▾")
            tap_hold = state.get("tap_hold")
            if tap_hold and getattr(self, "_quick_tap_hold", None):
                self._quick_tap_hold.set(tap_hold)
            if "key_interval" in state:
                ki = int(state["key_interval"])
                self._quick_key_interval_slider.set(ki)
                self._quick_key_interval_entry.delete(0, "end")
                self._quick_key_interval_entry.insert(0, str(ki))
            if "key_count_infinite" in state:
                if state["key_count_infinite"]:
                    self._quick_key_count_infinite.select()
                else:
                    self._quick_key_count_infinite.deselect()
            if "key_count" in state and not state.get("key_count_infinite", False):
                kc = int(state["key_count"])
                self._quick_key_count_entry.delete(0, "end")
                self._quick_key_count_entry.insert(0, str(kc))
            mb = state.get("mouse_button")
            if mb and getattr(self, "_quick_mouse_btn", None):
                self._quick_mouse_btn.set(mb)
            mmode = state.get("mouse_mode")
            if mmode and getattr(self, "_quick_mouse_single_repeat", None):
                self._quick_mouse_single_repeat.set(mmode)
            if "mouse_interval" in state:
                mi = int(state["mouse_interval"])
                self._quick_mouse_interval_slider.set(mi)
                self._quick_mouse_interval_entry.delete(0, "end")
                self._quick_mouse_interval_entry.insert(0, str(mi))
            if "mouse_count_infinite" in state:
                if state["mouse_count_infinite"]:
                    self._quick_mouse_count_infinite.select()
                else:
                    self._quick_mouse_count_infinite.deselect()
            if "mouse_count" in state and not state.get("mouse_count_infinite", False):
                mc = int(state["mouse_count"])
                self._quick_mouse_count_entry.delete(0, "end")
                self._quick_mouse_count_entry.insert(0, str(mc))
        except Exception:
            pass

    def _toggle_key_spammer(self) -> None:
        if self._controller.is_key_spammer_running():
            self._stop_key_spammer()
        else:
            self._start_key_spammer()

    def _toggle_key_dropdown(self) -> None:
        """Show or hide the inline key selection dropdown (opens to the right of the key button)."""
        if not getattr(self, "_key_dropdown_container", None):
            return
        try:
            if self._key_dropdown_container.winfo_ismapped():
                self._key_dropdown_container.pack_forget()
            else:
                self._key_dropdown_container.pack(side="left", padx=(8, 0), fill="y")
        except Exception:
            pass

    def _select_key(self, key_name: str) -> None:
        """Update selected key from the inline dropdown."""
        self._quick_key_selected = key_name
        if getattr(self, "_quick_key_display", None):
            try:
                self._quick_key_display.configure(text=f"{key_name} ▾")
            except Exception:
                pass
        if getattr(self, "_key_dropdown_container", None):
            try:
                self._key_dropdown_container.pack_forget()
            except Exception:
                pass

    def _start_key_spammer(self) -> None:
        key = getattr(self, "_quick_key_selected", "space")
        tap = self._quick_tap_hold.get() == "Tap"
        interval = self._parse_interval(
            self._quick_key_interval_slider, self._quick_key_interval_entry,
            config.KEY_SPAM_INTERVAL_MS_MIN, config.KEY_SPAM_INTERVAL_MS_MAX, 200
        )
        count = self._parse_count(self._quick_key_count_infinite, self._quick_key_count_entry)
        self._quick_key_interval_entry.delete(0, "end")
        self._quick_key_interval_entry.insert(0, str(interval))
        if self._quick_key_interval_display_var:
            self._quick_key_interval_display_var.set("Last interval: — ms")
        if getattr(self, "_key_countdown_progress_var", None) is not None:
            self._key_countdown_progress_var.set(0.0)
        self._controller.start_key_spammer(key, tap, interval, count, self._quick_randomize.get())
        btn = self._quick_key_toggle_btn
        btn.configure(text="Stop Spamming", fg_color=COLOR_DANGER, hover_color="#CC2244", text_color="white")
        self._root.after(0, self._update_state_badge)
        if self._quick_key_interval_display_var:
            self._poll_key_interval_display(self._quick_key_interval_display_var)

    def _poll_key_interval_display(self, var: ctk.StringVar) -> None:
        if not self._controller.is_key_spammer_running():
            if getattr(self, "_key_countdown_progress_var", None) is not None:
                self._key_countdown_progress_var.set(0.0)
            self._root.after(0, self._refresh_key_spammer_ui)
            return
        last_ms = self._controller.get_last_key_interval_ms()
        if last_ms is not None:
            var.set(f"Last interval: {int(round(last_ms))} ms")
        # Update countdown progress: 0 = just pressed, 1 = about to press
        last_time = self._controller.get_last_key_execution_time()
        if last_time is not None and last_ms is not None and last_ms > 0:
            elapsed_ms = (time.perf_counter() - last_time) * 1000.0
            progress = min(1.0, elapsed_ms / last_ms)
            if getattr(self, "_key_countdown_progress_var", None) is not None:
                self._key_countdown_progress_var.set(progress)
        self._root.after(50, lambda: self._poll_key_interval_display(var))

    def _refresh_key_spammer_ui(self) -> None:
        if not self._controller.is_key_spammer_running() and getattr(self, "_quick_key_toggle_btn", None):
            btn = self._quick_key_toggle_btn
            fg, hover, text_on = self._get_accent_colors()
            btn.configure(text="Start Spamming", fg_color=fg, hover_color=hover, text_color=text_on)
            if getattr(self, "_quick_key_interval_display_var", None):
                self._quick_key_interval_display_var.set("Last interval: — ms")
            if getattr(self, "_key_countdown_progress_var", None) is not None:
                self._key_countdown_progress_var.set(0.0)
            self._update_state_badge()

    def _stop_key_spammer(self) -> None:
        self._controller.stop_key_spammer()
        if getattr(self, "_quick_key_toggle_btn", None):
            fg, hover, text_on = self._get_accent_colors()
            self._quick_key_toggle_btn.configure(text="Start Spamming", fg_color=fg, hover_color=hover, text_color=text_on)
        if getattr(self, "_quick_key_interval_display_var", None):
            self._quick_key_interval_display_var.set("Last interval: — ms")
        if getattr(self, "_key_countdown_progress_var", None) is not None:
            self._key_countdown_progress_var.set(0.0)
        self._root.after(0, self._update_state_badge)

    def _toggle_mouse_clicker(self) -> None:
        if self._controller.is_mouse_clicker_running():
            self._stop_mouse_clicker()
        else:
            self._start_mouse_clicker()

    def _poll_mouse_interval_display(self, var: ctk.StringVar) -> None:
        if not self._controller.is_mouse_clicker_running():
            self._root.after(0, self._refresh_mouse_clicker_ui)
            return
        last = self._controller.get_last_mouse_interval_ms()
        if last is not None:
            var.set(f"Last interval: {int(round(last))} ms")
        self._root.after(200, lambda: self._poll_mouse_interval_display(var))

    def _refresh_mouse_clicker_ui(self) -> None:
        if not self._controller.is_mouse_clicker_running() and getattr(self, "_quick_mouse_toggle_btn", None):
            btn = self._quick_mouse_toggle_btn
            fg, hover, text_on = self._get_accent_colors()
            btn.configure(text="Start Clicking", fg_color=fg, hover_color=hover, text_color=text_on)
            if getattr(self, "_quick_mouse_interval_display_var", None):
                self._quick_mouse_interval_display_var.set("Last interval: — ms")
            self._update_state_badge()

    def _start_mouse_clicker(self) -> None:
        left = self._quick_mouse_btn.get() == "Left Click"
        single_click = self._quick_mouse_single_repeat.get() == "Single click"
        interval = self._parse_interval(
            self._quick_mouse_interval_slider, self._quick_mouse_interval_entry,
            config.MOUSE_CLICK_INTERVAL_MS_MIN, config.MOUSE_CLICK_INTERVAL_MS_MAX, 200
        )
        count = self._parse_count(self._quick_mouse_count_infinite, self._quick_mouse_count_entry)
        self._quick_mouse_interval_entry.delete(0, "end")
        self._quick_mouse_interval_entry.insert(0, str(interval))
        if self._quick_mouse_interval_display_var:
            self._quick_mouse_interval_display_var.set("Last interval: — ms")
        self._controller.start_mouse_clicker(left, interval, count, self._quick_randomize.get(), single_click=single_click)
        btn = self._quick_mouse_toggle_btn
        btn.configure(text="Stop Clicking", fg_color=COLOR_DANGER, hover_color="#CC2244", text_color="white")
        self._root.after(0, self._update_state_badge)
        if self._quick_mouse_interval_display_var:
            self._poll_mouse_interval_display(self._quick_mouse_interval_display_var)

    def _stop_mouse_clicker(self) -> None:
        self._controller.stop_mouse_clicker()
        if getattr(self, "_quick_mouse_toggle_btn", None):
            fg, hover, text_on = self._get_accent_colors()
            self._quick_mouse_toggle_btn.configure(text="Start Clicking", fg_color=fg, hover_color=hover, text_color=text_on)
        if getattr(self, "_quick_mouse_interval_display_var", None):
            self._quick_mouse_interval_display_var.set("Last interval: — ms")
        self._root.after(0, self._update_state_badge)

    # --- Profiles handlers ---

    def _on_profile_selected(self, name: str) -> None:
        if not name:
            return
        # Avoid re-applying the same profile redundantly
        if getattr(self, "_current_profile", None) == name:
            return
        self._current_profile = name
        prof = self._profiles.get(name)
        if not isinstance(prof, dict):
            return
        settings_snapshot = prof.get("settings") or {}
        if isinstance(settings_snapshot, dict):
            # Apply settings snapshot to in-memory settings and persist behaviour-level config.
            self._settings.update(settings_snapshot)
            settings_manager.save_settings(self._settings)
            config.update_from_settings(self._settings)
            from src import input_backend
            input_backend.set_stealth_options(
                config.get_insert_nulls(),
                config.get_use_qpc_time(),
                config.get_input_mix_ratio(),
            )
            self._apply_window_title()
            self._apply_macros_dir_override()
            self._update_always_on_top()
            self._on_settings_saved()
        qa = prof.get("quick_actions") or {}
        if isinstance(qa, dict):
            self._apply_quick_actions_state(qa)
        # Keep toolbar and Settings profile combos in sync
        if hasattr(self, "_profile_combo"):
            try:
                self._profile_combo.set(name)
            except Exception:
                pass
        if hasattr(self, "_toolbar_profile_combo") and getattr(self, "_toolbar_profile_combo", None):
            try:
                if self._toolbar_profile_combo.cget("state") != "disabled":
                    self._toolbar_profile_combo.set(name)
            except Exception:
                pass

    def _handle_profile_save_as(self) -> None:
        name = simpledialog.askstring("Save Profile", "Profile name:", parent=self._root)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        snapshot = {
            "settings": dict(self._settings),
            "quick_actions": self._collect_quick_actions_state(),
        }
        self._profiles[name] = snapshot
        profile_manager.save_profiles(self._profiles)
        # Refresh combo values (Settings and toolbar)
        names = sorted(self._profiles.keys())
        self._profile_combo.configure(values=names)
        self._profile_combo.set(name)
        self._current_profile = name
        if getattr(self, "_toolbar_profile_combo", None):
            self._toolbar_profile_combo.configure(values=names, state="readonly")
            self._toolbar_profile_combo.set(name)
        if getattr(self, "_toolbar_save_btn", None):
            self._toolbar_save_btn.configure(state="normal")

    def _handle_profile_overwrite(self) -> None:
        name = getattr(self, "_current_profile", None) or (self._profile_combo.get() if hasattr(self, "_profile_combo") else None)
        if not name:
            return
        snapshot = {
            "settings": dict(self._settings),
            "quick_actions": self._collect_quick_actions_state(),
        }
        self._profiles[name] = snapshot
        profile_manager.save_profiles(self._profiles)

    def _handle_profile_delete(self) -> None:
        name = getattr(self, "_current_profile", None) or (self._profile_combo.get() if hasattr(self, "_profile_combo") else None)
        if not name:
            return
        if name in self._profiles:
            del self._profiles[name]
            profile_manager.save_profiles(self._profiles)
        names = sorted(self._profiles.keys()) or ["Default"]
        if names == ["Default"] and "Default" not in self._profiles:
            self._profiles["Default"] = {
                "settings": dict(self._settings),
                "quick_actions": self._collect_quick_actions_state(),
            }
            profile_manager.save_profiles(self._profiles)
        self._profile_combo.configure(values=names)
        self._profile_combo.set(names[0])
        self._current_profile = names[0]

    def trigger_key_spammer_start(self) -> None:
        if self._controller.is_key_spammer_running():
            return
        self._root.after(0, self._start_key_spammer)

    def trigger_key_spammer_stop(self) -> None:
        if not self._controller.is_key_spammer_running():
            return
        self._root.after(0, self._stop_key_spammer)

    def trigger_mouse_clicker_start(self) -> None:
        if self._controller.is_mouse_clicker_running():
            return
        self._root.after(0, self._start_mouse_clicker)

    def trigger_mouse_clicker_stop(self) -> None:
        if not self._controller.is_mouse_clicker_running():
            return
        self._root.after(0, self._stop_mouse_clicker)

    def set_on_settings_saved(self, callback: callable) -> None:
        self._on_settings_saved = callback or (lambda: None)

    def _build_recorder_tab(self, parent: ctk.CTkFrame) -> None:
        rec = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
        rec.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(rec, text="Macro Recorder", font=ctk.CTkFont(weight="bold", size=16)).pack(anchor="w", padx=12, pady=(12, 8))
        self._recorded_count_var = ctk.StringVar(value="Recorded 0 events")
        ctk.CTkLabel(rec, textvariable=self._recorded_count_var).pack(anchor="w", padx=12, pady=(0, 4))
        ctk.CTkLabel(rec, text="Live events (keys, mouse, duration):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(4, 2))
        self._live_events_text = ctk.CTkTextbox(rec, height=180, wrap="word", state="normal")
        self._live_events_text.pack(fill="x", padx=12, pady=(0, 8))
        self._live_events_text.insert("1.0", "Start recording to see events here.\n")
        self._live_events_text.configure(state="disabled")

        btn_row = ctk.CTkFrame(rec, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=8)
        self._btn_record = ctk.CTkButton(btn_row, text="Record", fg_color=COLOR_ACCENT, hover_color="#00CC7D", text_color="#000", width=140,
                                         command=self._handle_record)
        self._btn_record.pack(side="left", padx=(0, 8))
        self._btn_stop_record = ctk.CTkButton(btn_row, text="Stop Recording", fg_color=COLOR_DANGER, hover_color="#CC2244", width=140,
                                              command=self._handle_stop_record)
        self._btn_stop_record.pack(side="left", padx=(0, 8))
        self._btn_stop_record.configure(state="disabled")

        save_row = ctk.CTkFrame(rec, fg_color="transparent")
        save_row.pack(fill="x", padx=12, pady=8)
        self._save_entry = ctk.CTkEntry(save_row, width=250, placeholder_text="Macro name")
        self._save_entry.pack(side="left", padx=(0, 8))
        self._btn_save_macro = ctk.CTkButton(save_row, text="Save as…", fg_color=COLOR_ACCENT, text_color="#000", width=100, command=self._handle_save_macro_quick)
        self._btn_save_macro.pack(side="left")

        self._rec_border = rec

    def _build_library_tab(self, parent: ctk.CTkFrame) -> None:
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 4))
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._refresh_library_list())
        ctk.CTkEntry(top, width=220, placeholder_text="Search macros…", textvariable=self._search_var).pack(side="left", padx=(0, 8))
        ctk.CTkButton(top, text="Refresh", width=80, command=self._refresh_library_list).pack(side="left")

        list_frame = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=8)
        list_frame.pack(fill="both", expand=True, padx=10, pady=4)
        self._library_listbox = ctk.CTkTextbox(list_frame, wrap="word", state="disabled")
        self._library_listbox.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self._library_info = ctk.CTkTextbox(list_frame, width=280, wrap="word", state="disabled")
        self._library_info.pack(side="right", fill="y", padx=6, pady=6)

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=8)
        ctk.CTkButton(btn_row, text="Load", width=90, command=self._handle_library_load).pack(side="left", padx=(0, 6))
        self._btn_library_play = ctk.CTkButton(btn_row, text="Play", width=90, fg_color=COLOR_ACCENT, text_color="#000", command=self._handle_library_play)
        self._btn_library_play.pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Delete", width=90, fg_color=COLOR_DANGER, command=self._handle_library_delete).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Export", width=90, command=self._handle_library_export).pack(side="left")

        # Macro playback speed (bottom card)
        speed_card = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color="#333")
        speed_card.pack(fill="x", padx=10, pady=(0, 10))
        speed_row = ctk.CTkFrame(speed_card, fg_color="transparent")
        speed_row.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(speed_row, text="Macro playback speed (0.5×–3×):", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self._quick_speed = ctk.CTkSlider(speed_row, from_=0.5, to=3.0, number_of_steps=25, width=140)
        self._quick_speed.set(float(self._settings.get("playback_speed", 1.0)))
        self._quick_speed.pack(side="left", padx=4)
        self._quick_speed_label = ctk.CTkLabel(speed_row, text="1.0×", font=ctk.CTkFont(size=12, weight="bold"), width=36)
        self._quick_speed_label.pack(side="left", padx=(0, 8))

        def on_speed_changed(v: float) -> None:
            if getattr(self, "_quick_speed_label", None):
                self._quick_speed_label.configure(text=f"{v:.1f}×")

        self._quick_speed.configure(command=on_speed_changed)
        on_speed_changed(self._quick_speed.get())

        self._refresh_library_list()

    def _refresh_library_list(self) -> None:
        macros = macro_storage.list_macros()
        q = (self._search_var.get() or "").strip().lower()
        if q:
            macros = [(n, p) for n, p in macros if q in n.lower()]
        lines = []
        for name, path in macros:
            info = macro_storage.get_macro_info(path)
            if info:
                dur = info.get("duration_sec", 0)
                count = info.get("event_count", 0)
                created = info.get("created", 0)
                dt = datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M") if created else "—"
                lines.append(f"{name}  |  {count} events  |  {dur:.1f}s  |  {dt}  |  {path}")
            else:
                lines.append(f"{name}  |  {path}")
        self._library_listbox.configure(state="normal")
        self._library_listbox.delete("1.0", "end")
        self._library_listbox.insert("1.0", "\n".join(lines) if lines else "No macros found.")
        self._library_listbox.configure(state="disabled")
        self._library_info.configure(state="normal")
        self._library_info.delete("1.0", "end")
        self._library_info.insert("1.0", "Select a macro (use Load/Play).\nPreview shows first 5 events after Load.")
        self._library_info.configure(state="disabled")

    def _get_selected_macro_path(self) -> str | None:
        # Simple: we don't have real selection in Textbox; user clicks Load/Play after viewing. Use first macro or prompt.
        macros = macro_storage.list_macros()
        q = (self._search_var.get() or "").strip().lower()
        if q:
            macros = [(n, p) for n, p in macros if q in n.lower()]
        return macros[0][1] if macros else None

    def _handle_library_load(self) -> None:
        path = self._get_selected_macro_path()
        if not path:
            return
        result = macro_storage.load_macro(path)
        if result is None:
            return
        name, events = result
        self._controller.set_recorded_events(events)
        self._current_macro_path = path
        self._current_macro_name = name
        preview = "\n".join(str(e) for e in events[:5])
        self._library_info.configure(state="normal")
        self._library_info.delete("1.0", "end")
        self._library_info.insert("1.0", f"Loaded: {name}\n\nFirst 5 events:\n{preview}")
        self._library_info.configure(state="disabled")
        self._set_status(f"Loaded: {name}")

    def _handle_library_play(self) -> None:
        events = self._controller.get_recorded_events()
        if not events and self._current_macro_path:
            loaded = macro_storage.load_macro(self._current_macro_path)
            if loaded:
                _, events = loaded
        if not events:
            return
        speed = getattr(self, "_quick_speed", None)
        speed_val = speed.get() if speed else 1.0
        rand = getattr(self, "_quick_randomize", None)
        randomize = rand.get() if rand else False
        self._controller.start_playback(events=events, speed=speed_val, randomize=randomize)
        self._set_status(f"Playing '{self._current_macro_name or 'macro'}' at {speed_val:.1f}×")

    def _handle_library_delete(self) -> None:
        path = self._get_selected_macro_path()
        if not path or not os.path.isfile(path):
            return
        try:
            os.remove(path)
            self._refresh_library_list()
            self._set_status("Macro deleted.")
        except OSError:
            pass

    def _handle_library_export(self) -> None:
        path = self._get_selected_macro_path()
        if not path:
            return
        result = macro_storage.load_macro(path)
        if result is None:
            return
        name, events = result
        save_path = ctk.filedialog.asksaveasfilename(
            initialdir=os.path.dirname(path), initialfile=name + ".json",
            defaultextension=".json", filetypes=[("JSON", "*.json")]
        )
        if save_path:
            import json
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump({"name": name, "events": events}, f, indent=2)
            self._set_status("Exported.")

    def _build_settings_tab(self, parent: ctk.CTkFrame) -> None:
        s = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        s.pack(fill="both", expand=True, padx=10, pady=10)

        # --- Profiles ---
        profiles_row = ctk.CTkFrame(s, fg_color="transparent")
        profiles_row.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(profiles_row, text="Profiles", font=ctk.CTkFont(weight="bold", size=14)).pack(side="left", padx=(0, 8))
        profile_names = sorted(self._profiles.keys()) if getattr(self, "_profiles", None) else []
        if not profile_names:
            profile_names = ["Default"]
            if "Default" not in self._profiles:
                self._profiles["Default"] = {
                    "settings": dict(self._settings),
                    "quick_actions": self._collect_quick_actions_state(),
                }
                profile_manager.save_profiles(self._profiles)
        self._profile_combo = ctk.CTkComboBox(profiles_row, values=profile_names, width=180, state="readonly",
                                              command=self._on_profile_selected)
        self._profile_combo.pack(side="left", padx=(0, 8))
        self._profile_combo.set(profile_names[0])
        self._current_profile = profile_names[0]
        self._btn_profile_save_as = ctk.CTkButton(profiles_row, text="Save as…", width=90, fg_color=COLOR_ACCENT, text_color="#000", command=self._handle_profile_save_as)
        self._btn_profile_save_as.pack(side="left", padx=2)
        self._btn_profile_overwrite = ctk.CTkButton(profiles_row, text="Overwrite", width=90, fg_color=COLOR_ACCENT, text_color="#000", command=self._handle_profile_overwrite)
        self._btn_profile_overwrite.pack(side="left", padx=2)
        ctk.CTkButton(profiles_row, text="Delete", width=90, fg_color=COLOR_DANGER, command=self._handle_profile_delete).pack(side="left", padx=2)

        # --- Color profile ---
        ctk.CTkLabel(s, text="Color profile", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(16, 6))
        color_row = ctk.CTkFrame(s, fg_color="transparent")
        color_row.pack(anchor="w", pady=(0, 12))
        current_color = self._settings.get("color_profile", "green")
        self._color_profile_buttons: list[tuple[str, ctk.CTkButton]] = []
        for profile_id, (fg, hover) in COLOR_PROFILES.items():
            is_current = profile_id == current_color
            btn = ctk.CTkButton(
                color_row,
                text=profile_id.capitalize(),
                width=72,
                height=28,
                fg_color=fg if is_current else "#3a3a3a",
                hover_color=hover,
                text_color="#000" if profile_id in ("green", "amber") else "#fff",
                command=lambda p=profile_id: self._on_color_profile_selected(p),
            )
            btn.pack(side="left", padx=2)
            self._color_profile_buttons.append((profile_id, btn))

        # --- Paths & startup ---
        ctk.CTkLabel(s, text="Paths & startup", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(16, 8))
        run_startup = ctk.CTkCheckBox(s, text="Run on Windows startup")
        run_startup.pack(anchor="w", pady=4)
        if self._settings.get("run_on_startup"):
            run_startup.select()
        ctk.CTkLabel(s, text="Macro storage path", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        path_entry = ctk.CTkEntry(s, width=400, placeholder_text=config.get_macros_dir())
        path_entry.insert(0, self._settings.get("macros_dir_override", "") or config.get_macros_dir())
        path_entry.pack(anchor="w", pady=(0, 12))

        # --- Hotkeys ---
        ctk.CTkLabel(s, text="Hotkeys", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(16, 8))
        ctk.CTkLabel(s, text="Emergency stop (exits app)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(0, 4))
        hotkey_entry = ctk.CTkEntry(s, width=200, placeholder_text="ctrl+shift+f12")
        hotkey_entry.insert(0, self._settings.get("emergency_hotkey", config.EMERGENCY_HOTKEY))
        hotkey_entry.pack(anchor="w", pady=(0, 12))

        # --- Randomization ---
        ctk.CTkLabel(s, text="Randomization", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(16, 8))
        ctk.CTkLabel(s, text="Timing jitter (ms)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(0, 4))
        rmin = ctk.CTkEntry(s, width=80, placeholder_text="5")
        rmin.insert(0, str(self._settings.get("randomize_time_ms_min", 5)))
        rmin.pack(anchor="w", pady=2)
        self._restrict_entry_to_digits(rmin)
        rmax = ctk.CTkEntry(s, width=80, placeholder_text="15")
        rmax.insert(0, str(self._settings.get("randomize_time_ms_max", 15)))
        rmax.pack(anchor="w", pady=(0, 12))
        self._restrict_entry_to_digits(rmax)

        ctk.CTkLabel(s, text="Randomization (mouse noise px)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        pxmin = ctk.CTkEntry(s, width=80)
        pxmin.insert(0, str(self._settings.get("randomize_mouse_px_min", 1)))
        pxmin.pack(anchor="w", pady=2)
        self._restrict_entry_to_digits(pxmin)
        pxmax = ctk.CTkEntry(s, width=80)
        pxmax.insert(0, str(self._settings.get("randomize_mouse_px_max", 4)))
        pxmax.pack(anchor="w", pady=(0, 12))
        self._restrict_entry_to_digits(pxmax)

        ctk.CTkLabel(s, text="Start recording hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        start_rec_row = ctk.CTkFrame(s, fg_color="transparent")
        start_rec_row.pack(anchor="w", pady=2)
        start_rec_entry = ctk.CTkEntry(start_rec_row, width=180, placeholder_text="f9")
        start_rec_entry.insert(0, self._settings.get("start_recording_hotkey", "f9"))
        start_rec_entry.pack(side="left", padx=(0, 8))
        self._settings_record_key_buttons: list[ctk.CTkButton] = []
        _btn = ctk.CTkButton(start_rec_row, text="Record key", width=100, fg_color=COLOR_ACCENT, text_color="#000",
                             command=lambda: self._record_hotkey("Start recording", start_rec_entry))
        _btn.pack(side="left")
        self._settings_record_key_buttons.append(_btn)
        ctk.CTkLabel(s, text="Stop recording hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        stop_rec_row = ctk.CTkFrame(s, fg_color="transparent")
        stop_rec_row.pack(anchor="w", pady=2)
        stop_rec_entry = ctk.CTkEntry(stop_rec_row, width=180, placeholder_text="f10")
        stop_rec_entry.insert(0, self._settings.get("stop_recording_hotkey", "f10"))
        stop_rec_entry.pack(side="left", padx=(0, 8))
        _btn = ctk.CTkButton(stop_rec_row, text="Record key", width=100, fg_color=COLOR_ACCENT, text_color="#000",
                             command=lambda: self._record_hotkey("Stop recording", stop_rec_entry))
        _btn.pack(side="left")
        self._settings_record_key_buttons.append(_btn)
        ctk.CTkLabel(s, text="Key Spammer start hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 4))
        key_spam_start_row = ctk.CTkFrame(s, fg_color="transparent")
        key_spam_start_row.pack(anchor="w", pady=2)
        key_spammer_start_entry = ctk.CTkEntry(key_spam_start_row, width=180, placeholder_text="f7")
        key_spammer_start_entry.insert(0, self._settings.get("key_spammer_start_hotkey", "f7"))
        key_spammer_start_entry.pack(side="left", padx=(0, 8))
        _btn = ctk.CTkButton(key_spam_start_row, text="Record key", width=100, fg_color=COLOR_ACCENT, text_color="#000",
                             command=lambda: self._record_hotkey("Key Spammer start", key_spammer_start_entry))
        _btn.pack(side="left")
        self._settings_record_key_buttons.append(_btn)
        ctk.CTkLabel(s, text="Key Spammer stop hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        key_spam_stop_row = ctk.CTkFrame(s, fg_color="transparent")
        key_spam_stop_row.pack(anchor="w", pady=2)
        key_spammer_stop_entry = ctk.CTkEntry(key_spam_stop_row, width=180, placeholder_text="f8")
        key_spammer_stop_entry.insert(0, self._settings.get("key_spammer_stop_hotkey", "f8"))
        key_spammer_stop_entry.pack(side="left", padx=(0, 8))
        _btn = ctk.CTkButton(key_spam_stop_row, text="Record key", width=100, fg_color=COLOR_ACCENT, text_color="#000",
                             command=lambda: self._record_hotkey("Key Spammer stop", key_spammer_stop_entry))
        _btn.pack(side="left")
        self._settings_record_key_buttons.append(_btn)
        ctk.CTkLabel(s, text="Mouse Clicker start hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 4))
        mouse_start_row = ctk.CTkFrame(s, fg_color="transparent")
        mouse_start_row.pack(anchor="w", pady=2)
        mouse_clicker_start_entry = ctk.CTkEntry(mouse_start_row, width=180, placeholder_text="f5")
        mouse_clicker_start_entry.insert(0, self._settings.get("mouse_clicker_start_hotkey", "f5"))
        mouse_clicker_start_entry.pack(side="left", padx=(0, 8))
        _btn = ctk.CTkButton(mouse_start_row, text="Record key", width=100, fg_color=COLOR_ACCENT, text_color="#000",
                             command=lambda: self._record_hotkey("Mouse Clicker start", mouse_clicker_start_entry))
        _btn.pack(side="left")
        self._settings_record_key_buttons.append(_btn)
        ctk.CTkLabel(s, text="Mouse Clicker stop hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        mouse_stop_row = ctk.CTkFrame(s, fg_color="transparent")
        mouse_stop_row.pack(anchor="w", pady=2)
        mouse_clicker_stop_entry = ctk.CTkEntry(mouse_stop_row, width=180, placeholder_text="f6")
        mouse_clicker_stop_entry.insert(0, self._settings.get("mouse_clicker_stop_hotkey", "f6"))
        mouse_clicker_stop_entry.pack(side="left", padx=(0, 8))
        _btn = ctk.CTkButton(mouse_stop_row, text="Record key", width=100, fg_color=COLOR_ACCENT, text_color="#000",
                             command=lambda: self._record_hotkey("Mouse Clicker stop", mouse_clicker_stop_entry))
        _btn.pack(side="left")
        self._settings_record_key_buttons.append(_btn)
        ctk.CTkLabel(s, text="", height=0).pack(anchor="w", pady=(0, 8))

        # --- Anti-Detection / Humanization ---
        ctk.CTkLabel(s, text="Anti-Detection / Humanization", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(16, 8))
        self._adv_human_cb = ctk.CTkCheckBox(s, text="Enable Advanced Humanization (gaussian jitter, drift, micro-pauses)")
        self._adv_human_cb.pack(anchor="w", pady=4)
        if self._settings.get("advanced_humanization_enabled", True):
            self._adv_human_cb.select()
        adv_human = self._adv_human_cb
        humanization_status_var = ctk.StringVar(value="Current: Off")
        HUMANIZATION_LABELS = ("Off", "Low", "Medium", "High", "Paranoid")

        def _update_humanization_status() -> None:
            idx = min(4, max(0, int(round(intensity_slider.get()))))
            adv = adv_human.get()
            nulls = insert_nulls_cb.get()
            qpc = use_qpc_cb.get()
            # Recommended flags for each intensity level
            # 0: Off, 1: Low, 2: Medium, 3: High, 4: Paranoid
            defaults = {
                0: (False, False, False),
                1: (True, False, False),
                2: (True, True, False),
                3: (True, True, True),
                4: (True, True, True),
            }
            expected = defaults.get(idx)
            if expected is not None and expected == (adv, nulls, qpc):
                humanization_status_var.set(f"Current: {HUMANIZATION_LABELS[idx]}")
            else:
                humanization_status_var.set("Current: Custom")

        def update_humanization_label(val: float) -> None:
            _update_humanization_status()

        ctk.CTkLabel(s, text="Humanization intensity: Low / Medium / High / Paranoid").pack(anchor="w", pady=(8, 2))
        self._intensity_slider = ctk.CTkSlider(s, from_=0, to=4, number_of_steps=4, width=200,
                                               command=update_humanization_label)
        self._intensity_slider.set(self._settings.get("humanization_intensity", 0))
        self._intensity_slider.pack(anchor="w", pady=2)
        intensity_slider = self._intensity_slider
        ctk.CTkLabel(s, textvariable=humanization_status_var, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=0, pady=(0, 4))
        self._insert_nulls_cb = ctk.CTkCheckBox(s, text="Insert 1–2 null SendInput between events (pattern break)")
        self._insert_nulls_cb.pack(anchor="w", pady=4)
        if self._settings.get("insert_nulls"):
            self._insert_nulls_cb.select()
        insert_nulls_cb = self._insert_nulls_cb
        self._use_qpc_cb = ctk.CTkCheckBox(s, text="Use QueryPerformanceCounter in INPUT time field")
        self._use_qpc_cb.pack(anchor="w", pady=4)
        if self._settings.get("use_qpc_time"):
            self._use_qpc_cb.select()
        use_qpc_cb = self._use_qpc_cb
        HUMANIZATION_FEATURES = [
            ("Gaussian delay jitter", 1),
            ("Variable key hold", 1),
            ("Session drift (±%)", 2),
            ("Micro-pauses", 3),
            ("Insert nulls", "cb_nulls"),
            ("Use QPC time", "cb_qpc"),
        ]
        humanization_feature_labels: list[ctk.CTkLabel] = []
        humanization_frame = ctk.CTkFrame(s, fg_color="transparent")

        def update_humanization_features() -> None:
            adv = adv_human.get()
            intensity = int(round(intensity_slider.get()))
            nulls = insert_nulls_cb.get()
            qpc = use_qpc_cb.get()
            for i, (label_text, req) in enumerate(HUMANIZATION_FEATURES):
                if req == "cb_nulls":
                    on = nulls
                elif req == "cb_qpc":
                    on = qpc
                else:
                    on = adv and intensity >= req
                accent = COLOR_PROFILES.get(self._settings.get("color_profile", "green"), (COLOR_ACCENT,))[0]
                color = accent if on else "#FF2D55"
                if i < len(humanization_feature_labels):
                    humanization_feature_labels[i].configure(text_color=color)
            _update_humanization_status()

        for feat_name, _ in HUMANIZATION_FEATURES:
            lbl = ctk.CTkLabel(humanization_frame, text=f"• {feat_name}", font=ctk.CTkFont(size=12))
            humanization_feature_labels.append(lbl)
            lbl.pack(anchor="w", padx=(0, 8), pady=1)
        humanization_frame.pack(anchor="w", pady=(4, 8))
        self._update_humanization_features_cb = update_humanization_features
        update_humanization_features()
        intensity_slider.configure(command=lambda v: (update_humanization_label(v), update_humanization_features()))
        adv_human.configure(command=lambda: update_humanization_features())
        insert_nulls_cb.configure(command=update_humanization_features)
        use_qpc_cb.configure(command=update_humanization_features)
        self._obfuscate_cb = ctk.CTkCheckBox(s, text="Obfuscate process name on launch (random generic title)")
        self._obfuscate_cb.pack(anchor="w", pady=4)
        if self._settings.get("obfuscate_process_name"):
            self._obfuscate_cb.select()
        obfuscate_cb = self._obfuscate_cb
        ctk.CTkLabel(s, text="Generic window title (overrides app name when set)").pack(anchor="w", pady=(8, 2))
        generic_title_entry = ctk.CTkEntry(s, width=300, placeholder_text="e.g. System Monitor")
        generic_title_entry.insert(0, self._settings.get("generic_window_title", ""))
        generic_title_entry.pack(anchor="w", pady=(0, 12))

        def save_settings_cb() -> None:
            try:
                self._settings["randomize_time_ms_min"] = int(rmin.get().strip() or 5)
                self._settings["randomize_time_ms_max"] = int(rmax.get().strip() or 15)
                self._settings["randomize_mouse_px_min"] = int(pxmin.get().strip() or 1)
                self._settings["randomize_mouse_px_max"] = int(pxmax.get().strip() or 4)
                self._settings["emergency_hotkey"] = hotkey_entry.get().strip() or config.EMERGENCY_HOTKEY
                self._settings["start_recording_hotkey"] = start_rec_entry.get().strip() or "f9"
                self._settings["stop_recording_hotkey"] = stop_rec_entry.get().strip() or "f10"
                self._settings["key_spammer_start_hotkey"] = key_spammer_start_entry.get().strip() or "f7"
                self._settings["key_spammer_stop_hotkey"] = key_spammer_stop_entry.get().strip() or "f8"
                self._settings["mouse_clicker_start_hotkey"] = mouse_clicker_start_entry.get().strip() or "f5"
                self._settings["mouse_clicker_stop_hotkey"] = mouse_clicker_stop_entry.get().strip() or "f6"
                self._settings["run_on_startup"] = run_startup.get()
                self._settings["macros_dir_override"] = path_entry.get().strip()
                self._settings["always_on_top"] = self._always_on_top_var.get() if self._always_on_top_var else False
                self._settings["window_transparency"] = float(self._window_transparency)
                self._settings["advanced_humanization_enabled"] = adv_human.get()
                self._settings["humanization_intensity"] = int(round(intensity_slider.get()))
                self._settings["insert_nulls"] = insert_nulls_cb.get()
                self._settings["use_qpc_time"] = use_qpc_cb.get()
                self._settings["obfuscate_process_name"] = obfuscate_cb.get()
                self._settings["generic_window_title"] = generic_title_entry.get().strip()
            except ValueError:
                pass
            settings_manager.save_settings(self._settings)
            config.update_from_settings(self._settings)
            self._apply_window_title()
            self._apply_macros_dir_override()
            self._update_always_on_top()
            self._window_transparency = self._settings["window_transparency"]
            if self._transparency_slider is not None:
                self._transparency_slider.set(self._window_transparency)
                self._update_transparency_label(self._window_transparency)
            self._on_transparency_changed(self._window_transparency)
            self._on_settings_saved()
            self._set_status("Settings saved. Hotkeys updated.")

        self._btn_save_settings = ctk.CTkButton(s, text="Save settings", fg_color=COLOR_ACCENT, text_color="#000", command=save_settings_cb)
        self._btn_save_settings.pack(anchor="w", pady=16)

        # --- About ---
        ctk.CTkLabel(s, text="About", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(16, 8))
        ctk.CTkLabel(s, text=f"{config.APP_NAME}  v{config.APP_VERSION}", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(s, text="Professional macro recorder & playback with Key Presser and Mouse Clicker.").pack(anchor="w", pady=(0, 8))

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self._root, fg_color=COLOR_CARD, corner_radius=6, height=36)
        bar.pack(fill="x", padx=10, pady=(6, 4))
        bar.pack_propagate(False)
        self._status_var = ctk.StringVar(value="")
        ctk.CTkLabel(bar, textvariable=self._status_var).pack(side="left", padx=12, pady=8)
        self._progress_var = ctk.DoubleVar(value=0.0)
        self._progress_bar = ctk.CTkProgressBar(bar, variable=self._progress_var, width=200)
        self._progress_bar.pack(side="right", padx=12, pady=8)
        self._progress_bar.pack_forget()  # show only during playback
        footer = ctk.CTkLabel(self._root, text="Created by: Solve4x", font=ctk.CTkFont(size=11))
        footer.pack(pady=(0, 10))

    def _set_status(self, text: str) -> None:
        if self._status_var:
            self._status_var.set(text)

    def _on_state_change(self, state: str) -> None:
        self._root.after(0, lambda: self._update_state_badge())
        self._root.after(0, lambda: self._update_recorder_buttons())
        self._root.after(0, lambda: self._update_recorded_count())
        if state == State.IDLE and self._progress_bar:
            self._progress_bar.pack_forget()
            if self._progress_var:
                self._progress_var.set(0.0)

    def _update_state_badge(self) -> None:
        if not self._state_badge:
            return
        s = self._controller.get_state()
        if self._controller.is_key_spammer_running() or self._controller.is_mouse_clicker_running():
            label = "Spamming / Clicking"
        elif s == State.RECORDING:
            label = "Recording"
        elif s == State.PLAYING:
            label = "Playing"
        elif s == State.PAUSED:
            label = "Paused"
        else:
            label = "Idle"
        self._state_badge.configure(text=label)

    def _update_recorder_buttons(self) -> None:
        s = self._controller.get_state()
        self._btn_record.configure(state="normal" if s == State.IDLE else "disabled")
        self._btn_stop_record.configure(state="normal" if s == State.RECORDING else "disabled")

    def _update_recorded_count(self) -> None:
        if self._recorded_count_var:
            n = len(self._controller.get_recorded_events())
            self._recorded_count_var.set(f"Recorded {n} events")

    def _handle_record(self) -> None:
        self._live_events_text.configure(state="normal")
        self._live_events_text.delete("1.0", "end")
        self._live_events_text.insert("1.0", "Recording… (use hotkey or Stop to end)\n")
        self._live_events_text.configure(state="disabled")
        self._controller.start_recording()
        self._set_status("Recording – Press Stop or hotkey when done")

    def _handle_stop_record(self) -> None:
        self._controller.stop_recording()
        self._update_recorded_count()
        self._set_status("Recording saved in memory. Save as… or play from Macro Library.")

    def _handle_save_macro_quick(self) -> None:
        events = self._controller.get_recorded_events()
        if not events:
            return
        name = (self._save_entry.get() or "macro").strip() or "macro"
        macro_storage.save_macro(name, events)
        self._current_macro_name = name
        self._current_macro_path = os.path.join(config.get_macros_dir(), name.replace(" ", "_") + ".json")
        self._set_status(f"Saved: {name}")
        self._save_entry.delete(0, "end")

    def run(self) -> None:
        self._root.mainloop()
