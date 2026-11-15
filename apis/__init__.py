"""APIs package: Modular integration layer for external dairy farm monitoring systems.

Owner: @uiobio (Lei)
Boundary & Responsibilities:
- Standardized adapter interface for external systems (BaseAdapter).
- Central registry for discovery, attach/detach, health tracking, and feasibility profiling.
- Offline-ready synthetic mock adapters conforming to MMCows schemas and contracts.
- Invariants: cow_id categorical (None for farm-level), ts_utc tz-aware UTC, no silent imputation,
  is_synthetic=True for all mocks.
"""

from apis.base import (
    AdapterHealth,
    BaseAdapter,
    CostProfile,
    FeasibilityTier,
    HealthStatus,
    ObservationRecord,
    SystemMetadata,
)
from apis.registry import IntegrationRegistry, create_default_registry

__all__ = [
    "BaseAdapter",
    "SystemMetadata",
    "CostProfile",
    "FeasibilityTier",
    "HealthStatus",
    "AdapterHealth",
    "ObservationRecord",
    "IntegrationRegistry",
    "create_default_registry",
]
