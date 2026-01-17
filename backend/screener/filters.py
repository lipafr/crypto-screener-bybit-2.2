"""
Filters Module (WebSocket Mode) - WITH CHARTS SUPPORT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Filter checking logic adapted for WebSocket candle-based triggers.

KEY CHANGES:
- check_all_filters_for_symbol() - checks filters on candle close
- Uses only CLOSED candles from database
- Called by WebSocket manager at XX:XX:10 after candle finalization

CHARTS INTEGRATION:
- Adds trigger marks to cache on filter hits
- Broadcasts trigger marks via charts WebSocket
"""

import logging
import json
import time
from typing import Optional, List, Dict

from .database import Database
from .time_utils import get_last_closed_candle_timestamp, format_timestamp

# NEW: Import cache and charts WebSocket manager
from . import cache
from backend.api.websocket_charts import chart_manager

logger = logging.getLogger(__name__)


# ============================================
# Main Entry Point (called by WebSocket manager)
# ============================================

async def check_all_filters_for_symbol(
    symbol: str,
    closed_minute: int,
    db: Database
) -> List[Dict]:
    """
    Check all active filters for symbol after candle close.
    
    Called by WebSocket manager at XX:XX:10 after candle finalized.
    
    Args:
        symbol: Trading symbol
        closed_minute: Timestamp of closed minute
        db: Database instance
    
    Returns:
        List of triggered filter dicts
    """
    triggers = []
    
    try:
        # Get active filters for this symbol
        filters = await _get_active_filters_for_symbol(symbol, db)
        
        if not filters:
            return []
        
        logger.debug(
            f"Checking {len(filters)} filter(s) for {symbol} "
            f"at {format_timestamp(closed_minute)}"
        )
        
        # Check each filter
        for filter_obj in filters:
            try:
                # Extract market from config
                market = filter_obj['config'].get('market', 'spot')
                
                # Check cooldown
                in_cooldown = await _check_cooldown(
                    filter_id=filter_obj['id'],
                    symbol=symbol,
                    market=market,
                    cooldown_minutes=15,
                    db=db
                )
                
                if in_cooldown:
                    logger.debug(
                        f"[{filter_obj['name']}] {symbol}: ⏳ In cooldown, skipping"
                    )
                    continue
                
                # Check filter based on type
                result = None
                
                if filter_obj['type'] == 'price_change':
                    result = await check_price_change_filter(
                        symbol=symbol,
                        market=market,
                        filter_config=filter_obj['config'],
                        filter_name=filter_obj['name'],
                        db=db
                    )
                
                elif filter_obj['type'] == 'volume_spike':
                    result = await check_volume_spike_filter(
                        symbol=symbol,
                        market=market,
                        filter_config=filter_obj['config'],
                        filter_name=filter_obj['name'],
                        db=db
                    )
                
                # If triggered
                if result:
                    trigger_data = {
                        'filter_id': filter_obj['id'],
                        'filter_name': filter_obj['name'],
                        'symbol': symbol,
                        'market': market,
                        'data': result,
                        'timestamp': closed_minute
                    }
                    
                    triggers.append(trigger_data)
                    
                    # Save to DB
                    await _save_trigger(trigger_data, db)
                    
                    # ============================================
                    # NEW: Add trigger mark to cache
                    # ============================================
                    cache.add_trigger_mark(
                        symbol=symbol,
                        market=market,
                        trigger_data={
                            'timestamp': int(time.time()),
                            'filter_id': filter_obj['id'],
                            'filter_name': filter_obj['name'],
                            'filter_type': filter_obj['type']
                        }
                    )
                    
                    # ============================================
                    # NEW: Broadcast trigger mark via charts WebSocket
                    # ============================================
                    await chart_manager.broadcast_trigger_mark(
                        symbol=symbol,
                        market=market,
                        trigger_data={
                            'timestamp': int(time.time()),
                            'filter_name': filter_obj['name'],
                            'filter_type': filter_obj['type']
                        }
                    )
                    # ============================================
                    # END NEW CODE
                    # ============================================
                    
                    # Send Telegram notification
                    await _send_telegram_alert(trigger_data)
                    
                    logger.info(
                        f"🔥 [{filter_obj['name']}] {symbol}: TRIGGERED! "
                        f"Data: {result}"
                    )
            
            except Exception as e:
                logger.error(
                    f"Error checking filter {filter_obj['name']} for {symbol}: {e}"
                )
        
        return triggers
        
    except Exception as e:
        logger.error(f"Error checking filters for {symbol}: {e}")
        return []


# ============================================
# Filter Implementations
# ============================================

