#!/usr/bin/env python3

"""
fluxfce-temp-control - Live Screen Temperature Tool

A simple GTK3-based GUI tool to adjust screen temperature in real-time
using the `xsct` command via the fluxfce_core library.
"""

import logging
import sys
from pathlib import Path # <-- Added for robust path handling

# --- GTK and Core Library Imports ---
try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
except (ImportError, ValueError) as e:
    print("FATAL: GTK3 bindings are not installed or configured correctly.", file=sys.stderr)
    print("On Debian/Ubuntu, try: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0", file=sys.stderr)
    print(f"Error details: {e}", file=sys.stderr)
    sys.exit(1)

try:
    from fluxfce_core import xfce
    from fluxfce_core.exceptions import XfceError
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
log = logging.getLogger("fluxfce_temp_control")

# --- Asset Path ---
# Build a reliable path to the assets directory
SCRIPT_DIR = Path(__file__).resolve().parent
ASSET_PATH = SCRIPT_DIR / "fluxfce_core" / "assets" / "temp-slider.png"


# --- Main Application Class ---
class TempControlWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Screen Temperature")
        self.set_border_width(15)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(False)
        self.connect("destroy", Gtk.main_quit)

        try:
            self.xfce_handler = xfce.XfceHandler()
        except XfceError as e:
            self.show_error_dialog("Initialization Error", f"Could not start the tool.\nIs `xsct` installed and in your PATH?\n\nDetails: {e}")
            GLib.idle_add(Gtk.main_quit)
            return
            
        self.current_brightness = 1.0
        self.slider_handler_id = None

        self._build_ui()
        self._update_ui_from_backend()
        self.show_all()

    def _build_ui(self):
        """Constructs the UI layout and widgets."""
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(main_vbox)

        self.lbl_temp_readout = Gtk.Label()
        self.lbl_temp_readout.set_markup("<span size='xx-large' weight='bold'>... K</span>")
        main_vbox.pack_start(self.lbl_temp_readout, False, True, 5)

        # --- START: Layout Change for Image ---
        # Use a horizontal box for the slider and its visual guide
        control_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        main_vbox.pack_start(control_hbox, True, True, 5)

        # Add the gradient image if it exists
        if ASSET_PATH.is_file():
            log.debug(f"Loading gradient image from: {ASSET_PATH}")
            img_temp_gradient = Gtk.Image.new_from_file(str(ASSET_PATH))
            control_hbox.pack_start(img_temp_gradient, False, True, 0)
        else:
            log.warning(f"Temperature gradient image not found at: {ASSET_PATH}")
        
        # Add the slider to the horizontal box
        adjustment = Gtk.Adjustment(6500, 1000, 10000, 50, 500, 0)
        self.slider = Gtk.Scale(orientation=Gtk.Orientation.VERTICAL, adjustment=adjustment)
        self.slider.set_inverted(True)
        self.slider.set_size_request(-1, 200)
        self.slider_handler_id = self.slider.connect("value-changed", self.on_slider_value_changed)
        control_hbox.pack_start(self.slider, True, True, 0)
        # --- END: Layout Change for Image ---

        btn_reset = Gtk.Button(label="Reset to Default")
        btn_reset.connect("clicked", self.on_reset_clicked)
        main_vbox.pack_start(btn_reset, False, True, 5)
        
    def _update_ui_from_backend(self):
        """Fetches the current screen state and updates the UI."""
        log.debug("Updating UI from backend screen state.")
        try:
            settings = self.xfce_handler.get_screen_settings()
            temp = settings.get("temperature")
            self.current_brightness = settings.get("brightness") or 1.0

            if temp is None:
                temp = 6500
                log.info("No temperature set (xsct is likely off). UI defaulting to 6500K.")

            if self.slider_handler_id:
                self.slider.handler_block(self.slider_handler_id)

            self.lbl_temp_readout.set_markup(f"<span size='xx-large' weight='bold'>{temp} K</span>")
            self.slider.get_adjustment().set_value(temp)
            
        except XfceError as e:
            self.show_error_dialog("Error", f"Could not get screen settings: {e}")
        finally:
            if self.slider_handler_id:
                self.slider.handler_unblock(self.slider_handler_id)

    # --- Signal Handlers ---
    def on_slider_value_changed(self, widget):
        """Called when the user moves the slider."""
        new_temp = int(widget.get_value())
        self.lbl_temp_readout.set_markup(f"<span size='xx-large' weight='bold'>{new_temp} K</span>")
        
        try:
            log.info(f"Setting screen: Temp={new_temp}, Brightness={self.current_brightness:.2f}")
            self.xfce_handler.set_screen_temp(new_temp, self.current_brightness)
        except (XfceError, ValueError) as e:
            self.show_error_dialog("Apply Error", f"Failed to set screen temperature: {e}")

    def on_reset_clicked(self, widget):
        """Called when the reset button is clicked."""
        log.info("Resetting screen temperature/brightness via button.")
        try:
            self.xfce_handler.set_screen_temp(None, None)
            self._update_ui_from_backend()
        except XfceError as e:
            self.show_error_dialog("Reset Error", f"Failed to reset screen settings: {e}")
            
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


if __name__ == "__main__":
    win = TempControlWindow()
    if win.get_window(): # Check if window was successfully created
        Gtk.main()