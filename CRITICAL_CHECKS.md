# Критические проверки перед запуском

**Дата:** 2026-01-12  
**Версия:** 1.0  
**Цель:** Чек-лист для валидации реализации перед production

---

## ✅ Проверка 1: Работа со временем

### 1.1 Timestamps в секундах

```bash
# Проверить БД
docker exec -it crypto_screener_backend sqlite3 /data/screener.db

SELECT timestamp, datetime(timestamp, 'unixepoch') as time, close
FROM candles
ORDER BY timestamp DESC
LIMIT 5;
```

**✅ Правильно:**
```
timestamp    | time                | close
1736614800   | 2026-01-12 10:33:00 | 90827.89
1736614740   | 2026-01-12 10:32:00 | 90749.90
```

**❌ Неправильно:**
```
timestamp       | time  | close
1736614800000   | ???   | 90827.89  # Миллисекунды!
```

### 1.2 Только закрытые свечи

```python
# Проверить в логах
docker-compose logs backend | grep "Last closed"

# Должно быть:
# "Last closed: 2026-01-12 10:32:00"  # ВСЕГДА -1 минута от текущей
```

**Test:**
```python
now = int(time.time())
last_closed = get_last_closed_candle_timestamp()
current_minute = (now // 60) * 60

assert last_closed == current_minute - 60
```

### 1.3 Округление до минут

```sql
SELECT COUNT(*) as bad_timestamps
FROM candles
WHERE timestamp % 60 != 0;

-- Должно быть: 0
```

---

## ✅ Проверка 2: Разделение Spot/Futures

### 2.1 Правильные символы

```sql
-- Проверить спот (БЕЗ ':')
SELECT symbol FROM tickers WHERE market = 'spot' LIMIT 5;
-- Должно быть: BTC/USDT, ETH/USDT, SOL/USDT

-- Проверить фьючерсы (С ':USDT')
SELECT symbol FROM tickers WHERE market = 'futures' LIMIT 5;
-- Должно быть: BTC/USDT:USDT, ETH/USDT:USDT, SOL/USDT:USDT
```

### 2.2 Нет смешивания данных

```sql
-- Проверить что нет дубликатов
SELECT symbol, market, COUNT(*) as cnt
FROM tickers
GROUP BY symbol, market
HAVING cnt > 1;

-- Должно быть: пусто (0 rows)
```

### 2.3 Оба рынка парсятся

```sql
SELECT market, COUNT(DISTINCT symbol) as symbols
FROM tickers
GROUP BY market;

-- Должно быть:
-- spot     | 500-600
-- futures  | 500-600
```

---

## ✅ Проверка 3: quoteVolume используется

### 3.1 Проверить в БД

```sql
SELECT symbol, market, volume_24h
FROM tickers
WHERE symbol = 'BTC/USDT' OR symbol = 'BTC/USDT:USDT'
ORDER BY market;
```

**✅ Правильно:** volume_24h в миллиардах USD (5,000,000,000)  
**❌ Неправильно:** volume_24h < 1000 (это baseVolume в BTC!)

### 3.2 Проверить в логах

```bash
docker-compose logs backend | grep "quoteVolume"
```

---

## ✅ Проверка 4: Алгоритм всплеска объёмов

### Test:

```python
# Создать тестовые данные
candles = [
    {'volume': 100000},  # 110 минут назад
    {'volume': 100000},
    # ... 9 свечей по 100k
    {'volume': 100000},  # 10 минут назад (начало current)
    {'volume': 500000},  # Current period - 10 минут
]

# Проверить расчёт
historical = candles[:-10]  # Первые 110 минут
current = candles[-10:]     # Последние 10 минут

total_historical = sum(c['volume'] for c in historical)  # 1,100,000
num_intervals = len(historical) / 10  # 11
average = total_historical / num_intervals  # 100,000

current_volume = sum(c['volume'] for c in current)  # 500,000
coefficient = current_volume / average  # 5.0

assert coefficient == 5.0  # ✅
```

**❌ Неправильно:**
```python
# Если включить current period в average
total = sum(all 120 candles)  # 1,600,000
average = total / 12  # 133,333
coefficient = 500000 / 133333  # 3.75 (НЕПРАВИЛЬНО!)
```

---

