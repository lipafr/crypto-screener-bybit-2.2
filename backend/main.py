"""
FastAPI Main Application - WITH CHARTS SUPPORT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Main entry point for crypto screener with charts functionality.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.screener.engine import start_screener, get_engine
from backend.screener import cache

# Setup logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


# ============================================
# Lifespan Context Manager
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown events.
    """
    logger.info("=" * 70)
    logger.info("🚀 STARTING CRYPTO SCREENER API")
    logger.info("=" * 70)
    
    # Initialize cache
    cache.init_cache()
    logger.info("✅ Cache initialized")
    
    # Initialize database for API endpoints
    from backend.screener.database import Database
    app.state.db = Database(settings.db_path)
    await app.state.db.connect()
    logger.info("✅ API database connection initialized")
    
    # Start screener engine in background
    import asyncio
    screener_task = asyncio.create_task(
        start_screener(
            db_path=settings.db_path,
            testnet=settings.testnet,
            check_delay_seconds=settings.check_delay_seconds
        )
    )
    
    # Store engine reference for API access
    app.state.engine = None
    app.state.notifier = None
    
    # Wait a bit for engine to initialize
    await asyncio.sleep(2)
    
    # Get engine and notifier references
    engine = get_engine()
    if engine:
        app.state.engine = engine
        app.state.notifier = engine.notifier
        logger.info("✅ Engine and notifier references stored in app.state")
    
    try:
        yield
    finally:
        logger.info("🛑 Shutting down...")
        
        # Cancel screener task
        screener_task.cancel()
        try:
            await screener_task
        except asyncio.CancelledError:
            pass
        
        # Close database
        if hasattr(app.state, 'db'):
            await app.state.db.close()
            logger.info("✅ API database connection closed")


# ============================================
# FastAPI Application
# ============================================

app = FastAPI(
    title="Crypto Screener API",
    description="Real-time cryptocurrency screening with charts",
    version="2.1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# Include Routers
# ============================================

# FIXED: Import settings API router with alias to avoid conflict
from backend.api import filters, triggers
from backend.api import settings as settings_api  # ← RENAMED!
from backend.api import charts  # NEW
from backend.api.websocket import router as websocket_router
from backend.api.websocket_charts import websocket_chart_endpoint, chart_manager  # NEW

# Existing routers
app.include_router(filters.router)
app.include_router(triggers.router)
app.include_router(settings_api.router)  # ← Using alias
app.include_router(websocket_router)

# NEW: Charts router
app.include_router(charts.router)

# NEW: Charts WebSocket endpoint
from fastapi import WebSocket

@app.websocket("/ws/charts")
async def websocket_charts(websocket: WebSocket):
    """WebSocket endpoint for real-time chart updates."""
    await websocket_chart_endpoint(websocket)


# ============================================
# Health Check Endpoints
# ============================================

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        Status dict
    """
    return {
        "status": "healthy",
        "version": "2.1.0",
        "features": ["filters", "triggers", "charts", "websocket"]
    }


@app.get("/")
async def root():
    """
    Root endpoint.
    
    Returns:
        Welcome message with links
    """
    return {
        "name": "Crypto Screener API",
        "version": "2.1.0",
        "features": ["filters", "triggers", "charts", "websocket"],
        "docs": "/docs",
        "health": "/health",
        "charts": "/charts.html"
    }


# ============================================
# Status Endpoint
# ============================================

@app.get("/api/status")
async def get_status():
    """
    Get system status.
    
    Returns:
        System status information
    """
    import time
    
    status = {
        "api_status": "online",
        "engine_status": "unknown",
        "cache_stats": cache.get_cache_stats(),
        "timestamp": int(time.time())
    }
    
    # Check engine status
    engine = get_engine()
    if engine:
        status["engine_status"] = "running"
        if hasattr(engine, 'last_parse_time'):
            time_since_parse = int(time.time()) - engine.last_parse_time
            status["seconds_since_last_parse"] = time_since_parse
            
            # Считаем данные устаревшими если не обновлялись > 5 минут
            if time_since_parse > 300:
                status["data_status"] = "stale"
            else:
                status["data_status"] = "live"
    else:
        status["engine_status"] = "not_running"
        status["data_status"] = "offline"
    
    return status


# ============================================
# Store chart_manager reference
# ============================================

app.state.chart_manager = chart_manager