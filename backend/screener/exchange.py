"""
Exchange Module
~~~~~~~~~~~~~~~

CRITICAL: Bybit exchange integration via CCXT.

KEY REQUIREMENTS:
1. Separate spot and futures markets (different symbols!)
   - Spot: BTC/USDT
   - Futures: BTC/USDT:USDT
2. Use quoteVolume for volume (in USD, not base currency)
3. Convert timestamps from milliseconds to seconds
4. Exclude last candle from fetch_ohlcv (only closed candles!)
5. Retry on NetworkError with exponential backoff
6. NO retry on ExchangeError

This module handles all communication with Bybit exchange.
"""

import ccxt.async_support as ccxt
import asyncio
import logging
from typing import Optional
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
    Bybit exchange wrapper using CCXT.
    
    Handles:
    - Market data fetching (spot and futures separately)
    - Automatic retries on network errors
    - Timestamp conversion
    - Rate limiting
    """
    
    def __init__(
        self,
        testnet: bool = False,
        timeout: int = 30000,
        retry_max_attempts: int = 3,
        retry_delay: float = 5.0
    ):
        """
        Initialize Bybit exchange client.
        
        Args:
            testnet: Use testnet (default: False - use mainnet)
            timeout: Request timeout in milliseconds
            retry_max_attempts: Maximum retry attempts for network errors
            retry_delay: Delay between retries in seconds
        """
        self.testnet = testnet
        self.timeout = timeout
        self.retry_max_attempts = retry_max_attempts
        self.retry_delay = retry_delay
        
        # Create exchange instance
        self.exchange = ccxt.bybit({
            'enableRateLimit': True,  # Important!
            'timeout': timeout,
        })
        
        if testnet:
            self.exchange.set_sandbox_mode(True)
            logger.warning("⚠️  Using TESTNET mode!")
        
        logger.info(f"✅ Bybit exchange initialized (testnet={testnet})")
    
    # ============================================
    # Market Data - Tickers
    # ============================================
    
    async def fetch_tickers(self, market: str) -> dict:
        """
        Fetch all tickers for specified market.
        
        CRITICAL: Spot and Futures have different symbols!
        - Spot: BTC/USDT
        - Futures: BTC/USDT:USDT
        
        Args:
            market: 'spot' or 'futures'
        
        Returns:
            Dict of {symbol: ticker_data}
        
        Raises:
            ValueError: If market is invalid
            NetworkError: If network error after retries
        
        Examples:
            >>> tickers = await exchange.fetch_tickers('spot')
            >>> tickers['BTC/USDT']['quoteVolume']
            1234567890.0
        """
        if market not in ['spot', 'futures']:
            raise ValueError(f"Invalid market: {market}. Must be 'spot' or 'futures'")
        
        # Set market type and category for Bybit V5 API
        original_default_type = self.exchange.options.get('defaultType')
        self.exchange.options['defaultType'] = market
        
        # Bybit V5 API requires explicit category parameter
        # spot = spot trading, linear = USDT perpetual futures
        category = 'spot' if market == 'spot' else 'linear'
        
        try:
            logger.debug(f"📊 Fetching {market} tickers (category: {category})...")
            
            # Fetch with retry logic and category parameter
            last_error = None
            for attempt in range(1, self.retry_max_attempts + 1):
                try:
                    tickers = await self.exchange.fetch_tickers(params={'category': category})
                    
                    # Success!
                    if attempt > 1:
                        logger.info(f"✅ fetch_{market}_tickers succeeded on attempt {attempt}")
                    break
                    
                except NetworkError as e:
                    last_error = e
                    if attempt < self.retry_max_attempts:
                        delay = self.retry_delay * (2 ** (attempt - 1))
                        logger.warning(
                            f"⚠️  fetch_{market}_tickers failed (attempt {attempt}/{self.retry_max_attempts}): "
                            f"{e}. Retrying in {delay:.1f}s..."
                        )
                        if attempt >= 2:
                            logger.warning("💡 Hint: If network errors persist, try enabling VPN")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"❌ fetch_{market}_tickers failed after {self.retry_max_attempts} attempts")
                        raise
                        
                except ExchangeError as e:
                    logger.error(f"❌ fetch_{market}_tickers failed with ExchangeError: {e}")
                    raise
                    
                except Exception as e:
                    logger.error(f"❌ fetch_{market}_tickers failed with unexpected error: {e}")
                    raise
            
            # Filter USDT pairs only
            usdt_tickers = {
                symbol: ticker
                for symbol, ticker in tickers.items()
                if '/USDT' in symbol
            }
            
            logger.info(
                f"✅ Fetched {len(usdt_tickers)} {market} tickers "
                f"(total: {len(tickers)})"
            )
            
            return usdt_tickers
            
        finally:
            # Restore original setting
            if original_default_type:
                self.exchange.options['defaultType'] = original_default_type
    
    async def fetch_ticker(self, symbol: str, market: str) -> Optional[dict]:
        """
        Fetch single ticker.
        
        Args:
            symbol: Trading pair (e.g. 'BTC/USDT' or 'BTC/USDT:USDT')
            market: 'spot' or 'futures'
        
        Returns:
            Ticker dict or None if error
        """
        original_default_type = self.exchange.options.get('defaultType')
        self.exchange.options['defaultType'] = market
        
        # Bybit V5 API category
        category = 'spot' if market == 'spot' else 'linear'
        
        try:
            # Retry logic inline
            for attempt in range(1, self.retry_max_attempts + 1):
                try:
                    ticker = await self.exchange.fetch_ticker(symbol, params={'category': category})
                    if attempt > 1:
                        logger.info(f"✅ fetch_ticker_{symbol} succeeded on attempt {attempt}")
                    return ticker
                    
                except NetworkError as e:
                    if attempt < self.retry_max_attempts:
                        delay = self.retry_delay * (2 ** (attempt - 1))
                        logger.warning(f"⚠️  fetch_ticker_{symbol} retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"❌ fetch_ticker_{symbol} failed after retries")
                        return None
                        
                except Exception as e:
                    logger.error(f"❌ Error fetching ticker {symbol} ({market}): {e}")
                    return None
            
            return None
            
        finally:
            if original_default_type:
                self.exchange.options['defaultType'] = original_default_type
    
    # ============================================
    # Market Data - Candles (OHLCV)
    # ============================================
    
    async def fetch_ohlcv(
        self,
        symbol: str,
        market: str,
        timeframe: str = '1m',
        limit: int = 120
    ) -> list[dict]:
        """
        Fetch OHLCV candles for symbol.
        
        CRITICAL REQUIREMENTS:
        1. Only fetch CLOSED candles (exclude last one!)
        2. Timestamps in SECONDS (convert from milliseconds)
        3. Use quoteVolume (USD volume, not base currency)
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            timeframe: Candle timeframe (default: '1m')
            limit: Number of candles to fetch (default: 120 = 2 hours)
        
        Returns:
            List of candle dicts with keys:
                - timestamp (int, seconds)
                - open (float)
                - high (float)
                - low (float)
                - close (float)
                - volume (float, quoteVolume in USD)
        
        Examples:
            >>> candles = await exchange.fetch_ohlcv('BTC/USDT', 'spot', '1m', 15)
            >>> len(candles)
            15  # Excludes current open candle!
        """
        original_default_type = self.exchange.options.get('defaultType')
        self.exchange.options['defaultType'] = market
        
        # Bybit V5 API category
        category = 'spot' if market == 'spot' else 'linear'
        
        try:
            logger.debug(
                f"📈 Fetching {timeframe} candles for {symbol} ({market}), limit={limit}"
            )
            
            # Fetch with retry logic inline
            ohlcv = None
            for attempt in range(1, self.retry_max_attempts + 1):
                try:
                    ohlcv = await self.exchange.fetch_ohlcv(
                        symbol,
                        timeframe,
                        limit=limit + 1,
                        params={'category': category}
                    )
                    if attempt > 1:
                        logger.info(f"✅ fetch_ohlcv_{symbol} succeeded on attempt {attempt}")
                    break
                    
                except NetworkError as e:
                    if attempt < self.retry_max_attempts:
                        delay = self.retry_delay * (2 ** (attempt - 1))
                        logger.warning(f"⚠️  fetch_ohlcv_{symbol} retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"❌ fetch_ohlcv_{symbol} failed after retries: {e}")
                        return []
                        
                except Exception as e:
                    logger.error(f"❌ Error fetching candles for {symbol} ({market}): {e}")
                    return []
            
            if not ohlcv:
                logger.warning(f"⚠️  No candles returned for {symbol} ({market})")
                return []
            
            # CRITICAL: Exclude last candle (not closed yet!)
            ohlcv = ohlcv[:-1]
            
            # Convert to our format
            candles = []
            for candle in ohlcv:
                # CCXT format: [timestamp_ms, open, high, low, close, volume]
                timestamp_ms = candle[0]
                open_price = candle[1]
                high = candle[2]
                low = candle[3]
                close = candle[4]
                base_volume = candle[5]  # This is base currency volume
                
                # Calculate quoteVolume (USD volume)
                # quoteVolume = volume * average_price
                avg_price = (high + low) / 2
                quote_volume = base_volume * avg_price
                
                candles.append({
                    'timestamp': milliseconds_to_seconds(timestamp_ms),
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'close': close,
                    'volume': quote_volume  # CRITICAL: Use quoteVolume!
                })
            
            logger.debug(
                f"✅ Fetched {len(candles)} closed candles for {symbol} ({market})"
            )
            
            return candles
            
        except Exception as e:
            logger.error(
                f"❌ Error fetching candles for {symbol} ({market}): {e}",
                exc_info=True
            )
            return []
            
        finally:
            if original_default_type:
                self.exchange.options['defaultType'] = original_default_type
    
    # ============================================
    # Helper Methods
    # ============================================
    
    def get_bybit_url(self, symbol: str, market: str) -> str:
        """
        Get Bybit trading page URL for symbol.
        
        Args:
            symbol: Trading pair (e.g. 'BTC/USDT')
            market: 'spot' or 'futures'
        
        Returns:
            URL string
        
        Examples:
            >>> url = exchange.get_bybit_url('BTC/USDT', 'spot')
            >>> url
            'https://www.bybit.com/trade/spot/BTC/USDT'
        """
        # Remove settlement suffix for futures symbols
        clean_symbol = symbol.replace(':USDT', '')
        
        # Replace / with /
        url_symbol = clean_symbol.replace('/', '/')
        
        if market == 'spot':
            return f"https://www.bybit.com/trade/spot/{url_symbol}"
        else:
            # Futures URL format
            pair = clean_symbol.replace('/', '')
            return f"https://www.bybit.com/trade/usdt/{pair}"
    
    async def _retry_on_network_error(
        self,
        func,
        *args,
        operation: str = "operation",
        **kwargs
    ):
        """
        Retry function on NetworkError with exponential backoff.
        
        CRITICAL: Only retry NetworkError, NOT ExchangeError!
        
        Args:
            func: Async function to call
            *args: Positional arguments
            operation: Operation name for logging
            **kwargs: Keyword arguments
        
        Returns:
            Function result
        
        Raises:
            NetworkError: If all retries failed
            ExchangeError: Immediately (no retry)
        """
        last_error = None
        
        for attempt in range(1, self.retry_max_attempts + 1):
            try:
                # Call function
                result = await func(*args, **kwargs)
                
                # Success!
                if attempt > 1:
                    logger.info(
                        f"✅ {operation} succeeded on attempt {attempt}"
                    )
                
                return result
                
            except NetworkError as e:
                last_error = e
                
                if attempt < self.retry_max_attempts:
                    # Calculate backoff delay (exponential)
                    delay = self.retry_delay * (2 ** (attempt - 1))
                    
                    logger.warning(
                        f"⚠️  {operation} failed (attempt {attempt}/{self.retry_max_attempts}): "
                        f"{e}. Retrying in {delay:.1f}s..."
                    )
                    
                    # Add VPN hint after 2nd failure
                    if attempt >= 2:
                        logger.warning(
                            "💡 Hint: If network errors persist, try enabling VPN"
                        )
                    
                    await asyncio.sleep(delay)
                else:
                    # All retries exhausted
                    logger.error(
                        f"❌ {operation} failed after {self.retry_max_attempts} attempts: {e}"
                    )
                    raise
            
            except ExchangeError as e:
                # Do NOT retry ExchangeError (API errors, invalid symbols, etc.)
                logger.error(f"❌ {operation} failed with ExchangeError: {e}")
                raise
            
            except Exception as e:
                # Unknown error - don't retry
                logger.error(
                    f"❌ {operation} failed with unexpected error: {e}",
                    exc_info=True
                )
                raise
        
        # Should never reach here, but just in case
        raise last_error
    
    async def close(self) -> None:
        """Close exchange connection."""
        if self.exchange:
            await self.exchange.close()
            logger.info("Exchange connection closed")


# ============================================
# Convenience Functions
# ============================================

def create_exchange(
    testnet: bool = False,
    timeout: int = 30000,
    retry_max_attempts: int = 3,
    retry_delay: float = 5.0
) -> BybitExchange:
    """
    Create Bybit exchange instance.
    
    Args:
        testnet: Use testnet
        timeout: Request timeout (ms)
        retry_max_attempts: Max retries
        retry_delay: Retry delay (seconds)
    
    Returns:
        BybitExchange instance
    
    Examples:
        >>> exchange = create_exchange()
        >>> tickers = await exchange.fetch_tickers('spot')
    """
    return BybitExchange(
        testnet=testnet,
        timeout=timeout,
        retry_max_attempts=retry_max_attempts,
        retry_delay=retry_delay
    )


if __name__ == "__main__":
    async def test_exchange():
        """Test exchange operations."""
        print("=" * 50)
        print("Exchange Test")
        print("=" * 50)
        
        exchange = create_exchange()
        
        try:
            # Test spot tickers
            print("\n📊 Fetching spot tickers...")
            spot_tickers = await exchange.fetch_tickers('spot')
            print(f"✅ Spot tickers: {len(spot_tickers)}")
            
            # Test BTC ticker
            if 'BTC/USDT' in spot_tickers:
                btc = spot_tickers['BTC/USDT']
                print(f"   BTC/USDT: ${btc['last']:.2f}, Vol: ${btc.get('quoteVolume', 0):,.0f}")
            
            # Test candles
            print("\n📈 Fetching BTC/USDT candles...")
            candles = await exchange.fetch_ohlcv('BTC/USDT', 'spot', '1m', 5)
            print(f"✅ Candles: {len(candles)}")
            
            if candles:
                last = candles[-1]
                print(f"   Last closed: {format_timestamp(last['timestamp'])}")
                print(f"   Price: ${last['close']:.2f}, Volume: ${last['volume']:,.0f}")
            
            # Test URL generation
            url = exchange.get_bybit_url('BTC/USDT', 'spot')
            print(f"\n🔗 Trading URL: {url}")
            
        finally:
            await exchange.close()
        
        print("\n" + "=" * 50)
        print("Test completed! ✅")
    
    asyncio.run(test_exchange())