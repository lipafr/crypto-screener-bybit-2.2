"""
API endpoints для работы с графиками (свечи, тикеры).
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.screener import cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["charts"])


class CandleData(BaseModel):
    """Модель для свечи в формате Lightweight Charts."""
    time: int  # Unix timestamp в секундах
    open: float
    high: float
    low: float
    close: float
    volume: float


class TriggerMark(BaseModel):
    """Модель для метки срабатывания фильтра."""
    time: int  # Unix timestamp
    filter_name: str
    filter_type: str


class ChartDataResponse(BaseModel):
    """Ответ с данными для графика."""
    symbol: str
    market: str
    timeframe: str
    candles: List[CandleData]
    triggers: List[TriggerMark]


@router.get("/candles", response_model=ChartDataResponse)
async def get_candles_for_chart(
    symbol: str = Query(..., description="Symbol (e.g., 'BTC/USDT' or 'BTCUSDT')"),
    market: str = Query(..., description="Market type: 'spot' or 'futures'"),
    timeframe: str = Query(default="1m", regex="^(1m|5m|15m|30m|1h)$")
):
    """
    Получить свечи для графика.
    
    Args:
        symbol: Символ (например, 'BTC/USDT' или 'BTCUSDT')
        market: Рынок ('spot' или 'futures')
        timeframe: Таймфрейм ('1m', '5m', '15m', '30m', '1h')
    
    Returns:
        Данные для графика с свечами и метками фильтров
    """
    # Нормализация символа
    if market == "spot":
        if ":" in symbol:
            symbol = symbol.split(":")[0]
        if "/" not in symbol:
            symbol = f"{symbol[:3]}/{symbol[3:]}"  # BTC/USDT
    else:  # futures
        if ":" not in symbol:
            if "/" in symbol:
                base, quote = symbol.split("/")
                symbol = f"{base}/{quote}:{quote}"
            else:
                symbol = f"{symbol[:3]}/{symbol[3:]}:{symbol[3:]}"
    
    logger.info(f"📊 Fetching candles for {symbol} ({market}) @ {timeframe}")
    
    # Получаем свечи из кэша
    candles_data = cache.get_candles(symbol, market)
    
    # Если кэш пуст, пытаемся загрузить из БД
    if not candles_data:
        logger.warning(f"⚠️ Cache miss for {symbol} ({market}), loading from DB...")
        
        # Получаем Database инстанс из app.state
        from fastapi import Request
        from backend.main import app
        
        if hasattr(app.state, 'db'):
            db = app.state.db
            
            # Получаем свечи из БД через метод класса Database
            db_candles = await db.get_candles(symbol, market, minutes=120)
            
            if not db_candles:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data available for {symbol} ({market}). The screener may not have started monitoring this symbol yet."
                )
            
            # Формируем данные для кэша
            # db_candles возвращает список словарей с ключами: timestamp, open, high, low, close, volume
            candles_data = [
                {
                    'timestamp': c['timestamp'],
                    'open': c['open'],
                    'high': c['high'],
                    'low': c['low'],
                    'close': c['close'],
                    'volume': c['volume']
                }
                for c in db_candles
            ]
            
            # Обновляем кэш
            cache.bulk_update_candles(symbol, market, candles_data)
        else:
            raise HTTPException(
                status_code=500,
                detail="Database not available"
            )
    
    # Агрегация если нужен таймфрейм больше 1m
    if timeframe != "1m":
        candles_data = _aggregate_candles(candles_data, timeframe)
    
    # Формируем ответ в формате Lightweight Charts
    candles_response = [
        CandleData(
            time=c['timestamp'],
            open=c['open'],
            high=c['high'],
            low=c['low'],
            close=c['close'],
            volume=c['volume']
        )
        for c in candles_data
    ]
    
    # Получаем метки срабатываний фильтров
    trigger_marks_data = cache.get_trigger_marks(symbol, market)
    triggers_response = [
        TriggerMark(
            time=t['timestamp'],
            filter_name=t['filter_name'],
            filter_type=t['filter_type']
        )
        for t in trigger_marks_data
    ]
    
    logger.info(f"✅ Returning {len(candles_response)} candles and {len(triggers_response)} triggers")
    
    return ChartDataResponse(
        symbol=symbol,
        market=market,
        timeframe=timeframe,
        candles=candles_response,
        triggers=triggers_response
    )


@router.get("/symbols", response_model=List[dict])
async def get_available_symbols():
    """
    Получить список всех доступных символов в кэше.
    
    Returns:
        Список символов с рынками [{'symbol': 'BTC/USDT', 'market': 'spot'}, ...]
    """
    symbols_data = cache.get_all_symbols()
    
    return [
        {'symbol': symbol, 'market': market}
        for symbol, market in symbols_data
    ]


def _aggregate_candles(candles: List[dict], timeframe: str) -> List[dict]:
    """
    Агрегировать минутные свечи в более крупные таймфреймы.
    
    Args:
        candles: Список минутных свечей
        timeframe: Целевой таймфрейм ('5m', '15m', '30m', '1h')
    
    Returns:
        Агрегированные свечи
    """
    # Определяем интервал в минутах
    interval_map = {
        '5m': 5,
        '15m': 15,
        '30m': 30,
        '1h': 60
    }
    
    interval_minutes = interval_map.get(timeframe, 1)
    
    if interval_minutes == 1:
        return candles
    
    aggregated = []
    current_group = []
    
    for candle in candles:
        timestamp = candle['timestamp']
        
        # Определяем к какому интервалу относится свеча
        interval_start = (timestamp // (interval_minutes * 60)) * (interval_minutes * 60)
        
        # Если это новый интервал и есть накопленная группа
        if current_group and current_group[0]['interval_start'] != interval_start:
            # Агрегируем накопленную группу
            aggregated.append(_merge_candles(current_group))
            current_group = []
        
        # Добавляем метку интервала
        candle_copy = candle.copy()
        candle_copy['interval_start'] = interval_start
        current_group.append(candle_copy)
    
    # Агрегируем последнюю группу
    if current_group:
        aggregated.append(_merge_candles(current_group))
    
    return aggregated


def _merge_candles(candles_group: List[dict]) -> dict:
    """
    Объединить группу свечей в одну.
    
    Args:
        candles_group: Группа свечей для объединения
    
    Returns:
        Агрегированная свеча
    """
    if not candles_group:
        return {}
    
    first_candle = candles_group[0]
    last_candle = candles_group[-1]
    
    return {
        'timestamp': first_candle['interval_start'],
        'open': first_candle['open'],
        'high': max(c['high'] for c in candles_group),
        'low': min(c['low'] for c in candles_group),
        'close': last_candle['close'],
        'volume': sum(c['volume'] for c in candles_group)
    }