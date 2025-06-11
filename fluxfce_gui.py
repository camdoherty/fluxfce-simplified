#!/usr/bin/env python3

"""
fluxfce (GUI) - Simplified XFCE Theming Tool

Graphical user interface for managing automatic XFCE theme/background/screen
switching using the fluxfce_core library.
"""

import logging
import subprocess
import sys
from pathlib import Path
from datetime import datetime # <-- BUG FIX 1: Added missing import

# --- GTK and Core Library Imports ---
try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib, Pango
except (ImportError, ValueError) as e:
    print("FATAL: GTK3 bindings are not installed or configured correctly.", file=sys.stderr)
    print("On Debian/Ubuntu, try: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0", file=sys.stderr)
    print(f"Error details: {e}", file=sys.stderr)
    sys.exit(1)

try:
    import fluxfce_core
    from fluxfce_core import exceptions as core_exc
except ImportError as e:
    dialog = Gtk.MessageDialog(
        transient_for=None,
        flags=0,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.OK,
        text="Fatal Error: fluxfce_core library not found",
    )
    dialog.format_secondary_text(
        f"Could not import the core library: {e}.\n\n"
        "Please ensure fluxfce_core is installed or available in your Python path."
    )
    dialog.run()
    dialog.destroy()
    sys.exit(1)

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")
log = logging.getLogger("fluxfce_gui")


