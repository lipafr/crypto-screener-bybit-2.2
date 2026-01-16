"""
API Package
~~~~~~~~~~~

FastAPI REST endpoints for managing filters, triggers, and settings.

Available routers:
- filters: CRUD operations for filters
- triggers: Historical trigger data
- settings: System configuration
- websocket: Real-time notifications
"""

__all__ = ["filters", "triggers", "settings", "websocket"]
