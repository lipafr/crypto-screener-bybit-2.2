"""
Models Package
~~~~~~~~~~~~~~

Pydantic models for data validation and serialization.

Available models:
- Filter: Filter configuration and validation
- Trigger: Trigger event data
- Settings: System settings
"""

from .filter import (
    FilterBase,
    FilterCreate,
    FilterUpdate,
    FilterResponse,
    PriceChangeConfig,
    VolumeSpikeConfig
)
from .trigger import (
    TriggerResponse,
    TriggerData,
    TriggerListResponse
)
from .settings import (
    Settings,
    SettingsUpdate
)

__all__ = [
    # Filter models
    "FilterBase",
    "FilterCreate",
    "FilterUpdate",
    "FilterResponse",
    "PriceChangeConfig",
    "VolumeSpikeConfig",
    # Trigger models
    "TriggerResponse",
    "TriggerData",
    "TriggerListResponse",
    # Settings
    "Settings",
    "SettingsUpdate",
]
