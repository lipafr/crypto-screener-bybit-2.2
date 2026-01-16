"""
FastAPI Main Application (WebSocket Version)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Main entry point for WebSocket-based crypto screener.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .screener.engine import start_screener

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
    
    # Start screener engine in background
    import asyncio
    screener_task = asyncio.create_task(
        start_screener(
            db_path=settings.db_path,
            testnet=settings.testnet,
            check_delay_seconds=settings.check_delay_seconds
        )
    )
    
    try:
        yield
    finally:
        logger.info("🛑 Shutting down...")
        screener_task.cancel()
        try:
            await screener_task
        except asyncio.CancelledError:
            pass


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
# Import and Include API Routers
# ============================================

# Import API routers
from .api import filters, triggers, settings as settings_api, websocket

# Include routers
app.include_router(filters.router, prefix="/api", tags=["filters"])
app.include_router(triggers.router, prefix="/api", tags=["triggers"])
app.include_router(settings_api.router, prefix="/api", tags=["settings"])
app.include_router(websocket.router, prefix="/ws", tags=["websocket"])


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