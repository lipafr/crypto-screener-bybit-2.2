"""
Screener Engine Module (WebSocket Mode) - WITH CHARTS SUPPORT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CRITICAL: Main screening loop using WebSocket for real-time data.

This version replaces REST API polling with WebSocket streaming.

ARCHITECTURE:
1. WebSocket receives ticker updates every second
2. CandleBuilder accumulates ticks into 1-minute candles
3. At XX:XX:10, finalize candle and check filters
4. Triggers sent to Telegram and saved to DB

CHARTS INTEGRATION:
- Updates cache on candle finalization
- Broadcasts candle updates via WebSocket
- Broadcasts trigger marks on filter hits
"""

import asyncio
import logging
import signal
import os
import time
from typing import Optional, Set, Dict

from .websocket_manager import WebSocketManager, create_websocket_manager
from .database import Database
from .exchange import create_exchange

# NEW: Import cache and charts WebSocket manager
from . import cache
from backend.api.websocket_charts import chart_manager

logger = logging.getLogger(__name__)


# ============================================
# Engine State
# ============================================

class ScreenerEngine:
    """
    Main screener engine using WebSocket.
    
    Coordinates:
    - WebSocket manager (data streaming)
    - Database (persistence)
    - Telegram notifier (alerts)
    - Cache (charts data)
    - Charts WebSocket (real-time UI updates)
    """
    
    def __init__(
        self,
        db_path: str = "/data/screener.db",
        testnet: bool = False,
        check_delay_seconds: int = 10
    ):
        """
        Initialize screener engine.
        
        Args:
            db_path: Database file path
            testnet: Use testnet (default: False)
            check_delay_seconds: Delay after candle close before checking
        """
        self.db_path = db_path
        self.testnet = testnet
        self.check_delay_seconds = check_delay_seconds
        
        # Components (initialized in start())
        self.database: Optional[Database] = None
        self.exchange = None
        self.ws_manager: Optional[WebSocketManager] = None
        self.notifier = None
        
        # Running flag
        self.running = False
        
        # NEW: Track last parse time for status API
        self.last_parse_time = 0
        
        logger.info("✅ ScreenerEngine initialized (WebSocket mode with charts)")
    
    # ============================================
    # Lifecycle
    # ============================================
    
    async def start(self):
        """
        Start the screener engine.
        
        1. Initialize components
        2. Warm up cache from database
        3. Get active symbols from filters
        4. Start WebSocket manager
        """
        logger.info("=" * 70)
        logger.info("🚀 STARTING CRYPTO SCREENER (WEBSOCKET MODE + CHARTS)")
        logger.info("=" * 70)
        
        self.running = True
        
        try:
            # 1. Initialize database
            logger.info("📦 Initializing database...")
            self.database = Database(self.db_path)
            await self.database.connect()
            
            # 2. Initialize exchange
            logger.info("🌐 Initializing exchange...")
            self.exchange = create_exchange(testnet=self.testnet)
            
            # ============================================
            # NEW: Warm up cache from database
            # ============================================
            logger.info("📦 Warming up cache from database...")
            
            try:
                # Get all symbols from tickers table
                all_symbols_spot = await self.database.get_symbols_for_market('spot')
                all_symbols_futures = await self.database.get_symbols_for_market('futures')
                
                warmed_count = 0
                
                # Load spot candles
                for symbol in all_symbols_spot:
                    try:
                        candles = await self.database.get_candles(symbol, 'spot', minutes=120)
                        if candles:
                            candles_data = [
                                {
                                    'timestamp': c[0],
                                    'open': c[1],
                                    'high': c[2],
                                    'low': c[3],
                                    'close': c[4],
                                    'volume': c[5]
                                }
                                for c in candles
                            ]
                            cache.bulk_update_candles(symbol, 'spot', candles_data)
                            warmed_count += 1
                    except Exception as e:
                        logger.debug(f"Could not load spot candles for {symbol}: {e}")
                
                # Load futures candles
                for symbol in all_symbols_futures:
                    try:
                        candles = await self.database.get_candles(symbol, 'futures', minutes=120)
                        if candles:
                            candles_data = [
                                {
                                    'timestamp': c[0],
                                    'open': c[1],
                                    'high': c[2],
                                    'low': c[3],
                                    'close': c[4],
                                    'volume': c[5]
                                }
                                for c in candles
                            ]
                            cache.bulk_update_candles(symbol, 'futures', candles_data)
                            warmed_count += 1
                    except Exception as e:
                        logger.debug(f"Could not load futures candles for {symbol}: {e}")
                
                logger.info(f"✅ Cache warmed: {warmed_count} symbols loaded")
                
                # Log cache stats
                stats = cache.get_cache_stats()
                logger.info(
                    f"📊 Cache stats: {stats['total_symbols']} symbols, "
                    f"{stats['total_candles']} candles, "
                    f"{stats['total_triggers']} trigger marks"
                )
            except Exception as e:
                logger.warning(f"⚠️ Could not warm up cache: {e}")
            # ============================================
            # END NEW CODE
            # ============================================
            
            # 3. Get active filters and symbols
            logger.info("🔍 Getting active symbols from filters...")
            symbols, markets = await self._get_active_symbols()
            
            if not symbols:
                logger.warning("⚠️ No active symbols found from filters")
                logger.info("Waiting for filters to be created...")
                
                # Wait for filters
                for attempt in range(60):
                    await asyncio.sleep(10)
                    symbols, markets = await self._get_active_symbols()
                    if symbols:
                        logger.info(f"✅ Found {len(symbols)} symbols. Starting monitoring...")
                        break
                
                # If still no symbols after loop, return
                if not symbols:
                    return
            
            # 4. Create and start WebSocket manager
            logger.info(f"📡 Creating WebSocket manager for {len(symbols)} symbols...")
            self.ws_manager = create_websocket_manager(
                exchange=self.exchange,
                database=self.database,
                check_delay_seconds=self.check_delay_seconds
            )
            
            # 5. Start WebSocket manager (this will run until stopped)
            # Cache updates and WebSocket broadcasts happen in websocket_manager._process_closed_candles()
            logger.info(f"📡 Starting WebSocket manager...")
            await self.ws_manager.start(list(symbols), markets)
            
        except asyncio.CancelledError:
            logger.info("Engine cancelled")
        except Exception as e:
            logger.error(f"❌ Fatal error in engine: {e}", exc_info=True)
        finally:
            await self.stop()
    
    async def stop(self):
        """
        Stop the screener engine gracefully.
        """
        if not self.running:
            return
        
        logger.info("🛑 Stopping screener engine...")
        
        self.running = False
        
        # Stop WebSocket manager
        if self.ws_manager:
            await self.ws_manager.stop()
            logger.info("✅ WebSocket manager stopped")
        
        # Close exchange
        if self.exchange:
            await self.exchange.close()
            logger.info("✅ Exchange connection closed")
        
        # Close database
        if self.database:
            await self.database.close()
            logger.info("✅ Database connection closed")
        
        logger.info("✅ Engine stopped")
    
    # ============================================
    # Helper Methods
    # ============================================
    
    async def _get_active_symbols(self) -> tuple[Set[str], Dict[str, str]]:
        """
        Get active symbols from enabled filters.
        
        Returns:
            tuple: (set of symbols, dict mapping symbol to market)
        """
        try:
            filters = await self.database.get_all_filters(enabled_only=True)
            
            if not filters:
                return set(), {}
            
            symbols = set()
            symbol_to_market = {}
            
            for f in filters:
                market = f['config'].get('market', 'spot')
                
                # Get all symbols for this market
                market_symbols = await self.database.get_symbols_for_market(market)
                
                # Apply exclusions
                exclusions = set(f['config'].get('exclude_symbols', []))
                
                for symbol in market_symbols:
                    if symbol not in exclusions:
                        symbols.add(symbol)
                        symbol_to_market[symbol] = market
            
            logger.info(f"✅ Found {len(symbols)} active symbols across filters")
            
            return symbols, symbol_to_market
            
        except Exception as e:
            logger.error(f"Error getting active symbols: {e}", exc_info=True)
            return set(), {}


