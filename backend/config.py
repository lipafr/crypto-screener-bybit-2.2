# 🔧 Инструкция: Добавить в config.py

## Откройте файл:
```
I:\crypto-screener-bybit-2.2\backend\config.py
```

## Добавьте эти строки в класс Settings:

```python
class Settings(BaseSettings):
    # ... существующие настройки ...
    
    # ===== ДОБАВЬТЕ ЭТИ СТРОКИ =====
    
    # WebSocket settings
    check_delay_seconds: int = Field(
        default=10,
        description="Delay after candle close before checking filters"
    )
    
    # API settings
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    
    # Exchange settings
    testnet: bool = Field(default=False, description="Use testnet")
    
    # ==================================
```

## Пример полного Settings (если нужно):

```python
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    """Application settings"""
    
    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str
    
    # Screener
    check_interval_seconds: int = 300  # Для REST (не используется в WS)
    check_delay_seconds: int = 10      # ← НОВОЕ! Для WebSocket
    cooldown_minutes: int = 15
    parse_spot: bool = True
    parse_futures: bool = True
    
    # Database
    db_path: str = "/data/screener.db"
    
    # Logging
    log_level: str = "INFO"
    log_path: str = "/logs/screener.log"
    
    # API
    api_host: str = "0.0.0.0"          # ← НОВОЕ!
    api_port: int = 8000               # ← НОВОЕ!
    
    # Exchange
    testnet: bool = False              # ← НОВОЕ!
    request_timeout: int = 30000
    max_retry_attempts: int = 3
    retry_delay: float = 5.0
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

