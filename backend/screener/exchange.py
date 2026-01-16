"""
Exchange Module with WebSocket Support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bybit exchange integration via CCXT Pro (WebSocket + REST).

KEY FEATURES:
1. WebSocket support via ccxt.pro
2. Separate exchange objects for spot/futures (Bybit requirement)
3. REST API fallback for gap recovery
4. Automatic reconnection handling
"""

import ccxt.pro as ccxtpro
import ccxt.async_support as ccxt
import asyncio
import logging
from typing import Optional, Dict, List
from ccxt.base.errors import NetworkError, ExchangeError

from .time_utils import (
    get_last_closed_candle_timestamp,
    seconds_to_milliseconds,
    milliseconds_to_seconds,
    format_timestamp
)

logger = logging.getLogger(__name__)


class BybitExchange:
    """
    Bybit exchange wrapper with WebSocket and REST support.
    
    CRITICAL: Bybit has conflicting symbol IDs for spot and futures!
    - Spot: BTC/USDT
    - Futures: BTC/USDT:USDT (same base symbol!)
    
    Solution: We create separate exchange instances for each market type.
    """
    
    def __init__(
        self,
        testnet: bool = False,
        timeout: int = 30000,
        retry_max_attempts: int = 3,
        retry_delay: float = 5.0
    ):
        """
        Initialize Bybit exchange with WebSocket support.
        
        Args:
            testnet: Use testnet (default: False)
            timeout: Request timeout in milliseconds
            retry_max_attempts: Max retry attempts
            retry_delay: Delay between retries in seconds
        """
        self.testnet = testnet
        self.timeout = timeout
        self.retry_max_attempts = retry_max_attempts
        self.retry_delay = retry_delay
        
        # Create separate exchanges for spot and futures (WebSocket)
        self.spot_exchange_ws = self._create_ws_exchange('spot')
        self.futures_exchange_ws = self._create_ws_exchange('swap')
        
        # Create REST exchange for data fetching (gap recovery)
        self.exchange_rest = self._create_rest_exchange()
        
        logger.info(f"✅ Bybit exchange initialized (testnet={testnet}, WebSocket enabled)")
    
    def _create_ws_exchange(self, market_type: str):
        """
        Create ccxt.pro exchange for WebSocket.
        
        Args:
            market_type: 'spot' or 'swap'
        
        Returns:
            CCXT Pro exchange instance
        """
        exchange = ccxtpro.bybit({
            'enableRateLimit': True,
            'timeout': self.timeout,
            'options': {
                'defaultType': market_type,
            }
        })
        
        if self.testnet:
            exchange.set_sandbox_mode(True)
        
        return exchange
    
    def _create_rest_exchange(self):
        """
        Create regular CCXT exchange for REST API.
        
        Returns:
            CCXT exchange instance
        """
        exchange = ccxt.bybit({
            'enableRateLimit': True,
            'timeout': self.timeout,
            'options': {
                'defaultType': 'swap',  # Default to futures
                'subType': 'linear',     # Force linear contracts (avoid options)
            }
        })
        
        if self.testnet:
            exchange.set_sandbox_mode(True)
        
        return exchange
    
    # ============================================
    # WebSocket Methods
    # ============================================
    
    async def watch_ticker(self, symbol: str, market: str) -> Dict:
        """
        Watch ticker updates via WebSocket.
        
        Args:
            symbol: Trading pair (e.g. 'BTC/USDT' or 'BTC/USDT:USDT')
            market: 'spot' or 'futures'
        
        Returns:
            Ticker data dict
        """
        try:
            # Select correct exchange based on market
            if market == 'spot':
                exchange = self.spot_exchange_ws
            else:
                exchange = self.futures_exchange_ws
            
            # Watch ticker
            ticker = await exchange.watch_ticker(symbol)
            
            return ticker
            
        except Exception as e:
            logger.error(f"Error watching ticker {symbol} ({market}): {e}")
            raise
    
    async def close_websockets(self):
        """Close all WebSocket connections."""
        try:
            await self.spot_exchange_ws.close()
            await self.futures_exchange_ws.close()
            logger.info("✅ WebSocket connections closed")
        except Exception as e:
            logger.error(f"Error closing WebSockets: {e}")
    
    # ============================================
    # REST Methods (for gap recovery & initial data)
    # ============================================
    
    async def fetch_tickers(self, market: str) -> Dict:
        """
        Fetch all tickers for market (REST API).
        
        Args:
            market: 'spot' or 'futures'
        
        Returns:
            Dict of {symbol: ticker_data}
        """
        try:
            # Set market type and fetch tickers
            if market == 'spot':
                self.exchange_rest.options['defaultType'] = 'spot'
                tickers = await self.exchange_rest.fetch_tickers()
            else:
                # Futures market - explicitly use linear perpetuals
                self.exchange_rest.options['defaultType'] = 'swap'
                # CRITICAL: Use 'category' not 'type' for Bybit!
                tickers = await self.exchange_rest.fetch_tickers(params={'category': 'linear'})
            
            logger.debug(f"✅ Fetched {len(tickers)} {market} tickers via REST")
            
            return tickers
            
        except Exception as e:
            logger.error(f"Error fetching {market} tickers: {e}")
            return {}
    
    async def fetch_ohlcv(
        self,
        symbol: str,
        market: str,
        timeframe: str = '1m',
        limit: int = 100
    ) -> List[Dict]:
        """
        Fetch OHLCV candles (REST API).
        
        CRITICAL: Only returns CLOSED candles (excludes last/current candle).
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            timeframe: Timeframe (default: '1m')
            limit: Number of candles
        
        Returns:
            List of candle dicts
        """
        try:
            # Set market type
            if market == 'spot':
                self.exchange_rest.options['defaultType'] = 'spot'
            else:
                self.exchange_rest.options['defaultType'] = 'swap'
            
            # Fetch OHLCV
            since_ms = None  # Get latest candles
            
            ohlcv_raw = await self.exchange_rest.fetch_ohlcv(
                symbol,
                timeframe,
                since_ms,
                limit
            )
            
            # Exclude last candle (current/incomplete)
            if ohlcv_raw:
                ohlcv_raw = ohlcv_raw[:-1]
            
            # Convert to dict format
            candles = []
            for candle in ohlcv_raw:
                candles.append({
                    'timestamp': milliseconds_to_seconds(candle[0]),
                    'open': candle[1],
                    'high': candle[2],
                    'low': candle[3],
                    'close': candle[4],
                    'volume': candle[5] if len(candle) > 5 else 0
                })
            
            logger.debug(f"✅ Fetched {len(candles)} closed candles for {symbol} ({market})")
            
            return candles
            
        except Exception as e:
            logger.error(f"Error fetching candles for {symbol} ({market}): {e}")
            return []
    
    async def close(self):
        """Close all connections (WebSocket + REST)."""
        await self.close_websockets()
        await self.exchange_rest.close()
        logger.info("✅ All exchange connections closed")
    
    # ============================================
    # Helper Methods
    # ============================================
    
    def get_bybit_url(self, symbol: str, market: str) -> str:
        """
        Get Bybit trading page URL.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
        
        Returns:
            URL string
        """
        # Remove settlement suffix for futures
        clean_symbol = symbol.replace(':USDT', '')
        url_symbol = clean_symbol.replace('/', '/')
        
        if market == 'spot':
            return f"https://www.bybit.com/trade/spot/{url_symbol}"
        else:
            pair = clean_symbol.replace('/', '')
            return f"https://www.bybit.com/trade/usdt/{pair}"


# ============================================
# Factory Functions
# ============================================

def create_exchange(testnet: bool = False) -> BybitExchange:
    """
    Create Bybit exchange instance with WebSocket support.
    
    Args:
        testnet: Use testnet mode
    
    Returns:
        BybitExchange instance
    """
    return BybitExchange(testnet=testnet)


def create_ws_exchange(market: str, testnet: bool = False):
    """
    Create WebSocket exchange for specific market.
    
    Args:
        market: 'spot' or 'futures'
        testnet: Use testnet
    
    Returns:
        CCXT Pro exchange instance
    """
    market_type = 'spot' if market == 'spot' else 'swap'
    
    exchange = ccxtpro.bybit({
        'enableRateLimit': True,
        'timeout': 30000,
        'options': {
            'defaultType': market_type,
        }
    })
    
    if testnet:
        exchange.set_sandbox_mode(True)
    
    return exchange