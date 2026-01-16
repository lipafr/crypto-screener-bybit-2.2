"""
CoinGecko Database Module
~~~~~~~~~~~~~~~~~~~~~~~~~

Database operations for CoinGecko integration tables.

Tables:
- coingecko_coins: CoinGecko coins reference
- symbol_mapping: Bybit symbol to CoinGecko ID mapping
- market_cap_cache: Market cap data cache
- sync_status: Synchronization status and API usage tracking
"""

import aiosqlite
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class CoinGeckoDatabase:
    """Database manager for CoinGecko integration."""
    
    def __init__(self, db: aiosqlite.Connection):
        """
        Initialize CoinGecko database manager.
        
        Args:
            db: Connected aiosqlite database connection
        """
        self.db = db
    
    # ============================================
    # CoinGecko Coins Table
    # ============================================
    
    async def save_coingecko_coins(self, coins: List[Dict[str, str]]) -> int:
        """
        Save CoinGecko coins list to database.
        
        Args:
            coins: List of coins [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}, ...]
        
        Returns:
            Number of coins saved
        """
        try:
            current_time = int(datetime.now(timezone.utc).timestamp())
            
            # Insert or replace coins
            await self.db.executemany("""
                INSERT OR REPLACE INTO coingecko_coins 
                (coingecko_id, symbol, name, last_updated)
                VALUES (?, ?, ?, ?)
            """, [(coin['id'], coin['symbol'], coin['name'], current_time) for coin in coins])
            
            await self.db.commit()
            
            logger.info(f"✅ Saved {len(coins)} CoinGecko coins to database")
            return len(coins)
        
        except Exception as e:
            logger.error(f"❌ Error saving CoinGecko coins: {e}", exc_info=True)
            await self.db.rollback()
            return 0
    
    async def get_all_coingecko_coins(self) -> List[Dict[str, Any]]:
        """
        Get all CoinGecko coins from database.
        
        Returns:
            List of coins
        """
        try:
            cursor = await self.db.execute("""
                SELECT coingecko_id, symbol, name, last_updated
                FROM coingecko_coins
                ORDER BY symbol
            """)
            
            rows = await cursor.fetchall()
            
            return [
                {
                    'coingecko_id': row[0],
                    'symbol': row[1],
                    'name': row[2],
                    'last_updated': row[3]
                }
                for row in rows
            ]
        
        except Exception as e:
            logger.error(f"❌ Error getting CoinGecko coins: {e}", exc_info=True)
            return []
    
    async def find_coingecko_id_by_symbol(self, symbol: str) -> Optional[str]:
        """
        Find CoinGecko ID by symbol.
        
        Args:
            symbol: Symbol to search (e.g., "btc", "eth")
        
        Returns:
            CoinGecko ID or None if not found
        """
        try:
            cursor = await self.db.execute("""
                SELECT coingecko_id FROM coingecko_coins
                WHERE symbol = ?
                LIMIT 1
            """, (symbol.lower(),))
            
            row = await cursor.fetchone()
            return row[0] if row else None
        
        except Exception as e:
            logger.error(f"❌ Error finding CoinGecko ID: {e}", exc_info=True)
            return None
    
    # ============================================
    # Symbol Mapping Table
    # ============================================
    
    async def save_symbol_mapping(
        self,
        bybit_symbol: str,
        market: str,
        coingecko_id: Optional[str],
        status: str,
        sync_batch_id: str
    ) -> None:
        """
        Save Bybit to CoinGecko symbol mapping.
        
        Args:
            bybit_symbol: Bybit symbol (e.g., "BTC/USDT")
            market: Market type ("spot" or "futures")
            coingecko_id: CoinGecko ID or None if not found
            status: Status ("found", "not_found", "pending")
            sync_batch_id: Sync batch ID (e.g., "2026-W03")
        """
        try:
            current_time = int(datetime.now(timezone.utc).timestamp())
            
            await self.db.execute("""
                INSERT OR REPLACE INTO symbol_mapping
                (bybit_symbol, coingecko_id, market, status, last_check, sync_batch_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (bybit_symbol, coingecko_id, market, status, current_time, sync_batch_id))
            
            await self.db.commit()
        
        except Exception as e:
            logger.error(f"❌ Error saving symbol mapping: {e}", exc_info=True)
            await self.db.rollback()
    
    async def get_symbol_mapping(self, bybit_symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get symbol mapping for a Bybit symbol.
        
        Args:
            bybit_symbol: Bybit symbol (e.g., "BTC/USDT")
        
        Returns:
            Mapping dict or None if not found
        """
        try:
            cursor = await self.db.execute("""
                SELECT bybit_symbol, coingecko_id, market, status, last_check, sync_batch_id
                FROM symbol_mapping
                WHERE bybit_symbol = ?
            """, (bybit_symbol,))
            
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            return {
                'bybit_symbol': row[0],
                'coingecko_id': row[1],
                'market': row[2],
                'status': row[3],
                'last_check': row[4],
                'sync_batch_id': row[5]
            }
        
        except Exception as e:
            logger.error(f"❌ Error getting symbol mapping: {e}", exc_info=True)
            return None
    
    async def get_symbols_for_batch(self, sync_batch_id: str, status: str = None) -> List[str]:
        """
        Get Bybit symbols for a specific sync batch.
        
        Args:
            sync_batch_id: Sync batch ID (e.g., "2026-W03")
            status: Optional status filter
        
        Returns:
            List of Bybit symbols
        """
        try:
            if status:
                cursor = await self.db.execute("""
                    SELECT bybit_symbol FROM symbol_mapping
                    WHERE sync_batch_id = ? AND status = ?
                """, (sync_batch_id, status))
            else:
                cursor = await self.db.execute("""
                    SELECT bybit_symbol FROM symbol_mapping
                    WHERE sync_batch_id = ?
                """, (sync_batch_id,))
            
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
        
        except Exception as e:
            logger.error(f"❌ Error getting symbols for batch: {e}", exc_info=True)
            return []
    
    async def get_mapped_symbols_count(self) -> Dict[str, int]:
        """
        Get count of mapped symbols by status.
        
        Returns:
            Dict with counts {"found": 450, "not_found": 37}
        """
        try:
            cursor = await self.db.execute("""
                SELECT status, COUNT(*) as count
                FROM symbol_mapping
                GROUP BY status
            """)
            
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}
        
        except Exception as e:
            logger.error(f"❌ Error getting mapped symbols count: {e}", exc_info=True)
            return {}
    
    # ============================================
    # Market Cap Cache Table
    # ============================================
    
    async def save_market_cap_data(self, coingecko_id: str, data: Dict[str, Any], ttl: int = 3600) -> None:
        """
        Save market cap data to cache.
        
        Args:
            coingecko_id: CoinGecko ID
            data: Market data from CoinGecko API
            ttl: Cache TTL in seconds
        """
        try:
            current_time = int(datetime.now(timezone.utc).timestamp())
            
            # Extract data from CoinGecko response
            await self.db.execute("""
                INSERT OR REPLACE INTO market_cap_cache
                (
                    coingecko_id, name, symbol,
                    current_price, price_change_24h, price_change_percentage_24h, price_change_percentage_7d,
                    market_cap, market_cap_rank, market_cap_change_24h, market_cap_change_percentage_24h,
                    total_volume_24h,
                    circulating_supply, total_supply, max_supply,
                    ath, ath_change_percentage, ath_date,
                    atl, atl_change_percentage, atl_date,
                    last_updated, cached_at, ttl
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                coingecko_id,
                data.get('name'),
                data.get('symbol'),
                data.get('current_price'),
                data.get('price_change_24h'),
                data.get('price_change_percentage_24h'),
                data.get('price_change_percentage_7d'),
                data.get('market_cap'),
                data.get('market_cap_rank'),
                data.get('market_cap_change_24h'),
                data.get('market_cap_change_percentage_24h'),
                data.get('total_volume'),
                data.get('circulating_supply'),
                data.get('total_supply'),
                data.get('max_supply'),
                data.get('ath'),
                data.get('ath_change_percentage'),
                self._parse_date(data.get('ath_date')),
                data.get('atl'),
                data.get('atl_change_percentage'),
                self._parse_date(data.get('atl_date')),
                self._parse_date(data.get('last_updated')),
                current_time,
                ttl
            ))
            
            await self.db.commit()
        
        except Exception as e:
            logger.error(f"❌ Error saving market cap data: {e}", exc_info=True)
            await self.db.rollback()
    
    async def get_market_cap_data(self, coingecko_id: str) -> Optional[Dict[str, Any]]:
        """
        Get market cap data from cache.
        
        Args:
            coingecko_id: CoinGecko ID
        
        Returns:
            Market cap data or None if not cached or expired
        """
        try:
            current_time = int(datetime.now(timezone.utc).timestamp())
            
            cursor = await self.db.execute("""
                SELECT * FROM market_cap_cache
                WHERE coingecko_id = ?
                AND (cached_at + ttl) > ?
            """, (coingecko_id, current_time))
            
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            # Convert row to dict
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        
        except Exception as e:
            logger.error(f"❌ Error getting market cap data: {e}", exc_info=True)
            return None
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[int]:
        """Parse ISO date string to timestamp."""
        if not date_str:
            return None
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return int(dt.timestamp())
        except:
            return None
    
    # ============================================
    # Sync Status Table
    # ============================================
    
    async def get_sync_status(self) -> Dict[str, Any]:
        """
        Get current sync status.
        
        Returns:
            Sync status dict
        """
        try:
            cursor = await self.db.execute("""
                SELECT * FROM sync_status WHERE id = 1
            """)
            
            row = await cursor.fetchone()
            
            if not row:
                # Initialize if not exists
                await self._init_sync_status()
                return await self.get_sync_status()
            
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        
        except Exception as e:
            logger.error(f"❌ Error getting sync status: {e}", exc_info=True)
            return {}
    
    async def _init_sync_status(self) -> None:
        """Initialize sync status table with default values."""
        current_time = int(datetime.now(timezone.utc).timestamp())
        
        await self.db.execute("""
            INSERT OR IGNORE INTO sync_status (id, sync_state, api_month_start)
            VALUES (1, 'idle', ?)
        """, (current_time,))
        
        await self.db.commit()
    
    async def update_sync_status(self, updates: Dict[str, Any]) -> None:
        """
        Update sync status.
        
        Args:
            updates: Dict of fields to update
        """
        try:
            # Build UPDATE query dynamically
            fields = ', '.join([f"{key} = ?" for key in updates.keys()])
            values = list(updates.values())
            
            await self.db.execute(f"""
                UPDATE sync_status SET {fields} WHERE id = 1
            """, values)
            
            await self.db.commit()
        
        except Exception as e:
            logger.error(f"❌ Error updating sync status: {e}", exc_info=True)
            await self.db.rollback()
    
    async def increment_api_calls(self) -> Dict[str, int]:
        """
        Increment API call counters and check limits.
        
        Returns:
            Dict with current counts {"minute": 5, "month": 123}
        
        Raises:
            Exception: If rate limit exceeded
        """
        try:
            current_time = int(datetime.now(timezone.utc).timestamp())
            status = await self.get_sync_status()
            
            # Check minute window
            minute_start = status.get('api_minute_window_start', 0)
            minute_calls = status.get('api_calls_minute', 0)
            
            # Reset minute counter if new minute
            if current_time - minute_start >= 60:
                minute_calls = 0
                minute_start = current_time
            
            # Increment minute counter
            minute_calls += 1
            
            # Check minute limit (leave buffer: 28 instead of 30)
            if minute_calls >= 28:
                raise Exception("Rate limit: minute limit reached (28/30)")
            
            # Check month limit
            month_calls = status.get('api_calls_month', 0) + 1
            
            if month_calls >= 9900:
                raise Exception("Rate limit: monthly limit approaching (9900/10000)")
            
            # Update counters
            await self.update_sync_status({
                'api_calls_minute': minute_calls,
                'api_minute_window_start': minute_start,
                'api_calls_month': month_calls
            })
            
            return {'minute': minute_calls, 'month': month_calls}
        
        except Exception as e:
            logger.error(f"❌ Error incrementing API calls: {e}")
            raise
    
    async def reset_monthly_api_calls(self) -> None:
        """Reset monthly API call counter (call on 1st of month)."""
        try:
            current_time = int(datetime.now(timezone.utc).timestamp())
            
            await self.update_sync_status({
                'api_calls_month': 0,
                'api_month_start': current_time
            })
            
            logger.info("🔄 Monthly API call counter reset")
        
        except Exception as e:
            logger.error(f"❌ Error resetting monthly API calls: {e}", exc_info=True)
