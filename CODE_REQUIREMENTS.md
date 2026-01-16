# Требования к коду

**Дата:** 2026-01-12  
**Версия:** 1.0  
**Цель:** Стандарты качества для генерации кода

---

## 1. Python Code Style

### 1.1 PEP8 Compliance

**MUST follow PEP8:**
- Отступы: 4 пробела (не табы)
- Длина строки: 88 символов (Black style)
- Blank lines: 2 между функциями/классами, 1 внутри функций
- Imports: stdlib → third-party → local, alphabetically

**Example:**
```python
import asyncio
import time
from datetime import datetime
from typing import Optional, Dict, List

import ccxt.async_support as ccxt
from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.screener.database import get_filter, create_filter
```

### 1.2 Type Hints

**MUST use type hints for all functions:**

```python
# ✅ ПРАВИЛЬНО
async def get_candles(
    symbol: str,
    market: str,
    minutes: int
) -> list[dict]:
    """Get candles from database"""
    pass

# ❌ НЕПРАВИЛЬНО
async def get_candles(symbol, market, minutes):
    pass
```

**Type hints для сложных структур:**
```python
from typing import Optional, Dict, List, Tuple

def process_data(
    tickers: Dict[str, dict],
    filters: List[dict],
    config: Optional[Dict[str, any]] = None
) -> Tuple[int, List[str]]:
    pass
```

### 1.3 Docstrings

**MUST use docstrings for all public functions:**

**Format:** Google style

```python
def check_price_change_filter(
    symbol: str,
    market: str,
    filter_config: dict,
    filter_name: str
) -> Optional[dict]:
    """
    Check if price change filter triggers for symbol.
    
    Args:
        symbol: Trading pair (e.g. 'BTC/USDT' or 'BTC/USDT:USDT')
        market: Market type ('spot' or 'futures')
        filter_config: Filter configuration dictionary
        filter_name: Filter name for logging
    
    Returns:
        Trigger data dict if triggered, None otherwise.
        
        Example return:
        {
            'price_change_percent': 7.3,
            'price_from': 142.50,
            'price_to': 152.90,
            'volume_period': 245000,
            'volume_24h': 1200000,
            'url': 'https://www.bybit.com/trade/spot/SOL/USDT'
        }
    
    Raises:
        ValueError: If filter_config is invalid
    
    Note:
        This function calculates MAX price change, not just first-to-last!
    """
    pass
```

**Для модулей:**
```python
"""
Exchange integration module.

This module handles all interactions with Bybit exchange via CCXT library.
Includes functions for fetching tickers and candles for both spot and futures markets.

Critical Requirements:
- MUST set exchange.options['defaultType'] before requests
- MUST exclude last (current) candle from results
- MUST use quoteVolume (USD) not baseVolume
"""
```

---

## 2. Error Handling

### 2.1 Always Use Try-Except

**MUST handle exceptions gracefully:**

```python
# ✅ ПРАВИЛЬНО
async def fetch_tickers():
    try:
        tickers = await exchange.fetch_tickers()
        return tickers
    except ccxt.NetworkError as e:
        logger.error(f"Network error: {e}")
        raise
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error: {e}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {}

# ❌ НЕПРАВИЛЬНО
async def fetch_tickers():
    tickers = await exchange.fetch_tickers()
    return tickers
```

### 2.2 Specific Exceptions

**MUST catch specific exceptions first:**

```python
try:
    result = await dangerous_operation()
except ValueError as e:
    logger.warning(f"Invalid value: {e}")
    return None
except KeyError as e:
    logger.error(f"Missing key: {e}")
    return None
except Exception as e:
    logger.error(f"Unexpected: {e}", exc_info=True)
    raise
```

### 2.3 Don't Swallow Errors

**MUST log before returning/raising:**

```python
# ✅ ПРАВИЛЬНО
except NetworkError as e:
    logger.error(f"Network error fetching {symbol}: {e}")
    return None

# ❌ НЕПРАВИЛЬНО
except NetworkError:
    return None
```

---

## 3. Logging

### 3.1 Log Levels

