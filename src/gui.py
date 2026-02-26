"""
Professional customtkinter GUI: 4 tabs (Quick Actions, Macro Recorder, Macro Library, Settings).
Toolbar with state badge and emergency stop; status bar with progress.
ACT-style overlay: always-on-top, click-through by default, hotkey toggles interactivity.
"""

import os
from datetime import datetime

import ctypes
from ctypes import wintypes

import customtkinter as ctk

from src import config

# --- Overlay mode (ACT-style): topmost + toggleable click-through ---
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
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
    """Get HWND from tkinter/CTk root for Win32 overlay APIs."""
    return wintypes.HWND(root.winfo_id())


from src.controllers.playback_controller import PlaybackController, State
from src import macro_storage
from src import settings_manager

# Visual style (theme-aware: light, dark)
COLOR_ACCENT = "#00FF9D"
COLOR_DANGER = "#FF2D55"
COLOR_CARD = ("#E8E8E8", "#2A2A2A")  # light mode, dark mode
COLOR_BORDER = ("#ccc", "#333")
MIN_WIDTH = 900
MIN_HEIGHT = 620
INTERVAL_MAX_MS = 600_000  # 10 minutes


class AppGui:
    def __init__(self, controller: PlaybackController, on_settings_saved: callable = None) -> None:
        self._controller = controller
        self._on_settings_saved = on_settings_saved or (lambda: None)
        self._current_macro_path: str | None = None
        self._current_macro_name: str | None = None
        self._settings = settings_manager.load_settings()
        self._apply_macros_dir_override()
        self._recorded_count_var: ctk.StringVar | None = None
        self._progress_var: ctk.DoubleVar | None = None
        self._progress_bar: ctk.CTkProgressBar | None = None
        self._state_badge: ctk.CTkLabel | None = None
        self._status_var: ctk.StringVar | None = None
        self._playback_progress_job: str | None = None
        self._overlay_toggle_btn: ctk.CTkButton | None = None
        self._overlay_status_label: ctk.CTkLabel | None = None
        self._is_click_through = False
        self._overlay_enforced = False
        self._overlay_opacity = float(self._settings.get("overlay_opacity", 1.0))
        self._configure_after_id: str | None = None
        self._overlay_transparency_slider: ctk.CTkSlider | None = None
        self._overlay_click_through_cb: ctk.CTkCheckBox | None = None

        ctk.set_appearance_mode(self._settings.get("theme", "Dark"))
        ctk.set_default_color_theme("green")
        self._root = ctk.CTk()
        self._apply_window_title()
        self._root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._root.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}")
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
        self._root.after(400, self._maybe_setup_overlay_mode)

    def _on_configure(self, event) -> None:
        """Force complete redraw on resize to eliminate ghosting with layered windows."""
        if self._configure_after_id:
            self._root.after_cancel(self._configure_after_id)
        self._configure_after_id = self._root.after(10, self._force_full_redraw)

    def _force_full_redraw(self) -> None:
        """Full redraw of window and all children; re-apply overlay style after redraw."""
        self._configure_after_id = None
        try:
            hwnd = get_hwnd(self._root)
            user32.RedrawWindow(
                hwnd, None, None,
                RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN | RDW_ERASE,
            )
            self._root.update_idletasks()
            self._root.update()
            self._reapply_overlay_style()
        except Exception:
            pass

    def _is_layered(self) -> bool:
        try:
            hwnd = get_hwnd(self._root)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            return bool(style & WS_EX_LAYERED)
        except Exception:
            return False

    def _maybe_setup_overlay_mode(self) -> None:
        if self._settings.get("start_in_overlay_mode", False):
            self.setup_overlay_mode()

    def _get_overlay_opacity(self) -> float:
        if self._overlay_transparency_slider is not None:
            return float(self._overlay_transparency_slider.get())
        return self._overlay_opacity

    def _get_overlay_click_through(self) -> bool:
        if self._overlay_click_through_cb is not None:
            return self._overlay_click_through_cb.get()
        return self._is_click_through

    def _reapply_overlay_style(self) -> None:
        """Re-apply current click-through state after resize (topmost/layered already set)."""
        if not self._overlay_enforced:
            return
        try:
            hwnd = get_hwnd(self._root)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if self._is_click_through:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED)
        except Exception:
            pass

    def setup_overlay_mode(self) -> None:
        try:
            self._root.update_idletasks()
            hwnd = get_hwnd(self._root)
            self._overlay_opacity = self._get_overlay_opacity()
            self._is_click_through = self._get_overlay_click_through()

            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_TOPMOST
            if self._overlay_opacity < 1.0:
                style |= WS_EX_LAYERED
            if self._is_click_through:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED)

            if self._overlay_opacity < 1.0:
                user32.SetLayeredWindowAttributes(hwnd, 0, int(self._overlay_opacity * 255), LWA_ALPHA)

            self._root.resizable(False, False)
            self._overlay_enforced = True
            self._enforce_topmost()
            self._update_overlay_ui_text()
            self._root.attributes("-alpha", self._overlay_opacity)
            self._force_full_redraw()
        except Exception:
            self._overlay_enforced = False

    def _enforce_topmost(self) -> None:
        if not self._overlay_enforced:
            return
        try:
            hwnd = get_hwnd(self._root)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        except Exception:
            pass
        self._root.after(100, self._enforce_topmost)

    def _overlay_hotkey_display(self) -> str:
        return (self._settings.get("overlay_toggle_hotkey") or "ctrl+alt+o").replace("+", "+").upper()

    def _update_overlay_ui_text(self) -> None:
        hotkey = self._overlay_hotkey_display()
        if self._overlay_status_label:
            if self._is_click_through:
                self._overlay_status_label.configure(
                    text=f"Click-through ON – Press {hotkey} to unlock (button cannot be clicked)"
                )
            else:
                self._overlay_status_label.configure(text="Interactive Mode – Click Lock Overlay or use hotkey")
        if self._overlay_toggle_btn:
            if self._is_click_through:
                self._overlay_toggle_btn.configure(
                    text="Unlock Overlay", fg_color=COLOR_DANGER, hover_color="#CC2244", text_color="white"
                )
            else:
                self._overlay_toggle_btn.configure(
                    text="Lock Overlay", fg_color=COLOR_ACCENT, hover_color="#00CC7D", text_color="#000"
                )

    def toggle_click_through(self) -> None:
        if not self._overlay_enforced:
            return
        try:
            hwnd = get_hwnd(self._root)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            if self._is_click_through:
                style &= ~WS_EX_TRANSPARENT
                self._is_click_through = False
                self._root.attributes("-alpha", 1.0)
                self._root.resizable(True, True)
            else:
                style |= WS_EX_TRANSPARENT
                self._is_click_through = True
                self._root.attributes("-alpha", self._overlay_opacity)
                self._root.resizable(False, False)

            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED)

            if self._overlay_click_through_cb is not None:
                if self._is_click_through:
                    self._overlay_click_through_cb.select()
                else:
                    self._overlay_click_through_cb.deselect()
            self._update_overlay_ui_text()
            self._force_full_redraw()
        except Exception:
            pass

    def _on_transparency_changed(self, value: float) -> None:
        self._overlay_opacity = value
        try:
            self._root.attributes("-alpha", value)
            hwnd = get_hwnd(self._root)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            insert_after = HWND_TOPMOST if self._overlay_enforced else 0
            if value < 1.0:
                style |= WS_EX_LAYERED
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
                user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED)
                user32.SetLayeredWindowAttributes(hwnd, 0, int(value * 255), LWA_ALPHA)
            else:
                style &= ~WS_EX_LAYERED
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
                user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED)
            self._force_full_redraw()
        except Exception:
            pass

    def _on_click_through_changed(self) -> None:
        self._is_click_through = self._get_overlay_click_through()
        if not self._overlay_enforced:
            return
        self._reapply_overlay_style()

    def _apply_macros_dir_override(self) -> None:
        override = self._settings.get("macros_dir_override", "").strip()
        if override and os.path.isdir(override):
            config.set_macros_dir(override)
        else:
            config.set_macros_dir(None)

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

        self._overlay_toggle_btn = ctk.CTkButton(
            toolbar, text="Enable Overlay", fg_color=COLOR_ACCENT, hover_color="#00CC7D", text_color="#000",
            font=ctk.CTkFont(size=12, weight="bold"), command=self._handle_overlay_toggle,
            width=140, height=32
        )
        self._overlay_toggle_btn.pack(side="right", padx=8, pady=10)
        self._overlay_toggle_btn.configure(cursor="hand2")
        self._overlay_toggle_btn.bind(
            "<Enter>",
            lambda e: self._root.after(0, lambda: self.toggle_click_through() if self._is_click_through else None),
        )

        stop_btn = ctk.CTkButton(
            toolbar, text="EMERGENCY STOP", fg_color=COLOR_DANGER, hover_color="#CC2244",
            font=ctk.CTkFont(size=12, weight="bold"), command=self._controller.emergency_stop,
            width=140, height=32
        )
        stop_btn.pack(side="right", padx=12, pady=10)
        stop_btn.configure(cursor="hand2")

        overlay_row = ctk.CTkFrame(self._root, fg_color="transparent")
        overlay_row.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(overlay_row, text="Opacity:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        def on_opacity_slider(v: float) -> None:
            self._update_opacity_label(v)
            self._on_transparency_changed(v)

        self._overlay_transparency_slider = ctk.CTkSlider(
            overlay_row, from_=0.5, to=1.0, number_of_steps=10, width=120, command=on_opacity_slider
        )
        self._overlay_transparency_slider.set(self._settings.get("overlay_opacity", 1.0))
        self._update_opacity_label(self._overlay_transparency_slider.get())
        self._overlay_transparency_slider.pack(side="left", padx=(0, 8))
        self._overlay_opacity_label = ctk.CTkLabel(overlay_row, text="100%", font=ctk.CTkFont(size=12), width=36)
        self._overlay_opacity_label.pack(side="left", padx=(0, 16))
        self._overlay_click_through_cb = ctk.CTkCheckBox(overlay_row, text="Click-through", command=self._on_click_through_changed)
        self._overlay_click_through_cb.pack(side="left", padx=0)
        if self._settings.get("overlay_click_through", False):
            self._overlay_click_through_cb.select()
        self._update_opacity_label(self._overlay_transparency_slider.get())

    def _update_opacity_label(self, value: float) -> None:
        if getattr(self, "_overlay_opacity_label", None):
            self._overlay_opacity_label.configure(text=f"{int(round(value * 100))}%")

    def _build_tabs(self) -> None:
        tabview = ctk.CTkTabview(self._root, fg_color=COLOR_CARD, corner_radius=8)
        tabview.pack(fill="both", expand=True, padx=10, pady=6)

        tabview.add("Quick Actions")
        tabview.add("Macro Recorder")
        tabview.add("Macro Library")
        tabview.add("Settings")
        tabview.set("Quick Actions")

        self._build_quick_actions_tab(tabview.tab("Quick Actions"))
        self._build_recorder_tab(tabview.tab("Macro Recorder"))
        self._build_library_tab(tabview.tab("Macro Library"))
        self._build_settings_tab(tabview.tab("Settings"))

    def _build_quick_actions_tab(self, parent: ctk.CTkFrame) -> None:
        # Two panels side by side
        panes = ctk.CTkFrame(parent, fg_color="transparent")
        panes.pack(fill="both", expand=True, padx=10, pady=10)

        # Key Press Spammer
        key_frame = ctk.CTkFrame(panes, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color="#333")
        key_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ctk.CTkLabel(key_frame, text="Key Press Spammer", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))

        key_names = sorted(config.SCAN_CODES.keys(), key=lambda x: (x not in ["space", "enter", "shift", "ctrl", "alt"], x))
        key_combo = ctk.CTkComboBox(key_frame, values=key_names, width=180, state="readonly")
        key_combo.set("space")
        key_combo.pack(anchor="w", padx=12, pady=4)

        tap_hold = ctk.CTkSegmentedButton(key_frame, values=["Tap", "Hold"])
        tap_hold.pack(anchor="w", padx=12, pady=4)
        tap_hold.set("Tap")

        ctk.CTkLabel(key_frame, text="Interval (ms): 50 – 600000 (10 min)").pack(anchor="w", padx=12, pady=(8, 0))
        key_interval_entry = ctk.CTkEntry(key_frame, width=80, placeholder_text="200")
        key_interval_entry.insert(0, "200")
        key_interval_entry.pack(anchor="w", padx=12, pady=2)
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

        key_interval_display_var = ctk.StringVar(value="Last interval: — ms")
        key_interval_display = ctk.CTkLabel(key_frame, textvariable=key_interval_display_var, font=ctk.CTkFont(size=13, weight="bold"), text_color="#00FF9D")
        key_interval_display.pack(anchor="w", padx=12, pady=(4, 0))
        key_start = ctk.CTkButton(key_frame, text="Start Spamming", fg_color=COLOR_ACCENT, hover_color="#00CC7D", text_color="#000",
                                   command=lambda: self._start_key_spammer(key_combo, tap_hold, key_interval, key_interval_entry, key_count_infinite, key_count_entry, key_start, key_stop, key_interval_display_var))
        key_start.pack(pady=12, padx=12, fill="x")
        key_stop = ctk.CTkButton(key_frame, text="Stop", fg_color=COLOR_DANGER, hover_color="#CC2244",
                                 command=lambda: self._stop_key_spammer(key_start, key_stop, key_interval_display_var))
        key_stop.pack(pady=(0, 12), padx=12, fill="x")
        key_stop.configure(state="disabled")
        self._quick_key_combo = key_combo
        self._quick_tap_hold = tap_hold
        self._quick_key_interval_slider = key_interval
        self._quick_key_interval_entry = key_interval_entry
        self._quick_key_count_infinite = key_count_infinite
        self._quick_key_count_entry = key_count_entry
        self._quick_key_start_btn = key_start
        self._quick_key_stop_btn = key_stop
        self._quick_key_interval_display_var = key_interval_display_var

        # Mouse Auto-Clicker
        mouse_frame = ctk.CTkFrame(panes, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color="#333")
        mouse_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))
        ctk.CTkLabel(mouse_frame, text="Mouse Auto-Clicker", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))

        mouse_btn = ctk.CTkSegmentedButton(mouse_frame, values=["Left Click", "Right Click"])
        mouse_btn.pack(anchor="w", padx=12, pady=4)
        mouse_btn.set("Left Click")

        ctk.CTkLabel(mouse_frame, text="Interval (ms): 50 – 600000 (10 min)").pack(anchor="w", padx=12, pady=(8, 0))
        mouse_interval_entry = ctk.CTkEntry(mouse_frame, width=80, placeholder_text="200")
        mouse_interval_entry.insert(0, "200")
        mouse_interval_entry.pack(anchor="w", padx=12, pady=2)
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

        mouse_interval_display_var = ctk.StringVar(value="Last interval: — ms")
        mouse_interval_display = ctk.CTkLabel(mouse_frame, textvariable=mouse_interval_display_var, font=ctk.CTkFont(size=13, weight="bold"), text_color="#00FF9D")
        mouse_interval_display.pack(anchor="w", padx=12, pady=(4, 0))
        mouse_start = ctk.CTkButton(mouse_frame, text="Start Clicking", fg_color=COLOR_ACCENT, hover_color="#00CC7D", text_color="#000",
                                   command=lambda: self._start_mouse_clicker(mouse_btn, mouse_interval, mouse_interval_entry, mouse_count_infinite, mouse_count_entry, mouse_start, mouse_stop, mouse_interval_display_var))
        mouse_start.pack(pady=12, padx=12, fill="x")
        mouse_stop = ctk.CTkButton(mouse_frame, text="Stop", fg_color=COLOR_DANGER, hover_color="#CC2244",
                                   command=lambda: self._stop_mouse_clicker(mouse_start, mouse_stop, mouse_interval_display_var))
        mouse_stop.pack(pady=(0, 12), padx=12, fill="x")
        mouse_stop.configure(state="disabled")
        self._quick_mouse_btn = mouse_btn
        self._quick_mouse_interval_slider = mouse_interval
        self._quick_mouse_interval_entry = mouse_interval_entry
        self._quick_mouse_count_infinite = mouse_count_infinite
        self._quick_mouse_count_entry = mouse_count_entry
        self._quick_mouse_start_btn = mouse_start
        self._quick_mouse_stop_btn = mouse_stop
        self._quick_mouse_interval_display_var = mouse_interval_display_var

        # Shared: randomization, speed, at bottom of tab
        shared = ctk.CTkFrame(parent, fg_color="transparent")
        shared.pack(fill="x", padx=10, pady=10)
        self._quick_randomize = ctk.CTkCheckBox(shared, text="Global randomization (micro-jitter)")
        self._quick_randomize.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(shared, text="Playback speed:").pack(side="left", padx=(0, 6))
        self._quick_speed = ctk.CTkSlider(shared, from_=0.5, to=3.0, number_of_steps=25, width=120)
        self._quick_speed.set(1.0)
        self._quick_speed.pack(side="left", padx=6)

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

    def _start_key_spammer(self, combo, tap_hold, slider, entry, infinite_cb, count_entry, start_btn, stop_btn, interval_display_var: ctk.StringVar | None = None) -> None:
        key = combo.get()
        tap = tap_hold.get() == "Tap"
        interval = self._parse_interval(slider, entry, config.KEY_SPAM_INTERVAL_MS_MIN, config.KEY_SPAM_INTERVAL_MS_MAX, 200)
        count = self._parse_count(infinite_cb, count_entry)
        entry.delete(0, "end")
        entry.insert(0, str(interval))
        if interval_display_var:
            interval_display_var.set("Last interval: — ms")
        self._controller.start_key_spammer(key, tap, interval, count, self._quick_randomize.get())
        start_btn.configure(state="disabled")
        stop_btn.configure(state="normal")
        self._root.after(0, self._update_state_badge)
        if interval_display_var:
            self._poll_key_interval_display(interval_display_var)

    def _poll_key_interval_display(self, var: ctk.StringVar) -> None:
        if not self._controller.is_key_spammer_running():
            return
        last = self._controller.get_last_key_interval_ms()
        if last is not None:
            var.set(f"Last interval: {int(round(last))} ms")
        self._root.after(200, lambda: self._poll_key_interval_display(var))

    def _poll_mouse_interval_display(self, var: ctk.StringVar) -> None:
        if not self._controller.is_mouse_clicker_running():
            return
        last = self._controller.get_last_mouse_interval_ms()
        if last is not None:
            var.set(f"Last interval: {int(round(last))} ms")
        self._root.after(200, lambda: self._poll_mouse_interval_display(var))

    def _stop_key_spammer(self, start_btn, stop_btn, interval_display_var: ctk.StringVar | None = None) -> None:
        self._controller.stop_key_spammer()
        start_btn.configure(state="normal")
        stop_btn.configure(state="disabled")
        if interval_display_var:
            interval_display_var.set("Last interval: — ms")
        self._root.after(0, self._update_state_badge)

    def _start_mouse_clicker(self, btn, slider, entry, infinite_cb, count_entry, start_btn, stop_btn, interval_display_var: ctk.StringVar | None = None) -> None:
        left = btn.get() == "Left Click"
        interval = self._parse_interval(slider, entry, config.MOUSE_CLICK_INTERVAL_MS_MIN, config.MOUSE_CLICK_INTERVAL_MS_MAX, 200)
        count = self._parse_count(infinite_cb, count_entry)
        entry.delete(0, "end")
        entry.insert(0, str(interval))
        if interval_display_var:
            interval_display_var.set("Last interval: — ms")
        self._controller.start_mouse_clicker(left, interval, count, self._quick_randomize.get())
        start_btn.configure(state="disabled")
        stop_btn.configure(state="normal")
        self._root.after(0, self._update_state_badge)
        if interval_display_var:
            self._poll_mouse_interval_display(interval_display_var)

    def _stop_mouse_clicker(self, start_btn, stop_btn, interval_display_var: ctk.StringVar | None = None) -> None:
        self._controller.stop_mouse_clicker()
        start_btn.configure(state="normal")
        stop_btn.configure(state="disabled")
        if interval_display_var:
            interval_display_var.set("Last interval: — ms")
        self._root.after(0, self._update_state_badge)

    def trigger_key_spammer_start(self) -> None:
        if self._controller.is_key_spammer_running():
            return
        self._root.after(0, lambda: self._start_key_spammer(
            self._quick_key_combo, self._quick_tap_hold, self._quick_key_interval_slider,
            self._quick_key_interval_entry, self._quick_key_count_infinite, self._quick_key_count_entry,
            self._quick_key_start_btn, self._quick_key_stop_btn, self._quick_key_interval_display_var,
        ))

    def trigger_key_spammer_stop(self) -> None:
        if not self._controller.is_key_spammer_running():
            return
        self._root.after(0, lambda: self._stop_key_spammer(
            self._quick_key_start_btn, self._quick_key_stop_btn, self._quick_key_interval_display_var,
        ))

    def trigger_mouse_clicker_start(self) -> None:
        if self._controller.is_mouse_clicker_running():
            return
        self._root.after(0, lambda: self._start_mouse_clicker(
            self._quick_mouse_btn, self._quick_mouse_interval_slider, self._quick_mouse_interval_entry,
            self._quick_mouse_count_infinite, self._quick_mouse_count_entry,
            self._quick_mouse_start_btn, self._quick_mouse_stop_btn, self._quick_mouse_interval_display_var,
        ))

    def trigger_mouse_clicker_stop(self) -> None:
        if not self._controller.is_mouse_clicker_running():
            return
        self._root.after(0, lambda: self._stop_mouse_clicker(
            self._quick_mouse_start_btn, self._quick_mouse_stop_btn, self._quick_mouse_interval_display_var,
        ))

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
        ctk.CTkButton(save_row, text="Save as…", fg_color=COLOR_ACCENT, text_color="#000", width=100, command=self._handle_save_macro_quick).pack(side="left")

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
        ctk.CTkButton(btn_row, text="Play", width=90, fg_color=COLOR_ACCENT, text_color="#000", command=self._handle_library_play).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Delete", width=90, fg_color=COLOR_DANGER, command=self._handle_library_delete).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Export", width=90, command=self._handle_library_export).pack(side="left")
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

        ctk.CTkLabel(s, text="Theme", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(0, 4))
        theme_combo = ctk.CTkComboBox(s, values=["Dark", "Light", "System"], width=180)
        theme_combo.set(self._settings.get("theme", "Dark"))
        theme_combo.pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(s, text="Randomization (timing jitter ms)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        rmin = ctk.CTkEntry(s, width=80, placeholder_text="5")
        rmin.insert(0, str(self._settings.get("randomize_time_ms_min", 5)))
        rmin.pack(anchor="w", pady=2)
        rmax = ctk.CTkEntry(s, width=80, placeholder_text="15")
        rmax.insert(0, str(self._settings.get("randomize_time_ms_max", 15)))
        rmax.pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(s, text="Randomization (mouse noise px)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        pxmin = ctk.CTkEntry(s, width=80)
        pxmin.insert(0, str(self._settings.get("randomize_mouse_px_min", 1)))
        pxmin.pack(anchor="w", pady=2)
        pxmax = ctk.CTkEntry(s, width=80)
        pxmax.insert(0, str(self._settings.get("randomize_mouse_px_max", 4)))
        pxmax.pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(s, text="Emergency stop hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        hotkey_entry = ctk.CTkEntry(s, width=200, placeholder_text="ctrl+shift+f12")
        hotkey_entry.insert(0, self._settings.get("emergency_hotkey", config.EMERGENCY_HOTKEY))
        hotkey_entry.pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(s, text="Start recording hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        start_rec_row = ctk.CTkFrame(s, fg_color="transparent")
        start_rec_row.pack(anchor="w", pady=2)
        start_rec_entry = ctk.CTkEntry(start_rec_row, width=180, placeholder_text="f9")
        start_rec_entry.insert(0, self._settings.get("start_recording_hotkey", "f9"))
        start_rec_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(start_rec_row, text="Record key", width=100,
                      command=lambda: self._record_hotkey("Start recording", start_rec_entry)).pack(side="left")
        ctk.CTkLabel(s, text="Stop recording hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        stop_rec_row = ctk.CTkFrame(s, fg_color="transparent")
        stop_rec_row.pack(anchor="w", pady=2)
        stop_rec_entry = ctk.CTkEntry(stop_rec_row, width=180, placeholder_text="f10")
        stop_rec_entry.insert(0, self._settings.get("stop_recording_hotkey", "f10"))
        stop_rec_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(stop_rec_row, text="Record key", width=100,
                      command=lambda: self._record_hotkey("Stop recording", stop_rec_entry)).pack(side="left")
        ctk.CTkLabel(s, text="Key Spammer start hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 4))
        key_spam_start_row = ctk.CTkFrame(s, fg_color="transparent")
        key_spam_start_row.pack(anchor="w", pady=2)
        key_spammer_start_entry = ctk.CTkEntry(key_spam_start_row, width=180, placeholder_text="f7")
        key_spammer_start_entry.insert(0, self._settings.get("key_spammer_start_hotkey", "f7"))
        key_spammer_start_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(key_spam_start_row, text="Record key", width=100,
                      command=lambda: self._record_hotkey("Key Spammer start", key_spammer_start_entry)).pack(side="left")
        ctk.CTkLabel(s, text="Key Spammer stop hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        key_spam_stop_row = ctk.CTkFrame(s, fg_color="transparent")
        key_spam_stop_row.pack(anchor="w", pady=2)
        key_spammer_stop_entry = ctk.CTkEntry(key_spam_stop_row, width=180, placeholder_text="f8")
        key_spammer_stop_entry.insert(0, self._settings.get("key_spammer_stop_hotkey", "f8"))
        key_spammer_stop_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(key_spam_stop_row, text="Record key", width=100,
                      command=lambda: self._record_hotkey("Key Spammer stop", key_spammer_stop_entry)).pack(side="left")
        ctk.CTkLabel(s, text="Mouse Clicker start hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 4))
        mouse_start_row = ctk.CTkFrame(s, fg_color="transparent")
        mouse_start_row.pack(anchor="w", pady=2)
        mouse_clicker_start_entry = ctk.CTkEntry(mouse_start_row, width=180, placeholder_text="f5")
        mouse_clicker_start_entry.insert(0, self._settings.get("mouse_clicker_start_hotkey", "f5"))
        mouse_clicker_start_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(mouse_start_row, text="Record key", width=100,
                      command=lambda: self._record_hotkey("Mouse Clicker start", mouse_clicker_start_entry)).pack(side="left")
        ctk.CTkLabel(s, text="Mouse Clicker stop hotkey", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        mouse_stop_row = ctk.CTkFrame(s, fg_color="transparent")
        mouse_stop_row.pack(anchor="w", pady=2)
        mouse_clicker_stop_entry = ctk.CTkEntry(mouse_stop_row, width=180, placeholder_text="f6")
        mouse_clicker_stop_entry.insert(0, self._settings.get("mouse_clicker_stop_hotkey", "f6"))
        mouse_clicker_stop_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(mouse_stop_row, text="Record key", width=100,
                      command=lambda: self._record_hotkey("Mouse Clicker stop", mouse_clicker_stop_entry)).pack(side="left")
        ctk.CTkLabel(s, text="", height=0).pack(anchor="w", pady=(0, 8))

        run_startup = ctk.CTkCheckBox(s, text="Run on Windows startup")
        run_startup.pack(anchor="w", pady=8)
        if self._settings.get("run_on_startup"):
            run_startup.select()

        ctk.CTkLabel(s, text="Macro storage path", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        path_entry = ctk.CTkEntry(s, width=400, placeholder_text=config.get_macros_dir())
        path_entry.insert(0, self._settings.get("macros_dir_override", "") or config.get_macros_dir())
        path_entry.pack(anchor="w", pady=(0, 12))

        always_top = ctk.CTkCheckBox(s, text="Always on top")
        always_top.pack(anchor="w", pady=8)
        if self._settings.get("always_on_top"):
            always_top.select()

        ctk.CTkLabel(s, text="Overlay Mode (ACT-style)", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(16, 8))
        start_overlay_cb = ctk.CTkCheckBox(s, text="Start in Overlay Mode (gaming)")
        start_overlay_cb.pack(anchor="w", pady=4)
        if self._settings.get("start_in_overlay_mode", False):
            start_overlay_cb.select()
        ctk.CTkLabel(s, text="Transparency (opacity) when overlay is on: 50–100%", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        settings_opacity_slider = ctk.CTkSlider(s, from_=0.5, to=1.0, number_of_steps=10, width=200)
        settings_opacity_slider.set(self._settings.get("overlay_opacity", 1.0))
        settings_opacity_slider.pack(anchor="w", pady=2)
        overlay_click_through_cb_settings = ctk.CTkCheckBox(s, text="Click-through (mouse passes to game when overlay is on)")
        overlay_click_through_cb_settings.pack(anchor="w", pady=6)
        if self._settings.get("overlay_click_through", False):
            overlay_click_through_cb_settings.select()
        ctk.CTkLabel(s, text="Overlay toggle hotkey (toggle click-through when overlay is on)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        overlay_hotkey_row = ctk.CTkFrame(s, fg_color="transparent")
        overlay_hotkey_row.pack(anchor="w", pady=2)
        overlay_toggle_entry = ctk.CTkEntry(overlay_hotkey_row, width=180, placeholder_text="ctrl+alt+o")
        overlay_toggle_entry.insert(0, self._settings.get("overlay_toggle_hotkey", "ctrl+alt+o"))
        overlay_toggle_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(overlay_hotkey_row, text="Record key", width=100,
                      command=lambda: self._record_hotkey("Overlay toggle", overlay_toggle_entry)).pack(side="left")
        ctk.CTkLabel(s, text="Switch game to Borderless Windowed for overlay support.", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(4, 0))

        ctk.CTkLabel(s, text="Anti-Detection", font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", pady=(16, 8))
        ctk.CTkLabel(s, text="Profile", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(4, 2))
        profile_combo = ctk.CTkComboBox(s, values=["Safe", "Aggressive", "Stealth", "Custom"], width=180)
        profile_combo.set(self._settings.get("antidetect_profile", "safe").capitalize())
        profile_combo.pack(anchor="w", pady=(0, 8))
        adv_human = ctk.CTkCheckBox(s, text="Enable Advanced Humanization (gaussian jitter, drift, micro-pauses)")
        adv_human.pack(anchor="w", pady=4)
        if self._settings.get("advanced_humanization_enabled", True):
            adv_human.select()
        humanization_status_var = ctk.StringVar(value="Current: Off")
        HUMANIZATION_LABELS = ("Off", "Low", "Medium", "High", "Paranoid")

        def update_humanization_label(val: float) -> None:
            idx = min(4, max(0, int(round(val))))
            humanization_status_var.set(f"Current: {HUMANIZATION_LABELS[idx]}")

        ctk.CTkLabel(s, text="Humanization intensity: Low / Medium / High / Paranoid").pack(anchor="w", pady=(8, 2))
        intensity_slider = ctk.CTkSlider(s, from_=0, to=4, number_of_steps=4, width=200,
                                          command=update_humanization_label)
        intensity_slider.set(self._settings.get("humanization_intensity", 0))
        intensity_slider.pack(anchor="w", pady=2)
        update_humanization_label(intensity_slider.get())
        ctk.CTkLabel(s, textvariable=humanization_status_var, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=0, pady=(0, 4))
        insert_nulls_cb = ctk.CTkCheckBox(s, text="Insert 1–2 null SendInput between events (pattern break)")
        insert_nulls_cb.pack(anchor="w", pady=4)
        if self._settings.get("insert_nulls"):
            insert_nulls_cb.select()
        use_qpc_cb = ctk.CTkCheckBox(s, text="Use QueryPerformanceCounter in INPUT time field")
        use_qpc_cb.pack(anchor="w", pady=4)
        if self._settings.get("use_qpc_time"):
            use_qpc_cb.select()
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
                color = "#00FF9D" if on else "#FF2D55"
                if i < len(humanization_feature_labels):
                    humanization_feature_labels[i].configure(text_color=color)

        for feat_name, _ in HUMANIZATION_FEATURES:
            lbl = ctk.CTkLabel(humanization_frame, text=f"• {feat_name}", font=ctk.CTkFont(size=12))
            humanization_feature_labels.append(lbl)
            lbl.pack(anchor="w", padx=(0, 8), pady=1)
        humanization_frame.pack(anchor="w", pady=(4, 8))
        update_humanization_features()
        intensity_slider.configure(command=lambda v: (update_humanization_label(v), update_humanization_features()))
        adv_human.configure(command=lambda: update_humanization_features())
        insert_nulls_cb.configure(command=update_humanization_features)
        use_qpc_cb.configure(command=update_humanization_features)
        obfuscate_cb = ctk.CTkCheckBox(s, text="Obfuscate process name on launch (random generic title)")
        obfuscate_cb.pack(anchor="w", pady=4)
        if self._settings.get("obfuscate_process_name"):
            obfuscate_cb.select()
        ctk.CTkLabel(s, text="Generic window title (overrides app name when set)").pack(anchor="w", pady=(8, 2))
        generic_title_entry = ctk.CTkEntry(s, width=300, placeholder_text="e.g. System Monitor")
        generic_title_entry.insert(0, self._settings.get("generic_window_title", ""))
        generic_title_entry.pack(anchor="w", pady=(0, 12))

        def save_settings_cb() -> None:
            try:
                self._settings["theme"] = theme_combo.get()
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
                self._settings["always_on_top"] = always_top.get()
                self._settings["start_in_overlay_mode"] = start_overlay_cb.get()
                self._settings["overlay_opacity"] = round(settings_opacity_slider.get(), 2)
                self._settings["overlay_click_through"] = overlay_click_through_cb_settings.get()
                self._settings["overlay_toggle_hotkey"] = overlay_toggle_entry.get().strip().lower() or "ctrl+alt+o"
                self._settings["antidetect_profile"] = profile_combo.get().lower()
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
            ctk.set_appearance_mode(self._settings["theme"])
            self._apply_macros_dir_override()
            self._update_always_on_top()
            self._overlay_opacity = self._settings["overlay_opacity"]
            self._is_click_through = self._settings["overlay_click_through"]
            if self._overlay_enforced:
                self._reapply_overlay_style()
                self._on_transparency_changed(self._overlay_opacity)
            self._on_settings_saved()
            self._set_status("Settings saved. Hotkeys updated.")

        ctk.CTkButton(s, text="Save settings", fg_color=COLOR_ACCENT, text_color="#000", command=save_settings_cb).pack(anchor="w", pady=16)

        ctk.CTkLabel(s, text=f"About  {config.APP_NAME}  v{config.APP_VERSION}", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(16, 4))
        ctk.CTkLabel(s, text="Professional macro recorder & playback with Quick Actions (key spammer, auto-clicker).").pack(anchor="w", pady=(0, 8))

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self._root, fg_color=COLOR_CARD, corner_radius=6, height=36)
        bar.pack(fill="x", padx=10, pady=(6, 10))
        bar.pack_propagate(False)
        self._status_var = ctk.StringVar(value="Idle – Ready")
        ctk.CTkLabel(bar, textvariable=self._status_var).pack(side="left", padx=12, pady=8)
        self._progress_var = ctk.DoubleVar(value=0.0)
        self._progress_bar = ctk.CTkProgressBar(bar, variable=self._progress_var, width=200)
        self._progress_bar.pack(side="right", padx=12, pady=8)
        self._progress_bar.pack_forget()  # show only during playback
        self._overlay_status_label = ctk.CTkLabel(
            bar, text="Normal window",
            font=ctk.CTkFont(size=11), text_color=COLOR_BORDER[1]
        )
        self._overlay_status_label.pack(side="right", padx=12, pady=8)

    def _handle_overlay_toggle(self) -> None:
        if not self._overlay_enforced:
            self.setup_overlay_mode()
        else:
            self.toggle_click_through()

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
