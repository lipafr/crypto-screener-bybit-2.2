"""
Модуль кэширования свечей в памяти для быстрого доступа.

Хранит последние 2 часа свечей для каждого символа и рынка.
"""

import logging
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import time

logger = logging.getLogger(__name__)

# Глобальный кэш: {(symbol, market): [candles]}
_candles_cache: Dict[Tuple[str, str], List[dict]] = {}

# Кэш меток фильтров: {(symbol, market): [triggers]}
_triggers_cache: Dict[Tuple[str, str], List[dict]] = {}

# Lock для thread-safe операций (на случай будущих расширений)
_cache_lock = None

# Константы
MAX_CANDLES_IN_CACHE = 120  # 2 часа минутных свечей


def init_cache():
    """Инициализация кэша."""
    global _candles_cache, _triggers_cache
    _candles_cache = {}
    _triggers_cache = {}
    logger.info("📦 Cache initialized")


def get_candles(symbol: str, market: str) -> List[dict]:
    """
    Получить свечи из кэша.
    
    Args:
        symbol: Символ ('BTC/USDT' или 'BTC/USDT:USDT')
        market: Рынок ('spot' или 'futures')
    
    Returns:
        Список свечей [{timestamp, open, high, low, close, volume}, ...]
    """
    key = (symbol, market)
    return _candles_cache.get(key, [])


def update_candle(symbol: str, market: str, candle: dict):
    """
    Обновить или добавить свечу в кэш.
    
    Args:
        symbol: Символ
        market: Рынок
        candle: Данные свечи {timestamp, open, high, low, close, volume}
    """
    key = (symbol, market)
    
    if key not in _candles_cache:
        _candles_cache[key] = []
    
    candles = _candles_cache[key]
    
    # Проверяем, есть ли уже свеча с таким timestamp
    existing_index = None
    for i, c in enumerate(candles):
        if c['timestamp'] == candle['timestamp']:
            existing_index = i
            break
    
    if existing_index is not None:
        # Обновляем существующую свечу
        candles[existing_index] = candle
    else:
        # Добавляем новую свечу
        candles.append(candle)
        # Сортируем по timestamp
        candles.sort(key=lambda x: x['timestamp'])
    
    # Ограничиваем размер кэша (только последние 120 свечей)
    if len(candles) > MAX_CANDLES_IN_CACHE:
        _candles_cache[key] = candles[-MAX_CANDLES_IN_CACHE:]
    
    logger.debug(f"📦 Cache updated for {symbol} ({market}): {len(_candles_cache[key])} candles")


def bulk_update_candles(symbol: str, market: str, candles: List[dict]):
    """
    Массовое обновление свечей в кэше (например, при загрузке из БД).
    
    Args:
        symbol: Символ
        market: Рынок
        candles: Список свечей
    """
    key = (symbol, market)
    
    # Сортируем по timestamp
    sorted_candles = sorted(candles, key=lambda x: x['timestamp'])
    
    # Берём только последние 120
    _candles_cache[key] = sorted_candles[-MAX_CANDLES_IN_CACHE:]
    
    logger.debug(f"📦 Bulk cache update for {symbol} ({market}): {len(_candles_cache[key])} candles")


def get_all_symbols() -> List[Tuple[str, str]]:
    """
    Получить список всех символов в кэше.
    
    Returns:
        Список кортежей [(symbol, market), ...]
    """
    return list(_candles_cache.keys())


def add_trigger_mark(symbol: str, market: str, trigger_data: dict):
    """
    Добавить метку срабатывания фильтра.
    
    Args:
        symbol: Символ
        market: Рынок
        trigger_data: {timestamp, filter_id, filter_name, filter_type}
    """
    key = (symbol, market)
    
    if key not in _triggers_cache:
        _triggers_cache[key] = []
    
    _triggers_cache[key].append(trigger_data)
    
    # Чистим старые метки (старше 2 часов)
    cutoff = int(time.time()) - 7200
    _triggers_cache[key] = [t for t in _triggers_cache[key] if t['timestamp'] > cutoff]
    
    logger.debug(f"📌 Trigger mark added for {symbol} ({market})")


def get_trigger_marks(symbol: str, market: str) -> List[dict]:
    """
    Получить метки срабатываний фильтров.
    
    Args:
        symbol: Символ
        market: Рынок
    
    Returns:
        Список меток [{timestamp, filter_id, filter_name, filter_type}, ...]
    """
    key = (symbol, market)
    return _triggers_cache.get(key, [])


def clear_cache():
    """Очистить весь кэш."""
    global _candles_cache, _triggers_cache
    _candles_cache = {}
    _triggers_cache = {}
    logger.info("🗑️ Cache cleared")


def get_cache_stats() -> dict:
    """
    Получить статистику по кэшу.
    
    Returns:
        {total_symbols, total_candles, memory_usage_mb}
    """
    total_symbols = len(_candles_cache)
    total_candles = sum(len(candles) for candles in _candles_cache.values())
    total_triggers = sum(len(triggers) for triggers in _triggers_cache.values())
    
    return {
        'total_symbols': total_symbols,
        'total_candles': total_candles,
        'total_triggers': total_triggers,
    }
