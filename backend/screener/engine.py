"""
Screener Engine Module (WebSocket Mode)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CRITICAL: Main screening loop using WebSocket for real-time data.

This version replaces REST API polling with WebSocket streaming.

ARCHITECTURE:
1. WebSocket receives ticker updates every second
2. CandleBuilder accumulates ticks into 1-minute candles
3. At XX:XX:10, finalize candle and check filters
4. Triggers sent to Telegram and saved to DB

KEY CHANGES FROM REST VERSION:
- No more 5-minute polling cycle
- Real-time ticker updates via WebSocket
- Filter checks triggered by candle close events
- Gap recovery handled automatically
"""

import asyncio
import logging
import signal
import os
from typing import Optional, Set, Dict

from .websocket_manager import WebSocketManager, create_websocket_manager
from .database import Database
from .exchange import create_exchange

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
        
        logger.info("✅ ScreenerEngine initialized (WebSocket mode)")
    
    # ============================================
    # Lifecycle
    # ============================================
    
    async def start(self):
        """
        Start the screener engine.
        
        1. Initialize components
        2. Get active symbols from filters
        3. Start WebSocket manager
        """
        logger.info("=" * 70)
        logger.info("🚀 STARTING CRYPTO SCREENER (WEBSOCKET MODE)")
        logger.info("=" * 70)
        
        self.running = True
        
        try:
            # 1. Initialize database
            logger.info("📦 Initializing database...")
            self.database = Database(self.db_path)
            await self.database.connect()
            
            # 2. Initialize exchange
            logger.info("🔌 Initializing exchange...")
            self.exchange = create_exchange(testnet=self.testnet)
            
            # 3. Initialize Telegram notifier
            logger.info("📱 Initializing Telegram notifier...")
            from ..config import settings
            from telegram import Bot
            
            # Create bot instance
            bot = Bot(token=settings.telegram_bot_token)
            
            # Create notifier with bot object
            from .notifications import create_notifier
            self.notifier = create_notifier(
                bot=bot,
                chat_id=settings.telegram_chat_id,
                logger=logger
            )
            
            logger.info("✅ Telegram notifier initialized")
            
            # 4. Get active symbols from filters
            logger.info("🔍 Loading active filters...")
            symbols, markets = await self._get_active_symbols()
            
            if not symbols:
                logger.warning("⚠️ No active filters found. Engine will wait for filters to be created.")
                logger.info("💡 You can create filters via the web UI at http://localhost:3000")
                
                # Wait mode - check for filters every minute
                while self.running:
                    await asyncio.sleep(60)
                    symbols, markets = await self._get_active_symbols()
                    if symbols:
                        logger.info(f"✅ Found {len(symbols)} active symbols. Starting monitoring...")
                        break
                
                # If still no symbols after loop, return
                if not symbols:
                    return
            
            # 5. Create and start WebSocket manager
            logger.info(f"📡 Starting WebSocket manager for {len(symbols)} symbols...")
            self.ws_manager = create_websocket_manager(
                exchange=self.exchange,
                database=self.database,
                check_delay_seconds=self.check_delay_seconds
            )
            
            # This will run until stopped
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
            Tuple of (symbols_set, markets_dict)
            - symbols_set: Set of unique symbols
            - markets_dict: {symbol: market} mapping
        """
        try:
            # Get all active filters
            filters = await self.database.get_active_filters()
            
            if not filters:
                return set(), {}
            
            symbols = set()
            markets = {}
            
            # Get configurable limit from environment
            # 0 = no limit (all symbols)
            max_symbols = int(os.getenv('MAX_SYMBOLS_PER_MARKET', '100'))
            limit = None if max_symbols == 0 else max_symbols
            
            # Extract symbols from filter configurations
            for filter_data in filters:
                market = filter_data.get('config', {}).get('market', 'spot')
                
                # Get all symbols for this market from database
                # (Assumes symbols are already in tickers table from previous runs)
                # For first run, we'll use top symbols by volume
                market_symbols = await self._get_symbols_for_market(market, limit=limit)
                
                for symbol in market_symbols:
                    symbols.add(symbol)
                    markets[symbol] = market
            
            logger.info(
                f"📊 Found {len(symbols)} unique symbols from {len(filters)} active filters"
            )
            
            return symbols, markets
            
        except Exception as e:
            logger.error(f"Error getting active symbols: {e}", exc_info=True)
            return set(), {}
    
    async def _get_symbols_for_market(self, market: str, limit: Optional[int] = 100) -> list:
        """
        Get top symbols for market by volume.
        
        Args:
            market: 'spot' or 'futures'
            limit: Max number of symbols (None = all symbols)
        
        Returns:
            List of symbols
        """
        try:
            # Fetch tickers with market parameter
            tickers = await self.exchange.fetch_tickers(market)
            
            if not tickers:
                logger.warning(f"No tickers returned for {market}")
                return []
            
            # Sort by quoteVolume
            sorted_symbols = sorted(
                tickers.items(),
                key=lambda x: x[1].get('quoteVolume', 0),
                reverse=True
            )
            
            # Apply limit if specified
            if limit is not None:
                top_symbols = [symbol for symbol, _ in sorted_symbols[:limit]]
                logger.info(f"📊 Selected top {len(top_symbols)} {market} symbols by volume")
            else:
                top_symbols = [symbol for symbol, _ in sorted_symbols]
                logger.info(f"📊 Selected ALL {len(top_symbols)} {market} symbols")
            
            return top_symbols
            
        except Exception as e:
            logger.error(f"Error getting top symbols for {market}: {e}")
            return []


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
    Start the screener engine.
    
    Args:
        db_path: Database path
        testnet: Use testnet
        check_delay_seconds: Delay before filter checks
    """
    global _engine_instance
    
    if _engine_instance and _engine_instance.running:
        logger.warning("Engine already running")
        return
    
    # Create and start engine
    _engine_instance = ScreenerEngine(
        db_path=db_path,
        testnet=testnet,
        check_delay_seconds=check_delay_seconds
    )
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, stopping engine...")
        if _engine_instance:
            asyncio.create_task(_engine_instance.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start engine
    await _engine_instance.start()


async def stop_screener():
    """Stop the screener engine."""
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
        print("Screener Engine Test (WebSocket Mode)")
        print("=" * 50)
        print("\n⚠️  This requires full configuration (.env file)")
        print("Run from main.py instead")
        
        return 1
    
    sys.exit(asyncio.run(test_engine()))