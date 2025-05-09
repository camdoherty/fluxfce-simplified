# ~/dev/fluxfce-simplified/fluxfce_core/sun.py

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Dict

# zoneinfo is standard library in Python 3.9+
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    # This is a critical dependency failure if zoneinfo is expected
    raise ImportError(
        "Required module 'zoneinfo' not found. FluxFCE requires Python 3.9+."
    )

# Import custom exceptions from within the same package
from .exceptions import CalculationError, ValidationError

log = logging.getLogger(__name__)


# --- Internal Sun Calculation Algorithm ---


def _noaa_sunrise_sunset(
    *, lat: float, lon: float, target_date: date
) -> tuple[float, float]:
    """
    Internal NOAA algorithm to calculate UTC sunrise/sunset times in minutes past midnight.

    Based on NOAA Javascript: www.esrl.noaa.gov/gmd/grad/solcalc/calcdetails.html

    Args:
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        target_date: The specific date for calculation.

    Returns:
        A tuple (sunrise_utc_minutes, sunset_utc_minutes).

    Raises:
        CalculationError: If latitude/longitude are out of range, or for
                          polar day/night conditions where calculation fails.
    """
    log.debug(
        f"Calculating NOAA sun times for lat={lat}, lon={lon}, date={target_date}"
    )
    # Validate latitude/longitude ranges (redundant if called via get_sun_times which validates input strings, but good practice)
    if not (-90 <= lat <= 90):
        raise CalculationError(
            f"Invalid latitude for calculation: {lat}. Must be between -90 and 90."
        )
    if not (-180 <= lon <= 180):
        raise CalculationError(
            f"Invalid longitude for calculation: {lon}. Must be between -180 and 180."
        )

    n = target_date.timetuple().tm_yday  # Day of year
    longitude = lon  # Use validated input directly

    # Equation of Time and Declination (approximation)
    gamma = (2 * math.pi / 365) * (
        n - 1 + (12 - (longitude / 15)) / 24
    )  # Fractional year
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )

    # Hour Angle Calculation
    lat_rad = math.radians(lat)
    # Zenith for sunrise/sunset (geometric center of sun) - 90.833 degrees
    # includes refraction and sun radius adjustment
    cos_zenith = math.cos(math.radians(90.833))
    try:
        # Argument for arccos to find hour angle
        cos_h_arg = (cos_zenith - math.sin(lat_rad) * math.sin(decl)) / (
            math.cos(lat_rad) * math.cos(decl)
        )
    except ZeroDivisionError:
        # This can happen near the poles if cos(decl) is near zero
        raise CalculationError(
            "Division by zero encountered during hour angle calculation (likely near poles)."
        )

    # Check for polar day/night conditions
    if cos_h_arg > 1.0:
        # Sun never rises (polar night)
        raise CalculationError(
            f"Sun never rises on {target_date} at lat {lat} (polar night)."
        )
    if cos_h_arg < -1.0:
        # Sun never sets (polar day)
        raise CalculationError(
            f"Sun never sets on {target_date} at lat {lat} (polar day)."
        )

    try:
        ha_rad = math.acos(cos_h_arg)  # Hour angle in radians
        ha_minutes = 4 * math.degrees(
            ha_rad
        )  # Convert hour angle to minutes (15 deg/hour * 4 min/deg)
    except ValueError as e:
        # Should not happen due to checks above, but safeguard
        raise CalculationError(f"Error calculating arccos for hour angle: {e}") from e

    # Solar noon (in minutes from UTC midnight)
    solar_noon_utc_min = 720 - 4 * longitude - eqtime  # 720 = 12 * 60

    sunrise_utc_min = solar_noon_utc_min - ha_minutes
    sunset_utc_min = solar_noon_utc_min + ha_minutes

    log.debug(
        f"Calculated UTC times (minutes from midnight): sunrise={sunrise_utc_min:.2f}, sunset={sunset_utc_min:.2f}"
    )
    return sunrise_utc_min, sunset_utc_min


# --- Public API for Sun Times ---


def get_sun_times(
    lat: float, lon: float, target_date: date, tz_name: str
) -> Dict[str, datetime]:
    """
    Calculates sunrise and sunset times, returning them as timezone-aware datetimes.

    Args:
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        target_date: The date for which to calculate times.
        tz_name: The IANA timezone name (e.g., 'America/Toronto').

    Returns:
        A dictionary {'sunrise': datetime_obj, 'sunset': datetime_obj} where
        datetime objects are timezone-aware for the specified tz_name.

    Raises:
        ValidationError: If the timezone name is invalid or not found by zoneinfo.
        CalculationError: If the underlying NOAA calculation fails (e.g., invalid
                          lat/lon passed internally, polar day/night).
    """
    log.debug(
        f"Getting sun times for lat={lat}, lon={lon}, date={target_date}, timezone={tz_name}"
    )
    try:
        tz_info = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        log.error(f"Invalid or unknown IANA Timezone Name: '{tz_name}'")
        raise ValidationError(f"Invalid or unknown IANA Timezone Name: '{tz_name}'")
    except Exception as e:  # Catch other potential zoneinfo errors
        log.error(f"Error loading timezone '{tz_name}': {e}")
        raise ValidationError(f"Error loading timezone '{tz_name}': {e}") from e

    try:
        # Call the internal algorithm
        sunrise_min, sunset_min = _noaa_sunrise_sunset(
            lat=lat, lon=lon, target_date=target_date
        )
    except CalculationError as e:
        # Propagate calculation errors (like polar day/night)
        log.error(f"Sun time calculation failed: {e}")
        raise  # Re-raise the specific CalculationError

    # Convert minutes from UTC midnight to datetime objects
    # Create a UTC midnight datetime for the target date
    utc_midnight = datetime(
        target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc
    )

    # Add the calculated minutes to get the UTC event times
    sunrise_utc_dt = utc_midnight + timedelta(minutes=sunrise_min)
    sunset_utc_dt = utc_midnight + timedelta(minutes=sunset_min)

    # Convert to the target local timezone
    try:
        sunrise_local = sunrise_utc_dt.astimezone(tz_info)
        sunset_local = sunset_utc_dt.astimezone(tz_info)
    except Exception as e:
        # Handle potential errors during timezone conversion (less likely)
        log.exception(
            f"Failed to convert calculated UTC times to timezone '{tz_name}': {e}"
        )
        raise CalculationError(
            f"Failed timezone conversion for '{tz_name}': {e}"
        ) from e

    log.debug(
        f"Calculated local times: sunrise={sunrise_local.isoformat()}, sunset={sunset_local.isoformat()}"
    )
    return {"sunrise": sunrise_local, "sunset": sunset_local}
