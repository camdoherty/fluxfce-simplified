#!/usr/bin/env python3

"""
fluxfce (GUI) - Simplified XFCE Theming Tool

Graphical user interface for managing automatic XFCE theme/background/screen
switching using the fluxfce_core library. Runs as a background application
with a system tray status icon.
"""

import logging
import subprocess
import sys
from pathlib import Path
from datetime import datetime
try:
    from importlib import resources
except ImportError:
    import importlib_resources as resources


# --- GTK and Core Library Imports ---
try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import Gtk, GLib, Pango
    from gi.repository import AppIndicator3
except (ImportError, ValueError) as e:
    if "Gtk" in str(e):
        print("FATAL: GTK3 bindings are not installed or configured correctly.", file=sys.stderr)
        print("On Debian/Ubuntu, try: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0", file=sys.stderr)
    elif "AppIndicator3" in str(e):
        print("FATAL: AppIndicator3 library not found.", file=sys.stderr)
        print("This is required for the system tray icon.", file=sys.stderr)
        print("On Debian/Ubuntu, try: sudo apt install gir1.2-appindicator3-0.1", file=sys.stderr)
    else:
        print(f"An unexpected import error occurred: {e}", file=sys.stderr)
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
APP_ID = "com.github.youruser.fluxfce"
APP_SCRIPT_PATH = Path(__file__).resolve()
SLIDER_DEBOUNCE_MS = 200
POLLING_INTERVAL_MS = 200
POLLING_ATTEMPTS = 25