**Use appropriate log levels:**

- `DEBUG`: Детальная информация для отладки
- `INFO`: Важные события (старт, финиш, срабатывания)
- `WARNING`: Проблемы не критичные (пропущенные данные)
- `ERROR`: Ошибки (exceptions, недоступность API)

```python
logger.debug(f"Checking {symbol}: got {len(candles)} candles")
logger.info(f"✅ Trigger: {filter_name} - {symbol}")
logger.warning(f"⚠️ Insufficient data for {symbol}")
logger.error(f"❌ Failed to fetch {symbol}: {e}", exc_info=True)
```

### 3.2 Structured Logging

**MUST include context:**

```python
# ✅ ПРАВИЛЬНО
logger.info(
    f"[{filter_name}] {symbol} ({market}): "
    f"Change {change:.2f}% (need {threshold}%)"
)

# ❌ НЕПРАВИЛЬНО
logger.info("Check failed")
```

### 3.3 Emoji for Visibility

**Use emoji for quick scanning:**

```python
logger.info(f"✅ Success: {message}")
logger.warning(f"⚠️ Warning: {message}")
logger.error(f"❌ Error: {message}")
logger.debug(f"🔍 Debug: {message}")
```

---

## 4. Validation

### 4.1 Input Validation

**MUST validate all inputs:**

```python
def validate_candle_timestamp(timestamp: int, symbol: str = None) -> bool:
    """Validate candle timestamp"""
    
    # Type check
    if not isinstance(timestamp, int):
        logger.warning(f"{symbol}: Timestamp not int: {type(timestamp)}")
        return False
    
    # Range check
    now = int(time.time())
    if timestamp > now + 60:
        logger.warning(f"{symbol}: Timestamp in future")
        return False
    
    if timestamp < now - (3 * 3600):
        logger.debug(f"{symbol}: Timestamp too old")
        return False
    
    # Format check
    if timestamp % 60 != 0:
        logger.warning(f"{symbol}: Not rounded to minute")
        return False
    
    return True
```

### 4.2 Null/None Checks

**MUST check for None/null values:**

```python
# ✅ ПРАВИЛЬНО
volume = ticker.get('quoteVolume')
if volume is None or volume < 0:
    logger.debug(f"{symbol}: Invalid volume: {volume}")
    volume = 0

# ❌ НЕПРАВИЛЬНО
volume = ticker['quoteVolume']
```

### 4.3 Edge Cases

**MUST handle edge cases:**

```python
# Division by zero
if average_volume == 0:
    logger.debug(f"{symbol}: Average volume is zero, skipping")
    return None

coefficient = current_volume / average_volume

# Empty lists
if not candles or len(candles) < 2:
    logger.debug(f"{symbol}: Insufficient candles")
    return None

# NaN/Infinity
import math
if math.isnan(price) or math.isinf(price):
    logger.warning(f"{symbol}: Invalid price: {price}")
    return None
```

---

## 5. Async/Await Best Practices

### 5.1 Always Await Async Functions

```python
# ✅ ПРАВИЛЬНО
result = await async_function()

# ❌ НЕПРАВИЛЬНО
result = async_function()  # Вернёт coroutine!
```

### 5.2 Use asyncio.gather for Parallel

```python
# Параллельное выполнение
tasks = [fetch_candles(symbol) for symbol in symbols]
results = await asyncio.gather(*tasks, return_exceptions=True)

# Обработка результатов
for symbol, result in zip(symbols, results):
    if isinstance(result, Exception):
        logger.error(f"{symbol}: Error - {result}")
        continue
    # Process result
```

### 5.3 Don't Block Event Loop

```python
# ❌ НЕПРАВИЛЬНО - блокирует event loop
time.sleep(10)

# ✅ ПРАВИЛЬНО
await asyncio.sleep(10)
```

---

## 6. Database Operations

### 6.1 Parameterized Queries

**MUST use parameterized queries (SQL injection prevention):**

