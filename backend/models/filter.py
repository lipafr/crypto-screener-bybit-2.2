"""
Filter Models
~~~~~~~~~~~~~

Pydantic models for filter configuration and validation.

Two filter types:
    1. price_change: Monitors price changes over time
    2. volume_spike: Detects abnormal volume spikes
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime


# ============================================
# Configuration Models for Filter Types
# ============================================

class PriceChangeConfig(BaseModel):
    """
    Configuration for price_change filter type.
    
    Monitors price changes over a specified interval.
    """
    
    market: Literal["spot", "futures"] = Field(
        description="Market type"
    )
    
    interval_minutes: int = Field(
        description="Time interval to check (5, 10, 15, 30, 60, 120, 240)"
    )
    
    min_price_change_percent: float = Field(
        ge=0,
        description="Minimum price change percentage to trigger"
    )
    
    direction: Literal["up", "down", "any"] = Field(
        default="any",
        description="Price movement direction"
    )
    
    min_volume_period: float = Field(
        ge=0,
        description="Minimum volume during the period (USD)"
    )
    
    min_volume_24h: float = Field(
        ge=0,
        description="Minimum 24h volume (USD)"
    )
    
    max_volume_24h: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum 24h volume (USD), None = no limit"
    )
    
    exclude_coins: list[str] = Field(
        default_factory=list,
        description="List of symbols to exclude (e.g. ['BTCUSDT', 'ETHUSDT'])"
    )
    
    comment: str = Field(
        default="",
        description="Optional comment"
    )
    
    @field_validator("interval_minutes")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        """Validate interval is one of allowed values."""
        allowed = [5, 10, 15, 30, 60, 120, 240]
        if v not in allowed:
            raise ValueError(f"interval_minutes must be one of {allowed}")
        return v
    
    @model_validator(mode='after')
    def validate_volume_range(self):
        """Validate max_volume_24h is greater than min_volume_24h."""
        if self.max_volume_24h is not None:
            if self.max_volume_24h <= self.min_volume_24h:
                raise ValueError("max_volume_24h must be greater than min_volume_24h")
        return self
    
    class Config:
        json_schema_extra = {
            "example": {
                "market": "spot",
                "interval_minutes": 15,
                "min_price_change_percent": 5.0,
                "direction": "up",
                "min_volume_period": 10000,
                "min_volume_24h": 100000,
                "max_volume_24h": None,
                "exclude_coins": ["BTCUSDT", "ETHUSDT"],
                "comment": "Pump alerts for altcoins"
            }
        }


class VolumeSpikeConfig(BaseModel):
    """
    Configuration for volume_spike filter type.
    
    Detects abnormal volume increases compared to historical average.
    """
    
    market: Literal["spot", "futures"] = Field(
        description="Market type"
    )
    
    short_period_minutes: int = Field(
        description="Short period for current volume (5, 10, 15, 30)"
    )
    
    base_period_minutes: int = Field(
        description="Base period for average calculation (60, 120, 240)"
    )
    
    spike_coefficient: float = Field(
        ge=1.0,
        description="Minimum spike coefficient (e.g. 5.0 = 5x volume)"
    )
    
    price_direction: Literal["up", "down", "all"] = Field(
        default="all",
        description="Price movement direction filter"
    )
    
    min_price_change_percent: float = Field(
        default=0,
        ge=0,
        description="Minimum price change % during spike (0 = disabled)"
    )
    
    min_volume_24h: float = Field(
        ge=0,
        description="Minimum 24h volume (USD)"
    )
    
    max_volume_24h: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum 24h volume (USD), None = no limit"
    )
    
    exclude_coins: list[str] = Field(
        default_factory=list,
        description="List of symbols to exclude"
    )
    
    comment: str = Field(
        default="",
        description="Optional comment"
    )
    
    @field_validator("short_period_minutes")
    @classmethod
    def validate_short_period(cls, v: int) -> int:
        """Validate short period is one of allowed values."""
        allowed = [5, 10, 15, 30]
        if v not in allowed:
            raise ValueError(f"short_period_minutes must be one of {allowed}")
        return v
    
    @field_validator("base_period_minutes")
    @classmethod
    def validate_base_period(cls, v: int) -> int:
        """Validate base period is one of allowed values."""
        allowed = [60, 120, 240]
        if v not in allowed:
            raise ValueError(f"base_period_minutes must be one of {allowed}")
        return v
    
    @model_validator(mode='after')
    def validate_periods(self):
        """Validate base_period > short_period."""
        if self.base_period_minutes <= self.short_period_minutes:
            raise ValueError("base_period_minutes must be greater than short_period_minutes")
        return self
    
    @model_validator(mode='after')
    def validate_volume_range(self):
        """Validate max_volume_24h is greater than min_volume_24h."""
        if self.max_volume_24h is not None:
            if self.max_volume_24h <= self.min_volume_24h:
                raise ValueError("max_volume_24h must be greater than min_volume_24h")
        return self
    
    class Config:
        json_schema_extra = {
            "example": {
                "market": "futures",
                "short_period_minutes": 10,
                "base_period_minutes": 120,
                "spike_coefficient": 5.0,
                "price_direction": "all",
                "min_price_change_percent": 2.0,
                "min_volume_24h": 1000000,
                "max_volume_24h": None,
                "exclude_coins": ["BTCUSDT"],
                "comment": "High volume breakouts"
            }
        }


# ============================================
# Filter CRUD Models
# ============================================

class FilterBase(BaseModel):
    """Base filter model with common fields."""
    
    name: str = Field(
        min_length=1,
        max_length=100,
        description="Filter name"
    )
    
    type: Literal["price_change", "volume_spike"] = Field(
        description="Filter type"
    )
    
    enabled: bool = Field(
        default=True,
        description="Whether filter is active"
    )


class FilterCreate(FilterBase):
    """Filter creation request model."""
    
    config: PriceChangeConfig | VolumeSpikeConfig = Field(
        description="Filter configuration (type-specific)"
    )
    
    @model_validator(mode='after')
    def validate_config_type(self):
        """Validate config matches filter type."""
        if self.type == "price_change" and not isinstance(self.config, PriceChangeConfig):
            raise ValueError("config must be PriceChangeConfig for price_change filter")
        if self.type == "volume_spike" and not isinstance(self.config, VolumeSpikeConfig):
            raise ValueError("config must be VolumeSpikeConfig for volume_spike filter")
        return self
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "5% Pump Detector",
                "type": "price_change",
                "enabled": True,
                "config": {
                    "market": "spot",
                    "interval_minutes": 15,
                    "min_price_change_percent": 5.0,
                    "direction": "up",
                    "min_volume_period": 10000,
                    "min_volume_24h": 100000,
                    "exclude_coins": []
                }
            }
        }


class FilterUpdate(BaseModel):
    """Filter update request model (all fields optional)."""
    
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Filter name"
    )
    
    enabled: Optional[bool] = Field(
        None,
        description="Whether filter is active"
    )
    
    config: Optional[PriceChangeConfig | VolumeSpikeConfig] = Field(
        None,
        description="Filter configuration"
    )


class FilterResponse(FilterBase):
    """Filter response model with additional metadata."""
    
    id: int = Field(description="Filter ID")
    
    config: dict = Field(description="Filter configuration as dict")
    
    created_at: int = Field(description="Creation timestamp (Unix seconds)")
    
    updated_at: Optional[int] = Field(
        None,
        description="Last update timestamp (Unix seconds)"
    )
    
    last_trigger: Optional[int] = Field(
        None,
        description="Last trigger timestamp (Unix seconds)"
    )
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "name": "5% Pump Detector",
                "type": "price_change",
                "enabled": True,
                "config": {
                    "market": "spot",
                    "interval_minutes": 15,
                    "min_price_change_percent": 5.0,
                    "direction": "up",
                    "min_volume_period": 10000,
                    "min_volume_24h": 100000
                },
                "created_at": 1704801234,
                "updated_at": None,
                "last_trigger": 1704805000
            }
        }


# ============================================
# Helper Functions
# ============================================

def parse_filter_config(filter_type: str, config_dict: dict) -> PriceChangeConfig | VolumeSpikeConfig:
    """
    Parse filter config from dict to appropriate Pydantic model.
    
    Args:
        filter_type: "price_change" or "volume_spike"
        config_dict: Configuration dictionary
    
    Returns:
        Parsed config model
    
    Raises:
        ValueError: If filter_type is invalid
    
    Examples:
        >>> config = parse_filter_config("price_change", {...})
        >>> isinstance(config, PriceChangeConfig)
        True
    """
    if filter_type == "price_change":
        return PriceChangeConfig(**config_dict)
    elif filter_type == "volume_spike":
        return VolumeSpikeConfig(**config_dict)
    else:
        raise ValueError(f"Invalid filter type: {filter_type}")