# --- Main Window Class ---
class FluxFceWindow(Gtk.Window):
    def __init__(self, application):
        super().__init__(title="fluxfce")
        self.app = application
        self.set_border_width(12)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self.on_close_button_pressed)

        try:
            self.xfce_handler = xfce.XfceHandler()
        except core_exc.XfceError as e:
            self.show_error_dialog("Initialization Error", f"Could not start the tool.\nIs `xsct` installed and in your PATH?\n\nDetails: {e}")
            GLib.idle_add(self.app.quit)
            return

        # State variables
        self.current_brightness = 1.0
        self.slider_handler_id = None
        self.polling_source_id = None
        self.slider_debounce_id = None
        self.details_widgets = []

        self._build_ui()
        self.refresh_ui()
        self._update_ui_from_backend()

    def on_close_button_pressed(self, widget, event):
        self.hide()
        return True

    def _build_ui(self):
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.add(main_vbox)
        status_frame = Gtk.Frame(label=" Status & Scheduling ")
        status_frame.set_label_align(0.05, 0.5)
        main_vbox.pack_start(status_frame, False, True, 0)
        self._build_status_section(status_frame)
        bottom_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        main_vbox.pack_start(bottom_hbox, True, True, 0)
        profiles_frame = Gtk.Frame(label=" Appearance Profiles ")
        profiles_frame.set_label_align(0.05, 0.5)
        bottom_hbox.pack_start(profiles_frame, True, True, 0)
        self._build_profiles_section(profiles_frame)
        temp_frame = Gtk.Frame(label=" Temp Control ")
        temp_frame.set_label_align(0.05, 0.5)
        bottom_hbox.pack_start(temp_frame, False, False, 0)
        self._build_temp_control_section(temp_frame)

    def _build_status_section(self, parent_frame):
        grid = Gtk.Grid(column_spacing=10, row_spacing=6, margin=10)
        grid.set_column_homogeneous(False)
        parent_frame.add(grid)
        self.lbl_overall_status = Gtk.Label(label="Fetching status...")
        self.lbl_overall_status.set_xalign(0)
        self.btn_toggle_schedule = Gtk.Button()
        self.btn_toggle_schedule.connect("clicked", self.on_toggle_schedule_clicked)
        self.btn_toggle_schedule.set_halign(Gtk.Align.END)
        grid.attach(self.lbl_overall_status, 0, 0, 1, 1)
        grid.attach(self.btn_toggle_schedule, 1, 0, 1, 1)
        lbl_edit_title = Gtk.Label(label="<b>Edit config.ini:</b>", use_markup=True, xalign=0)
        btn_open_config = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        btn_open_config.set_tooltip_text("Open config.ini in text editor")
        btn_open_config.connect("clicked", self.on_open_config_clicked)
        btn_open_config.set_halign(Gtk.Align.END)
        grid.attach(lbl_edit_title, 0, 1, 1, 1)
        grid.attach(btn_open_config, 1, 1, 1, 1)
        lbl_transition_title = Gtk.Label(label="<b>Next Transition:</b>", use_markup=True, xalign=0)
        self.lbl_next_transition = Gtk.Label(label="N/A", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        grid.attach(lbl_transition_title, 0, 3, 1, 1)
        grid.attach(self.lbl_next_transition, 1, 3, 1, 1)
        self.details_widgets = [lbl_transition_title, self.lbl_next_transition]

    def _create_profile_widget(self, mode, title):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        grid = Gtk.Grid(column_spacing=10, row_spacing=4)
        title_label = Gtk.Label(xalign=0)
        title_label.set_markup(f"<big><b>{title}</b></big>")
        grid.attach(title_label, 0, 0, 3, 1)
        grid.attach(Gtk.Label(label="Theme:", xalign=0), 0, 1, 1, 1)
        lbl_theme = Gtk.Label(label="N/A", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        grid.attach(lbl_theme, 1, 1, 2, 1)
        grid.attach(Gtk.Label(label="Profile:", xalign=0), 0, 2, 1, 1)
        lbl_profile = Gtk.Label(label="N/A", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        btn_edit = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        btn_edit.set_tooltip_text("Open profile file in text editor")
        btn_edit.connect("clicked", self.on_edit_profile_clicked, mode)
        grid.attach(lbl_profile, 1, 2, 1, 1)
        grid.attach(btn_edit, 2, 2, 1, 1)
        vbox.pack_start(grid, False, False, 0)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_top=4, halign=Gtk.Align.CENTER)
        btn_set_default = Gtk.Button(label="Save Current")
        btn_set_default.set_tooltip_text(f"Save Current Look as {mode.capitalize()} Default")
        btn_set_default.connect("clicked", self.on_set_default_clicked, mode)
        btn_apply_now = Gtk.Button(label="Apply Now")
        btn_apply_now.set_tooltip_text(f"Apply {mode.capitalize()} Mode Temporarily")
        btn_apply_now.connect("clicked", self.on_apply_temporary_clicked, mode)
        btn_box.pack_start(btn_set_default, True, True, 0)
        btn_box.pack_start(btn_apply_now, True, True, 0)
        vbox.pack_start(btn_box, False, False, 0)
        return vbox, lbl_theme, lbl_profile
        
    def _build_profiles_section(self, parent_frame):
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=10)
        parent_frame.add(main_vbox)
        day_box, self.lbl_day_theme, self.lbl_day_profile = self._create_profile_widget("day", "☀️ Day Mode")
        main_vbox.pack_start(day_box, False, False, 0)
        main_vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=5, margin_bottom=5), False, False, 0)
        night_box, self.lbl_night_theme, self.lbl_night_profile = self._create_profile_widget("night", "🌙 Night Mode")
        main_vbox.pack_start(night_box, False, False, 0)

    def _build_temp_control_section(self, parent_frame):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=10)
        parent_frame.add(vbox)
        self.lbl_temp_readout = Gtk.Label()
        self.lbl_temp_readout.set_markup("<span size='x-large' weight='bold'>... K</span>")
        vbox.pack_start(self.lbl_temp_readout, False, True, 5)
        control_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5, halign=Gtk.Align.CENTER)
        vbox.pack_start(control_hbox, True, True, 5)
        image_height = 180
        try:
            asset_path = resources.files("fluxfce_core.assets").joinpath("temp-slider.png")
            img_temp_gradient = Gtk.Image.new_from_file(str(asset_path))
            pixbuf = img_temp_gradient.get_pixbuf()
            if pixbuf: image_height = pixbuf.get_height()
            control_hbox.pack_start(img_temp_gradient, False, True, 0)
        except (FileNotFoundError, NotADirectoryError):
            log.warning("Temperature gradient image not found in package assets.")
        
        adjustment = Gtk.Adjustment(
            value=6500, lower=1000, upper=10000, 
            step_increment=50, page_increment=500, page_size=0
        )
        self.slider = Gtk.Scale(orientation=Gtk.Orientation.VERTICAL, adjustment=adjustment)
        self.slider.set_inverted(True)
        self.slider.set_size_request(-1, image_height)
        self.slider_handler_id = self.slider.connect("value-changed", self.on_slider_value_changed)
        control_hbox.pack_start(self.slider, True, True, 0)
        btn_reset = Gtk.Button(label="Reset")
        btn_reset.connect("clicked", self.on_reset_clicked)
        vbox.pack_start(btn_reset, False, True, 5)

    def refresh_ui(self):
        try:
            status = fluxfce_core.get_status()
            summary = status.get("summary", {})
            config = status.get("config", {})
            is_enabled = summary.get("overall_status") == "[OK]"
            self.app.update_status(is_enabled)
            if is_enabled:
                self.lbl_overall_status.set_markup("<span color='#2E8B57'><b>Enabled</b></span>")
                self.btn_toggle_schedule.set_label("Disable Scheduling")
                for widget in self.details_widgets: widget.show()
                next_time = summary.get("next_transition_time")
                if next_time:
                    delta = next_time - datetime.now(next_time.tzinfo)
                    time_left_str = "in the past" if delta.total_seconds() < 0 else f"in {int(delta.seconds / 3600)}h {int((delta.seconds % 3600) / 60)}m"
                    self.lbl_next_transition.set_text(f"{summary.get('next_transition_mode', '')} at {next_time.strftime('%H:%M')} ({time_left_str})")
                else:
                    self.lbl_next_transition.set_text("Not scheduled")
            else:
                status_message = summary.get("status_message", "Could not get status.")
                self.lbl_overall_status.set_markup(f"<span color='red'><b>Disabled</b></span>: {GLib.markup_escape_text(status_message)}")
                self.btn_toggle_schedule.set_label("Enable Scheduling")
                for widget in self.details_widgets: widget.hide()
            self.lbl_day_theme.set_text(config.get("light_theme", "N/A"))
            self.lbl_day_profile.set_text(f'{config.get("day_bg_profile", "N/A")}.profile')
            self.lbl_night_theme.set_text(config.get("dark_theme", "N/A"))
            self.lbl_night_profile.set_text(f'{config.get("night_bg_profile", "N/A")}.profile')
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Core Error", f"Failed to get status: {e}")

    def _update_ui_from_backend(self):
        log.debug("Updating UI from backend screen state.")
        try:
            settings = self.xfce_handler.get_screen_settings()
            temp = settings.get("temperature", 6500)
            self.current_brightness = settings.get("brightness", 1.0)
            if self.slider_handler_id: self.slider.handler_block(self.slider_handler_id)
            self.lbl_temp_readout.set_markup(f"<span size='x-large' weight='bold'>{int(temp)} K</span>")
            self.slider.get_adjustment().set_value(temp)
        except core_exc.XfceError as e:
            log.error(f"Could not get screen settings: {e}")
        finally:
            if self.slider_handler_id: self.slider.handler_unblock(self.slider_handler_id)
    
    def on_toggle_schedule_clicked(self, widget=None):
        try:
            status = fluxfce_core.get_status()
            is_enabled = status.get("summary", {}).get("overall_status") == "[OK]"
            if is_enabled:
                fluxfce_core.disable_scheduling()
            else:
                fluxfce_core.enable_scheduling(sys.executable, str(APP_SCRIPT_PATH))
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Scheduling Error", f"Operation failed: {e}")
        self.refresh_ui()

    def on_set_default_clicked(self, widget, mode):
        dialog = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL, text=f"Confirm: Save Current Look as {mode.capitalize()} Default?")
        dialog.format_secondary_text(f"This will overwrite the current GTK theme, screen settings, and background profile for '{mode}' mode.")
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                fluxfce_core.set_default_from_current(mode)
                self.show_info_dialog("Success", f"{mode.capitalize()} mode defaults have been saved.")
                self.refresh_ui()
            except core_exc.FluxFceError as e:
                self.show_error_dialog("Save Error", f"Failed to save defaults: {e}")
        dialog.destroy()

    def on_apply_temporary_clicked(self, widget, mode):
        try:
            self._start_polling_for_temp_change()
            fluxfce_core.apply_temporary_mode(mode)
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Apply Error", f"Failed to apply {mode} mode: {e}")
            self._stop_polling()

    def on_slider_value_changed(self, slider):
        new_temp = int(slider.get_value())
        self.lbl_temp_readout.set_markup(f"<span size='x-large' weight='bold'>{new_temp} K</span>")
        if self.slider_debounce_id: GLib.source_remove(self.slider_debounce_id)
        self.slider_debounce_id = GLib.timeout_add(SLIDER_DEBOUNCE_MS, self._apply_slider_temp, new_temp)

    def _apply_slider_temp(self, temp):
        try:
            self.xfce_handler.set_screen_temp(temp, self.current_brightness)
        except (core_exc.XfceError, ValueError) as e:
            self.show_error_dialog("Apply Error", f"Failed to set screen temperature: {e}")
        self.slider_debounce_id = None
        return GLib.SOURCE_REMOVE

    def on_reset_clicked(self, widget):
        try:
            self._start_polling_for_temp_change()
            self.xfce_handler.set_screen_temp(None, None)
        except core_exc.XfceError as e:
            self.show_error_dialog("Reset Error", f"Failed to reset screen settings: {e}")
            self._stop_polling()

    def on_edit_profile_clicked(self, widget, mode):
        try:
            profile_path = fluxfce_core.get_profile_path_for_mode(mode)
            self.open_file_in_editor(profile_path)
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Error", f"Could not determine profile path: {e}")

    def on_open_config_clicked(self, widget): self.open_file_in_editor(fluxfce_core.CONFIG_FILE)
    def _stop_polling(self):
        if self.polling_source_id:
            GLib.source_remove(self.polling_source_id)
            self.polling_source_id = None
    def _start_polling_for_temp_change(self):
        self._stop_polling()
        try:
            initial_temp = self.xfce_handler.get_screen_settings().get("temperature", 6500)
        except core_exc.XfceError:
            initial_temp = self.slider.get_value()
        self.polling_source_id = GLib.timeout_add(POLLING_INTERVAL_MS, self._poll_until_temp_changes, initial_temp, POLLING_ATTEMPTS)
    def _poll_until_temp_changes(self, initial_temp, attempts_left):
        try:
            current_temp = self.xfce_handler.get_screen_settings().get("temperature", initial_temp)
        except core_exc.XfceError:
            current_temp = initial_temp
        if current_temp != initial_temp or attempts_left <= 0:
            if attempts_left <= 0: log.warning("Polling timed out. Forcing UI update.")
            self._update_ui_from_backend()
            self.polling_source_id = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

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

