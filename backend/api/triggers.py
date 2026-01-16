"""
Triggers API
~~~~~~~~~~~~

REST API endpoints for trigger history and statistics.

Endpoints:
- GET /api/triggers - List triggers with filters
- GET /api/triggers/stats - Get trigger statistics
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends

from ..models.trigger import TriggerResponse, TriggerListResponse, TriggerStats, TriggerData
from ..screener.database import Database
from ..screener.time_utils import (
    get_day_start_timestamp,
    get_week_start_timestamp,
    get_month_start_timestamp
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/triggers", tags=["triggers"])


# ============================================
# Dependency: Get Database
# ============================================

async def get_db() -> Database:
    """Get database instance (dependency injection)."""
    from ..main import app
    return app.state.db


# ============================================
# Endpoints
# ============================================

@router.get("", response_model=TriggerListResponse)
async def list_triggers(
    filter_id: Optional[int] = Query(None, description="Filter by filter ID"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    market: Optional[str] = Query(None, description="Filter by market"),
    from_date: Optional[int] = Query(None, description="From timestamp (Unix seconds)"),
    to_date: Optional[int] = Query(None, description="To timestamp (Unix seconds)"),
    limit: int = Query(100, ge=1, le=1000, description="Results limit"),
    offset: int = Query(0, ge=0, description="Results offset"),
    db: Database = Depends(get_db)
):
    """
    Get list of trigger events.
    
    Query parameters:
        filter_id: Filter by specific filter
        symbol: Filter by trading pair
        market: Filter by market (spot/futures)
        from_date: Start date (Unix timestamp)
        to_date: End date (Unix timestamp)
        limit: Maximum results (1-1000)
        offset: Skip first N results
    
    Returns:
        Paginated list of triggers
    """
    try:
        # Build query
        query = """
            SELECT id, filter_id, filter_name, symbol, market,
                   triggered_at, data, notified
            FROM filter_triggers
            WHERE 1=1
        """
        params = []
        
        if filter_id:
            query += " AND filter_id = ?"
            params.append(filter_id)
        
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        
        if market:
            query += " AND market = ?"
            params.append(market)
        
        if from_date:
            query += " AND triggered_at >= ?"
            params.append(from_date)
        
        if to_date:
            query += " AND triggered_at <= ?"
            params.append(to_date)
        
        # Get total count
        count_query = query.replace(
            "SELECT id, filter_id, filter_name, symbol, market, triggered_at, data, notified",
            "SELECT COUNT(*) as count"
        )
        
        cursor = await db.db.execute(count_query, params)
        row = await cursor.fetchone()
        total = row[0] if row else 0
        
        # Get paginated results
        query += " ORDER BY triggered_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor = await db.db.execute(query, params)
        rows = await cursor.fetchall()
        
        # Convert to response models
        items = []
        for row in rows:
            import json
            
            trigger_data = TriggerData(**json.loads(row['data']))
            
            items.append(TriggerResponse(
                id=row['id'],
                filter_id=row['filter_id'],
                filter_name=row['filter_name'],
                symbol=row['symbol'],
                market=row['market'],
                triggered_at=row['triggered_at'],
                data=trigger_data,
                notified=bool(row['notified'])
            ))
        
        logger.info(
            f"📋 Listed {len(items)} triggers (total: {total})"
        )
        
        return TriggerListResponse(
            total=total,
            items=items
        )
        
    except Exception as e:
        logger.error(f"❌ Error listing triggers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=TriggerStats)
async def get_trigger_stats(
    db: Database = Depends(get_db)
):
    """
    Get trigger statistics.
    
    Returns:
        Statistics including:
        - Total triggers today/week/month
        - Triggers by filter
        - Triggers by symbol
    """
    try:
        # Get time boundaries
        day_start = get_day_start_timestamp()
        week_start = get_week_start_timestamp()
        month_start = get_month_start_timestamp()
        
        # Count today
        cursor = await db.db.execute("""
            SELECT COUNT(*) as count
            FROM filter_triggers
            WHERE triggered_at >= ?
        """, (day_start,))
        row = await cursor.fetchone()
        total_today = row[0] if row else 0
        
        # Count this week
        cursor = await db.db.execute("""
            SELECT COUNT(*) as count
            FROM filter_triggers
            WHERE triggered_at >= ?
        """, (week_start,))
        row = await cursor.fetchone()
        total_week = row[0] if row else 0
        
        # Count this month
        cursor = await db.db.execute("""
            SELECT COUNT(*) as count
            FROM filter_triggers
            WHERE triggered_at >= ?
        """, (month_start,))
        row = await cursor.fetchone()
        total_month = row[0] if row else 0
        
        # Group by filter
        cursor = await db.db.execute("""
            SELECT filter_id, filter_name, COUNT(*) as count
            FROM filter_triggers
            WHERE triggered_at >= ?
            GROUP BY filter_id, filter_name
            ORDER BY count DESC
            LIMIT 10
        """, (month_start,))
        rows = await cursor.fetchall()
        
        by_filter = [
            {
                'filter_id': row['filter_id'],
                'filter_name': row['filter_name'],
                'count': row['count']
            }
            for row in rows
        ]
        
        # Group by symbol
        cursor = await db.db.execute("""
            SELECT symbol, COUNT(*) as count
            FROM filter_triggers
            WHERE triggered_at >= ?
            GROUP BY symbol
            ORDER BY count DESC
            LIMIT 10
        """, (month_start,))
        rows = await cursor.fetchall()
        
        by_symbol = [
            {
                'symbol': row['symbol'],
                'count': row['count']
            }
            for row in rows
        ]
        
        logger.info(
            f"📊 Trigger stats: today={total_today}, "
            f"week={total_week}, month={total_month}"
        )
        
        return TriggerStats(
            total_today=total_today,
            total_week=total_week,
            total_month=total_month,
            by_filter=by_filter,
            by_symbol=by_symbol
        )
        
    except Exception as e:
        logger.error(f"❌ Error getting trigger stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))