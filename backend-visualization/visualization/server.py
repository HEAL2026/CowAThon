"""
Zero-dependency HTTP server for backend-visualization API endpoints.
Enables frontend clients to fetch view payloads with CORS support.
"""

import os
import sys
import json
import re
import argparse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Tuple, Dict, Any, Optional

# Ensure repository packages are resolvable regardless of cwd
REPO_ROOT = Path(__file__).resolve().parents[2]
for subfolder in ["backend-cleaning", "apis", "backend-analysis", "backend-visualization"]:
    p = str(REPO_ROOT / subfolder)
    if p not in sys.path:
        sys.path.insert(0, p)

from visualization.payloads import (
    generate_barn_overview,
    generate_cow_timeseries,
    generate_milking_stalls,
    generate_watch_list,
    generate_benchmarks_summary,
    generate_integrations_feasibility,
)
from visualization.fixtures import (
    generate_mock_cows_overview,
    generate_mock_timeseries,
    COW_IDS,
)
from visualization.data_loader import (
    get_barn_overview_data,
    get_cow_timeseries_data,
    get_benchmarks_data,
    get_watch_list_data,
    get_pen_map_data,
    get_herd_health_data,
    get_attribution_data,
    get_impact_data,
)


class VisualizationAPIHandler(BaseHTTPRequestHandler):

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)
        params = {k: v[0] if len(v) == 1 else v for k, v in query.items()}
        status_code, payload = self.route_request(path, params)

        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw_data = self.rfile.read(content_length)
                payload = json.loads(raw_data.decode("utf-8"))
            else:
                payload = {}
        except Exception as exc:
            status_code, response_data = 400, {"error": f"Invalid JSON payload: {exc}", "status": 400}
        else:
            status_code, response_data = self.route_post_request(path, payload)

        body = json.dumps(response_data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @classmethod
    def route_post_request(cls, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if path in ("/backtrace", "/api/backtrace", "/api/attribution"):
            from visualization.payloads import generate_backtrace_run

            flags = payload.get("flags")
            target_ids: List[str] = []
            if flags and isinstance(flags, list):
                for f in flags:
                    if isinstance(f, dict):
                        cid = f.get("cow_id") or f.get("animal_id")
                        if cid:
                            target_ids.append(str(cid).upper())
                    elif isinstance(f, str):
                        target_ids.append(f.upper())
            elif "animal_ids" in payload and isinstance(payload["animal_ids"], list):
                target_ids = [str(a).upper() for a in payload["animal_ids"]]
            elif "animal_id" in payload:
                target_ids = [str(payload["animal_id"]).upper()]
            elif "target_animal_id" in payload:
                target_ids = [str(payload["target_animal_id"]).upper()]

            if not target_ids:
                target_ids = ["C01"]

            lookback_hours = int(payload.get("lookback_hours", 72))
            if "lookback_days" in payload and "lookback_hours" not in payload:
                lookback_hours = int(payload["lookback_days"]) * 24

            result = generate_backtrace_run(
                flags=flags,
                target_cows=target_ids,
                lookback_hours=lookback_hours,
            )
            return 200, result

        return 404, {"error": f"POST endpoint '{path}' not found", "status": 404}

    @classmethod
    def route_request(cls, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
        params = params or {}
        ts_utc = params.get("ts_utc") or params.get("timestamp")
        pen_id = params.get("pen_id") or "pen_01"
        lookback_hours = (
            int(params["lookback_hours"])
            if "lookback_hours" in params and str(params["lookback_hours"]).isdigit()
            else 72
        )

        if path in ("", "/api/health"):
            return 200, {
                "status": "healthy",
                "service": "backend-visualization",
                "endpoints": [
                    "/api/barn-overview",
                    "/api/cows/{cow_id}",
                    "/api/milking-stalls",
                    "/api/watch-list",
                    "/api/benchmarks",
                    "/api/integrations",
                    "/api/pen-map",
                    "/api/herd-health",
                    "/api/attribution",
                    "/api/impact",
                    "/backtrace (POST)",
                ],
            }

        if path == "/api/barn-overview":
            cows, env, is_synthetic = get_barn_overview_data()
            return 200, generate_barn_overview(
                cows_data=cows,
                indoor_thi=env.get("indoor_thi", 74.2),
                indoor_temp_c=env.get("indoor_temp_c", 26.8),
                indoor_humidity_pct=env.get("indoor_humidity_pct", 66.0),
                ts_utc=ts_utc,
                is_synthetic=is_synthetic,
            )

        if path == "/api/milking-stalls":
            return 200, generate_milking_stalls()

        if path == "/api/watch-list":
            flagged, is_synth = get_watch_list_data()
            payload = generate_watch_list(flagged)
            payload["is_synthetic"] = is_synth
            return 200, payload

        if path == "/api/benchmarks":
            payload, is_synth = get_benchmarks_data()
            payload["is_synthetic"] = is_synth
            return 200, payload

        if path == "/api/integrations":
            return 200, generate_integrations_feasibility()

        if path == "/api/pen-map":
            payload, is_synth = get_pen_map_data(ts_utc=ts_utc, pen_id=pen_id)
            payload["is_synthetic"] = is_synth
            return 200, payload

        if path == "/api/herd-health":
            payload, is_synth = get_herd_health_data(ts_utc=ts_utc)
            payload["is_synthetic"] = is_synth
            return 200, payload

        if path in ("/api/attribution", "/backtrace", "/api/backtrace"):
            payload, is_synth = get_attribution_data(ts_utc=ts_utc, lookback_hours=lookback_hours)
            payload["is_synthetic"] = is_synth
            return 200, payload

        if path == "/api/impact":
            payload, is_synth = get_impact_data(ts_utc=ts_utc)
            payload["is_synthetic"] = is_synth
            return 200, payload

        cow_match = re.match(r"^/api/cows/([A-Za-z0-9_]+)$", path)
        if cow_match:
            cid = cow_match.group(1).upper()
            if cid in COW_IDS:
                days = int(params.get("days", 7)) if "days" in params and str(params["days"]).isdigit() else 7
                pts, is_synth = get_cow_timeseries_data(cid, days=days)
                co_resters = [
                    {
                        "cow_id": "C02" if cid == "C01" else "C01",
                        "shared_zone": "cubicle_row_b",
                        "overlap_minutes": 110,
                        "last_shared_utc": "2023-07-28T12:00:00Z",
                    }
                ] if cid in ["C01", "C02"] else []
                payload = generate_cow_timeseries(
                    cow_id=cid,
                    timeseries_points=pts,
                    co_resting_cows=co_resters,
                )
                payload["is_synthetic"] = is_synth
                return 200, payload
            return 404, {"error": f"Cow '{cid}' not found in registry", "available_ids": COW_IDS}

        return 404, {"error": f"Path '{path}' not found", "status": 404}

    def log_message(self, format, *args):
        # Mute console request logging during tests
        pass


def create_server(host: str = "127.0.0.1", port: int = 8000) -> HTTPServer:
    return HTTPServer((host, port), VisualizationAPIHandler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run visualization HTTP API server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    args = parser.parse_args()

    server = create_server(args.host, args.port)
    print(f"Visualization server running on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()