```python
# ✅ ПРАВИЛЬНО
cursor = await db.execute(
    "SELECT * FROM candles WHERE symbol = ? AND market = ?",
    (symbol, market)
)

# ❌ НЕПРАВИЛЬНО - SQL injection!
cursor = await db.execute(
    f"SELECT * FROM candles WHERE symbol = '{symbol}'"
)
```

### 6.2 Transaction Handling

```python
async def save_multiple_candles(candles: list):
    async with db.transaction():
        for candle in candles:
            await db.execute(
                "INSERT INTO candles (...) VALUES (?, ?, ...)",
                candle
            )
```

### 6.3 Close Cursors

```python
# ✅ ПРАВИЛЬНО
async with db.execute(query, params) as cursor:
    rows = await cursor.fetchall()

# Или
cursor = await db.execute(query, params)
try:
    rows = await cursor.fetchall()
finally:
    await cursor.close()
```

---

## 7. Performance

### 7.1 Batch Operations

```python
# ✅ ПРАВИЛЬНО - batch insert
async def save_candles_batch(candles: list):
    query = "INSERT INTO candles (...) VALUES (?, ?, ...)"
    await db.executemany(query, candles)

# ❌ НЕПРАВИЛЬНО - one by one
for candle in candles:
    await db.execute(query, candle)
```

### 7.2 Limit Concurrent Requests

```python
# ✅ ПРАВИЛЬНО - limit concurrency
semaphore = asyncio.Semaphore(10)

async def fetch_with_limit(symbol):
    async with semaphore:
        return await fetch_candles(symbol)

tasks = [fetch_with_limit(s) for s in symbols]
results = await asyncio.gather(*tasks)

# ❌ НЕПРАВИЛЬНО - unlimited concurrency
tasks = [fetch_candles(s) for s in symbols]
results = await asyncio.gather(*tasks)
```

---

## 8. Code Organization

### 8.1 Function Length

**SHOULD be < 50 lines:**

```python
# ✅ ПРАВИЛЬНО - разбито на функции
async def _parse_market_data():
    await _parse_spot_market()
    await _parse_futures_market()

async def _parse_spot_market():
    # 20-30 lines
    pass

# ❌ НЕПРАВИЛЬНО - одна функция 200 строк
async def _parse_market_data():
    # 200 lines of code
    pass
```

### 8.2 Single Responsibility

**Each function should do ONE thing:**

```python
# ✅ ПРАВИЛЬНО
async def fetch_tickers():
    """Only fetch tickers"""
    return await exchange.fetch_tickers()

async def save_tickers(tickers):
    """Only save tickers"""
    for symbol, ticker in tickers.items():
        await db.save_ticker(symbol, ticker)

# ❌ НЕПРАВИЛЬНО
async def fetch_and_save_tickers():
    """Does two things"""
    tickers = await exchange.fetch_tickers()
    for symbol, ticker in tickers.items():
        await db.save_ticker(symbol, ticker)
```

### 8.3 DRY (Don't Repeat Yourself)

```python
# ✅ ПРАВИЛЬНО - переиспользуемая функция
def is_excluded(symbol: str, exclude_list: list) -> bool:
    normalized = symbol.replace('/', '').replace(':', '')
    return any(
        normalized.upper() == exc.replace('/', '').replace(':', '').upper()
        for exc in exclude_list
    )

# Используется в обоих фильтрах
if is_excluded(symbol, filter_config['exclude_coins']):
    return None

# ❌ НЕПРАВИЛЬНО - дублирование кода
# В каждом фильтре копипаста одного и того же кода
```

---

## 9. Constants

### 9.1 Use Constants for Magic Numbers

```python
# ✅ ПРАВИЛЬНО
CANDLES_RETENTION_HOURS = 2
TRIGGERS_RETENTION_DAYS = 30
MAX_CONCURRENT_REQUESTS = 10
RETRY_MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5.0

await cleanup_old_candles(hours=CANDLES_RETENTION_HOURS)

# ❌ НЕПРАВИЛЬНО
await cleanup_old_candles(hours=2)
```

### 9.2 Use Enums for Types

