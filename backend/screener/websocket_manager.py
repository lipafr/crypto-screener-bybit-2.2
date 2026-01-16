"""
WebSocket Manager Module
~~~~~~~~~~~~~~~~~~~~~~~~

CRITICAL: WebSocket-based data streaming with candle building.

This module replaces REST API polling with real-time WebSocket updates.

KEY FEATURES:
1. Real-time ticker updates via WebSocket
2. Build 1-minute candles from ticker stream
3. Trigger filter checks on candle close (XX:XX:10)
4. Gap recovery via REST API fallback
5. All data written to database (no in-memory cache)

ARCHITECTURE:
WebSocket Stream → CandleBuilder → DB → Filter Check (on close) → Telegram
"""

import ccxt.async_support as ccxt
import asyncio
import time
import logging
from typing import Optional, Dict, Set
from datetime import datetime, timezone

from .time_utils import (
    get_current_timestamp,
    get_current_minute_timestamp,
    get_last_closed_candle_timestamp,
    round_to_minute,
    format_timestamp
)
from .database import Database

logger = logging.getLogger(__name__)


# ============================================
# CandleBuilder - Build candles from tickers
# ============================================

class CandleBuilder:
    """
    Builds 1-minute candles from ticker stream.
    
    Each symbol has its own builder that accumulates
    ticks during the minute and finalizes on close.
    """
    
    def __init__(self, symbol: str, market: str):
        """
        Initialize candle builder.
        
        Args:
            symbol: Trading pair (e.g. 'BTC/USDT')
            market: 'spot' or 'futures'
        """
        self.symbol = symbol
        self.market = market
        
        # Current building candle
        self.current_candle: Optional[Dict] = None
        self.current_minute_start: Optional[int] = None
        
        # Stats
        self.tick_count = 0
    
    def update(self, timestamp: int, price: float, volume_24h: float):
        """
        Update candle with new tick.
        
        Args:
            timestamp: Current minute start (rounded)
            price: Current price
            volume_24h: 24h quote volume (for tracking)
        """
        # Check if new minute started
        if self.current_minute_start != timestamp:
            if self.current_candle:
                logger.debug(
                    f"{self.symbol}: Minute {format_timestamp(self.current_minute_start)} "
                    f"closed with {self.tick_count} ticks"
                )
            
            # Start new candle
            self.current_minute_start = timestamp
            self.current_candle = {
                'symbol': self.symbol,
                'market': self.market,
                'timestamp': timestamp,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 0,  # Will calculate from volume changes
                'tick_count': 0
            }
            self.tick_count = 0
        
        # Update OHLC
        if self.current_candle:
            self.current_candle['high'] = max(self.current_candle['high'], price)
            self.current_candle['low'] = min(self.current_candle['low'], price)
            self.current_candle['close'] = price
            self.tick_count += 1
            self.current_candle['tick_count'] = self.tick_count
    
    def finalize(self, timestamp: int) -> Optional[Dict]:
        """
        Finalize candle for given minute.
        
        Args:
            timestamp: Minute to finalize
        
        Returns:
            Finalized candle dict or None
        """
        if not self.current_candle:
            logger.warning(f"{self.symbol}: No candle to finalize for {format_timestamp(timestamp)}")
            return None
        
        if self.current_candle['timestamp'] != timestamp:
            logger.warning(
                f"{self.symbol}: Timestamp mismatch. "
                f"Expected {format_timestamp(timestamp)}, "
                f"got {format_timestamp(self.current_candle['timestamp'])}"
            )
            return None
        
        # Return copy
        candle = self.current_candle.copy()
        
        logger.debug(
            f"✅ {self.symbol} candle finalized: "
            f"O={candle['open']:.2f} H={candle['high']:.2f} "
            f"L={candle['low']:.2f} C={candle['close']:.2f} "
            f"({candle['tick_count']} ticks)"
        )
        
        return candle
    
    def get_current_price(self) -> Optional[float]:
        """Get current price from building candle."""
        if self.current_candle:
            return self.current_candle['close']
        return None


