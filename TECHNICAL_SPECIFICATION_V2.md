# Техническое задание v2.0: Криптоскринер Bybit

**Дата:** 2026-01-12  
**Версия:** 2.0  
**Цель:** Полная спецификация для генерации кода системы мониторинга криптовалют

---

## 📋 Оглавление

1. [Обзор системы](#1-обзор-системы)
2. [Архитектура](#2-архитектура)
3. [Критические требования](#3-критические-требования)
4. [База данных](#4-база-данных)
5. [Backend: Exchange Integration](#5-backend-exchange-integration)
6. [Backend: Screener Engine](#6-backend-screener-engine)
7. [Backend: API](#7-backend-api)
8. [Backend: WebSocket](#8-backend-websocket)
9. [Frontend](#9-frontend)
10. [Docker & Deployment](#10-docker--deployment)
11. [Acceptance Criteria](#11-acceptance-criteria)

---

## 1. Обзор системы

### 1.1 Цель проекта

Создать систему автоматического мониторинга криптовалютных инструментов на бирже Bybit с возможностью настройки пользовательских фильтров и получения уведомлений в Telegram при срабатывании условий.

### 1.2 Ключевые возможности

- ✅ Мониторинг **спот** и **фьючерсных** рынков Bybit (раздельно)
- ✅ Два типа фильтров:
  - **"Изменение цены"** - резкий рост/падение за период
  - **"Всплеск объёмов"** - необычный рост объёмов
- ✅ Веб-интерфейс для управления фильтрами
- ✅ Real-time уведомления через WebSocket
- ✅ Telegram бот для push-уведомлений
- ✅ История и статистика срабатываний
- ✅ Cooldown система (предотвращение спама)
- ✅ Docker-based deployment

### 1.3 Технологический стек

**Backend:**
- Python 3.11+
- FastAPI (async web framework)
- CCXT (exchange API integration)
- aiosqlite (async SQLite driver)
- python-telegram-bot (Telegram notifications)
- uvicorn (ASGI server)

**Frontend:**
- HTML5 + Vanilla JavaScript
- Tailwind CSS
- WebSocket для real-time
- Nginx для статики

**Infrastructure:**
- Docker + Docker Compose
- SQLite database (в volume)
- Nginx reverse proxy

### 1.4 Ограничения и допущения

- **Один пользователь** (персональное использование)
- **Один экземпляр** (single instance deployment)
- **Один Telegram чат** для уведомлений
- **Только Bybit** (другие биржи не поддерживаются)
- **Только USDT пары** (BTC/USDT, ETH/USDT, etc)
- **Данные в памяти** за последние 2 часа (свечи)

---

## 2. Архитектура

### 2.1 Диаграмма компонентов

```
┌─────────────────────────────────────────────────────────────┐
│                         Пользователь                          │
└──────────────┬────────────────────────────────┬───────────────┘
               │                                │
       HTTP/WebSocket                      Telegram Bot
               │                                │
┌──────────────▼────────────────────────────────▼───────────────┐
│                     Nginx (Порт 3000)                          │
│  - Static files (Frontend)                                     │
│  - Reverse proxy для API                                       │
│  - WebSocket proxy                                             │
└──────────────┬────────────────────────────────────────────────┘
               │
┌──────────────▼────────────────────────────────────────────────┐
│                 FastAPI Backend (Порт 8000)                    │
│                                                                │
│  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────┐ │
│  │   REST API      │  │   WebSocket      │  │   Screener   │ │
│  │  /api/*         │  │   /ws/triggers   │  │   Engine     │ │
│  └─────────────────┘  └──────────────────┘  └──────────────┘ │
│                                                                │
└──────────────┬────────────────────────────────┬───────────────┘
               │                                │
       ┌───────▼────────┐              ┌────────▼──────────┐
       │ SQLite Database│              │   Bybit API       │
       │  /data/*.db    │              │   (via CCXT)      │
       └────────────────┘              └───────────────────┘
                                                │
                                       ┌────────▼──────────┐
                                       │  Telegram API     │
                                       └───────────────────┘
```

### 2.2 Поток данных

**Цикл парсинга (каждые 5 минут):**
```
1. Bybit API → CCXT → Backend
2. Backend → Валидация → SQLite (tickers, candles)
3. Backend → Очистка старых данных (>2 часа)
```

**Цикл проверки (сразу после парсинга):**
```
1. SQLite → Backend (получить активные фильтры)
2. Backend → Проверка каждого фильтра
3. Backend → Cooldown проверка
4. Backend → SQLite (сохранить срабатывание)
5. Backend → Telegram API (отправить уведомление)
6. Backend → WebSocket (broadcast клиентам)
```

**Real-time обновления:**
```
Frontend → WebSocket connection → Backend
Backend → Срабатывание фильтра → WebSocket broadcast
Frontend → Получение → Отображение + Звук
```

### 2.3 Модульная структура кода

```
backend/
├── main.py                   # Точка входа FastAPI
├── config.py                 # Конфигурация (Settings)
│
├── api/                      # REST API модуль
│   ├── __init__.py
│   ├── filters.py            # CRUD для фильтров
│   ├── triggers.py           # История срабатываний
│   ├── settings.py           # Настройки системы
│   └── websocket.py          # WebSocket endpoint
│
├── screener/                 # Движок скринера
│   ├── __init__.py
│   ├── engine.py             # Главный цикл (парсинг + проверка)
│   ├── database.py           # Работа с SQLite
│   ├── exchange.py           # CCXT интеграция (Bybit)
│   ├── filters.py            # Логика проверки фильтров
│   ├── notifications.py      # Telegram уведомления
│   └── time_utils.py         # Работа со временем
│
├── models/                   # Pydantic модели
│   ├── __init__.py
│   ├── filter.py             # FilterCreate, FilterResponse
│   ├── trigger.py            # TriggerResponse
│   └── settings.py           # SettingsModel
│
└── utils/                    # Утилиты
    ├── __init__.py
    ├── validation.py         # Валидация данных
    └── logging_config.py     # Настройка логирования
```

---

## 3. Критические требования

### 3.1 Работа со временем

**КРИТИЧНО:** Неправильная работа со временем - основная причина багов!

#### 3.1.1 Unix timestamps (секунды, не миллисекунды)

```python
# ✅ ПРАВИЛЬНО
timestamp_ms = candle[0]  # CCXT возвращает миллисекунды
timestamp_sec = int(timestamp_ms / 1000)  # Конвертация в секунды

# ❌ НЕПРАВИЛЬНО
timestamp = int(candle[0])  # 1736614800000 - переполнение!
```

**Acceptance Criteria:**
- Все timestamps в БД MUST быть в секундах (10 цифр)
- Все timestamps MUST быть округлены до минуты: `(ts // 60) * 60`
- Все datetime операции MUST использовать UTC timezone

#### 3.1.2 Только закрытые свечи

```python
# ✅ ПРАВИЛЬНО
candles = await exchange.fetch_ohlcv(symbol, '1m', limit=121)
closed_candles = candles[:-1]  # Исключить последнюю (текущую)

# ❌ НЕПРАВИЛЬНО
candles = await exchange.fetch_ohlcv(symbol, '1m', limit=120)
# Последняя свеча ещё не закрыта - данные меняются!
```

**Acceptance Criteria:**
- MUST исключать последнюю свечу из `fetch_ohlcv` результата
- MUST использовать `get_last_closed_candle_timestamp()` для определения окна
- Последняя закрытая свеча = current_minute_start - 60 секунд

#### 3.1.3 Функция получения последней закрытой свечи

```python
def get_last_closed_candle_timestamp() -> int:
    """
    Получить timestamp последней гарантированно закрытой 1m свечи
    
    Логика:
    - Свеча 11:32:00 закрывается в 11:33:00
    - Берём предыдущую минуту для безопасности
    
    Returns:
        Unix timestamp (секунды) начала последней закрытой минуты
    """
    now = int(time.time())
    current_minute_start = (now // 60) * 60
    last_closed = current_minute_start - 60  # Всегда -60!
    return last_closed
```

**Acceptance Criteria:**
- MUST ALWAYS возвращать `current_minute - 60 seconds`
- NEVER использовать логику "если прошло < 10 сек"
- MUST возвращать timestamp округлённый до минуты

#### 3.1.4 Валидация timestamps

```python
def validate_candle_timestamp(timestamp: int, symbol: str = None) -> bool:
    """Проверка корректности timestamp"""
    now = int(time.time())
    
    # 1. Не в будущем (+ 60 сек допустимо)
    if timestamp > now + 60:
        logger.warning(f"{symbol}: Timestamp in future!")
        return False
    
    # 2. Не слишком старый (> 3 часов)
    if timestamp < now - (3 * 3600):
        return False
    
    # 3. Округлён до минуты
    if timestamp % 60 != 0:
        logger.warning(f"{symbol}: Not rounded to minute")
        return False
    
    return True
```

**Acceptance Criteria:**
- MUST проверять каждый timestamp перед сохранением
- MUST логировать невалидные timestamps
- MUST пропускать невалидные данные (не падать)

### 3.2 Разделение Spot и Futures рынков

**КРИТИЧНО:** Спот и фьючерсы - это РАЗНЫЕ рынки!

#### 3.2.1 Разные символы

```
Спот:       BTC/USDT        (без :USDT)
Фьючерсы:   BTC/USDT:USDT   (с :USDT)
```

**Acceptance Criteria:**
- Спот тикеры MUST иметь формат: `BASE/USDT` без `:`
- Futures тикеры MUST иметь формат: `BASE/USDT:USDT`
- NEVER смешивать данные из разных рынков

#### 3.2.2 Раздельный парсинг

```python
# ✅ ПРАВИЛЬНО - две отдельные функции
async def fetch_spot_tickers():
    exchange.options['defaultType'] = 'spot'
    tickers = await exchange.fetch_tickers()
    return {k: v for k, v in tickers.items() 
            if '/USDT' in k and ':' not in k}

async def fetch_futures_tickers():
    exchange.options['defaultType'] = 'linear'
    tickers = await exchange.fetch_tickers()
    return {k: v for k, v in tickers.items() 
            if k.endswith('/USDT:USDT')}
```

**Acceptance Criteria:**
- MUST иметь отдельные функции для спот/фьючерсов
- MUST устанавливать `exchange.options['defaultType']` перед запросом
- MUST фильтровать только USDT пары
- Спот: только Linear (USDT-margined) фьючерсы

#### 3.2.3 Сохранение с указанием рынка

```sql
-- ✅ ПРАВИЛЬНО
INSERT INTO candles (symbol, market, timestamp, ...)
VALUES ('BTC/USDT', 'spot', 1736614800, ...);

INSERT INTO candles (symbol, market, timestamp, ...)
VALUES ('BTC/USDT:USDT', 'futures', 1736614800, ...);

-- PRIMARY KEY (symbol, market, timestamp)
```

**Acceptance Criteria:**
- EVERY DB операция MUST включать `market` параметр
- SQL WHERE clauses MUST фильтровать по `symbol AND market`
- Cooldown MUST проверяться по (filter_id, symbol, market)

### 3.3 Использование quoteVolume (USD)

**КРИТИЧНО:** Для корректного сравнения объёмов!

```python
# ✅ ПРАВИЛЬНО
volume_24h = ticker.get('quoteVolume', 0)  # В USD

# ❌ НЕПРАВИЛЬНО
volume_24h = ticker.get('volume', 0)  # В базовой валюте (BTC, ETH, etc)
```

**Проблема baseVolume:**
```
BTC/USDT: volume = 0.5 BTC = ? USD (зависит от цены)
SOL/USDT: volume = 100 SOL = ? USD (зависит от цены)
→ Нельзя сравнивать напрямую!

quoteVolume:
BTC/USDT: quoteVolume = $45,000 USDT ✅
SOL/USDT: quoteVolume = $13,500 USDT ✅
→ Можно сравнивать!
```

**Acceptance Criteria:**
- ALWAYS use `ticker.get('quoteVolume')` for 24h volume
- For candles: use `candle[6]` (quoteVolume) if available
- If quoteVolume unavailable: calculate as `baseVolume * close`
- NEVER compare baseVolume between different symbols

### 3.4 Алгоритм всплеска объёмов

**КРИТИЧНО:** Текущий период MUST быть исключён из среднего!

```python
# ❌ НЕПРАВИЛЬНО - текущий период включён
candles = get_candles(120)  # Все 120 минут
total = sum(all 120 candles)
avg = total / 12
current = sum(last 10 candles)
coefficient = current / avg  # НЕПРАВИЛЬНО!

# ✅ ПРАВИЛЬНО - текущий период исключён
candles = get_candles(120)
historical_candles = candles[:-10]  # Исключить последние 10 минут
recent_candles = candles[-10:]

total_historical = sum(historical_candles)
avg = total_historical / 11  # 110 минут / 10 = 11 периодов
current = sum(recent_candles)
coefficient = current / avg  # ПРАВИЛЬНО!
```

**Математика:**
```
Короткий период: 10 минут
Базовый период: 120 минут

Исторические данные: 120 - 10 = 110 минут
Количество интервалов: 110 / 10 = 11

Средний объём = Sum(first 110 minutes) / 11
Текущий объём = Sum(last 10 minutes)
Коэффициент = Текущий / Средний
```

**Acceptance Criteria:**
- MUST exclude current period from average calculation
- Number of intervals = (base_period - short_period) / short_period
- If average_volume == 0: return None (skip check)
- MUST use quoteVolume for all volume calculations

### 3.5 Синхронизация парсинга и проверки

**КРИТИЧНО:** Race condition между парсингом и проверкой!

```python
# ❌ НЕПРАВИЛЬНО - параллельные циклы
async def parse_loop():
    while True:
        await _parse_market_data()  # 4-8 минут
        await asyncio.sleep(5 * 60)

async def check_loop():
    while True:
        await _check_filters()  # 1-2 секунды
        await asyncio.sleep(60)  # Каждую минуту!

# Проблема: check читает частично обновлённые данные

# ✅ ПРАВИЛЬНО - последовательное выполнение
async def main_loop():
    while running:
        # 1. Парсинг (4-8 минут)
        await _parse_market_data()
        
        # 2. Пауза для завершения записи (5 секунд)
        await asyncio.sleep(5)
        
        # 3. Проверка фильтров (1-2 секунды)
        await _check_filters()
        
        # 4. Сон до следующего цикла (5 минут)
        await asyncio.sleep(5 * 60)
```

**Acceptance Criteria:**
- MUST run parsing and checking SEQUENTIALLY
- MUST wait 5 seconds after parsing before checking
- Check interval = parse interval (оба 5 минут)
- NEVER run parse and check in parallel

### 3.6 Retry механизм для сетевых ошибок

**КРИТИЧНО:** VPN может падать, API может таймаутить!

```python
@retry_on_network_error(max_attempts=3, delay_seconds=5.0)
async def fetch_tickers_from_exchange(market: str):
    """Retry decorator применяется автоматически"""
    exchange.options['defaultType'] = market
    tickers = await exchange.fetch_tickers()
    return tickers
```

**Acceptance Criteria:**
- MUST retry on `ccxt.NetworkError` (3 attempts)
- MUST use exponential backoff (5s → 10s → 20s)
- MUST NOT retry on `ccxt.ExchangeError` (rate limit, bad request)
- MUST log each retry attempt
- MUST log hint about VPN after failures

### 3.7 Детальное логирование

**КРИТИЧНО:** Без логов невозможно дебажить!

```python
# Каждая проверка фильтра
logger.debug(f"[{filter_name}] {symbol} ({market}): Got {len(candles)} candles")
logger.debug(f"[{filter_name}] {symbol}: Change = {change:.2f}% (need {min}%)")

# При срабатывании
logger.info(f"[{filter_name}] {symbol}: ✅ TRIGGERED! Change: {change:+.2f}%")

# При отказе
logger.debug(f"[{filter_name}] {symbol}: ❌ Change too small ({change:.2f}% < {min}%)")
```

**Log levels:**
- `DEBUG`: Каждая проверка, промежуточные вычисления
- `INFO`: Срабатывания, начало/конец циклов, важные события
- `WARNING`: Проблемы не критичные (мало данных, пропущенный символ)
- `ERROR`: Критичные ошибки (exception, недоступность API)

**Acceptance Criteria:**
- MUST log EVERY filter check at DEBUG level
- MUST log reason for not triggering
- MUST log all API errors with hints
- MUST log parsing statistics (X/Y symbols succeeded)
- MUST use structured logging format

---

## 4. База данных

### 4.1 Схема БД (SQLite)

#### Таблица: candles

```sql
CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,              -- 'BTC/USDT' или 'BTC/USDT:USDT'
    market TEXT NOT NULL,               -- 'spot' или 'futures'
    timestamp INTEGER NOT NULL,         -- Unix timestamp (секунды, округлено до минуты)
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,               -- quoteVolume (USD)
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    UNIQUE(symbol, market, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_candles_symbol_market_time 
    ON candles(symbol, market, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_candles_timestamp 
    ON candles(timestamp);
```

**Acceptance Criteria:**
- PRIMARY KEY auto-increment
- UNIQUE constraint на (symbol, market, timestamp)
- Индексы для быстрого поиска
- `volume` MUST содержать quoteVolume (USD)
- `timestamp` MUST быть округлён до минуты

**Управление данными:**
- Хранить только свечи за последние 2 часа
- Автоматическая очистка каждые 15 минут:
  ```sql
  DELETE FROM candles WHERE timestamp < (current_timestamp - 7200);
  ```

#### Таблица: tickers

```sql
CREATE TABLE IF NOT EXISTS tickers (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    volume_24h REAL NOT NULL,           -- quoteVolume за 24ч (USD)
    last_price REAL NOT NULL,
    updated_at INTEGER DEFAULT (strftime('%s', 'now')),
    PRIMARY KEY (symbol, market)
);
```

**Acceptance Criteria:**
- Composite PRIMARY KEY на (symbol, market)
- `volume_24h` MUST быть quoteVolume from exchange
- Обновляется каждый цикл парсинга (REPLACE INTO)

#### Таблица: filters

```sql
CREATE TABLE IF NOT EXISTS filters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,                 -- 'price_change' или 'volume_spike'
    enabled INTEGER DEFAULT 1,          -- 0 = disabled, 1 = enabled
    config TEXT NOT NULL,               -- JSON configuration
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER
);
```

**Config JSON для price_change:**
```json
{
  "market": "spot",
  "interval_minutes": 15,
  "min_price_change_percent": 5.0,
  "direction": "up",
  "min_volume_period": 10000,
  "min_volume_24h": 100000,
  "max_volume_24h": null,
  "exclude_coins": ["BTCUSDT", "ETHUSDT"],
  "comment": ""
}
```

**Config JSON для volume_spike:**
```json
{
  "market": "futures",
  "short_period_minutes": 10,
  "base_period_minutes": 120,
  "spike_coefficient": 5.0,
  "price_direction": "all",
  "min_price_change_percent": 0,
  "min_volume_24h": 1000000,
  "max_volume_24h": null,
  "exclude_coins": [],
  "comment": ""
}
```

**Acceptance Criteria:**
- Config MUST be valid JSON
- MUST validate config on INSERT/UPDATE
- `enabled` controls if filter is checked

#### Таблица: filter_triggers

```sql
CREATE TABLE IF NOT EXISTS filter_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filter_id INTEGER NOT NULL,
    filter_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    triggered_at INTEGER DEFAULT (strftime('%s', 'now')),
    data TEXT NOT NULL,                 -- JSON trigger details
    notified INTEGER DEFAULT 0,         -- 0 = not sent, 1 = sent to Telegram
    FOREIGN KEY (filter_id) REFERENCES filters(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_triggers_filter_symbol_time 
    ON filter_triggers(filter_id, symbol, market, triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_triggers_time 
    ON filter_triggers(triggered_at DESC);
```

**Data JSON example:**
```json
{
  "price_change_percent": 7.3,
  "price_from": 142.50,
  "price_to": 152.90,
  "volume_period": 245000,
  "volume_24h": 1200000,
  "url": "https://www.bybit.com/trade/spot/SOL/USDT"
}
```

**Acceptance Criteria:**
- FOREIGN KEY constraint on filter_id
- Index for cooldown checks (filter_id, symbol, market, triggered_at)
- Index for history queries (triggered_at DESC)
- Auto-cleanup: удалять записи старше 30 дней

### 4.2 Оптимизации SQLite

```python
async def init_database():
    """Инициализация БД с оптимизациями"""
    
    # WAL mode - позволяет одновременное чтение/запись
    await db.execute('PRAGMA journal_mode=WAL')
    
    # Cache size (64 MB)
    await db.execute('PRAGMA cache_size=-64000')
    
    # Temp in memory
    await db.execute('PRAGMA temp_store=MEMORY')
    
    # Sync mode для баланса безопасность/скорость
    await db.execute('PRAGMA synchronous=NORMAL')
    
    # Автовакуум
    await db.execute('PRAGMA auto_vacuum=INCREMENTAL')
    
    # Busy timeout для конкурентности
    await db.execute('PRAGMA busy_timeout=5000')
```

**Acceptance Criteria:**
- MUST apply all PRAGMA settings on init
- MUST run ANALYZE after schema creation
- SHOULD run VACUUM once a day (at 3:00 AM)

---

## 5. Backend: Exchange Integration

### 5.1 Модуль: exchange.py

**Purpose:** Взаимодействие с Bybit через CCXT

#### Function: init_exchange()

```python
async def init_exchange() -> ccxt.bybit:
    """
    Инициализация CCXT exchange объекта
    
    Returns:
        ccxt.bybit: Настроенный exchange объект
    
    Acceptance Criteria:
    - MUST use ccxt.async_support
    - MUST enable rate limiting
    - MUST set timeout to 30 seconds
    - SHOULD log exchange info (version, limits)
    """
    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'timeout': 30000,  # 30 секунд
    })
    
    logger.info(f"Exchange initialized: Bybit v{exchange.version}")
    return exchange
```

#### Function: fetch_spot_tickers()

```python
async def fetch_spot_tickers() -> dict:
    """
    Получить все спотовые тикеры
    
    Returns:
        dict: {'BTC/USDT': ticker_data, ...}
    
    Acceptance Criteria:
    - MUST set exchange.options['defaultType'] = 'spot'
    - MUST filter only '/USDT' pairs WITHOUT ':'
    - MUST validate ticker.last > 0
    - MUST use ticker.quoteVolume
    - MUST log "Got X SPOT tickers"
    - MUST handle exceptions (NetworkError, ExchangeError)
    - SHOULD complete in < 10 seconds
    
    Example Output:
    {
      'BTC/USDT': {
        'symbol': 'BTC/USDT',
        'last': 90827.89,
        'quoteVolume': 5000000000.0,
        ...
      },
      ...
    }
    """
```

#### Function: fetch_futures_tickers()

```python
async def fetch_futures_tickers() -> dict:
    """
    Получить фьючерсные тикеры (Linear USDT-margined)
    
    Returns:
        dict: {'BTC/USDT:USDT': ticker_data, ...}
    
    Acceptance Criteria:
    - MUST set exchange.options['defaultType'] = 'linear'
    - MUST filter only '/USDT:USDT' pairs
    - ONLY Linear (USDT-margined) futures
    - MUST validate ticker.last > 0
    - MUST use ticker.quoteVolume
    - MUST log "Got X FUTURES tickers"
    
    Example Output:
    {
      'BTC/USDT:USDT': {
        'symbol': 'BTC/USDT:USDT',
        'last': 90850.12,
        'quoteVolume': 8500000000.0,
        ...
      },
      ...
    }
    """
```

#### Function: fetch_candles()

```python
async def fetch_candles(
    symbol: str,
    market: str,
    timeframe: str = '1m',
    limit: int = 121
) -> list:
    """
    Получить свечи для символа
    
    Args:
        symbol: 'BTC/USDT' или 'BTC/USDT:USDT'
        market: 'spot' или 'futures'
        timeframe: '1m'
        limit: Количество свечей + 1 (для исключения последней)
    
    Returns:
        list: Закрытые свечи (последняя исключена)
    
    Acceptance Criteria:
    - MUST set correct defaultType for market
    - MUST fetch limit + 1 candles
    - MUST exclude last candle (current, not closed)
    - MUST convert timestamp ms → seconds
    - MUST validate timestamps
    - MUST use quoteVolume if available (candle[6])
    - MUST handle NetworkError with retry
    
    Example Output:
    [
      [1736614800, 90750.0, 90850.0, 90700.0, 90827.89, 125000.45],
      [1736614860, 90827.89, 90900.0, 90800.0, 90875.12, 98000.23],
      ...
    ]
    """
```

### 5.2 Retry декоратор

```python
def retry_on_network_error(
    max_attempts: int = 3,
    delay_seconds: float = 5.0,
    backoff_multiplier: float = 2.0
):
    """
    Декоратор для повторных попыток при сетевых ошибках
    
    Acceptance Criteria:
    - MUST retry only on ccxt.NetworkError
    - MUST NOT retry on ccxt.ExchangeError
    - MUST use exponential backoff
    - MUST log each attempt
    - MUST log "Check VPN" hint after failures
    """
```

**Example usage:**
```python
@retry_on_network_error(max_attempts=3, delay_seconds=5.0)
async def fetch_data():
    # Network request
    return data
```

---

## 6. Backend: Screener Engine

### 6.1 Модуль: engine.py

**Purpose:** Главный цикл парсинга и проверки фильтров

#### Function: start_screener()

```python
async def start_screener():
    """
    Запуск главного цикла скринера
    
    Acceptance Criteria:
    - MUST run sequentially (parse → wait → check → sleep)
    - MUST handle exceptions gracefully (continue on error)
    - MUST log cycle statistics
    - MUST respect PARSE_INTERVAL_MINUTES setting
    """
```

#### Function: _parse_market_data()

```python
async def _parse_market_data() -> dict:
    """
    Парсинг данных с биржи
    
    Returns:
        dict: Статистика парсинга
        {
          'spot': {'tickers': 523, 'candles_success': 510, 'candles_errors': 13},
          'futures': {'tickers': 586, 'candles_success': 570, 'candles_errors': 16}
        }
    
    Acceptance Criteria:
    - MUST parse spot and futures SEPARATELY
    - MUST save tickers to DB (REPLACE INTO)
    - MUST fetch candles for all symbols (batched)
    - MUST validate all timestamps
    - MUST exclude last (current) candle
    - MUST use quoteVolume
    - MUST handle errors per-symbol (continue on error)
    - MUST log detailed statistics
    - SHOULD complete in < 10 minutes
    
    Steps:
    1. Check which markets to parse (PARSE_SPOT, PARSE_FUTURES)
    2. For each market:
       a. Fetch tickers
       b. Save tickers to DB
       c. Get list of symbols
       d. Fetch candles for all symbols (batched, max 10 concurrent)
       e. Validate and save candles
    3. Return statistics
    """
```

#### Function: _check_filters()

```python
async def _check_filters() -> int:
    """
    Проверка всех активных фильтров
    
    Returns:
        int: Количество срабатываний
    
    Acceptance Criteria:
    - MUST get all enabled filters from DB
    - MUST check each filter only for its market
    - MUST skip if not enough data
    - MUST check cooldown before saving trigger
    - MUST save trigger to DB
    - MUST send Telegram notification
    - MUST broadcast via WebSocket
    - MUST log each check at DEBUG level
    - MUST handle errors per-filter (continue on error)
    
    Steps:
    1. Get active filters
    2. For each filter:
       a. Get symbols for filter's market
       b. For each symbol:
          - Check filter logic
          - If triggered:
            * Check cooldown
            * Save to DB
            * Send Telegram
            * Broadcast WebSocket
    3. Return total triggers count
    """
```

#### Function: _cleanup_old_data()

```python
async def _cleanup_old_data():
    """
    Очистка старых данных из БД
    
    Acceptance Criteria:
    - MUST run every 15 minutes
    - MUST delete candles older than 2 hours
    - MUST delete triggers older than 30 days (once per day)
    - MUST run VACUUM once per day (at 3:00 AM)
    - MUST log deletion statistics
    """
```

### 6.2 Модуль: filters.py

**Purpose:** Логика проверки фильтров

#### Function: check_price_change_filter()

```python
async def check_price_change_filter(
    symbol: str,
    market: str,
    filter_config: dict,
    filter_name: str
) -> Optional[dict]:
    """
    Проверка фильтра "Изменение цены"
    
    Args:
        symbol: 'BTC/USDT' или 'BTC/USDT:USDT'
        market: 'spot' или 'futures'
        filter_config: Конфигурация из filters.config
        filter_name: Название для логов
    
    Returns:
        dict с деталями если сработал, None если нет
        {
          'price_change_percent': 7.3,
          'price_from': 142.50,
          'price_to': 152.90,
          'volume_period': 245000,
          'volume_24h': 1200000,
          'url': 'https://www.bybit.com/trade/spot/SOL/USDT'
        }
    
    Acceptance Criteria:
    - MUST get candles for interval_minutes
    - MUST calculate max price change (not just first-to-last)
    - MUST check direction (up/down/any)
    - MUST check min_price_change_percent
    - MUST calculate volume for period
    - MUST check min_volume_period
    - MUST get ticker for volume_24h
    - MUST check min_volume_24h and max_volume_24h
    - MUST check exclude_coins
    - MUST log at DEBUG level for each check
    - MUST log reason if not triggered
    
    Algorithm:
    1. Get candles for interval_minutes
    2. If < 2 candles: return None
    3. Calculate max_change = max price change in any direction
    4. Check direction filter
    5. Check min_price_change threshold
    6. Calculate volume_period = sum of candle volumes
    7. Check min_volume_period
    8. Get ticker for volume_24h
    9. Check volume_24h range
    10. Check if symbol in exclude_coins
    11. If all checks pass: return trigger data
    """
```

**Price change algorithm:**
```python
def calculate_max_price_change(candles: list, direction: str) -> tuple:
    """
    Вычислить максимальное изменение цены
    
    NOT just first-to-last!
    Must find MAX change in the period.
    
    Example:
    [100, 105, 110, 95] → max change = 100→110 = +10%
    Not 100→95 = -5%
    
    Returns:
        (max_change_percent, price_from, price_to)
    """
    max_change = 0
    price_from = candles[0]['close']
    price_to = candles[0]['close']
    
    for i in range(len(candles)):
        for j in range(i + 1, len(candles)):
            change = (candles[j]['close'] - candles[i]['close']) / candles[i]['close'] * 100
            
            if direction == 'up' and change > max_change:
                max_change = change
                price_from = candles[i]['close']
                price_to = candles[j]['close']
            elif direction == 'down' and change < max_change:
                max_change = change
                price_from = candles[i]['close']
                price_to = candles[j]['close']
            elif direction == 'any' and abs(change) > abs(max_change):
                max_change = change
                price_from = candles[i]['close']
                price_to = candles[j]['close']
    
    return max_change, price_from, price_to
```

#### Function: check_volume_spike_filter()

```python
async def check_volume_spike_filter(
    symbol: str,
    market: str,
    filter_config: dict,
    filter_name: str
) -> Optional[dict]:
    """
    Проверка фильтра "Всплеск объёмов"
    
    Returns:
        dict с деталями если сработал, None если нет
        {
          'spike_coefficient': 6.2,
          'current_volume': 850000,
          'average_volume': 137000,
          'price_change_percent': 2.1,
          'price': 8.45,
          'volume_24h': 5300000,
          'url': 'https://www.bybit.com/trade/usdt/APTUSDT'
        }
    
    Acceptance Criteria:
    - MUST get candles for base_period_minutes
    - MUST exclude current period from average calculation
    - MUST calculate correct number of intervals
    - MUST handle average_volume == 0 (return None)
    - MUST calculate spike coefficient correctly
    - MUST check min spike_coefficient threshold
    - IF min_price_change_percent > 0:
      - MUST check price change in current period
      - MUST check price_direction
    - MUST get ticker for volume_24h
    - MUST check volume_24h range
    - MUST check exclude_coins
    - MUST log at DEBUG level
    
    Algorithm (CRITICAL - see section 3.4):
    1. Get candles for base_period_minutes
    2. Separate: historical = candles[:-short_period], current = candles[-short_period:]
    3. Calculate: num_intervals = len(historical) / short_period
    4. Calculate: average_volume = sum(historical) / num_intervals
    5. If average_volume == 0: return None
    6. Calculate: current_volume = sum(current)
    7. Calculate: coefficient = current_volume / average_volume
    8. If coefficient < spike_coefficient: return None
    9. If min_price_change > 0:
       - Calculate price change in current period
       - Check direction
    10. Check volume_24h and exclude_coins
    11. Return trigger data
    """
```

### 6.3 Модуль: time_utils.py

**Purpose:** Функции для работы со временем

```python
def get_current_timestamp() -> int:
    """Текущий Unix timestamp (UTC, секунды)"""

def get_last_closed_candle_timestamp() -> int:
    """Timestamp последней закрытой 1m свечи"""

def get_candle_window(minutes: int) -> tuple[int, int]:
    """Окно времени для свечей: (start, end)"""

def round_to_minute(timestamp: int) -> int:
    """Округлить timestamp до начала минуты"""

def timestamp_to_datetime(timestamp: int) -> datetime:
    """Unix timestamp → datetime (UTC)"""

def timestamp_to_str(timestamp: int, format: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Unix timestamp → строка"""

def validate_candle_timestamp(timestamp: int, symbol: str = None) -> bool:
    """Валидация timestamp свечи"""

def is_candle_closed(candle_timestamp: int, buffer_seconds: int = 10) -> bool:
    """Проверка что свеча закрыта"""
```

**Acceptance Criteria for each function - see section 3.1**

---

## 7. Backend: API

### 7.1 Модуль: api/filters.py

**Endpoints для управления фильтрами**

#### GET /api/filters

```python
@router.get("/api/filters")
async def get_filters(
    type: Optional[str] = None,
    enabled: Optional[bool] = None
) -> List[FilterResponse]:
    """
    Получить список фильтров
    
    Query Parameters:
    - type: 'price_change' или 'volume_spike' (optional)
    - enabled: true/false (optional)
    
    Response: 200 OK
    [
      {
        "id": 1,
        "name": "Рост 5%, спот",
        "type": "price_change",
        "enabled": true,
        "config": {...},
        "created_at": 1704801234,
        "updated_at": null,
        "last_trigger": 1704805000
      }
    ]
    
    Acceptance Criteria:
    - MUST support filtering by type
    - MUST support filtering by enabled
    - MUST include last_trigger timestamp (from filter_triggers table)
    - MUST parse config JSON
    - MUST return 200 OK
    """
```

#### GET /api/filters/{id}

```python
@router.get("/api/filters/{id}")
async def get_filter(id: int) -> FilterResponse:
    """
    Получить один фильтр
    
    Response: 200 OK or 404 Not Found
    
    Acceptance Criteria:
    - MUST return 404 if not found
    - MUST parse config JSON
    - MUST include last_trigger
    """
```

#### POST /api/filters

```python
@router.post("/api/filters", status_code=201)
async def create_filter(filter: FilterCreate) -> FilterResponse:
    """
    Создать новый фильтр
    
    Request Body:
    {
      "name": "Рост 5%, спот",
      "type": "price_change",
      "enabled": true,
      "config": {...}
    }
    
    Response: 201 Created
    
    Acceptance Criteria:
    - MUST validate config JSON structure
    - MUST validate type is 'price_change' or 'volume_spike'
    - MUST validate all required fields in config
    - MUST return 400 Bad Request if invalid
    - MUST return 201 Created with created filter
    """
```

#### PUT /api/filters/{id}

```python
@router.put("/api/filters/{id}")
async def update_filter(id: int, filter: FilterUpdate) -> FilterResponse:
    """
    Обновить фильтр
    
    Acceptance Criteria:
    - MUST validate config if provided
    - MUST update updated_at timestamp
    - MUST return 404 if not found
    - MUST return 200 OK
    """
```

#### DELETE /api/filters/{id}

```python
@router.delete("/api/filters/{id}", status_code=204)
async def delete_filter(id: int):
    """
    Удалить фильтр
    
    Acceptance Criteria:
    - MUST cascade delete filter_triggers (via FK)
    - MUST return 404 if not found
    - MUST return 204 No Content
    """
```

#### PATCH /api/filters/{id}/toggle

```python
@router.patch("/api/filters/{id}/toggle")
async def toggle_filter(id: int) -> dict:
    """
    Включить/выключить фильтр
    
    Response: 200 OK
    {
      "id": 1,
      "enabled": false
    }
    
    Acceptance Criteria:
    - MUST toggle enabled field (0 ↔ 1)
    - MUST return new state
    """
```

### 7.2 Модуль: api/triggers.py

**Endpoints для истории срабатываний**

#### GET /api/triggers

```python
@router.get("/api/triggers")
async def get_triggers(
    filter_id: Optional[int] = None,
    symbol: Optional[str] = None,
    market: Optional[str] = None,
    from_date: Optional[int] = None,
    to_date: Optional[int] = None,
    limit: int = 100,
    offset: int = 0
) -> dict:
    """
    Получить историю срабатываний
    
    Response: 200 OK
    {
      "total": 1250,
      "items": [
        {
          "id": 1,
          "filter_id": 1,
          "filter_name": "Рост 5%, спот",
          "symbol": "SOL/USDT",
          "market": "spot",
          "triggered_at": 1704805000,
          "data": {...},
          "notified": true
        }
      ]
    }
    
    Acceptance Criteria:
    - MUST support all filter parameters
    - MUST apply pagination (limit, offset)
    - MUST return total count
    - MUST order by triggered_at DESC
    - MUST parse data JSON
    """
```

#### GET /api/triggers/stats

```python
@router.get("/api/triggers/stats")
async def get_trigger_stats(period: str = "month") -> dict:
    """
    Статистика срабатываний
    
    Query Parameters:
    - period: 'today', 'week', 'month' (default: 'month')
    
    Response: 200 OK
    {
      "total_today": 45,
      "total_week": 320,
      "total_month": 1250,
      "by_filter": [
        {"filter_id": 1, "filter_name": "...", "count": 25}
      ],
      "by_symbol": [
        {"symbol": "SOL/USDT", "count": 12}
      ]
    }
    
    Acceptance Criteria:
    - MUST calculate counts for all periods
    - MUST group by filter and symbol
    - MUST order by count DESC
    """
```

### 7.3 Модуль: api/settings.py

#### GET /api/settings

```python
@router.get("/api/settings")
async def get_settings() -> dict:
    """
    Получить настройки системы
    
    Response: 200 OK
    {
      "check_interval_seconds": 60,
      "cooldown_minutes": 15,
      "telegram_configured": true,
      "parse_spot": true,
      "parse_futures": true
    }
    """
```

#### POST /api/settings/test-telegram

```python
@router.post("/api/settings/test-telegram")
async def test_telegram():
    """
    Отправить тестовое уведомление
    
    Acceptance Criteria:
    - MUST send test message to configured chat
    - MUST return 200 OK if sent
    - MUST return 400 Bad Request if failed
    """
```

### 7.4 Health Check

#### GET /health

```python
@router.get("/health")
async def health_check() -> dict:
    """
    Health check endpoint
    
    Response: 200 OK
    {
      "status": "healthy",
      "database": "connected",
      "screener": "running",
      "uptime_seconds": 86400
    }
    
    Acceptance Criteria:
    - MUST check DB connection
    - MUST check if screener is running
    - MUST return uptime
    - MUST return 200 if healthy
    - MAY return 503 if unhealthy
    """
```

---

## 8. Backend: WebSocket

### 8.1 Модуль: api/websocket.py

**Purpose:** Real-time уведомления о срабатываниях

#### ConnectionManager

```python
class ConnectionManager:
    """
    Менеджер WebSocket соединений
    
    Acceptance Criteria:
    - MUST track all active connections
    - MUST handle connect/disconnect
    - MUST broadcast to all clients
    - MUST handle client errors gracefully
    - MUST log connection count
    """
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        """Добавить клиента"""
        
    def disconnect(self, websocket: WebSocket):
        """Удалить клиента"""
        
    async def broadcast(self, message: dict):
        """Отправить сообщение всем"""
```

#### WebSocket Endpoint

```python
@router.websocket("/ws/triggers")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint для real-time уведомлений
    
    Message Format:
    {
      "type": "trigger",
      "filter_id": 1,
      "filter_name": "Рост 5%, спот",
      "symbol": "SOL/USDT",
      "market": "spot",
      "data": {...},
      "timestamp": 1704805000
    }
    
    Acceptance Criteria:
    - MUST accept WebSocket connection
    - MUST send welcome message on connect
    - MUST handle ping/pong for keep-alive
    - MUST handle disconnect gracefully
    - MUST broadcast triggers to all clients
    - MUST log connection/disconnection
    """
```

#### Function: broadcast_trigger()

```python
async def broadcast_trigger(trigger: dict):
    """
    Отправить срабатывание всем WebSocket клиентам
    
    Acceptance Criteria:
    - MUST format message with all required fields
    - MUST call manager.broadcast()
    - MUST handle if no clients connected (no error)
    - MUST log broadcast attempt
    """
```

---

## 9. Frontend

### 9.1 Структура

```
frontend/
├── index.html              # Главная (список фильтров)
├── filter-edit.html        # Создание/редактирование фильтра
├── triggers.html           # История срабатываний
├── dashboard.html          # Dashboard со статистикой
├── settings.html           # Настройки
│
├── css/
│   └── styles.css          # Кастомные стили
│
└── js/
    ├── api.js              # API клиент
    ├── websocket.js        # WebSocket клиент
    ├── filters.js          # Страница фильтров
    ├── filter-edit.js      # Форма редактирования
    ├── triggers.js         # История
    ├── dashboard.js        # Dashboard
    └── settings.js         # Настройки
```

### 9.2 WebSocket Client (js/websocket.js)

```javascript
class WebSocketClient {
    /**
     * WebSocket клиент для real-time уведомлений
     * 
     * Acceptance Criteria:
     * - MUST auto-connect on init
     * - MUST auto-reconnect on disconnect (exponential backoff)
     * - MUST send ping every 30 seconds
     * - MUST handle trigger messages
     * - MUST play sound on trigger (if enabled)
     * - MUST show browser notification (if permitted)
     * - MUST call onTriggerCallback
     * - MUST show connection status indicator
     */
    
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.soundEnabled = localStorage.getItem('soundEnabled') === 'true';
        this.notificationSound = new Audio('/sounds/notification.mp3');
    }
    
    connect() { }
    onMessage(event) { }
    handleTrigger(message) { }
    playNotificationSound() { }
    showBrowserNotification(message) { }
    scheduleReconnect() { }
}
```

### 9.3 Основные страницы

#### index.html - Список фильтров

**Acceptance Criteria:**
- MUST show all filters (tabs: Все / Изменение цены / Всплеск объёмов)
- MUST show filter card with: name, market, params, status (toggle)
- MUST allow: create, edit, clone, delete
- MUST update without page reload
- MUST use Tailwind CSS dark theme

#### filter-edit.html - Форма фильтра

**Acceptance Criteria:**
- MUST have separate forms for each filter type
- MUST validate all inputs
- MUST show error messages
- MUST save to API
- MUST redirect after save

#### triggers.html - История срабатываний

**Acceptance Criteria:**
- MUST show triggers table (paginated)
- MUST filter by: filter, symbol, market, date range
- MUST show real-time new triggers (via WebSocket)
- MUST prepend new triggers with animation
- MUST limit to 20 per page

#### dashboard.html - Dashboard

**Acceptance Criteria:**
- MUST show: active filters, triggers today/week, monitored symbols
- SHOULD show: chart of triggers over time
- SHOULD show: top 10 symbols by triggers
- MUST show last 10 triggers (real-time)

#### settings.html - Настройки

**Acceptance Criteria:**
- MUST allow: edit check interval, cooldown
- MUST allow: test Telegram notification
- MUST allow: export/import filters (JSON)
- MUST show: DB size, backup button

### 9.4 Дизайн

**Тема:** Тёмная

**Цвета:**
- Фон: `#1a1d29`
- Карточки: `#252936`
- Текст: `#e0e0e0`
- Акцент: `#8b5cf6` (фиолетовый)
- Успех: `#10b981` (зелёный)
- Ошибка: `#ef4444` (красный)

**Компоненты:**
- Border radius: 12px
- Box shadows
- Smooth transitions
- Hover effects

---

## 10. Docker & Deployment

### 10.1 docker-compose.yml

```yaml
version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    container_name: crypto_screener_backend
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/data
      - ./logs:/logs
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  frontend:
    image: nginx:alpine
    container_name: crypto_screener_frontend
    restart: unless-stopped
    volumes:
      - ./frontend:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    ports:
      - "3000:80"
    depends_on:
      - backend
```

**Acceptance Criteria:**
- MUST use volumes for persistence
- MUST have healthcheck for backend
- MUST restart on failure
- MUST use .env file
- MUST expose ports correctly

### 10.2 Dockerfile.backend

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/

RUN mkdir -p /data /logs

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/screener.db
ENV LOG_PATH=/logs/screener.log

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 10.3 requirements.txt

```txt
fastapi==0.109.0
uvicorn[standard]==0.27.0
websockets==12.0
ccxt==4.2.25
python-telegram-bot==20.7
aiosqlite==0.19.0
python-dotenv==1.0.0
python-multipart==0.0.6
pydantic==2.5.3
pydantic-settings==2.1.0
```

### 10.4 .env.example

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789

# Screener
CHECK_INTERVAL_SECONDS=60
COOLDOWN_MINUTES=15
PARSE_SPOT=true
PARSE_FUTURES=true

# Database
DB_PATH=/data/screener.db

# Logging
LOG_LEVEL=INFO
LOG_PATH=/logs/screener.log
```

---

## 11. Acceptance Criteria

### 11.1 Функциональные требования

#### Критичные (MUST HAVE)

- ✅ Парсинг Bybit spot и futures (раздельно)
- ✅ Работа со временем (только закрытые свечи, секунды)
- ✅ Использование quoteVolume (USD)
- ✅ Правильный алгоритм всплеска объёмов
- ✅ Синхронизация парсинга и проверки
- ✅ Retry механизм для сетевых ошибок
- ✅ Два типа фильтров (price_change, volume_spike)
- ✅ CRUD для фильтров через API
- ✅ Telegram уведомления
- ✅ WebSocket real-time обновления
- ✅ Cooldown система
- ✅ История срабатываний
- ✅ Docker deployment

#### Важные (SHOULD HAVE)

- ⚠️ Детальное логирование (DEBUG уровень)
- ⚠️ Валидация всех входных данных
- ⚠️ Обработка edge cases (NaN, Infinity, null)
- ⚠️ SQLite оптимизации (WAL, cache)
- ⚠️ Автоматическая очистка старых данных
- ⚠️ Dashboard с графиками
- ⚠️ Экспорт/импорт фильтров

#### Желательные (NICE TO HAVE)

- 💡 Makefile для быстрых команд
- 💡 Скрипт диагностики
- 💡 Health monitor с алертами
- 💡 Автоматические бэкапы
- 💡Unit тесты

### 11.2 Нефункциональные требования

#### Производительность

- Парсинг всех данных < 10 минут
- API response time < 500ms
- WebSocket latency < 100ms
- Проверка всех фильтров < 5 секунд

#### Надёжность

- Автоматический restart при падении (Docker)
- Graceful shutdown (сохранение состояния)
- Retry logic для API ошибок
- Обработка VPN проблем

#### Масштабируемость

- Поддержка 500+ символов
- Поддержка 50+ фильтров
- 100k+ записей в истории
- 10 одновременных WebSocket клиентов

#### Безопасность

- Секреты в .env (не в коде)
- .env в .gitignore
- Валидация всех входов (Pydantic)
- Защита от SQL injection (параметризованные запросы)

---

## Следующие документы

Это был **TECHNICAL_SPECIFICATION_V2.md** - главный документ.

Следующие документы:
1. ✅ IMPLEMENTATION_PLAN.md - пошаговый план реализации
2. ✅ FILE_STRUCTURE.md - детальная структура файлов
3. ✅ CODE_REQUIREMENTS.md - стандарты кодирования
4. ✅ API_SPECIFICATION.md - полная API документация
5. ✅ CRITICAL_CHECKS.md - чек-лист проверок

---

**Дата создания:** 2026-01-12  
**Версия:** 2.0  
**Статус:** Ready for implementation
