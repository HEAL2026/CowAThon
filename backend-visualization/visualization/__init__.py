"""
backend-visualization package.
Transforms cleaned datasets and analysis models into presentation-ready payloads.
"""

from visualization.payloads import (
    generate_barn_overview,
    generate_cow_timeseries,
    generate_milking_stalls,
    generate_watch_list,
    generate_benchmarks_summary,
    generate_integrations_feasibility,
    generate_pen_map,
    generate_herd_health,
    generate_attribution,
    generate_impact,
)

__all__ = [
    "generate_barn_overview",
    "generate_cow_timeseries",
    "generate_milking_stalls",
    "generate_watch_list",
    "generate_benchmarks_summary",
    "generate_integrations_feasibility",
    "generate_pen_map",
    "generate_herd_health",
    "generate_attribution",
    "generate_impact",
]
