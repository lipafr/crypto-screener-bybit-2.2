"""
Database Module
~~~~~~~~~~~~~~~

CRITICAL: SQLite database operations for crypto screener.

Tables:
- candles: Historical OHLCV data (last 2 hours)
- tickers: Current 24h volume and price data
- filters: User-defined filter configurations
- filter_triggers: History of filter activations

KEY REQUIREMENTS:
1. All timestamps in SECONDS (not milliseconds)
2. Separate spot and futures data by 'market' field
3. Use quoteVolume for volume comparisons (in USD)
4. Automatic cleanup of old data
5. Proper indexes for performance
"""

import aiosqlite
import json
import logging
from typing import Optional, Any
from pathlib import Path

from .time_utils import (
    get_current_timestamp,
    get_timestamp_n_minutes_ago,
    format_timestamp
)

logger = logging.getLogger(__name__)


class Database:
    """
    Async SQLite database manager.
    
    Handles all database operations including:
    - Schema creation
    - CRUD operations for all tables
    - Automatic cleanup
    - Data retrieval for screening
    """
    
    def __init__(self, db_path: str = "/data/screener.db"):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None
        
        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Database initialized: {db_path}")
    
    # ============================================
    # Connection Management
    # ============================================
    
    async def connect(self) -> None:
        """
        Connect to database and create schema if needed.
        
        Raises:
            aiosqlite.Error: If connection fails
        """
        try:
            self.db = await aiosqlite.connect(self.db_path)
            self.db.row_factory = aiosqlite.Row
            logger.info("✅ Database connected")
            
            # Create schema
            await self._create_schema()
            
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}", exc_info=True)
            raise
    
    async def close(self) -> None:
        """Close database connection."""
        if self.db:
            await self.db.close()
            logger.info("Database connection closed")
    
    async def _create_schema(self) -> None:
        """
        Create database schema if tables don't exist.
        
        Creates:
        - candles table with indexes
        - tickers table
        - filters table
        - filter_triggers table with indexes
        """
        try:
            # ============================================
            # Candles Table
            # ============================================
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    created_at INTEGER DEFAULT (strftime('%s', 'now')),
                    UNIQUE(symbol, market, timestamp)
                )
            """)
            
            # Indexes for candles
            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_candles_symbol_market_time 
                ON candles(symbol, market, timestamp DESC)
            """)
            
            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_candles_timestamp 
                ON candles(timestamp)
            """)
            
            # ============================================
            # Tickers Table
            # ============================================
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS tickers (
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    volume_24h REAL,
                    last_price REAL,
                    updated_at INTEGER DEFAULT (strftime('%s', 'now')),
                    PRIMARY KEY (symbol, market)
                )
            """)
            
            # ============================================
            # Filters Table
            # ============================================
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    config TEXT NOT NULL,
                    created_at INTEGER DEFAULT (strftime('%s', 'now')),
                    updated_at INTEGER
                )
            """)
            
            # ============================================
            # Filter Triggers Table
            # ============================================
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS filter_triggers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filter_id INTEGER NOT NULL,
                    filter_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    triggered_at INTEGER DEFAULT (strftime('%s', 'now')),
                    data TEXT,
                    notified INTEGER DEFAULT 0,
                    FOREIGN KEY (filter_id) REFERENCES filters(id)
                )
            """)
            
            # Indexes for triggers
            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_triggers_filter_symbol_time 
                ON filter_triggers(filter_id, symbol, triggered_at DESC)
            """)
            
            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_triggers_time 
                ON filter_triggers(triggered_at DESC)
            """)
            
            await self.db.commit()
            logger.debug("✅ Database schema created/verified")
            
        except Exception as e:
            logger.error(f"❌ Schema creation failed: {e}", exc_info=True)
            raise
    
    # ============================================
    # Candles Operations
    # ============================================
    
    async def save_candles(
        self,
        symbol: str,
        market: str,
        candles: list[dict]
    ) -> int:
        """
        Save candles to database (batch insert with conflict handling).
        
        Args:
            symbol: Trading pair (e.g. 'BTC/USDT')
            market: 'spot' or 'futures'
            candles: List of candle dicts with keys: timestamp, open, high, low, close, volume
        
        Returns:
            Number of candles inserted
        
        Examples:
            >>> candles = [
            ...     {
            ...         'timestamp': 1704805440,
            ...         'open': 142.5,
            ...         'high': 143.2,
            ...         'low': 142.1,
            ...         'close': 142.9,
            ...         'volume': 15000
            ...     }
            ... ]
            >>> count = await db.save_candles('SOL/USDT', 'spot', candles)
        """
        if not candles:
            return 0
        
        try:
            inserted = 0
            
            for candle in candles:
                # INSERT OR REPLACE to handle duplicates
                await self.db.execute("""
                    INSERT OR REPLACE INTO candles 
                    (symbol, market, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol,
                    market,
                    candle['timestamp'],
                    candle['open'],
                    candle['high'],
                    candle['low'],
                    candle['close'],
                    candle['volume']
                ))
                inserted += 1
            
            await self.db.commit()
            
            logger.debug(
                f"💾 Saved {inserted} candles for {symbol} ({market})"
            )
            
            return inserted
            
        except Exception as e:
            logger.error(
                f"❌ Error saving candles for {symbol} ({market}): {e}",
                exc_info=True
            )
            await self.db.rollback()
            raise
    
    async def get_candles(
        self,
        symbol: str,
        market: str,
        minutes: int
    ) -> list[dict]:
        """
        Get candles for symbol for last N minutes.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            minutes: Number of minutes to fetch
        
        Returns:
            List of candle dicts, ordered by timestamp ASC
        
        Examples:
            >>> candles = await db.get_candles('BTC/USDT', 'spot', 15)
            >>> len(candles)
            15
        """
        try:
            cutoff_time = get_timestamp_n_minutes_ago(minutes)
            
            cursor = await self.db.execute("""
                SELECT timestamp, open, high, low, close, volume
                FROM candles
                WHERE symbol = ? AND market = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (symbol, market, cutoff_time))
            
            rows = await cursor.fetchall()
            
            candles = [
                {
                    'timestamp': row['timestamp'],
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume']
                }
                for row in rows
            ]
            
            logger.debug(
                f"📊 Retrieved {len(candles)} candles for {symbol} ({market}), "
                f"last {minutes} minutes"
            )
            
            return candles
            
        except Exception as e:
            logger.error(
                f"❌ Error getting candles for {symbol} ({market}): {e}",
                exc_info=True
            )
            return []
    
    async def cleanup_old_candles(self, hours: int = 2) -> int:
        """
        Delete candles older than N hours.
        
        Args:
            hours: Keep candles from last N hours
        
        Returns:
            Number of deleted rows
        """
        try:
            cutoff_time = get_timestamp_n_minutes_ago(hours * 60)
            
            cursor = await self.db.execute("""
                DELETE FROM candles WHERE timestamp < ?
            """, (cutoff_time,))
            
            await self.db.commit()
            
            deleted = cursor.rowcount
            
            if deleted > 0:
                logger.info(f"🗑️  Cleaned up {deleted} old candles (>{hours}h)")
            
            return deleted
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up candles: {e}", exc_info=True)
            await self.db.rollback()
            return 0
    
    # ============================================
    # Tickers Operations
    # ============================================
    
    async def save_ticker(
        self,
        symbol: str,
        market: str,
        volume_24h: float,
        last_price: float
    ) -> None:
        """
        Save or update ticker data.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            volume_24h: 24h volume in USD
            last_price: Last traded price
        """
        try:
            await self.db.execute("""
                INSERT OR REPLACE INTO tickers 
                (symbol, market, volume_24h, last_price, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                symbol,
                market,
                volume_24h,
                last_price,
                get_current_timestamp()
            ))
            
            await self.db.commit()
            
            logger.debug(
                f"💾 Saved ticker for {symbol} ({market}): "
                f"vol24h=${volume_24h:,.0f}, price=${last_price:.2f}"
            )
            
        except Exception as e:
            logger.error(
                f"❌ Error saving ticker for {symbol} ({market}): {e}",
                exc_info=True
            )
            await self.db.rollback()
            raise
    
    async def get_ticker(
        self,
        symbol: str,
        market: str
    ) -> Optional[dict]:
        """
        Get ticker data for symbol.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
        
        Returns:
            Ticker dict or None if not found
        """
        try:
            cursor = await self.db.execute("""
                SELECT volume_24h, last_price, updated_at
                FROM tickers
                WHERE symbol = ? AND market = ?
            """, (symbol, market))
            
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            return {
                'volume_24h': row['volume_24h'],
                'last_price': row['last_price'],
                'updated_at': row['updated_at']
            }
            
        except Exception as e:
            logger.error(
                f"❌ Error getting ticker for {symbol} ({market}): {e}",
                exc_info=True
            )
            return None
    
    # ============================================
    # Filters Operations
    # ============================================
    
    async def create_filter(
        self,
        name: str,
        filter_type: str,
        config: dict,
        enabled: bool = True
    ) -> int:
        """
        Create new filter.
        
        Args:
            name: Filter name
            filter_type: 'price_change' or 'volume_spike'
            config: Filter configuration dict
            enabled: Whether filter is active
        
        Returns:
            Filter ID
        """
        try:
            config_json = json.dumps(config)
            
            cursor = await self.db.execute("""
                INSERT INTO filters (name, type, enabled, config)
                VALUES (?, ?, ?, ?)
            """, (name, filter_type, int(enabled), config_json))
            
            await self.db.commit()
            
            filter_id = cursor.lastrowid
            
            logger.info(
                f"✅ Created filter #{filter_id}: {name} ({filter_type})"
            )
            
            return filter_id
            
        except Exception as e:
            logger.error(f"❌ Error creating filter: {e}", exc_info=True)
            await self.db.rollback()
            raise
    
    async def get_filter(self, filter_id: int) -> Optional[dict]:
        """
        Get filter by ID.
        
        Args:
            filter_id: Filter ID
        
        Returns:
            Filter dict or None
        """
        try:
            cursor = await self.db.execute("""
                SELECT id, name, type, enabled, config, created_at, updated_at
                FROM filters
                WHERE id = ?
            """, (filter_id,))
            
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            return {
                'id': row['id'],
                'name': row['name'],
                'type': row['type'],
                'enabled': bool(row['enabled']),
                'config': json.loads(row['config']),
                'created_at': row['created_at'],
                'updated_at': row['updated_at']
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting filter {filter_id}: {e}", exc_info=True)
            return None
    
    async def get_all_filters(
        self,
        enabled_only: bool = False
    ) -> list[dict]:
        """
        Get all filters.
        
        Args:
            enabled_only: Only return enabled filters
        
        Returns:
            List of filter dicts
        """
        try:
            if enabled_only:
                cursor = await self.db.execute("""
                    SELECT id, name, type, enabled, config, created_at, updated_at
                    FROM filters
                    WHERE enabled = 1
                    ORDER BY created_at DESC
                """)
            else:
                cursor = await self.db.execute("""
                    SELECT id, name, type, enabled, config, created_at, updated_at
                    FROM filters
                    ORDER BY created_at DESC
                """)
            
            rows = await cursor.fetchall()
            
            filters = []
            for row in rows:
                filters.append({
                    'id': row['id'],
                    'name': row['name'],
                    'type': row['type'],
                    'enabled': bool(row['enabled']),
                    'config': json.loads(row['config']),
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                })
            
            logger.debug(f"📋 Retrieved {len(filters)} filters")
            
            return filters
            
        except Exception as e:
            logger.error(f"❌ Error getting filters: {e}", exc_info=True)
            return []
    
    async def update_filter(
        self,
        filter_id: int,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        config: Optional[dict] = None
    ) -> bool:
        """
        Update filter.
        
        Args:
            filter_id: Filter ID
            name: New name (optional)
            enabled: New enabled status (optional)
            config: New config (optional)
        
        Returns:
            True if updated successfully
        """
        try:
            updates = []
            params = []
            
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            
            if enabled is not None:
                updates.append("enabled = ?")
                params.append(int(enabled))
            
            if config is not None:
                updates.append("config = ?")
                params.append(json.dumps(config))
            
            if not updates:
                return True  # Nothing to update
            
            updates.append("updated_at = ?")
            params.append(get_current_timestamp())
            
            params.append(filter_id)
            
            query = f"UPDATE filters SET {', '.join(updates)} WHERE id = ?"
            
            await self.db.execute(query, params)
            await self.db.commit()
            
            logger.info(f"✅ Updated filter #{filter_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating filter {filter_id}: {e}", exc_info=True)
            await self.db.rollback()
            return False
    
    async def delete_filter(self, filter_id: int) -> bool:
        """
        Delete filter.
        
        Args:
            filter_id: Filter ID
        
        Returns:
            True if deleted successfully
        """
        try:
            await self.db.execute("DELETE FROM filters WHERE id = ?", (filter_id,))
            await self.db.commit()
            
            logger.info(f"🗑️  Deleted filter #{filter_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error deleting filter {filter_id}: {e}", exc_info=True)
            await self.db.rollback()
            return False
    
    # ============================================
    # Triggers Operations
    # ============================================
    
    async def save_trigger(
        self,
        filter_id: int,
        filter_name: str,
        symbol: str,
        market: str,
        data: dict,
        notified: bool = False
    ) -> int:
        """
        Save filter trigger event.
        
        Args:
            filter_id: Filter ID that triggered
            filter_name: Filter name at trigger time
            symbol: Trading pair
            market: 'spot' or 'futures'
            data: Trigger data (price, volume, etc.)
            notified: Whether notification was sent
        
        Returns:
            Trigger ID
        """
        try:
            data_json = json.dumps(data)
            
            cursor = await self.db.execute("""
                INSERT INTO filter_triggers 
                (filter_id, filter_name, symbol, market, data, notified)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                filter_id,
                filter_name,
                symbol,
                market,
                data_json,
                int(notified)
            ))
            
            await self.db.commit()
            
            trigger_id = cursor.lastrowid
            
            logger.info(
                f"🔔 Trigger #{trigger_id}: {filter_name} → {symbol} ({market})"
            )
            
            return trigger_id
            
        except Exception as e:
            logger.error(f"❌ Error saving trigger: {e}", exc_info=True)
            await self.db.rollback()
            raise
    
    async def get_last_trigger(
        self,
        filter_id: int,
        symbol: str
    ) -> Optional[dict]:
        """
        Get last trigger for filter and symbol.
        
        Args:
            filter_id: Filter ID
            symbol: Trading pair
        
        Returns:
            Trigger dict or None
        """
        try:
            cursor = await self.db.execute("""
                SELECT id, triggered_at, data
                FROM filter_triggers
                WHERE filter_id = ? AND symbol = ?
                ORDER BY triggered_at DESC
                LIMIT 1
            """, (filter_id, symbol))
            
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            return {
                'id': row['id'],
                'triggered_at': row['triggered_at'],
                'data': json.loads(row['data'])
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting last trigger: {e}", exc_info=True)
            return None
    
    async def check_cooldown(
        self,
        filter_id: int,
        symbol: str,
        cooldown_minutes: int
    ) -> bool:
        """
        Check if cooldown period has passed since last trigger.
        
        Args:
            filter_id: Filter ID
            symbol: Trading pair
            cooldown_minutes: Cooldown period in minutes
        
        Returns:
            True if can trigger (cooldown passed or no previous trigger)
        """
        try:
            cutoff_time = get_timestamp_n_minutes_ago(cooldown_minutes)
            
            cursor = await self.db.execute("""
                SELECT COUNT(*) as count
                FROM filter_triggers
                WHERE filter_id = ? 
                  AND symbol = ? 
                  AND triggered_at > ?
            """, (filter_id, symbol, cutoff_time))
            
            row = await cursor.fetchone()
            count = row['count']
            
            can_trigger = (count == 0)
            
            if not can_trigger:
                logger.debug(
                    f"⏸️  Cooldown active for filter #{filter_id} → {symbol}"
                )
            
            return can_trigger
            
        except Exception as e:
            logger.error(f"❌ Error checking cooldown: {e}", exc_info=True)
            return False
    
    async def cleanup_old_triggers(self, days: int = 30) -> int:
        """
        Delete triggers older than N days.
        
        Args:
            days: Keep triggers from last N days
        
        Returns:
            Number of deleted rows
        """
        try:
            cutoff_time = get_timestamp_n_minutes_ago(days * 24 * 60)
            
            cursor = await self.db.execute("""
                DELETE FROM filter_triggers WHERE triggered_at < ?
            """, (cutoff_time,))
            
            await self.db.commit()
            
            deleted = cursor.rowcount
            
            if deleted > 0:
                logger.info(f"🗑️  Cleaned up {deleted} old triggers (>{days} days)")
            
            return deleted
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up triggers: {e}", exc_info=True)
            await self.db.rollback()
            return 0


# ============================================
# Convenience Functions
# ============================================

async def get_database(db_path: str = "/data/screener.db") -> Database:
    """
    Create and connect to database.
    
    Args:
        db_path: Path to SQLite database
    
    Returns:
        Connected Database instance
    
    Examples:
        >>> db = await get_database()
        >>> filters = await db.get_all_filters()
    """
    db = Database(db_path)
    await db.connect()
    return db


if __name__ == "__main__":
    import asyncio
    
    async def test_database():
        """Test database operations."""
        print("=" * 50)
        print("Database Test")
        print("=" * 50)
        
        # Create database
        db = Database("/tmp/test_screener.db")
        await db.connect()
        
        # Test candles
        test_candles = [
            {
                'timestamp': get_current_timestamp() - 120,
                'open': 100.0,
                'high': 101.0,
                'low': 99.0,
                'close': 100.5,
                'volume': 10000
            }
        ]
        
        await db.save_candles("BTC/USDT", "spot", test_candles)
        candles = await db.get_candles("BTC/USDT", "spot", 5)
        print(f"\n✅ Candles test: {len(candles)} candles")
        
        # Test ticker
        await db.save_ticker("BTC/USDT", "spot", 1000000, 42000)
        ticker = await db.get_ticker("BTC/USDT", "spot")
        print(f"✅ Ticker test: ${ticker['volume_24h']:,.0f}")
        
        # Test filter
        config = {
            'market': 'spot',
            'interval_minutes': 15,
            'min_price_change_percent': 5.0
        }
        filter_id = await db.create_filter("Test Filter", "price_change", config)
        print(f"✅ Filter test: #{filter_id}")
        
        # Test trigger
        trigger_data = {'price_change_percent': 7.5}
        trigger_id = await db.save_trigger(
            filter_id, "Test Filter", "BTC/USDT", "spot", trigger_data
        )
        print(f"✅ Trigger test: #{trigger_id}")
        
        # Check cooldown
        can_trigger = await db.check_cooldown(filter_id, "BTC/USDT", 15)
        print(f"✅ Cooldown test: {can_trigger}")
        
        await db.close()
        print("\n" + "=" * 50)
        print("All tests passed! ✅")
    
    asyncio.run(test_database())