# --- Main Application Class ---
class FluxFceGui(Gtk.Window):
    def __init__(self):
        super().__init__(title="fluxfce Control Panel")
        self.set_border_width(12)
        self.set_default_size(500, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)

        self._build_ui()
        self.refresh_ui()

    def _build_ui(self):
        """Constructs the entire UI layout and widgets."""
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.add(main_vbox)

        # --- Status & Scheduling Frame ---
        status_frame = Gtk.Frame(label=" Status & Scheduling ")
        status_frame.set_label_align(0.05, 0.5)
        main_vbox.pack_start(status_frame, False, True, 0)
        self._build_status_section(status_frame)

        # --- Appearance Profiles Frame ---
        profiles_frame = Gtk.Frame(label=" Appearance Profiles ")
        profiles_frame.set_label_align(0.05, 0.5)
        main_vbox.pack_start(profiles_frame, False, True, 0)
        self._build_profiles_section(profiles_frame)

        # --- Manual Controls & Settings Frame ---
        controls_frame = Gtk.Frame(label=" Manual Controls & Settings ")
        controls_frame.set_label_align(0.05, 0.5)
        main_vbox.pack_start(controls_frame, False, True, 0)
        self._build_controls_section(controls_frame)

        self.show_all()

    def _build_status_section(self, parent_frame):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_border_width(10)
        parent_frame.add(vbox)

        # Overall Status
        hbox_status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.lbl_overall_status = Gtk.Label(label="Fetching status...")
        self.lbl_overall_status.set_xalign(0)
        self.btn_toggle_schedule = Gtk.Button(label="...")
        self.btn_toggle_schedule.connect("clicked", self.on_toggle_schedule_clicked)
        hbox_status.pack_start(self.lbl_overall_status, True, True, 0)
        hbox_status.pack_start(self.btn_toggle_schedule, False, False, 0)
        vbox.pack_start(hbox_status, True, True, 0)

        # Details Grid
        self.grid_status_details = Gtk.Grid(column_spacing=10, row_spacing=4)
        vbox.pack_start(self.grid_status_details, True, True, 5)
        self.grid_status_details.attach(Gtk.Label(label="<b>Current Period:</b>", use_markup=True, xalign=0), 0, 0, 1, 1)
        self.lbl_current_period = Gtk.Label(label="N/A", xalign=0)
        self.grid_status_details.attach(self.lbl_current_period, 1, 0, 1, 1)

        self.grid_status_details.attach(Gtk.Label(label="<b>Next Transition:</b>", use_markup=True, xalign=0), 0, 1, 1, 1)
        self.lbl_next_transition = Gtk.Label(label="N/A", xalign=0)
        self.grid_status_details.attach(self.lbl_next_transition, 1, 1, 1, 1)

    # --- BUG FIX 2: Refactored build logic for profiles ---
    def _build_profiles_section(self, parent_frame):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_border_width(10)
        parent_frame.add(vbox)

        # --- Day Mode ---
        day_grid = Gtk.Grid(column_spacing=10, row_spacing=4, margin_top=5)
        self.lbl_day_theme, self.lbl_day_profile, btn_edit_day = self._create_profile_row_widgets("day")
        self._populate_profile_grid(day_grid, "☀️ Day Mode", self.lbl_day_theme, self.lbl_day_profile, btn_edit_day)
        vbox.pack_start(day_grid, False, False, 0)

        btn_set_day = Gtk.Button(label="Save Current Look as Day Default")
        btn_set_day.connect("clicked", self.on_set_default_clicked, "day")
        vbox.pack_start(btn_set_day, False, False, 5)
        
        vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 5)

        # --- Night Mode ---
        night_grid = Gtk.Grid(column_spacing=10, row_spacing=4, margin_top=5)
        self.lbl_night_theme, self.lbl_night_profile, btn_edit_night = self._create_profile_row_widgets("night")
        self._populate_profile_grid(night_grid, "🌙 Night Mode", self.lbl_night_theme, self.lbl_night_profile, btn_edit_night)
        vbox.pack_start(night_grid, False, False, 0)
        
        btn_set_night = Gtk.Button(label="Save Current Look as Night Default")
        btn_set_night.connect("clicked", self.on_set_default_clicked, "night")
        vbox.pack_start(btn_set_night, False, False, 5)

    def _create_profile_row_widgets(self, mode):
        """Helper to create the widgets for a profile row, without parenting them."""
        lbl_theme = Gtk.Label(label="N/A", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        lbl_profile = Gtk.Label(label="N/A", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        
        btn_edit = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        btn_edit.set_tooltip_text("Open profile file in text editor")
        btn_edit.connect("clicked", self.on_edit_profile_clicked, mode)

        return lbl_theme, lbl_profile, btn_edit

    def _populate_profile_grid(self, grid, title, lbl_theme, lbl_profile, btn_edit):
        """Helper to attach widgets to a grid, solving the double-parenting issue."""
        title_label = Gtk.Label(xalign=0)
        title_label.set_markup(f"<big><b>{title}</b></big>")
        grid.attach(title_label, 0, 0, 3, 1)

        grid.attach(Gtk.Label(label="Theme:", xalign=0), 0, 1, 1, 1)
        grid.attach(lbl_theme, 1, 1, 2, 1) # Span 2 columns for text

        grid.attach(Gtk.Label(label="Profile:", xalign=0), 0, 2, 1, 1)
        grid.attach(lbl_profile, 1, 2, 1, 1) # Attach label and button separately
        grid.attach(btn_edit, 2, 2, 1, 1)
    # --- END OF BUG FIX 2 ---

    def _build_controls_section(self, parent_frame):
        grid = Gtk.Grid(column_spacing=6, row_spacing=10, halign=Gtk.Align.CENTER)
        grid.set_border_width(10)
        parent_frame.add(grid)

        btn_apply_day = Gtk.Button(label="Apply Day Mode Now")
        btn_apply_day.connect("clicked", self.on_apply_temporary_clicked, "day")
        grid.attach(btn_apply_day, 0, 0, 1, 1)

        btn_apply_night = Gtk.Button(label="Apply Night Mode Now")
        btn_apply_night.connect("clicked", self.on_apply_temporary_clicked, "night")
        grid.attach(btn_apply_night, 1, 0, 1, 1)

        btn_open_config = Gtk.Button(label="Open Configuration File (config.ini)")
        btn_open_config.connect("clicked", self.on_open_config_clicked)
        grid.attach(btn_open_config, 0, 1, 2, 1)

    # --- UI Update Logic ---
    def refresh_ui(self):
        """Fetches status from core and updates all relevant UI elements."""
        try:
            status = fluxfce_core.get_status()
            summary = status.get("summary", {})
            config = status.get("config", {})

            # Update Status Section
            is_enabled = summary.get("overall_status") == "[OK]"
            status_message = summary.get("status_message", "Could not get status.")
            
            if is_enabled:
                self.lbl_overall_status.set_markup("<span color='#2E8B57'><b>Enabled</b></span>")
                self.btn_toggle_schedule.set_label("Disable Scheduling")
                self.grid_status_details.show()
                next_time = summary.get("next_transition_time")
                if next_time:
                    delta = next_time - datetime.now(next_time.tzinfo)
                    hours, rem = divmod(delta.total_seconds(), 3600)
                    minutes, _ = divmod(rem, 60)
                    if delta.total_seconds() < 0:
                        time_left_str = "in the past"
                    elif hours >= 1:
                        time_left_str = f"in approx. {int(hours)}h {int(minutes)}m"
                    else:
                        time_left_str = f"soon"
                    self.lbl_next_transition.set_text(f"{summary.get('next_transition_mode', '')} at {next_time.strftime('%H:%M:%S')} ({time_left_str})")
                else:
                    self.lbl_next_transition.set_text("Not scheduled")
            else:
                self.lbl_overall_status.set_markup(f"<span color='red'><b>Disabled</b></span>: {GLib.markup_escape_text(status_message)}")
                self.btn_toggle_schedule.set_label("Enable Scheduling")
                self.grid_status_details.hide()

            self.lbl_current_period.set_text(status.get("current_period", "N/A").capitalize())
            
            # Update Profiles Section
            self.lbl_day_theme.set_text(config.get("light_theme", "N/A"))
            self.lbl_day_profile.set_text(config.get("day_bg_profile", "N/A") + ".profile")
            self.lbl_night_theme.set_text(config.get("dark_theme", "N/A"))
            self.lbl_night_profile.set_text(config.get("night_bg_profile", "N/A") + ".profile")

        except core_exc.FluxFceError as e:
            self.show_error_dialog("Core Error", f"Failed to get status: {e}")
            log.error(f"Error refreshing UI: {e}")

    # --- Signal Handlers ---
    def on_toggle_schedule_clicked(self, widget):
        label = widget.get_label()
        try:
            if "Disable" in label:
                fluxfce_core.disable_scheduling()
            else:
                script_path = Path(sys.argv[0]).resolve()
                fluxfce_core.enable_scheduling(sys.executable, str(script_path))
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Scheduling Error", f"Operation failed: {e}")
        self.refresh_ui()

    def on_set_default_clicked(self, widget, mode):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"Confirm: Save Current Look as {mode.capitalize()} Default?",
        )
        dialog.format_secondary_text(
            "This will overwrite the current GTK theme, screen settings, and background "
            f"profile for '{mode}' mode with your current desktop settings."
        )
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            try:
                fluxfce_core.set_default_from_current(mode)
                self.show_info_dialog("Success", f"{mode.capitalize()} mode defaults have been saved.")
            except core_exc.FluxFceError as e:
                self.show_error_dialog("Save Error", f"Failed to save defaults: {e}")
            self.refresh_ui()

    def on_apply_temporary_clicked(self, widget, mode):
        try:
            fluxfce_core.apply_temporary_mode(mode)
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Apply Error", f"Failed to apply {mode} mode: {e}")

    def on_edit_profile_clicked(self, widget, mode):
        try:
            config_obj = fluxfce_core.get_current_config()
            profile_key = "DAY_BACKGROUND_PROFILE" if mode == "day" else "NIGHT_BACKGROUND_PROFILE"
            profile_name = config_obj.get("Appearance", profile_key)
            profile_path = fluxfce_core.CONFIG_DIR / "backgrounds" / f"{profile_name}.profile"
            self.open_file_in_editor(profile_path)
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Error", f"Could not determine profile path: {e}")
            
    def on_open_config_clicked(self, widget):
        self.open_file_in_editor(fluxfce_core.CONFIG_FILE)
        
    # --- Utility Methods ---
    def show_error_dialog(self, title, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(str(message))
        dialog.run()
        dialog.destroy()
        
    def show_info_dialog(self, title, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(str(message))
        dialog.run()
        dialog.destroy()

    def open_file_in_editor(self, file_path: Path):
        if not file_path.exists():
            self.show_error_dialog("File Not Found", f"The file does not exist:\n{file_path}")
            return
        try:
            # xdg-open is the standard, desktop-agnostic way to open a file
            # with the user's preferred application.
            subprocess.Popen(["xdg-open", str(file_path)])
        except (FileNotFoundError, OSError) as e:
            self.show_error_dialog("Could Not Open File", f"Failed to launch text editor using 'xdg-open'.\nError: {e}")

if __name__ == "__main__":
    win = FluxFceGui()
    Gtk.main()