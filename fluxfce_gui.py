#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fluxfce (GUI) - Simplified XFCE Theming Tool

Graphical user interface for managing automatic XFCE theme/background/screen
switching using the fluxfce_core library. Runs as a background application
with a system tray status icon.
"""

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --- Gtk and Core Library Imports ---
try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk, Pango
except (ImportError, ValueError):
    print("FATAL: Gtk3 bindings are not installed or configured correctly.", file=sys.stderr)
    print("On Debian/Ubuntu, try: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0", file=sys.stderr)
    sys.exit(1)

try:
    import fluxfce_core
    from fluxfce_core import exceptions as core_exc
    from fluxfce_core import xfce
except ImportError as e:
    print(f"FATAL: fluxfce_core library not found: {e}", file=sys.stderr)
    print("Please ensure fluxfce_core is installed or available in your Python path.", file=sys.stderr)
    sys.exit(1)

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")
log = logging.getLogger("fluxfce_gui")

# --- Constants ---
APP_SCRIPT_PATH = Path(__file__).resolve()
SLIDER_DEBOUNCE_MS = 200
UI_UPDATE_DELAY_MS = 250
UI_REFRESH_INTERVAL_MS = 60 * 1000  # 1 minute

class FluxFceWindow(Gtk.Window):
    """The main configuration and status window for fluxfce."""
    def __init__(self, application):
        super().__init__()
        self.app = application

        # Window properties
        self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        self.set_border_width(12)
        self.set_default_size(420, -1)
        self.set_resizable(False)
        self.set_decorated(False)

        # Signal connections
        self.connect("delete-event", self.on_close_button_pressed)
        self.connect("focus-out-event", self.on_focus_out_event)
        self.connect("show", self._start_ui_timers)
        self.connect("hide", self._stop_ui_timers)
        self.connect("size-allocate", self._on_size_allocated)

        # Custom styling with CSS for gradients and expanders
        style_provider = Gtk.CssProvider()
        css = b"""
        .dim-label {
            color: alpha(currentColor, 0.7);
        }
        .temp-gradient {
            background-image: linear-gradient(to right,
                #FF6600, #FFD8B1 35%, #FFFFFF 50%, #D4E4FF 65%, #B3CFFF);
            border-radius: 4px;
        }
        .bright-gradient {
            background-image: linear-gradient(to right, black, white);
            border-radius: 4px;
        }
        expander > header .expander-arrow {
            opacity: 0; min-width: 0; padding: 0; border: 0;
        }

        /*
         * This is the corrected, more aggressive rule for the slider.
         * By targeting the 'scale' widget type and its 'trough' sub-node,
         * we increase specificity to override theme defaults.
         */
        scale.transparent-slider.horizontal trough {
            background-image: none;
            background-color: transparent;
            border: none;
            box-shadow: none;
            min-height: 0; /* Remove any minimum size the theme enforces */
        }

        /* We must also hide the colored "fill" or "progress" part of the trough */
        scale.transparent-slider.horizontal trough > progress,
        scale.transparent-slider.horizontal trough > fill {
            background-image: none;
            background-color: transparent;
            border: none;
            box-shadow: none;
            min-height: 0;
        }
        """
        style_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        try:
            self.xfce_handler = xfce.XfceHandler()
        except core_exc.XfceError as e:
            self.show_error_dialog("Initialization Error", f"Could not start the tool.\nIs `xsct` installed and in your PATH?\n\nDetails: {e}")
            GLib.idle_add(self.app.quit)
            return

        # UI state variables
        self.toggle_switch_handler_id = None
        self.temp_slider_handler_id = None
        self.bright_slider_handler_id = None
        self.slider_debounce_id = None
        self.periodic_refresh_id = None
        self.one_shot_refresh_id = None
        self._last_height = None

        self._build_ui()

    def _on_size_allocated(self, widget, allocation):
        """
        Handles window size changes to keep the bottom edge stationary when
        collapsing/expanding sections.
        """
        # On first allocation, just store the height
        if self._last_height is None:
            self._last_height = allocation.height
            return

        # If height has changed, adjust window position
        if self._last_height != allocation.height:
            height_delta = allocation.height - self._last_height
            x, y = self.get_position()
            self.move(x, y - height_delta)
            self._last_height = allocation.height

    def _build_ui(self):
        """Constructs the entire UI, including a custom title bar and content."""
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        self.add(main_vbox)

    #    main_vbox.pack_start(self._build_title_bar(), False, True, 0)
        main_vbox.pack_start(self._build_status_section(), False, True, 0)
        main_vbox.pack_start(self._build_profiles_section(), False, True, 0)
        main_vbox.pack_start(self._build_manual_control_section(), False, True, 0)

    def _build_status_section(self):
        """Builds the top section with next transition info and toggle switch."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # One horizontal box: Next label, details/status, and toggle switch
        next_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl_transition_title = Gtk.Label(label="<b>Next:</b>", use_markup=True, xalign=0)
        self.lbl_next_transition = Gtk.Label(label="N/A", xalign=0, ellipsize=Pango.EllipsizeMode.END)

        next_hbox.pack_start(lbl_transition_title, False, False, 0)
        next_hbox.pack_start(self.lbl_next_transition, True, True, 0)

        self.toggle_switch = Gtk.Switch()
        self.toggle_switch.set_valign(Gtk.Align.CENTER)
        self.toggle_switch_handler_id = self.toggle_switch.connect("notify::active", self.on_toggle_switch_activated)
        next_hbox.pack_end(self.toggle_switch, False, False, 0)

        box.pack_start(next_hbox, False, True, 0)
        return box

    def _build_profiles_section(self):
        # Use an expander to allow collapsing this section
        frame = Gtk.Expander(use_markup=True, label="<b> Profiles </b>")
        frame.set_expanded(True)

        profile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=10)
        frame.add(profile_box)
        (self.day_grid, self.lbl_day_details, self.btn_edit_day_profile) = self._create_profile_row("day", "☀️", "Day Mode")
        profile_box.pack_start(self.day_grid, False, False, 0)
        profile_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 5)
        (self.night_grid, self.lbl_night_details, self.btn_edit_night_profile) = self._create_profile_row("night", "🌙", "Night Mode")
        profile_box.pack_start(self.night_grid, False, False, 0)
        return frame

    def _create_profile_row(self, mode, icon, title):
        grid = Gtk.Grid(column_spacing=6, row_spacing=4)
        btn_apply = Gtk.Button(halign=Gtk.Align.FILL, hexpand=True)
        btn_apply_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_apply_box.pack_start(Gtk.Label(label=icon), False, False, 0)
        btn_apply_box.pack_start(Gtk.Label(label=title), False, False, 0)
        btn_apply.add(btn_apply_box)
        btn_apply.connect("clicked", self.on_apply_temporary_clicked, mode)
        grid.attach(btn_apply, 0, 0, 1, 1)
        btn_save = Gtk.Button.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON)
        btn_save.set_tooltip_text(f"Save current desktop look as the new {mode.capitalize()} default")
        btn_save.connect("clicked", self.on_set_default_clicked, mode)
        grid.attach(btn_save, 1, 0, 1, 1)
        btn_edit_profile = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        btn_edit_profile.connect("clicked", self.on_edit_profile_clicked, mode)
        grid.attach(btn_edit_profile, 2, 0, 1, 1)
        lbl_details = Gtk.Label(xalign=0, yalign=0, use_markup=True)
        lbl_details.get_style_context().add_class("dim-label")
        grid.attach(lbl_details, 0, 1, 3, 1)
        return grid, lbl_details, btn_edit_profile

    def _build_manual_control_section(self):
        # Use an expander to allow collapsing this section
        frame = Gtk.Expander(use_markup=True, label="<b> Manual Control </b>")
        frame.set_expanded(True)

        # Use a Grid for precise alignment
        grid = Gtk.Grid(column_spacing=6, row_spacing=8, margin=10, hexpand=True)
        frame.add(grid)

        # --- Temperature Control ---
        temp_overlay = Gtk.Overlay()
        grid.attach(temp_overlay, 1, 0, 1, 1)

        temp_gradient_bar = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER, height_request=8)
        temp_gradient_bar.get_style_context().add_class("temp-gradient")
        temp_overlay.add(temp_gradient_bar)

        adj_temp = Gtk.Adjustment(value=6500, lower=1000, upper=10000, step_increment=50, page_increment=100)
        self.slider_temp = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj_temp, draw_value=False, hexpand=True)
        self.slider_temp.get_style_context().add_class("transparent-slider")
        self.temp_slider_handler_id = self.slider_temp.connect("value-changed", self.on_slider_value_changed)
        temp_overlay.add_overlay(self.slider_temp)

        self.lbl_temp_readout = Gtk.Label(label="... K", width_chars=7)
        btn_reset_temp = Gtk.Button.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.BUTTON)
        btn_reset_temp.set_tooltip_text("Reset Temperature to Default (6500K)")
        btn_reset_temp.connect("clicked", self.on_reset_slider_clicked, "temp")

        grid.attach(Gtk.Image.new_from_icon_name("weather-clear-symbolic", Gtk.IconSize.BUTTON), 0, 0, 1, 1)
        grid.attach(self.lbl_temp_readout, 2, 0, 1, 1)
        grid.attach(btn_reset_temp, 3, 0, 1, 1)

        # --- Brightness Control ---
        bright_overlay = Gtk.Overlay()
        grid.attach(bright_overlay, 1, 1, 1, 1)

        bright_gradient_bar = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER, height_request=8)
        bright_gradient_bar.get_style_context().add_class("bright-gradient")
        bright_overlay.add(bright_gradient_bar)

        adj_bright = Gtk.Adjustment(value=1.0, lower=0.1, upper=1.0, step_increment=0.01, page_increment=0.01)
        self.slider_bright = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj_bright, draw_value=False, hexpand=True)
        self.slider_bright.get_style_context().add_class("transparent-slider")
        self.bright_slider_handler_id = self.slider_bright.connect("value-changed", self.on_slider_value_changed)
        bright_overlay.add_overlay(self.slider_bright)

        self.lbl_bright_readout = Gtk.Label(label="... %", width_chars=7)
        btn_reset_bright = Gtk.Button.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.BUTTON)
        btn_reset_bright.set_tooltip_text("Reset Brightness to Default (100%)")
        btn_reset_bright.connect("clicked", self.on_reset_slider_clicked, "bright")

        grid.attach(Gtk.Image.new_from_icon_name("display-brightness-symbolic", Gtk.IconSize.BUTTON), 0, 1, 1, 1)
        grid.attach(self.lbl_bright_readout, 2, 1, 1, 1)
        grid.attach(btn_reset_bright, 3, 1, 1, 1)

        return frame

    def refresh_ui(self):
        if self.one_shot_refresh_id: GLib.source_remove(self.one_shot_refresh_id)
        self.one_shot_refresh_id = None
        try:
            status = fluxfce_core.get_status()
            config_parser = fluxfce_core.get_current_config()
            self._update_status_header(status.get("summary", {}))
            self._update_profile_display("day", status, config_parser)
            self._update_profile_display("night", status, config_parser)
            self._update_sliders_from_backend()
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Core Error", f"Failed to get status: {e}")

    def _update_status_header(self, summary):
        is_enabled = summary.get("overall_status") == "[OK]"
        self.app.update_status(is_enabled)
        self.toggle_switch.handler_block(self.toggle_switch_handler_id)
        self.toggle_switch.set_active(is_enabled)
        self.toggle_switch.handler_unblock(self.toggle_switch_handler_id)

        if is_enabled:
            next_time = summary.get("next_transition_time")
            if next_time:
                delta = next_time - datetime.now(next_time.tzinfo)
                if delta.total_seconds() < -1:
                    time_left_str = "in the past"
                elif delta.total_seconds() < 60:
                    time_left_str = "soon"
                else:
                    time_left_str = f"in {int(delta.seconds / 3600)}h {int((delta.seconds % 3600) / 60)}m"
                next_mode = GLib.markup_escape_text(summary.get('next_transition_mode', ''))
                next_time_str = GLib.markup_escape_text(f"{next_time.strftime('%H:%M')} ({time_left_str})")
                self.lbl_next_transition.set_markup(f"{next_mode} at <b>{next_time_str}</b>")
                delta_ms = delta.total_seconds() * 1000
                if delta_ms > 0:
                    self.one_shot_refresh_id = GLib.timeout_add(int(delta_ms) + 2000, self._on_transition_occurs)
            else:
                self.lbl_next_transition.set_text("Not scheduled")
        else:
            # When disabled, replace 'Next:' line with a bold red status
            self.lbl_next_transition.set_markup("<b>Scheduling disabled</b>")


    def _update_profile_display(self, mode, status, config_parser):
        config = status.get("config", {})
        if mode == "day":
            profile_name, theme = config.get("day_bg_profile", "N/A"), config.get("light_theme", "N/A")
            temp, bright = config_parser.get("ScreenDay", "XSCT_TEMP", fallback=""), config_parser.get("ScreenDay", "XSCT_BRIGHT", fallback="")
            label_widget, button_widget = self.lbl_day_details, self.btn_edit_day_profile
        else:
            profile_name, theme = config.get("night_bg_profile", "N/A"), config.get("dark_theme", "N/A")
            temp, bright = config_parser.get("ScreenNight", "XSCT_TEMP", fallback=""), config_parser.get("ScreenNight", "XSCT_BRIGHT", fallback="")
            label_widget, button_widget = self.lbl_night_details, self.btn_edit_night_profile
        temp_str = f"{temp} K" if temp else "Default"
        bright_str = f"{float(bright):.0%}" if bright else "Default"
        label_widget.set_markup(f"<small>Theme: <b>{theme}</b>\nScreen: <b>{temp_str}</b>, <b>{bright_str}</b></small>")
        button_widget.set_tooltip_text(f"Edit background profile '{profile_name}.profile'")

    def _update_sliders_from_backend(self):
        log.debug("Updating sliders from backend screen state.")
        try:
            settings = self.xfce_handler.get_screen_settings()
            temp, bright = settings.get("temperature", 6500), settings.get("brightness", 1.0)
            self.slider_temp.handler_block(self.temp_slider_handler_id)
            self.slider_bright.handler_block(self.bright_slider_handler_id)
            self.slider_temp.get_adjustment().set_value(temp)
            self.lbl_temp_readout.set_text(f"{int(temp)} K")
            self.slider_bright.get_adjustment().set_value(bright)
            self.lbl_bright_readout.set_text(f"{bright:.0%}")
        except core_exc.XfceError as e:
            log.error(f"Could not get screen settings: {e}")
        finally:
            self.slider_temp.handler_unblock(self.temp_slider_handler_id)
            self.slider_bright.handler_unblock(self.bright_slider_handler_id)

    def on_focus_out_event(self, widget, event):
        self.hide()
        return True

    def on_close_button_pressed(self, widget, event):
        self.hide()
        return True

    def _start_ui_timers(self, widget=None):
        self._stop_ui_timers()
        log.info("Window shown. Starting UI refresh timers.")
        self.refresh_ui()
        self.periodic_refresh_id = GLib.timeout_add(UI_REFRESH_INTERVAL_MS, self._on_periodic_refresh_tick)

    def _stop_ui_timers(self, widget=None):
        if self.periodic_refresh_id: GLib.source_remove(self.periodic_refresh_id)
        if self.one_shot_refresh_id: GLib.source_remove(self.one_shot_refresh_id)
        self.periodic_refresh_id = self.one_shot_refresh_id = None

    def _on_periodic_refresh_tick(self):
        self.refresh_ui()
        return GLib.SOURCE_CONTINUE

    def _on_transition_occurs(self):
        self.one_shot_refresh_id = None
        self.refresh_ui()
        return GLib.SOURCE_REMOVE

    def on_toggle_switch_activated(self, switch, gparam):
        try:
            if switch.get_active():
                fluxfce_core.enable_scheduling(sys.executable, str(APP_SCRIPT_PATH))
            else:
                fluxfce_core.disable_scheduling()
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Scheduling Error", f"Operation failed: {e}")
        GLib.idle_add(self.refresh_ui)

    def on_set_default_clicked(self, widget, mode):
        dialog = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL, text=f"Save as {mode.capitalize()} Default?")
        dialog.format_secondary_text(f"This will overwrite the current {mode} settings with the current desktop theme, background, and screen color.")
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                fluxfce_core.set_default_from_current(mode)
                self.show_info_dialog("Success", f"{mode.capitalize()} mode defaults have been saved.")
                self.refresh_ui()
            except core_exc.FluxFceError as e: self.show_error_dialog("Save Error", f"Failed to save defaults: {e}")
        dialog.destroy()

    def on_apply_temporary_clicked(self, widget, mode):
        try:
            fluxfce_core.apply_temporary_mode(mode)
            GLib.timeout_add(UI_UPDATE_DELAY_MS, self._update_sliders_from_backend)
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Apply Error", f"Failed to apply {mode} mode: {e}")

    def on_slider_value_changed(self, slider):
        self.lbl_temp_readout.set_text(f"{int(self.slider_temp.get_value())} K")
        self.lbl_bright_readout.set_text(f"{self.slider_bright.get_value():.0%}")
        if self.slider_debounce_id: GLib.source_remove(self.slider_debounce_id)
        self.slider_debounce_id = GLib.timeout_add(SLIDER_DEBOUNCE_MS, self._apply_slider_values)

    def _apply_slider_values(self):
        temp, bright = int(self.slider_temp.get_value()), self.slider_bright.get_value()
        try:
            self.xfce_handler.set_screen_temp(temp, bright)
        except (core_exc.XfceError, ValueError) as e:
            self.show_error_dialog("Apply Error", f"Failed to set screen values: {e}")
        self.slider_debounce_id = None
        return GLib.SOURCE_REMOVE

    def on_reset_slider_clicked(self, widget, control_type):
        try:
            settings = self.xfce_handler.get_screen_settings()
            temp, bright = settings.get("temperature", 6500), settings.get("brightness", 1.0)
            if control_type == "temp":
                temp = 6500
            elif control_type == "bright":
                bright = 1.0
            self.xfce_handler.set_screen_temp(temp, bright)
            GLib.timeout_add(UI_UPDATE_DELAY_MS, self._update_sliders_from_backend)
        except core_exc.XfceError as e:
            self.show_error_dialog("Reset Error", f"Failed to reset {control_type}: {e}")

    def on_edit_profile_clicked(self, widget, mode):
        try:
            config = fluxfce_core.get_current_config()
            key = "DAY_BACKGROUND_PROFILE" if mode == 'day' else "NIGHT_BACKGROUND_PROFILE"
            profile_name = config.get("Appearance", key)
            if not profile_name: raise core_exc.ConfigError(f"Could not find '{key}' in your configuration.")
            profile_path = fluxfce_core.CONFIG_DIR / "backgrounds" / f"{profile_name}.profile"
            self.open_file_in_editor(profile_path)
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Error", f"Could not determine profile path:\n{e}")

    def show_error_dialog(self, title, message):
        dialog = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text=title)
        dialog.format_secondary_text(str(message))
        dialog.run()
        dialog.destroy()

    def show_info_dialog(self, title, message):
        dialog = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK, text=title)
        dialog.format_secondary_text(str(message))
        dialog.run()
        dialog.destroy()

    def open_file_in_editor(self, file_path: Path):
        if not file_path.exists():
            self.show_error_dialog("File Not Found", f"The file does not exist:\n{file_path}")
            return
        try:
            subprocess.Popen(["xdg-open", str(file_path)])
        except (FileNotFoundError, OSError) as e:
            self.show_error_dialog("Could Not Open File", f"Failed to launch text editor using 'xdg-open'.\nError: {e}")

    # --- TRAY WINDOW POSITIONING FIXES ---

    def _calc_position(self, screen, icon_rect, win_w, win_h):
        display = Gdk.Display.get_default()
        monitor_index = screen.get_monitor_at_point(icon_rect.x, icon_rect.y)
        monitor = display.get_monitor(monitor_index)
        workarea = monitor.get_workarea()
        x = icon_rect.x + icon_rect.width // 2 - win_w // 2
        if icon_rect.y < workarea.y + workarea.height // 2:
            y = icon_rect.y + icon_rect.height + 5
        else:
            y = icon_rect.y - win_h - 5
        x = max(workarea.x, min(x, workarea.x + workarea.width - win_w))
        y = max(workarea.y, min(y, workarea.y + workarea.height - win_h))
        return x, y

    def show_and_position(self, status_icon):
        success, screen, icon_rect, orient = status_icon.get_geometry()
        if success:
            _min, nat = self.get_preferred_size()
            win_w, win_h = nat.width, nat.height
            x, y = self._calc_position(screen, icon_rect, win_w, win_h)
            self.move(x, y)
            self.show_all()
            self.present()
        else:
            self.show_all()
            GLib.timeout_add(50, self._get_geometry_and_move, status_icon, 0)

    def _get_geometry_and_move(self, status_icon, attempts):
        try:
            success, screen, icon_rect, orient = status_icon.get_geometry()
            if not success:
                raise RuntimeError("geometry unavailable")
            win_w, win_h = self.get_size()
            x, y = self._calc_position(screen, icon_rect, win_w, win_h)
            self.move(x, y)
            self.present()
            return GLib.SOURCE_REMOVE
        except Exception:
            if attempts < 5:
                GLib.timeout_add(80, self._get_geometry_and_move, status_icon, attempts + 1)
            else:
                self._position_near_cursor()
            return GLib.SOURCE_REMOVE

    def _position_near_cursor(self):
        display = Gdk.Display.get_default()
        if not display:
            self.present()
            return
        seat = display.get_default_seat()
        if not seat:
            self.present()
            return
        _screen, x, y = seat.get_pointer().get_position()
        monitor = display.get_monitor_at_point(x, y)
        if not monitor:
            self.present()
            return
        workarea = monitor.get_workarea()
        win_w, win_h = self.get_size()
        new_x = max(workarea.x, min(x - win_w // 2, workarea.x + workarea.width - win_w))
        new_y = max(workarea.y, min(y - win_h - 30, workarea.y + workarea.height - win_h))
        self.move(new_x, new_y)
        self.present()

class Application:
    """The main application class, handles lifecycle and status icon."""
    def __init__(self):
        self.status_icon = None
        self.right_click_menu = None
        self.toggle_item = None
        self.window = FluxFceWindow(self)
        self._init_status_icon()

    def _init_status_icon(self):
        self.status_icon = Gtk.StatusIcon.new_from_icon_name('emblem-synchronizing-symbolic')
        self.status_icon.set_tooltip_text("fluxfce")
        self.status_icon.set_visible(True)
        self.status_icon.connect("activate", self.on_icon_left_click)
        self.status_icon.connect("popup-menu", self.on_icon_right_click)

    def _build_right_click_menu(self):
        menu = Gtk.Menu()
        self.toggle_item = Gtk.MenuItem(label="Enable Scheduling")
        self.toggle_item.connect("activate", self.on_menu_toggle_clicked)
        menu.append(self.toggle_item)
        apply_menu_item = Gtk.MenuItem(label="Apply Mode")
        menu.append(apply_menu_item)
        apply_submenu = Gtk.Menu()
        apply_menu_item.set_submenu(apply_submenu)
        day_item = Gtk.MenuItem(label="Apply Day Mode")
        day_item.connect("activate", self.window.on_apply_temporary_clicked, "day")
        apply_submenu.append(day_item)
        night_item = Gtk.MenuItem(label="Apply Night Mode")
        night_item.connect("activate", self.window.on_apply_temporary_clicked, "night")
        apply_submenu.append(night_item)
        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Exit")
        quit_item.connect("activate", self.on_quit_activate)
        menu.append(quit_item)
        menu.show_all()
        return menu

    def on_icon_left_click(self, icon):
        if self.window.is_visible():
            self.window.hide()
        else:
            self.window.show_and_position(icon)

    def on_icon_right_click(self, icon, button, activate_time):
        if not self.right_click_menu:
            self.right_click_menu = self._build_right_click_menu()
        self.right_click_menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    def on_menu_toggle_clicked(self, widget):
        is_active = self.window.toggle_switch.get_active()
        self.window.toggle_switch.set_active(not is_active)

    def on_quit_activate(self, widget):
        self.quit()

    def update_status(self, is_enabled):
        if self.status_icon:
            self.status_icon.set_from_icon_name("weather-clear-symbolic" if is_enabled else "weather-clear-night-symbolic")
            self.status_icon.set_tooltip_text("fluxfce Enabled" if is_enabled else "fluxfce Disabled")
        if self.toggle_item:
            self.toggle_item.set_label("Disable Scheduling" if is_enabled else "Enable Scheduling")

    def run(self):
        self.window.refresh_ui()
        Gtk.main()

    def quit(self):
        Gtk.main_quit()

if __name__ == "__main__":
    app = Application()
    app.run()