```python
from enum import Enum

class MarketType(str, Enum):
    SPOT = "spot"
    FUTURES = "futures"

class FilterType(str, Enum):
    PRICE_CHANGE = "price_change"
    VOLUME_SPIKE = "volume_spike"

# Usage
if market == MarketType.SPOT:
    # ...
```

---

## 10. Comments

### 10.1 When to Comment

**DO comment:**
- Complex algorithms
- Критические требования
- Why, not what
- Временные workarounds (с TODO)

```python
# ✅ ПРАВИЛЬНО
# CRITICAL: Exclude current period from average calculation
# to avoid self-correlation. See CRITICAL_IMPLEMENTATION_DETAILS.md section 3.4
historical_candles = candles[:-short_period]

# TODO: Add rate limiting after 100 requests/minute
# See issue #123

# ❌ НЕПРАВИЛЬНО
# Increment i
i += 1
```

### 10.2 TODO Comments

```python
# TODO(username): Description of what needs to be done
# TODO: Add support for multiple Telegram chats
# FIXME: This fails when volume is exactly 0
# HACK: Temporary workaround for CCXT bug
```

---

## 11. Testing Code

### 11.1 Test Data

```python
# Create test data functions
def create_test_candles(count: int = 120) -> list:
    """Generate test candles for unit tests"""
    candles = []
    base_price = 90000
    base_time = int(time.time()) - (count * 60)
    
    for i in range(count):
        candles.append({
            'timestamp': base_time + (i * 60),
            'open': base_price + (i * 10),
            'close': base_price + (i * 10) + 5,
            'volume': 100000 + (i * 1000)
        })
    
    return candles
```

### 11.2 Assertions

```python
# Use assertions for invariants
assert len(candles) > 0, "Candles list cannot be empty"
assert timestamp % 60 == 0, f"Timestamp not rounded: {timestamp}"
assert market in ['spot', 'futures'], f"Invalid market: {market}"
```

---

## 12. Naming Conventions

### 12.1 Variables

```python
# snake_case для переменных
filter_config = {}
price_change_percent = 5.0
is_excluded = False

# UPPER_CASE для констант
MAX_RETRIES = 3
DEFAULT_INTERVAL = 60
```

### 12.2 Functions

```python
# snake_case, глаголы
def get_candles()
def save_ticker()
def check_filter()
def calculate_average()

# is_/has_ для boolean
def is_excluded()
def has_sufficient_data()
def is_candle_closed()
```

### 12.3 Classes

```python
# PascalCase для классов
class ConnectionManager
class FilterResponse
class Settings
```

---

## 13. Security

### 13.1 Never Log Secrets

```python
# ❌ НЕПРАВИЛЬНО
logger.info(f"Using token: {settings.telegram_bot_token}")

# ✅ ПРАВИЛЬНО
logger.info("Telegram bot initialized")
```

### 13.2 Validate External Input

```python
# Все данные от пользователя/API должны валидироваться
def validate_filter_config(config: dict) -> bool:
    required_fields = ['market', 'interval_minutes', 'min_price_change_percent']
    
    for field in required_fields:
        if field not in config:
            raise ValueError(f"Missing required field: {field}")
    
    if config['market'] not in ['spot', 'futures']:
        raise ValueError(f"Invalid market: {config['market']}")
    
    return True
```

---

## 14. Example: Perfect Function