## ✅ Проверка 5: Синхронизация парсинга/проверки

### 5.1 Проверить последовательность в логах

```bash
docker-compose logs backend | grep "Cycle"

# Должно быть:
# "Cycle #1 started"
# "Step 1/3: Parsing..."
# "Step 2/3: Checking..."
# "Cycle #1 completed"
# ... пауза 5 минут ...
# "Cycle #2 started"
```

**❌ Неправильно:**
```
# Если видите оба одновременно
"Parsing started"
"Checking started"  # ← БЕЗ паузы!
```

### 5.2 Проверить в коде

```python
# engine.py должен быть:
async def _main_loop():
    await _parse_market_data()     # 1. Parse
    await asyncio.sleep(5)          # 2. Wait
    await _check_filters()          # 3. Check
    await asyncio.sleep(300)        # 4. Sleep

# НЕ должно быть двух параллельных циклов!
```

---

## ✅ Проверка 6: Retry механизм

### 6.1 Тест retry

```bash
# Отключить VPN
# Посмотреть логи
docker-compose logs backend -f

# Должно быть:
# "Attempt 1/3"
# "Network error: ..."
# "Retrying in 5.0s..."
# "Attempt 2/3"
# "Network error: ..."
# "Retrying in 10.0s..."
# "Attempt 3/3"
```

### 6.2 Проверить декоратор

```python
# exchange.py должен иметь:
@retry_on_network_error(max_attempts=3, delay_seconds=5.0)
async def fetch_spot_tickers():
    # ...
```

---

## ✅ Проверка 7: Логирование

### 7.1 DEBUG уровень работает

```bash
# Установить LOG_LEVEL=DEBUG в .env
# Перезапустить
docker-compose restart backend

# Проверить логи
docker-compose logs backend | grep DEBUG

# Должны быть детальные логи каждой проверки
```

### 7.2 Структура логов

```bash
docker-compose logs backend --tail=20

# Должен быть формат:
# YYYY-MM-DD HH:MM:SS | LEVEL | module:function:line | message
```

---

## ✅ Проверка 8: WebSocket

### 8.1 Проверить подключение

```javascript
// В браузере DevTools → Console
wsClient.ws.readyState
// Должно быть: 1 (OPEN)

// DevTools → Network → WS
// Должно быть соединение к /ws/triggers
```

### 8.2 Проверить broadcast

```bash
# Создать фильтр с низким порогом (0.1%)
# Подождать срабатывания

# В DevTools → Network → WS → Messages
# Должно прийти:
{
  "type": "trigger",
  "filter_id": 1,
  "symbol": "...",
  ...
}
```

---

## ✅ Проверка 9: Cooldown

### Test:

```sql
-- Создать 2 триггера для одного символа с разницей < 15 минут
INSERT INTO filter_triggers (filter_id, symbol, market, triggered_at)
VALUES (1, 'BTC/USDT', 'spot', strftime('%s', 'now') - 600);  -- 10 минут назад

-- Проверить cooldown
SELECT 
    symbol,
    triggered_at,
    datetime(triggered_at, 'unixepoch') as time,
    (strftime('%s', 'now') - triggered_at) as seconds_ago
FROM filter_triggers
WHERE filter_id = 1 AND symbol = 'BTC/USDT'
ORDER BY triggered_at DESC
LIMIT 2;

-- Если второй триггер < 900 секунд (15 мин) от первого → cooldown НЕ работает!
```

---

## ✅ Проверка 10: Telegram

### 10.1 Тест уведомления

```bash
curl -X POST http://localhost:8000/api/settings/test-telegram

# Должно прийти в Telegram:
# "✅ Тестовое уведомление от Crypto Screener"
```

### 10.2 Проверить формат

**Сообщение должно содержать:**
- 🚀 Emoji
- Название фильтра
- Символ
- Рынок (Spot/Futures)
- Изменение %
- Цена from → to
- Объём
- Timestamp
- 🔗 Ссылка на Bybit

---

## ✅ Проверка 11: БД индексы

```sql
-- Проверить индексы
SELECT name, tbl_name, sql
FROM sqlite_master
WHERE type = 'index';

-- Должны быть:
-- idx_candles_symbol_market_time
-- idx_candles_timestamp
-- idx_triggers_filter_symbol_time
-- idx_triggers_time
```

