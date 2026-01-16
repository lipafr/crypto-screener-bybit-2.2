# Структура файлов проекта

**Дата:** 2026-01-12  
**Версия:** 1.0  
**Цель:** Детальное описание каждого файла и модуля для генерации кода

---

## 📁 Полная структура проекта

```
crypto_screener/
├── .env                          # Секреты (НЕ в Git!)
├── .env.example                  # Шаблон для .env
├── .gitignore                    # Игнорируемые файлы
├── .dockerignore                 # Игнор для Docker build
├── README.md                     # Документация для пользователя
├── requirements.txt              # Python зависимости
├── docker-compose.yml            # Docker оркестрация
├── Dockerfile.backend            # Backend образ
├── nginx.conf                    # Nginx конфигурация
│
├── backend/                      # Python backend
│   ├── __init__.py
│   ├── main.py                   # FastAPI приложение
│   ├── config.py                 # Настройки (Pydantic)
│   │
│   ├── api/                      # REST API endpoints
│   │   ├── __init__.py
│   │   ├── filters.py            # CRUD фильтров
│   │   ├── triggers.py           # История срабатываний
│   │   ├── settings.py           # Настройки системы
│   │   └── websocket.py          # WebSocket endpoint
│   │
│   ├── screener/                 # Движок скринера
│   │   ├── __init__.py
│   │   ├── engine.py             # Главный цикл
│   │   ├── database.py           # SQLite операции
│   │   ├── exchange.py           # CCXT интеграция
│   │   ├── filters.py            # Логика фильтров
│   │   ├── notifications.py      # Telegram бот
│   │   └── time_utils.py         # Работа со временем
│   │
│   ├── models/                   # Pydantic модели
│   │   ├── __init__.py
│   │   ├── filter.py             # Filter schemas
│   │   ├── trigger.py            # Trigger schemas
│   │   └── settings.py           # Settings schemas
│   │
│   └── utils/                    # Утилиты
│       ├── __init__.py
│       ├── logging_config.py     # Настройка логирования
│       └── validation.py         # Валидация данных
│
├── frontend/                     # Веб-интерфейс
│   ├── index.html                # Главная (список фильтров)
│   ├── filter-edit.html          # Создание/редактирование
│   ├── triggers.html             # История срабатываний
│   ├── dashboard.html            # Dashboard
│   ├── settings.html             # Настройки
│   │
│   ├── css/
│   │   └── styles.css            # Кастомные стили
│   │
│   ├── js/
│   │   ├── api.js                # API клиент
│   │   ├── websocket.js          # WebSocket клиент
│   │   ├── filters.js            # Логика страницы фильтров
│   │   ├── filter-edit.js        # Логика формы
│   │   ├── triggers.js           # Логика истории
│   │   ├── dashboard.js          # Логика dashboard
│   │   └── settings.js           # Логика настроек
│   │
│   └── sounds/
│       └── notification.mp3      # Звук уведомления
│
├── data/                         # SQLite БД (volume, не в Git)
│   ├── .gitkeep
│   └── screener.db               # База данных (создаётся автоматически)
│
├── logs/                         # Логи (volume, не в Git)
│   ├── .gitkeep
│   └── screener.log              # Лог файл (создаётся автоматически)
│
└── scripts/                      # Вспомогательные скрипты (опционально)
    ├── diagnose.sh               # Диагностика системы
    ├── backup.sh                 # Бэкап БД
    └── test_*.py                 # Тестовые скрипты
```

---

## 📄 Описание файлов

### Корневые конфигурационные файлы

#### .env
```bash
# Purpose: Секретные данные и конфигурация
# Location: Корень проекта
# Git: НЕ коммитить! (в .gitignore)

TELEGRAM_BOT_TOKEN=123456:ABC-DEF
TELEGRAM_CHAT_ID=123456789
CHECK_INTERVAL_SECONDS=300
COOLDOWN_MINUTES=15
PARSE_SPOT=true
PARSE_FUTURES=true
DB_PATH=/data/screener.db
LOG_LEVEL=INFO
LOG_PATH=/logs/screener.log
```

