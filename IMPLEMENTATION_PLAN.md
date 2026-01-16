# План реализации: Криптоскринер Bybit

**Дата:** 2026-01-12  
**Версия:** 1.0  
**Цель:** Пошаговая инструкция для последовательной реализации проекта

---

## 📋 Оглавление

1. [Обзор этапов](#1-обзор-этапов)
2. [Этап 0: Подготовка](#2-этап-0-подготовка)
3. [Этап 1: База данных](#3-этап-1-база-данных)
4. [Этап 2: Exchange Integration](#4-этап-2-exchange-integration)
5. [Этап 3: Time Utils](#5-этап-3-time-utils)
6. [Этап 4: Filters Logic](#6-этап-4-filters-logic)
7. [Этап 5: Screener Engine](#7-этап-5-screener-engine)
8. [Этап 6: Telegram Notifications](#8-этап-6-telegram-notifications)
9. [Этап 7: REST API](#9-этап-7-rest-api)
10. [Этап 8: WebSocket](#10-этап-8-websocket)
11. [Этап 9: Frontend](#11-этап-9-frontend)
12. [Этап 10: Docker](#12-этап-10-docker)
13. [Этап 11: Testing & Validation](#13-этап-11-testing--validation)

---

## 1. Обзор этапов

### Порядок реализации

```
Этап 0: Подготовка
    ↓
Этап 1: База данных (schema + utils)
    ↓
Этап 2: Exchange Integration (CCXT)
    ↓
Этап 3: Time Utils (работа со временем)
    ↓
Этап 4: Filters Logic (проверка фильтров)
    ↓
Этап 5: Screener Engine (главный цикл)
    ↓
Этап 6: Telegram (уведомления)
    ↓
Этап 7: REST API (endpoints)
    ↓
Этап 8: WebSocket (real-time)
    ↓
Этап 9: Frontend (UI)
    ↓
Этап 10: Docker (deployment)
    ↓
Этап 11: Testing (валидация)
```

### Зависимости между модулями

```
database.py ─┬─> exchange.py
             │
             ├─> time_utils.py ──> filters.py ──> engine.py
             │
             └─> notifications.py ──────────────────┘

engine.py ──> main.py (FastAPI)
         └──> api/* (endpoints)
         └──> websocket.py
```

---

## 2. Этап 0: Подготовка

### Шаг 0.1: Создать структуру проекта

```bash
mkdir -p crypto_screener/{backend/{api,screener,models,utils},frontend/{css,js},data,logs,config}
cd crypto_screener
```

**Создать файлы:**
```
crypto_screener/
├── .gitignore
├── .env.example
├── requirements.txt
├── docker-compose.yml
├── Dockerfile.backend
├── nginx.conf
├── README.md
│
├── backend/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── api/__init__.py
│   ├── screener/__init__.py
│   ├── models/__init__.py
│   └── utils/__init__.py
│
└── frontend/
    ├── index.html
    └── js/
        └── api.js
```

### Шаг 0.2: Создать .gitignore

```gitignore
# Environment
.env
.env.local
.env.production

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/

# Database
*.db
*.db-shm
*.db-wal

# Logs
logs/
*.log

# Data
data/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
```

### Шаг 0.3: Создать requirements.txt

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

### Шаг 0.4: Создать .env.example

```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

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

# API
API_HOST=0.0.0.0
API_PORT=8000
```

### Чек-лист Этапа 0:

- [ ] Структура папок создана
- [ ] .gitignore настроен
- [ ] requirements.txt создан
- [ ] .env.example создан
- [ ] Все __init__.py файлы созданы

---

## 3. Этап 1: База данных

### Цель: Создать схему БД и функции для работы с ней

### Шаг 1.1: Создать backend/screener/database.py

**Что реализовать:**

1. ✅ **Схема БД** (CREATE TABLE statements)
   - Таблица `candles` - исторические свечи
   - Таблица `tickers` - текущие тикеры
   - Таблица `filters` - настройки фильтров
   - Таблица `filter_triggers` - история срабатываний
   - Индексы для быстрых запросов

2. ✅ **init_database()** - инициализация БД
   - Создание таблиц
   - Применение PRAGMA оптимизаций
   - ANALYZE

3. ✅ **CRUD для candles:**
   ```python
   async def save_candle(symbol, market, timestamp, open, high, low, close, volume)
   async def get_candles(symbol, market, minutes) -> list
   async def cleanup_old_candles(hours=2)
   ```

4. ✅ **CRUD для tickers:**
   ```python
   async def save_ticker(symbol, market, volume_24h, last_price)
   async def get_ticker(symbol, market) -> dict
   async def get_symbols_for_market(market) -> list[str]
   ```

5. ✅ **CRUD для filters:**
   ```python
   async def get_active_filters() -> list
   async def get_filter(id) -> dict
   async def create_filter(name, type, config) -> int
   async def update_filter(id, **kwargs)
   async def delete_filter(id)
   async def toggle_filter(id)
   ```

6. ✅ **CRUD для filter_triggers:**
   ```python
   async def save_trigger(filter_id, filter_name, symbol, market, data) -> int
   async def get_triggers(filter_id=None, symbol=None, limit=100, offset=0) -> dict
   async def check_cooldown(filter_id, symbol, market, minutes=15) -> bool
   async def cleanup_old_triggers(days=30)
   ```

### Шаг 1.2: Тестирование БД

**Создать test_database.py:**
```python
import asyncio
from backend.screener.database import *

async def test():
    await init_database()
    
    # Test save_candle
    await save_candle('BTC/USDT', 'spot', 1736614800, 90000, 91000, 89000, 90500, 100000)
    
    # Test get_candles
    candles = await get_candles('BTC/USDT', 'spot', 15)
    print(f"Candles: {len(candles)}")
    
    # Test save_ticker
    await save_ticker('BTC/USDT', 'spot', 5000000000, 90500)
    
    # Test get_ticker
    ticker = await get_ticker('BTC/USDT', 'spot')
    print(f"Ticker: {ticker}")

asyncio.run(test())
```

**Запуск:**
```bash
python test_database.py
```

### Чек-лист Этапа 1:

- [ ] database.py создан
- [ ] Схема БД реализована
- [ ] init_database() работает
- [ ] CRUD для candles работает
- [ ] CRUD для tickers работает
- [ ] CRUD для filters работает
- [ ] CRUD для triggers работает
- [ ] Тесты пройдены
- [ ] БД создаётся в /data/screener.db

---

## 4. Этап 2: Exchange Integration

### Цель: Интеграция с Bybit через CCXT

### Шаг 2.1: Создать backend/screener/exchange.py

**Что реализовать:**

1. ✅ **init_exchange()** - инициализация CCXT
   ```python
   async def init_exchange() -> ccxt.bybit:
       exchange = ccxt.bybit({
           'enableRateLimit': True,
           'timeout': 30000,
       })
       return exchange
   ```

2. ✅ **fetch_spot_tickers()** - получить спот тикеры
   ```python
   async def fetch_spot_tickers() -> dict:
       exchange.options['defaultType'] = 'spot'
       tickers = await exchange.fetch_tickers()
       # Фильтр только USDT пар без ':'
       return usdt_tickers
   ```

3. ✅ **fetch_futures_tickers()** - получить фьючерсные тикеры
   ```python
   async def fetch_futures_tickers() -> dict:
       exchange.options['defaultType'] = 'linear'
       tickers = await exchange.fetch_tickers()
       # Фильтр только /USDT:USDT
       return linear_tickers
   ```

4. ✅ **fetch_candles()** - получить свечи
   ```python
   async def fetch_candles(symbol, market, timeframe='1m', limit=121) -> list:
       exchange.options['defaultType'] = market  # spot/linear
       candles = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
       # Исключить последнюю (текущую) свечу
       return candles[:-1]
   ```

5. ✅ **retry_on_network_error()** - декоратор для retry
   ```python
   def retry_on_network_error(max_attempts=3, delay_seconds=5.0):
       # Реализация декоратора с exponential backoff
   ```

### Шаг 2.2: Тестирование Exchange

**Создать test_exchange.py:**
```python
import asyncio
from backend.screener.exchange import *

async def test():
    exchange = await init_exchange()
    
    # Test spot
    spot_tickers = await fetch_spot_tickers()
    print(f"Spot tickers: {len(spot_tickers)}")
    print(f"Sample: {list(spot_tickers.keys())[:5]}")
    
    # Test futures
    futures_tickers = await fetch_futures_tickers()
    print(f"Futures tickers: {len(futures_tickers)}")
    print(f"Sample: {list(futures_tickers.keys())[:5]}")
    
    # Test candles
    candles = await fetch_candles('BTC/USDT', 'spot', '1m', 121)
    print(f"Candles: {len(candles)}")
    print(f"Latest: {candles[-1]}")

asyncio.run(test())
```

**Запуск:**
```bash
python test_exchange.py
```

### Чек-лист Этапа 2:

- [ ] exchange.py создан
- [ ] init_exchange() работает
- [ ] fetch_spot_tickers() возвращает правильные символы (без ':')
- [ ] fetch_futures_tickers() возвращает Linear (/USDT:USDT)
- [ ] fetch_candles() исключает последнюю свечу
- [ ] retry_on_network_error() декоратор работает
- [ ] Тесты пройдены

---

## 5. Этап 3: Time Utils

### Цель: Функции для корректной работы со временем

### Шаг 3.1: Создать backend/screener/time_utils.py

**Что реализовать:**

1. ✅ **get_current_timestamp()** - текущий timestamp
2. ✅ **get_last_closed_candle_timestamp()** - последняя закрытая свеча
3. ✅ **get_candle_window(minutes)** - окно времени
4. ✅ **round_to_minute(timestamp)** - округление
5. ✅ **timestamp_to_datetime(timestamp)** - конвертация в datetime
6. ✅ **timestamp_to_str(timestamp)** - конвертация в строку
7. ✅ **validate_candle_timestamp(timestamp)** - валидация
8. ✅ **is_candle_closed(candle_timestamp)** - проверка закрытия

**Критично:**
- `get_last_closed_candle_timestamp()` MUST ALWAYS return `current_minute - 60`
- Все функции MUST use UTC timezone
- Все timestamps MUST быть в секундах

### Шаг 3.2: Тестирование Time Utils

**Создать test_time_utils.py:**
```python
import time
from backend.screener.time_utils import *

def test():
    # Test current timestamp
    now = get_current_timestamp()
    print(f"Now: {now} ({timestamp_to_str(now)})")
    
    # Test last closed
    last_closed = get_last_closed_candle_timestamp()
    print(f"Last closed: {last_closed} ({timestamp_to_str(last_closed)})")
    
    # Test window
    start, end = get_candle_window(15)
    print(f"Window 15m: {timestamp_to_str(start)} - {timestamp_to_str(end)}")
    
    # Test validation
    valid = validate_candle_timestamp(last_closed)
    print(f"Valid: {valid}")
    
    # Test is_closed
    closed = is_candle_closed(last_closed - 60)
    print(f"Is closed: {closed}")

test()
```

### Чек-лист Этапа 3:

- [ ] time_utils.py создан
- [ ] Все функции реализованы
- [ ] get_last_closed_candle_timestamp() возвращает current_minute - 60
- [ ] validate_candle_timestamp() проверяет корректно
- [ ] Тесты пройдены

---

## 6. Этап 4: Filters Logic

### Цель: Логика проверки фильтров

### Шаг 4.1: Создать backend/screener/filters.py

**Что реализовать:**

1. ✅ **check_price_change_filter()** - фильтр "Изменение цены"
   - Получить свечи за interval_minutes
   - Вычислить max изменение цены (НЕ только first-to-last!)
   - Проверить direction
   - Проверить min_price_change_percent
   - Вычислить volume_period
   - Проверить min_volume_period
   - Получить ticker для volume_24h
   - Проверить volume_24h range
   - Проверить exclude_coins
   - Вернуть trigger data или None

2. ✅ **check_volume_spike_filter()** - фильтр "Всплеск объёмов"
   - Получить свечи за base_period_minutes
   - КРИТИЧНО: разделить на historical и current
   - Вычислить average_volume (только из historical!)
   - Вычислить current_volume
   - Вычислить coefficient
   - Проверить spike_coefficient
   - Если min_price_change_percent > 0: проверить изменение цены
   - Проверить volume_24h range
   - Проверить exclude_coins
   - Вернуть trigger data или None

3. ✅ **calculate_max_price_change()** - вычисление max изменения
   ```python
   def calculate_max_price_change(candles, direction) -> tuple:
       # O(n²) алгоритм для поиска максимального изменения
       return (max_change_percent, price_from, price_to)
   ```

4. ✅ **is_excluded()** - проверка exclude_coins
   ```python
   def is_excluded(symbol, exclude_list) -> bool:
       # Нормализация символа и проверка
   ```

### Шаг 4.2: Тестирование Filters

**Создать test_filters.py:**
```python
import asyncio
from backend.screener.database import *
from backend.screener.filters import *

async def test():
    await init_database()
    
    # Подготовка тестовых данных
    # ... создать свечи в БД
    
    # Test price_change filter
    config = {
        'market': 'spot',
        'interval_minutes': 15,
        'min_price_change_percent': 5.0,
        'direction': 'up',
        'min_volume_period': 10000,
        'min_volume_24h': 100000,
        'max_volume_24h': None,
        'exclude_coins': []
    }
    
    result = await check_price_change_filter('BTC/USDT', 'spot', config, 'Test Filter')
    print(f"Result: {result}")

asyncio.run(test())
```

### Чек-лист Этапа 4:

- [ ] filters.py создан
- [ ] check_price_change_filter() реализован
- [ ] check_volume_spike_filter() реализован (ПРАВИЛЬНО!)
- [ ] calculate_max_price_change() ищет MAX, не first-to-last
- [ ] Volume spike ИСКЛЮЧАЕТ current period из average
- [ ] is_excluded() работает
- [ ] Тесты пройдены

---

## 7. Этап 5: Screener Engine

### Цель: Главный цикл парсинга и проверки

### Шаг 5.1: Создать backend/screener/engine.py

**Что реализовать:**

1. ✅ **start_screener()** - точка входа
   ```python
   async def start_screener():
       logger.info("Screener starting...")
       await init_database()
       
       while running:
           try:
               await _main_loop()
           except Exception as e:
               logger.error(f"Fatal error: {e}", exc_info=True)
               await asyncio.sleep(60)
   ```

2. ✅ **_main_loop()** - главный цикл
   ```python
   async def _main_loop():
       # 1. Parse
       await _parse_market_data()
       
       # 2. Wait
       await asyncio.sleep(5)
       
       # 3. Check
       await _check_filters()
       
       # 4. Sleep
       await asyncio.sleep(PARSE_INTERVAL_MINUTES * 60)
   ```

3. ✅ **_parse_market_data()** - парсинг данных
   - Определить какие рынки парсить (PARSE_SPOT, PARSE_FUTURES)
   - Для каждого рынка:
     - Fetch tickers
     - Save tickers to DB
     - Fetch candles (batched, max 10 concurrent)
     - Validate timestamps
     - Save candles to DB
   - Вернуть статистику

4. ✅ **_check_filters()** - проверка фильтров
   - Получить активные фильтры
   - Для каждого фильтра:
     - Получить символы для рынка фильтра
     - Для каждого символа:
       - Проверить фильтр
       - Если сработал:
         - Проверить cooldown
         - Сохранить trigger
         - Отправить Telegram
         - Broadcast WebSocket

5. ✅ **_cleanup_loop()** - очистка старых данных
   - Каждые 15 минут: cleanup_old_candles(2 часа)
   - Раз в день (3:00): cleanup_old_triggers(30 дней) + VACUUM

### Шаг 5.2: Создать backend/config.py

**Настройки приложения:**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str
    
    # Screener
    check_interval_seconds: int = 60
    cooldown_minutes: int = 15
    parse_spot: bool = True
    parse_futures: bool = True
    
    # Database
    db_path: str = "/data/screener.db"
    
    # Logging
    log_level: str = "INFO"
    log_path: str = "/logs/screener.log"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### Чек-лист Этапа 5:

- [ ] engine.py создан
- [ ] config.py создан
- [ ] start_screener() запускается
- [ ] _main_loop() работает последовательно
- [ ] _parse_market_data() парсит оба рынка
- [ ] _check_filters() проверяет все фильтры
- [ ] _cleanup_loop() очищает старые данные
- [ ] Логирование работает

---

## 8. Этап 6: Telegram Notifications

### Цель: Отправка уведомлений в Telegram

### Шаг 6.1: Создать backend/screener/notifications.py

**Что реализовать:**

1. ✅ **init_telegram_bot()** - инициализация бота
   ```python
   from telegram import Bot
   
   bot = Bot(token=settings.telegram_bot_token)
   ```

2. ✅ **send_telegram_notification(trigger)** - отправка уведомления
   ```python
   async def send_telegram_notification(trigger: dict):
       message = format_telegram_message(trigger)
       await bot.send_message(
           chat_id=settings.telegram_chat_id,
           text=message,
           parse_mode='HTML'
       )
   ```

3. ✅ **format_telegram_message(trigger)** - форматирование
   ```python
   def format_telegram_message(trigger: dict) -> str:
       data = trigger['data']
       market_emoji = '💰' if trigger['market'] == 'spot' else '📈'
       
       message = f"""
   🚀 Сработал фильтр: "{trigger['filter_name']}"
   
   {market_emoji} Пара: {trigger['symbol']}
   📊 Рынок: {'Spot' if trigger['market'] == 'spot' else 'Futures'}
   📈 Изменение: {data['price_change_percent']:+.2f}%
   💵 Цена: ${data['price_from']:.2f} → ${data['price_to']:.2f}
   📦 Объём: ${data['volume_period']:,.0f}
   📊 Объём 24ч: ${data['volume_24h']:,.0f}
   
   ⏰ {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
   🔗 Bybit: {data['url']}
       """
       return message.strip()
   ```

4. ✅ **send_test_message()** - тестовое уведомление
   ```python
   async def send_test_message():
       await bot.send_message(
           chat_id=settings.telegram_chat_id,
           text="✅ Тестовое уведомление от Crypto Screener"
       )
   ```

### Шаг 6.2: Тестирование Telegram

```python
import asyncio
from backend.screener.notifications import *

async def test():
    await send_test_message()
    print("Test message sent!")

asyncio.run(test())
```

### Чек-лист Этапа 6:

- [ ] notifications.py создан
- [ ] init_telegram_bot() работает
- [ ] send_telegram_notification() отправляет
- [ ] format_telegram_message() форматирует правильно
- [ ] send_test_message() работает
- [ ] Тест пройден (сообщение пришло в Telegram)

---

## 9. Этап 7: REST API

### Цель: Создать API endpoints

### Шаг 7.1: Создать backend/main.py

**FastAPI приложение:**
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncio

from backend.screener.engine import start_screener
from backend.api import filters, triggers, settings, websocket

app = FastAPI(title="Crypto Screener API", version="2.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(filters.router, prefix="/api", tags=["filters"])
app.include_router(triggers.router, prefix="/api", tags=["triggers"])
app.include_router(settings.router, prefix="/api", tags=["settings"])
app.include_router(websocket.router, tags=["websocket"])

# Health check
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Startup
@app.on_event("startup")
async def startup():
    asyncio.create_task(start_screener())
```

### Шаг 7.2: Создать backend/api/filters.py

**Endpoints:**
- `GET /api/filters` - список фильтров
- `GET /api/filters/{id}` - один фильтр
- `POST /api/filters` - создать фильтр
- `PUT /api/filters/{id}` - обновить фильтр
- `DELETE /api/filters/{id}` - удалить фильтр
- `PATCH /api/filters/{id}/toggle` - включить/выключить

### Шаг 7.3: Создать backend/api/triggers.py

**Endpoints:**
- `GET /api/triggers` - история срабатываний
- `GET /api/triggers/stats` - статистика

### Шаг 7.4: Создать backend/api/settings.py

**Endpoints:**
- `GET /api/settings` - получить настройки
- `PUT /api/settings` - обновить настройки
- `POST /api/settings/test-telegram` - тест Telegram

### Шаг 7.5: Создать Pydantic модели (backend/models/)

**filter.py:**
```python
from pydantic import BaseModel
from typing import Optional, Dict

class FilterBase(BaseModel):
    name: str
    type: str  # 'price_change' или 'volume_spike'
    enabled: bool = True
    config: Dict

class FilterCreate(FilterBase):
    pass

class FilterUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[Dict] = None

class FilterResponse(FilterBase):
    id: int
    created_at: int
    updated_at: Optional[int] = None
    last_trigger: Optional[int] = None
```

### Чек-лист Этапа 7:

- [ ] main.py создан и запускается
- [ ] filters.py с endpoints создан
- [ ] triggers.py с endpoints создан
- [ ] settings.py с endpoints создан
- [ ] Pydantic модели созданы
- [ ] API доступен на http://localhost:8000
- [ ] Swagger docs доступен на http://localhost:8000/docs
- [ ] Все endpoints работают

---

## 10. Этап 8: WebSocket

### Цель: Real-time уведомления

### Шаг 8.1: Создать backend/api/websocket.py

**Что реализовать:**

1. ✅ **ConnectionManager** - управление подключениями
2. ✅ **websocket_endpoint** - WS endpoint
3. ✅ **broadcast_trigger()** - broadcast функция

**Интеграция с engine.py:**
```python
# В _check_filters()
from backend.api.websocket import broadcast_trigger

# После сохранения trigger
await broadcast_trigger(trigger)
```

### Чек-лист Этапа 8:

- [ ] websocket.py создан
- [ ] ConnectionManager работает
- [ ] WS endpoint доступен на ws://localhost:8000/ws/triggers
- [ ] broadcast_trigger() вызывается из engine
- [ ] Клиенты получают уведомления

---

## 11. Этап 9: Frontend

### Цель: Веб-интерфейс

### Шаг 9.1: Создать frontend/js/api.js

**API клиент:**
```javascript
class APIClient {
    constructor(baseUrl = 'http://localhost:8000') {
        this.baseUrl = baseUrl;
    }
    
    async getFilters() { }
    async createFilter(data) { }
    async updateFilter(id, data) { }
    async deleteFilter(id) { }
    async toggleFilter(id) { }
    
    async getTriggers(params) { }
    async getTriggerStats() { }
    
    async getSettings() { }
    async testTelegram() { }
}

const api = new APIClient();
```

### Шаг 9.2: Создать frontend/js/websocket.js

**WebSocket клиент** (см. спецификацию)

### Шаг 9.3: Создать HTML страницы

**Порядок:**
1. index.html - список фильтров
2. filter-edit.html - создание/редактирование
3. triggers.html - история
4. dashboard.html - статистика
5. settings.html - настройки

### Шаг 9.4: Стилизация (Tailwind CSS)

**Подключить Tailwind CDN:**
```html
<script src="https://cdn.tailwindcss.com"></script>
```

### Чек-лист Этапа 9:

- [ ] api.js создан
- [ ] websocket.js создан
- [ ] index.html создан и работает
- [ ] filter-edit.html создан
- [ ] triggers.html создан с real-time
- [ ] dashboard.html создан
- [ ] settings.html создан
- [ ] Дизайн соответствует спецификации

---

## 12. Этап 10: Docker

### Цель: Контейнеризация и deployment

### Шаг 10.1: Создать Dockerfile.backend

(См. спецификацию)

### Шаг 10.2: Создать docker-compose.yml

(См. спецификацию)

### Шаг 10.3: Создать nginx.conf

(См. спецификацию)

### Шаг 10.4: Сборка и запуск

```bash
# Создать .env
cp .env.example .env
nano .env  # Заполнить токены

# Сборка
docker-compose build

# Запуск
docker-compose up -d

# Логи
docker-compose logs -f backend

# Проверка
curl http://localhost:8000/health
curl http://localhost:3000
```

### Чек-лист Этапа 10:

- [ ] Dockerfile.backend создан
- [ ] docker-compose.yml создан
- [ ] nginx.conf создан
- [ ] .env настроен
- [ ] Образы собираются
- [ ] Контейнеры запускаются
- [ ] Backend доступен на :8000
- [ ] Frontend доступен на :3000
- [ ] Healthcheck работает
- [ ] Volumes сохраняют данные

---

## 13. Этап 11: Testing & Validation

### Цель: Проверить что всё работает

### Шаг 11.1: Функциональное тестирование

**Тест 1: Парсинг данных**
```bash
# Проверить логи
docker-compose logs backend | grep "PARSING"

# Должно быть:
# "Got X SPOT tickers"
# "Got Y FUTURES tickers"
# "Candles: X/Y success"
```

**Тест 2: Создание фильтра**
- Открыть http://localhost:3000
- Создать фильтр "Тест"
- Проверить что появился в списке

**Тест 3: Срабатывание фильтра**
- Создать фильтр с низким порогом (0.1%)
- Подождать 5-10 минут
- Проверить Telegram уведомление
- Проверить WebSocket (в DevTools)
- Проверить историю

**Тест 4: WebSocket**
- Открыть http://localhost:3000/triggers.html
- Открыть DevTools → Network → WS
- Проверить что соединение установлено
- Подождать срабатывания
- Проверить что пришло через WS

### Шаг 11.2: Проверка критических требований

**Используй CRITICAL_CHECKS.md для полного списка!**

**Краткий чек-лист:**
- [ ] Timestamps в БД в секундах (10 цифр)
- [ ] Timestamps округлены до минут
- [ ] Только закрытые свечи в БД
- [ ] Спот и фьючерсы раздельно
- [ ] quoteVolume используется
- [ ] Всплеск объёмов считается правильно
- [ ] Парсинг и проверка последовательно
- [ ] Retry работает при ошибках
- [ ] Cooldown работает
- [ ] Логи детальные

### Шаг 11.3: Performance тестирование

```bash
# Время парсинга
docker-compose logs backend | grep "Parsed.*symbols in"

# Должно быть < 10 минут

# Время проверки
docker-compose logs backend | grep "Found.*triggers in"

# Должно быть < 5 секунд
```

### Шаг 11.4: Stress тестирование

**Создать 10-20 фильтров и проверить:**
- Парсинг не падает
- Проверка не замедляется
- БД не растёт слишком быстро
- Memory не утекает

### Чек-лист Этапа 11:

- [ ] Парсинг работает корректно
- [ ] Фильтры создаются и проверяются
- [ ] Срабатывания сохраняются
- [ ] Telegram уведомления приходят
- [ ] WebSocket работает
- [ ] Все критические проверки пройдены
- [ ] Performance приемлемый
- [ ] Stress test пройден

---

## Итоговый чек-лист

### Готовность к использованию:

- [ ] **Все этапы завершены**
- [ ] **Все тесты пройдены**
- [ ] **Критические требования выполнены**
- [ ] **Документация актуальна**
- [ ] **README.md создан**
- [ ] **.env.example актуален**
- [ ] **Docker deployment работает**

### Опциональные улучшения:

- [ ] Makefile создан
- [ ] Скрипт диагностики
- [ ] Автоматические бэкапы
- [ ] Health monitor
- [ ] Unit тесты

---

**Следующие шаги:** Начать реализацию с Этапа 0! 🚀

**Дата:** 2026-01-12  
**Статус:** Ready to implement
