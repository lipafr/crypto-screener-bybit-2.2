"""
WebSocket Manager - Simplified Version
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Real-time ticker monitoring via ccxt.pro WebSocket.

ARCHITECTURE:
1. Watch tickers via ccxt.pro
2. Build 1-min candles from ticker updates
3. Check filters on candle close
4. Send notifications

CRITICAL: Uses ccxt.pro for WebSocket support!
"""

import asyncio
import logging
from typing import Dict, Set, Optional, List
from datetime import datetime, timezone

from .time_utils import (
    get_current_timestamp,
    get_current_minute_timestamp,
    round_to_minute,
    format_timestamp
)
from .database import Database

logger = logging.getLogger(__name__)


# ============================================
# Candle Builder
# ============================================

class CandleBuilder:
    """Builds 1-minute candles from ticker stream."""
    
    def __init__(self, symbol: str, market: str):
        self.symbol = symbol
        self.market = market
        self.current_candle: Optional[Dict] = None
        self.current_minute_start: Optional[int] = None
    
    def update(self, timestamp: int, price: float, volume_24h: float):
        """Update candle with new tick."""
        minute_start = round_to_minute(timestamp)
        
        # New candle?
        if self.current_minute_start != minute_start:
            self.current_minute_start = minute_start
            self.current_candle = {
                'timestamp': minute_start,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 0,  # Will accumulate
                'tick_count': 0
            }
        
        # Update current candle
        if self.current_candle:
            self.current_candle['high'] = max(self.current_candle['high'], price)
            self.current_candle['low'] = min(self.current_candle['low'], price)
            self.current_candle['close'] = price
            self.current_candle['tick_count'] += 1
    
    def finalize(self, timestamp: int) -> Optional[Dict]:
        """Finalize candle for given minute."""
        if not self.current_candle:
            return None
        
        if self.current_candle['timestamp'] != timestamp:
            return None
        
        return self.current_candle.copy()


# ============================================
# WebSocket Manager
# ============================================