#### requirements.txt
```txt
# Purpose: Python зависимости
# Usage: pip install -r requirements.txt

fastapi==0.109.0
uvicorn[standard]==0.27.0
websockets==12.0
ccxt==4.2.25
python-telegram-bot==20.7
aiosqlite==0.19.0
python-dotenv==1.0.0
pydantic==2.5.3
pydantic-settings==2.1.0
```

#### docker-compose.yml
```yaml
# Purpose: Оркестрация контейнеров
# Services: backend, frontend (nginx)
# Volumes: data, logs
# Ports: 3000 (frontend), 8000 (backend)
```

---

## 🐍 Backend файлы

### backend/main.py

**Purpose:** Точка входа FastAPI приложения

**Responsibilities:**
- Создание FastAPI app
- Подключение роутеров (filters, triggers, settings, websocket)
- CORS middleware
- Health check endpoint
- Startup event (запуск screener)

**Key Functions:**
```python
app = FastAPI(title="Crypto Screener", version="2.0")

@app.get("/health")
async def health_check() -> dict

@app.on_event("startup")
async def startup()
```

**Dependencies:**
- fastapi
- backend.api.* (routers)
- backend.screener.engine (start_screener)

---

### backend/config.py

**Purpose:** Глобальные настройки приложения

**Responsibilities:**
- Загрузка переменных из .env
- Валидация конфигурации
- Предоставление settings singleton

**Key Classes:**
```python
class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str
    
    # Screener
    check_interval_seconds: int = 300
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

**Dependencies:**
- pydantic-settings
- python-dotenv

---

### backend/api/filters.py

**Purpose:** REST API endpoints для управления фильтрами

**Endpoints:**
- `GET /api/filters` - список фильтров
- `GET /api/filters/{id}` - один фильтр
- `POST /api/filters` - создать
- `PUT /api/filters/{id}` - обновить
- `DELETE /api/filters/{id}` - удалить
- `PATCH /api/filters/{id}/toggle` - включить/выключить

**Key Functions:**
```python
from fastapi import APIRouter, HTTPException
from backend.models.filter import FilterCreate, FilterResponse
from backend.screener.database import *

router = APIRouter()

@router.get("/filters")
async def get_filters(
    type: Optional[str] = None,
    enabled: Optional[bool] = None
) -> List[FilterResponse]

@router.post("/filters", status_code=201)
async def create_filter(filter: FilterCreate) -> FilterResponse

# etc...
```

**Dependencies:**
- FastAPI (Router, HTTPException)
- backend.models.filter
- backend.screener.database

---

### backend/api/triggers.py

**Purpose:** API для истории срабатываний

**Endpoints:**
- `GET /api/triggers` - история с фильтрацией и пагинацией
- `GET /api/triggers/stats` - статистика

**Key Functions:**
```python
@router.get("/triggers")
async def get_triggers(
    filter_id: Optional[int] = None,
    symbol: Optional[str] = None,
    market: Optional[str] = None,
    from_date: Optional[int] = None,
    to_date: Optional[int] = None,
    limit: int = 100,
    offset: int = 0
) -> dict

@router.get("/triggers/stats")
async def get_trigger_stats(period: str = "month") -> dict
```

---

### backend/api/settings.py

**Purpose:** API для системных настроек

**Endpoints:**
- `GET /api/settings` - получить настройки
- `POST /api/settings/test-telegram` - тест Telegram

**Key Functions:**
```python
@router.get("/settings")
async def get_settings() -> dict

@router.post("/settings/test-telegram")
async def test_telegram() -> dict
```

---

### backend/api/websocket.py

**Purpose:** WebSocket для real-time уведомлений

**Responsibilities:**
- Управление WebSocket соединениями
- Broadcast сообщений всем клиентам
- Ping/Pong keep-alive

**Key Classes & Functions:**
```python
from fastapi import WebSocket, WebSocketDisconnect
from typing import Set

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket)
    def disconnect(self, websocket: WebSocket)
    async def broadcast(self, message: dict)

manager = ConnectionManager()

@router.websocket("/ws/triggers")
async def websocket_endpoint(websocket: WebSocket)

