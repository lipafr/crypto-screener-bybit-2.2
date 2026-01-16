# Критические детали реализации скринера

**Дата создания:** 11 января 2026  
**Статус:** В процессе разработки  
**Цель документа:** Описание важных технических деталей и решений проблем, выявленных при анализе логики работы системы

---

## Содержание

1. [Проблема синхронизации парсинга и проверки](#1-проблема-синхронизации-парсинга-и-проверки)
2. [Правильный расчёт всплеска объёмов](#2-правильный-расчёт-всплеска-объёмов)
3. [Использование quoteVolume вместо volume](#3-использование-quotevolume-вместо-volume)

---

## 1. Проблема синхронизации парсинга и проверки

### Описание проблемы

**Текущая реализация имеет Race Condition:**

```python
# Два независимых asyncio цикла:
asyncio.create_task(_parse_data_loop())     # Каждые 5 минут, длится 4-8 минут
asyncio.create_task(_check_filters_loop())  # Каждую минуту в :05 секунд
```

**Что происходит:**

```
11:30:05 → Проверка фильтров (читает старые данные)
11:31:00 → Парсинг НАЧАЛСЯ (обновляет БД...)
11:31:05 → Проверка фильтров (читает ЧАСТИЧНО обновленные данные!) ❌
11:32:05 → Проверка фильтров (читает ЧАСТИЧНО обновленные данные!) ❌
11:33:05 → Проверка фильтров (читает ЧАСТИЧНО обновленные данные!) ❌
11:35:00 → Парсинг ЗАКОНЧИЛСЯ
11:35:05 → Проверка фильтров (данные полные) ✅
```

**Последствия:**

1. **Несогласованность данных** - в БД часть символов обновлена, часть нет
2. **Проверка работает с разновременными данными** - сравниваются старые и новые свечи одновременно
3. **Database locks** - SQLite не любит одновременную запись/чтение
4. **Сложность отладки** - трудно понять какие данные использовались

### ✅ Решение: Последовательное выполнение

**Вариант 1: Проверка ТОЛЬКО после парсинга (РЕКОМЕНДУЕТСЯ)**

```python
async def start():
    # Один главный цикл
    asyncio.create_task(_main_loop())
    # Очистка отдельно (не конфликтует)
    asyncio.create_task(_cleanup_loop())

async def _main_loop():
    """Главный цикл: парсинг → ожидание → проверка → сон"""
    while running:
        logger.info("=" * 60)
        logger.info("Starting new cycle")
        
        # 1. Парсим данные с биржи
        logger.info("Step 1: Parsing market data...")
        await _parse_market_data()
        logger.info("Step 1: Parsing complete")
        
        # 2. Ждём 5 секунд (гарантия что всё записалось в БД)
        await asyncio.sleep(5)
        
        # 3. Проверяем фильтры
        logger.info("Step 2: Checking filters...")
        await _check_filters()
        logger.info("Step 2: Check complete")
        
        # 4. Спим до следующего цикла
        logger.info(f"Sleeping for {PARSE_INTERVAL_MINUTES} minutes...")
        await asyncio.sleep(PARSE_INTERVAL_MINUTES * 60)
```

**Преимущества:**
- ✅ Никогда не читаем неполные данные
- ✅ Гарантия согласованности
- ✅ Проще отлаживать
- ✅ Меньше нагрузка на API биржи
- ✅ Нет race conditions
- ✅ Нет database locks

**Недостаток:**
- ❌ Реже проверяет (раз в 5 минут вместо раз в минуту)

**Почему это приемлемо:**
- Фильтры настроены на интервалы 5-30 минут
- Разница между проверкой раз в минуту vs раз в 5 минут несущественна
- Корректность данных важнее частоты проверки

### Конфигурация

```python
# backend/config.py
class Settings(BaseSettings):
    # Интервал парсинга данных с биржи (в минутах)
    PARSE_INTERVAL_MINUTES: int = 5
    
    # Старый параметр CHECK_INTERVAL_SECONDS больше не используется
    # Проверка фильтров происходит сразу после парсинга
```

### Timeline работы системы

```
00:00 → Парсинг (0-4 минуты)
00:04 → Ожидание (5 секунд)
00:04:05 → Проверка фильтров (1-2 секунды)
00:04:07 → Сон (до 00:05:00)

00:05:00 → Парсинг (0-4 минуты)
00:09:00 → Ожидание (5 секунд)
00:09:05 → Проверка фильтров (1-2 секунды)
00:09:07 → Сон (до 00:10:00)

...и так далее каждые 5 минут
```

---

## 2. Правильный расчёт всплеска объёмов

### Описание проблемы

**Текущий алгоритм (НЕПРАВИЛЬНЫЙ):**

```python
# Берём ВСЕ 120 минут (включая последние 10)
candles = await db.get_candles(symbol, market, base_period_minutes=120)

# Считаем средний объём
num_intervals = len(candles) // short_period  # 120 / 10 = 12
total_volume = sum(candle['volume'] for candle in candles)  # ❌ Все 120!
avg_volume = total_volume / num_intervals

# Берём текущий объём
recent_candles = candles[-short_period:]  # Последние 10 минут
current_volume = sum(candle['volume'] for candle in recent_candles)

# Сравниваем
coefficient = current_volume / avg_volume  # ❌ НЕПРАВИЛЬНО!
```

**В чём проблема:**

Последние 10 минут (текущий период) **УЖЕ ВХОДЯТ** в базовый период 120 минут!

```
Базовый период (120 минут):
┌────────────────────────────────────────────────────┐
│ 11:22 → 11:23 → ... → 12:30 → 12:31 → [12:32-12:41]│
│                                        └───────────┘│
│                                      Это УЖЕ здесь! │
└────────────────────────────────────────────────────┘
                                            ↓
                                    Берётся ЕЩЁ РАЗ!
```

**Результат:** Всплеск "размазывается" по истории, коэффициент занижается.

### Пример с числами

**Реальная ситуация:**
```
11:22-11:31 (10 мин): $100
11:32-11:41 (10 мин): $100
11:42-11:51 (10 мин): $100
...
12:22-12:31 (10 мин): $100
12:32-12:41 (10 мин): $500  ← ВСПЛЕСК!
```

**Неправильный расчёт (текущий):**
```python
# Суммарный объём за все 120 минут (включая всплеск)
total = 100×11 + 500 = 1,600

# Средний
avg = 1,600 / 12 = 133.33

# Текущий
current = 500

# Коэффициент
coefficient = 500 / 133.33 = 3.75x  ❌ ЗАНИЖЕН!
```

**Правильный расчёт:**
```python
# Суммарный объём за 110 минут (БЕЗ последних 10)
total = 100 × 11 = 1,100

# Средний
avg = 1,100 / 11 = 100

# Текущий
current = 500

# Коэффициент
coefficient = 500 / 100 = 5.0x  ✅ ПРАВИЛЬНО!
```

### ✅ Решение: Исключить текущий период из среднего

```python
async def check_volume_spike_filter(
    symbol: str,
    market: str,
    filter_config: dict
) -> Optional[dict]:
    """
    Проверка фильтра "Всплеск объёмов"
    
    ВАЖНО: Текущий период НЕ включается в расчёт среднего!
    """
    
    # Параметры
    base_period_minutes = filter_config['base_period_minutes']    # 120
    short_period_minutes = filter_config['short_period_minutes']  # 10
    spike_coefficient = filter_config['spike_coefficient']        # 5.0
    
    # 1. Получаем все свечи за базовый период
    candles = await db.get_candles(symbol, market, base_period_minutes)
    
    if len(candles) < base_period_minutes:
        logger.debug(f"{symbol}: Not enough candles ({len(candles)} < {base_period_minutes})")
        return None
    
    # 2. РАЗДЕЛЯЕМ на исторические и текущие
    historical_candles = candles[:-short_period_minutes]  # Первые 110 минут
    recent_candles = candles[-short_period_minutes:]      # Последние 10 минут
    
    if len(recent_candles) < short_period_minutes:
        logger.debug(f"{symbol}: Not enough recent candles ({len(recent_candles)})")
        return None
    
    # 3. Вычисляем средний объём ТОЛЬКО по историческим данным
    num_intervals = len(historical_candles) // short_period_minutes
    
    if num_intervals < 1:
        logger.debug(f"{symbol}: Not enough intervals ({num_intervals})")
        return None
    
    total_historical_volume = sum(candle['volume'] for candle in historical_candles)
    avg_volume_per_interval = total_historical_volume / num_intervals
    
    if avg_volume_per_interval == 0:
        logger.debug(f"{symbol}: Average volume is zero")
        return None
    
    # 4. Вычисляем текущий объём
    current_volume = sum(candle['volume'] for candle in recent_candles)
    
    # 5. Вычисляем коэффициент всплеска
    actual_coefficient = current_volume / avg_volume_per_interval
    
    logger.debug(
        f"{symbol}: Volume spike check - "
        f"current={current_volume:.2f}, "
        f"avg={avg_volume_per_interval:.2f}, "
        f"coefficient={actual_coefficient:.2f}x "
        f"(need {spike_coefficient}x)"
    )
    
    if actual_coefficient < spike_coefficient:
        return None
    
    # 6. Остальные проверки (цена, объём 24ч, исключения...)
    # ...
    
    return {
        'spike_coefficient': round(actual_coefficient, 2),
        'current_volume': round(current_volume, 2),
        'avg_volume': round(avg_volume_per_interval, 2),
        'price_change_percent': ...,
        'volume_24h': ...,
        'url': ...
    }
```

### Визуализация

**БЫЛО (неправильно):**
```
      Средний = (ВСЕ 120 минут включая всплеск) / 12
      ↓
┌──────────────────────────────────────────────┐
│ $100│$100│$100│...(9 раз)...│$100│ $500    │
│                                      ↑       │
│                                  ВСПЛЕСК    │
└──────────────────────────────────────────────┘
         ↓
    Сумма: $1,600
    Средний: $133.33
    Коэффициент: 500/133.33 = 3.75x  ❌
```

**СТАЛО (правильно):**
```
    Средний = (110 минут БЕЗ всплеска) / 11
    ↓
┌────────────────────────────────┐   ┌──────┐
│ $100│$100│...(9 раз)...│$100  │   │ $500 │
│                                │   │  ↑   │
│      ИСТОРИЧЕСКИЕ ДАННЫЕ       │   │ТЕКУЩИЙ│
└────────────────────────────────┘   └──────┘
    ↓                                    ↓
Сумма: $1,100                        $500
Средний: $100
    
Коэффициент: 500/100 = 5.0x  ✅
```

### Последствия исправления

**Если НЕ исправить:**
- ❌ Всплеск "размазывается" по истории
- ❌ Коэффициент занижается (3.75x вместо 5.0x)
- ❌ Пропускаются реальные всплески (если порог 5x)
- ❌ Возможны ложные срабатывания

**После исправления:**
- ✅ Точный расчёт коэффициента
- ✅ Правильное обнаружение всплесков
- ✅ Соответствие математическому определению

---

## 3. Использование quoteVolume вместо volume

### Описание проблемы

**В CCXT существует два типа объёма:**

1. **`volume`** (базовая валюта) - объём в первой валюте пары
   - Для BTC/USDT: объём в BTC
   - Для ETH/USDT: объём в ETH
   - Для SOL/USDT: объём в SOL

2. **`quoteVolume`** (котируемая валюта) - объём в USD/USDT
   - Для всех пар: объём в USDT

**Проблема "яблок с апельсинами":**

```python
# Если сравнивать volume (базовая валюта)
BTC/USDT:  0.5 BTC   ← Какой это объём в USD?
SOL/USDT:  100 SOL   ← Какой это объём в USD?

# Невозможно сравнить напрямую!
```

**Правильно сравнивать в единой валюте (USDT):**

```python
# quoteVolume (котируемая валюта)
BTC/USDT:  $45,000 USDT  ← Можно сравнивать
SOL/USDT:  $13,500 USDT  ← Можно сравнивать
```

### Где используется объём

**В фильтрах:**

1. **"Изменение цены":**
   - `min_volume_period` - минимальный объём за интервал
   - `max_volume_period` - максимальный объём за интервал
   - `min_volume_24h` - минимальный объём за 24 часа
   - `max_volume_24h` - максимальный объём за 24 часа

2. **"Всплеск объёмов":**
   - Сравнение текущего объёма со средним
   - `min_volume_24h` / `max_volume_24h`

**Все эти значения должны быть в USDT!**

### ✅ Решение: Использовать quoteVolume при парсинге

```python
async def _parse_market_data():
    """Парсинг данных с биржи"""
    
    # Получаем тикеры
    tickers = await exchange.fetch_tickers()
    
    for symbol, ticker in tickers.items():
        # ВАЖНО: Сохраняем quoteVolume (в USDT)
        volume_24h = ticker.get('quoteVolume', 0)  # ✅ USDT
        # НЕ использовать:
        # volume_24h = ticker.get('baseVolume', 0)  # ❌ BTC/ETH/SOL
        
        await db.save_ticker(
            symbol=symbol,
            market=market,
            volume_24h=volume_24h,  # В USDT!
            last_price=ticker['last']
        )
    
    # Получаем свечи
    for symbol in symbols:
        candles = await exchange.fetch_ohlcv(symbol, '1m', limit=120)
        
        for candle in candles:
            timestamp = int(candle[0] / 1000)  # Миллисекунды → секунды
            open_price = candle[1]
            high = candle[2]
            low = candle[3]
            close = candle[4]
            
            # ВАЖНО: Объём свечи в USDT
            # Вариант 1: Если CCXT возвращает quoteVolume (индекс 6)
            volume = candle[6] if len(candle) > 6 else None
            
            # Вариант 2: Если нет quoteVolume - вычисляем
            if volume is None:
                base_volume = candle[5]  # Объём в базовой валюте
                volume = base_volume * close  # Конвертируем в USDT
            
            await db.save_candle(
                symbol=symbol,
                market=market,
                timestamp=timestamp,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume  # В USDT!
            )
```

### Проверка корректности

**При отладке:**

```python
# Проверить что объёмы в USDT
candles = await db.get_candles('BTC/USDT:USDT', 'futures', 15)

for candle in candles:
    print(f"Timestamp: {candle['timestamp']}")
    print(f"Close: ${candle['close']:,.2f}")
    print(f"Volume: ${candle['volume']:,.2f} USDT")  # Должно быть большое число
    print()

# Для BTC объём должен быть $1,000,000+ (не 10-20 BTC)
# Для SOL объём должен быть $50,000+ (не 500-1000 SOL)
```

**В логах при срабатывании:**

```
✅ TRIGGERED: SOL/USDT:USDT
   Price change: +7.3%
   Volume (15m): $245,000 USDT  ← Должно быть в USD!
   Volume (24h): $1,200,000 USDT
```

### Последствия ошибки

**Если используется baseVolume вместо quoteVolume:**

- ❌ Невозможно корректно сравнивать объёмы разных монет
- ❌ Фильтры по `min_volume_period` работают неправильно
- ❌ Фильтры по `min_volume_24h` работают неправильно
- ❌ Коэффициент всплеска вычисляется некорректно
- ❌ Пользователь не может адекватно настроить пороги

**После исправления:**

- ✅ Все объёмы в единой валюте (USDT)
- ✅ Корректное сравнение между монетами
- ✅ Понятные настройки для пользователя
- ✅ Точная работа фильтров

---

## 4. Детальное логирование для отладки

### Описание проблемы

**Текущее состояние (предположительно):**

```python
# Минимальное логирование
async def check_price_change_filter(symbol, market, config):
    candles = await db.get_candles(...)
    if len(candles) < 2:
        return None  # ← Почему не сработал? Неизвестно!
    
    change = calculate_change(candles)
    if abs(change) < min_change:
        return None  # ← Какое было изменение? Неизвестно!
    
    volume = calculate_volume(candles)
    if volume < min_volume:
        return None  # ← Какой был объём? Неизвестно!
    
    return result
```

**Проблемы:**
- ❌ Невозможно понять почему фильтр НЕ сработал
- ❌ Нет промежуточных значений для отладки
- ❌ Сложно найти ошибки в логике
- ❌ Невозможно настроить пороги без данных

### ✅ Решение: Структурированное логирование с уровнями

#### 1. Уровни логирования

```python
import logging
from datetime import datetime

# Настройка логгера
logger = logging.getLogger(__name__)

# Уровни:
# DEBUG   - детальная информация для отладки (все проверки, вычисления)
# INFO    - важные события (срабатывания, начало/конец циклов)
# WARNING - проблемы, которые не критичны (мало данных, API ошибки)
# ERROR   - критические ошибки (исключения, недоступность БД)
```

#### 2. Что логировать в фильтре "Изменение цены"

```python
async def check_price_change_filter(
    symbol: str,
    market: str,
    filter_config: dict,
    filter_name: str
) -> Optional[dict]:
    """
    Проверка фильтра "Изменение цены" с детальным логированием
    """
    
    # Начало проверки (DEBUG уровень)
    logger.debug(
        f"[{filter_name}] Checking {symbol} ({market}): "
        f"interval={filter_config['interval_minutes']}m, "
        f"min_change={filter_config['min_price_change_percent']}%, "
        f"direction={filter_config['direction']}"
    )
    
    # 1. Получение свечей для цены
    interval_minutes = filter_config['interval_minutes']
    price_candles = await db.get_candles(symbol, market, interval_minutes)
    
    logger.debug(f"[{filter_name}] {symbol}: Got {len(price_candles)} price candles")
    
    if len(price_candles) < 2:
        logger.debug(
            f"[{filter_name}] {symbol}: ❌ Not enough price candles "
            f"(need 2, got {len(price_candles)})"
        )
        return None
    
    # 2. Вычисление изменения цены
    max_change_percent, price_from, price_to = calculate_max_price_change(
        price_candles,
        filter_config['direction']
    )
    
    logger.debug(
        f"[{filter_name}] {symbol}: Price change = {max_change_percent:+.2f}% "
        f"(${price_from:.8f} → ${price_to:.8f})"
    )
    
    # 3. Проверка минимального изменения
    min_change = filter_config['min_price_change_percent']
    
    if abs(max_change_percent) < min_change:
        logger.debug(
            f"[{filter_name}] {symbol}: ❌ Change too small "
            f"({abs(max_change_percent):.2f}% < {min_change}%)"
        )
        return None
    
    # 4. Получение свечей для объёма
    volume_interval = filter_config['volume_interval_minutes']
    volume_candles = await db.get_candles(symbol, market, volume_interval)
    
    logger.debug(f"[{filter_name}] {symbol}: Got {len(volume_candles)} volume candles")
    
    if len(volume_candles) < 1:
        logger.debug(f"[{filter_name}] {symbol}: ❌ Not enough volume candles")
        return None
    
    # 5. Вычисление объёма за период
    volume_period = sum(candle['volume'] for candle in volume_candles)
    
    logger.debug(
        f"[{filter_name}] {symbol}: Volume (period) = ${volume_period:,.2f}"
    )
    
    min_volume_period = filter_config['min_volume_period']
    max_volume_period = filter_config['max_volume_period']
    
    if volume_period < min_volume_period:
        logger.debug(
            f"[{filter_name}] {symbol}: ❌ Volume too low "
            f"(${volume_period:,.2f} < ${min_volume_period:,.2f})"
        )
        return None
    
    if volume_period > max_volume_period:
        logger.debug(
            f"[{filter_name}] {symbol}: ❌ Volume too high "
            f"(${volume_period:,.2f} > ${max_volume_period:,.2f})"
        )
        return None
    
    # 6. Проверка объёма 24ч
    ticker = await db.get_ticker(symbol, market)
    
    if not ticker:
        logger.warning(f"[{filter_name}] {symbol}: ⚠️ Ticker not found in DB")
        return None
    
    volume_24h = ticker['volume_24h']
    
    logger.debug(
        f"[{filter_name}] {symbol}: Volume (24h) = ${volume_24h:,.2f}"
    )
    
    min_volume_24h = filter_config['min_volume_24h']
    max_volume_24h = filter_config.get('max_volume_24h')
    
    if volume_24h < min_volume_24h:
        logger.debug(
            f"[{filter_name}] {symbol}: ❌ Volume 24h too low "
            f"(${volume_24h:,.2f} < ${min_volume_24h:,.2f})"
        )
        return None
    
    if max_volume_24h and volume_24h > max_volume_24h:
        logger.debug(
            f"[{filter_name}] {symbol}: ❌ Volume 24h too high "
            f"(${volume_24h:,.2f} > ${max_volume_24h:,.2f})"
        )
        return None
    
    # 7. Проверка исключений
    if is_excluded(symbol, filter_config['exclude_coins']):
        logger.debug(f"[{filter_name}] {symbol}: ❌ In exclusion list")
        return None
    
    # ✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!
    logger.info(
        f"[{filter_name}] {symbol}: ✅ TRIGGERED! "
        f"Change: {max_change_percent:+.2f}% "
        f"(${price_from:.8f} → ${price_to:.8f}), "
        f"Volume: ${volume_period:,.2f} ({volume_interval}m), "
        f"Volume 24h: ${volume_24h:,.2f}"
    )
    
    return {
        'price_change_percent': round(max_change_percent, 2),
        'price_from': round(price_from, 8),
        'price_to': round(price_to, 8),
        'volume_period': round(volume_period, 2),
        'volume_24h': round(volume_24h, 2),
        'url': get_exchange_url(symbol, market)
    }
```

#### 3. Логирование в основном цикле

```python
async def _main_loop():
    """Главный цикл с детальным логированием"""
    
    cycle_number = 0
    
    while running:
        cycle_number += 1
        cycle_start = time.time()
        
        logger.info("=" * 70)
        logger.info(f"Cycle #{cycle_number} started at {datetime.now()}")
        logger.info("=" * 70)
        
        # 1. Парсинг
        try:
            parse_start = time.time()
            logger.info("Step 1/3: Parsing market data...")
            
            symbols_parsed = await _parse_market_data()
            
            parse_duration = time.time() - parse_start
            logger.info(
                f"Step 1/3: Complete. "
                f"Parsed {symbols_parsed} symbols in {parse_duration:.1f}s"
            )
            
        except Exception as e:
            logger.error(f"Step 1/3: ERROR during parsing: {e}", exc_info=True)
            # Продолжаем работу
        
        # 2. Пауза
        await asyncio.sleep(5)
        
        # 3. Проверка фильтров
        try:
            check_start = time.time()
            logger.info("Step 2/3: Checking filters...")
            
            triggers_count = await _check_filters()
            
            check_duration = time.time() - check_start
            logger.info(
                f"Step 2/3: Complete. "
                f"Found {triggers_count} triggers in {check_duration:.1f}s"
            )
            
        except Exception as e:
            logger.error(f"Step 2/3: ERROR during check: {e}", exc_info=True)
        
        # 4. Итоги цикла
        cycle_duration = time.time() - cycle_start
        logger.info(f"Cycle #{cycle_number} completed in {cycle_duration:.1f}s")
        
        # 5. Сон
        sleep_time = PARSE_INTERVAL_MINUTES * 60
        logger.info(f"Sleeping for {sleep_time}s until next cycle...")
        logger.info("")
        
        await asyncio.sleep(sleep_time)
```

#### 4. Логирование ошибок API

```python
async def _parse_market_data():
    """Парсинг с обработкой ошибок"""
    
    try:
        # Получение тикеров
        logger.debug("Fetching tickers from exchange...")
        tickers = await exchange.fetch_tickers()
        logger.debug(f"Got {len(tickers)} tickers")
        
    except ccxt.NetworkError as e:
        logger.error(f"Network error fetching tickers: {e}")
        raise
        
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error fetching tickers: {e}")
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error fetching tickers: {e}", exc_info=True)
        raise
    
    # Сохранение в БД
    try:
        saved_count = 0
        for symbol, ticker in tickers.items():
            await db.save_ticker(symbol, market, ticker)
            saved_count += 1
        
        logger.debug(f"Saved {saved_count} tickers to database")
        
    except Exception as e:
        logger.error(f"Error saving tickers to DB: {e}", exc_info=True)
        raise
```

#### 5. Конфигурация логирования

```python
# backend/config.py
import logging
from logging.handlers import RotatingFileHandler
import sys

def setup_logging(log_level: str = "INFO", log_path: str = None):
    """
    Настройка системы логирования
    
    Args:
        log_level: DEBUG, INFO, WARNING, ERROR
        log_path: Путь к файлу логов (опционально)
    """
    
    # Формат логов
    log_format = (
        '%(asctime)s | %(levelname)-8s | '
        '%(name)s:%(funcName)s:%(lineno)d | '
        '%(message)s'
    )
    
    date_format = '%Y-%m-%d %H:%M:%S'
    
    formatter = logging.Formatter(log_format, date_format)
    
    # Корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Очистка существующих handlers
    root_logger.handlers.clear()
    
    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (если указан путь)
    if log_path:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,               # 5 файлов
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Отключаем избыточное логирование библиотек
    logging.getLogger('ccxt').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    
    logging.info(f"Logging configured: level={log_level}, path={log_path}")
```

### Куда собираются логи

#### В Docker контейнере:

**1. Stdout/Stderr (основной способ)**

```bash
# Просмотр логов в реальном времени
docker-compose logs -f backend

# Последние 100 строк
docker-compose logs backend --tail=100

# Только ошибки
docker-compose logs backend | grep ERROR

# Только срабатывания
docker-compose logs backend | grep "TRIGGERED"

# Логи за определённое время
docker-compose logs backend --since 2026-01-11T10:00:00
docker-compose logs backend --since 10m

# Сохранить логи в файл
docker-compose logs backend > backend_logs.txt
```

**2. Файл логов (в volume)**

```yaml
# docker-compose.yml
services:
  backend:
    volumes:
      - ./logs:/logs  # ← Здесь сохраняются файлы логов
```

```bash
# Доступ к файлу логов на хосте
tail -f ./logs/screener.log

# Последние 100 строк
tail -100 ./logs/screener.log

# Поиск по логам
grep "TRIGGERED" ./logs/screener.log

# Логи за сегодня
grep "2026-01-11" ./logs/screener.log
```

**3. Ротация логов**

Используется `RotatingFileHandler`:
- Максимальный размер файла: 10 MB
- Количество backup файлов: 5
- Итого: до 50 MB логов

```
logs/
├── screener.log       ← текущий файл
├── screener.log.1     ← предыдущий (самый свежий)
├── screener.log.2
├── screener.log.3
├── screener.log.4
└── screener.log.5     ← самый старый
```

### Примеры логов

#### При успешном срабатывании:

```
2026-01-11 14:32:05 | INFO     | screener.engine:_main_loop:45 | ======================================================================
2026-01-11 14:32:05 | INFO     | screener.engine:_main_loop:46 | Cycle #12 started at 2026-01-11 14:32:05
2026-01-11 14:32:05 | INFO     | screener.engine:_main_loop:47 | ======================================================================
2026-01-11 14:32:05 | INFO     | screener.engine:_main_loop:52 | Step 1/3: Parsing market data...
2026-01-11 14:36:42 | INFO     | screener.engine:_main_loop:58 | Step 1/3: Complete. Parsed 586 symbols in 277.3s
2026-01-11 14:36:47 | INFO     | screener.engine:_main_loop:68 | Step 2/3: Checking filters...
2026-01-11 14:36:47 | DEBUG    | screener.filters:check_price_change_filter:12 | [Рост 1%] Checking SOL/USDT:USDT (futures): interval=15m, min_change=1.0%, direction=up
2026-01-11 14:36:47 | DEBUG    | screener.filters:check_price_change_filter:20 | [Рост 1%] SOL/USDT:USDT: Got 15 price candles
2026-01-11 14:36:47 | DEBUG    | screener.filters:check_price_change_filter:30 | [Рост 1%] SOL/USDT:USDT: Price change = +2.35% ($135.42 → $138.60)
2026-01-11 14:36:47 | DEBUG    | screener.filters:check_price_change_filter:50 | [Рост 1%] SOL/USDT:USDT: Volume (period) = $245,820.00
2026-01-11 14:36:47 | DEBUG    | screener.filters:check_price_change_filter:70 | [Рост 1%] SOL/USDT:USDT: Volume (24h) = $1,203,450.00
2026-01-11 14:36:47 | INFO     | screener.filters:check_price_change_filter:95 | [Рост 1%] SOL/USDT:USDT: ✅ TRIGGERED! Change: +2.35% ($135.42 → $138.60), Volume: $245,820.00 (15m), Volume 24h: $1,203,450.00
2026-01-11 14:36:48 | INFO     | screener.engine:_main_loop:75 | Step 2/3: Complete. Found 1 triggers in 0.8s
2026-01-11 14:36:48 | INFO     | screener.engine:_main_loop:83 | Cycle #12 completed in 283.1s
```

#### При отказе срабатывания:

```
2026-01-11 14:36:47 | DEBUG    | screener.filters:check_price_change_filter:12 | [Рост 1%] Checking BTC/USDT:USDT (futures): interval=15m, min_change=1.0%, direction=up
2026-01-11 14:36:47 | DEBUG    | screener.filters:check_price_change_filter:20 | [Рост 1%] BTC/USDT:USDT: Got 15 price candles
2026-01-11 14:36:47 | DEBUG    | screener.filters:check_price_change_filter:30 | [Рост 1%] BTC/USDT:USDT: Price change = +0.45% ($90,420.00 → $90,827.89)
2026-01-11 14:36:47 | DEBUG    | screener.filters:check_price_change_filter:38 | [Рост 1%] BTC/USDT:USDT: ❌ Change too small (0.45% < 1.0%)
```

#### При ошибке:

```
2026-01-11 14:32:05 | ERROR    | screener.exchange:_parse_market_data:123 | Network error fetching tickers: bybit HTTPSConnectionPool(host='api.bybit.com', port=443): Max retries exceeded
2026-01-11 14:32:05 | ERROR    | screener.engine:_main_loop:61 | Step 1/3: ERROR during parsing: Network error
Traceback (most recent call last):
  File "backend/screener/engine.py", line 58, in _main_loop
    symbols_parsed = await _parse_market_data()
  ...
ccxt.NetworkError: bybit HTTPSConnectionPool...
```

### Уровни логирования для разных сценариев

**Продакшн (рабочая система):**
```bash
LOG_LEVEL=INFO  # Только важные события и срабатывания
```

**Отладка фильтров:**
```bash
LOG_LEVEL=DEBUG  # Все детали проверок и вычислений
```

**Минимум (только ошибки):**
```bash
LOG_LEVEL=ERROR  # Только критические проблемы
```

### Мониторинг логов

**1. Проверка что система работает:**
```bash
# Должны быть регулярные "Cycle #N completed"
docker-compose logs backend | grep "Cycle.*completed" | tail -5
```

**2. Поиск ошибок:**
```bash
# Все ошибки за последние 24 часа
docker-compose logs backend --since 24h | grep ERROR
```

**3. Статистика срабатываний:**
```bash
# Сколько срабатываний сегодня
docker-compose logs backend --since today | grep "TRIGGERED" | wc -l

# Какие символы срабатывали
docker-compose logs backend | grep "TRIGGERED" | grep -oP '\w+/USDT:\w+' | sort | uniq -c
```

**4. Производительность:**
```bash
# Время парсинга
docker-compose logs backend | grep "Parsed.*symbols in" | tail -10

# Время проверки фильтров
docker-compose logs backend | grep "Found.*triggers in" | tail -10
```

---

## 5. Надёжный парсинг данных с биржи (обработка VPN/сетевых проблем)

### Описание проблемы

**Частые сценарии сбоев:**

1. **VPN отключился** - нет доступа к api.bybit.com
2. **Timeout** - биржа не отвечает в течение 30 секунд
3. **Rate limiting** - слишком много запросов
4. **Частичные данные** - часть символов загрузилась, часть нет
5. **Неправильный формат данных** - биржа вернула неожиданный ответ

**Текущее поведение (вероятно):**

```python
# При ошибке весь парсинг падает
tickers = await exchange.fetch_tickers()  # ← Упало!
# Ничего не сохранилось в БД
# Проверка фильтров работает со старыми данными
```

**Последствия:**
- ❌ Потеря данных за целый цикл (5 минут)
- ❌ Невозможно понять какой именно символ/запрос упал
- ❌ Нет retry механизма
- ❌ Сложно диагностировать VPN проблемы

### ✅ Решение: Retry + детальное логирование + graceful degradation

#### 1. Обёртка для retry логики

```python
import asyncio
from functools import wraps
from typing import Optional, Callable, Any
import ccxt

def retry_on_network_error(
    max_attempts: int = 3,
    delay_seconds: float = 5.0,
    backoff_multiplier: float = 2.0
):
    """
    Декоратор для повторных попыток при сетевых ошибках
    
    Args:
        max_attempts: Максимум попыток (3 по умолчанию)
        delay_seconds: Задержка между попытками (5 сек)
        backoff_multiplier: Множитель для экспоненциального backoff (2x)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            delay = delay_seconds
            
            for attempt in range(1, max_attempts + 1):
                try:
                    logger.debug(
                        f"{func.__name__}: Attempt {attempt}/{max_attempts}"
                    )
                    
                    result = await func(*args, **kwargs)
                    
                    if attempt > 1:
                        logger.info(
                            f"{func.__name__}: ✅ Success on attempt {attempt}"
                        )
                    
                    return result
                    
                except ccxt.NetworkError as e:
                    last_exception = e
                    logger.warning(
                        f"{func.__name__}: ⚠️ Network error on attempt {attempt}: {e}"
                    )
                    
                    if attempt < max_attempts:
                        logger.info(f"Retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                        delay *= backoff_multiplier
                    else:
                        logger.error(
                            f"{func.__name__}: ❌ Failed after {max_attempts} attempts"
                        )
                        raise
                
                except ccxt.ExchangeError as e:
                    # Rate limit, invalid request - не retry
                    logger.error(f"{func.__name__}: ❌ Exchange error: {e}")
                    raise
                
                except Exception as e:
                    logger.error(
                        f"{func.__name__}: ❌ Unexpected error: {e}",
                        exc_info=True
                    )
                    raise
            
            # Не должно сюда попасть, но на всякий случай
            raise last_exception
        
        return wrapper
    return decorator
```

#### 2. Парсинг тикеров с retry и детальным логированием

```python
@retry_on_network_error(max_attempts=3, delay_seconds=5.0)
async def fetch_tickers_from_exchange(market: str) -> dict:
    """
    Загрузка тикеров с биржи с retry
    
    Args:
        market: 'spot' или 'futures'
    
    Returns:
        dict: {symbol: ticker_data}
    
    Raises:
        ccxt.NetworkError: После всех попыток
        ccxt.ExchangeError: Ошибка биржи
    """
    logger.info(f"Fetching tickers for {market} market...")
    
    start_time = time.time()
    
    try:
        # Настройка опций для конкретного рынка
        if market == 'spot':
            tickers = await exchange.fetch_tickers()
        else:  # futures
            tickers = await exchange.fetch_tickers({'type': 'future'})
        
        duration = time.time() - start_time
        
        logger.info(
            f"✅ Fetched {len(tickers)} {market} tickers in {duration:.1f}s"
        )
        
        return tickers
    
    except ccxt.NetworkError as e:
        duration = time.time() - start_time
        logger.error(
            f"❌ Network error fetching {market} tickers after {duration:.1f}s: {e}"
        )
        logger.error("💡 Hint: Check VPN connection and internet access")
        raise
    
    except ccxt.ExchangeError as e:
        logger.error(f"❌ Exchange error fetching {market} tickers: {e}")
        raise
    
    except Exception as e:
        logger.error(
            f"❌ Unexpected error fetching {market} tickers: {e}",
            exc_info=True
        )
        raise


async def save_tickers_to_db(
    tickers: dict,
    market: str
) -> tuple[int, int]:
    """
    Сохранение тикеров в БД с подсчётом успехов/ошибок
    
    Returns:
        (success_count, error_count)
    """
    logger.info(f"Saving {len(tickers)} {market} tickers to database...")
    
    success_count = 0
    error_count = 0
    
    for symbol, ticker in tickers.items():
        try:
            # Валидация данных
            if not ticker or 'last' not in ticker:
                logger.debug(f"{symbol}: ⚠️ Missing 'last' price, skipping")
                error_count += 1
                continue
            
            # ВАЖНО: Используем quoteVolume!
            volume_24h = ticker.get('quoteVolume', 0)
            
            if volume_24h is None or volume_24h < 0:
                logger.debug(
                    f"{symbol}: ⚠️ Invalid volume_24h ({volume_24h}), "
                    f"using 0"
                )
                volume_24h = 0
            
            last_price = ticker['last']
            
            if last_price is None or last_price <= 0:
                logger.debug(
                    f"{symbol}: ⚠️ Invalid price ({last_price}), skipping"
                )
                error_count += 1
                continue
            
            # Сохранение
            await db.save_ticker(
                symbol=symbol,
                market=market,
                volume_24h=volume_24h,
                last_price=last_price
            )
            
            success_count += 1
            
        except Exception as e:
            logger.warning(
                f"{symbol}: ⚠️ Error saving ticker: {e}"
            )
            error_count += 1
    
    logger.info(
        f"✅ Saved {success_count}/{len(tickers)} {market} tickers "
        f"({error_count} errors)"
    )
    
    return success_count, error_count
```

#### 3. Парсинг свечей с обработкой ошибок для каждого символа

```python
async def fetch_and_save_candles(
    symbol: str,
    market: str,
    limit: int = 120
) -> bool:
    """
    Загрузка и сохранение свечей для одного символа
    
    Returns:
        True если успешно, False если ошибка
    """
    try:
        logger.debug(f"{symbol}: Fetching {limit} candles...")
        
        start_time = time.time()
        
        # Загрузка с биржи
        candles = await exchange.fetch_ohlcv(
            symbol,
            timeframe='1m',
            limit=limit
        )
        
        duration = time.time() - start_time
        
        if not candles:
            logger.warning(
                f"{symbol}: ⚠️ No candles returned (empty response)"
            )
            return False
        
        logger.debug(
            f"{symbol}: Got {len(candles)} candles in {duration:.2f}s"
        )
        
        # Сохранение в БД
        saved_count = 0
        
        for candle in candles:
            try:
                timestamp = int(candle[0] / 1000)  # ms → s
                open_price = candle[1]
                high = candle[2]
                low = candle[3]
                close = candle[4]
                
                # ВАЖНО: quoteVolume или вычисление
                volume = candle[6] if len(candle) > 6 else None
                if volume is None:
                    base_volume = candle[5]
                    volume = base_volume * close  # Конвертация в USDT
                
                # Валидация
                if close <= 0 or volume < 0:
                    logger.debug(
                        f"{symbol}: Invalid candle at {timestamp}: "
                        f"close={close}, volume={volume}"
                    )
                    continue
                
                await db.save_candle(
                    symbol=symbol,
                    market=market,
                    timestamp=timestamp,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume
                )
                
                saved_count += 1
                
            except Exception as e:
                logger.debug(
                    f"{symbol}: Error saving candle {candle[0]}: {e}"
                )
        
        if saved_count < len(candles) * 0.8:  # Если < 80% сохранилось
            logger.warning(
                f"{symbol}: ⚠️ Only {saved_count}/{len(candles)} "
                f"candles saved"
            )
        
        return saved_count > 0
    
    except ccxt.NetworkError as e:
        logger.warning(f"{symbol}: ⚠️ Network error fetching candles: {e}")
        return False
    
    except ccxt.ExchangeError as e:
        logger.warning(f"{symbol}: ⚠️ Exchange error fetching candles: {e}")
        return False
    
    except Exception as e:
        logger.warning(
            f"{symbol}: ⚠️ Unexpected error fetching candles: {e}"
        )
        return False


async def fetch_candles_for_all_symbols(
    symbols: list[str],
    market: str,
    max_concurrent: int = 10
) -> tuple[int, int]:
    """
    Загрузка свечей для всех символов с ограничением конкурентности
    
    Args:
        symbols: Список символов
        market: 'spot' или 'futures'
        max_concurrent: Макс. одновременных запросов
    
    Returns:
        (success_count, error_count)
    """
    logger.info(
        f"Fetching candles for {len(symbols)} {market} symbols "
        f"(max {max_concurrent} concurrent)..."
    )
    
    start_time = time.time()
    
    success_count = 0
    error_count = 0
    
    # Разбиваем на батчи для контроля конкурентности
    for i in range(0, len(symbols), max_concurrent):
        batch = symbols[i:i + max_concurrent]
        batch_num = i // max_concurrent + 1
        total_batches = (len(symbols) + max_concurrent - 1) // max_concurrent
        
        logger.debug(
            f"Processing batch {batch_num}/{total_batches} "
            f"({len(batch)} symbols)..."
        )
        
        # Запускаем батч параллельно
        tasks = [
            fetch_and_save_candles(symbol, market)
            for symbol in batch
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        # Подсчёт результатов
        batch_success = sum(1 for r in results if r is True)
        batch_errors = len(results) - batch_success
        
        success_count += batch_success
        error_count += batch_errors
        
        logger.debug(
            f"Batch {batch_num}/{total_batches}: "
            f"{batch_success} success, {batch_errors} errors"
        )
        
        # Небольшая задержка между батчами (rate limiting)
        if i + max_concurrent < len(symbols):
            await asyncio.sleep(1.0)
    
    duration = time.time() - start_time
    
    logger.info(
        f"✅ Candles fetched: {success_count}/{len(symbols)} symbols "
        f"in {duration:.1f}s ({error_count} errors)"
    )
    
    return success_count, error_count
```

#### 4. Главная функция парсинга с агрегацией статистики

```python
async def _parse_market_data() -> dict:
    """
    Парсинг данных с биржи с детальной статистикой
    
    Returns:
        dict: Статистика парсинга
    """
    logger.info("=" * 70)
    logger.info("PARSING: Starting data collection from exchange")
    logger.info("=" * 70)
    
    overall_start = time.time()
    
    stats = {
        'markets_parsed': [],
        'total_tickers': 0,
        'total_symbols': 0,
        'ticker_errors': 0,
        'candle_success': 0,
        'candle_errors': 0,
        'duration_seconds': 0,
        'errors': []
    }
    
    # Определяем какие рынки парсить
    markets_to_parse = []
    if settings.parse_spot:
        markets_to_parse.append('spot')
    if settings.parse_futures:
        markets_to_parse.append('futures')
    
    if not markets_to_parse:
        logger.warning("⚠️ No markets enabled for parsing!")
        return stats
    
    logger.info(f"Markets to parse: {', '.join(markets_to_parse)}")
    
    # Парсим каждый рынок
    for market in markets_to_parse:
        logger.info(f"--- Processing {market.upper()} market ---")
        market_start = time.time()
        
        try:
            # 1. Загрузка тикеров
            tickers = await fetch_tickers_from_exchange(market)
            
            # 2. Сохранение тикеров
            ticker_success, ticker_errors = await save_tickers_to_db(
                tickers,
                market
            )
            
            stats['total_tickers'] += len(tickers)
            stats['ticker_errors'] += ticker_errors
            
            # 3. Получаем список символов для загрузки свечей
            symbols = list(tickers.keys())
            
            # Фильтруем только USDT пары
            usdt_symbols = [
                s for s in symbols
                if 'USDT' in s and '/USD:' not in s  # Исключаем инверсные
            ]
            
            logger.info(
                f"{market}: Filtered {len(usdt_symbols)}/{len(symbols)} "
                f"USDT symbols"
            )
            
            stats['total_symbols'] += len(usdt_symbols)
            
            # 4. Загрузка свечей
            if usdt_symbols:
                candle_success, candle_errors = \
                    await fetch_candles_for_all_symbols(
                        usdt_symbols,
                        market,
                        max_concurrent=10  # Настраиваемо
                    )
                
                stats['candle_success'] += candle_success
                stats['candle_errors'] += candle_errors
            
            market_duration = time.time() - market_start
            
            logger.info(
                f"{market}: ✅ Complete in {market_duration:.1f}s "
                f"(tickers: {ticker_success}/{len(tickers)}, "
                f"candles: {candle_success}/{len(usdt_symbols)})"
            )
            
            stats['markets_parsed'].append(market)
        
        except ccxt.NetworkError as e:
            error_msg = f"{market}: Network error - {e}"
            logger.error(f"❌ {error_msg}")
            logger.error("💡 Check VPN connection!")
            stats['errors'].append(error_msg)
            
            # Продолжаем со следующим рынком
            continue
        
        except Exception as e:
            error_msg = f"{market}: Unexpected error - {e}"
            logger.error(f"❌ {error_msg}", exc_info=True)
            stats['errors'].append(error_msg)
            
            # Продолжаем со следующим рынком
            continue
    
    # Финальная статистика
    overall_duration = time.time() - overall_start
    stats['duration_seconds'] = overall_duration
    
    logger.info("=" * 70)
    logger.info("PARSING: Summary")
    logger.info("=" * 70)
    logger.info(f"Markets parsed: {', '.join(stats['markets_parsed'])}")
    logger.info(f"Total tickers: {stats['total_tickers']}")
    logger.info(f"Total symbols: {stats['total_symbols']}")
    logger.info(
        f"Candles: {stats['candle_success']} success, "
        f"{stats['candle_errors']} errors"
    )
    logger.info(f"Duration: {overall_duration:.1f}s")
    
    if stats['errors']:
        logger.warning(f"⚠️ Errors encountered: {len(stats['errors'])}")
        for error in stats['errors']:
            logger.warning(f"  - {error}")
    else:
        logger.info("✅ No errors!")
    
    logger.info("=" * 70)
    
    return stats
```

#### 5. Проверка VPN и доступности биржи

```python
async def check_exchange_connectivity() -> bool:
    """
    Проверка доступности биржи перед парсингом
    
    Returns:
        True если биржа доступна
    """
    logger.info("Checking exchange connectivity...")
    
    try:
        # Простой запрос для проверки
        response = await exchange.fetch_status()
        
        if response and response.get('status') == 'ok':
            logger.info("✅ Exchange is accessible")
            return True
        else:
            logger.warning(f"⚠️ Exchange status: {response}")
            return False
    
    except ccxt.NetworkError as e:
        logger.error(f"❌ Cannot reach exchange: {e}")
        logger.error("💡 Possible causes:")
        logger.error("   1. VPN is disconnected")
        logger.error("   2. No internet connection")
        logger.error("   3. Exchange API is down")
        logger.error("   4. Firewall blocking access")
        return False
    
    except Exception as e:
        logger.error(f"❌ Error checking connectivity: {e}")
        return False


async def _main_loop_with_connectivity_check():
    """Главный цикл с проверкой доступности"""
    
    cycle_number = 0
    consecutive_failures = 0
    
    while running:
        cycle_number += 1
        
        logger.info("=" * 70)
        logger.info(f"Cycle #{cycle_number}")
        logger.info("=" * 70)
        
        # Проверяем доступность биржи
        if not await check_exchange_connectivity():
            consecutive_failures += 1
            
            logger.error(
                f"❌ Exchange not accessible "
                f"(failure #{consecutive_failures})"
            )
            
            if consecutive_failures >= 3:
                logger.error(
                    "❌ 3 consecutive failures! "
                    "Please check VPN and internet connection!"
                )
                # Отправить уведомление админу?
                # await send_admin_alert("Exchange connectivity lost")
            
            # Ждём дольше перед следующей попыткой
            wait_time = min(60 * consecutive_failures, 300)  # До 5 минут
            logger.info(f"Waiting {wait_time}s before retry...")
            await asyncio.sleep(wait_time)
            continue
        
        # Сброс счётчика при успехе
        if consecutive_failures > 0:
            logger.info(
                f"✅ Connection restored after {consecutive_failures} failures"
            )
            consecutive_failures = 0
        
        # Обычный цикл парсинга
        try:
            stats = await _parse_market_data()
            
            # Если было много ошибок - предупреждение
            error_rate = stats['candle_errors'] / max(stats['total_symbols'], 1)
            if error_rate > 0.2:  # Больше 20% ошибок
                logger.warning(
                    f"⚠️ High error rate: {error_rate*100:.1f}% "
                    f"({stats['candle_errors']}/{stats['total_symbols']})"
                )
                logger.warning("💡 This might indicate VPN or network issues")
        
        except Exception as e:
            logger.error(f"❌ Fatal error in parsing: {e}", exc_info=True)
            consecutive_failures += 1
        
        # Пауза перед проверкой фильтров
        await asyncio.sleep(5)
        
        # Проверка фильтров...
        # ...
        
        # Сон до следующего цикла
        await asyncio.sleep(PARSE_INTERVAL_MINUTES * 60)
```

### Примеры логов при проблемах

#### Проблема с VPN:

```
2026-01-11 14:32:05 | INFO     | Checking exchange connectivity...
2026-01-11 14:32:35 | ERROR    | ❌ Cannot reach exchange: bybit HTTPSConnectionPool(host='api.bybit.com', port=443): Max retries exceeded with url: /v5/market/time
2026-01-11 14:32:35 | ERROR    | 💡 Possible causes:
2026-01-11 14:32:35 | ERROR    |    1. VPN is disconnected
2026-01-11 14:32:35 | ERROR    |    2. No internet connection
2026-01-11 14:32:35 | ERROR    |    3. Exchange API is down
2026-01-11 14:32:35 | ERROR    |    4. Firewall blocking access
2026-01-11 14:32:35 | ERROR    | ❌ Exchange not accessible (failure #1)
2026-01-11 14:32:35 | INFO     | Waiting 60s before retry...
```

#### Частичные ошибки при парсинге:

```
2026-01-11 14:37:22 | INFO     | Fetching candles for 586 futures symbols (max 10 concurrent)...
2026-01-11 14:37:23 | DEBUG    | Processing batch 1/59 (10 symbols)...
2026-01-11 14:37:25 | WARNING  | SOL/USDT:USDT: ⚠️ Network error fetching candles: Request Timeout
2026-01-11 14:37:27 | WARNING  | APT/USDT:USDT: ⚠️ Network error fetching candles: Request Timeout
2026-01-11 14:37:28 | DEBUG    | Batch 1/59: 8 success, 2 errors
2026-01-11 14:41:50 | INFO     | ✅ Candles fetched: 570/586 symbols in 268.3s (16 errors)
2026-01-11 14:41:50 | WARNING  | ⚠️ High error rate: 2.7% (16/586)
2026-01-11 14:41:50 | WARNING  | 💡 This might indicate VPN or network issues
```

#### Успешный парсинг после retry:

```
2026-01-11 14:32:05 | INFO     | Fetching tickers for futures market...
2026-01-11 14:32:05 | DEBUG    | fetch_tickers_from_exchange: Attempt 1/3
2026-01-11 14:32:35 | WARNING  | fetch_tickers_from_exchange: ⚠️ Network error on attempt 1: Request Timeout
2026-01-11 14:32:35 | INFO     | Retrying in 5.0s...
2026-01-11 14:32:40 | DEBUG    | fetch_tickers_from_exchange: Attempt 2/3
2026-01-11 14:32:43 | INFO     | fetch_tickers_from_exchange: ✅ Success on attempt 2
2026-01-11 14:32:43 | INFO     | ✅ Fetched 586 futures tickers in 38.2s
```

### Мониторинг здоровья парсинга

```bash
# Проверка успешности парсинга
docker-compose logs backend | grep "PARSING: Summary" -A 10

# Проверка VPN проблем
docker-compose logs backend | grep "VPN\|Cannot reach exchange"

# Процент ошибок
docker-compose logs backend | grep "High error rate"

# Retry попытки
docker-compose logs backend | grep "Retrying in"

# Consecutive failures
docker-compose logs backend | grep "consecutive failures"
```

### Конфигурация

```python
# backend/config.py
class Settings(BaseSettings):
    # Retry настройки
    MAX_RETRY_ATTEMPTS: int = 3
    RETRY_DELAY_SECONDS: float = 5.0
    RETRY_BACKOFF_MULTIPLIER: float = 2.0
    
    # Парсинг настройки
    MAX_CONCURRENT_REQUESTS: int = 10  # Макс. параллельных запросов
    REQUEST_TIMEOUT_SECONDS: int = 30  # Timeout для запросов
    
    # Мониторинг
    MAX_CONSECUTIVE_FAILURES: int = 3  # Алерт после N провалов
```

---

## 6. WebSocket real-time обновления (звук + лента событий)

### Описание проблемы

**Текущее поведение:**
- ✅ Настройка звука есть в UI
- ❌ Лента событий НЕ обновляется автоматически
- ❌ Звуковые уведомления НЕ работают
- ❌ Нужно обновлять страницу вручную (F5)

**Причины:**

1. **WebSocket не подключен на клиенте** - соединение не устанавливается
2. **WebSocket подключен, но не слушает сообщения** - нет обработчика
3. **Backend не отправляет через WebSocket** - только в Telegram
4. **WebSocket обрывается и не переподключается** - ошибки соединения

### Диагностика

#### Проверка в браузере:

**1. Откройте DevTools (F12) → Console**

Должны быть сообщения:
```javascript
WebSocket connecting to ws://localhost:3000/ws/triggers
WebSocket connected
```

**2. Откройте DevTools → Network → WS (WebSocket)**

Должно быть:
- Соединение к `/ws/triggers`
- Status: `101 Switching Protocols`
- Messages: входящие сообщения при срабатывании

#### Проверка в логах backend:

```bash
docker-compose logs backend | grep -i websocket

# Должно быть:
# WebSocket client connected
# Broadcasting trigger to X clients
```

### ✅ Решение: Правильная реализация WebSocket

#### 1. Backend - WebSocket endpoint (проверить существующий)

```python
# backend/api/websocket.py
from fastapi import WebSocket, WebSocketDisconnect
from typing import Set
import logging
import json

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Менеджер WebSocket соединений"""
    
    def __init__(self):
        # Активные соединения
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        """Подключение нового клиента"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(
            f"WebSocket client connected. "
            f"Total clients: {len(self.active_connections)}"
        )
    
    def disconnect(self, websocket: WebSocket):
        """Отключение клиента"""
        self.active_connections.discard(websocket)
        logger.info(
            f"WebSocket client disconnected. "
            f"Total clients: {len(self.active_connections)}"
        )
    
    async def broadcast(self, message: dict):
        """
        Отправка сообщения всем подключённым клиентам
        
        Args:
            message: dict для сериализации в JSON
        """
        if not self.active_connections:
            logger.debug("No WebSocket clients to broadcast to")
            return
        
        logger.info(
            f"Broadcasting message to {len(self.active_connections)} clients"
        )
        
        # Отправляем всем клиентам
        disconnected = set()
        
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
                logger.debug(f"Message sent to client {id(connection)}")
                
            except Exception as e:
                logger.warning(
                    f"Failed to send to client {id(connection)}: {e}"
                )
                disconnected.add(connection)
        
        # Удаляем отключившихся
        for connection in disconnected:
            self.disconnect(connection)


# Глобальный менеджер
manager = ConnectionManager()


# WebSocket endpoint
@router.websocket("/ws/triggers")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint для real-time уведомлений о срабатываниях
    """
    await manager.connect(websocket)
    
    try:
        # Отправляем приветственное сообщение
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket connected successfully",
            "timestamp": int(time.time())
        })
        
        # Держим соединение открытым
        while True:
            # Ждём сообщений от клиента (ping/pong)
            data = await websocket.receive_text()
            
            # Обработка ping
            if data == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": int(time.time())
                })
            
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected normally")
        manager.disconnect(websocket)
        
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        manager.disconnect(websocket)


# Функция для отправки срабатывания
async def broadcast_trigger(trigger: dict):
    """
    Отправка срабатывания фильтра всем клиентам
    
    Args:
        trigger: Данные о срабатывании
    """
    message = {
        "type": "trigger",
        "filter_id": trigger['filter_id'],
        "filter_name": trigger['filter_name'],
        "symbol": trigger['symbol'],
        "market": trigger['market'],
        "data": trigger['data'],
        "timestamp": trigger['triggered_at']
    }
    
    await manager.broadcast(message)
```

#### 2. Backend - вызов broadcast при срабатывании

```python
# backend/screener/engine.py

async def _check_filters():
    """Проверка всех фильтров"""
    
    # ... получение фильтров и символов ...
    
    for filter in active_filters:
        for symbol in symbols:
            # Проверка фильтра
            result = await check_filter(filter, symbol)
            
            if result:
                # Проверка cooldown
                if not await check_cooldown(filter.id, symbol):
                    continue
                
                # Сохранение в БД
                trigger = await db.save_trigger(
                    filter_id=filter.id,
                    filter_name=filter.name,
                    symbol=symbol,
                    market=filter.market,
                    data=result
                )
                
                logger.info(
                    f"✅ Trigger saved: {filter.name} - {symbol}"
                )
                
                # 1. Telegram уведомление
                try:
                    await send_telegram_notification(trigger)
                except Exception as e:
                    logger.error(f"Telegram error: {e}")
                
                # 2. WebSocket broadcast ← ДОБАВИТЬ!
                try:
                    from backend.api.websocket import broadcast_trigger
                    await broadcast_trigger(trigger)
                    logger.info(f"WebSocket broadcast sent for {symbol}")
                except Exception as e:
                    logger.error(f"WebSocket broadcast error: {e}")
```

#### 3. Frontend - WebSocket клиент

```javascript
// frontend/js/websocket.js

class WebSocketClient {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000; // 1 секунда
        this.isManualClose = false;
        this.onTriggerCallback = null;
        this.soundEnabled = localStorage.getItem('soundEnabled') === 'true';
        
        // Загрузка звука
        this.notificationSound = new Audio('/sounds/notification.mp3');
        this.notificationSound.volume = 0.5;
    }
    
    connect() {
        // WebSocket URL (автоматически определяет протокол)
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/ws/triggers`;
        
        console.log('WebSocket connecting to:', wsUrl);
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            // Обработчики событий
            this.ws.onopen = this.onOpen.bind(this);
            this.ws.onmessage = this.onMessage.bind(this);
            this.ws.onclose = this.onClose.bind(this);
            this.ws.onerror = this.onError.bind(this);
            
        } catch (error) {
            console.error('WebSocket connection error:', error);
            this.scheduleReconnect();
        }
    }
    
    onOpen(event) {
        console.log('✅ WebSocket connected');
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        
        // Показать уведомление в UI
        this.showConnectionStatus('connected');
        
        // Запустить ping каждые 30 секунд
        this.startPing();
    }
    
    onMessage(event) {
        try {
            const message = JSON.parse(event.data);
            console.log('WebSocket message received:', message);
            
            switch (message.type) {
                case 'connected':
                    console.log('WebSocket handshake:', message.message);
                    break;
                
                case 'pong':
                    console.debug('Pong received');
                    break;
                
                case 'trigger':
                    // СРАБАТЫВАНИЕ ФИЛЬТРА!
                    this.handleTrigger(message);
                    break;
                
                default:
                    console.warn('Unknown message type:', message.type);
            }
            
        } catch (error) {
            console.error('Error parsing WebSocket message:', error);
        }
    }
    
    onClose(event) {
        console.log('WebSocket closed:', event.code, event.reason);
        
        this.showConnectionStatus('disconnected');
        
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
        }
        
        // Переподключение если не ручное закрытие
        if (!this.isManualClose) {
            this.scheduleReconnect();
        }
    }
    
    onError(event) {
        console.error('WebSocket error:', event);
        this.showConnectionStatus('error');
    }
    
    handleTrigger(message) {
        console.log('🔔 TRIGGER:', message);
        
        // 1. Воспроизвести звук
        if (this.soundEnabled) {
            this.playNotificationSound();
        }
        
        // 2. Показать браузерное уведомление
        this.showBrowserNotification(message);
        
        // 3. Добавить в ленту событий на странице
        if (this.onTriggerCallback) {
            this.onTriggerCallback(message);
        }
        
        // 4. Мигание favicon (опционально)
        this.flashFavicon();
    }
    
    playNotificationSound() {
        try {
            // Клонируем для множественных одновременных звуков
            const sound = this.notificationSound.cloneNode();
            sound.play().catch(e => {
                console.warn('Cannot play sound:', e);
                // Требуется user interaction для autoplay
            });
        } catch (error) {
            console.error('Error playing sound:', error);
        }
    }
    
    showBrowserNotification(message) {
        // Проверка поддержки
        if (!('Notification' in window)) {
            return;
        }
        
        // Запрос разрешения
        if (Notification.permission === 'default') {
            Notification.requestPermission();
            return;
        }
        
        // Показать уведомление
        if (Notification.permission === 'granted') {
            const { filter_name, symbol, data } = message;
            
            new Notification(`🔔 ${filter_name}`, {
                body: `${symbol}: ${data.price_change_percent > 0 ? '+' : ''}${data.price_change_percent}%`,
                icon: '/favicon.ico',
                badge: '/favicon.ico',
                tag: `trigger-${message.timestamp}`, // Группировка
                requireInteraction: false,
                silent: false
            });
        }
    }
    
    flashFavicon() {
        // Мигание favicon для привлечения внимания
        const link = document.querySelector("link[rel*='icon']");
        if (!link) return;
        
        const originalHref = link.href;
        link.href = '/favicon-alert.ico'; // Если есть альтернативная иконка
        
        setTimeout(() => {
            link.href = originalHref;
        }, 1000);
    }
    
    startPing() {
        // Ping каждые 30 секунд для keep-alive
        this.pingInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send('ping');
            }
        }, 30000);
    }
    
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('Max reconnect attempts reached');
            this.showConnectionStatus('failed');
            return;
        }
        
        this.reconnectAttempts++;
        
        console.log(
            `Reconnecting in ${this.reconnectDelay}ms ` +
            `(attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
        );
        
        setTimeout(() => {
            this.connect();
        }, this.reconnectDelay);
        
        // Exponential backoff
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
    }
    
    showConnectionStatus(status) {
        // Показать индикатор статуса в UI
        const indicator = document.getElementById('ws-status');
        if (!indicator) return;
        
        indicator.className = 'ws-status';
        
        switch (status) {
            case 'connected':
                indicator.classList.add('ws-connected');
                indicator.textContent = '● Connected';
                indicator.title = 'WebSocket connected - real-time updates active';
                break;
            
            case 'disconnected':
                indicator.classList.add('ws-disconnected');
                indicator.textContent = '○ Disconnected';
                indicator.title = 'WebSocket disconnected - reconnecting...';
                break;
            
            case 'error':
                indicator.classList.add('ws-error');
                indicator.textContent = '✕ Error';
                indicator.title = 'WebSocket error';
                break;
            
            case 'failed':
                indicator.classList.add('ws-failed');
                indicator.textContent = '✕ Failed';
                indicator.title = 'Cannot connect to WebSocket';
                break;
        }
    }
    
    setOnTriggerCallback(callback) {
        this.onTriggerCallback = callback;
    }
    
    setSoundEnabled(enabled) {
        this.soundEnabled = enabled;
        localStorage.setItem('soundEnabled', enabled);
    }
    
    disconnect() {
        this.isManualClose = true;
        if (this.ws) {
            this.ws.close();
        }
    }
}

// Глобальный экземпляр
window.wsClient = new WebSocketClient();
```

#### 4. Frontend - интеграция на странице истории

```javascript
// frontend/js/triggers.js (или где страница истории)

let currentPage = 1;
const itemsPerPage = 20;

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', async () => {
    // 1. Загрузить историю
    await loadTriggers();
    
    // 2. Подключить WebSocket
    connectWebSocket();
    
    // 3. Настроить обработчики
    setupEventHandlers();
});

function connectWebSocket() {
    // Подключаемся к WebSocket
    window.wsClient.connect();
    
    // Устанавливаем callback для новых срабатываний
    window.wsClient.setOnTriggerCallback((message) => {
        console.log('New trigger received via WebSocket:', message);
        
        // Добавить в начало ленты
        prependTriggerToList(message);
        
        // Показать toast уведомление
        showToast(`🔔 ${message.filter_name}: ${message.symbol}`);
    });
}

async function loadTriggers(page = 1) {
    try {
        const response = await fetch(
            `/api/triggers?limit=${itemsPerPage}&offset=${(page - 1) * itemsPerPage}`
        );
        
        if (!response.ok) {
            throw new Error('Failed to load triggers');
        }
        
        const data = await response.json();
        
        // Отобразить список
        renderTriggersList(data.items);
        
        // Пагинация
        renderPagination(data.total, page);
        
    } catch (error) {
        console.error('Error loading triggers:', error);
        showError('Failed to load triggers');
    }
}

function renderTriggersList(triggers) {
    const container = document.getElementById('triggers-list');
    
    if (!triggers || triggers.length === 0) {
        container.innerHTML = '<p class="text-gray-500">No triggers found</p>';
        return;
    }
    
    container.innerHTML = triggers.map(trigger => renderTriggerCard(trigger)).join('');
}

function renderTriggerCard(trigger) {
    const data = JSON.parse(trigger.data);
    const date = new Date(trigger.triggered_at * 1000);
    
    return `
        <div class="trigger-card" data-id="${trigger.id}">
            <div class="flex justify-between items-start">
                <div>
                    <h3 class="font-semibold">${trigger.filter_name}</h3>
                    <p class="text-sm text-gray-400">${trigger.symbol} • ${trigger.market}</p>
                </div>
                <span class="text-sm text-gray-500">${formatTime(date)}</span>
            </div>
            
            <div class="mt-2">
                <span class="text-lg ${data.price_change_percent > 0 ? 'text-green-500' : 'text-red-500'}">
                    ${data.price_change_percent > 0 ? '+' : ''}${data.price_change_percent}%
                </span>
                <span class="text-sm text-gray-400 ml-2">
                    $${data.price_from.toFixed(2)} → $${data.price_to.toFixed(2)}
                </span>
            </div>
            
            <div class="mt-1 text-sm text-gray-500">
                Volume: $${formatNumber(data.volume_period)}
            </div>
            
            <a href="${data.url}" target="_blank" class="text-purple-500 text-sm mt-2 inline-block">
                Open on Bybit →
            </a>
        </div>
    `;
}

function prependTriggerToList(message) {
    const container = document.getElementById('triggers-list');
    
    // Создаём новую карточку
    const trigger = {
        id: Date.now(), // Временный ID
        filter_name: message.filter_name,
        symbol: message.symbol,
        market: message.market,
        triggered_at: message.timestamp,
        data: JSON.stringify(message.data)
    };
    
    const card = renderTriggerCard(trigger);
    
    // Добавляем в начало с анимацией
    const temp = document.createElement('div');
    temp.innerHTML = card;
    const newCard = temp.firstElementChild;
    
    // Анимация появления
    newCard.style.opacity = '0';
    newCard.style.transform = 'translateY(-20px)';
    
    container.prepend(newCard);
    
    // Trigger reflow
    newCard.offsetHeight;
    
    // Анимация
    newCard.style.transition = 'all 0.3s ease';
    newCard.style.opacity = '1';
    newCard.style.transform = 'translateY(0)';
    
    // Удалить последнюю карточку если превысили лимит
    const cards = container.querySelectorAll('.trigger-card');
    if (cards.length > itemsPerPage) {
        cards[cards.length - 1].remove();
    }
}

function showToast(message) {
    // Показать временное уведомление
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    // Анимация
    setTimeout(() => toast.classList.add('show'), 10);
    
    // Удалить через 3 секунды
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function setupEventHandlers() {
    // Настройка звука
    const soundToggle = document.getElementById('sound-toggle');
    if (soundToggle) {
        soundToggle.checked = window.wsClient.soundEnabled;
        
        soundToggle.addEventListener('change', (e) => {
            window.wsClient.setSoundEnabled(e.target.checked);
        });
    }
}

// Отключение при уходе со страницы
window.addEventListener('beforeunload', () => {
    window.wsClient.disconnect();
});
```

#### 5. HTML - индикатор статуса WebSocket

```html
<!-- В header или навбаре -->
<div id="ws-status" class="ws-status ws-disconnected">
    ○ Connecting...
</div>

<!-- Звуковой файл -->
<audio id="notification-sound" preload="auto">
    <source src="/sounds/notification.mp3" type="audio/mpeg">
    <source src="/sounds/notification.ogg" type="audio/ogg">
</audio>
```

#### 6. CSS - стили для статуса и toast

```css
/* WebSocket status indicator */
.ws-status {
    position: fixed;
    top: 20px;
    right: 20px;
    padding: 8px 16px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    z-index: 1000;
    transition: all 0.3s ease;
}

.ws-connected {
    background: rgba(16, 185, 129, 0.2);
    color: #10b981;
    border: 1px solid #10b981;
}

.ws-disconnected {
    background: rgba(239, 68, 68, 0.2);
    color: #ef4444;
    border: 1px solid #ef4444;
}

.ws-error {
    background: rgba(245, 158, 11, 0.2);
    color: #f59e0b;
    border: 1px solid #f59e0b;
}

/* Toast notifications */
.toast {
    position: fixed;
    bottom: -100px;
    right: 20px;
    background: #252936;
    color: #e0e0e0;
    padding: 16px 24px;
    border-radius: 12px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
    z-index: 1001;
    transition: bottom 0.3s ease;
    max-width: 400px;
}

.toast.show {
    bottom: 20px;
}

/* Анимация новой карточки */
.trigger-card {
    transition: all 0.3s ease;
}

.trigger-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}
```

### Проверка работоспособности

#### 1. Проверить в DevTools Console:

```javascript
// Должны быть логи:
// "WebSocket connecting to: ws://localhost:3000/ws/triggers"
// "✅ WebSocket connected"
// "WebSocket handshake: WebSocket connected successfully"

// При срабатывании:
// "WebSocket message received: {type: 'trigger', ...}"
// "🔔 TRIGGER: {...}"
```

#### 2. Проверить в DevTools Network → WS:

- Соединение установлено
- Ping/Pong сообщения каждые 30 секунд
- Trigger сообщения при срабатываниях

#### 3. Проверить звук:

```javascript
// В консоли:
window.wsClient.playNotificationSound();
// Должен проиграться звук
```

#### 4. Проверить в логах backend:

```bash
docker-compose logs backend | grep -i websocket

# Должно быть:
# "WebSocket client connected. Total clients: 1"
# "Broadcasting message to 1 clients"
```

---

## 2. Выбор базы данных: SQLite vs PostgreSQL

### Текущая ситуация (SQLite)

**Что используется:**
- SQLite - файловая БД (`/data/screener.db`)
- Работает в том же процессе что и приложение
- Без отдельного сервера

**Плюсы SQLite для вашего случая:**

✅ **Простота** - zero configuration, один файл
✅ **Портативность** - легко бэкапить (`cp screener.db backup.db`)
✅ **Достаточная производительность** - до 100k записей в секунду
✅ **Низкие требования** - не нужна дополнительная RAM
✅ **Идеально для Docker** - файл в volume, всё работает
✅ **Транзакции ACID** - надёжность данных
✅ **Полнотекстовый поиск** - FTS5 если понадобится

**Ваша нагрузка:**
- ~600 символов
- Проверка раз в 5 минут = ~120 свечей × 600 = 72k записей
- История 30 дней ≈ 100k-500k триггеров
- **Это ЛЕГКО для SQLite!**

**Минусы SQLite:**
- ❌ Конкурентная запись (но у вас один writer - screener)
- ❌ Нет сетевого доступа (но не нужен)
- ❌ Нет репликации (но не нужна для single-server)
- ❌ Размер БД до ~140 TB (у вас будет < 1 GB)

### Когда НУЖЕН PostgreSQL:

🔴 **Множество одновременных писателей** - у вас один (screener)
🔴 **Сетевой доступ из разных сервисов** - у вас монолит
🔴 **Репликация** - у вас single server
🔴 **Партиционирование больших таблиц** - у вас < 1 GB данных
🔴 **Сложные запросы с JOIN** - у вас простые запросы
🔴 **Расширения (PostGIS, TimescaleDB)** - не нужны

### Когда ЗАХОЧЕТСЯ PostgreSQL:

**Сценарий 1: Множество пользователей**
```
Если каждый пользователь имеет свои фильтры:
- 100 пользователей
- По 10 фильтров каждый
- Одновременные изменения настроек
→ PostgreSQL лучше справится с конкурентностью
```

**Сценарий 2: Несколько серверов**
```
Если запускаете на разных серверах:
- Backend на сервере A
- Worker на сервере B
- Оба пишут в БД
→ Нужна сетевая БД (PostgreSQL)
```

**Сценарий 3: Аналитика**
```
Если хотите сложную аналитику:
- Корреляции между символами
- Machine learning модели
- Агрегации за годы
→ PostgreSQL + расширения
```

### 🎯 Вердикт для вашего проекта:

**ОСТАВАЙТЕСЬ НА SQLite!**

**Почему:**
1. Ваша нагрузка - это 0.1% от возможностей SQLite
2. Один writer (screener), много readers - идеально для SQLite
3. Упрощает деплой (нет отдельного сервиса БД)
4. Легко бэкапить и восстанавливать
5. Меньше RAM требуется

**Когда мигрировать на PostgreSQL:**
- Добавили multi-user систему (каждый свои фильтры)
- Запускаете несколько инстансов screener
- Нужна репликация для fault tolerance
- Данные > 50 GB
- Нужны сложные аналитические запросы

### Оптимизация SQLite (если нужно)

```python
# backend/screener/database.py

async def init_db():
    """Инициализация БД с оптимизациями"""
    
    # Подключение
    db = await aiosqlite.connect(settings.DB_PATH)
    
    # ОПТИМИЗАЦИИ для производительности
    
    # 1. WAL mode - позволяет одновременное чтение/запись
    await db.execute('PRAGMA journal_mode=WAL')
    
    # 2. Увеличиваем cache
    await db.execute('PRAGMA cache_size=-64000')  # 64 MB
    
    # 3. Temp в RAM для скорости
    await db.execute('PRAGMA temp_store=MEMORY')
    
    # 4. Синхронизация - баланс безопасность/скорость
    await db.execute('PRAGMA synchronous=NORMAL')
    
    # 5. Автовакуум для очистки
    await db.execute('PRAGMA auto_vacuum=INCREMENTAL')
    
    # 6. Busy timeout для конкурентности
    await db.execute('PRAGMA busy_timeout=5000')  # 5 секунд
    
    logger.info("Database initialized with optimizations")
    
    return db
```

---

## 7. Безопасное хранение секретов (.env файлы в Git)

### Описание проблемы

**Текущая ситуация:**
```bash
# .env файл содержит секреты:
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
```

**Опасности:**
- ❌ Нельзя коммитить в Git (утечка секретов)
- ❌ Сложно деплоить на новый сервер (нужно вручную переносить)
- ❌ Нет контроля версий конфигурации
- ❌ Каждый разработчик должен получать токены отдельно

### ❌ Плохие решения (НЕ ДЕЛАТЬ):

**1. Просто закоммитить .env**
```bash
git add .env
git commit -m "add config"  # ❌ ОЧЕНЬ ПЛОХО!
```
→ Токены навсегда в истории Git, даже если удалить файл!

**2. Зашифровать "домашним" способом**
```bash
openssl enc -aes-256-cbc -in .env -out .env.enc
git add .env.enc  # ❌ ПЛОХО!
```
→ Пароль всё равно нужно передавать, неудобно

**3. Хранить в коде**
```python
TELEGRAM_BOT_TOKEN = "123456789:ABC..."  # ❌ ОЧЕНЬ ПЛОХО!
```
→ Секреты в коде = утечка гарантирована

### ✅ Правильные решения

## Решение 1: Git + .gitignore + .env.example (РЕКОМЕНДУЕТСЯ для вашего случая)

**Суть:** Секреты НЕ в Git, только шаблон

### Шаг 1: Добавить .gitignore

```bash
# .gitignore
.env
.env.local
.env.production

# Но НЕ игнорировать пример
!.env.example
```

### Шаг 2: Создать .env.example (шаблон без секретов)

```bash
# .env.example
# Скопируйте этот файл в .env и заполните реальными значениями

# Telegram Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Screener Settings
CHECK_INTERVAL_SECONDS=60
COOLDOWN_MINUTES=15

# Markets
PARSE_SPOT=false
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

### Шаг 3: Добавить в README инструкцию

```markdown
## Первый запуск

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/your-username/crypto-screener.git
   cd crypto-screener
   ```

2. Создайте .env файл:
   ```bash
   cp .env.example .env
   ```

3. Отредактируйте .env и заполните секреты:
   ```bash
   nano .env
   # Или используйте любой редактор
   ```

4. Получите Telegram токены:
   - Bot Token: @BotFather в Telegram
   - Chat ID: @userinfobot или https://api.telegram.org/bot<TOKEN>/getUpdates

5. Запустите:
   ```bash
   docker-compose up -d --build
   ```
```

### Шаг 4: Коммит

```bash
# Убедитесь что .env в .gitignore
git status
# Не должно быть .env в списке!

# Коммитим только пример
git add .env.example .gitignore
git commit -m "Add environment configuration template"
git push
```

**Плюсы:**
- ✅ Секреты не попадают в Git
- ✅ Контроль версий структуры конфигурации
- ✅ Просто для понимания
- ✅ Стандартный подход

**Минусы:**
- ❌ Нужно вручную создавать .env на каждом сервере
- ❌ Нет автоматизации передачи секретов

---

## Решение 2: git-crypt (зашифрованные файлы в Git)

**Суть:** Автоматическое шифрование/дешифрование при commit/pull

### Установка git-crypt

```bash
# macOS
brew install git-crypt

# Ubuntu/Debian
sudo apt-get install git-crypt

# Windows (WSL или через Chocolatey)
choco install git-crypt
```

### Настройка

**Шаг 1: Инициализация в репозитории**

```bash
cd crypto-screener
git-crypt init
```

**Шаг 2: Создать .gitattributes**

```bash
# .gitattributes
# Шифровать все .env файлы (кроме .example)
.env filter=git-crypt diff=git-crypt
.env.production filter=git-crypt diff=git-crypt
.env.local filter=git-crypt diff=git-crypt

# НЕ шифровать примеры
.env.example !filter !diff
```

**Шаг 3: Экспортировать ключ (один раз)**

```bash
# Создать симметричный ключ для команды
git-crypt export-key ../crypto-screener-key

# ВАЖНО: Сохраните crypto-screener-key в безопасное место!
# Например, в password manager (1Password, Bitwarden)
```

**Шаг 4: Использование**

```bash
# На первом компьютере (где настроили)
echo "TELEGRAM_BOT_TOKEN=123456:ABC" > .env
git add .env
git commit -m "Add encrypted env"
git push

# На втором компьютере (новый сервер)
git clone https://github.com/your/repo.git
cd repo

# Разблокировать репозиторий с ключом
git-crypt unlock ../crypto-screener-key

# Теперь .env дешифрован и доступен!
cat .env  # Видны реальные значения
```

**Как это работает:**
1. При `git add .env` → git-crypt шифрует содержимое
2. В Git хранится зашифрованная версия
3. При `git checkout` → git-crypt дешифрует (если ключ есть)
4. Без ключа → файл остаётся зашифрованным

**Плюсы:**
- ✅ Секреты под контролем версий
- ✅ Автоматическое шифрование/дешифрование
- ✅ Можно давать доступ разным людям (GPG keys)
- ✅ История изменений секретов

**Минусы:**
- ❌ Нужно управлять ключами
- ❌ Если потеряли ключ → потеряли доступ
- ❌ Дополнительный инструмент в workflow

---

## Решение 3: Docker Secrets (для продакшна)

**Суть:** Docker управляет секретами, не в .env файле

### Настройка

**Шаг 1: Создать секреты**

```bash
# Создать файлы секретов
echo "123456789:ABCdefGHI" > telegram_bot_token.txt
echo "987654321" > telegram_chat_id.txt

# Создать Docker secrets
docker secret create telegram_bot_token telegram_bot_token.txt
docker secret create telegram_chat_id telegram_chat_id.txt

# Удалить файлы
rm telegram_bot_token.txt telegram_chat_id.txt
```

**Шаг 2: docker-compose.yml**

```yaml
version: '3.8'

services:
  backend:
    image: crypto_screener_backend
    secrets:
      - telegram_bot_token
      - telegram_chat_id
    environment:
      # Указываем путь к секретам
      TELEGRAM_BOT_TOKEN_FILE: /run/secrets/telegram_bot_token
      TELEGRAM_CHAT_ID_FILE: /run/secrets/telegram_chat_id
    # ... остальное

secrets:
  telegram_bot_token:
    external: true
  telegram_chat_id:
    external: true
```

**Шаг 3: Чтение секретов в коде**

```python
# backend/config.py
from pydantic_settings import BaseSettings
import os

def read_secret(secret_name: str, default: str = None) -> str:
    """
    Читает секрет из Docker secret или переменной окружения
    """
    # Проверяем Docker secret
    secret_file = os.getenv(f'{secret_name}_FILE')
    if secret_file and os.path.exists(secret_file):
        with open(secret_file) as f:
            return f.read().strip()
    
    # Иначе из env
    return os.getenv(secret_name, default)

class Settings(BaseSettings):
    # Читаем из Docker secrets или .env
    telegram_bot_token: str = None
    telegram_chat_id: str = None
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Переопределяем из secrets если доступны
        self.telegram_bot_token = read_secret(
            'TELEGRAM_BOT_TOKEN',
            self.telegram_bot_token
        )
        self.telegram_chat_id = read_secret(
            'TELEGRAM_CHAT_ID',
            self.telegram_chat_id
        )
```

**Плюсы:**
- ✅ Секреты не в файловой системе
- ✅ Управление доступом на уровне Docker
- ✅ Ротация секретов без рестарта
- ✅ Стандарт для продакшна

**Минусы:**
- ❌ Только для Docker Swarm (не для обычного docker-compose)
- ❌ Сложнее для локальной разработки

---

## Решение 4: Переменные окружения в облаке (для деплоя)

**Для разных платформ:**

### GitHub Actions (CI/CD)

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Deploy to VPS
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          # Создать .env на сервере
          echo "TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN" > .env
          echo "TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID" >> .env
          
          # Скопировать на сервер
          scp .env user@server:/path/to/app/
```

**Где хранить секреты:**
- GitHub: Settings → Secrets and variables → Actions
- GitLab: Settings → CI/CD → Variables
- Bitbucket: Repository settings → Pipelines → Repository variables

### Heroku

```bash
# Установить секреты через CLI
heroku config:set TELEGRAM_BOT_TOKEN=123456:ABC
heroku config:set TELEGRAM_CHAT_ID=987654321

# Или через веб-интерфейс
# Settings → Config Vars
```

### AWS / DigitalOcean / VPS

```bash
# SSH на сервер
ssh user@your-server

# Создать .env файл напрямую
cat > /path/to/app/.env << EOF
TELEGRAM_BOT_TOKEN=123456:ABC
TELEGRAM_CHAT_ID=987654321
EOF

# Защитить файл
chmod 600 /path/to/app/.env
```

---

## 🎯 Рекомендация для вашего случая

### Для личного проекта: **Решение 1 (.gitignore + .env.example)**

**Почему:**
- ✅ Просто и понятно
- ✅ Стандартный подход (все так делают)
- ✅ Не нужны дополнительные инструменты
- ✅ Легко объяснить другим

**Что делать:**

```bash
# 1. Создать .gitignore
echo ".env" >> .gitignore
echo ".env.local" >> .gitignore
echo ".env.production" >> .gitignore

# 2. Создать .env.example
cp .env .env.example

# 3. Очистить секреты в .env.example
nano .env.example
# Заменить все токены на плейсхолдеры:
# TELEGRAM_BOT_TOKEN=your_bot_token_here

# 4. Убедиться что .env не в Git
git status  # .env не должен быть в списке

# 5. Коммит
git add .gitignore .env.example
git commit -m "Add environment configuration template"
git push
```

**На новом сервере:**

```bash
git clone https://github.com/your/repo.git
cd repo
cp .env.example .env
nano .env  # Заполнить реальные значения
docker-compose up -d
```

### Если хотите автоматизацию: **Решение 2 (git-crypt)**

Используйте если:
- Нужен автоматический деплой на несколько серверов
- Хотите версионировать изменения секретов
- Готовы управлять ключами шифрования

---

## Проверка безопасности

### ❌ Проверить что .env НЕ в Git:

```bash
# 1. Проверить текущий статус
git status
# Не должно быть .env!

# 2. Проверить историю (на всякий случай)
git log --all --full-history -- .env
# Должно быть пусто!

# 3. Если .env случайно закоммитили - СРОЧНО:
# a) Изменить ВСЕ токены/пароли
# b) Удалить из истории Git:
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch .env" \
  --prune-empty --tag-name-filter cat -- --all

# c) Force push
git push origin --force --all
```

### ✅ Проверить что .env.example есть:

```bash
git ls-files | grep .env.example
# Должен быть в списке!
```

### 🔒 Дополнительная безопасность:

**1. Git hooks (предотвращение случайного коммита)**

```bash
# .git/hooks/pre-commit
#!/bin/bash

if git diff --cached --name-only | grep -q "^.env$"; then
    echo "❌ ERROR: Attempting to commit .env file!"
    echo "Please remove .env from staging:"
    echo "  git reset HEAD .env"
    exit 1
fi
```

```bash
chmod +x .git/hooks/pre-commit
```

**2. Проверка в CI/CD**

```yaml
# .github/workflows/security-check.yml
name: Security Check

on: [push, pull_request]

jobs:
  check-secrets:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Check for .env files
        run: |
          if git ls-files | grep -E "^\.env$"; then
            echo "❌ .env file found in repository!"
            exit 1
          fi
          echo "✅ No .env files in repository"
```

**3. .dockerignore (не копировать .env в образ)**

```
# .dockerignore
.env
.env.local
.env.production
.git
.gitignore
```

---

## Альтернатива: Защита через ограничение IP

**Даже если токен украдут, ограничить использование:**

### Telegram Bot

К сожалению, Telegram Bot API не поддерживает IP whitelist.

**Но можно:**
1. Проверять `chat_id` перед обработкой команд
2. Использовать webhook вместо polling (можно ограничить IP на уровне сервера)

```python
# backend/screener/notifications.py

ALLOWED_CHAT_IDS = [int(os.getenv('TELEGRAM_CHAT_ID'))]

async def handle_telegram_message(message):
    """Обработка входящих сообщений"""
    
    chat_id = message.chat.id
    
    # Проверка whitelist
    if chat_id not in ALLOWED_CHAT_IDS:
        logger.warning(f"Unauthorized access attempt from chat_id: {chat_id}")
        return
    
    # Обработка...
```

---

## 8. Корректность работы со временем (timestamps, timezones, свечи)

### Критические вопросы про время

**Нужно проверить:**
1. ✅ Часовой пояс (UTC везде?)
2. ✅ Формат временных меток (секунды vs миллисекунды)
3. ✅ Округление до минут
4. ✅ Закрытые vs открытые свечи
5. ✅ Синхронизация с биржей
6. ⚠️ **КРИТИЧНО:** Соответствие timestamp в БД реальному времени свечи

### Проблема 1: Формат временных меток

**CCXT возвращает миллисекунды, БД хранит секунды!**

```python
# CCXT fetch_ohlcv возвращает:
[
  1736614800000,  # ← МИЛЛИСЕКУНДЫ! (13 цифр)
  90749.9,        # open
  90850.0,        # high
  90700.0,        # low
  90827.89,       # close
  125.45          # volume
]

# Ваша БД хранит:
timestamp INTEGER  # ← СЕКУНДЫ! (10 цифр)
```

**Конвертация:**
```python
# ✅ Правильно
timestamp_seconds = int(candle[0] / 1000)  # 1736614800

# ❌ Неправильно
timestamp_seconds = int(candle[0])  # 1736614800000 - переполнение!
```

### Проблема 2: Часовой пояс и timestamp

**Что такое Unix timestamp:**
```
Unix timestamp = количество секунд с 01.01.1970 00:00:00 UTC
Это ВСЕГДА UTC! Не зависит от локального часового пояса.
```

**Пример:**
```python
import time
from datetime import datetime, timezone

# Текущее время UTC
now_utc = datetime.now(timezone.utc)
print(now_utc)  # 2026-01-12 10:30:00+00:00

# Unix timestamp (одинаковый во всех часовых поясах!)
timestamp = int(time.time())
print(timestamp)  # 1736680200

# Обратное преобразование
dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
print(dt)  # 2026-01-12 10:30:00+00:00
```

**Проверка в вашей системе:**

```python
# backend/screener/exchange.py

async def _parse_market_data():
    """Парсинг с проверкой временных меток"""
    
    for symbol in symbols:
        candles = await exchange.fetch_ohlcv(symbol, '1m', limit=120)
        
        for candle in candles:
            # КРИТИЧНО: Конвертация миллисекунды → секунды
            timestamp_ms = candle[0]
            timestamp_sec = int(timestamp_ms / 1000)
            
            # ПРОВЕРКА: Временная метка из будущего?
            now = int(time.time())
            if timestamp_sec > now + 60:  # > 1 минуты в будущем
                logger.warning(
                    f"{symbol}: Candle timestamp in future! "
                    f"candle={timestamp_sec}, now={now}, "
                    f"diff={timestamp_sec - now}s"
                )
                continue  # Пропускаем
            
            # ПРОВЕРКА: Временная метка слишком старая?
            if timestamp_sec < now - (3 * 3600):  # > 3 часов назад
                logger.debug(
                    f"{symbol}: Candle too old "
                    f"({(now - timestamp_sec) // 60} minutes)"
                )
                continue  # Пропускаем (нам нужны только последние 2 часа)
            
            # ПРОВЕРКА: Округление до минуты
            minute_start = (timestamp_sec // 60) * 60
            if minute_start != timestamp_sec:
                logger.debug(
                    f"{symbol}: Timestamp not rounded to minute: "
                    f"{timestamp_sec} → {minute_start}"
                )
                timestamp_sec = minute_start
            
            # Сохранение
            await db.save_candle(
                symbol=symbol,
                market=market,
                timestamp=timestamp_sec,  # Секунды, округлённо до минуты
                open=candle[1],
                high=candle[2],
                low=candle[3],
                close=candle[4],
                volume=candle[5]
            )
```

### Проблема 3: Закрытые vs Текущие свечи

**Bybit возвращает последнюю свечу как "текущую" (ещё не закрытую)!**

```
Сейчас: 11:32:45

CCXT fetch_ohlcv возвращает:
[
  [11:30:00, ...],  # Закрытая свеча ✅
  [11:31:00, ...],  # Закрытая свеча ✅
  [11:32:00, ...],  # ТЕКУЩАЯ свеча (ещё открыта!) ❌
]
```

**Проблема:** Если использовать текущую свечу → данные меняются каждую секунду!

```python
# ❌ НЕПРАВИЛЬНО
candles = await exchange.fetch_ohlcv(symbol, '1m', limit=15)
# Последняя свеча ещё не закрыта!

# ✅ ПРАВИЛЬНО - исключить последнюю свечу
candles = await exchange.fetch_ohlcv(symbol, '1m', limit=16)
candles = candles[:-1]  # Убрать последнюю (текущую)
# Теперь только закрытые свечи

# Или проверять timestamp
now = int(time.time())
current_minute_start = (now // 60) * 60

candles_closed = [
    c for c in candles
    if int(c[0] / 1000) < current_minute_start
]
```

### Проблема 4: Определение "последней закрытой минуты"

**Из технической документации (строки 1027-1038):**

```python
now = int(time.time())  # 11:33:05
current_minute_start = (now // 60) * 60  # 11:33:00

# Если прошло меньше 10 секунд - берём предыдущую
if now - current_minute_start < 10:
    last_closed = current_minute_start - 60  # 11:32:00
else:
    last_closed = current_minute_start  # 11:33:00
```

**Вопрос: Почему 10 секунд?**

**Проблема с этой логикой:**

```
11:33:05 → берём 11:32:00 (предыдущую)
11:33:15 → берём 11:33:00 (текущую)

Но свеча 11:33:00 закрылась только в 11:34:00!
```

**То есть в 11:33:15 вы используете свечу 11:33:00, которая ЕЩЁ НЕ ЗАКРЫТА!**

### ✅ ПРАВИЛЬНОЕ решение

```python
def get_last_closed_candle_timestamp() -> int:
    """
    Получить timestamp последней ГАРАНТИРОВАННО закрытой свечи
    
    Логика:
    - Свеча 11:32:00-11:33:00 закрывается в 11:33:00
    - Биржа обрабатывает данные 0-5 секунд
    - Безопасно использовать свечу 11:32:00 начиная с 11:33:10
    
    Returns:
        Unix timestamp (секунды) начала последней закрытой минуты
    """
    now = int(time.time())
    
    # Начало текущей минуты
    current_minute_start = (now // 60) * 60
    
    # ВСЕГДА берём ПРЕДЫДУЩУЮ минуту для безопасности
    # Текущая минута гарантированно не закрыта
    last_closed_minute = current_minute_start - 60
    
    return last_closed_minute


# Пример использования
async def get_candles(symbol: str, market: str, minutes: int) -> list:
    """
    Получить свечи за последние N минут (только закрытые)
    
    Args:
        symbol: Торговая пара
        market: 'spot' или 'futures'
        minutes: Сколько минут назад (15, 30, 60, 120)
    
    Returns:
        Список свечей (только закрытые)
    """
    # Последняя закрытая минута
    last_closed = get_last_closed_candle_timestamp()
    
    # Окно: [last_closed - minutes*60, last_closed]
    window_start = last_closed - (minutes * 60)
    
    logger.debug(
        f"Getting {minutes}m candles for {symbol}: "
        f"window [{timestamp_to_str(window_start)} - "
        f"{timestamp_to_str(last_closed)}]"
    )
    
    # SQL запрос
    candles = await db.execute(
        """
        SELECT * FROM candles
        WHERE symbol = ? AND market = ?
          AND timestamp > ?
          AND timestamp <= ?
        ORDER BY timestamp ASC
        """,
        (symbol, market, window_start, last_closed)
    )
    
    logger.debug(f"Got {len(candles)} candles for {symbol}")
    
    return candles


def timestamp_to_str(ts: int) -> str:
    """Конвертация timestamp в читаемый формат"""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%H:%M:%S')
```

### Проблема 5: Фиксированное vs Скользящее окно

**Из документации (строки 1048-1061):**

```
Сейчас: 11:37:05
Последняя закрытая: 11:36:00
Интервал: 15 минут

Окно: 11:21:00 - 11:36:00  ← ФИКСИРОВАНО!

Через 30 секунд (11:37:35):
Окно: 11:21:00 - 11:36:00  ← ТО ЖЕ САМОЕ!

Через минуту (11:38:05):
Окно: 11:22:00 - 11:37:00  ← СДВИНУЛОСЬ!
```

**Это правильно!** ✅

Окно НЕ должно "плавать" внутри минуты, иначе:
- В 11:37:05 проверяем окно 11:22:05 - 11:37:05
- В 11:37:35 проверяем окно 11:22:35 - 11:37:35
- **Разные данные → разные результаты → хаос!**

### Проблема 6: Синхронизация проверки с закрытием свечей

**Из документации (строки 1066-1076):**

```
11:30:00 ← свеча закрылась
11:30:05 ← ПРОВЕРКА

11:31:00 ← свеча закрылась
11:31:05 ← ПРОВЕРКА
```

**Вопрос: Достаточно ли 5 секунд для обработки биржей?**

**Обычно да, но бывают задержки!**

```python
async def _check_filters_loop():
    """
    Цикл проверки фильтров синхронизированный с закрытием свечей
    """
    while running:
        now = time.time()
        
        # Начало текущей минуты
        current_minute_start = (now // 60) * 60
        
        # Сколько секунд прошло в текущей минуте
        seconds_in_minute = now - current_minute_start
        
        # ВАЖНО: Ждём 10 секунд ПОСЛЕ начала минуты
        # Это даёт бирже время обработать закрытие предыдущей свечи
        SAFE_DELAY = 10  # секунд
        
        if seconds_in_minute < SAFE_DELAY:
            # Слишком рано, ждём
            sleep_time = SAFE_DELAY - seconds_in_minute
            logger.debug(f"Waiting {sleep_time:.1f}s for candles to close")
            await asyncio.sleep(sleep_time)
        else:
            # Уже прошло > 10 секунд, ждём следующей минуты + 10 сек
            sleep_time = (60 - seconds_in_minute) + SAFE_DELAY
            logger.debug(f"Waiting {sleep_time:.1f}s for next minute")
            await asyncio.sleep(sleep_time)
        
        # Теперь время = XX:XX:10+, можно проверять
        logger.info("Starting filter check cycle...")
        await _check_filters()
```

### ✅ Полный правильный код для работы со временем

```python
# backend/screener/time_utils.py

from datetime import datetime, timezone
import time
from typing import Tuple

def get_current_timestamp() -> int:
    """
    Получить текущий Unix timestamp (UTC)
    
    Returns:
        int: Секунды с 01.01.1970 00:00:00 UTC
    """
    return int(time.time())


def get_last_closed_candle_timestamp() -> int:
    """
    Получить timestamp последней ГАРАНТИРОВАННО закрытой 1m свечи
    
    Логика:
    - Свеча 11:32:00 закрывается в 11:33:00
    - Берём текущую минуту - 60 секунд = предыдущая минута
    - Предыдущая минута точно закрыта
    
    Returns:
        int: Unix timestamp начала последней закрытой минуты
    """
    now = get_current_timestamp()
    current_minute_start = (now // 60) * 60
    last_closed = current_minute_start - 60
    return last_closed


def get_candle_window(minutes: int) -> Tuple[int, int]:
    """
    Получить окно времени для свечей (только закрытые)
    
    Args:
        minutes: Длина окна в минутах (15, 30, 120, etc)
    
    Returns:
        (window_start, window_end) в Unix timestamp (секунды)
        
    Example:
        Сейчас 11:37:45
        get_candle_window(15)
        → (11:21:00, 11:36:00)  # 15 минут до последней закрытой
    """
    last_closed = get_last_closed_candle_timestamp()
    window_start = last_closed - (minutes * 60) + 60  # +60 чтобы включить start
    window_end = last_closed
    
    return window_start, window_end


def round_to_minute(timestamp: int) -> int:
    """
    Округлить timestamp до начала минуты
    
    Args:
        timestamp: Unix timestamp (секунды)
    
    Returns:
        Округлённый timestamp (начало минуты)
        
    Example:
        round_to_minute(1736614845)  # 11:34:05
        → 1736614800  # 11:34:00
    """
    return (timestamp // 60) * 60


def timestamp_to_datetime(timestamp: int) -> datetime:
    """
    Конвертация Unix timestamp → datetime (UTC)
    
    Args:
        timestamp: Unix timestamp (секунды)
    
    Returns:
        datetime object with UTC timezone
    """
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def timestamp_to_str(timestamp: int, format: str = '%Y-%m-%d %H:%M:%S') -> str:
    """
    Конвертация Unix timestamp → строка
    
    Args:
        timestamp: Unix timestamp (секунды)
        format: Формат вывода (strftime format)
    
    Returns:
        Отформатированная строка
    """
    dt = timestamp_to_datetime(timestamp)
    return dt.strftime(format)


def validate_candle_timestamp(
    timestamp: int,
    symbol: str = None
) -> bool:
    """
    Проверка корректности timestamp свечи
    
    Args:
        timestamp: Unix timestamp для проверки
        symbol: Символ (для логирования)
    
    Returns:
        True если timestamp корректный
    """
    now = get_current_timestamp()
    
    # 1. Не в будущем (+ 60 сек допустимо для десинхронизации часов)
    if timestamp > now + 60:
        logger.warning(
            f"{symbol or 'Unknown'}: Timestamp in future! "
            f"timestamp={timestamp_to_str(timestamp)}, "
            f"now={timestamp_to_str(now)}"
        )
        return False
    
    # 2. Не слишком старый (> 3 часов для 120m window)
    max_age = 3 * 3600  # 3 часа
    if timestamp < now - max_age:
        logger.debug(
            f"{symbol or 'Unknown'}: Timestamp too old "
            f"({(now - timestamp) // 60} minutes)"
        )
        return False
    
    # 3. Округлён до минуты
    if timestamp % 60 != 0:
        logger.warning(
            f"{symbol or 'Unknown'}: Timestamp not rounded to minute: "
            f"{timestamp}"
        )
        return False
    
    return True


def is_candle_closed(candle_timestamp: int, buffer_seconds: int = 10) -> bool:
    """
    Проверка что свеча гарантированно закрыта
    
    Args:
        candle_timestamp: Начало свечи (Unix timestamp)
        buffer_seconds: Буфер для обработки биржей (по умолчанию 10)
    
    Returns:
        True если свеча точно закрыта
        
    Example:
        Сейчас 11:33:15
        is_candle_closed(11:32:00) → True  (закрылась в 11:33:00)
        is_candle_closed(11:33:00) → False (закроется в 11:34:00)
    """
    now = get_current_timestamp()
    
    # Свеча закрывается через 60 секунд после начала
    close_time = candle_timestamp + 60
    
    # Добавляем буфер для обработки биржей
    safe_time = close_time + buffer_seconds
    
    return now >= safe_time
```

### Тестирование временных функций

```python
# backend/tests/test_time_utils.py

import pytest
from backend.screener.time_utils import *
from unittest.mock import patch
import time

def test_get_last_closed_candle():
    """Тест получения последней закрытой свечи"""
    
    # Mock текущего времени
    # 11:33:45
    mock_time = 1736614425
    
    with patch('time.time', return_value=mock_time):
        last_closed = get_last_closed_candle_timestamp()
        
        # Должно быть 11:32:00
        expected = 1736614320
        assert last_closed == expected
        
        # Проверка что это действительно начало минуты
        assert last_closed % 60 == 0

def test_get_candle_window():
    """Тест окна свечей"""
    
    # Mock: 11:37:45
    mock_time = 1736614665
    
    with patch('time.time', return_value=mock_time):
        # Окно 15 минут
        start, end = get_candle_window(15)
        
        # End должен быть 11:36:00 (последняя закрытая)
        assert end == 1736614560
        
        # Start должен быть 11:22:00 (15 минут до end + 1 минута)
        assert start == 1736613780
        
        # Разница должна быть 15 минут
        assert (end - start) == 14 * 60

def test_validate_candle_timestamp():
    """Тест валидации timestamp"""
    
    now = int(time.time())
    
    # Корректный timestamp (1 минута назад, округлён)
    valid = (now // 60 - 1) * 60
    assert validate_candle_timestamp(valid) == True
    
    # Timestamp в будущем
    future = now + 120
    assert validate_candle_timestamp(future) == False
    
    # Не округлён до минуты
    not_rounded = now - 45
    assert validate_candle_timestamp(not_rounded) == False
    
    # Слишком старый
    old = now - (4 * 3600)  # 4 часа назад
    assert validate_candle_timestamp(old) == False

def test_is_candle_closed():
    """Тест проверки закрытия свечи"""
    
    # Mock: 11:33:15
    mock_time = 1736614395
    
    with patch('time.time', return_value=mock_time):
        # Свеча 11:32:00 закрылась в 11:33:00 + 10 сек = 11:33:10
        # Сейчас 11:33:15 → закрыта
        assert is_candle_closed(1736614320) == True
        
        # Свеча 11:33:00 закроется в 11:34:00 + 10 сек = 11:34:10
        # Сейчас 11:33:15 → ещё не закрыта
        assert is_candle_closed(1736614380) == False
```

### Проверка в логах

```python
# При парсинге
logger.info(
    f"Parsing candles. Current time: {timestamp_to_str(get_current_timestamp())}, "
    f"Last closed: {timestamp_to_str(get_last_closed_candle_timestamp())}"
)

# При проверке фильтров
window_start, window_end = get_candle_window(15)
logger.info(
    f"Checking filters with window: "
    f"{timestamp_to_str(window_start)} - {timestamp_to_str(window_end)}"
)
```

---

## 🎯 Итоговые рекомендации

### ✅ Что ДОЛЖНО быть:

1. **CCXT миллисекунды → секунды**
   ```python
   timestamp = int(candle[0] / 1000)
   ```

2. **Всегда UTC**
   ```python
   datetime.now(timezone.utc)
   ```

3. **Округление до минуты**
   ```python
   timestamp = (timestamp // 60) * 60
   ```

4. **Только закрытые свечи**
   ```python
   last_closed = current_minute_start - 60
   ```

5. **Валидация timestamp**
   ```python
   if not validate_candle_timestamp(ts):
       continue
   ```

6. **Буфер 10 секунд**
   ```python
   # Проверка в XX:XX:10+
   ```

### ❌ Что НЕЛЬЗЯ делать:

- ❌ Использовать локальное время (`datetime.now()` без timezone)
- ❌ Хранить timestamp в миллисекундах
- ❌ Использовать текущую (не закрытую) свечу
- ❌ Проверять фильтры раньше чем XX:XX:10
- ❌ Доверять timestamp без валидации

---

## 9. Финальный чек-лист упущенных моментов (для персонального Docker-деплоя)

### Контекст: Персональный софт в Docker

**Что у нас есть:**
- ✅ Один пользователь (вы)
- ✅ Docker на локальной машине или VPS
- ✅ Нет multi-user требований
- ✅ Нет высоких требований к security/scalability

**Что можем упустить:**
- Мелкие удобства использования
- Edge cases
- Оптимизации
- Мониторинг и алерты
- Backup и восстановление

---

## Категория 1: Удобство использования

### 1.1 Управление контейнерами

**Проблема:** Каждый раз `docker-compose up -d --build` долго

**Решение: Makefile для быстрых команд**

```makefile
# Makefile
.PHONY: help start stop restart logs build clean backup restore status

help:  ## Показать помощь
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

start:  ## Запустить контейнеры
	docker-compose up -d

stop:  ## Остановить контейнеры
	docker-compose down

restart:  ## Перезапустить контейнеры
	docker-compose restart

logs:  ## Показать логи (follow)
	docker-compose logs -f backend

logs-tail:  ## Показать последние 100 строк логов
	docker-compose logs --tail=100 backend

build:  ## Пересобрать и запустить
	docker-compose up -d --build

clean:  ## Очистить всё (включая volumes)
	docker-compose down -v
	docker system prune -f

backup:  ## Сделать бэкап БД
	@mkdir -p backups
	docker cp crypto_screener_backend:/data/screener.db backups/screener_$(shell date +%Y%m%d_%H%M%S).db
	@echo "Backup created in backups/"

restore:  ## Восстановить БД из последнего бэкапа
	@LATEST=$$(ls -t backups/screener_*.db 2>/dev/null | head -n1); \
	if [ -z "$$LATEST" ]; then \
		echo "No backups found"; \
		exit 1; \
	fi; \
	echo "Restoring from $$LATEST..."; \
	docker cp "$$LATEST" crypto_screener_backend:/data/screener.db; \
	echo "Restored! Restarting..."; \
	$(MAKE) restart

status:  ## Показать статус контейнеров
	docker-compose ps
	@echo ""
	@echo "Resource usage:"
	docker stats --no-stream crypto_screener_backend crypto_screener_frontend

shell:  ## Открыть shell в backend контейнере
	docker-compose exec backend bash

db-shell:  ## Открыть sqlite shell
	docker-compose exec backend sqlite3 /data/screener.db

test-telegram:  ## Отправить тестовое уведомление в Telegram
	docker-compose exec backend python -c "from backend.screener.notifications import send_test_message; import asyncio; asyncio.run(send_test_message())"

watch-logs:  ## Следить за логами с фильтрацией
	docker-compose logs -f backend | grep -E "(ERROR|TRIGGERED|✅|❌)"

check-health:  ## Проверить здоровье системы
	@echo "Checking backend health..."
	@curl -s http://localhost:8000/health | jq .
	@echo ""
	@echo "Checking frontend..."
	@curl -s -o /dev/null -w "Frontend: HTTP %{http_code}\n" http://localhost:3000

update:  ## Обновить код и перезапустить
	git pull
	$(MAKE) build
	@echo "Updated and restarted!"
```

**Использование:**
```bash
make help          # Список команд
make start         # Запустить
make logs          # Логи
make backup        # Бэкап БД
make restart       # Перезапуск
```

### 1.2 Быстрая диагностика проблем

**Проблема:** Не понятно что не работает

**Решение: Скрипт диагностики**

```bash
#!/bin/bash
# scripts/diagnose.sh

echo "======================================"
echo "CRYPTO SCREENER DIAGNOSTICS"
echo "======================================"
echo ""

# 1. Docker
echo "1. Docker status:"
if docker ps &>/dev/null; then
    echo "   ✅ Docker is running"
else
    echo "   ❌ Docker is NOT running!"
    exit 1
fi
echo ""

# 2. Containers
echo "2. Containers:"
docker-compose ps
echo ""

# 3. Backend health
echo "3. Backend health check:"
if curl -sf http://localhost:8000/health &>/dev/null; then
    echo "   ✅ Backend is healthy"
    curl -s http://localhost:8000/health | jq .
else
    echo "   ❌ Backend is NOT responding"
fi
echo ""

# 4. Frontend
echo "4. Frontend check:"
if curl -sf http://localhost:3000 &>/dev/null; then
    echo "   ✅ Frontend is accessible"
else
    echo "   ❌ Frontend is NOT accessible"
fi
echo ""

# 5. Database
echo "5. Database check:"
DB_SIZE=$(docker exec crypto_screener_backend sh -c 'du -h /data/screener.db 2>/dev/null | cut -f1')
if [ -n "$DB_SIZE" ]; then
    echo "   ✅ Database exists (size: $DB_SIZE)"
    
    # Таблицы
    echo "   Tables:"
    docker exec crypto_screener_backend sqlite3 /data/screener.db ".tables" | tr ' ' '\n' | sed 's/^/      - /'
    
    # Статистика
    echo "   Stats:"
    docker exec crypto_screener_backend sqlite3 /data/screener.db "
        SELECT 'Filters: ' || COUNT(*) FROM filters;
        SELECT 'Candles: ' || COUNT(*) FROM candles;
        SELECT 'Triggers: ' || COUNT(*) FROM filter_triggers;
    " | sed 's/^/      /'
else
    echo "   ❌ Database NOT found"
fi
echo ""

# 6. Логи (последние ошибки)
echo "6. Recent errors in logs:"
ERRORS=$(docker-compose logs backend --tail=100 2>/dev/null | grep -i error | tail -5)
if [ -n "$ERRORS" ]; then
    echo "$ERRORS" | sed 's/^/   /'
else
    echo "   ✅ No recent errors"
fi
echo ""

# 7. VPN check
echo "7. Network connectivity:"
if docker exec crypto_screener_backend curl -sf https://api.bybit.com/v5/market/time &>/dev/null; then
    echo "   ✅ Can reach Bybit API"
else
    echo "   ❌ Cannot reach Bybit API (VPN issue?)"
fi
echo ""

# 8. Disk space
echo "8. Disk space:"
df -h | grep -E "Filesystem|/$" | sed 's/^/   /'
echo ""

echo "======================================"
echo "Diagnostic complete!"
echo "======================================"
```

```bash
chmod +x scripts/diagnose.sh
./scripts/diagnose.sh
```

### 1.3 Автоматический backup

**Проблема:** Забываешь делать бэкапы

**Решение: Cron задача**

```bash
# scripts/auto-backup.sh
#!/bin/bash

BACKUP_DIR="$HOME/crypto_screener_backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup БД
docker cp crypto_screener_backend:/data/screener.db \
    "$BACKUP_DIR/screener_$DATE.db"

# Backup .env
cp .env "$BACKUP_DIR/env_$DATE"

# Удалить бэкапы старше 30 дней
find "$BACKUP_DIR" -name "screener_*.db" -mtime +30 -delete
find "$BACKUP_DIR" -name "env_*" -mtime +30 -delete

echo "Backup created: $BACKUP_DIR/screener_$DATE.db"
```

**Добавить в crontab:**
```bash
crontab -e

# Бэкап каждый день в 3:00
0 3 * * * /path/to/crypto_screener/scripts/auto-backup.sh >> /path/to/logs/backup.log 2>&1
```

---

## Категория 2: Мониторинг и алерты

### 2.1 Healthcheck скрипт

**Проблема:** Не знаешь когда система упала

**Решение: Мониторинг + уведомление**

```python
# scripts/health_monitor.py
#!/usr/bin/env python3

import requests
import time
import os
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CHECK_INTERVAL = 60  # секунд

def send_alert(message):
    """Отправить алерт в Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"ALERT: {message}")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': f"🚨 SCREENER ALERT\n\n{message}",
        'parse_mode': 'HTML'
    }
    
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Failed to send alert: {e}")

def check_health():
    """Проверка здоровья системы"""
    try:
        # Backend health
        r = requests.get('http://localhost:8000/health', timeout=10)
        if r.status_code != 200:
            return False, f"Backend returned {r.status_code}"
        
        data = r.json()
        if data.get('status') != 'healthy':
            return False, f"Backend unhealthy: {data}"
        
        # Frontend
        r = requests.get('http://localhost:3000', timeout=10)
        if r.status_code != 200:
            return False, f"Frontend returned {r.status_code}"
        
        return True, "All systems operational"
    
    except requests.RequestException as e:
        return False, f"Connection error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"

def main():
    print("Health monitor started")
    consecutive_failures = 0
    last_alert_time = 0
    ALERT_COOLDOWN = 3600  # 1 час между алертами
    
    while True:
        healthy, message = check_health()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if healthy:
            if consecutive_failures > 0:
                print(f"[{timestamp}] ✅ RECOVERED: {message}")
                if consecutive_failures >= 3:
                    send_alert(f"✅ System recovered!\n{message}")
                consecutive_failures = 0
            else:
                print(f"[{timestamp}] ✅ {message}")
        else:
            consecutive_failures += 1
            print(f"[{timestamp}] ❌ FAILURE #{consecutive_failures}: {message}")
            
            # Алерт после 3 провалов подряд
            if consecutive_failures == 3:
                current_time = time.time()
                if current_time - last_alert_time > ALERT_COOLDOWN:
                    send_alert(
                        f"❌ System is down!\n"
                        f"Consecutive failures: {consecutive_failures}\n"
                        f"Error: {message}\n\n"
                        f"Please check the system ASAP!"
                    )
                    last_alert_time = current_time
        
        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    main()
```

**Запуск в фоне:**
```bash
# В отдельном терминале или через systemd
python3 scripts/health_monitor.py &
```

### 2.2 Алерт о долгом парсинге

**Проблема:** Парсинг завис, но вы не знаете

**Решение: Добавить в движок**

```python
# backend/screener/engine.py

async def _parse_market_data():
    start_time = time.time()
    TIMEOUT = 600  # 10 минут максимум
    
    try:
        # ... парсинг ...
        
        duration = time.time() - start_time
        
        # Алерт если слишком долго
        if duration > TIMEOUT:
            logger.error(f"⚠️ Parsing took {duration:.0f}s (timeout: {TIMEOUT}s)")
            # Опционально: отправить в Telegram
            await send_admin_alert(
                f"Parsing is taking too long!\n"
                f"Duration: {duration:.0f}s\n"
                f"This may indicate VPN or network issues."
            )
    
    except Exception as e:
        logger.error(f"Fatal parsing error: {e}", exc_info=True)
        await send_admin_alert(f"Parsing failed!\n\nError: {e}")
        raise
```

---

## Категория 3: Производительность и оптимизация

### 3.1 Индексы БД

**Проблема:** Запросы могут быть медленными при большом количестве данных

**Решение: Проверить индексы**

```sql
-- Проверить существующие индексы
SELECT name, tbl_name, sql 
FROM sqlite_master 
WHERE type='index';

-- Если каких-то нет, добавить:

-- Для быстрого поиска свечей
CREATE INDEX IF NOT EXISTS idx_candles_symbol_market_time 
    ON candles(symbol, market, timestamp DESC);

-- Для cooldown проверки
CREATE INDEX IF NOT EXISTS idx_triggers_filter_symbol_time 
    ON filter_triggers(filter_id, symbol, triggered_at DESC);

-- Для истории
CREATE INDEX IF NOT EXISTS idx_triggers_time 
    ON filter_triggers(triggered_at DESC);

-- ANALYZE для оптимизации query planner
ANALYZE;
```

### 3.2 Очистка старых данных

**Проблема:** БД растёт бесконечно

**Решение: Автоматическая очистка** (уже в движке, но проверить)

```python
async def _cleanup_loop():
    """Очистка старых данных"""
    while running:
        await asyncio.sleep(15 * 60)  # Каждые 15 минут
        
        try:
            # Свечи старше 2 часов
            cutoff_candles = int(time.time()) - (2 * 3600)
            deleted_candles = await db.execute(
                "DELETE FROM candles WHERE timestamp < ?",
                (cutoff_candles,)
            )
            logger.info(f"Cleanup: deleted {deleted_candles} old candles")
            
            # Триггеры старше 30 дней (раз в день в 3:00)
            current_hour = datetime.now().hour
            if current_hour == 3:
                cutoff_triggers = int(time.time()) - (30 * 24 * 3600)
                deleted_triggers = await db.execute(
                    "DELETE FROM filter_triggers WHERE triggered_at < ?",
                    (cutoff_triggers,)
                )
                logger.info(f"Cleanup: deleted {deleted_triggers} old triggers")
                
                # VACUUM для освобождения места
                await db.execute("VACUUM")
                logger.info("Cleanup: VACUUM completed")
        
        except Exception as e:
            logger.error(f"Cleanup error: {e}", exc_info=True)
```

### 3.3 Размер Docker образов

**Проблема:** Образы слишком большие

**Решение: Multi-stage build**

```dockerfile
# Dockerfile.backend
FROM python:3.11-slim as builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Финальный образ
FROM python:3.11-slim

# Только runtime зависимости
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем установленные пакеты
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app
COPY backend/ ./backend/

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Категория 4: Edge cases и баги

### 4.1 Обработка пустых результатов

**Проблема:** Что если биржа вернула 0 символов?

```python
async def _parse_market_data():
    tickers = await exchange.fetch_tickers(market)
    
    if not tickers:
        logger.warning(f"⚠️ No tickers returned for {market}!")
        # Не падаем, просто пропускаем
        return 0
    
    logger.info(f"Got {len(tickers)} tickers")
    # ...
```

### 4.2 Дедупликация символов

**Проблема:** BTC/USDT может быть несколько раз

```python
# Фильтровать только нужные типы фьючерсов
if market == 'futures':
    # Только USDT-margined (линейные)
    tickers = {
        k: v for k, v in tickers.items()
        if k.endswith('/USDT:USDT')
    }
    
    logger.info(f"Filtered to {len(tickers)} USDT-margined futures")
```

### 4.3 Обработка NaN и Infinity

**Проблема:** Биржа может вернуть невалидные числа

```python
import math

def is_valid_number(value):
    """Проверка что число валидно"""
    if value is None:
        return False
    if math.isnan(value) or math.isinf(value):
        return False
    return True

# При сохранении
if not is_valid_number(candle['close']):
    logger.warning(f"{symbol}: Invalid close price: {candle['close']}")
    continue
```

### 4.4 Защита от деления на ноль

**Проблема:** Средний объём может быть 0

```python
# В фильтре всплеска объёмов
if avg_volume_per_interval == 0:
    logger.debug(f"{symbol}: Average volume is zero, skipping")
    return None

coefficient = current_volume / avg_volume_per_interval
```

---

## Категория 5: Документация

### 5.1 README.md

**Должен содержать:**

```markdown
# Crypto Screener for Bybit

Система мониторинга криптовалютных инструментов с настраиваемыми фильтрами.

## Быстрый старт

1. Клонировать и настроить:
   ```bash
   git clone <repo>
   cd crypto-screener
   cp .env.example .env
   nano .env  # Заполнить токены
   ```

2. Запустить:
   ```bash
   docker-compose up -d --build
   ```

3. Открыть: http://localhost:3000

## Telegram настройка

1. Создать бота: @BotFather → /newbot
2. Получить Chat ID: @userinfobot
3. Добавить в .env

## Команды

```bash
make start       # Запуск
make stop        # Остановка
make logs        # Логи
make backup      # Бэкап БД
make diagnose    # Диагностика
```

## Проблемы?

- VPN не работает → проверить подключение
- Нет уведомлений → проверить токены в .env
- Ошибки в логах → `make logs`
- Диагностика → `./scripts/diagnose.sh`

## Бэкапы

Автоматически каждый день в 3:00 → `~/crypto_screener_backups/`

Вручную: `make backup`

## Структура

- `/backend` - Python код
- `/frontend` - HTML/CSS/JS
- `/data` - БД (персистентная)
- `/logs` - Логи (персистентные)
```

### 5.2 CHANGELOG.md

```markdown
# Changelog

## [1.0.0] - 2026-01-12

### Added
- Фильтр "Изменение цены"
- Фильтр "Всплеск объёмов"
- Telegram уведомления
- WebSocket real-time
- Docker деплой

### Fixed
- Корректная работа со временем
- Retry механизм для API
- Cooldown система

## [1.1.0] - План

### Planned
- Multiple Telegram чатов
- Экспорт истории в CSV
- Dashboard с графиками
```

---

## Категория 6: Безопасность (для персонального использования)

### 6.1 Firewall (если на VPS)

```bash
# Закрыть порты от внешнего доступа
sudo ufw allow ssh
sudo ufw allow from 192.168.1.0/24 to any port 3000  # Только локальная сеть
sudo ufw enable
```

### 6.2 Защита БД

```bash
# Права доступа
chmod 600 .env
chmod 700 data/

# В docker-compose.yml
volumes:
  - ./data:/data:rw  # Read-write для backend
```

### 6.3 Rate limiting Telegram

**Проблема:** Можете заспамить себя уведомлениями

```python
# backend/screener/notifications.py

import time
from collections import deque

class RateLimiter:
    def __init__(self, max_messages=20, window_seconds=60):
        self.max_messages = max_messages
        self.window = window_seconds
        self.timestamps = deque()
    
    def can_send(self):
        now = time.time()
        
        # Удалить старые
        while self.timestamps and self.timestamps[0] < now - self.window:
            self.timestamps.popleft()
        
        # Проверить лимит
        if len(self.timestamps) >= self.max_messages:
            logger.warning(
                f"Rate limit reached: {len(self.timestamps)}/{self.max_messages} "
                f"in last {self.window}s"
            )
            return False
        
        self.timestamps.append(now)
        return True

rate_limiter = RateLimiter(max_messages=20, window_seconds=60)

async def send_telegram_notification(trigger):
    if not rate_limiter.can_send():
        logger.warning("Skipping notification due to rate limit")
        return
    
    # Отправка...
```

---

## Категория 7: Тестирование

### 7.1 Тестовые фильтры

**Создать фильтр с гарантированным срабатыванием:**

```json
{
  "name": "TEST: Любое изменение",
  "type": "price_change",
  "config": {
    "interval_minutes": 15,
    "min_price_change_percent": 0.001,  // Очень маленький порог
    "direction": "any",
    "min_volume_period": 1,  // Минимальный объём
    "min_volume_24h": 1,
    "exclude_coins": []
  }
}
```

### 7.2 Симуляция срабатывания

```python
# scripts/test_trigger.py

async def test_trigger():
    """Создать тестовое срабатывание"""
    
    trigger = {
        'filter_id': 999,
        'filter_name': 'TEST FILTER',
        'symbol': 'BTC/USDT:USDT',
        'market': 'futures',
        'triggered_at': int(time.time()),
        'data': {
            'price_change_percent': 5.5,
            'price_from': 90000.0,
            'price_to': 94950.0,
            'volume_period': 1500000,
            'volume_24h': 5000000000,
            'url': 'https://www.bybit.com/trade/usdt/BTCUSDT'
        }
    }
    
    # Отправить в Telegram
    await send_telegram_notification(trigger)
    
    # Broadcast через WebSocket
    await broadcast_trigger(trigger)
    
    print("✅ Test trigger sent!")

# Запуск
python -c "
from backend.screener.notifications import *
import asyncio
asyncio.run(test_trigger())
"
```

---

## ✅ Финальный чек-лист

### Критичное (обязательно проверить):

- [ ] ✅ Время: миллисекунды → секунды конвертация
- [ ] ✅ Время: только закрытые свечи
- [ ] ✅ Время: округление до минут
- [ ] ✅ Всплеск объёмов: исключить текущий период из среднего
- [ ] ✅ Объём: quoteVolume (USD) а не baseVolume
- [ ] ✅ WebSocket: подключен и работает
- [ ] ✅ .env: в .gitignore

### Важное (желательно):

- [ ] ⚠️ Логирование: DEBUG уровень для отладки
- [ ] ⚠️ Retry: механизм для сетевых ошибок
- [ ] ⚠️ Валидация: проверка данных от биржи
- [ ] ⚠️ Индексы БД: для быстрых запросов
- [ ] ⚠️ Бэкапы: автоматические (cron)

### Удобное (nice to have):

- [ ] 🎨 Makefile: быстрые команды
- [ ] 🎨 Диагностика: скрипт проверки
- [ ] 🎨 Health monitor: алерты при падении
- [ ] 🎨 README: инструкции
- [ ] 🎨 Тестовые фильтры

### Оптимизации (если нужно):

- [ ] 🚀 Multi-stage Docker build
- [ ] 🚀 SQLite PRAGMA оптимизации
- [ ] 🚀 Rate limiting для Telegram
- [ ] 🚀 Дедупликация символов

---

## 10. Правильное разделение Spot и Futures рынков

### Описание проблемы

**Спот и Фьючерсы - ЭТО РАЗНЫЕ РЫНКИ!**

```
BTC/USDT (spot)        ← Одна монета, можно купить и держать
BTC/USDT:USDT (futures) ← Другая монета, контракт с кредитным плечом

Разные:
- Цены (фьючерс может быть дороже/дешевле спота)
- Объёмы (фьючерсы обычно > спота)
- Волатильность
- Символы в CCXT
```

**Проблема:** Если не разделять правильно:
- ❌ Дублирование символов (BTC/USDT и BTC/USDT:USDT)
- ❌ Сравнение спот-цен с фьючерсными (некорректно)
- ❌ Смешивание данных в БД
- ❌ Срабатывание фильтра на "неправильном" рынке

### Как CCXT различает рынки

```python
# СПОТ
exchange.fetch_tickers()  # Все рынки (включая spot)
# Возвращает:
{
  'BTC/USDT': {...},
  'ETH/USDT': {...},
  'SOL/USDT': {...}
}

# ФЬЮЧЕРСЫ (Linear - USDT-margined)
exchange.fetch_tickers({'type': 'linear'})
# Или
exchange.options['defaultType'] = 'linear'
exchange.fetch_tickers()
# Возвращает:
{
  'BTC/USDT:USDT': {...},
  'ETH/USDT:USDT': {...},
  'SOL/USDT:USDT': {...}
}

# Обратите внимание на РАЗНЫЕ символы!
```

### Структура БД правильная

**В техдокументации БД правильно спроектирована:**

```sql
CREATE TABLE candles (
    symbol TEXT NOT NULL,     -- 'BTC/USDT' или 'BTC/USDT:USDT'
    market TEXT NOT NULL,     -- 'spot' или 'futures'
    ...
    UNIQUE(symbol, market, timestamp)
);

CREATE TABLE tickers (
    symbol TEXT NOT NULL,     -- 'BTC/USDT' или 'BTC/USDT:USDT'
    market TEXT NOT NULL,     -- 'spot' или 'futures'
    ...
    PRIMARY KEY (symbol, market)
);
```

**Это означает:**
- ✅ `BTC/USDT` + `spot` = отдельная запись
- ✅ `BTC/USDT:USDT` + `futures` = отдельная запись
- ✅ Нет коллизий

### ✅ Правильная реализация парсинга

```python
# backend/screener/exchange.py

import ccxt.async_support as ccxt

# Инициализация
exchange = ccxt.bybit({
    'enableRateLimit': True,
})

async def fetch_spot_tickers():
    """
    Получить тикеры спотового рынка
    
    Returns:
        dict: {'BTC/USDT': {...}, 'ETH/USDT': {...}}
    """
    logger.info("Fetching SPOT tickers...")
    
    try:
        # СПОСОБ 1: Явно указать spot
        exchange.options['defaultType'] = 'spot'
        tickers = await exchange.fetch_tickers()
        
        # Фильтрация только USDT пар
        usdt_tickers = {
            symbol: ticker
            for symbol, ticker in tickers.items()
            if '/USDT' in symbol and ':' not in symbol  # Без ':'
        }
        
        logger.info(f"Got {len(usdt_tickers)} SPOT tickers")
        return usdt_tickers
    
    except Exception as e:
        logger.error(f"Error fetching SPOT tickers: {e}")
        raise


async def fetch_futures_tickers():
    """
    Получить тикеры фьючерсного рынка (linear/USDT-margined)
    
    Returns:
        dict: {'BTC/USDT:USDT': {...}, 'ETH/USDT:USDT': {...}}
    """
    logger.info("Fetching FUTURES tickers...")
    
    try:
        # СПОСОБ 1: Явно указать linear (USDT-margined)
        exchange.options['defaultType'] = 'linear'
        tickers = await exchange.fetch_tickers()
        
        # Фильтрация только Linear USDT пар
        # Linear фьючерсы имеют формат: BASE/QUOTE:SETTLE
        # Например: BTC/USDT:USDT
        linear_tickers = {
            symbol: ticker
            for symbol, ticker in tickers.items()
            if symbol.endswith('/USDT:USDT')  # Только linear USDT
        }
        
        logger.info(f"Got {len(linear_tickers)} FUTURES (linear) tickers")
        return linear_tickers
    
    except Exception as e:
        logger.error(f"Error fetching FUTURES tickers: {e}")
        raise


async def fetch_spot_candles(symbol: str, timeframe: str = '1m', limit: int = 120):
    """
    Получить свечи для спотового рынка
    
    Args:
        symbol: Например 'BTC/USDT' (БЕЗ :USDT!)
        timeframe: '1m', '5m', etc
        limit: Количество свечей
    
    Returns:
        list: Массив свечей [[timestamp, o, h, l, c, volume], ...]
    """
    logger.debug(f"Fetching SPOT candles for {symbol}")
    
    try:
        exchange.options['defaultType'] = 'spot'
        candles = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        logger.debug(f"Got {len(candles)} SPOT candles for {symbol}")
        return candles
    
    except Exception as e:
        logger.warning(f"Error fetching SPOT candles for {symbol}: {e}")
        return []


async def fetch_futures_candles(symbol: str, timeframe: str = '1m', limit: int = 120):
    """
    Получить свечи для фьючерсного рынка
    
    Args:
        symbol: Например 'BTC/USDT:USDT' (С :USDT!)
        timeframe: '1m', '5m', etc
        limit: Количество свечей
    
    Returns:
        list: Массив свечей [[timestamp, o, h, l, c, volume], ...]
    """
    logger.debug(f"Fetching FUTURES candles for {symbol}")
    
    try:
        exchange.options['defaultType'] = 'linear'
        candles = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        logger.debug(f"Got {len(candles)} FUTURES candles for {symbol}")
        return candles
    
    except Exception as e:
        logger.warning(f"Error fetching FUTURES candles for {symbol}: {e}")
        return []
```

### ✅ Правильная реализация в движке

```python
# backend/screener/engine.py

async def _parse_market_data():
    """
    Парсинг данных с биржи (spot и futures отдельно)
    """
    logger.info("=" * 70)
    logger.info("PARSING: Starting data collection")
    logger.info("=" * 70)
    
    stats = {
        'spot': {'tickers': 0, 'candles_success': 0, 'candles_errors': 0},
        'futures': {'tickers': 0, 'candles_success': 0, 'candles_errors': 0}
    }
    
    # Определяем какие рынки парсить (из настроек)
    markets_to_parse = []
    if settings.PARSE_SPOT:
        markets_to_parse.append('spot')
    if settings.PARSE_FUTURES:
        markets_to_parse.append('futures')
    
    if not markets_to_parse:
        logger.warning("⚠️ No markets enabled for parsing!")
        return stats
    
    logger.info(f"Markets to parse: {', '.join(markets_to_parse)}")
    
    # ПАРСИМ КАЖДЫЙ РЫНОК ОТДЕЛЬНО
    for market in markets_to_parse:
        logger.info(f"--- Processing {market.upper()} market ---")
        
        try:
            # 1. Загрузка тикеров
            if market == 'spot':
                tickers = await fetch_spot_tickers()
            else:  # futures
                tickers = await fetch_futures_tickers()
            
            stats[market]['tickers'] = len(tickers)
            
            # 2. Сохранение тикеров в БД
            for symbol, ticker in tickers.items():
                try:
                    volume_24h = ticker.get('quoteVolume', 0)  # USD
                    last_price = ticker.get('last', 0)
                    
                    if not last_price or last_price <= 0:
                        continue
                    
                    # ВАЖНО: Сохраняем с указанием рынка!
                    await db.save_ticker(
                        symbol=symbol,        # 'BTC/USDT' или 'BTC/USDT:USDT'
                        market=market,        # 'spot' или 'futures'
                        volume_24h=volume_24h,
                        last_price=last_price
                    )
                
                except Exception as e:
                    logger.warning(f"{symbol} ({market}): Error saving ticker: {e}")
            
            # 3. Получение символов для загрузки свечей
            symbols = list(tickers.keys())
            logger.info(f"{market}: Loading candles for {len(symbols)} symbols")
            
            # 4. Загрузка свечей (параллельно, батчами)
            for i in range(0, len(symbols), 10):  # Батчи по 10
                batch = symbols[i:i+10]
                
                tasks = []
                for symbol in batch:
                    if market == 'spot':
                        task = fetch_spot_candles(symbol, '1m', 120)
                    else:  # futures
                        task = fetch_futures_candles(symbol, '1m', 120)
                    
                    tasks.append((symbol, task))
                
                # Ждём батч
                results = await asyncio.gather(
                    *[t[1] for t in tasks],
                    return_exceptions=True
                )
                
                # Сохранение свечей
                for (symbol, _), candles in zip(tasks, results):
                    if isinstance(candles, Exception):
                        stats[market]['candles_errors'] += 1
                        continue
                    
                    if not candles:
                        stats[market]['candles_errors'] += 1
                        continue
                    
                    # Исключить последнюю (текущую) свечу
                    closed_candles = candles[:-1]
                    
                    for candle in closed_candles:
                        try:
                            timestamp = int(candle[0] / 1000)  # ms → sec
                            
                            # Валидация
                            if not validate_candle_timestamp(timestamp, symbol):
                                continue
                            
                            # Сохранение с указанием рынка
                            await db.save_candle(
                                symbol=symbol,       # 'BTC/USDT' или 'BTC/USDT:USDT'
                                market=market,       # 'spot' или 'futures'
                                timestamp=timestamp,
                                open=candle[1],
                                high=candle[2],
                                low=candle[3],
                                close=candle[4],
                                volume=candle[5]  # или candle[6] если quoteVolume
                            )
                        
                        except Exception as e:
                            logger.debug(f"{symbol} ({market}): Error saving candle: {e}")
                    
                    stats[market]['candles_success'] += 1
            
            logger.info(
                f"{market}: Complete - "
                f"tickers: {stats[market]['tickers']}, "
                f"candles: {stats[market]['candles_success']}/{len(symbols)}"
            )
        
        except Exception as e:
            logger.error(f"{market}: Fatal error - {e}", exc_info=True)
    
    # Финальная статистика
    logger.info("=" * 70)
    logger.info("PARSING: Summary")
    logger.info(f"SPOT: {stats['spot']}")
    logger.info(f"FUTURES: {stats['futures']}")
    logger.info("=" * 70)
    
    return stats
```

### ✅ Проверка фильтров с учётом рынка

```python
# backend/screener/filters.py

async def check_price_change_filter(
    symbol: str,
    market: str,  # ← ВАЖНО!
    filter_config: dict,
    filter_name: str
) -> Optional[dict]:
    """
    Проверка фильтра "Изменение цены"
    
    Args:
        symbol: 'BTC/USDT' или 'BTC/USDT:USDT'
        market: 'spot' или 'futures'
        filter_config: Конфигурация фильтра
        filter_name: Название для логов
    """
    
    # Проверка что фильтр для этого рынка
    if filter_config['market'] != market:
        return None  # Фильтр для другого рынка
    
    logger.debug(
        f"[{filter_name}] Checking {symbol} ({market}): "
        f"interval={filter_config['interval_minutes']}m"
    )
    
    # Получение свечей ТОЛЬКО для этого рынка и символа
    candles = await db.get_candles(
        symbol=symbol,
        market=market,  # ← ФИЛЬТРАЦИЯ ПО РЫНКУ!
        minutes=filter_config['interval_minutes']
    )
    
    if len(candles) < 2:
        logger.debug(f"[{filter_name}] {symbol} ({market}): Not enough candles")
        return None
    
    # ... остальная логика проверки ...


async def _check_filters():
    """
    Проверка всех активных фильтров
    """
    filters = await db.get_active_filters()
    
    if not filters:
        logger.info("No active filters")
        return 0
    
    logger.info(f"Checking {len(filters)} active filters...")
    
    triggers_count = 0
    
    for filter in filters:
        filter_market = filter['config']['market']  # 'spot' или 'futures'
        
        logger.debug(f"Filter '{filter['name']}': market={filter_market}")
        
        # Получить символы ТОЛЬКО для этого рынка
        symbols = await db.get_symbols_for_market(filter_market)
        
        logger.debug(f"Filter '{filter['name']}': checking {len(symbols)} symbols")
        
        for symbol in symbols:
            try:
                # Проверка фильтра
                if filter['type'] == 'price_change':
                    result = await check_price_change_filter(
                        symbol=symbol,
                        market=filter_market,  # ← ПЕРЕДАЁМ РЫНОК!
                        filter_config=filter['config'],
                        filter_name=filter['name']
                    )
                elif filter['type'] == 'volume_spike':
                    result = await check_volume_spike_filter(
                        symbol=symbol,
                        market=filter_market,  # ← ПЕРЕДАЁМ РЫНОК!
                        filter_config=filter['config'],
                        filter_name=filter['name']
                    )
                
                if result:
                    # Cooldown проверка
                    if not await check_cooldown(filter['id'], symbol, filter_market):
                        continue
                    
                    # Сохранение срабатывания
                    trigger = await db.save_trigger(
                        filter_id=filter['id'],
                        filter_name=filter['name'],
                        symbol=symbol,
                        market=filter_market,  # ← СОХРАНЯЕМ РЫНОК!
                        data=result
                    )
                    
                    triggers_count += 1
                    
                    # Уведомления...
            
            except Exception as e:
                logger.error(
                    f"Error checking {symbol} ({filter_market}): {e}",
                    exc_info=True
                )
    
    return triggers_count
```

### ✅ База данных - запросы с учётом рынка

```python
# backend/screener/database.py

async def get_candles(
    symbol: str,
    market: str,
    minutes: int
) -> list:
    """
    Получить свечи за последние N минут
    
    Args:
        symbol: 'BTC/USDT' или 'BTC/USDT:USDT'
        market: 'spot' или 'futures'
        minutes: Длина окна
    
    Returns:
        Список свечей (только закрытые)
    """
    last_closed = get_last_closed_candle_timestamp()
    window_start = last_closed - (minutes * 60) + 60
    
    # ВАЖНО: Фильтрация по symbol И market!
    query = """
        SELECT timestamp, open, high, low, close, volume
        FROM candles
        WHERE symbol = ? AND market = ?
          AND timestamp > ?
          AND timestamp <= ?
        ORDER BY timestamp ASC
    """
    
    rows = await db.execute(query, (symbol, market, window_start, last_closed))
    
    return rows


async def get_ticker(symbol: str, market: str) -> Optional[dict]:
    """
    Получить тикер
    
    Args:
        symbol: 'BTC/USDT' или 'BTC/USDT:USDT'
        market: 'spot' или 'futures'
    
    Returns:
        {'volume_24h': ..., 'last_price': ...} или None
    """
    # ВАЖНО: Фильтрация по symbol И market!
    query = """
        SELECT volume_24h, last_price
        FROM tickers
        WHERE symbol = ? AND market = ?
    """
    
    row = await db.execute_one(query, (symbol, market))
    
    return row


async def get_symbols_for_market(market: str) -> list[str]:
    """
    Получить все символы для конкретного рынка
    
    Args:
        market: 'spot' или 'futures'
    
    Returns:
        Список символов ['BTC/USDT', 'ETH/USDT', ...] или
        ['BTC/USDT:USDT', 'ETH/USDT:USDT', ...]
    """
    query = """
        SELECT DISTINCT symbol
        FROM tickers
        WHERE market = ?
    """
    
    rows = await db.execute(query, (market,))
    
    return [row['symbol'] for row in rows]


async def check_cooldown(
    filter_id: int,
    symbol: str,
    market: str,
    cooldown_minutes: int = 15
) -> bool:
    """
    Проверка cooldown
    
    Args:
        filter_id: ID фильтра
        symbol: Символ
        market: Рынок
        cooldown_minutes: Период cooldown
    
    Returns:
        True если можно отправлять уведомление
    """
    cutoff_time = int(time.time()) - (cooldown_minutes * 60)
    
    # ВАЖНО: Проверка по filter_id, symbol И market!
    query = """
        SELECT triggered_at
        FROM filter_triggers
        WHERE filter_id = ? AND symbol = ? AND market = ?
        ORDER BY triggered_at DESC
        LIMIT 1
    """
    
    row = await db.execute_one(query, (filter_id, symbol, market))
    
    if not row:
        return True  # Можно отправлять
    
    return row['triggered_at'] < cutoff_time
```

### Примеры правильного использования

```python
# Пример 1: Фильтр только для спота
filter_config = {
    "market": "spot",  # ← Только спот!
    "interval_minutes": 15,
    "min_price_change_percent": 5,
    ...
}

# Будет проверяться только:
# - BTC/USDT (spot)
# - ETH/USDT (spot)
# - SOL/USDT (spot)

# НЕ будет проверяться:
# - BTC/USDT:USDT (futures)
# - ETH/USDT:USDT (futures)


# Пример 2: Фильтр только для фьючерсов
filter_config = {
    "market": "futures",  # ← Только фьючерсы!
    "interval_minutes": 10,
    "min_price_change_percent": 3,
    ...
}

# Будет проверяться только:
# - BTC/USDT:USDT (futures)
# - ETH/USDT:USDT (futures)
# - SOL/USDT:USDT (futures)

# НЕ будет проверяться:
# - BTC/USDT (spot)
# - ETH/USDT (spot)


# Пример 3: Два фильтра для одной монеты
filter_spot = {
    "name": "BTC Рост 5% (Spot)",
    "market": "spot",
    ...
}

filter_futures = {
    "name": "BTC Рост 3% (Futures)",
    "market": "futures",
    ...
}

# BTC/USDT (spot) проверяется filter_spot
# BTC/USDT:USDT (futures) проверяется filter_futures
# ЭТО КОРРЕКТНО! Разные рынки, разные условия.
```

### Проверка в логах

```python
# При парсинге
logger.info("--- Processing SPOT market ---")
logger.info("Got 523 SPOT tickers")
logger.info("SPOT: Candles: 510/523 symbols")

logger.info("--- Processing FUTURES market ---")
logger.info("Got 586 FUTURES (linear) tickers")
logger.info("FUTURES: Candles: 570/586 symbols")

# При проверке фильтров
logger.debug("Filter 'Рост 5% Spot': market=spot")
logger.debug("Filter 'Рост 5% Spot': checking 523 symbols")

logger.debug("Filter 'Рост 3% Futures': market=futures")
logger.debug("Filter 'Рост 3% Futures': checking 586 symbols")

# При срабатывании
logger.info("[Рост 5% Spot] BTC/USDT (spot): ✅ TRIGGERED!")
logger.info("[Рост 3% Futures] BTC/USDT:USDT (futures): ✅ TRIGGERED!")
```

### Проверка в БД

```sql
-- Проверить что спот и фьючерсы разделены
SELECT market, COUNT(DISTINCT symbol) as symbols
FROM tickers
GROUP BY market;

-- Результат должен быть:
-- market   | symbols
-- spot     | 523
-- futures  | 586

-- Проверить свечи для BTC
SELECT market, COUNT(*) as candles
FROM candles
WHERE symbol LIKE 'BTC/USDT%'
GROUP BY market;

-- Результат:
-- market   | candles
-- spot     | 120     (BTC/USDT)
-- futures  | 120     (BTC/USDT:USDT)

-- Проверить срабатывания
SELECT market, symbol, COUNT(*) as triggers
FROM filter_triggers
GROUP BY market, symbol
ORDER BY triggers DESC
LIMIT 10;
```

### Настройки (.env)

```bash
# .env

# Какие рынки парсить
PARSE_SPOT=true        # Парсить спот
PARSE_FUTURES=true     # Парсить фьючерсы

# Можно отключить один из рынков:
# PARSE_SPOT=false     # Только фьючерсы
# PARSE_FUTURES=false  # Только спот
```

### Telegram уведомления с указанием рынка

```python
# backend/screener/notifications.py

def format_telegram_message(trigger: dict) -> str:
    """Форматирование уведомления для Telegram"""
    
    data = trigger['data']
    market_emoji = '💰' if trigger['market'] == 'spot' else '📈'
    market_name = 'Spot' if trigger['market'] == 'spot' else 'Futures'
    
    # URL на биржу
    if trigger['market'] == 'spot':
        # Пример: https://www.bybit.com/trade/spot/SOL/USDT
        pair = trigger['symbol'].replace('/', '/')  # SOL/USDT
        url = f"https://www.bybit.com/trade/spot/{pair}"
    else:  # futures
        # Пример: https://www.bybit.com/trade/usdt/SOLUSDT
        pair = trigger['symbol'].replace('/USDT:USDT', 'USDT')  # SOLUSDT
        url = f"https://www.bybit.com/trade/usdt/{pair}"
    
    message = f"""
🚀 Сработал фильтр: "{trigger['filter_name']}"

{market_emoji} Пара: {trigger['symbol']}
📊 Рынок: {market_name}
📈 Изменение: {data['price_change_percent']:+.2f}%
💵 Цена: ${data['price_from']:.2f} → ${data['price_to']:.2f}
📦 Объём: ${data['volume_period']:,.0f}
📊 Объём 24ч: ${data['volume_24h']:,.0f}

⏰ {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
🔗 Bybit: {url}
"""
    
    return message.strip()
```

---

## Итого: Что нужно проверить

### ✅ Правильное разделение

1. **Парсинг:**
   - `fetch_spot_tickers()` → символы БЕЗ `:USDT`
   - `fetch_futures_tickers()` → символы С `:USDT`
   - Отдельные функции для свечей

2. **Сохранение в БД:**
   - `symbol='BTC/USDT'` + `market='spot'`
   - `symbol='BTC/USDT:USDT'` + `market='futures'`
   - PRIMARY KEY на (symbol, market)

3. **Проверка фильтров:**
   - Фильтр с `market='spot'` → проверяет только спот
   - Фильтр с `market='futures'` → проверяет только фьючерсы
   - SQL запросы с `WHERE market = ?`

4. **Cooldown:**
   - По (filter_id, symbol, market) - разные рынки независимы

### ❌ Неправильное (дедупликация)

**НЕ нужно дедуплицировать!**

```python
# ❌ НЕПРАВИЛЬНО
if 'BTC/USDT' in spot_symbols and 'BTC/USDT:USDT' in futures_symbols:
    # Удалить один из них
    pass

# ✅ ПРАВИЛЬНО
# Оба символа нужны! Это разные рынки!
```

---

## Статус реализации

- [ ] **Проблема 1:** Синхронизация парсинга и проверки - **НЕ ИСПРАВЛЕНО**
- [ ] **Проблема 2:** Расчёт всплеска объёмов - **НЕ ИСПРАВЛЕНО**
- [ ] **Проблема 3:** Использование quoteVolume - **ТРЕБУЕТ ПРОВЕРКИ**
- [ ] **Проблема 4:** Детальное логирование - **НЕ РЕАЛИЗОВАНО**
- [ ] **Проблема 5:** Надёжный парсинг с retry и обработкой VPN - **НЕ РЕАЛИЗОВАНО**
- [ ] **Проблема 6:** WebSocket real-time обновления - **ТРЕБУЕТ ПРОВЕРКИ/ДОРАБОТКИ**
- [ ] **Проблема 8:** Корректность работы со временем - **ТРЕБУЕТ ПРОВЕРКИ И ВОЗМОЖНО ИСПРАВЛЕНИЯ**
- [ ] **Проблема 10:** Правильное разделение Spot и Futures - **ТРЕБУЕТ ПРОВЕРКИ**

---

## Решённые вопросы

- ✅ **Вопрос 1:** Выбор БД (SQLite vs PostgreSQL) - **SQLite подходит идеально, миграция не требуется**
- ✅ **Вопрос 2:** Безопасное хранение .env в Git - **Использовать .gitignore + .env.example (стандартный подход)**

---

## Следующие шаги

1. Исправить `backend/screener/engine.py` - синхронизация циклов
2. Исправить `backend/screener/filters.py` - алгоритм всплеска объёмов
3. Проверить `backend/screener/exchange.py` - используется ли quoteVolume
4. Реализовать детальное логирование по стандарту выше
5. Настроить RotatingFileHandler для ротации логов
6. Протестировать на реальных данных с DEBUG уровнем

---

**Документ будет обновляться по мере обнаружения и исправления проблем.**
