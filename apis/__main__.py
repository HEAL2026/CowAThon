"""CLI for the farm API integration layer.

Usage:
    python -m apis list
    python -m apis export-feasibility [--output PATH] [--attach-all]
    python -m apis fetch [--start ISO_UTC] [--end ISO_UTC] [--adapter ID]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from apis.fixtures import export_integrations_feasibility, export_window_fixtures
from apis.registry import create_default_registry


def cmd_list(args: argparse.Namespace) -> int:
    registry = create_default_registry(attach_all=args.attach_all)
    print("\n--- Registered Farm Monitoring & Management Integrations ---")
    for adapter in registry.list_adapters():
        meta = adapter.metadata
        health = adapter.health()
        status_flag = "[ATTACHED]" if adapter.is_attached else "[DETACHED]"
        print(f"\n{status_flag} {meta.name} (id: {meta.adapter_id})")
        print(f"  Vendor:      {meta.vendor}")
        print(f"  Category:    {meta.system_category}")
        print(f"  Cadence:     {meta.cadence}")
        print(f"  Signals:     {', '.join(meta.signals)}")
        print(f"  Health:      {health.status.value} (is_synthetic: {health.is_synthetic})")
        print(f"  Cost/Head:   ${meta.cost_profile.annual_cost_per_head_usd:.2f}/year (Hardware: ${meta.cost_profile.hardware_setup_cost_usd:.2f})")
        print(f"  Feasibility: {meta.cost_profile.feasibility_tier.value}")
        print(f"  ROI Note:    {meta.cost_profile.roi_summary}")
    print()
    return 0


def cmd_export_feasibility(args: argparse.Namespace) -> int:
    output_path = Path(args.output) if args.output else None
    payload = export_integrations_feasibility(output_path=output_path, attach_all=args.attach_all)
    if not output_path:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Exported feasibility payload to {output_path} ({len(payload['systems'])} systems).")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    registry = create_default_registry(attach_all=args.attach_all)
    if args.adapter:
        adapter = registry.get(args.adapter)
        if not adapter:
            print(f"Error: Adapter '{args.adapter}' not found.", file=sys.stderr)
            return 1
        records = adapter.fetch_window(start_utc=args.start, end_utc=args.end, cow_ids=args.cow_ids)
        dumped = [r.to_dict() for r in records]
        print(json.dumps(dumped, indent=2))
    else:
        payload = export_window_fixtures(
            start_utc=args.start,
            end_utc=args.end,
            cow_ids=args.cow_ids,
            output_path=Path(args.output) if args.output else None,
            attach_all=args.attach_all,
        )
        if not args.output:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Exported window fixtures to {args.output}")
    return 0


def cmd_serve_icar(args: argparse.Namespace) -> int:
    from apis.icar.server import run_server
    run_server(port=args.port, host=args.host)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="External Farm APIs Integration Layer CLI (@uiobio)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List all integrations, status, and feasibility")
    p_list.add_argument("--attach-all", action="store_true", help="Include specialized integrations as attached")

    # export-feasibility
    p_export = subparsers.add_parser("export-feasibility", help="Export integrations feasibility JSON")
    p_export.add_argument("--output", "-o", type=str, help="Output JSON file path")
    p_export.add_argument("--attach-all", action="store_true", help="Attach all systems in payload")

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="Fetch window observation records")
    p_fetch.add_argument("--start", type=str, default="2023-07-25T00:00:00Z", help="Start UTC timestamp")
    p_fetch.add_argument("--end", type=str, default="2023-07-25T01:00:00Z", help="End UTC timestamp")
    p_fetch.add_argument("--adapter", "-a", type=str, help="Specific adapter ID to query")
    p_fetch.add_argument("--cow-ids", nargs="*", help="List of cow IDs (e.g. C01 C02)")
    p_fetch.add_argument("--output", "-o", type=str, help="Output file path")
    p_fetch.add_argument("--attach-all", action="store_true", help="Attach all systems")

    # serve-icar
    p_serve = subparsers.add_parser("serve-icar", help="Run ICAR ADE mock vendor HTTP server")
    p_serve.add_argument("--port", "-p", type=int, default=8001, help="Port to bind (default: 8001)")
    p_serve.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")

    args = parser.parse_args()
    if args.command == "list":
        return cmd_list(args)
    elif args.command == "export-feasibility":
        return cmd_export_feasibility(args)
    elif args.command == "fetch":
        return cmd_fetch(args)
    elif args.command == "serve-icar":
        return cmd_serve_icar(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
