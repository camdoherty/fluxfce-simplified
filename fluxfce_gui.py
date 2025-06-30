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
ASSETS_DIR = Path(__file__).resolve().parent / "fluxfce_core" / "assets"
ICON_ENABLED = str(ASSETS_DIR / "icon-enabled.png")
ICON_DISABLED = str(ASSETS_DIR / "icon-disabled.png")

class FluxFceWindow(Gtk.Window):
    """The main configuration and status window for fluxfce."""
    def __init__(self, application):
        super().__init__()
        self.app = application

        # --- Give the window a CSS name so we can style it specifically ---
        self.set_name("fluxfce-main-window")

        # Window properties
        self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        self.set_skip_taskbar_hint(True)
        self.set_border_width(8)
        self.set_default_size(360, -1)
        self.set_resizable(False)
        self.set_decorated(False)

        # Signal connections
        self.connect("delete-event", self.on_close_button_pressed)
        self.connect("focus-out-event", self.on_focus_out_event)
        self.connect("show", self._start_ui_timers)
        self.connect("hide", self._stop_ui_timers)
        self.connect("size-allocate", self._on_size_allocated)

        # --- Read opacities from config and prepare for transparency ---
        try:
            config = fluxfce_core.get_current_config()
            # Read window background opacity
            opacity = config.getfloat("GUI", "opacity", fallback=1.0)
            opacity = max(0.0, min(1.0, opacity))
            # Read widget opacity
            widget_opacity = config.getfloat("GUI", "widget_opacity", fallback=1.0)
            widget_opacity = max(0.0, min(1.0, widget_opacity))
        except (core_exc.ConfigError, ValueError) as e:
            log.warning(f"Could not read GUI opacity from config, defaulting to opaque. Error: {e}")
            opacity = 1.0
            widget_opacity = 1.0

        window_bg_css = ""
        widget_opacity_css = ""
        screen = self.get_screen()

        if screen.is_composited():
            if opacity < 1.0:
                log.info(f"Compositor detected. Applying window opacity: {opacity}")
                visual = screen.get_rgba_visual()
                if visual:
                    self.set_visual(visual)

                window_bg_css = f"""
                #fluxfce-main-window {{
                    background-color: alpha(@theme_bg_color, {opacity});
                    border-radius: 8px;
                }}
                """
            else:
                 log.info("No compositor or opacity is 1.0, using solid theme background.")
                 window_bg_css = """
                 #fluxfce-main-window {
                     background-color: @theme_bg_color;
                     border-radius: 8px;
                 }
                 """

            if widget_opacity < 1.0:
                log.info(f"Applying widget opacity: {widget_opacity}")
                # This rule targets every widget inside the main window
                widget_opacity_css = f"""
                #fluxfce-main-window * {{
                    opacity: {widget_opacity};
                }}
                """
        else:
            log.info("No compositor detected, window and widgets will be fully opaque.")
            window_bg_css = """
            #fluxfce-main-window {
                background-color: @theme_bg_color;
                border-radius: 8px;
            }
            """

        # Custom styling with CSS for gradients and expanders
        style_provider = Gtk.CssProvider()
        # Combine the dynamic window/widget CSS with the static widget CSS
        css = f"""
        {window_bg_css}
        {widget_opacity_css}

        .dim-label {{
            color: alpha(currentColor, 0.7);
        }}
        .temp-gradient {{
            background-image: linear-gradient(to right,
                #FF6600, #FFD8B1 35%, #FFFFFF 50%, #D4E4FF 65%, #B3CFFF);
            border-radius: 4px;
        }}
        .bright-gradient {{
            background-image: linear-gradient(to right, black, white);
            border-radius: 4px;
        }}
        expander > header .expander-arrow {{
            opacity: 0; min-width: 0; padding: 0; border: 0;
        }}

        scale.transparent-slider.horizontal trough,
        scale.transparent-slider.horizontal trough > progress,
        scale.transparent-slider.horizontal trough > fill,
        scale.transparent-slider.horizontal trough > highlight {{
            background-image: none;
            background-color: transparent;
            border-color: transparent;
            border-style: none;
            box-shadow: none;
            min-height: 1px;
        }}

        scale.transparent-slider.horizontal trough,
        scale.transparent-slider.horizontal trough > highlight {{
            border-image: none;
        }}

        scale.transparent-slider.horizontal slider {{
            min-width: 20px;
            min-height: 20px;
        }}
        """.encode('utf-8')

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
        self.btn_apply_day = None
        self.btn_apply_night = None
        self.toggle_switch_handler_id = None
        self.temp_slider_handler_id = None
        self.bright_slider_handler_id = None
        self.slider_debounce_id = None
        self.periodic_refresh_id = None
        self.one_shot_refresh_id = None
        self._last_height = None

        # --- Size groups for aligning profile and manual control columns ---
        self.col0_size_group = Gtk.SizeGroup(Gtk.SizeGroupMode.HORIZONTAL)
        self.col2_size_group = Gtk.SizeGroup(Gtk.SizeGroupMode.HORIZONTAL)

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
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(main_vbox)

    #    main_vbox.pack_start(self._build_title_bar(), False, True, 0)
        main_vbox.pack_start(self._build_status_section(), False, True, 0)
        main_vbox.pack_start(self._build_profiles_section(), False, True, 0)

        # Add a separator for visual distinction between major sections
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(2)
        separator.set_margin_bottom(2)
        main_vbox.pack_start(separator, False, True, 0)

        main_vbox.pack_start(self._build_manual_control_section(), False, True, 0)

    def _build_status_section(self):
        """Builds the top section with next transition info and toggle switch."""
        # The main container for this whole section
        section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # The hbox for the label and switch
        next_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.lbl_next_transition = Gtk.Label(label="...", xalign=0, ellipsize=Pango.EllipsizeMode.END, wrap=True, justify=Gtk.Justification.LEFT)
        next_hbox.pack_start(self.lbl_next_transition, True, True, 0)

        self.toggle_switch = Gtk.Switch()
        self.toggle_switch.set_valign(Gtk.Align.CENTER)
        self.toggle_switch.set_tooltip_text("Enable or disable automatic theme and screen transitions")
        self.toggle_switch_handler_id = self.toggle_switch.connect("notify::active", self.on_toggle_switch_activated)
        next_hbox.pack_end(self.toggle_switch, False, False, 0)

        section_box.pack_start(next_hbox, False, True, 0)

        # Add the separator to the bottom of the section's box
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        # Add a top margin to the separator to create space between it and the status text
        separator.set_margin_top(3)
        section_box.pack_start(separator, False, True, 0)

        return section_box

    def _build_profiles_section(self):
        # Use an expander to allow collapsing this section
        frame = Gtk.Expander(use_markup=True, label="<b>Mode</b>")
        frame.set_expanded(True)

        profile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=4)
        frame.add(profile_box)

        # Create and store all the new widgets for the 'day' row
        (self.day_grid, self.lbl_day_screen, self.lbl_day_theme, self.lbl_day_background) = self._create_profile_row(
            "day", " ", "Day Mode", self.col0_size_group, self.col2_size_group
        )
        profile_box.pack_start(self.day_grid, False, False, 0)
        profile_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

        # Create and store all the new widgets for the 'night' row
        (self.night_grid, self.lbl_night_screen, self.lbl_night_theme, self.lbl_night_background) = self._create_profile_row(
            "night", " ", "Night Mode", self.col0_size_group, self.col2_size_group
        )
        profile_box.pack_start(self.night_grid, False, False, 0)
        return frame

    def _create_profile_row(self, mode, icon, title, col0_group, col2_group):
        # The main grid for this profile row
        grid = Gtk.Grid(column_spacing=8, row_spacing=2, hexpand=True)

        # --- Row 1: Buttons (in a 3-column grid to align with sliders) ---
        buttons_grid = Gtk.Grid(column_spacing=4, hexpand=True)
        grid.attach(buttons_grid, 0, 0, 2, 1)

        btn_apply = Gtk.Button(halign=Gtk.Align.FILL, hexpand=True)

        # Store the button so its tooltip can be updated dynamically.
        if mode == 'day':
            self.btn_apply_day = btn_apply
        else:
            self.btn_apply_night = btn_apply

        btn_apply_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_apply_box.pack_start(Gtk.Label(label=icon), False, False, 0)
        btn_apply_box.pack_start(Gtk.Label(label=title), False, False, 0)
        btn_apply.add(btn_apply_box)
        btn_apply.connect("clicked", self.on_apply_temporary_clicked, mode)

        btn_save = Gtk.Button.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON)
        btn_save.set_tooltip_text(f"Save current desktop look as the new {mode.capitalize()} default")
        btn_save.connect("clicked", self.on_set_default_clicked, mode)

        # Column 1: The expanding "Apply" button
        buttons_grid.attach(btn_apply, 1, 0, 1, 1)

        # Column 2: The "Save" button
        col2_group.add_widget(btn_save)
        buttons_grid.attach(btn_save, 2, 0, 1, 1)

        # --- Row 2: Details Grid for proper alignment ---
        details_grid = Gtk.Grid(column_spacing=22, row_spacing=1, margin_top=4, margin_start=30)
        details_grid.get_style_context().add_class("dim-label")
        details_grid.set_column_homogeneous(False)
        details_grid.set_hexpand(True)
        grid.attach(details_grid, 0, 1, 2, 1) # Span both columns

        # Create labels for Screen, Theme, Background
        lbl_screen_title = Gtk.Label(label="Screen:", xalign=0, yalign=0.5)
        lbl_theme_title = Gtk.Label(label="Theme:", xalign=0, yalign=0.5)
        lbl_background_title = Gtk.Label(label="Background:", xalign=0, yalign=0.5)

        lbl_screen_value = Gtk.Label(xalign=0, yalign=0.5, use_markup=True, ellipsize=Pango.EllipsizeMode.END)
        lbl_theme_value = Gtk.Label(xalign=0, yalign=0.5, use_markup=True, ellipsize=Pango.EllipsizeMode.END)
        lbl_background_value = Gtk.Label(xalign=0, yalign=0.5, use_markup=True, ellipsize=Pango.EllipsizeMode.END)

        # --- Create EventBox for clickable links ---
        theme_event_box = Gtk.EventBox()
        theme_event_box.add(lbl_theme_value)
        theme_event_box.connect("button-press-event", self.on_details_link_clicked, "theme", mode)

        background_event_box = Gtk.EventBox()
        background_event_box.add(lbl_background_value)
        background_event_box.connect("button-press-event", self.on_details_link_clicked, "background", mode)

        # Attach all labels to the details grid in the new order
        details_grid.attach(lbl_screen_title, 0, 0, 1, 1)
        details_grid.attach(lbl_screen_value, 1, 0, 1, 1)
        details_grid.attach(lbl_theme_title, 0, 1, 1, 1)
        details_grid.attach(theme_event_box, 1, 1, 1, 1)
        details_grid.attach(lbl_background_title, 0, 2, 1, 1)
        details_grid.attach(background_event_box, 1, 2, 1, 1)

        # Return the main grid and the individual value labels so they can be updated
        return grid, lbl_screen_value, lbl_theme_value, lbl_background_value

    def _build_manual_control_section(self):
        # Use an expander to allow collapsing this section
        frame = Gtk.Expander(use_markup=True, label="<b>X Screen Control</b>")
        frame.set_expanded(True)
        frame.set_tooltip_text("Adjust screen temperature and brightness")

        # Use a Grid for precise alignment
        grid = Gtk.Grid(column_spacing=4, row_spacing=2, margin=4, hexpand=True)
        frame.add(grid)

        # --- Temperature Control ---
        temp_overlay = Gtk.Overlay(height_request=45)
        grid.attach(temp_overlay, 1, 0, 1, 1)

        temp_gradient_bar = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER, height_request=12, margin_start=5, margin_end=5)
        temp_gradient_bar.get_style_context().add_class("temp-gradient")
        temp_overlay.add(temp_gradient_bar)

        adj_temp = Gtk.Adjustment(value=6500, lower=1000, upper=10000, step_increment=50, page_increment=200)
        self.slider_temp = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj_temp, draw_value=False, hexpand=True)
        self.slider_temp.get_style_context().add_class("transparent-slider")
        self.temp_slider_handler_id = self.slider_temp.connect("value-changed", self.on_slider_value_changed)
        temp_overlay.add_overlay(self.slider_temp)

        self.lbl_temp_readout = Gtk.Label(label="... K", width_chars=6)
        temp_reset_box = Gtk.EventBox()
        temp_reset_box.add(self.lbl_temp_readout)
        temp_reset_box.set_tooltip_text("Click to reset temperature")
        temp_reset_box.connect("button-press-event", self.on_reset_label_clicked, "temp")

        temp_icon = Gtk.Image.new_from_icon_name("weather-clear-symbolic", Gtk.IconSize.BUTTON)
        self.col0_size_group.add_widget(temp_icon)
        self.col2_size_group.add_widget(temp_reset_box)
        grid.attach(temp_icon, 0, 0, 1, 1)
        grid.attach(temp_reset_box, 2, 0, 1, 1)

        # --- Brightness Control ---
        bright_overlay = Gtk.Overlay(height_request=45)
        grid.attach(bright_overlay, 1, 1, 1, 1)

        bright_gradient_bar = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER, height_request=12, margin_start=5, margin_end=5)
        bright_gradient_bar.get_style_context().add_class("bright-gradient")
        bright_overlay.add(bright_gradient_bar)

        adj_bright = Gtk.Adjustment(value=1.0, lower=0.1, upper=1.0, step_increment=0.01, page_increment=0.02)
        self.slider_bright = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj_bright, draw_value=False, hexpand=True)
        self.slider_bright.get_style_context().add_class("transparent-slider")
        self.bright_slider_handler_id = self.slider_bright.connect("value-changed", self.on_slider_value_changed)
        bright_overlay.add_overlay(self.slider_bright)

        self.lbl_bright_readout = Gtk.Label(label="... %", width_chars=5)
        bright_reset_box = Gtk.EventBox()
        bright_reset_box.add(self.lbl_bright_readout)
        bright_reset_box.set_tooltip_text("Click to reset brightness")
        bright_reset_box.connect("button-press-event", self.on_reset_label_clicked, "bright")

        bright_icon = Gtk.Image.new_from_icon_name("display-brightness-symbolic", Gtk.IconSize.BUTTON)
        self.col0_size_group.add_widget(bright_icon)
        self.col2_size_group.add_widget(bright_reset_box)
        grid.attach(bright_icon, 0, 1, 1, 1)
        grid.attach(bright_reset_box, 2, 1, 1, 1)

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
            self._update_profile_tooltips(status.get("summary", {}))
        except core_exc.FluxFceError as e:
            self.show_error_dialog("Core Error", f"Failed to get status: {e}")

    def _update_profile_tooltips(self, summary):
        """Updates the tooltips for the apply buttons based on scheduling status."""
        is_enabled = summary.get("overall_status") == "[OK]"

        # Tooltip for Day Button
        if self.btn_apply_day:
            if is_enabled:
                tooltip = "Apply Day Mode. Scheduling will remain enabled."
            else:
                tooltip = "Apply Day Mode. This setting will persist because scheduling is disabled."
            self.btn_apply_day.set_tooltip_text(tooltip)

        # Tooltip for Night Button
        if self.btn_apply_night:
            if is_enabled:
                tooltip = "Apply Night Mode. Scheduling will remain enabled."
            else:
                tooltip = "Apply Night Mode. This setting will persist because scheduling is disabled."
            self.btn_apply_night.set_tooltip_text(tooltip)

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
                # Calculate the relative time string first
                if delta.total_seconds() < -1:
                    time_left_str = "in the past"
                elif delta.total_seconds() < 60:
                    time_left_str = "soon"
                else:
                    time_left_str = f"{int(delta.seconds / 3600)}h {int((delta.seconds % 3600) / 60)}m"

                next_mode = summary.get('next_transition_mode', '')
                transition_term = "Sunrise" if next_mode.lower() == 'day' else "Sunset"

                # Escape any special characters in the parts of the string we don't control
                time_str = GLib.markup_escape_text(f"{next_time.strftime('%H:%M')}")
                relative_str = GLib.markup_escape_text(time_left_str)

                # Construct the final markup string with the new bolding format
                self.lbl_next_transition.set_markup(f"<b>{transition_term}</b> at {time_str} (in {relative_str})")

                delta_ms = delta.total_seconds() * 1000
                if delta_ms > 0:
                    self.one_shot_refresh_id = GLib.timeout_add(int(delta_ms) + 2000, self._on_transition_occurs)
            else:
                self.lbl_next_transition.set_text("Scheduling not configured")
        else:
            # When disabled, use the new "Transitions Disabled" markup
            self.lbl_next_transition.set_markup("Transitions <b>Disabled</b>")

    def _update_profile_display(self, mode, status, config_parser):
        config = status.get("config", {})
        if mode == "day":
            profile_name = config.get("day_bg_profile", "N/A")
            theme = config.get("light_theme", "N/A")
            temp, bright = config_parser.get("ScreenDay", "XSCT_TEMP", fallback=""), config_parser.get("ScreenDay", "XSCT_BRIGHT", fallback="")
            lbl_screen_value, lbl_theme_value, lbl_background_value = self.lbl_day_screen, self.lbl_day_theme, self.lbl_day_background
        else: # night
            profile_name = config.get("night_bg_profile", "N/A")
            theme = config.get("dark_theme", "N/A")
            temp, bright = config_parser.get("ScreenNight", "XSCT_TEMP", fallback=""), config_parser.get("ScreenNight", "XSCT_BRIGHT", fallback="")
            lbl_screen_value, lbl_theme_value, lbl_background_value = self.lbl_night_screen, self.lbl_night_theme, self.lbl_night_background

        # --- Set Screen Label ---
        temp_str = f"{temp} K" if temp else "Default"
        bright_str = f"{float(bright):.0%}" if bright else "Default"
        lbl_screen_value.set_markup(f"<small><b>{temp_str}</b>, <b>{bright_str}</b></small>")
        lbl_screen_value.set_tooltip_text("Current screen settings for this mode (use controls below to adjust)")

        # --- Set Theme Label ---
        lbl_theme_value.set_markup(f"<small><u><b>{GLib.markup_escape_text(theme)}</b></u></small>")
        lbl_theme_value.set_tooltip_text("Click to open system theme preferences (xfce4-appearance-settings)")

        # --- Set Background Label ---
        lbl_background_value.set_markup(f"<small><u><b>{GLib.markup_escape_text(profile_name)}.profile</b></u></small>")
        lbl_background_value.set_tooltip_text(f"Click to edit background profile '{profile_name}.profile'")

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
        """Shows a confirmation dialog to save the current look as a new default."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,  # <-- THE FIX: Use the correct enum instead of None
            text=f"Save as {mode.capitalize()} Default?"
        )
        dialog.format_secondary_text(
            f"This will overwrite the current {mode} settings with the current "
            "desktop theme, background, and screen temp & brightness."
        )

        # Add a standard "Cancel" button
        dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        
        # Add our custom-labeled "Save" button. The underscore makes 'S' a keyboard shortcut.
        dialog.add_button(f"_Save {mode.capitalize()} Mode", Gtk.ResponseType.OK)

        # Run the dialog and get the user's response
        response = dialog.run()
        dialog.destroy()

        # Only proceed if the user clicked our custom "Save" button
        if response == Gtk.ResponseType.OK:
            try:
                fluxfce_core.set_default_from_current(mode)
                # The second confirmation dialog has been removed.
                # We still refresh the UI to show the new settings, which is good feedback.
                self.refresh_ui()
            except core_exc.FluxFceError as e:
                self.show_error_dialog("Save Error", f"Failed to save defaults: {e}")   

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

    def on_reset_label_clicked(self, widget, event, control_type):
        """Resets a slider to the default for the current day/night mode."""
        if event.button != Gdk.BUTTON_PRIMARY:
            return False

        try:
            status = fluxfce_core.get_status()
            current_mode = status.get("summary", {}).get("current_mode", "day")
            config = fluxfce_core.get_current_config()

            section = "ScreenDay" if current_mode == 'day' else "ScreenNight"
            
            # Get current screen settings to only change one value at a time
            settings = self.xfce_handler.get_screen_settings()
            temp, bright = settings.get("temperature", 6500), settings.get("brightness", 1.0)

            if control_type == "temp":
                temp = config.getint(section, "XSCT_TEMP", fallback=6500)
            elif control_type == "bright":
                bright = config.getfloat(section, "XSCT_BRIGHT", fallback=1.0)

            self.xfce_handler.set_screen_temp(temp, bright)
            GLib.timeout_add(UI_UPDATE_DELAY_MS, self._update_sliders_from_backend)

        except (core_exc.FluxFceError, ValueError) as e:
            self.show_error_dialog("Reset Error", f"Failed to reset {control_type}: {e}")

        return True # Event handled

    def on_details_link_clicked(self, widget, event, link_type, mode):
        """Handles clicks on the new Theme and Wallpaper links."""
        # We only care about the primary mouse button (left-click)
        if event.button != Gdk.BUTTON_PRIMARY:
            return False

        if link_type == "theme":
            try:
                # Use the more specific command for appearance settings
                subprocess.Popen(["xfce4-appearance-settings"])
            except (FileNotFoundError, OSError) as e:
                self.show_error_dialog("Could Not Open Settings", f"Failed to launch 'xfce4-appearance-settings'.\nError: {e}")
        elif link_type == "background":
            # Re-use the existing logic for editing profiles
            self.on_edit_profile_clicked(widget, mode)

        return True # Stop event propagation

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

    # --- TRAY WINDOW POSITIONING FIXES (START of modifications) ---

    def _calc_position(self, screen, icon_rect, win_w, win_h, orient):
        """
        Calculates window position to be adjacent to the panel, with its
        corner aligned to the mouse cursor's position at the time of click.
        """
        display = Gdk.Display.get_default()
        monitor = display.get_monitor_at_point(icon_rect.x, icon_rect.y)
        workarea = monitor.get_workarea()

        # Get the current cursor position
        _seat, cursor_x, cursor_y = display.get_default_seat().get_pointer().get_position()

        # Determine panel location based on the icon's position relative to the monitor's center
        monitor_center_x = workarea.x + workarea.width / 2
        monitor_center_y = workarea.y + workarea.height / 2
        icon_center_y = icon_rect.y + icon_rect.height / 2
        icon_center_x = icon_rect.x + icon_rect.width / 2

        if orient == Gtk.Orientation.HORIZONTAL:
            # --- Horizontal Panel (Top or Bottom) ---
            # Align window's x position with cursor, biased towards screen center
            if cursor_x < monitor_center_x:
                x = cursor_x  # Align left edge of window with cursor
            else:
                x = cursor_x - win_w  # Align right edge of window with cursor

            # Position window flush against the panel
            if icon_center_y < monitor_center_y:
                y = icon_rect.y + icon_rect.height  # Panel at top
            else:
                y = icon_rect.y - win_h  # Panel at bottom
        else:
            # --- Vertical Panel (Left or Right) ---
            # Align window's y position with cursor, biased towards screen center
            if cursor_y < monitor_center_y:
                y = cursor_y # Align top edge of window with cursor
            else:
                y = cursor_y - win_h # Align bottom edge of window with cursor

            # Position window flush against the panel
            if icon_center_x < monitor_center_x:
                x = icon_rect.x + icon_rect.width  # Panel on left
            else:
                x = icon_rect.x - win_w  # Panel on right

        # Clamp coordinates to be safely within the monitor's workarea
        x = max(workarea.x, min(x, workarea.x + workarea.width - win_w))
        y = max(workarea.y, min(y, workarea.y + workarea.height - win_h))

        return int(x), int(y)

    def show_and_position(self, status_icon):
        success, screen, icon_rect, orient = status_icon.get_geometry()
        if success:
            _min, nat = self.get_preferred_size()
            win_w, win_h = nat.width, nat.height
            # Pass the orientation to the calculation function
            x, y = self._calc_position(screen, icon_rect, win_w, win_h, orient)
            self.move(x, y)
            self.show_all()
            self.present()
        else:
            # Fallback if geometry is not immediately available
            self.show_all()
            GLib.timeout_add(50, self._get_geometry_and_move, status_icon, 0)

    def _get_geometry_and_move(self, status_icon, attempts):
        try:
            success, screen, icon_rect, orient = status_icon.get_geometry()
            if not success:
                raise RuntimeError("geometry unavailable")
            win_w, win_h = self.get_size()
            # Pass the orientation to the calculation function
            x, y = self._calc_position(screen, icon_rect, win_w, win_h, orient)
            self.move(x, y)
            self.present()
            return GLib.SOURCE_REMOVE
        except Exception:
            if attempts < 5:
                # Retry a few times if the geometry isn't ready
                GLib.timeout_add(80, self._get_geometry_and_move, status_icon, attempts + 1)
            else:
                # Final fallback to position near cursor
                self._position_near_cursor()
            return GLib.SOURCE_REMOVE
            
    # --- TRAY WINDOW POSITIONING FIXES (END of modifications) ---

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
        self.status_icon = Gtk.StatusIcon.new_from_file(ICON_DISABLED)
        self.status_icon.set_tooltip_text("fluxfce (loading...)")
        self.status_icon.set_visible(True)
        self.status_icon.connect("activate", self.on_icon_left_click)
        self.status_icon.connect("popup-menu", self.on_icon_right_click)

    

    def _build_right_click_menu(self):
        menu = Gtk.Menu()

        # --- Enable/Disable Scheduling ---
        self.toggle_item = Gtk.MenuItem(label="Enable Scheduling")
        self.toggle_item.connect("activate", self.on_menu_toggle_clicked)
        menu.append(self.toggle_item)

        # --- Edit Config ---
        edit_config_item = Gtk.MenuItem(label="Edit config.ini")
        edit_config_item.connect("activate", self.on_edit_config_clicked)
        menu.append(edit_config_item)

        # --- Open UI ---
        open_ui_item = Gtk.MenuItem(label="Open UI")
        open_ui_item.connect("activate", self.on_menu_open_ui_clicked)
        menu.append(open_ui_item)

        menu.append(Gtk.SeparatorMenuItem())

        # --- Save Mode Submenu ---
        save_menu_item = Gtk.MenuItem(label="Save Mode")
        menu.append(save_menu_item)
        save_submenu = Gtk.Menu()
        save_menu_item.set_submenu(save_submenu)
        save_day_item = Gtk.MenuItem(label="Save Current Settings as Day Mode")
        save_day_item.connect("activate", self.window.on_set_default_clicked, "day")
        save_submenu.append(save_day_item)
        save_night_item = Gtk.MenuItem(label="Save Current Settings as Night Mode")
        save_night_item.connect("activate", self.window.on_set_default_clicked, "night")
        save_submenu.append(save_night_item)

        # --- Apply Mode Submenu ---
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

        # --- Separator and Quit ---
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

    def on_menu_open_ui_clicked(self, widget):
        """Handler for the 'Open UI' menu item."""
        self.on_icon_left_click(self.status_icon)

    def on_edit_config_clicked(self, widget):
        """Opens the main config.ini file in the default editor."""
        try:
            # Use the core library's constant for the config directory
            config_path = fluxfce_core.CONFIG_DIR / "config.ini"
            self.window.open_file_in_editor(config_path)
        except Exception as e:
            # The window might not be created yet, so we can't assume show_error_dialog exists
            log.error(f"Could not open config file: {e}")

    def on_menu_toggle_clicked(self, widget):
        is_active = self.window.toggle_switch.get_active()
        self.window.toggle_switch.set_active(not is_active)

    def on_quit_activate(self, widget):
        self.quit()

    def update_status(self, is_enabled):
        if self.status_icon:
            # Set the icon from your custom files based on the is_enabled status
            if is_enabled:
                self.status_icon.set_from_file(ICON_ENABLED)
            else:
                self.status_icon.set_from_file(ICON_DISABLED)

            # The existing tooltip and menu item updates are perfect
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
