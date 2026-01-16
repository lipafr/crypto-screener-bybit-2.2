"""
Configuration Module
~~~~~~~~~~~~~~~~~~~

Pydantic Settings for application configuration.
Uses environment variables from .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # ============================================
    # Telegram Settings
    # ============================================
    telegram_bot_token: str = Field(
        description="Telegram bot token from @BotFather"
    )
    telegram_chat_id: str = Field(
        description="Telegram chat ID to send notifications"
    )
    
    # ============================================
    # Screener Settings
    # ============================================
    check_interval_seconds: int = Field(
        default=300,
        description="Interval between filter checks (seconds) - for REST mode"
    )
    
    check_delay_seconds: int = Field(
        default=10,
        description="Delay after candle close before checking filters - for WebSocket mode"
    )
    
    cooldown_minutes: int = Field(
        default=15,
        description="Cooldown between repeated notifications for same filter+symbol"
    )
    
    parse_spot: bool = Field(
        default=True,
        description="Enable spot market parsing"
    )
    
    parse_futures: bool = Field(
        default=True,
        description="Enable futures market parsing"
    )
    
    # ============================================
    # Database Settings
    # ============================================
    db_path: str = Field(
        default="/data/screener.db",
        description="SQLite database file path"
    )
    
    # ============================================
    # Logging Settings
    # ============================================
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    
    log_path: str = Field(
        default="/logs/screener.log",
        description="Log file path"
    )
    
    # ============================================
    # API Settings
    # ============================================
    api_host: str = Field(
        default="0.0.0.0",
        description="API host to bind"
    )
    
    api_port: int = Field(
        default=8000,
        description="API port"
    )
    
    # ============================================
    # Exchange Settings
    # ============================================
    testnet: bool = Field(
        default=False,
        description="Use Bybit testnet instead of mainnet"
    )
    
    request_timeout: int = Field(
        default=30000,
        description="CCXT request timeout (milliseconds)"
    )
    
    max_retry_attempts: int = Field(
        default=3,
        description="Maximum retry attempts for failed requests"
    )
    
    retry_delay: float = Field(
        default=5.0,
        description="Delay between retry attempts (seconds)"
    )
    
    class Config:
        """Pydantic config."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()