async def check_price_change_filter(
    symbol: str,
    market: str,
    filter_config: dict,
    filter_name: str,
    db: Database
) -> Optional[Dict]:
    """
    Check price change filter.
    
    Uses only CLOSED candles from database.
    
    Args:
        symbol: Trading symbol
        market: 'spot' or 'futures'
        filter_config: Filter configuration
        filter_name: Filter name (for logging)
        db: Database instance
    
    Returns:
        Trigger data dict if triggered, None otherwise
    """
    try:
        interval_minutes = filter_config['interval_minutes']
        min_change = filter_config['min_price_change_percent']
        direction = filter_config.get('direction', 'any')
        min_volume_24h = filter_config.get('min_volume_24h', 0)
        
        logger.debug(
            f"[{filter_name}] Checking {symbol} ({market}): "
            f"interval={interval_minutes}m, min_change={min_change}%, direction={direction}"
        )
        
        # Get candles from DB (only closed ones)
        candles = await db.get_candles(
            symbol=symbol,
            market=market,
            minutes=interval_minutes
        )
        
        if len(candles) < interval_minutes:
            logger.debug(
                f"[{filter_name}] {symbol}: Insufficient candles "
                f"(got {len(candles)}, need {interval_minutes})"
            )
            return None
        
        # Calculate price change
        first_candle = candles[0]
        last_candle = candles[-1]
        
        price_start = first_candle['open']
        price_end = last_candle['close']
        
        if price_start <= 0:
            logger.warning(f"[{filter_name}] {symbol}: Invalid start price {price_start}")
            return None
        
        change_pct = ((price_end - price_start) / price_start) * 100
        
        logger.debug(
            f"[{filter_name}] {symbol}: Price change = {change_pct:+.2f}% "
            f"(${price_start:.2f} → ${price_end:.2f})"
        )
        
        # Check direction
        triggered = False
        
        if direction == 'up' and change_pct >= min_change:
            triggered = True
        elif direction == 'down' and change_pct <= -min_change:
            triggered = True
        elif direction == 'any' and abs(change_pct) >= min_change:
            triggered = True
        
        if not triggered:
            logger.debug(
                f"[{filter_name}] {symbol}: ❌ Change too small "
                f"({change_pct:+.2f}% vs {min_change}%)"
            )
            return None
        
        # Check volume filter (if specified)
        if min_volume_24h > 0:
            # Get current ticker for 24h volume
            ticker = await db.get_ticker(symbol, market)
            
            if ticker:
                volume_24h = ticker.get('quote_volume', 0)
                
                if volume_24h < min_volume_24h:
                    logger.debug(
                        f"[{filter_name}] {symbol}: ❌ Volume too low "
                        f"(${volume_24h:,.0f} < ${min_volume_24h:,.0f})"
                    )
                    return None
        
        # TRIGGERED!
        logger.info(
            f"[{filter_name}] {symbol}: ✅ TRIGGERED! "
            f"Change: {change_pct:+.2f}% (${price_start:.2f} → ${price_end:.2f})"
        )
        
        return {
            'price_change_percent': round(change_pct, 2),
            'price_from': price_start,
            'price_to': price_end,
            'volume_24h': ticker.get('quote_volume', 0) if ticker else 0,
            'url': _get_bybit_url(symbol, market)
        }
    
    except Exception as e:
        logger.error(f"[{filter_name}] Error checking {symbol}: {e}")
        return None


async def check_volume_spike_filter(
    symbol: str,
    market: str,
    filter_config: dict,
    filter_name: str,
    db: Database
) -> Optional[Dict]:
    """
    Check volume spike filter.
    
    CRITICAL: Current period excluded from average calculation!
    
    Args:
        symbol: Trading symbol
        market: 'spot' or 'futures'
        filter_config: Filter configuration
        filter_name: Filter name
        db: Database instance
    
    Returns:
        Trigger data if triggered, None otherwise
    """
    try:
        short_period = filter_config['short_period_minutes']
        long_period = filter_config['long_period_minutes']
        spike_multiplier = filter_config['spike_multiplier']
        min_price_change = filter_config.get('min_price_change_percent', 0)
        
        logger.debug(
            f"[{filter_name}] Checking {symbol} ({market}): "
            f"short={short_period}m, long={long_period}m, multiplier={spike_multiplier}x"
        )
        
        # Get candles
        candles = await db.get_candles(
            symbol=symbol,
            market=market,
            minutes=long_period
        )
        
        if len(candles) < long_period:
            logger.debug(
                f"[{filter_name}] {symbol}: Insufficient candles "
                f"(got {len(candles)}, need {long_period})"
            )
            return None
        
        # CRITICAL: Split candles
        # Current period (last N minutes)
        current_candles = candles[-short_period:]
        
        # Historical period (everything EXCEPT current)
        historical_candles = candles[:-short_period]
        
        if len(historical_candles) < 1:
            logger.debug(f"[{filter_name}] {symbol}: No historical data")
            return None
        
        # Calculate volumes
        current_volume = sum(c['volume'] for c in current_candles)
        avg_volume = sum(c['volume'] for c in historical_candles) / len(historical_candles)
        
        if avg_volume <= 0:
            logger.debug(f"[{filter_name}] {symbol}: Zero average volume")
            return None
        
        # Calculate spike ratio
        spike_ratio = current_volume / avg_volume
        
        logger.debug(
            f"[{filter_name}] {symbol}: Volume spike = {spike_ratio:.2f}x "
            f"(current=${current_volume:,.0f}, avg=${avg_volume:,.0f})"
        )
        
        # Check if spike
        if spike_ratio < spike_multiplier:
            logger.debug(
                f"[{filter_name}] {symbol}: ❌ Spike too small "
                f"({spike_ratio:.2f}x < {spike_multiplier}x)"
            )
            return None
        
        # Check price change (if specified)
        if min_price_change > 0:
            price_start = current_candles[0]['open']
            price_end = current_candles[-1]['close']
            
            if price_start > 0:
                change_pct = abs((price_end - price_start) / price_start * 100)
                
                if change_pct < min_price_change:
                    logger.debug(
                        f"[{filter_name}] {symbol}: ❌ Price change too small "
                        f"({change_pct:.2f}% < {min_price_change}%)"
                    )
                    return None
        
        # TRIGGERED!
        logger.info(
            f"[{filter_name}] {symbol}: ✅ TRIGGERED! "
            f"Volume spike: {spike_ratio:.2f}x"
        )
        
        return {
            'volume_spike_ratio': round(spike_ratio, 2),
            'current_volume': current_volume,
            'average_volume': avg_volume,
            'period': short_period,
            'url': _get_bybit_url(symbol, market)
        }
    
    except Exception as e:
        logger.error(f"[{filter_name}] Error checking {symbol}: {e}")
        return None


