"""
Settings Models
~~~~~~~~~~~~~~~

Pydantic models for system settings and configuration.
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    """System settings response model."""
    
    check_interval_seconds: int = Field(
        description="How often to check filters (seconds)"
    )
    
    cooldown_minutes: int = Field(
        description="Cooldown between notifications (minutes)"
    )
    
    telegram_configured: bool = Field(
        description="Whether Telegram is properly configured"
    )
    
    parse_spot: bool = Field(
        default=True,
        description="Parse spot market"
    )
    
    parse_futures: bool = Field(
        default=True,
        description="Parse futures market"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "check_interval_seconds": 300,
                "cooldown_minutes": 15,
                "telegram_configured": True,
                "parse_spot": True,
                "parse_futures": True
            }
        }


class SettingsUpdate(BaseModel):
    """Settings update request model."""
    
    check_interval_seconds: Optional[int] = Field(
        None,
        ge=60,
        le=3600,
        description="How often to check filters (60-3600 seconds)"
    )
    
    cooldown_minutes: Optional[int] = Field(
        None,
        ge=1,
        le=1440,
        description="Cooldown between notifications (1-1440 minutes)"
    )
    
    parse_spot: Optional[bool] = Field(
        None,
        description="Parse spot market"
    )
    
    parse_futures: Optional[bool] = Field(
        None,
        description="Parse futures market"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "check_interval_seconds": 600,
                "cooldown_minutes": 30
            }
        }