# ============================================
# Global Engine Instance
# ============================================

_engine_instance: Optional[ScreenerEngine] = None


async def start_screener(
    db_path: str = "/data/screener.db",
    testnet: bool = False,
    check_delay_seconds: int = 10
):
    """
    Start screener engine (called from main.py).
    
    Args:
        db_path: Database file path
        testnet: Use testnet (default: False)
        check_delay_seconds: Delay after candle close
    """
    global _engine_instance
    
    try:
        _engine_instance = ScreenerEngine(
            db_path=db_path,
            testnet=testnet,
            check_delay_seconds=check_delay_seconds
        )
        
        # Handle signals
        loop = asyncio.get_event_loop()
        
        def signal_handler():
            logger.info("Received shutdown signal")
            asyncio.create_task(stop_screener())
        
        # Register signal handlers
        if os.name != 'nt':  # Unix-like systems
            loop.add_signal_handler(signal.SIGTERM, signal_handler)
            loop.add_signal_handler(signal.SIGINT, signal_handler)
        
        # Start engine
        await _engine_instance.start()
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        await stop_screener()


async def stop_screener():
    """Stop screener engine."""
    global _engine_instance
    
    if _engine_instance:
        await _engine_instance.stop()
        _engine_instance = None


def get_engine() -> Optional[ScreenerEngine]:
    """Get current engine instance."""
    return _engine_instance


# ============================================
# For Testing
# ============================================

if __name__ == "__main__":
    import sys
    
    # Test mode
    async def test_engine():
        print("=" * 50)
        print("Screener Engine Test (WebSocket Mode + Charts)")
        print("=" * 50)
        print("\n⚠️  This requires full configuration (.env file)")
        print("Run from main.py instead")
        
        return 1
    
    sys.exit(asyncio.run(test_engine()))