async def broadcast_trigger(trigger: dict)
```

**Message Format:**
```json
{
  "type": "trigger",
  "filter_id": 1,
  "filter_name": "Рост 5%",
  "symbol": "BTC/USDT",
  "market": "spot",
  "data": {...},
  "timestamp": 1736614800
}
```

---

### backend/screener/engine.py

**Purpose:** Главный движок скринера

**Responsibilities:**
- Основной цикл парсинга и проверки
- Парсинг данных с биржи
- Проверка всех фильтров
- Очистка старых данных
- Координация всех модулей

**Key Functions:**
```python
async def start_screener():
    """Точка входа скринера"""
    
async def _main_loop():
    """Главный цикл: parse → wait → check → sleep"""
    
async def _parse_market_data() -> dict:
    """
    Парсинг spot и futures данных
    Returns: статистика парсинга
    """
    
async def _check_filters() -> int:
    """
    Проверка всех активных фильтров
    Returns: количество срабатываний
    """
    
async def _cleanup_old_data():
    """Очистка candles > 2h, triggers > 30d"""
```

**Algorithm:**
```
1. Init database
2. Loop:
   a. Parse market data (spot + futures)
   b. Wait 5 seconds
   c. Check all filters
   d. Sleep (CHECK_INTERVAL_SECONDS)
3. Cleanup loop (every 15 min)
```

---

### backend/screener/database.py

**Purpose:** Все операции с SQLite БД

**Responsibilities:**
- Создание схемы БД
- CRUD для candles, tickers, filters, filter_triggers
- Cooldown проверка
- Cleanup старых данных

**Key Functions:**
```python
# Initialization
async def init_database()
async def apply_pragma_optimizations()

# Candles
async def save_candle(symbol, market, timestamp, open, high, low, close, volume)
async def get_candles(symbol, market, minutes) -> list
async def cleanup_old_candles(hours=2)

# Tickers
async def save_ticker(symbol, market, volume_24h, last_price)
async def get_ticker(symbol, market) -> dict
async def get_symbols_for_market(market) -> list

# Filters
async def get_active_filters() -> list
async def get_filter(id) -> dict
async def create_filter(name, type, config) -> int
async def update_filter(id, **kwargs)
async def delete_filter(id)
async def toggle_filter(id)

# Triggers
async def save_trigger(filter_id, filter_name, symbol, market, data) -> int
async def get_triggers(...) -> dict
async def get_trigger_stats(period) -> dict
async def check_cooldown(filter_id, symbol, market, minutes) -> bool
async def cleanup_old_triggers(days=30)
```

**Schema:**
- candles (свечи за 2 часа)
- tickers (текущие данные)
- filters (настройки фильтров)
- filter_triggers (история срабатываний)

---

### backend/screener/exchange.py

**Purpose:** Интеграция с Bybit через CCXT

**Responsibilities:**
- Получение тикеров (spot/futures раздельно)
- Получение свечей
- Retry механизм для сетевых ошибок
- Валидация данных от биржи

**Key Functions:**
```python
import ccxt.async_support as ccxt

async def init_exchange() -> ccxt.bybit:
    """Инициализация CCXT"""
    
async def fetch_spot_tickers() -> dict:
    """Спот тикеры (BTC/USDT без ':')"""
    
async def fetch_futures_tickers() -> dict:
    """Фьючерсы Linear (BTC/USDT:USDT)"""
    
async def fetch_candles(symbol, market, timeframe='1m', limit=121) -> list:
    """
    Свечи для символа
    ВАЖНО: исключает последнюю (текущую) свечу!
    """

def retry_on_network_error(max_attempts=3, delay=5.0):
    """Декоратор для retry при NetworkError"""
```

**Critical:**
- MUST set `exchange.options['defaultType']` перед запросами
- MUST exclude last candle (current, not closed)
- MUST use quoteVolume
- MUST retry on NetworkError

---

### backend/screener/filters.py

**Purpose:** Логика проверки фильтров

**Responsibilities:**
- Проверка фильтра "Изменение цены"
- Проверка фильтра "Всплеск объёмов"
- Вычисление максимального изменения цены
- Валидация условий

**Key Functions:**
```python
async def check_price_change_filter(
    symbol: str,
    market: str,
    filter_config: dict,
    filter_name: str
) -> Optional[dict]:
    """
    Проверка фильтра изменения цены
    
    Returns:
        dict с trigger data если сработал
        None если не сработал
    """

