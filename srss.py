#!/usr/bin/env python3

"""
srss.py - Calculate and print sunrise/sunset times for N days.

Reads location and timezone configuration from the fluxfce config file
and calculates times using the fluxfce_core library.

Usage:
  python3 srss.py <number_of_days>
  Example: python3 srss.py 60
"""

import argparse
import logging
import sys
import time
from datetime import date, timedelta

# --- Import fluxfce_core ---
# This assumes srss.py is run from the project root (fluxfce-simplified)
# or that fluxfce_core is installed in the Python environment.
try:
    from fluxfce_core import CONFIG_FILE  # Import config path constant
    from fluxfce_core import api as fluxfce_api
    from fluxfce_core import exceptions as fluxfce_exc
    from fluxfce_core import helpers as fluxfce_helpers
    from fluxfce_core import sun as fluxfce_sun  # Direct access needed
except ImportError as e:
    print(f"Error: Failed to import fluxfce_core: {e}", file=sys.stderr)
    print("Please run this script from the project root directory", file=sys.stderr)
    print("or ensure fluxfce_core is installed.", file=sys.stderr)
    sys.exit(1)

# --- Basic Logging ---
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger('srss')

# --- Main Function ---
def main():
    parser = argparse.ArgumentParser(
        description="Calculate sunrise/sunset times for N days using fluxfce config.",
        epilog="Example: python3 srss.py 60"
    )
    parser.add_argument(
        'days',
        type=int,
        metavar='N',
        help='Number of days (starting from today) to calculate times for.'
    )
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress informational messages, only output times or errors.'
    )

    args = parser.parse_args()
    num_days = args.days

    if num_days <= 0:
        log.error("Number of days must be a positive integer.")
        sys.exit(1)

    if args.quiet:
        log.setLevel(logging.WARNING) # Suppress INFO messages

    log.info(f"Calculating sunrise/sunset for {num_days} days...")
    log.info(f"Using configuration file: {CONFIG_FILE}")

    start_time = time.monotonic()

    try:
        # 1. Load Configuration
        config = fluxfce_api.get_current_config()
        lat_str = config.get('Location', 'LATITUDE')
        lon_str = config.get('Location', 'LONGITUDE')
        tz_name = config.get('Location', 'TIMEZONE')

        # 2. Validate Location/Timezone
        if not (lat_str and lon_str and tz_name):
            raise fluxfce_exc.ConfigError("Latitude, Longitude, or Timezone missing in config.")

        lat = fluxfce_helpers.latlon_str_to_float(lat_str)
        lon = fluxfce_helpers.latlon_str_to_float(lon_str)
        # Timezone validity checked by get_sun_times, but basic check here
        if not tz_name:
             raise fluxfce_exc.ValidationError("Timezone value is empty in config.")

        log.info(f"Using Location: Lat={lat_str}, Lon={lon_str}, TZ={tz_name}")

        # 3. Loop and Calculate
        today = date.today()
        calculation_errors = 0
        output_count = 0

        print("Type\tDate\tTime") # Header
        print("----\t----\t----")

        for i in range(num_days):
            target_date = today + timedelta(days=i)
            try:
                sun_times = fluxfce_sun.get_sun_times(lat, lon, target_date, tz_name)
                # Format Output (ISO-like, tab-separated)
                date_str = target_date.isoformat()
                sunrise_time_str = sun_times['sunrise'].strftime('%H:%M:%S%z')
                sunset_time_str = sun_times['sunset'].strftime('%H:%M:%S%z')

                print(f"Sunrise\t{date_str}\t{sunrise_time_str}")
                print(f"Sunset\t{date_str}\t{sunset_time_str}")
                output_count += 2

            except fluxfce_exc.CalculationError as e:
                # Handle errors like polar day/night for specific dates
                log.warning(f"Could not calculate times for {target_date}: {e}")
                calculation_errors += 1
            except fluxfce_exc.ValidationError as e:
                # Handle invalid timezone error once if it occurs
                log.error(f"Invalid Timezone Configuration: {e}")
                sys.exit(1)

        end_time = time.monotonic()
        duration = end_time - start_time

        log.info("-" * 30)
        log.info("Calculation complete.")
        log.info(f"Total output lines: {output_count}")
        if calculation_errors > 0:
             log.warning(f"Dates with calculation errors (e.g., polar day/night): {calculation_errors}")
        log.info(f"Duration: {duration:.4f} seconds")

    except fluxfce_exc.FluxFceError as e:
        log.error(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        log.exception(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
