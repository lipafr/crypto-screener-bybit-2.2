"""
WebSocket API
~~~~~~~~~~~~~

WebSocket endpoint for real-time trigger notifications.

Clients can connect to /ws/triggers to receive live updates
when filters are triggered.
"""

import logging
import asyncio
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# ============================================
# Connection Manager
# ============================================

class ConnectionManager:
    """
    Manages WebSocket connections.
    
    Handles:
    - Adding/removing connections
    - Broadcasting messages to all clients
    """
    
    def __init__(self):
        """Initialize connection manager."""
        self.active_connections: Set[WebSocket] = set()
        logger.info("WebSocket connection manager initialized")
    
    async def connect(self, websocket: WebSocket):
        """
        Accept new WebSocket connection.
        
        Args:
            websocket: WebSocket connection
        """
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(
            f"✅ WebSocket connected. "
            f"Total connections: {len(self.active_connections)}"
        )
    
    def disconnect(self, websocket: WebSocket):
        """
        Remove WebSocket connection.
        
        Args:
            websocket: WebSocket connection
        """
        self.active_connections.discard(websocket)
        logger.info(
            f"❌ WebSocket disconnected. "
            f"Total connections: {len(self.active_connections)}"
        )
    
    async def broadcast(self, message: dict):
        """
        Send message to all connected clients.
        
        Args:
            message: Message dict (will be converted to JSON)
        """
        if not self.active_connections:
            logger.debug("No active WebSocket connections to broadcast to")
            return
        
        # Send to all connections
        disconnected = set()
        
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Error sending to WebSocket: {e}")
                disconnected.add(connection)
        
        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect(connection)
        
        logger.debug(
            f"📡 Broadcast to {len(self.active_connections)} clients"
        )


# Global connection manager instance
manager = ConnectionManager()


# ============================================
# Endpoints
# ============================================

@router.websocket("/ws/triggers")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time trigger notifications.
    
    Clients connect here and receive JSON messages when filters trigger.
    
    Message format:
        {
            "type": "trigger",
            "filter_id": 1,
            "filter_name": "5% Pump",
            "symbol": "BTC/USDT",
            "market": "spot",
            "data": {...},
            "timestamp": 1234567890
        }
    
    Usage:
        const ws = new WebSocket('ws://localhost:8000/ws/triggers');
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log('Trigger:', data);
        };
    """
    await manager.connect(websocket)
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            # Wait for any message from client (ping/pong)
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0  # 60 second timeout
                )
                
                # Echo back (for ping/pong)
                if data == "ping":
                    await websocket.send_text("pong")
                
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket client disconnected normally")
    
    except Exception as e:
        manager.disconnect(websocket)
        logger.error(f"WebSocket error: {e}", exc_info=True)


# ============================================
# Helper Functions
# ============================================

async def broadcast_trigger(trigger_message: dict):
    """
    Broadcast trigger event to all WebSocket clients.
    
    This function is called by the screener engine when a filter triggers.
    
    Args:
        trigger_message: Trigger message dict
    
    Examples:
        >>> await broadcast_trigger({
        ...     "type": "trigger",
        ...     "filter_id": 1,
        ...     "symbol": "BTC/USDT",
        ...     ...
        ... })
    """
    await manager.broadcast(trigger_message)


def get_connection_count() -> int:
    """
    Get number of active WebSocket connections.
    
    Returns:
        Number of connected clients
    """
    return len(manager.active_connections)
