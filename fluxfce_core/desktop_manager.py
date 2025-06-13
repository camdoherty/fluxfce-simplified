# fluxfce_core/desktop_manager.py
import logging
import time
import configparser
from typing import Literal

from .xfce import XfceHandler
from .api import get_current_config
from .exceptions import XfceError, ConfigError # Consistent error imports

log = logging.getLogger(__name__)

def _load_cfg() -> configparser.ConfigParser:
    """Helper to load configuration via the API's get_current_config."""
    try:
        return get_current_config()
    except ConfigError as e: # Catch specific ConfigError from api.get_current_config
        log.error(f"desktop_manager: Failed to load configuration via api.get_current_config: {e}")
        raise # Re-raise to be caught by the caller or to propagate
    except Exception as e: # Catch any other unexpected error from get_current_config
        log.error(f"desktop_manager: Unexpected error loading configuration: {e}")
        # Wrap it in ConfigError or a more general FluxFceError if defined
        raise ConfigError(f"Unexpected error loading configuration: {e}")


def handle_gradual_transition(mode: Literal["day", "night"]) -> bool:
    """
    Performs a gradual transition of screen temperature and brightness.
    This is a long-running process intended to be called by a systemd service.
    """
    log.info(f"Starting gradual transition to '{mode}' mode.")
    xfce_handler = None # Initialize to allow access in finally block if needed, though not used there currently

    try:
        conf = _load_cfg()
        xfce_handler = XfceHandler() # Instantiated here

        # 1. Get configuration values
        duration_minutes = conf.getint("Transitions", "DURATION_MINUTES", fallback=15)
        target_section = "ScreenDay" if mode == "day" else "ScreenNight"
        target_temp = conf.getint(target_section, "XSCT_TEMP")
        target_bright = conf.getfloat(target_section, "XSCT_BRIGHT")

        # 2. Get starting values from the live desktop
        start_settings = None # Initialize to None
        try:
            start_settings = xfce_handler.get_screen_settings()
        except XfceError as e:
            log.error(f"Could not get current screen settings: {e}. Aborting transition.")
            return False

        raw_start_temp = start_settings.get("temperature") if start_settings else None
        raw_start_bright = start_settings.get("brightness") if start_settings else None

        start_temp = raw_start_temp if raw_start_temp is not None else 6500
        start_bright = raw_start_bright if raw_start_bright is not None else 1.0

        log.debug(f"Raw start_settings from xfce_handler: temp={raw_start_temp}, bright={raw_start_bright}")
        log.debug(f"Effective start values for transition: temp={start_temp}K, bright={start_bright:.2f}")

        # 3. Calculate steps
        total_seconds = duration_minutes * 60
        if total_seconds <= 0:
            log.warning(f"Transition duration is {duration_minutes}m. Must be > 0. Aborting.")
            return False

        step_interval_seconds = 2
        num_steps = int(total_seconds / step_interval_seconds)

        if num_steps < 1:
            log.info(f"Transition duration ({duration_minutes}m) is too short for any steps with a {step_interval_seconds}s interval. The main timer will handle the change.")
            return True

        temp_delta = target_temp - start_temp
        bright_delta = target_bright - start_bright

        temp_per_step = temp_delta / num_steps
        bright_per_step = bright_delta / num_steps

        log.info(
            f"Transitioning over {duration_minutes}m ({num_steps} steps, interval {step_interval_seconds}s): "
            f"Temp: {start_temp}K -> {target_temp}K (step: {temp_per_step:.2f}K), "
            f"Bright: {start_bright:.2f} -> {target_bright:.2f} (step: {bright_per_step:.3f})"
        )

        # 4. Execute transition loop
        for i in range(1, num_steps + 1):
            current_temp_float = start_temp + temp_per_step * i
            current_bright_float = start_bright + bright_per_step * i

            current_temp = int(round(current_temp_float))
            current_bright = current_bright_float

            current_bright = max(0.1, min(2.0, current_bright))
            current_temp = max(1000, min(10000, current_temp))

            log.debug(f"Step {i}/{num_steps}: Setting Temp={current_temp}K, Bright={current_bright:.2f}")

            try:
                xfce_handler.set_screen_temp(current_temp, current_bright)
            except XfceError as e:
                log.error(f"XFCE interaction error during step {i}: {e}. Transition may be incomplete. Continuing...")

            if i < num_steps:
                time.sleep(step_interval_seconds)

    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        log.error(f"Configuration error during transition: {e}. Ensure [Transitions], [ScreenDay], [ScreenNight] are correctly set up with XSCT_TEMP/BRIGHT.")
        return False
    except ValueError as e:
        log.error(f"Configuration value error (e.g., non-integer for TEMP or non-float for BRIGHT): {e}")
        return False
    except ConfigError as e:
        log.error(f"Failed to load configuration for transition: {e}")
        return False
    except XfceError as e:
        log.error(f"XFCE interaction error (e.g., during XfceHandler init or early call): {e}")
        return False
    except Exception as e:
        log.exception(f"An unexpected error occurred during gradual transition: {e}")
        return False

    # After the loop, explicitly set the final target values to ensure precision.
    try:
        if xfce_handler: # Check if xfce_handler was successfully initialized
            log.debug(f"Ensuring final target values are set: Temp={target_temp}K, Bright={target_bright:.2f}")
            xfce_handler.set_screen_temp(target_temp, target_bright)
    except XfceError as e:
        log.error(f"XFCE interaction error while setting final target values: {e}. The main timer should still correct this.")
        # Do not return False here, as the transition largely succeeded.

    log.info(f"Gradual transition to '{mode}' mode finished.")
    return True
