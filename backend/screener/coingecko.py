"""
CoinGecko Integration Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Handles all interactions with CoinGecko API for market cap data enrichment.

Features:
- Weekly sync of coin mappings (Bybit -> CoinGecko)
- Incremental sync (continues if interrupted)
- Hourly updates for top symbols
- On-demand updates for rare symbols
- Smart caching with TTL
- Rate limit handling (30 req/min, 10,000 req/month)
- Detailed error reporting via Telegram

API Documentation: https://docs.coingecko.com/reference/introduction
"""

import httpx
import logging
import asyncio
import time
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


class CoinGeckoAPIError(Exception):
    """Base exception for CoinGecko API errors"""
    pass


class RateLimitError(CoinGeckoAPIError):
    """Rate limit exceeded"""
    def __init__(self, limit_type: str, retry_after: Optional[int] = None):
        self.limit_type = limit_type  # 'minute' or 'month'
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded: {limit_type}")


class ConnectionError(CoinGeckoAPIError):
    """Connection/network error"""
    pass


class CoinGeckoClient:
    """
    CoinGecko API client with rate limiting and error handling.
    
    Uses Pro API with authentication via x-cg-pro-api-key header.
    """
    
    BASE_URL = "https://pro-api.coingecko.com/api/v3"
    
    def __init__(
        self,
        api_key: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 2.0
    ):
        """
        Initialize CoinGecko client.
        
        Args:
            api_key: CoinGecko Pro API key
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            retry_delay: Delay between retries in seconds
        """
        if not api_key or api_key == "your_coingecko_api_key_here":
            raise ValueError("Invalid CoinGecko API key")
        
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Create HTTP client
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "x-cg-pro-api-key": api_key,
                "Accept": "application/json"
            }
        )
        
        logger.info("✅ CoinGecko client initialized")
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None
    ) -> Dict:
        """
        Make HTTP request to CoinGecko API with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/coins/list")
            params: Query parameters
        
        Returns:
            JSON response as dict
        
        Raises:
            RateLimitError: Rate limit exceeded
            ConnectionError: Network/connection error
            CoinGeckoAPIError: Other API errors
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"🔍 CoinGecko API: {method} {endpoint} (attempt {attempt + 1})")
                
                response = await self.client.request(
                    method=method,
                    url=url,
                    params=params
                )
                
                # Check rate limits
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After')
                    error_text = response.text.lower()
                    
                    # Determine limit type
                    if 'monthly' in error_text or 'month' in error_text:
                        raise RateLimitError('month', retry_after)
                    else:
                        raise RateLimitError('minute', retry_after)
                
                # Check other errors
                response.raise_for_status()
                
                # Success
                data = response.json()
                logger.debug(f"✅ CoinGecko API: {endpoint} success")
                return data
            
            except httpx.TimeoutException as e:
                logger.warning(f"⏱️ Timeout on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise ConnectionError(f"Request timeout after {self.max_retries} attempts")
            
            except httpx.NetworkError as e:
                logger.warning(f"🌐 Network error on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise ConnectionError(f"Network error after {self.max_retries} attempts: {e}")
            
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limit - already handled above
                    raise
                else:
                    # Other HTTP error
                    raise CoinGeckoAPIError(
                        f"HTTP {e.response.status_code}: {e.response.text}"
                    )
    
    async def fetch_coins_list(self) -> List[Dict]:
        """
        Fetch complete list of coins from CoinGecko.
        
        Returns:
            List of coins: [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}, ...]
        
        Raises:
            RateLimitError, ConnectionError, CoinGeckoAPIError
        
        API Call Cost: 1 call
        """
        logger.info("📥 Fetching CoinGecko coins list...")
        
        data = await self._request("GET", "/coins/list")
        
        logger.info(f"✅ Fetched {len(data)} coins from CoinGecko")
        return data
    
    async def fetch_markets(
        self,
        ids: Optional[List[str]] = None,
        per_page: int = 250,
        page: int = 1
    ) -> List[Dict]:
        """
        Fetch market data for coins.
        
        Args:
            ids: List of CoinGecko IDs to fetch (max 250). If None, fetches top coins.
            per_page: Results per page (max 250)
            page: Page number
        
        Returns:
            List of market data dicts
        
        Raises:
            RateLimitError, ConnectionError, CoinGeckoAPIError
        
        API Call Cost: 1 call per 250 coins
        """
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": min(per_page, 250),
            "page": page,
            "sparkline": False,
            "price_change_percentage": "24h,7d"
        }
        
        if ids:
            params["ids"] = ",".join(ids[:250])  # Max 250
            logger.info(f"📥 Fetching market data for {len(ids)} coins...")
        else:
            logger.info(f"📥 Fetching top {per_page} coins (page {page})...")
        
        data = await self._request("GET", "/coins/markets", params=params)
        
        logger.info(f"✅ Fetched market data for {len(data)} coins")
        return data
    
    async def fetch_coin(self, coin_id: str) -> Dict:
        """
        Fetch detailed data for a single coin.
        
        Args:
            coin_id: CoinGecko ID (e.g., "bitcoin")
        
        Returns:
            Coin data dict
        
        Raises:
            RateLimitError, ConnectionError, CoinGeckoAPIError
        
        API Call Cost: 1 call
        """
        logger.info(f"📥 Fetching data for coin: {coin_id}")
        
        params = {
            "localization": False,
            "tickers": False,
            "community_data": False,
            "developer_data": False
        }
        
        data = await self._request("GET", f"/coins/{coin_id}", params=params)
        
        logger.info(f"✅ Fetched data for {coin_id}")
        return data


def find_coingecko_id(coins_list: List[Dict], base_currency: str) -> Optional[str]:
    """
    Find CoinGecko ID for a base currency symbol.
    
    Args:
        coins_list: List of coins from fetch_coins_list()
        base_currency: Base currency symbol (e.g., "BTC", "ETH")
    
    Returns:
        CoinGecko ID (e.g., "bitcoin") or None if not found
    
    Examples:
        >>> coins = [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}]
        >>> find_coingecko_id(coins, "BTC")
        "bitcoin"
    """
    base_lower = base_currency.lower()
    
    # First try: exact symbol match
    for coin in coins_list:
        if coin['symbol'].lower() == base_lower:
            return coin['id']
    
    # Second try: name contains symbol (for wrapped tokens)
    for coin in coins_list:
        if base_lower in coin['name'].lower():
            return coin['id']
    
    # Not found
    return None


def extract_base_currency(symbol: str) -> str:
    """
    Extract base currency from Bybit symbol.
    
    Args:
        symbol: Bybit symbol (e.g., "BTC/USDT", "ETH/USDT:USDT")
    
    Returns:
        Base currency (e.g., "BTC", "ETH")
    
    Examples:
        >>> extract_base_currency("BTC/USDT")
        "BTC"
        >>> extract_base_currency("ETH/USDT:USDT")
        "ETH"
    """
    # Remove :USDT suffix for futures
    if ":" in symbol:
        symbol = symbol.split(":")[0]
    
    # Split by /
    parts = symbol.split("/")
    return parts[0] if parts else symbol


def get_current_sync_week() -> str:
    """
    Get current sync week ID.
    
    Week starts on Sunday 00:00 UTC.
    
    Returns:
        Week ID in format "YYYY-WNN" (e.g., "2026-W03")
    
    Examples:
        >>> # If today is Wednesday, Jan 15, 2026
        >>> get_current_sync_week()
        "2026-W03"  # Week starting on Sunday, Jan 12
    """
    now = datetime.now(timezone.utc)
    
    # Find last Sunday
    days_since_sunday = (now.weekday() + 1) % 7
    last_sunday = now - timedelta(days=days_since_sunday)
    
    # ISO week number
    week_num = last_sunday.isocalendar()[1]
    year = last_sunday.year
    
    return f"{year}-W{week_num:02d}"


def is_new_sync_week(last_sync_week: Optional[str]) -> bool:
    """
    Check if a new sync week has started.
    
    Args:
        last_sync_week: Last sync week ID (e.g., "2026-W03")
    
    Returns:
        True if current week is different from last sync week
    
    Examples:
        >>> is_new_sync_week("2026-W02")
        True  # If current week is W03
        >>> is_new_sync_week("2026-W03")
        False  # If current week is also W03
    """
    if not last_sync_week:
        return True
    
    current_week = get_current_sync_week()
    return current_week != last_sync_week


def format_large_number(num: float) -> str:
    """
    Format large numbers in readable format.
    
    Args:
        num: Number to format
    
    Returns:
        Formatted string (e.g., "1.2T", "45.3B", "890M")
    
    Examples:
        >>> format_large_number(1_200_000_000_000)
        "1.2T"
        >>> format_large_number(45_300_000_000)
        "45.3B"
        >>> format_large_number(890_000_000)
        "890M"
    """
    if num >= 1e12:
        return f"{num/1e12:.1f}T"
    elif num >= 1e9:
        return f"{num/1e9:.1f}B"
    elif num >= 1e6:
        return f"{num/1e6:.1f}M"
    elif num >= 1e3:
        return f"{num/1e3:.1f}K"
    else:
        return f"{num:.0f}"


def format_time_ago(seconds: int) -> str:
    """
    Format time "ago" in human-readable format.
    
    Args:
        seconds: Seconds elapsed
    
    Returns:
        Human-readable string (e.g., "5 min ago", "2 hours ago")
    
    Examples:
        >>> format_time_ago(300)
        "5 min ago"
        >>> format_time_ago(7200)
        "2 hours ago"
        >>> format_time_ago(172800)
        "2 days ago"
    """
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} min ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    else:
        days = seconds // 86400
        return f"{days} day{'s' if days > 1 else ''} ago"
