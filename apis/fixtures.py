"""Fixture generators and exporters for the integration layer.

Owner: @uiobio (Lei)
Provides:
- Generation of synthetic integrations feasibility payloads for frontend and visualization.
- Generation of multi-adapter window observation dumps for offline tests and demos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from apis.registry import IntegrationRegistry, create_default_registry


def export_integrations_feasibility(
    output_path: Optional[Path] = None,
    attach_all: bool = False,
) -> Dict[str, Any]:
    """Generate and optionally save integrations_feasibility.json.

    Conforms to backend-visualization/CONTRACT.md §3.5:
    {
      "systems": [ ... ]
    }
    """
    registry = create_default_registry(attach_all=attach_all)
    payload = registry.to_feasibility_payload()

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    return payload


def export_window_fixtures(
    start_utc: str = "2023-07-25T00:00:00Z",
    end_utc: str = "2023-07-25T02:00:00Z",
    cow_ids: Optional[List[str]] = None,
    output_path: Optional[Path] = None,
    attach_all: bool = False,
) -> Dict[str, Any]:
    """Generate and optionally save multi-system window observation records."""
    registry = create_default_registry(attach_all=attach_all)
    records_by_adapter = registry.fetch_all(
        start_utc=start_utc,
        end_utc=end_utc,
        cow_ids=cow_ids,
        only_attached=True,
    )

    dumped: Dict[str, List[Dict[str, Any]]] = {}
    for adapter_id, records in records_by_adapter.items():
        dumped[adapter_id] = [r.to_dict() for r in records]

    payload = {
        "start_utc": start_utc,
        "end_utc": end_utc,
        "is_synthetic": True,
        "adapter_records": dumped,
    }

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    return payload