```python
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Constants
MIN_CANDLES_REQUIRED = 2
EXCLUDE_CURRENT_PERIOD = True

async def check_price_change_filter(
    symbol: str,
    market: str,
    filter_config: Dict[str, any],
    filter_name: str
) -> Optional[Dict[str, any]]:
    """
    Check if price change filter triggers for symbol.
    
    This function implements the "Price Change" filter logic:
    1. Get candles for the specified interval
    2. Calculate MAX price change (not just first-to-last)
    3. Check all filter conditions
    4. Return trigger data if all conditions met
    
    Args:
        symbol: Trading pair (e.g. 'BTC/USDT')
        market: Market type ('spot' or 'futures')
        filter_config: Filter configuration with keys:
            - interval_minutes: Period to check (int)
            - min_price_change_percent: Threshold (float)
            - direction: 'up', 'down', or 'any'
            - min_volume_period: Minimum volume in USD (float)
            - min_volume_24h: Minimum 24h volume (float)
            - exclude_coins: List of symbols to exclude
        filter_name: Filter name for logging
    
    Returns:
        Trigger data dict if triggered, None otherwise
    
    Raises:
        ValueError: If filter_config is invalid
    
    Example:
        >>> config = {
        ...     'interval_minutes': 15,
        ...     'min_price_change_percent': 5.0,
        ...     'direction': 'up',
        ...     'min_volume_period': 10000,
        ...     'min_volume_24h': 100000,
        ...     'exclude_coins': ['BTCUSDT']
        ... }
        >>> result = await check_price_change_filter(
        ...     'SOL/USDT', 'spot', config, 'Test Filter'
        ... )
    """
    
    # Step 1: Get candles
    try:
        candles = await get_candles(
            symbol=symbol,
            market=market,
            minutes=filter_config['interval_minutes']
        )
    except Exception as e:
        logger.error(
            f"[{filter_name}] {symbol} ({market}): "
            f"Error getting candles: {e}"
        )
        return None
    
    # Step 2: Validate data
    if not candles or len(candles) < MIN_CANDLES_REQUIRED:
        logger.debug(
            f"[{filter_name}] {symbol} ({market}): "
            f"Insufficient candles (got {len(candles)}, need {MIN_CANDLES_REQUIRED})"
        )
        return None
    
    # Step 3: Calculate price change
    direction = filter_config['direction']
    max_change, price_from, price_to = calculate_max_price_change(
        candles, direction
    )
    
    logger.debug(
        f"[{filter_name}] {symbol} ({market}): "
        f"Max change = {max_change:+.2f}% "
        f"(${price_from:.2f} → ${price_to:.2f})"
    )
    
    # Step 4: Check threshold
    threshold = filter_config['min_price_change_percent']
    if abs(max_change) < threshold:
        logger.debug(
            f"[{filter_name}] {symbol} ({market}): "
            f"❌ Change too small ({max_change:.2f}% < {threshold}%)"
        )
        return None
    
    # Step 5: Check volume
    volume_period = sum(candle['volume'] for candle in candles)
    min_volume = filter_config['min_volume_period']
    
    if volume_period < min_volume:
        logger.debug(
            f"[{filter_name}] {symbol} ({market}): "
            f"❌ Volume too low (${volume_period:,.0f} < ${min_volume:,.0f})"
        )
        return None
    
    # Step 6: Check 24h volume
    ticker = await get_ticker(symbol, market)
    if not ticker:
        logger.warning(
            f"[{filter_name}] {symbol} ({market}): "
            f"⚠️ Ticker not found"
        )
        return None
    
    volume_24h = ticker['volume_24h']
    if volume_24h < filter_config['min_volume_24h']:
        logger.debug(
            f"[{filter_name}] {symbol} ({market}): "
            f"❌ 24h volume too low (${volume_24h:,.0f})"
        )
        return None
    
    # Step 7: Check exclusions
    if is_excluded(symbol, filter_config.get('exclude_coins', [])):
        logger.debug(
            f"[{filter_name}] {symbol} ({market}): "
            f"⏭️ Excluded by filter"
        )
        return None
    
    # Step 8: All checks passed - TRIGGERED!
    logger.info(
        f"[{filter_name}] {symbol} ({market}): "
        f"✅ TRIGGERED! Change: {max_change:+.2f}%"
    )
    
    # Build URL
    if market == 'spot':
        pair = symbol.replace('/', '/')
        url = f"https://www.bybit.com/trade/spot/{pair}"
    else:
        pair = symbol.replace('/USDT:USDT', 'USDT')
        url = f"https://www.bybit.com/trade/usdt/{pair}"
    
    return {
        'price_change_percent': max_change,
        'price_from': price_from,
        'price_to': price_to,
        'volume_period': volume_period,
        'volume_24h': volume_24h,
        'url': url
    }
```

---

**Дата:** 2026-01-12  
**Статус:** Apply these standards to all generated code
