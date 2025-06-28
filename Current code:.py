Current code:

```
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
    from gi.repository import Gtk, GLib, Pango, GdkPixbuf
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
UI_REFRESH_INTERVAL_MS = 60 * 1000  # 1 minute

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
        self.action_button_size_group = Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL)

        # --- NEW: Timers for UI updates ---
        self.periodic_refresh_id = None  # The 1-minute timer for the countdown
        self.one_shot_refresh_id = None  # The precise timer for post-transition refresh
        self.connect("show", self._start_ui_timers)
        self.connect("hide", self._stop_ui_timers)

        self._build_ui()
        # The initial refresh is now handled by the window's 'show' signal

    def on_close_button_pressed(self, widget, event):
        self.hide()
        return True

    # --- NEW: Consolidated timer management ---
    def _start_ui_timers(self, widget=None):
        """Starts the periodic UI refresh timer and does an initial refresh."""
        self._stop_ui_timers() # Ensure no old timers are running
        log.info("Window shown. Starting UI refresh timers.")
        # We do an immediate, full refresh when the window is shown
        # so the user doesn't have to wait for the first tick.
        self.refresh_ui()
        # Start the 1-minute periodic timer
        self.periodic_refresh_id = GLib.timeout_add(UI_REFRESH_INTERVAL_MS, self._on_periodic_refresh_tick)

    def _stop_ui_timers(self, widget=None):
        """Stops all UI refresh timers."""
        if self.periodic_refresh_id:
            log.info("Stopping periodic UI refresh timer.")
            GLib.source_remove(self.periodic_refresh_id)
            self.periodic_refresh_id = None
        if self.one_shot_refresh_id:
            log.info("Stopping one-shot UI refresh timer.")
            GLib.source_remove(self.one_shot_refresh_id)
            self.one_shot_refresh_id = None

    def _on_periodic_refresh_tick(self):
        """Called by the GLib timer to refresh the UI periodically."""
        log.debug("Periodic UI refresh tick.")
        self.refresh_ui()
        return GLib.SOURCE_CONTINUE # Keep the timer running

    # --- NEW: Callback for the one-shot timer ---
    def _on_transition_occurs(self):
        """
        One-shot callback fired just after a scheduled transition.
        Triggers a full UI refresh to show the new state.
        """
        log.info("Scheduled transition time has passed. Refreshing UI.")
        self.one_shot_refresh_id = None # The timer is now spent
        self.refresh_ui()
        return GLib.SOURCE_REMOVE # Ensures the timer only runs once

    # --- MODIFIED: `refresh_ui` now manages the one-shot timer ---
    def refresh_ui(self):
        """
        Refreshes the entire UI by fetching the latest status from the core library.
        Also schedules a one-shot timer to refresh again after the next transition.
        """
        # First, cancel any pending one-shot timer before we create a new one.
        if self.one_shot_refresh_id:
            GLib.source_remove(self.one_shot_refresh_id)
            self.one_shot_refresh_id = None

        try:
            status = fluxfce_core.get_status()
            summary = status.get("summary", {})
            config = status.get("config", {})
            is_enabled = summary.get("overall_status") == "[OK]"

            self.app.update_status(is_enabled)

            if is_enabled:
                self.lbl_overall_status.set_markup("<b><span color='#2E8B57'>Enabled</span></b>")
                self.btn_toggle_schedule.set_label("Disable Scheduling")
                for widget in self.details_widgets: widget.show()

                next_time = summary.get("next_transition_time")
                if next_time:
                    delta = next_time - datetime.now(next_time.tzinfo)
                    time_left_str = "in the past" if delta.total_seconds() < 0 else f"in {int(delta.seconds / 3600)}h {int((delta.seconds % 3600) / 60)}m"
                    next_mode = GLib.markup_escape_text(summary.get('next_transition_mode', ''))
                    next_time_str = GLib.markup_escape_text(f"{next_time.strftime('%H:%M')} ({time_left_str})")
                    self.lbl_next_transition.set_markup(f"<b>{next_mode}</b> at <b>{next_time_str}</b>")

                    # --- NEW: Schedule the anticipatory refresh ---
                    delta_ms = delta.total_seconds() * 1000
                    if delta_ms > 0:
                        # Schedule a refresh 2 seconds *after* the transition to ensure
                        # the backend script has had time to complete.
                        refresh_delay_ms = int(delta_ms) + 2000
                        log.info(f"Scheduling a one-shot UI refresh in {refresh_delay_ms / 1000:.1f} seconds.")
                        self.one_shot_refresh_id = GLib.timeout_add(refresh_delay_ms, self._on_transition_occurs)

                else:
                    self.lbl_next_transition.set_text("Not scheduled")
            else:
                status_message = summary.get("status_message", "Could not get status.")
                self.lbl_overall_status.set_markup(f"<span color='red'><b>Disabled</b></span>: {GLib.markup_escape_text(status_message)}")
                self.btn_toggle_schedule.set_label("Enable Scheduling")
                for widget in self.details_widgets: widget.hide()

            self.lbl_day_theme.set_text(config.get("light_theme", "N/A"))
            day_profile_name = config.get("day_bg_profile", "N/A")
            self.lbl_day_profile.set_text(day_profile_name)
            self.lbl_day_profile.set_tooltip_text(f"Profile file: {day_profile_name}.profile")

            self.lbl_night_theme.set_text(config.get("dark_theme", "N/A"))
            night_profile_name = config.get("night_bg_profile", "N/A")
            self.lbl_night_profile.set_text(night_profile_name)
            self.lbl_night_profile.set_tooltip_text(f"Profile file: {night_profile_name}.profile")

            # --- MODIFIED: Ensure temp slider updates during a refresh ---
            self._update_ui_from_backend()

        except core_exc.FluxFceError as e:
            self.show_error_dialog("Core Error", f"Failed to get status: {e}")

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
        # Trigger a full refresh to update the UI and schedule the next one-shot timer
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

    def _on_ui_refresh_tick(self):
        """Called by the GLib timer to refresh the UI."""
        log.debug("UI refresh timer tick.")
        self.refresh_ui()
        # Return True (or GLib.SOURCE_CONTINUE) to keep the timer running
        return GLib.SOURCE_CONTINUE

    def _start_ui_refresh_timer(self, widget=None):
        """Starts the periodic UI refresh timer."""
        # First, ensure any existing timer is stopped before starting a new one.
        self._stop_ui_refresh_timer()
        
        # We do an immediate refresh when the window is shown
        # so the user doesn't have to wait for the first tick.
        self.refresh_ui()
        
        log.info("Starting UI refresh timer.")
        self.ui_refresh_timer_id = GLib.timeout_add(
            UI_REFRESH_INTERVAL_MS, self._on_ui_refresh_tick
        )

    def _stop_ui_refresh_timer(self, widget=None):
        """Stops the periodic UI refresh timer."""
        if self.ui_refresh_timer_id:
            log.info("Stopping UI refresh timer.")
            GLib.source_remove(self.ui_refresh_timer_id)
            self.ui_refresh_timer_id = None

    def on_edit_profile_clicked(self, widget, mode):
        try:
            # 1. Get the current status which contains config info
            status = fluxfce_core.get_status()
            config = status.get("config", {})

            # 2. Get the specific profile name for the mode ('day' or 'night')
            # The key in config.ini is like 'day_bg_profile'
            profile_key = f"{mode}_bg_profile"
            profile_name = config.get(profile_key)

            if not profile_name:
                raise core_exc.FluxFceError(f"Could not find '{profile_key}' in your configuration.")

            # 3. Construct the full path, including the 'backgrounds' subdirectory
            config_dir = fluxfce_core.CONFIG_FILE.parent
            backgrounds_dir = config_dir / "backgrounds"
            profile_path = backgrounds_dir / f"{profile_name}.profile"
            
            self.open_file_in_editor(profile_path)
            
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Error", f"Could not determine profile path:\n{e}")

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
        # The initial refresh is now handled by the window's 'show' signal
        # self.window.refresh_ui() 

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
    # Note: present() will trigger the 'show' signal, which in turn calls
    # our _start_ui_refresh_timer method for the first time.
    app.window.present()
    app.run()

```

I noticed some odd behavior: when the timer reached zero (sunset systemd unit was triggered), the timer didn't immediately update to re, but it did update after a minute or so. the ideal behavior would be for the timer to update the Next Transition time and mode immediately after the transitions. the temp control slider should also update to reflect the new value after a transition.

Does this make sense?

Is it possible to detect changes to the xfce environment to trigger a UI refresh 

(btw, Would you recommend only refreshing specific elements, namely the countdown timer and the temp control slider?)

Alternatively we could hard code a window refresh or UI elements refresh when the timer reaches zero.

Also, Ideally the temp control slider would reflect the real time value but I'm not sure that's possible without constant polling. I don't want to make changes to fluxfce_core.

Please review the code and determine the best way to approach this.