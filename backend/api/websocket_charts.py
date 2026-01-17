"""
WebSocket endpoint для real-time обновлений графиков.
"""

import logging
import json
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
import asyncio

logger = logging.getLogger(__name__)


class ChartConnectionManager:
    """Менеджер WebSocket соединений для графиков."""
    
    def __init__(self):
        # {websocket: set((symbol, market))}
        self.active_connections: Dict[WebSocket, Set[tuple]] = {}
    
    async def connect(self, websocket: WebSocket):
        """Принять новое соединение."""
        await websocket.accept()
        self.active_connections[websocket] = set()
        logger.info(f"📊 Chart WebSocket connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """Отключить соединение."""
        if websocket in self.active_connections:
            subscriptions = self.active_connections[websocket]
            del self.active_connections[websocket]
            logger.info(
                f"📊 Chart WebSocket disconnected (was subscribed to {len(subscriptions)} symbols). "
                f"Total: {len(self.active_connections)}"
            )
    
    def subscribe(self, websocket: WebSocket, symbol: str, market: str):
        """Подписать соединение на символ."""
        if websocket in self.active_connections:
            self.active_connections[websocket].add((symbol, market))
            logger.debug(f"📊 Subscribed to {symbol} ({market})")
    
    def unsubscribe(self, websocket: WebSocket, symbol: str, market: str):
        """Отписать соединение от символа."""
        if websocket in self.active_connections:
            self.active_connections[websocket].discard((symbol, market))
            logger.debug(f"📊 Unsubscribed from {symbol} ({market})")
    
    async def broadcast_candle_update(self, symbol: str, market: str, candle: dict):
        """
        Отправить обновление свечи всем подписанным соединениям.
        
        Args:
            symbol: Символ
            market: Рынок
            candle: Данные свечи {timestamp, open, high, low, close, volume}
        """
        message = {
            "type": "candle_update",
            "symbol": symbol,
            "market": market,
            "candle": {
                "time": candle['timestamp'],
                "open": candle['open'],
                "high": candle['high'],
                "low": candle['low'],
                "close": candle['close'],
                "volume": candle['volume']
            }
        }
        
        message_json = json.dumps(message)
        disconnected = []
        
        for websocket, subscriptions in self.active_connections.items():
            if (symbol, market) in subscriptions:
                try:
                    await websocket.send_text(message_json)
                except Exception as e:
                    logger.error(f"❌ Error sending candle update: {e}")
                    disconnected.append(websocket)
        
        # Удаляем отключенные соединения
        for ws in disconnected:
            self.disconnect(ws)
    
    async def broadcast_trigger_mark(self, symbol: str, market: str, trigger_data: dict):
        """
        Отправить метку срабатывания фильтра.
        
        Args:
            symbol: Символ
            market: Рынок
            trigger_data: {timestamp, filter_name, filter_type}
        """
        message = {
            "type": "trigger_mark",
            "symbol": symbol,
            "market": market,
            "trigger": {
                "time": trigger_data['timestamp'],
                "filter_name": trigger_data['filter_name'],
                "filter_type": trigger_data['filter_type']
            }
        }
        
        message_json = json.dumps(message)
        disconnected = []
        
        for websocket, subscriptions in self.active_connections.items():
            if (symbol, market) in subscriptions:
                try:
                    await websocket.send_text(message_json)
                except Exception as e:
                    logger.error(f"❌ Error sending trigger mark: {e}")
                    disconnected.append(websocket)
        
        # Удаляем отключенные соединения
        for ws in disconnected:
            self.disconnect(ws)
    
    async def send_status(self, status: str):
        """
        Отправить статус всем соединениям.
        
        Args:
            status: 'live', 'reconnecting', 'offline', 'stale'
        """
        message = {
            "type": "status",
            "status": status
        }
        
        message_json = json.dumps(message)
        disconnected = []
        
        for websocket in self.active_connections.keys():
            try:
                await websocket.send_text(message_json)
            except Exception as e:
                logger.error(f"❌ Error sending status: {e}")
                disconnected.append(websocket)
        
        # Удаляем отключенные соединения
        for ws in disconnected:
            self.disconnect(ws)


# Глобальный менеджер для графиков
chart_manager = ChartConnectionManager()


async def websocket_chart_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint для real-time обновлений графиков.
    
    Протокол:
    
    От клиента:
    {
        "action": "subscribe",
        "symbol": "BTC/USDT",
        "market": "spot"
    }
    
    {
        "action": "unsubscribe",
        "symbol": "BTC/USDT",
        "market": "spot"
    }
    
    От сервера:
    {
        "type": "candle_update",
        "symbol": "BTC/USDT",
        "market": "spot",
        "candle": {
            "time": 1705500660,
            "open": 42150,
            "high": 42200,
            "low": 42100,
            "close": 42180,
            "volume": 800000
        }
    }
    
    {
        "type": "trigger_mark",
        "symbol": "BTC/USDT",
        "market": "spot",
        "trigger": {
            "time": 1705500300,
            "filter_name": "Быстрый рост",
            "filter_type": "price_change"
        }
    }
    
    {
        "type": "status",
        "status": "live|reconnecting|offline|stale"
    }
    """
    await chart_manager.connect(websocket)
    
    try:
        while True:
            # Ожидаем сообщения от клиента
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                action = message.get('action')
                symbol = message.get('symbol')
                market = message.get('market')
                
                if action == 'subscribe' and symbol and market:
                    chart_manager.subscribe(websocket, symbol, market)
                    await websocket.send_text(json.dumps({
                        "type": "subscribed",
                        "symbol": symbol,
                        "market": market
                    }))
                
                elif action == 'unsubscribe' and symbol and market:
                    chart_manager.unsubscribe(websocket, symbol, market)
                    await websocket.send_text(json.dumps({
                        "type": "unsubscribed",
                        "symbol": symbol,
                        "market": market
                    }))
                
                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Invalid action or missing parameters"
                    }))
            
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON"
                }))
    
    except WebSocketDisconnect:
        chart_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"❌ Chart WebSocket error: {e}", exc_info=True)
        chart_manager.disconnect(websocket)
