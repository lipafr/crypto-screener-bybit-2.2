# Добавьте в backend/api/candles.py (или создайте новый файл)

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/api/candles", tags=["candles"])

@router.get("/export/{symbol}/{market}")
async def export_candles(symbol: str, market: str, limit: int = 100):
    """Export candles as CSV"""
    from ..screener.database import get_database
    from datetime import datetime
    
    db = get_database()
    
    cursor = await db.execute("""
        SELECT timestamp, open, high, low, close, volume 
        FROM candles 
        WHERE symbol = ? AND market = ?
        ORDER BY timestamp DESC 
        LIMIT ?
    """, (symbol, market, limit))
    
    rows = await cursor.fetchall()
    
    lines = ["Timestamp,Open,High,Low,Close,Volume"]
    for row in rows:
        dt = datetime.fromtimestamp(row['timestamp'])
        lines.append(f"{dt},{row['open']},{row['high']},{row['low']},{row['close']},{row['volume']}")
    
    return PlainTextResponse("\n".join(lines))