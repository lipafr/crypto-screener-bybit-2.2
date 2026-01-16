"""
Trigger Models
~~~~~~~~~~~~~~

Pydantic models for filter trigger events and history.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class TriggerData(BaseModel):
    """
    Trigger event data (details of what triggered the filter).
    
    Contains specific information about the trigger event,
    such as price change, volume, etc.
    """
    
    price_change_percent: Optional[float] = Field(
        None,
        description="Price change percentage"
    )
    
    price_from: Optional[float] = Field(
        None,
        description="Starting price"
    )
    
    price_to: Optional[float] = Field(
        None,
        description="Ending price"
    )
    
    volume_period: Optional[float] = Field(
        None,
        description="Volume during the period (USD)"
    )
    
    volume_24h: Optional[float] = Field(
        None,
        description="24h volume (USD)"
    )
    
    spike_coefficient: Optional[float] = Field(
        None,
        description="Volume spike coefficient (for volume_spike filters)"
    )
    
    average_volume: Optional[float] = Field(
        None,
        description="Average volume (for volume_spike filters)"
    )
    
    url: Optional[str] = Field(
        None,
        description="Link to exchange trading page"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "price_change_percent": 7.3,
                "price_from": 142.50,
                "price_to": 152.90,
                "volume_period": 245000,
                "volume_24h": 1200000,
                "url": "https://www.bybit.com/trade/spot/SOL/USDT"
            }
        }


class TriggerResponse(BaseModel):
    """Trigger event response model."""
    
    id: int = Field(description="Trigger ID")
    
    filter_id: int = Field(description="Filter ID that triggered")
    
    filter_name: str = Field(description="Filter name at trigger time")
    
    symbol: str = Field(description="Trading pair symbol")
    
    market: str = Field(description="Market type (spot/futures)")
    
    triggered_at: int = Field(description="Trigger timestamp (Unix seconds)")
    
    data: TriggerData = Field(description="Trigger event details")
    
    notified: bool = Field(
        default=False,
        description="Whether Telegram notification was sent"
    )
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 123,
                "filter_id": 1,
                "filter_name": "5% Pump Detector",
                "symbol": "SOL/USDT",
                "market": "spot",
                "triggered_at": 1704805000,
                "data": {
                    "price_change_percent": 7.3,
                    "price_from": 142.50,
                    "price_to": 152.90,
                    "volume_period": 245000,
                    "volume_24h": 1200000,
                    "url": "https://www.bybit.com/trade/spot/SOL/USDT"
                },
                "notified": True
            }
        }


class TriggerListResponse(BaseModel):
    """Paginated list of triggers."""
    
    total: int = Field(description="Total number of triggers")
    
    items: list[TriggerResponse] = Field(description="List of trigger events")
    
    class Config:
        json_schema_extra = {
            "example": {
                "total": 1250,
                "items": [
                    {
                        "id": 123,
                        "filter_id": 1,
                        "filter_name": "5% Pump Detector",
                        "symbol": "SOL/USDT",
                        "market": "spot",
                        "triggered_at": 1704805000,
                        "data": {
                            "price_change_percent": 7.3,
                            "price_from": 142.50,
                            "price_to": 152.90,
                            "volume_period": 245000,
                            "volume_24h": 1200000
                        },
                        "notified": True
                    }
                ]
            }
        }


class TriggerStats(BaseModel):
    """Trigger statistics."""
    
    total_today: int = Field(description="Triggers today")
    
    total_week: int = Field(description="Triggers this week")
    
    total_month: int = Field(description="Triggers this month")
    
    by_filter: list[dict[str, Any]] = Field(
        description="Triggers grouped by filter"
    )
    
    by_symbol: list[dict[str, Any]] = Field(
        description="Triggers grouped by symbol"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "total_today": 45,
                "total_week": 320,
                "total_month": 1250,
                "by_filter": [
                    {
                        "filter_id": 1,
                        "filter_name": "5% Pump",
                        "count": 25
                    }
                ],
                "by_symbol": [
                    {
                        "symbol": "SOL/USDT",
                        "count": 12
                    }
                ]
            }
        }


class WebSocketTriggerMessage(BaseModel):
    """WebSocket trigger notification message."""
    
    type: str = Field(
        default="trigger",
        description="Message type"
    )
    
    filter_id: int = Field(description="Filter ID")
    
    filter_name: str = Field(description="Filter name")
    
    symbol: str = Field(description="Trading pair")
    
    market: str = Field(description="Market type")
    
    data: TriggerData = Field(description="Trigger details")
    
    timestamp: int = Field(description="Trigger timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "trigger",
                "filter_id": 1,
                "filter_name": "5% Pump Detector",
                "symbol": "SOL/USDT",
                "market": "spot",
                "data": {
                    "price_change_percent": 7.3,
                    "price_from": 142.50,
                    "price_to": 152.90,
                    "volume_period": 245000,
                    "volume_24h": 1200000
                },
                "timestamp": 1704805000
            }
        }
