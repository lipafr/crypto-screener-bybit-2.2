"""
Time Utilities
~~~~~~~~~~~~~~

CRITICAL: Timestamp handling utilities for crypto screener.

KEY REQUIREMENTS:
1. ALL timestamps are in SECONDS (not milliseconds!)
2. Only use CLOSED candles (exclude last candle from fetch_ohlcv)
3. Round timestamps to minute boundaries
4. get_last_closed_candle_timestamp() MUST return current_minute - 60

This module is essential for correct data synchronization.
"""

import time
from datetime import datetime, timezone
from typing import Optional


def get_current_timestamp() -> int:
    """
    Get current Unix timestamp in SECONDS.
    
    Returns:
        Current timestamp in seconds
    
    Examples:
        >>> ts = get_current_timestamp()
        >>> ts > 1704800000  # Should be after 2024
        True
    """
    return int(time.time())


def get_current_minute_timestamp() -> int:
    """
    Get current timestamp rounded DOWN to minute boundary.
    
    Returns:
        Timestamp of current minute start (in seconds)
    
    Examples:
        >>> # If current time is 12:34:56
        >>> ts = get_current_minute_timestamp()
        >>> # ts will be 12:34:00
    """
    current = get_current_timestamp()
    return round_to_minute(current)


def round_to_minute(timestamp: int) -> int:
    """
    Round timestamp DOWN to minute boundary.
    
    Args:
        timestamp: Unix timestamp in seconds
    
    Returns:
        Timestamp rounded to minute (seconds component = 0)
    
    Examples:
        >>> round_to_minute(1704805456)  # 12:34:56
        1704805440  # 12:34:00
    """
    return (timestamp // 60) * 60


def get_last_closed_candle_timestamp() -> int:
    """
    Get timestamp of last CLOSED 1-minute candle.
    
    CRITICAL: This is the most recent candle we should use for analysis.
    Current candle is NOT closed yet, so we use previous minute.
    
    Returns:
        Timestamp of last closed candle (current_minute - 60 seconds)
    
    Examples:
        >>> # If current time is 12:34:56
        >>> ts = get_last_closed_candle_timestamp()
        >>> # ts will be 12:33:00 (previous minute)
    """
    current_minute = get_current_minute_timestamp()
    return current_minute - 60


def get_timestamp_n_minutes_ago(minutes: int) -> int:
    """
    Get timestamp N minutes ago (rounded to minute).
    
    Args:
        minutes: Number of minutes in the past
    
    Returns:
        Timestamp N minutes ago
    
    Examples:
        >>> # If current minute is 12:34:00
        >>> ts = get_timestamp_n_minutes_ago(15)
        >>> # ts will be 12:19:00
    """
    current_minute = get_current_minute_timestamp()
    return current_minute - (minutes * 60)


def get_candle_range_for_interval(interval_minutes: int) -> tuple[int, int]:
    """
    Get timestamp range for fetching candles for given interval.
    
    CRITICAL: Uses CLOSED candles only!
    - end_time: last closed candle (current_minute - 60)
    - start_time: end_time - interval_minutes
    
    Args:
        interval_minutes: Time interval in minutes
    
    Returns:
        Tuple of (start_timestamp, end_timestamp) in seconds
    
    Examples:
        >>> # If current time is 12:34:56
        >>> start, end = get_candle_range_for_interval(15)
        >>> # start = 12:18:00, end = 12:33:00
    """
    end_time = get_last_closed_candle_timestamp()
    start_time = end_time - (interval_minutes * 60)
    return start_time, end_time


def minutes_between_timestamps(ts1: int, ts2: int) -> int:
    """
    Calculate number of complete minutes between two timestamps.
    
    Args:
        ts1: First timestamp (seconds)
        ts2: Second timestamp (seconds)
    
    Returns:
        Number of complete minutes
    
    Examples:
        >>> minutes_between_timestamps(1704805440, 1704806340)
        15
    """
    return abs(ts2 - ts1) // 60


def timestamp_to_datetime(timestamp: int) -> datetime:
    """
    Convert Unix timestamp to datetime object (UTC).
    
    Args:
        timestamp: Unix timestamp in seconds
    
    Returns:
        Datetime object in UTC timezone
    
    Examples:
        >>> dt = timestamp_to_datetime(1704805440)
        >>> dt.year
        2024
    """
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def datetime_to_timestamp(dt: datetime) -> int:
    """
    Convert datetime object to Unix timestamp.
    
    Args:
        dt: Datetime object
    
    Returns:
        Unix timestamp in seconds
    
    Examples:
        >>> dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        >>> ts = datetime_to_timestamp(dt)
        >>> ts > 0
        True
    """
    return int(dt.timestamp())


def format_timestamp(timestamp: int, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format timestamp as string.
    
    Args:
        timestamp: Unix timestamp in seconds
        fmt: Format string (strftime format)
    
    Returns:
        Formatted time string
    
    Examples:
        >>> format_timestamp(1704805440)
        '2024-01-09 12:34:00'
    """
    dt = timestamp_to_datetime(timestamp)
    return dt.strftime(fmt)


def is_timestamp_in_last_n_minutes(timestamp: int, minutes: int) -> bool:
    """
    Check if timestamp is within last N minutes.
    
    Args:
        timestamp: Unix timestamp in seconds
        minutes: Number of minutes
    
    Returns:
        True if timestamp is within last N minutes
    
    Examples:
        >>> # Check if timestamp is recent
        >>> is_timestamp_in_last_n_minutes(get_current_timestamp(), 5)
        True
    """
    current = get_current_timestamp()
    threshold = current - (minutes * 60)
    return timestamp >= threshold


def get_day_start_timestamp() -> int:
    """
    Get timestamp of current day start (00:00:00 UTC).
    
    Returns:
        Timestamp of day start
    
    Examples:
        >>> ts = get_day_start_timestamp()
        >>> dt = timestamp_to_datetime(ts)
        >>> dt.hour == 0 and dt.minute == 0
        True
    """
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return datetime_to_timestamp(day_start)


def get_week_start_timestamp() -> int:
    """
    Get timestamp of current week start (Monday 00:00:00 UTC).
    
    Returns:
        Timestamp of week start
    """
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()
    week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = week_start.replace(day=now.day - days_since_monday)
    return datetime_to_timestamp(week_start)


def get_month_start_timestamp() -> int:
    """
    Get timestamp of current month start (1st day 00:00:00 UTC).
    
    Returns:
        Timestamp of month start
    """
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return datetime_to_timestamp(month_start)


def validate_timestamp(timestamp: int) -> bool:
    """
    Validate that timestamp is reasonable.
    
    Checks:
    - Is positive
    - Is not in far future (max 1 year ahead)
    - Is not too old (min year 2020)
    
    Args:
        timestamp: Unix timestamp to validate
    
    Returns:
        True if timestamp is valid
    
    Examples:
        >>> validate_timestamp(1704805440)
        True
        >>> validate_timestamp(-100)
        False
    """
    if timestamp <= 0:
        return False
    
    # Year 2020 timestamp
    min_timestamp = 1577836800
    
    # 1 year in future
    max_timestamp = get_current_timestamp() + (365 * 24 * 60 * 60)
    
    return min_timestamp <= timestamp <= max_timestamp


# ============================================
# Milliseconds Conversion (for CCXT compatibility)
# ============================================

def seconds_to_milliseconds(timestamp: int) -> int:
    """
    Convert seconds to milliseconds.
    
    ONLY use this when calling CCXT methods that expect milliseconds!
    NEVER store milliseconds in database!
    
    Args:
        timestamp: Unix timestamp in seconds
    
    Returns:
        Timestamp in milliseconds
    
    Examples:
        >>> seconds_to_milliseconds(1704805440)
        1704805440000
    """
    return timestamp * 1000


def milliseconds_to_seconds(timestamp: int) -> int:
    """
    Convert milliseconds to seconds.
    
    Use this when receiving timestamps from CCXT (they return milliseconds).
    
    Args:
        timestamp: Unix timestamp in milliseconds
    
    Returns:
        Timestamp in seconds
    
    Examples:
        >>> milliseconds_to_seconds(1704805440000)
        1704805440
    """
    return timestamp // 1000


if __name__ == "__main__":
    # Test time utilities
    print("=" * 50)
    print("Time Utilities Test")
    print("=" * 50)
    
    current = get_current_timestamp()
    print(f"Current timestamp: {current}")
    print(f"Formatted: {format_timestamp(current)}")
    
    current_minute = get_current_minute_timestamp()
    print(f"\nCurrent minute: {format_timestamp(current_minute)}")
    
    last_closed = get_last_closed_candle_timestamp()
    print(f"Last closed candle: {format_timestamp(last_closed)}")
    
    start, end = get_candle_range_for_interval(15)
    print(f"\n15-minute range:")
    print(f"  Start: {format_timestamp(start)}")
    print(f"  End: {format_timestamp(end)}")
    print(f"  Minutes: {minutes_between_timestamps(start, end)}")
    
    print(f"\nDay start: {format_timestamp(get_day_start_timestamp())}")
    print(f"Week start: {format_timestamp(get_week_start_timestamp())}")
    print(f"Month start: {format_timestamp(get_month_start_timestamp())}")