---

## ✅ Проверка 12: Docker

### 12.1 Healthcheck

```bash
curl http://localhost:8000/health

# Должно быть:
{
  "status": "healthy",
  "database": "connected",
  "screener": "running"
}
```

### 12.2 Volumes персистентны

```bash
# Остановить
docker-compose down

# Запустить снова
docker-compose up -d

# Проверить что данные сохранились
docker exec -it crypto_screener_backend sqlite3 /data/screener.db "SELECT COUNT(*) FROM candles;"

# Должно быть: > 0
```

---

## ✅ Проверка 13: Performance

### 13.1 Время парсинга

```bash
docker-compose logs backend | grep "Parsed.*symbols in"

# Должно быть < 600 секунд (10 минут)
# "Parsed 586 symbols in 268.3s"  ✅
```

### 13.2 Время проверки

```bash
docker-compose logs backend | grep "Found.*triggers in"

# Должно быть < 5 секунд
# "Found 3 triggers in 1.2s"  ✅
```

---

## 📋 Финальный чек-лист

### Критичные (MUST):

- [ ] Timestamps в секундах (10 цифр)
- [ ] Timestamps округлены до минут
- [ ] Только закрытые свечи
- [ ] Спот символы БЕЗ ':'
- [ ] Futures символы С ':USDT'
- [ ] quoteVolume используется
- [ ] Всплеск объёмов БЕЗ current в average
- [ ] Парсинг → wait → check (последовательно)
- [ ] Retry работает (3 попытки)
- [ ] Cooldown работает (15 минут)
- [ ] WebSocket подключается
- [ ] Telegram уведомления приходят

### Важные (SHOULD):

- [ ] Логирование детальное (DEBUG)
- [ ] Индексы БД созданы
- [ ] Healthcheck работает
- [ ] Volumes персистентны
- [ ] Performance < 10 мин парсинг
- [ ] Performance < 5 сек проверка

### Желательные (NICE TO HAVE):

- [ ] Makefile создан
- [ ] Диагностика скрипт работает
- [ ] Бэкапы настроены
- [ ] README актуален

---

## 🚨 Критические ошибки

**Если видите это - STOP и исправь:**

1. ❌ Timestamps в миллисекундах (13 цифр)
2. ❌ Спот и фьючерсы смешаны (нет разделения по market)
3. ❌ Используется baseVolume вместо quoteVolume
4. ❌ Current period включён в average (volume spike)
5. ❌ Параллельные циклы parse и check
6. ❌ Нет retry при NetworkError
7. ❌ Cooldown не работает (дубликаты < 15 мин)
8. ❌ WebSocket не подключается
9. ❌ Telegram не отправляет

---

## 🎯 Quick Validation Script

```bash
#!/bin/bash
# validate.sh - Быстрая проверка всех критичных моментов

echo "=== CRITICAL VALIDATION ==="

# 1. Check timestamps
echo "1. Checking timestamps..."
docker exec crypto_screener_backend sqlite3 /data/screener.db \
  "SELECT CASE WHEN MAX(LENGTH(timestamp)) = 10 THEN '✅ OK' ELSE '❌ FAIL' END FROM candles;"

# 2. Check markets
echo "2. Checking markets..."
docker exec crypto_screener_backend sqlite3 /data/screener.db \
  "SELECT market, COUNT(DISTINCT symbol) FROM tickers GROUP BY market;"

# 3. Check healthcheck
echo "3. Checking health..."
curl -s http://localhost:8000/health | jq .

# 4. Check WebSocket
echo "4. Checking WebSocket..."
curl -s --include \
  --no-buffer \
  --header "Connection: Upgrade" \
  --header "Upgrade: websocket" \
  --header "Sec-WebSocket-Version: 13" \
  --header "Sec-WebSocket-Key: test" \
  http://localhost:8000/ws/triggers \
  | head -1

# 5. Check logs for errors
echo "5. Recent errors:"
docker-compose logs backend --tail=100 | grep ERROR | tail -5

echo "=== VALIDATION COMPLETE ==="
```

---

**Используй этот чек-лист перед запуском в production!**

**Дата:** 2026-01-12  
**Статус:** Ready for validation