async def check_volume_spike_filter(
    symbol: str,
    market: str,
    filter_config: dict,
    filter_name: str
) -> Optional[dict]:
    """
    Проверка фильтра всплеска объёмов
    
    КРИТИЧНО: Исключить current period из average!
    """

def calculate_max_price_change(candles: list, direction: str) -> tuple:
    """
    Найти максимальное изменение цены в периоде
    НЕ просто first-to-last!
    
    Returns:
        (max_change_percent, price_from, price_to)
    """
```

**Critical:**
- Volume spike MUST exclude current period from average
- Price change MUST find MAX, not just first-to-last
- MUST log DEBUG for each check
- MUST check cooldown before returning trigger

---

### backend/screener/notifications.py

**Purpose:** Telegram уведомления

**Responsibilities:**
- Инициализация Telegram бота
- Отправка уведомлений
- Форматирование сообщений

**Key Functions:**
```python
from telegram import Bot
from backend.config import settings

bot = Bot(token=settings.telegram_bot_token)

async def send_telegram_notification(trigger: dict):
    """Отправить уведомление о срабатывании"""
    
def format_telegram_message(trigger: dict) -> str:
    """Форматирование сообщения (HTML)"""
    
async def send_test_message():
    """Тестовое уведомление"""
```

**Message Format:**
```
🚀 Сработал фильтр: "Название"

💰 Пара: BTC/USDT
📊 Рынок: Spot
📈 Изменение: +7.3%
💵 Цена: $90000 → $96570
📦 Объём: $245K
📊 Объём 24ч: $5.2B

⏰ 12.01.2026 14:30:00
🔗 Bybit: https://...
```

---

### backend/screener/time_utils.py

**Purpose:** Корректная работа со временем

**Responsibilities:**
- Получение текущего timestamp
- Определение последней закрытой свечи
- Вычисление временных окон
- Валидация timestamps

**Key Functions:**
```python
import time
from datetime import datetime, timezone

def get_current_timestamp() -> int:
    """Текущий Unix timestamp (UTC, секунды)"""
    return int(time.time())

