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
from typing import Optional, List, Dict, Any
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
    
    async def execute(self, query: str, params: tuple = ()) -> aiosqlite.Cursor:
        """
        Execute SQL query.
        
        Args:
            query: SQL query
            params: Query parameters
        
        Returns:
            Cursor object
        """
        return await self.db.execute(query, params)
    
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
    
    async def save_candle(
        self,
        symbol: str,
        market: str,
        timestamp: int,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float
    ) -> bool:
        """
        Save single candle to database.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            timestamp: Candle timestamp (seconds)
            open_price: Open price
            high: High price
            low: Low price
            close: Close price
            volume: Volume
        
        Returns:
            True if saved successfully
        """
        try:
            await self.db.execute("""
                INSERT OR REPLACE INTO candles 
                (symbol, market, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, market, timestamp, open_price, high, low, close, volume))
            
            await self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"❌ Error saving candle: {e}", exc_info=True)
            await self.db.rollback()
            return False
    
    async def save_candles(
        self,
        symbol: str,
        market: str,
        candles: List[Dict]
    ) -> int:
        """
        Save multiple candles (batch insert).
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            candles: List of candle dicts with keys: timestamp, open, high, low, close, volume
        
        Returns:
            Number of candles saved
        """
        try:
            data = [
                (symbol, market, c['timestamp'], c['open'], c['high'], c['low'], c['close'], c.get('volume', 0))
                for c in candles
            ]
            
            await self.db.executemany("""
                INSERT OR REPLACE INTO candles 
                (symbol, market, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
            
            await self.db.commit()
            
            logger.debug(f"✅ Saved {len(candles)} candles for {symbol} ({market})")
            
            return len(candles)
            
        except Exception as e:
            logger.error(f"❌ Error saving candles: {e}", exc_info=True)
            await self.db.rollback()
            return 0
    
    async def get_candles(
        self,
        symbol: str,
        market: str,
        minutes: int
    ) -> List[Dict]:
        """
        Get candles for last N minutes.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            minutes: Number of minutes to retrieve
        
        Returns:
            List of candle dicts (oldest first)
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
            
            return candles
            
        except Exception as e:
            logger.error(f"❌ Error getting candles: {e}", exc_info=True)
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
    ) -> bool:
        """
        Save or update ticker data.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
            volume_24h: 24h quote volume
            last_price: Last price
        
        Returns:
            True if saved successfully
        """
        try:
            current_time = get_current_timestamp()
            
            await self.db.execute("""
                INSERT OR REPLACE INTO tickers 
                (symbol, market, volume_24h, last_price, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, market, volume_24h, last_price, current_time))
            
            await self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"❌ Error saving ticker: {e}", exc_info=True)
            await self.db.rollback()
            return False
    
    async def get_ticker(self, symbol: str, market: str) -> Optional[Dict]:
        """
        Get ticker data.
        
        Args:
            symbol: Trading pair
            market: 'spot' or 'futures'
        
        Returns:
            Ticker dict or None
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
                'symbol': symbol,
                'market': market,
                'volume_24h': row['volume_24h'],
                'last_price': row['last_price'],
                'updated_at': row['updated_at']
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting ticker: {e}", exc_info=True)
            return None
    
    async def get_symbols_for_market(self, market: str) -> List[str]:
        """
        Get all symbols for market.
        
        Args:
            market: 'spot' or 'futures'
        
        Returns:
            List of symbols
        """
        try:
            cursor = await self.db.execute("""
                SELECT DISTINCT symbol
                FROM tickers
                WHERE market = ?
                ORDER BY volume_24h DESC
            """, (market,))
            
            rows = await cursor.fetchall()
            
            return [row['symbol'] for row in rows]
            
        except Exception as e:
            logger.error(f"❌ Error getting symbols: {e}", exc_info=True)
            return []
    
    # ============================================
    # Filters Operations
    # ============================================
    
    async def create_filter(
        self,
        name: str,
        filter_type: str,
        config: Dict,
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
            
            logger.info(f"✅ Created filter #{filter_id}: {name} ({filter_type})")
            
            return filter_id
            
        except Exception as e:
            logger.error(f"❌ Error creating filter: {e}", exc_info=True)
            await self.db.rollback()
            raise
    
    async def get_filter(self, filter_id: int) -> Optional[Dict]:
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
    
    async def get_all_filters(self, enabled_only: bool = False) -> List[Dict]:
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
    
    async def get_active_filters(self) -> List[Dict]:
        """
        Get only enabled filters.
        
        This is a convenience method that calls get_all_filters(enabled_only=True).
        
        Returns:
            List of enabled filter dicts
        """
        return await self.get_all_filters(enabled_only=True)
    
    async def update_filter(
        self,
        filter_id: int,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        config: Optional[Dict] = None
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
                return True
            
            updates.append("updated_at = ?")
            params.append(get_current_timestamp())
            
            params.append(filter_id)
            
            query = f"UPDATE filters SET {', '.join(updates)} WHERE id = ?"
            
            await self.db.execute(query, tuple(params))
            await self.db.commit()
            
            logger.info(f"✅ Updated filter #{filter_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating filter: {e}", exc_info=True)
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
            
            logger.info(f"✅ Deleted filter #{filter_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error deleting filter: {e}", exc_info=True)
            await self.db.rollback()
            return False
    
    async def toggle_filter(self, filter_id: int) -> bool:
        """
        Toggle filter enabled status.
        
        Args:
            filter_id: Filter ID
        
        Returns:
            New enabled status
        """
        try:
            # Get current status
            filter_data = await self.get_filter(filter_id)
            
            if not filter_data:
                return False
            
            new_status = not filter_data['enabled']
            
            # Update
            await self.update_filter(filter_id, enabled=new_status)
            
            return new_status
            
        except Exception as e:
            logger.error(f"❌ Error toggling filter: {e}", exc_info=True)
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
        data: Dict
    ) -> int:
        """
        Save filter trigger.
        
        Args:
            filter_id: Filter ID
            filter_name: Filter name
            symbol: Trading pair
            market: 'spot' or 'futures'
            data: Trigger data dict
        
        Returns:
            Trigger ID
        """
        try:
            data_json = json.dumps(data)
            current_time = get_current_timestamp()
            
            cursor = await self.db.execute("""
                INSERT INTO filter_triggers 
                (filter_id, filter_name, symbol, market, triggered_at, data, notified)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (filter_id, filter_name, symbol, market, current_time, data_json))
            
            await self.db.commit()
            
            trigger_id = cursor.lastrowid
            
            logger.info(f"✅ Saved trigger #{trigger_id}: {filter_name} → {symbol}")
            
            return trigger_id
            
        except Exception as e:
            logger.error(f"❌ Error saving trigger: {e}", exc_info=True)
            await self.db.rollback()
            return 0
    
    async def get_triggers(
        self,
        filter_id: Optional[int] = None,
        symbol: Optional[str] = None,
        market: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get triggers with filtering and pagination.
        
        Args:
            filter_id: Filter by filter ID
            symbol: Filter by symbol
            market: Filter by market
            limit: Max results
            offset: Skip first N results
        
        Returns:
            Dict with 'triggers' list and 'total' count
        """
        try:
            # Build query
            where_clauses = []
            params = []
            
            if filter_id is not None:
                where_clauses.append("filter_id = ?")
                params.append(filter_id)
            
            if symbol:
                where_clauses.append("symbol = ?")
                params.append(symbol)
            
            if market:
                where_clauses.append("market = ?")
                params.append(market)
            
            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
            
            # Get total count
            count_cursor = await self.db.execute(
                f"SELECT COUNT(*) as count FROM filter_triggers {where_sql}",
                tuple(params)
            )
            count_row = await count_cursor.fetchone()
            total = count_row['count']
            
            # Get triggers
            params.extend([limit, offset])
            
            cursor = await self.db.execute(f"""
                SELECT id, filter_id, filter_name, symbol, market, triggered_at, data, notified
                FROM filter_triggers
                {where_sql}
                ORDER BY triggered_at DESC
                LIMIT ? OFFSET ?
            """, tuple(params))
            
            rows = await cursor.fetchall()
            
            triggers = []
            for row in rows:
                triggers.append({
                    'id': row['id'],
                    'filter_id': row['filter_id'],
                    'filter_name': row['filter_name'],
                    'symbol': row['symbol'],
                    'market': row['market'],
                    'triggered_at': row['triggered_at'],
                    'data': json.loads(row['data']),
                    'notified': bool(row['notified'])
                })
            
            return {
                'triggers': triggers,
                'total': total
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting triggers: {e}", exc_info=True)
            return {'triggers': [], 'total': 0}
    
    async def check_cooldown(
        self,
        filter_id: int,
        symbol: str,
        market: str,
        cooldown_minutes: int
    ) -> bool:
        """
        Check if filter can trigger again (cooldown check).
        
        Args:
            filter_id: Filter ID
            symbol: Trading pair
            market: 'spot' or 'futures'
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
                  AND market = ?
                  AND triggered_at > ?
            """, (filter_id, symbol, market, cutoff_time))
            
            row = await cursor.fetchone()
            count = row['count']
            
            can_trigger = (count == 0)
            
            if not can_trigger:
                logger.debug(f"⏸️  Cooldown active for filter #{filter_id} → {symbol}")
            
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
    """
    db = Database(db_path)
    await db.connect()
    return db