class Application:
    def __init__(self):
        self.indicator = None
        self.toggle_item = None
        self.window = FluxFceWindow(self)
        self._init_indicator()
        self.window.refresh_ui()

    def _init_indicator(self):
        self.indicator = AppIndicator3.Indicator.new(
            APP_ID, "emblem-synchronizing-symbolic", AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        
        menu = Gtk.Menu()
        show_item = Gtk.MenuItem()
        show_item_label = Gtk.Label(label="<b>Show/Hide fluxfce</b>", use_markup=True, xalign=0)
        show_item.add(show_item_label)
        show_item.connect("activate", self.on_show_hide_activate)
        menu.append(show_item)
        menu.append(Gtk.SeparatorMenuItem())
        self.toggle_item = Gtk.MenuItem(label="Enable/Disable Scheduling")
        self.toggle_item.connect("activate", self.on_toggle_activate)
        menu.append(self.toggle_item)
        quit_item = Gtk.MenuItem(label="Exit")
        quit_item.connect("activate", self.on_quit_activate)
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)

    def on_show_hide_activate(self, widget):
        log.debug("Show/Hide activated, toggling window.")
        if self.window.is_visible():
            self.window.hide()
        else:
            self.window.present()

    def on_toggle_activate(self, widget):
        log.debug("Toggle activated from tray menu.")
        self.window.on_toggle_schedule_clicked()

    def on_quit_activate(self, widget):
        log.debug("Quit activated from tray menu.")
        self.quit()

    def update_status(self, is_enabled):
        if self.indicator:
            if is_enabled:
                self.indicator.set_icon_full("weather-clear-symbolic", "fluxfce Enabled")
                self.toggle_item.set_label("Disable Scheduling")
            else:
                self.indicator.set_icon_full("weather-clear-night-symbolic", "fluxfce Disabled")
                self.toggle_item.set_label("Enable Scheduling")

    def run(self):
        Gtk.main()

    def quit(self):
        Gtk.main_quit()

if __name__ == "__main__":
    app = Application()
    # Call show_all() before present() to make the window contents visible.
    app.window.show_all()
    app.window.present()
    app.run()