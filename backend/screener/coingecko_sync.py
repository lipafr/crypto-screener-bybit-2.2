"""
CoinGecko Synchronization Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Handles synchronization of CoinGecko data with Bybit symbols.

Features:
- Weekly full synchronization
- Incremental sync (continues if interrupted)
- Hourly updates for top symbols
- On-demand updates for rare symbols
- Rate limit handling
- Error recovery
"""

import asyncio
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone

from backend.config import settings
from backend.screener.coingecko import (
    CoinGeckoClient,
    find_coingecko_id,
    extract_base_currency,
    get_current_sync_week,
    is_new_sync_week,
    RateLimitError,
    ConnectionError as CoinGeckoConnectionError
)

logger = logging.getLogger(__name__)


class CoinGeckoSync:
    """CoinGecko synchronization manager."""
    
    def __init__(self, db, exchange, telegram_notifier):
        """
        Initialize sync manager.
        
        Args:
            db: CoinGeckoDatabase instance
            exchange: Exchange client (CCXT)
            telegram_notifier: Telegram notifier for alerts
        """
        self.db = db
        self.exchange = exchange
        self.telegram = telegram_notifier
        self.client = None
        
        if settings.should_use_coingecko():
            self.client = CoinGeckoClient(
                api_key=settings.coingecko_api_key,
                timeout=30.0,
                max_retries=3,
                retry_delay=2.0
            )
            logger.info("✅ CoinGecko sync manager initialized")
        else:
            logger.info("⏭️  CoinGecko integration disabled")
    
    async def close(self):
        """Close CoinGecko client."""
        if self.client:
            await self.client.close()
    
    # ============================================
    # Main Synchronization
    # ============================================
    
    async def sync_coingecko_data(self) -> Dict[str, any]:
        """
        Main synchronization function.
        
        Performs weekly sync of Bybit symbols to CoinGecko IDs.
        Uses incremental approach - continues if interrupted.
        
        Returns:
            Sync result dict
        """
        if not self.client:
            logger.info("⏭️  CoinGecko sync skipped (disabled)")
            return {'success': False, 'reason': 'disabled'}
        
        try:
            logger.info("=" * 60)
            logger.info("🔄 Starting CoinGecko synchronization...")
            logger.info("=" * 60)
            
            current_week = get_current_sync_week()
            status = await self.db.get_sync_status()
            
            # Check if we need to sync
            last_week = status.get('last_full_sync_week')
            
            if last_week == current_week:
                logger.info(f"⏭️  Sync already completed for {current_week}")
                return {'success': True, 'reason': 'already_synced', 'week': current_week}
            
            # Update status - sync starting
            await self.db.update_sync_status({
                'sync_state': 'in_progress',
                'sync_started_at': int(datetime.now(timezone.utc).timestamp()),
                'total_symbols': 0,
                'processed_symbols': 0,
                'failed_symbols': 0
            })
            
            # Step 1: Fetch CoinGecko coins list
            logger.info("📥 Step 1: Fetching CoinGecko coins list...")
            coins_list = await self._fetch_coingecko_coins_list()
            
            if not coins_list:
                raise Exception("Failed to fetch CoinGecko coins list")
            
            # Step 2: Get Bybit symbols
            logger.info("📥 Step 2: Fetching Bybit symbols...")
            bybit_symbols = await self._get_bybit_symbols()
            
            logger.info(f"✅ Got {len(bybit_symbols)} Bybit symbols")
            
            # Update total count
            await self.db.update_sync_status({'total_symbols': len(bybit_symbols)})
            
            # Step 3: Map symbols
            logger.info("🔗 Step 3: Mapping Bybit symbols to CoinGecko IDs...")
            
            mapped_count = 0
            not_found_count = 0
            failed_count = 0
            
            for i, symbol_info in enumerate(bybit_symbols, 1):
                try:
                    symbol = symbol_info['symbol']
                    market = symbol_info['market']
                    
                    # Extract base currency (BTC from BTC/USDT)
                    base_currency = extract_base_currency(symbol)
                    
                    # Find CoinGecko ID
                    coingecko_id = find_coingecko_id(coins_list, base_currency)
                    
                    if coingecko_id:
                        status = 'found'
                        mapped_count += 1
                        logger.debug(f"✅ {symbol} → {coingecko_id}")
                    else:
                        status = 'not_found'
                        not_found_count += 1
                        logger.debug(f"❌ {symbol} → NOT FOUND")
                    
                    # Save mapping
                    await self.db.save_symbol_mapping(
                        bybit_symbol=symbol,
                        market=market,
                        coingecko_id=coingecko_id,
                        status=status,
                        sync_batch_id=current_week
                    )
                    
                    # Update progress
                    if i % 50 == 0:
                        await self.db.update_sync_status({'processed_symbols': i})
                        logger.info(f"⏳ Progress: {i}/{len(bybit_symbols)} symbols processed")
                
                except Exception as e:
                    logger.error(f"❌ Error mapping {symbol}: {e}")
                    failed_count += 1
            
            # Step 4: Complete sync
            current_time = int(datetime.now(timezone.utc).timestamp())
            
            await self.db.update_sync_status({
                'sync_state': 'completed',
                'sync_completed_at': current_time,
                'processed_symbols': len(bybit_symbols),
                'failed_symbols': failed_count,
                'last_full_sync_at': current_time,
                'last_full_sync_symbols': mapped_count,
                'last_full_sync_week': current_week,
                'next_sync_at': current_time + (7 * 86400)  # Next week
            })
            
            # Send Telegram notification
            message = (
                f"✅ <b>CoinGecko Sync Completed</b>\n\n"
                f"📅 Week: {current_week}\n"
                f"✅ Mapped: {mapped_count}\n"
                f"❌ Not Found: {not_found_count}\n"
                f"⚠️ Failed: {failed_count}\n"
                f"📊 Total: {len(bybit_symbols)}\n"
                f"🔄 Next sync: in 7 days"
            )
            
            await self.telegram.send_message(message)
            
            logger.info("=" * 60)
            logger.info("✅ CoinGecko synchronization completed!")
            logger.info(f"   Mapped: {mapped_count}")
            logger.info(f"   Not Found: {not_found_count}")
            logger.info(f"   Failed: {failed_count}")
            logger.info("=" * 60)
            
            return {
                'success': True,
                'week': current_week,
                'mapped': mapped_count,
                'not_found': not_found_count,
                'failed': failed_count
            }
        
        except RateLimitError as e:
            logger.error(f"❌ Rate limit exceeded: {e}")
            
            await self.db.update_sync_status({
                'sync_state': 'failed',
                'sync_error': str(e),
                'last_api_error': str(e),
                'last_api_error_at': int(datetime.now(timezone.utc).timestamp())
            })
            
            # Notify via Telegram
            retry_time = "1 hour" if e.limit_type == 'minute' else "next month"
            message = (
                f"⚠️ <b>CoinGecko Sync Failed</b>\n\n"
                f"❌ Rate limit exceeded: {e.limit_type}\n"
                f"⏰ Retry in: {retry_time}"
            )
            await self.telegram.send_message(message)
            
            return {'success': False, 'error': str(e)}
        
        except Exception as e:
            logger.error(f"❌ Sync error: {e}", exc_info=True)
            
            await self.db.update_sync_status({
                'sync_state': 'failed',
                'sync_error': str(e)
            })
            
            # Notify via Telegram
            message = (
                f"⚠️ <b>CoinGecko Sync Failed</b>\n\n"
                f"❌ Error: {str(e)[:200]}\n"
                f"🔄 Will retry in 1 hour"
            )
            await self.telegram.send_message(message)
            
            return {'success': False, 'error': str(e)}
    
    async def _fetch_coingecko_coins_list(self) -> List[Dict]:
        """Fetch CoinGecko coins list with API call tracking."""
        try:
            # Increment API calls counter
            await self.db.increment_api_calls()
            
            # Fetch coins
            coins = await self.client.fetch_coins_list()
            
            # Save to database
            await self.db.save_coingecko_coins(coins)
            
            logger.info(f"✅ Fetched {len(coins)} coins from CoinGecko")
            return coins
        
        except Exception as e:
            logger.error(f"❌ Error fetching CoinGecko coins: {e}")
            raise
    
    async def _get_bybit_symbols(self) -> List[Dict[str, str]]:
        """Get all Bybit symbols (spot + futures)."""
        try:
            symbols = []
            
            # Load spot markets
            if settings.parse_spot:
                await self.exchange.load_markets('spot')
                spot_symbols = list(self.exchange.markets['spot'].keys())
                symbols.extend([{'symbol': s, 'market': 'spot'} for s in spot_symbols])
                logger.info(f"✅ Got {len(spot_symbols)} spot symbols")
            
            # Load futures markets
            if settings.parse_futures:
                await self.exchange.load_markets('futures')
                futures_symbols = list(self.exchange.markets['futures'].keys())
                symbols.extend([{'symbol': s, 'market': 'futures'} for s in futures_symbols])
                logger.info(f"✅ Got {len(futures_symbols)} futures symbols")
            
            return symbols
        
        except Exception as e:
            logger.error(f"❌ Error getting Bybit symbols: {e}")
            raise
    
    # ============================================
    # Hourly Updates
    # ============================================
    
    async def update_top_symbols(self, limit: int = None) -> int:
        """
        Update market cap data for top symbols.
        
        Args:
            limit: Number of top symbols to update (default from settings)
        
        Returns:
            Number of symbols updated
        """
        if not self.client:
            return 0
        
        try:
            if limit is None:
                limit = settings.coingecko_top_symbols_hourly
            
            logger.info(f"🔄 Updating top {limit} symbols...")
            
            # Get top symbols by status='found'
            cursor = await self.db.db.execute("""
                SELECT DISTINCT sm.coingecko_id
                FROM symbol_mapping sm
                WHERE sm.status = 'found' AND sm.coingecko_id IS NOT NULL
                LIMIT ?
            """, (limit,))
            
            rows = await cursor.fetchall()
            coingecko_ids = [row[0] for row in rows]
            
            if not coingecko_ids:
                logger.info("⚠️ No symbols to update")
                return 0
            
            # Fetch market data in batches of 250
            updated_count = 0
            
            for i in range(0, len(coingecko_ids), 250):
                batch = coingecko_ids[i:i+250]
                
                try:
                    # Increment API calls
                    await self.db.increment_api_calls()
                    
                    # Fetch market data
                    market_data = await self.client.fetch_markets(ids=batch)
                    
                    # Save to cache
                    for coin_data in market_data:
                        await self.db.save_market_cap_data(
                            coingecko_id=coin_data['id'],
                            data=coin_data,
                            ttl=settings.coingecko_cache_ttl
                        )
                        updated_count += 1
                    
                    logger.info(f"✅ Updated {len(market_data)} coins (batch {i//250 + 1})")
                    
                    # Small delay between batches
                    if i + 250 < len(coingecko_ids):
                        await asyncio.sleep(2)
                
                except RateLimitError as e:
                    logger.warning(f"⚠️ Rate limit hit during update: {e}")
                    break
                
                except Exception as e:
                    logger.error(f"❌ Error updating batch: {e}")
            
            logger.info(f"✅ Updated {updated_count}/{len(coingecko_ids)} top symbols")
            return updated_count
        
        except Exception as e:
            logger.error(f"❌ Error in update_top_symbols: {e}", exc_info=True)
            return 0
    
    # ============================================
    # On-Demand Updates
    # ============================================
    
    async def get_market_cap_for_symbol(self, bybit_symbol: str) -> Optional[Dict]:
        """
        Get market cap data for a Bybit symbol.
        
        Uses cache if available, otherwise fetches from API.
        
        Args:
            bybit_symbol: Bybit symbol (e.g., "BTC/USDT")
        
        Returns:
            Market cap data or None
        """
        if not self.client:
            return None
        
        try:
            # Get symbol mapping
            mapping = await self.db.get_symbol_mapping(bybit_symbol)
            
            if not mapping or not mapping.get('coingecko_id'):
                logger.debug(f"⚠️ No CoinGecko mapping for {bybit_symbol}")
                return None
            
            coingecko_id = mapping['coingecko_id']
            
            # Check cache
            cached_data = await self.db.get_market_cap_data(coingecko_id)
            
            if cached_data:
                logger.debug(f"✅ Using cached data for {bybit_symbol}")
                return cached_data
            
            # Fetch from API
            logger.info(f"📥 Fetching fresh data for {bybit_symbol} ({coingecko_id})")
            
            try:
                # Increment API calls
                await self.db.increment_api_calls()
                
                # Fetch market data
                market_data = await self.client.fetch_markets(ids=[coingecko_id])
                
                if market_data:
                    coin_data = market_data[0]
                    
                    # Save to cache with longer TTL for rare symbols
                    await self.db.save_market_cap_data(
                        coingecko_id=coingecko_id,
                        data=coin_data,
                        ttl=settings.coingecko_cache_ttl_rare
                    )
                    
                    return await self.db.get_market_cap_data(coingecko_id)
            
            except RateLimitError as e:
                logger.warning(f"⚠️ Rate limit hit for {bybit_symbol}: {e}")
                return None
            
        except Exception as e:
            logger.error(f"❌ Error getting market cap for {bybit_symbol}: {e}")
            return None
    
    # ============================================
    # Scheduler
    # ============================================
    
    async def scheduler_loop(self):
        """Background task for periodic syncs."""
        logger.info("🔄 CoinGecko scheduler started")
        
        while True:
            try:
                # Check if we need weekly sync
                status = await self.db.get_sync_status()
                last_week = status.get('last_full_sync_week')
                current_week = get_current_sync_week()
                
                if is_new_sync_week(last_week):
                    logger.info(f"📅 New sync week detected: {current_week}")
                    await self.sync_coingecko_data()
                
                # Update top symbols hourly
                await self.update_top_symbols()
                
                # Sleep for 1 hour
                await asyncio.sleep(3600)
            
            except Exception as e:
                logger.error(f"❌ Scheduler error: {e}", exc_info=True)
                await asyncio.sleep(3600)
