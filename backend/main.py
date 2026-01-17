"""
FastAPI Main Application (WebSocket Version) - WITH STATUS ENDPOINT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Main entry point for WebSocket-based crypto screener.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .screener.engine import start_screener, get_engine

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
    
    This starts the WebSocket screener engine on startup.
    """
    logger.info("=" * 70)
    logger.info("🚀 STARTING CRYPTO SCREENER API (WEBSOCKET MODE)")
    logger.info("=" * 70)
    
    # Initialize database for API endpoints
    from .screener.database import Database
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
    description="Real-time cryptocurrency screening with WebSocket",
    version="2.0.0",
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
        "version": "2.0.0",
        "mode": "websocket"
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
        "version": "2.0.0",
        "mode": "WebSocket",
        "docs": "/docs",
        "health": "/health"
    }


# ============================================
# Status Endpoint (for frontend)
# ============================================

@app.get("/api/status")
async def get_status():
    """
    Get system status.
    
    Returns:
        System status information
    """
    engine = get_engine()
    
    return {
        "status": "running" if engine and engine.running else "stopped",
        "mode": "websocket",
        "version": "2.0.0",
        "running": engine.running if engine else False,
        "active_filters": 0,  # TODO: Get from database
        "last_check": None,  # TODO: Get from database
    }


# ============================================
# Import and Include API Routers
# ============================================

# Import API routers
from .api import filters, triggers, settings as settings_api, websocket, candles

# Include routers (routers already have their own prefixes!)
app.include_router(filters.router)
app.include_router(triggers.router)
app.include_router(settings_api.router)
app.include_router(websocket.router)
app.include_router(candles.router)  # <-- Добавьте эту строку


logger.info("✅ API application initialized")


# ============================================
# Main Entry Point (for development)
# ============================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.log_level.lower()
    )