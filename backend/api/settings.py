"""
Settings API
~~~~~~~~~~~~

REST API endpoints for system settings.

Endpoints:
- GET /api/settings - Get current settings
- PUT /api/settings - Update settings
- POST /api/settings/test-telegram - Test Telegram connection
"""

import logging
from fastapi import APIRouter, HTTPException, Depends

from ..models.settings import Settings, SettingsUpdate
from ..config import settings as app_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ============================================
# Endpoints
# ============================================

@router.get("", response_model=Settings)
async def get_settings():
    """
    Get current system settings.
    
    Returns:
        Current settings
    """
    try:
        # Check if Telegram is configured
        telegram_configured = True
        try:
            if (app_settings.telegram_bot_token == "your_bot_token_here" or
                app_settings.telegram_chat_id == "your_chat_id_here"):
                telegram_configured = False
        except:
            telegram_configured = False
        
        return Settings(
            check_interval_seconds=app_settings.check_interval_seconds,
            cooldown_minutes=app_settings.cooldown_minutes,
            telegram_configured=telegram_configured,
            parse_spot=app_settings.parse_spot,
            parse_futures=app_settings.parse_futures
        )
        
    except Exception as e:
        logger.error(f"❌ Error getting settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("", response_model=Settings)
async def update_settings(
    settings_update: SettingsUpdate
):
    """
    Update system settings.
    
    NOTE: This endpoint updates runtime settings only.
    To persist changes, update .env file.
    
    Request body:
        SettingsUpdate model
    
    Returns:
        Updated settings
    """
    try:
        # Update settings in memory
        if settings_update.check_interval_seconds is not None:
            app_settings.check_interval_seconds = settings_update.check_interval_seconds
        
        if settings_update.cooldown_minutes is not None:
            app_settings.cooldown_minutes = settings_update.cooldown_minutes
        
        if settings_update.parse_spot is not None:
            app_settings.parse_spot = settings_update.parse_spot
        
        if settings_update.parse_futures is not None:
            app_settings.parse_futures = settings_update.parse_futures
        
        logger.info("✅ Settings updated (runtime only)")
        
        # Return updated settings
        return Settings(
            check_interval_seconds=app_settings.check_interval_seconds,
            cooldown_minutes=app_settings.cooldown_minutes,
            telegram_configured=True,  # Assume configured if we got here
            parse_spot=app_settings.parse_spot,
            parse_futures=app_settings.parse_futures
        )
        
    except Exception as e:
        logger.error(f"❌ Error updating settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-telegram")
async def test_telegram():
    """
    Send test message to Telegram to verify configuration.
    
    Returns:
        Success status
    
    Raises:
        400: Telegram not configured or test failed
    """
    try:
        from ..main import app
        
        # Check if notifier exists
        if not hasattr(app.state, 'notifier'):
            raise HTTPException(
                status_code=400,
                detail="Telegram notifier not initialized"
            )
        
        notifier = app.state.notifier
        
        # Send test message
        success = await notifier.send_test_message()
        
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Failed to send test message. Check logs."
            )
        
        logger.info("✅ Test Telegram message sent")
        
        return {
            "success": True,
            "message": "Test message sent successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error sending test message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
