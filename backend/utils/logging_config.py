"""
Logging Configuration
~~~~~~~~~~~~~~~~~~~~~

Setup structured logging with emoji indicators for better visibility.

Features:
- Colored console output
- File logging with rotation
- Structured format with timestamps
- Emoji indicators for log levels
- Context information (module, function)
"""

import logging
import sys
from pathlib import Path
from typing import Optional


class EmojiFormatter(logging.Formatter):
    """
    Custom formatter that adds emoji indicators to log messages.
    
    Emoji mapping:
        DEBUG: 🔍
        INFO: ℹ️
        WARNING: ⚠️
        ERROR: ❌
        CRITICAL: 🔥
    """
    
    EMOJI_MAP = {
        logging.DEBUG: "🔍",
        logging.INFO: "ℹ️",
        logging.WARNING: "⚠️",
        logging.ERROR: "❌",
        logging.CRITICAL: "🔥",
    }
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record with emoji.
        
        Args:
            record: Log record to format
        
        Returns:
            Formatted log message with emoji
        """
        # Add emoji to the message
        emoji = self.EMOJI_MAP.get(record.levelno, "📝")
        record.emoji = emoji
        
        # Call parent formatter
        return super().format(record)


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    enable_console: bool = True
) -> logging.Logger:
    """
    Setup application logging.
    
    Creates a logger with console and/or file handlers.
    Uses emoji formatter for better visibility.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to log file (None = no file logging)
        enable_console: Enable console output
    
    Returns:
        Configured logger instance
    
    Examples:
        >>> logger = setup_logging("DEBUG", "/logs/app.log")
        >>> logger.info("Application started")
        ℹ️  2026-01-11 12:34:56 [INFO] Application started
    """
    # Get root logger
    logger = logging.getLogger("crypto_screener")
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Format string
    log_format = (
        "%(emoji)s %(asctime)s [%(levelname)s] "
        "%(name)s.%(funcName)s:%(lineno)d - %(message)s"
    )
    
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # ============================================
    # Console Handler
    # ============================================
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_formatter = EmojiFormatter(log_format, datefmt=date_format)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # ============================================
    # File Handler
    # ============================================
    if log_file:
        # Create log directory if doesn't exist
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create file handler
        file_handler = logging.FileHandler(
            log_file,
            mode='a',
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = EmojiFormatter(log_format, datefmt=date_format)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    # Don't propagate to root logger
    logger.propagate = False
    
    # Log initial message
    logger.debug(f"Logging initialized: level={log_level}, file={log_file}")
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Logger instance
    
    Examples:
        >>> logger = get_logger(__name__)
        >>> logger.info("Module loaded")
    """
    return logging.getLogger(f"crypto_screener.{name}")


# ============================================
# Convenience Functions
# ============================================

def log_exception(logger: logging.Logger, e: Exception, context: str = "") -> None:
    """
    Log exception with full traceback.
    
    Args:
        logger: Logger instance
        e: Exception to log
        context: Additional context information
    
    Examples:
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     log_exception(logger, e, "risky_operation failed")
    """
    if context:
        logger.error(f"{context}: {e}", exc_info=True)
    else:
        logger.error(f"Exception occurred: {e}", exc_info=True)


def log_network_error(
    logger: logging.Logger,
    error: Exception,
    operation: str,
    retry_count: int = 0
) -> None:
    """
    Log network error with VPN hint.
    
    Args:
        logger: Logger instance
        error: Network error
        operation: Operation that failed
        retry_count: Current retry attempt
    
    Examples:
        >>> log_network_error(logger, e, "fetch_tickers", retry_count=1)
    """
    msg = f"Network error during {operation}"
    if retry_count > 0:
        msg += f" (attempt {retry_count})"
    msg += f": {error}"
    
    logger.warning(msg)
    
    # Add VPN hint after multiple failures
    if retry_count >= 2:
        logger.warning(
            "💡 Hint: If network errors persist, try enabling VPN"
        )


if __name__ == "__main__":
    # Test logging
    logger = setup_logging("DEBUG", "/tmp/test.log")
    
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")
    
    try:
        1 / 0
    except Exception as e:
        log_exception(logger, e, "Division test")
