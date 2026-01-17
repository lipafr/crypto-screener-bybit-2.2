# backend/api/candles.py

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from datetime import datetime

router = APIRouter(prefix="/api/candles", tags=["candles"])

@router.get("/export/{symbol}/{market}")
async def export_candles(symbol: str, market: str, limit: int = 100):
    """
    Export candles as CSV
    
    Args:
        symbol: Trading symbol (e.g., BTC/USDT:USDT)
        market: Market type (spot or futures)
        limit: Number of candles to export (default: 100)
    
    Returns:
        CSV file with OHLCV data
    """
    try:
        # Import Database class
        from ..screener.database import Database
        from ..config import settings
        
        # Create database instance
        db = Database(settings.db_path)
        await db.connect()
        
        # Query candles
        cursor = await db.execute("""
            SELECT timestamp, open, high, low, close, volume 
            FROM candles 
            WHERE symbol = ? AND market = ?
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (symbol, market, limit))
        
        rows = await cursor.fetchall()
        
        # Close database connection
        await db.close()
        
        # Check if we have data
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"No candle data found for {symbol} on {market} market"
            )
        
        # Format as CSV
        lines = ["Timestamp,Open,High,Low,Close,Volume"]
        for row in rows:
            dt = datetime.fromtimestamp(row['timestamp'])
            lines.append(f"{dt},{row['open']},{row['high']},{row['low']},{row['close']},{row['volume']}")
        
        return PlainTextResponse(
            content="\n".join(lines),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={symbol.replace('/', '_')}_{market}_candles.csv"
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))