class WebSocketManager:
    """
    Manages WebSocket ticker streams and candle building.
    
    Uses ccxt.pro for real-time data.
    """
    
    def __init__(
        self,
        exchange,  # BybitExchange instance
        database: Database,
        check_delay_seconds: int = 10
    ):
        self.exchange = exchange
        self.db = database
        self.check_delay_seconds = check_delay_seconds
        
        # Candle builders per symbol
        self.candle_builders: Dict[str, CandleBuilder] = {}
        
        # Active tasks
        self.watch_tasks: Dict[str, asyncio.Task] = {}
        
        # Running flag
        self.running = False
        
        logger.info("✅ WebSocketManager initialized (ccxt.pro)")
    
    async def start(self, symbols: List[str], markets: Dict[str, str]):
        """
        Start WebSocket monitoring.
        
        Args:
            symbols: List of symbols to watch
            markets: Dict mapping symbol to market type
        """
        if not symbols:
            logger.warning("No symbols to watch")
            return
        
        self.running = True
        
        logger.info(f"📡 Starting WebSocket watch for {len(symbols)} symbols...")
        
        try:
            # Group symbols by market type
            spot_symbols = [s for s in symbols if markets.get(s) == 'spot']
            futures_symbols = [s for s in symbols if markets.get(s) == 'futures']
            
            logger.info(f"📊 Spot: {len(spot_symbols)}, Futures: {len(futures_symbols)}")
            
            # Create watch tasks for each symbol
            tasks = []
            
            for symbol in spot_symbols:
                task = asyncio.create_task(self._watch_symbol(symbol, 'spot'))
                self.watch_tasks[symbol] = task
                tasks.append(task)
            
            for symbol in futures_symbols:
                task = asyncio.create_task(self._watch_symbol(symbol, 'futures'))
                self.watch_tasks[symbol] = task
                tasks.append(task)
            
            # Also start scheduler task
            scheduler_task = asyncio.create_task(self._candle_close_scheduler())
            tasks.append(scheduler_task)
            
            # Wait for all tasks
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except asyncio.CancelledError:
            logger.info("WebSocket manager cancelled")
        except Exception as e:
            logger.error(f"Fatal error in WebSocket manager: {e}", exc_info=True)
        finally:
            await self.stop()
    
    async def _watch_symbol(self, symbol: str, market: str):
        """
        Watch single symbol via WebSocket.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
        """
        # Create candle builder
        builder = CandleBuilder(symbol, market)
        self.candle_builders[symbol] = builder
        
        logger.info(f"📡 Watching {symbol} ({market})...")
        
        retry_count = 0
        max_retries = 5
        
        while self.running:
            try:
                # Watch ticker via ccxt.pro
                ticker = await self.exchange.watch_ticker(symbol, market)
                
                # Reset retry count on success
                retry_count = 0
                
                # Extract data
                timestamp = get_current_timestamp()
                price = ticker.get('last', 0)
                volume_24h = ticker.get('quoteVolume', 0)
                
                if price > 0:
                    # Update candle builder
                    builder.update(timestamp, price, volume_24h)
                    
                    # Also save ticker to database
                    await self.db.save_ticker(symbol, market, volume_24h, price)
                
            except asyncio.CancelledError:
                logger.info(f"Watch cancelled for {symbol}")
                break
            
            except Exception as e:
                retry_count += 1
                
                if retry_count >= max_retries:
                    logger.error(f"❌ Max retries reached for {symbol}. Stopping watch.")
                    break
                
                logger.warning(
                    f"⚠️ WebSocket error for {symbol} (error {retry_count}/{max_retries}): {e}"
                )
                
                # Exponential backoff
                delay = min(2 ** retry_count, 60)
                logger.info(f"Retrying {symbol} in {delay}s...")
                await asyncio.sleep(delay)
    
    async def _candle_close_scheduler(self):
        """
        Scheduler that triggers filter checks when candles close.
        
        Runs every minute at XX:XX:10 (10 seconds after minute change).
        """
        logger.info("🕐 Candle close scheduler started")
        
        while self.running:
            try:
                # Wait until next minute + delay
                now = get_current_timestamp()
                current_minute = get_current_minute_timestamp()
                next_minute = current_minute + 60
                next_check = next_minute + self.check_delay_seconds
                
                sleep_seconds = next_check - now
                
                if sleep_seconds > 0:
                    logger.debug(f"⏰ Sleeping {sleep_seconds}s until next candle check...")
                    await asyncio.sleep(sleep_seconds)
                
                # Candle just closed - process all symbols
                closed_minute = current_minute
                
                logger.info(f"🔔 Candle closed: {format_timestamp(closed_minute)}. Processing...")
                
                # Finalize and check all candles
                await self._process_closed_candles(closed_minute)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler: {e}", exc_info=True)
                await asyncio.sleep(60)
        
        logger.info("🛑 Candle close scheduler stopped")
    
    async def _process_closed_candles(self, closed_minute: int):
        """
        Process all closed candles and trigger filter checks.
        
        Args:
            closed_minute: Timestamp of the closed minute
        """
        symbols_to_check = []
        
        for symbol, builder in self.candle_builders.items():
            # Finalize candle
            candle = builder.finalize(closed_minute)
            
            if candle:
                # Save to database
                await self.db.save_candle(
                    symbol,
                    builder.market,
                    candle['timestamp'],
                    candle['open'],
                    candle['high'],
                    candle['low'],
                    candle['close'],
                    candle.get('volume', 0)
                )
                
                symbols_to_check.append((symbol, builder.market))
                
                logger.debug(
                    f"✅ {symbol}: Candle saved "
                    f"O={candle['open']:.2f} H={candle['high']:.2f} "
                    f"L={candle['low']:.2f} C={candle['close']:.2f}"
                )
        
        if symbols_to_check:
            logger.info(f"🔍 Checking filters for {len(symbols_to_check)} symbols...")
            
            # Import here to avoid circular dependency
            from .filters import check_all_filters_for_symbol
            
            # Check filters for each symbol
            for symbol, market in symbols_to_check:
                try:
                    await check_all_filters_for_symbol(
                        self.db,
                        symbol,
                        market
                    )
                except Exception as e:
                    logger.error(f"Error checking filters for {symbol}: {e}")
    
    async def stop(self):
        """Stop WebSocket manager."""
        if not self.running:
            return
        
        logger.info("🛑 Stopping WebSocket manager...")
        
        self.running = False
        
        # Cancel all watch tasks
        for symbol, task in self.watch_tasks.items():
            if not task.done():
                task.cancel()
        
        # Wait for tasks to finish
        if self.watch_tasks:
            await asyncio.gather(*self.watch_tasks.values(), return_exceptions=True)
        
        logger.info("✅ WebSocket manager stopped")


# ============================================
# Factory Function
# ============================================

def create_websocket_manager(
    exchange,
    database: Database,
    check_delay_seconds: int = 10
) -> WebSocketManager:
    """
    Create WebSocket manager instance.
    
    Args:
        exchange: BybitExchange instance
        database: Database instance
        check_delay_seconds: Delay after candle close
    
    Returns:
        WebSocketManager instance
    """
    return WebSocketManager(exchange, database, check_delay_seconds)
