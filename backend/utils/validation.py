"""
Validation Utilities
~~~~~~~~~~~~~~~~~~~~

Input validation helpers for symbols, timeframes, and other data.
"""

import re
from typing import Optional


def validate_symbol(symbol: str, market: str = "spot") -> tuple[bool, Optional[str]]:
    """
    Validate trading pair symbol format.
    
    Args:
        symbol: Trading pair (e.g. 'BTC/USDT' or 'BTC/USDT:USDT')
        market: Market type ('spot' or 'futures')
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Examples:
        >>> validate_symbol("BTC/USDT", "spot")
        (True, None)
        
        >>> validate_symbol("INVALID", "spot")
        (False, "Invalid symbol format")
    """
    if not symbol or not isinstance(symbol, str):
        return False, "Symbol must be a non-empty string"
    
    # Spot format: BASE/QUOTE (e.g. BTC/USDT)
    spot_pattern = r"^[A-Z0-9]{1,10}/[A-Z]{3,10}$"
    
    # Futures format: BASE/QUOTE:SETTLE (e.g. BTC/USDT:USDT)
    futures_pattern = r"^[A-Z0-9]{1,10}/[A-Z]{3,10}:[A-Z]{3,10}$"
    
    if market == "spot":
        if not re.match(spot_pattern, symbol):
            return False, f"Invalid spot symbol format: {symbol}. Expected: BASE/QUOTE"
    
    elif market == "futures":
        if not re.match(futures_pattern, symbol):
            return False, f"Invalid futures symbol format: {symbol}. Expected: BASE/QUOTE:SETTLE"
    
    else:
        return False, f"Invalid market: {market}. Must be 'spot' or 'futures'"
    
    return True, None


def validate_timeframe(timeframe: str) -> tuple[bool, Optional[str]]:
    """
    Validate timeframe string.
    
    Args:
        timeframe: Timeframe string (e.g. '1m', '5m', '1h')
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Examples:
        >>> validate_timeframe("1m")
        (True, None)
        
        >>> validate_timeframe("invalid")
        (False, "Invalid timeframe format")
    """
    if not timeframe or not isinstance(timeframe, str):
        return False, "Timeframe must be a non-empty string"
    
    # Allowed timeframes for our use case
    allowed = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
    
    if timeframe not in allowed:
        return False, f"Invalid timeframe: {timeframe}. Allowed: {allowed}"
    
    return True, None


def validate_percentage(value: float, min_val: float = 0, max_val: float = 100) -> tuple[bool, Optional[str]]:
    """
    Validate percentage value.
    
    Args:
        value: Percentage value to validate
        min_val: Minimum allowed value
        max_val: Maximum allowed value
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Examples:
        >>> validate_percentage(5.5)
        (True, None)
        
        >>> validate_percentage(150)
        (False, "Percentage must be between 0 and 100")
    """
    if not isinstance(value, (int, float)):
        return False, "Percentage must be a number"
    
    if value < min_val or value > max_val:
        return False, f"Percentage must be between {min_val} and {max_val}"
    
    return True, None


def validate_volume(value: float) -> tuple[bool, Optional[str]]:
    """
    Validate volume value (must be positive).
    
    Args:
        value: Volume value in USD
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Examples:
        >>> validate_volume(1000.0)
        (True, None)
        
        >>> validate_volume(-100)
        (False, "Volume must be positive")
    """
    if not isinstance(value, (int, float)):
        return False, "Volume must be a number"
    
    if value < 0:
        return False, "Volume must be positive"
    
    if value == 0:
        return False, "Volume must be greater than zero"
    
    return True, None


def validate_interval_minutes(minutes: int) -> tuple[bool, Optional[str]]:
    """
    Validate interval in minutes.
    
    Args:
        minutes: Interval in minutes
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Examples:
        >>> validate_interval_minutes(15)
        (True, None)
        
        >>> validate_interval_minutes(7)
        (False, "Interval must be one of: 5, 10, 15, 30, 60, 120, 240")
    """
    if not isinstance(minutes, int):
        return False, "Interval must be an integer"
    
    # Allowed intervals (in minutes)
    allowed = [5, 10, 15, 30, 60, 120, 240]
    
    if minutes not in allowed:
        return False, f"Interval must be one of: {', '.join(map(str, allowed))}"
    
    return True, None


def validate_direction(direction: str) -> tuple[bool, Optional[str]]:
    """
    Validate price direction.
    
    Args:
        direction: Direction ('up', 'down', 'any', 'all')
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Examples:
        >>> validate_direction("up")
        (True, None)
        
        >>> validate_direction("invalid")
        (False, "Direction must be one of: up, down, any, all")
    """
    if not direction or not isinstance(direction, str):
        return False, "Direction must be a non-empty string"
    
    allowed = ['up', 'down', 'any', 'all']
    direction_lower = direction.lower()
    
    if direction_lower not in allowed:
        return False, f"Direction must be one of: {', '.join(allowed)}"
    
    return True, None


def sanitize_symbol_list(symbols: list[str]) -> list[str]:
    """
    Clean and normalize symbol list.
    
    Removes duplicates, empty strings, and converts to uppercase.
    
    Args:
        symbols: List of trading pairs
    
    Returns:
        Cleaned list of symbols
    
    Examples:
        >>> sanitize_symbol_list(["BTC/USDT", "btc/usdt", "", "ETH/USDT"])
        ['BTC/USDT', 'ETH/USDT']
    """
    if not symbols:
        return []
    
    # Convert to uppercase, remove empty, remove duplicates
    cleaned = list(set(
        s.strip().upper() 
        for s in symbols 
        if s and isinstance(s, str) and s.strip()
    ))
    
    return sorted(cleaned)


if __name__ == "__main__":
    # Test validation functions
    print("Testing validation functions...")
    
    # Symbol validation
    print("\nSymbol validation:")
    print(validate_symbol("BTC/USDT", "spot"))
    print(validate_symbol("BTC/USDT:USDT", "futures"))
    print(validate_symbol("INVALID", "spot"))
    
    # Timeframe validation
    print("\nTimeframe validation:")
    print(validate_timeframe("1m"))
    print(validate_timeframe("invalid"))
    
    # Percentage validation
    print("\nPercentage validation:")
    print(validate_percentage(5.5))
    print(validate_percentage(150))
    
    # Symbol list sanitization
    print("\nSymbol list sanitization:")
    print(sanitize_symbol_list(["BTC/USDT", "btc/usdt", "", "ETH/USDT"]))