# ============================================
# WebSocketManager - Main orchestrator
# ============================================

class WebSocketManager:
    """
    Manages WebSocket connections and candle-based filtering.
    
    Responsibilities:
    - Watch tickers via WebSocket
    - Build candles from ticker stream
    - Schedule filter checks on candle close
    - Handle reconnections and gaps
    """
    
    def __init__(
        self,
        exchange: ccxt.bybit,
        database: Database,
        check_delay_seconds: int = 10
    ):
        """
        Initialize WebSocket manager.
        
        Args:
            exchange: CCXT exchange instance
            database: Database instance
            check_delay_seconds: Delay after candle close before checking (default: 10)
        """
        self.exchange = exchange
        self.db = database
        self.check_delay_seconds = check_delay_seconds
        
        # Candle builders for each symbol
        self.candle_builders: Dict[str, CandleBuilder] = {}
        
        # Filter check queue
        self.filter_check_queue: asyncio.Queue = asyncio.Queue()
        
        # Active symbols to watch
        self.active_symbols: Set[str] = set()
        
        # Last update timestamps (for gap detection)
        self.last_update: Dict[str, int] = {}
        
        # Running flag
        self.running = False
        
        logger.info("✅ WebSocketManager initialized")
    
    # ============================================
    # Main Entry Point
    # ============================================
    
    async def start(self, symbols: list, markets: dict):
        """
        Start WebSocket monitoring for symbols.
        
        Args:
            symbols: List of symbols to watch
            markets: Dict mapping symbol to market ('spot' or 'futures')
        """
        logger.info(f"🚀 Starting WebSocket monitoring for {len(symbols)} symbols...")
        
        self.running = True
        self.active_symbols = set(symbols)
        
        # Create candle builders
        for symbol in symbols:
            market = markets.get(symbol, 'spot')
            self.candle_builders[symbol] = CandleBuilder(symbol, market)
        
        # 1. Load initial history via REST
        await self._load_initial_history(symbols)
        
        # 2. Start tasks
        tasks = []
        
        # WebSocket watchers for each symbol
        for symbol in symbols:
            tasks.append(self._watch_symbol(symbol))
        
        # Filter check scheduler
        tasks.append(self._filter_check_scheduler())
        
        # Filter check processor
        tasks.append(self._process_filter_checks())
        
        # Cleanup task
        tasks.append(self._cleanup_loop())
        
        # Gap checker (every 5 minutes)
        tasks.append(self._gap_checker())
        
        # Run all tasks
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("WebSocket manager cancelled")
            self.running = False
        except Exception as e:
            logger.error(f"WebSocket manager error: {e}", exc_info=True)
            self.running = False
    
    async def stop(self):
        """Stop WebSocket manager gracefully."""
        logger.info("Stopping WebSocket manager...")
        self.running = False
        
        # Close exchange connection
        if self.exchange:
            await self.exchange.close()
    
    # ============================================
    # WebSocket Watching
    # ============================================
    
    async def _watch_symbol(self, symbol: str):
        """
        Watch ticker updates for symbol via WebSocket.
        
        Args:
            symbol: Symbol to watch
        """
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        logger.info(f"📡 Starting WebSocket watch for {symbol}")
        
        while self.running:
            try:
                # Watch ticker (blocks until update received)
                ticker = await self.exchange.watch_ticker(symbol)
                
                # Reset error counter on success
                if consecutive_errors > 0:
                    logger.info(
                        f"✅ {symbol} WebSocket recovered after {consecutive_errors} errors"
                    )
                    consecutive_errors = 0
                
                # Process ticker update
                await self._process_ticker_update(symbol, ticker)
                
            except Exception as e:
                consecutive_errors += 1
                
                logger.warning(
                    f"⚠️ WebSocket error for {symbol} "
                    f"(error {consecutive_errors}/{max_consecutive_errors}): {e}"
                )
                
                # If too many errors - check for gaps
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        f"❌ Too many errors for {symbol}. Checking for gaps..."
                    )
                    
                    await self._ensure_data_continuity(symbol)
                    consecutive_errors = 0
                
                # Exponential backoff
                delay = min(5 * (2 ** consecutive_errors), 60)
                logger.info(f"Retrying {symbol} in {delay}s...")
                await asyncio.sleep(delay)
    
    async def _process_ticker_update(self, symbol: str, ticker: dict):
        """
        Process ticker update from WebSocket.
        
        Args:
            symbol: Symbol
            ticker: Ticker data from WebSocket
        """
        try:
            # Extract data
            timestamp_ms = ticker.get('timestamp', time.time() * 1000)
            timestamp = int(timestamp_ms / 1000)
            minute_start = round_to_minute(timestamp)
            
            price = ticker.get('last', 0)
            volume_24h = ticker.get('quoteVolume', 0)
            
            if price <= 0:
                logger.warning(f"{symbol}: Invalid price {price}, skipping")
                return
            
            # Update last seen timestamp
            self.last_update[symbol] = timestamp
            
            # Update candle builder
            builder = self.candle_builders.get(symbol)
            if builder:
                builder.update(minute_start, price, volume_24h)
            else:
                logger.warning(f"{symbol}: No candle builder found")
            
        except Exception as e:
            logger.error(f"Error processing ticker for {symbol}: {e}")
    
    # ============================================
    # Filter Check Scheduling
    # ============================================
    
    async def _filter_check_scheduler(self):
        """
        Schedule filter checks at XX:XX:10 each minute.
        
        Waits until XX:XX:10, then queues all symbols for checking.
        """
        logger.info("🕐 Filter check scheduler started")
        
        while self.running:
            try:
                now = time.time()
                current_minute_start = (int(now) // 60) * 60
                
                # Next check time: XX:XX:10
                next_check_time = current_minute_start + 60 + self.check_delay_seconds
                
                # If already passed, next minute
                if now > next_check_time:
                    next_check_time += 60
                
                # Sleep until check time
                sleep_seconds = next_check_time - now
                
                logger.debug(
                    f"Next filter check in {sleep_seconds:.1f}s "
                    f"at {format_timestamp(int(next_check_time))}"
                )
                
                await asyncio.sleep(sleep_seconds)
                
                # Time to check!
                closed_minute = current_minute_start
                
                logger.info(
                    f"🔔 Candle closed: {format_timestamp(closed_minute)}. "
                    f"Queuing {len(self.active_symbols)} symbols for filter checks..."
                )
                
                # Queue all symbols
                for symbol in self.active_symbols:
                    await self.filter_check_queue.put({
                        'symbol': symbol,
                        'closed_minute': closed_minute,
                        'timestamp': time.time()
                    })
                
            except Exception as e:
                logger.error(f"Error in filter check scheduler: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def _process_filter_checks(self):
        """
        Process filter check queue.
        
        Takes symbols from queue and checks filters.
        """
        logger.info("⚙️ Filter check processor started")
        
        while self.running:
            try:
                # Get task from queue (blocks if empty)
                task = await self.filter_check_queue.get()
                
                symbol = task['symbol']
                closed_minute = task['closed_minute']
                
                try:
                    # Finalize and save candle
                    await self._finalize_candle(symbol, closed_minute)
                    
                    # Check filters
                    await self._check_filters_for_symbol(symbol, closed_minute)
                    
                except Exception as e:
                    logger.error(
                        f"Error checking filters for {symbol}: {e}",
                        exc_info=True
                    )
                
                finally:
                    self.filter_check_queue.task_done()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in filter check processor: {e}", exc_info=True)
                await asyncio.sleep(1)
    
    async def _finalize_candle(self, symbol: str, candle_timestamp: int):
        """
        Finalize candle and save to database.
        
        Args:
            symbol: Symbol
            candle_timestamp: Candle minute timestamp
        """
        builder = self.candle_builders.get(symbol)
        
        if not builder:
            logger.warning(f"{symbol}: No candle builder")
            return
        
        # Finalize candle
        candle = builder.finalize(candle_timestamp)
        
        if not candle:
            logger.warning(f"{symbol}: Could not finalize candle")
            return
        
        # Save to database
        try:
            await self.db.save_candle(
                symbol=candle['symbol'],
                market=candle['market'],
                timestamp=candle['timestamp'],
                open_price=candle['open'],
                high=candle['high'],
                low=candle['low'],
                close=candle['close'],
                volume=candle.get('volume', 0)
            )
            
            logger.debug(f"✅ Saved candle: {symbol} at {format_timestamp(candle_timestamp)}")
            
        except Exception as e:
            logger.error(f"Error saving candle for {symbol}: {e}")
    
    async def _check_filters_for_symbol(self, symbol: str, closed_minute: int):
        """
        Check all filters for symbol after candle close.
        
        Args:
            symbol: Symbol
            closed_minute: Closed minute timestamp
        """
        # Import here to avoid circular dependency
        from .filters import check_all_filters_for_symbol
        
        try:
            # This will be implemented in filters.py
            # It should get active filters and check each one
            triggers = await check_all_filters_for_symbol(
                symbol=symbol,
                closed_minute=closed_minute,
                db=self.db
            )
            
            if triggers:
                logger.info(
                    f"🔥 {len(triggers)} filter(s) triggered for {symbol} "
                    f"at {format_timestamp(closed_minute)}"
                )
            
        except Exception as e:
            logger.error(f"Error checking filters for {symbol}: {e}")
    
    # ============================================
    # Gap Recovery
    # ============================================
    
    async def _ensure_data_continuity(self, symbol: str):
        """
        Ensure no gaps in candle data for symbol.
        
        Fetches missing candles via REST API.
        
        Args:
            symbol: Symbol to check
        """
        try:
            # Get last candle from DB
            last_candle_row = await self.db.execute(
                """
                SELECT timestamp FROM candles
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (symbol,)
            )
            
            last_candles = await last_candle_row.fetchall()
            
            if not last_candles:
                logger.info(f"{symbol}: No history, loading initial data...")
                await self._load_history_for_symbol(symbol)
                return
            
            last_timestamp = last_candles[0]['timestamp']
            now = get_current_timestamp()
            current_minute = get_current_minute_timestamp()
            
            # Calculate gap
            gap_minutes = (current_minute - last_timestamp) // 60 - 1
            
            if gap_minutes > 0:
                logger.warning(
                    f"⚠️ Gap detected for {symbol}: {gap_minutes} minutes missing. "
                    f"Fetching via REST..."
                )
                
                # Fetch missing candles
                market = self.candle_builders[symbol].market if symbol in self.candle_builders else 'spot'
                
                since_ms = (last_timestamp + 60) * 1000
                limit = gap_minutes + 1
                
                candles = await self.exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe='1m',
                    since=since_ms,
                    limit=limit
                )
                
                # Save candles (exclude last one - not closed yet)
                saved_count = 0
                for candle_data in candles[:-1]:
                    await self._save_ohlcv_candle(symbol, market, candle_data)
                    saved_count += 1
                
                logger.info(f"✅ Gap filled: restored {saved_count} candles for {symbol}")
            
        except Exception as e:
            logger.error(f"Error ensuring continuity for {symbol}: {e}")
    
    async def _gap_checker(self):
        """
        Periodically check for gaps in all symbols.
        
        Runs every 5 minutes.
        """
        logger.info("🔍 Gap checker started")
        
        while self.running:
            try:
                await asyncio.sleep(300)  # 5 minutes
                
                logger.info("Running periodic gap check...")
                
                tasks = [
                    self._ensure_data_continuity(symbol)
                    for symbol in self.active_symbols
                ]
                
                await asyncio.gather(*tasks, return_exceptions=True)
                
                logger.info("✅ Gap check complete")
                
            except Exception as e:
                logger.error(f"Error in gap checker: {e}")
    
    # ============================================
    # Initial Data Loading
    # ============================================
    
    async def _load_initial_history(self, symbols: list):
        """
        Load initial 2-hour history for all symbols via REST.
        
        Args:
            symbols: List of symbols
        """
        logger.info(f"📚 Loading initial history for {len(symbols)} symbols...")
        
        tasks = []
        for symbol in symbols:
            # Check if history already exists
            existing = await self.db.execute(
                """
                SELECT COUNT(*) as cnt FROM candles
                WHERE symbol = ?
                """,
                (symbol,)
            )
            
            rows = await existing.fetchall()
            count = rows[0]['cnt'] if rows else 0
            
            if count >= 120:
                logger.debug(f"{symbol}: History exists ({count} candles)")
                continue
            
            tasks.append(self._load_history_for_symbol(symbol))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info(f"✅ Initial history loaded for {len(tasks)} symbols")
    
    async def _load_history_for_symbol(self, symbol: str):
        """
        Load 2-hour history for single symbol.
        
        Args:
            symbol: Symbol
        """
        try:
            market = self.candle_builders[symbol].market if symbol in self.candle_builders else 'spot'
            
            # Fetch 121 candles (120 + 1 to exclude last)
            candles = await self.exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe='1m',
                limit=121
            )
            
            # Save all except last
            saved_count = 0
            for candle_data in candles[:-1]:
                await self._save_ohlcv_candle(symbol, market, candle_data)
                saved_count += 1
            
            logger.debug(f"✅ Loaded {saved_count} candles for {symbol}")
            
        except Exception as e:
            logger.error(f"Failed to load history for {symbol}: {e}")
    
    async def _save_ohlcv_candle(self, symbol: str, market: str, candle_data: list):
        """
        Save OHLCV candle data to database.
        
        Args:
            symbol: Symbol
            market: Market type
            candle_data: CCXT OHLCV format [timestamp_ms, o, h, l, c, v]
        """
        timestamp_ms = candle_data[0]
        timestamp = int(timestamp_ms / 1000)
        
        # Calculate quote volume (approximate)
        volume_base = candle_data[5]
        avg_price = (candle_data[2] + candle_data[3]) / 2  # (high + low) / 2
        volume_quote = volume_base * avg_price
        
        await self.db.save_candle(
            symbol=symbol,
            market=market,
            timestamp=timestamp,
            open_price=candle_data[1],
            high=candle_data[2],
            low=candle_data[3],
            close=candle_data[4],
            volume=volume_quote
        )
    
    # ============================================
    # Cleanup
    # ============================================
    
    async def _cleanup_loop(self):
        """
        Periodically clean up old candles.
        
        Runs every hour, removes candles older than 3 hours.
        """
        logger.info("🗑️ Cleanup task started")
        
        while self.running:
            try:
                await asyncio.sleep(3600)  # 1 hour
                
                cutoff = get_current_timestamp() - (3 * 3600)  # 3 hours ago
                
                result = await self.db.execute(
                    "DELETE FROM candles WHERE timestamp < ?",
                    (cutoff,)
                )
                
                deleted = result.rowcount if hasattr(result, 'rowcount') else 0
                
                if deleted > 0:
                    logger.info(f"🗑️ Cleaned up {deleted} old candles")
                
            except Exception as e:
                logger.error(f"Error in cleanup: {e}")


# ============================================
# Factory Function
# ============================================

def create_websocket_manager(
    exchange: ccxt.bybit,
    database: Database,
    check_delay_seconds: int = 10
) -> WebSocketManager:
    """
    Create WebSocket manager instance.
    
    Args:
        exchange: CCXT exchange
        database: Database instance
        check_delay_seconds: Delay before checking filters after candle close
    
    Returns:
        WebSocketManager instance
    """
    return WebSocketManager(
        exchange=exchange,
        database=database,
        check_delay_seconds=check_delay_seconds
    )
