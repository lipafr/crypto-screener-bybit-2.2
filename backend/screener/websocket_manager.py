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
        self.previous_candle: Optional[Dict] = None
        self.current_minute_start: Optional[int] = None
    
    def update(self, timestamp: int, price: float, volume_24h: float):
        """Update candle with new tick."""
        minute_start = round_to_minute(timestamp)
        
        # New candle?
        if self.current_minute_start != minute_start:
            # Save current as previous before creating new
            if self.current_candle:
                self.previous_candle = self.current_candle.copy()
            
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
        # Return previous candle if it matches the requested timestamp
        if self.previous_candle and self.previous_candle['timestamp'] == timestamp:
            return self.previous_candle.copy()
        
        # Fallback: check current candle
        if self.current_candle and self.current_candle['timestamp'] == timestamp:
            return self.current_candle.copy()
        
        return None


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
            
            # Start scheduler task FIRST (parallel with gap filling)
            logger.info("🕐 Starting candle close scheduler...")
            scheduler_task = asyncio.create_task(self._candle_close_scheduler())
            
            # STEP 1: Fill initial gaps AND start WebSocket incrementally
            logger.info("📥 Filling initial historical data (last 2 hours)...")
            gap_fill_task = asyncio.create_task(
                self._fill_gaps_and_start_websockets(spot_symbols, futures_symbols)
            )
            
            # Wait for both tasks (runs forever)
            await asyncio.gather(scheduler_task, gap_fill_task)
            
        except asyncio.CancelledError:
            logger.info("WebSocket manager cancelled")
        except Exception as e:
            logger.error(f"Fatal error in WebSocket manager: {e}", exc_info=True)
        finally:
            await self.stop()
    
    # ============================================
    # Gap Filling
    # ============================================
    
    async def _fill_gaps_and_start_websockets(self, spot_symbols: List[str], futures_symbols: List[str]):
        """
        Fill gaps AND start WebSocket incrementally (batch by batch).
        
        This allows data collection to begin immediately for first symbols
        while still filling history for remaining symbols.
        
        Args:
            spot_symbols: List of spot symbols
            futures_symbols: List of futures symbols
        """
        from .time_utils import get_current_timestamp
        
        now = get_current_timestamp()
        since = now - (2 * 60 * 60)  # 2 hours ago
        
        all_symbols = [
            (s, 'spot') for s in spot_symbols
        ] + [
            (s, 'futures') for s in futures_symbols
        ]
        
        total_filled = 0
        total_errors = 0
        
        # Process in batches
        BATCH_SIZE = 10
        BATCH_DELAY = 0.5
        
        for i in range(0, len(all_symbols), BATCH_SIZE):
            batch = all_symbols[i:i + BATCH_SIZE]
            
            # Fill gaps for this batch (parallel)
            fill_tasks = [
                self._fill_gap_for_symbol(symbol, market, since, now)
                for symbol, market in batch
            ]
            
            results = await asyncio.gather(*fill_tasks, return_exceptions=True)
            
            # Count results
            for result in results:
                if isinstance(result, int):
                    total_filled += result
                else:
                    total_errors += 1
            
            # Start WebSocket for this batch (parallel)
            for symbol, market in batch:
                if symbol not in self.watch_tasks:
                    task = asyncio.create_task(self._watch_symbol(symbol, market))
                    self.watch_tasks[symbol] = task
            
            # Progress
            processed = min(i + BATCH_SIZE, len(all_symbols))
            logger.info(
                f"   📊 {processed}/{len(all_symbols)} symbols: "
                f"filled {total_filled} candles, started {len(self.watch_tasks)} WebSockets"
            )
            
            # Delay between batches
            if i + BATCH_SIZE < len(all_symbols):
                await asyncio.sleep(BATCH_DELAY)
        
        logger.info(
            f"✅ Complete: {total_filled} candles filled, "
            f"{len(self.watch_tasks)} WebSockets active ({total_errors} errors)"
        )
    
    async def _fill_gap_for_symbol(
        self, 
        symbol: str, 
        market: str, 
        start_time: int, 
        end_time: int
    ) -> int:
        """
        Fill missing candles for a symbol using REST API.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            start_time: Start timestamp
            end_time: End timestamp
        
        Returns:
            Number of candles filled
        """
        try:
            # Fetch OHLCV data via REST (last 120 candles = 2 hours)
            ohlcv = await self.exchange.fetch_ohlcv(
                symbol, market, '1m', limit=120
            )
            
            if not ohlcv:
                return 0
            
            candles_saved = 0
            
            for candle in ohlcv:
                # OHLCV returned as dict from our exchange wrapper
                timestamp = candle['timestamp']
                
                # Skip if too old or too new
                if timestamp < start_time or timestamp >= end_time:
                    continue
                
                # Check if candle already exists
                existing = await self.db.execute(
                    "SELECT 1 FROM candles WHERE symbol = ? AND market = ? AND timestamp = ?",
                    (symbol, market, timestamp)
                )
                if await existing.fetchone():
                    continue  # Already exists
                
                # Save candle
                await self.db.save_candle(
                    symbol, market,
                    timestamp,
                    float(candle['open']),
                    float(candle['high']),
                    float(candle['low']),
                    float(candle['close']),
                    float(candle['volume'])
                )
                candles_saved += 1
            
            if candles_saved > 0:
                logger.debug(f"📥 {symbol} ({market}): Filled {candles_saved} candles")
            
            return candles_saved
            
        except Exception as e:
            logger.error(
                f"Error fetching OHLCV for {symbol} ({market}): "
                f"{type(e).__name__}: {e}",
                exc_info=True
            )
            return 0
    
    async def _detect_and_fill_gap(
        self,
        symbol: str,
        market: str,
        builder: 'CandleBuilder',
        current_timestamp: int
    ):
        """
        Detect and fill gaps in real-time.
        
        If we detect missing candles (e.g. WebSocket was disconnected),
        fill them via REST API.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            builder: CandleBuilder instance
            current_timestamp: Current timestamp
        """
        from .time_utils import round_to_minute
        
        # Skip if this is first update
        if not builder.previous_candle:
            return
        
        current_minute = round_to_minute(current_timestamp)
        last_minute = builder.previous_candle['timestamp']
        
        # Calculate gap
        expected_minutes = (current_minute - last_minute) // 60
        
        # If gap > 1 minute, fill it
        if expected_minutes > 1:
            logger.warning(
                f"⚠️ Gap detected for {symbol}: {expected_minutes} minutes missing!"
            )
            
            # Fill gap from last_minute to current_minute
            gap_start = last_minute + 60
            gap_end = current_minute
            
            filled = await self._fill_gap_for_symbol(
                symbol, market, gap_start, gap_end
            )
            
            if filled > 0:
                logger.info(f"✅ {symbol}: Filled {filled} missing candles")
    
    # ============================================
    # WebSocket Watching
    # ============================================
    
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
                
                if price and price > 0:
                    # Check for gaps (missing candles)
                    await self._detect_and_fill_gap(symbol, market, builder, timestamp)
                    
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
        try:
            logger.info(f"📊 Processing {len(self.candle_builders)} symbols...")
            
            symbols_to_check = []
            candles_saved = 0
            
            for symbol, builder in self.candle_builders.items():
                try:
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
                        
                        # ============================================
                        # NEW: Update cache and broadcast via WebSocket
                        # ============================================
                        logger.info(f"🔄 About to update cache for {symbol}...")
                        try:
                            from . import cache
                            from backend.api.websocket_charts import chart_manager
                            
                            logger.info(f"📦 Updating cache for {symbol}...")
                            # Update cache
                            cache.update_candle(
                                symbol=symbol,
                                market=builder.market,
                                candle={
                                    'timestamp': candle['timestamp'],
                                    'open': candle['open'],
                                    'high': candle['high'],
                                    'low': candle['low'],
                                    'close': candle['close'],
                                    'volume': candle.get('volume', 0)
                                }
                            )
                            
                            logger.info(f"📡 Broadcasting via WebSocket for {symbol}...")
                            # Broadcast via charts WebSocket
                            await chart_manager.broadcast_candle_update(
                                symbol,  # позиционный аргумент
                                builder.market,  # позиционный аргумент  
                                {  # позиционный аргумент
                                    'timestamp': candle['timestamp'],
                                    'open': candle['open'],
                                    'high': candle['high'],
                                    'low': candle['low'],
                                    'close': candle['close'],
                                    'volume': candle.get('volume', 0)
                                }
                            )
                            
                            logger.info(f"✅ Cache & WebSocket updated for {symbol}")
                        except Exception as cache_error:
                            logger.error(f"❌ Error updating cache/WS for {symbol}: {cache_error}", exc_info=True)
                        # ============================================
                        # END NEW CODE
                        # ============================================
                        
                        symbols_to_check.append((symbol, builder.market))
                        candles_saved += 1
                        
                        logger.info(
                            f"✅ {symbol}: Candle saved "
                            f"O={candle['open']:.4f} H={candle['high']:.4f} "
                            f"L={candle['low']:.4f} C={candle['close']:.4f}"
                        )
                    else:
                        logger.debug(f"⏭️ {symbol}: No candle to finalize")
                        
                except Exception as e:
                    logger.error(f"Error processing candle for {symbol}: {e}", exc_info=True)
            
            logger.info(f"💾 Saved {candles_saved}/{len(self.candle_builders)} candles")
            
            if symbols_to_check:
                logger.info(f"🔍 Checking filters for {len(symbols_to_check)} symbols...")
                
                # Import here to avoid circular dependency
                from .filters import check_all_filters_for_symbol
                
                # Check filters for each symbol
                for symbol, market in symbols_to_check:
                    try:
                        # CRITICAL: Correct parameter order!
                        await check_all_filters_for_symbol(
                            symbol=symbol,
                            closed_minute=closed_minute,
                            db=self.db
                        )
                    except Exception as e:
                        logger.error(f"Error checking filters for {symbol}: {e}", exc_info=True)
            else:
                logger.warning("⚠️ No candles to check (all builders returned None)")
                
        except Exception as e:
            logger.error(f"Error in _process_closed_candles: {e}", exc_info=True)
    
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