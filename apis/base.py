"""Base definitions and contract for the external farm API integration layer.

Owner: @uiobio (Lei)
Boundary:
- Adapters fetch and shape observations from external farm systems into records
  keyed by `cow_id` (C-scheme categorical string, or None for barn/farm-wide systems)
  and `ts_utc` (ISO 8601 string in tz-aware UTC).
- Invariant: Adapters fetch and shape only. They do not duplicate cleaning,
  and never silently impute data. If data is filled, `*_is_imputed` must be set.
- All mock data carries `is_synthetic = True`.
- Detached or unhealthy integrations degrade gracefully and return empty/missing
  indicators without raising unexpected errors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class HealthStatus(str, Enum):
    """Health status of an external farm API integration."""
    ATTACHED = "attached"
    CONFIGURED = "configured"
    REACHABLE = "reachable"
    MOCKED = "mocked"
    DEGRADED = "degraded"
    DETACHED = "detached"
    UNAVAILABLE = "unavailable"


class FeasibilityTier(str, Enum):
    """Small-farm economic feasibility tier."""
    RECOMMENDED = "recommended"       # High ROI, affordable for <= 100 cows
    OPTIONAL = "optional"             # Moderate ROI, farm-specific priority
    HIGH_COST_SPECIALIZED = "high_cost_specialized"  # Expensive infrastructure (e.g. RTLS)


@dataclass(frozen=True)
class CostProfile:
    """Cost and small-farm economic feasibility profile."""
    annual_cost_per_head_usd: float
    hardware_setup_cost_usd: float
    feasibility_tier: FeasibilityTier
    recommended_min_herd_size: int
    roi_summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "annual_cost_per_head_usd": self.annual_cost_per_head_usd,
            "hardware_setup_cost_usd": self.hardware_setup_cost_usd,
            "feasibility_tier": self.feasibility_tier.value,
            "recommended_min_herd_size": self.recommended_min_herd_size,
            "roi_summary": self.roi_summary,
        }


@dataclass(frozen=True)
class SystemMetadata:
    """Static metadata describing an external integration adapter."""
    adapter_id: str
    name: str
    vendor: str
    system_category: str
    signals: List[str]
    cadence: str
    is_animal_level: bool  # True: per-cow records (C01..C16); False: barn/farm-wide (cow_id is None)
    cost_profile: CostProfile
    documentation_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "name": self.name,
            "vendor": self.vendor,
            "system_category": self.system_category,
            "signals": list(self.signals),
            "cadence": self.cadence,
            "is_animal_level": self.is_animal_level,
            "cost_profile": self.cost_profile.to_dict(),
            "documentation_url": self.documentation_url,
        }


@dataclass
class AdapterHealth:
    """Live health and connection state of an adapter."""
    adapter_id: str
    status: HealthStatus
    is_attached: bool
    is_healthy: bool
    is_synthetic: bool
    last_heartbeat_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    message: str = "Ready"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "status": self.status.value,
            "is_attached": self.is_attached,
            "is_healthy": self.is_healthy,
            "is_synthetic": self.is_synthetic,
            "last_heartbeat_utc": self.last_heartbeat_utc,
            "message": self.message,
        }


@dataclass
class ObservationRecord:
    """Standardized observation record matching backend-cleaning invariants.

    Keys:
    - cow_id: Optional[str] (e.g. "C01".."C16", or None for farm-level like weather)
    - ts_utc: str (tz-aware ISO 8601 UTC timestamp, e.g. "2023-07-25T14:00:00Z")
    - values: Dict[str, Any] (metrics matching canonical names)
    - imputation_flags: Dict[str, bool] (signals mapped to True if imputed)
    - age_seconds: Dict[str, float] (seconds since last non-imputed reading)
    - is_synthetic: bool (always True for mock adapters)
    """
    cow_id: Optional[str]
    ts_utc: str
    values: Dict[str, Any] = field(default_factory=dict)
    imputation_flags: Dict[str, bool] = field(default_factory=dict)
    age_seconds: Dict[str, float] = field(default_factory=dict)
    is_synthetic: bool = False

    def __post_init__(self) -> None:
        if self.cow_id is not None and not isinstance(self.cow_id, str):
            raise TypeError(f"cow_id must be str or None, got {type(self.cow_id)}")
        if not isinstance(self.ts_utc, str) or not self.ts_utc.endswith("Z"):
            raise ValueError(f"ts_utc must be UTC ISO-8601 ending with 'Z', got '{self.ts_utc}'")

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "cow_id": self.cow_id,
            "ts_utc": self.ts_utc,
            "is_synthetic": self.is_synthetic,
            **self.values,
        }
        for k, v in self.imputation_flags.items():
            out[f"{k}_is_imputed"] = v
        for k, v in self.age_seconds.items():
            out[f"{k}_age_s"] = v
        return out


class BaseAdapter(ABC):
    """Abstract base class for all external farm system adapters."""

    def __init__(self, is_attached: bool = True) -> None:
        self._is_attached = is_attached

    @property
    @abstractmethod
    def metadata(self) -> SystemMetadata:
        """Returns the static metadata describing this integration."""
        pass

    @abstractmethod
    def health(self) -> AdapterHealth:
        """Returns the current connection and operational health."""
        pass

    @property
    def is_attached(self) -> bool:
        """Whether this adapter is currently attached to the farm dashboard."""
        return self._is_attached

    def attach(self) -> None:
        """Attach this integration."""
        self._is_attached = True

    def detach(self) -> None:
        """Detach this integration."""
        self._is_attached = False

    @abstractmethod
    def fetch_window(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[ObservationRecord]:
        """Fetch records for a given UTC time window.

        Args:
            start_utc: ISO UTC string (inclusive)
            end_utc: ISO UTC string (inclusive)
            cow_ids: Optional list of cow IDs (e.g. ['C01', 'C02']) to filter by.

        Returns:
            List of ObservationRecords. If detached or unavailable, returns an
            empty list gracefully rather than crashing.
        """
        pass