# ============================================
# Helper Functions
# ============================================

async def _get_active_filters_for_symbol(symbol: str, db: Database) -> List[Dict]:
    """
    Get all active filters that apply to symbol.
    
    Args:
        symbol: Symbol
        db: Database
    
    Returns:
        List of filter dicts
    """
    result = await db.execute(
        """
        SELECT id, name, type, config, enabled
        FROM filters
        WHERE enabled = 1
        """
    )
    
    rows = await result.fetchall()
    
    filters = []
    for row in rows:
        filter_dict = dict(row)
        
        # Parse config JSON
        filter_dict['config'] = json.loads(filter_dict['config'])
        
        # Check if symbol is excluded
        excluded = filter_dict['config'].get('excluded_symbols', [])
        if symbol in excluded:
            continue
        
        filters.append(filter_dict)
    
    return filters


async def _check_cooldown(
    filter_id: int,
    symbol: str,
    market: str,
    cooldown_minutes: int,
    db: Database
) -> bool:
    """
    Check if filter is in cooldown for symbol.
    
    Args:
        filter_id: Filter ID
        symbol: Symbol
        market: Market
        cooldown_minutes: Cooldown period
        db: Database
    
    Returns:
        True if in cooldown
    """
    return await db.check_cooldown(
        filter_id=filter_id,
        symbol=symbol,
        market=market,
        cooldown_minutes=cooldown_minutes
    )


async def _save_trigger(trigger_data: Dict, db: Database):
    """
    Save trigger to database.
    
    Args:
        trigger_data: Trigger data dict
        db: Database
    """
    await db.save_trigger(
        filter_id=trigger_data['filter_id'],
        filter_name=trigger_data['filter_name'],
        symbol=trigger_data['symbol'],
        market=trigger_data['market'],
        data=trigger_data['data']
    )


def _get_bybit_url(symbol: str, market: str) -> str:
    """
    Generate Bybit trading URL for symbol.
    
    Args:
        symbol: Symbol (e.g. 'BTC/USDT' or 'BTC/USDT:USDT')
        market: Market type
    
    Returns:
        Bybit URL
    """
    # Clean symbol for URL
    if market == 'spot':
        # BTC/USDT → BTCUSDT
        clean_symbol = symbol.replace('/', '')
        return f"https://www.bybit.com/trade/spot/{clean_symbol}"
    else:
        # BTC/USDT:USDT → BTCUSDT
        clean_symbol = symbol.split(':')[0].replace('/', '')
        return f"https://www.bybit.com/trade/usdt/{clean_symbol}"


async def _send_telegram_alert(trigger_data: Dict):
    """
    Send Telegram alert for trigger.
    
    This is a wrapper to get the global notifier instance.
    
    Args:
        trigger_data: Trigger data dict
    """
    try:
        # Import here to avoid circular dependency
        from .engine import get_engine
        
        engine = get_engine()
        if engine and engine.notifier:
            await engine.notifier.send_trigger_notification(
                filter_name=trigger_data['filter_name'],
                symbol=trigger_data['symbol'],
                market=trigger_data['market'],
                trigger_data=trigger_data['data']
            )
        else:
            logger.warning("No telegram notifier available")
    
    except Exception as e:
        logger.error(f"Failed to send telegram notification: {e}")