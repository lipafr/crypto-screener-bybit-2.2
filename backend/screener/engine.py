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
from typing import Optional

from .websocket_manager import WebSocketManager, create_websocket_manager
from .database import Database
from .exchange import create_exchange
from .notifications import TelegramNotifier

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
        self.notifier: Optional[TelegramNotifier] = None
        
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
            self.notifier = TelegramNotifier(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id
            )
            await self.notifier.start()
            
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
            
            # 5. Create and start WebSocket manager
            logger.info(f"📡 Starting WebSocket manager for {len(symbols)} symbols...")
            self.ws_manager = create_websocket_manager(
                exchange=self.exchange,
                database=self.database,
                check_delay_seconds=self.check_delay_seconds
            )
            
            # This will run until stopped
            await self.ws_manager.start(symbols, markets)
            
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
        logger.info("🛑 Stopping screener engine...")
        
        self.running = False
        
        # Stop components
        if self.ws_manager:
            await self.ws_manager.stop()
        
        if self.notifier:
            await self.notifier.stop()
        
        if self.exchange:
            await self.exchange.close()
        
        if self.database:
            await self.database.close()
        
        logger.info("✅ Engine stopped")
    
    # ============================================
    # Symbol Management
    # ============================================
    
    async def _get_active_symbols(self) -> tuple[list, dict]:
        """
        Get list of symbols from active filters.
        
        Returns:
            Tuple of (symbols_list, markets_dict)
            - symbols_list: List of unique symbols
            - markets_dict: Dict mapping symbol to market type
        """
        try:
            # Get all active filters
            filters_result = await self.database.execute(
                """
                SELECT DISTINCT market, config
                FROM filters
                WHERE enabled = 1
                """
            )
            
            filters = await filters_result.fetchall()
            
            if not filters:
                return [], {}
            
            # Parse symbols from filter configs
            import json
            symbols_set = set()
            markets = {}
            
            for filter_row in filters:
                market = filter_row['market']
                config = json.loads(filter_row['config'])
                
                # Get excluded symbols from config
                excluded = set(config.get('excluded_symbols', []))
                
                # For now, we'll monitor all USDT pairs
                # In production, you'd want to get this from tickers
                # and apply volume filters
                
                # Placeholder: get top symbols by volume
                # This should be implemented based on your requirements
                pass
            
            # For demo: if no filters, return empty
            # In production: fetch and filter symbols by volume
            
            logger.info(f"📊 Found {len(symbols_set)} unique symbols from active filters")
            
            return list(symbols_set), markets
            
        except Exception as e:
            logger.error(f"Error getting active symbols: {e}")
            return [], {}
    
    async def _get_top_symbols_by_volume(self, market: str, limit: int = 200) -> list:
        """
        Get top symbols by 24h volume.
        
        Args:
            market: 'spot' or 'futures'
            limit: Max number of symbols
        
        Returns:
            List of symbols
        """
        try:
            # Fetch tickers
            tickers = await self.exchange.fetch_tickers(market)
            
            # Sort by quoteVolume
            sorted_symbols = sorted(
                tickers.items(),
                key=lambda x: x[1].get('quoteVolume', 0),
                reverse=True
            )
            
            # Take top N
            top_symbols = [symbol for symbol, _ in sorted_symbols[:limit]]
            
            logger.info(f"📊 Selected top {len(top_symbols)} {market} symbols by volume")
            
            return top_symbols
            
        except Exception as e:
            logger.error(f"Error getting top symbols: {e}")
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