def get_last_closed_candle_timestamp() -> int:
    """
    Последняя ГАРАНТИРОВАННО закрытая минута
    КРИТИЧНО: ALWAYS return current_minute - 60
    """
    now = int(time.time())
    current_minute = (now // 60) * 60
    return current_minute - 60

def get_candle_window(minutes: int) -> tuple[int, int]:
    """
    Окно времени для свечей
    Returns: (start, end) в секундах
    """
    
def round_to_minute(timestamp: int) -> int:
    """Округлить до начала минуты"""
    return (timestamp // 60) * 60

def validate_candle_timestamp(timestamp: int, symbol: str = None) -> bool:
    """
    Валидация timestamp:
    - Не в будущем
    - Не слишком старый
    - Округлён до минуты
    """

def timestamp_to_str(timestamp: int, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Unix timestamp → строка (UTC)"""
```

**Critical:**
- ALL timestamps MUST be in seconds
- get_last_closed_candle_timestamp() NEVER use "if elapsed < 10"
- ALL datetime operations MUST use UTC

---

### backend/models/filter.py

**Purpose:** Pydantic модели для фильтров

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict

class FilterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(price_change|volume_spike)$")
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
    
    class Config:
        from_attributes = True
```

---

### backend/models/trigger.py

**Purpose:** Pydantic модели для срабатываний

```python
class TriggerResponse(BaseModel):
    id: int
    filter_id: int
    filter_name: str
    symbol: str
    market: str
    triggered_at: int
    data: Dict
    notified: bool
    
    class Config:
        from_attributes = True
```

---

### backend/utils/logging_config.py

**Purpose:** Настройка логирования

```python
import logging
from logging.handlers import RotatingFileHandler
from backend.config import settings

def setup_logging():
    """
    Настройка логирования:
    - Уровень из settings.log_level
    - Формат: timestamp | level | module:func:line | message
    - RotatingFileHandler: 10MB × 5 = 50MB max
    - Suppress noisy libraries (ccxt, telegram, httpx)
    """
    
    # Root logger
    logger = logging.getLogger()
    logger.setLevel(settings.log_level)
    
    # Format
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (rotating)
    if settings.log_path:
        file_handler = RotatingFileHandler(
            settings.log_path,
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # Suppress noisy libraries
    logging.getLogger('ccxt').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
```

---

## 🌐 Frontend файлы

### frontend/js/api.js

**Purpose:** API клиент для взаимодействия с backend

```javascript
class APIClient {
    constructor(baseUrl = 'http://localhost:8000') {
        this.baseUrl = baseUrl;
    }
    
    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        return response.json();
    }
    
    // Filters
    async getFilters(params = {}) { }
    async getFilter(id) { }
    async createFilter(data) { }
    async updateFilter(id, data) { }
    async deleteFilter(id) { }
    async toggleFilter(id) { }
    
    // Triggers
    async getTriggers(params = {}) { }
    async getTriggerStats(period = 'month') { }
    
    // Settings
    async getSettings() { }
    async testTelegram() { }
}

const api = new APIClient();
```

---

### frontend/js/websocket.js

**Purpose:** WebSocket клиент для real-time уведомлений

**Key Features:**
- Auto-connect
- Auto-reconnect (exponential backoff)
- Ping/Pong keep-alive
- Sound notifications
- Browser notifications
- Connection status indicator

```javascript
class WebSocketClient {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.soundEnabled = localStorage.getItem('soundEnabled') === 'true';
        this.onTriggerCallback = null;
    }
    
    connect() { }
    onMessage(event) { }
    handleTrigger(message) { }
    playNotificationSound() { }
    showBrowserNotification(message) { }
    scheduleReconnect() { }
    setOnTriggerCallback(callback) { }
}

window.wsClient = new WebSocketClient();
```

---

### frontend/index.html

**Purpose:** Главная страница (список фильтров)

**Features:**
- Вкладки: Все / Изменение цены / Всплеск объёмов
- Карточки фильтров
- Toggle switch (вкл/выкл)
- Кнопки: Создать, Редактировать, Клонировать, Удалить
- Поиск по названию

---

### frontend/filter-edit.html

**Purpose:** Создание/редактирование фильтра

**Features:**
- Две формы (для каждого типа)
- Валидация полей
- Динамическое переключение формы по типу
- Кнопки: Сохранить, Сохранить и запустить, Отмена

---

### frontend/triggers.html

**Purpose:** История срабатываний

**Features:**
- Таблица с пагинацией
- Фильтры: по фильтру, монете, рынку, дате
- Real-time обновления (WebSocket)
- Анимация новых срабатываний

---

## 🐳 Docker файлы

### Dockerfile.backend

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/

RUN mkdir -p /data /logs

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Порядок создания файлов

**Для генерации кода следуй этому порядку:**

1. Config & Utils:
   - backend/config.py
   - backend/utils/logging_config.py

2. Database Layer:
   - backend/screener/database.py

3. External Integrations:
   - backend/screener/exchange.py
   - backend/screener/time_utils.py
   - backend/screener/notifications.py

4. Business Logic:
   - backend/screener/filters.py

5. Engine:
   - backend/screener/engine.py

6. API Models:
   - backend/models/filter.py
   - backend/models/trigger.py

7. API Endpoints:
   - backend/api/filters.py
   - backend/api/triggers.py
   - backend/api/settings.py
   - backend/api/websocket.py

8. Main Application:
   - backend/main.py

9. Frontend:
   - frontend/js/api.js
   - frontend/js/websocket.js
   - frontend/index.html
   - (остальные страницы)

10. Docker:
    - Dockerfile.backend
    - docker-compose.yml
    - nginx.conf

---

**Дата:** 2026-01-12  
**Статус:** Ready for code generation
