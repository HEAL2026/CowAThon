"""
Zero-dependency HTTP server for backend-visualization API endpoints.
Enables frontend clients to fetch view payloads with CORS support.
"""

import json
import re
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from typing import Tuple, Dict, Any, Optional

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
)


class VisualizationAPIHandler(BaseHTTPRequestHandler):

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        status_code, payload = self.route_request(path)

        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @classmethod
    def route_request(cls, path: str) -> Tuple[int, Dict[str, Any]]:
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
                ],
            }

        if path == "/api/barn-overview":
            cows, env, is_synthetic = get_barn_overview_data()
            return 200, generate_barn_overview(
                cows_data=cows,
                indoor_thi=env.get("indoor_thi", 74.2),
                indoor_temp_c=env.get("indoor_temp_c", 26.8),
                indoor_humidity_pct=env.get("indoor_humidity_pct", 66.0),
                is_synthetic=is_synthetic,
            )

        if path == "/api/milking-stalls":
            return 200, generate_milking_stalls()

        if path == "/api/watch-list":
            flagged = [
                {
                    "cow_id": "C01",
                    "flag_type": "model_suggestion",
                    "risk_category": "priority_watch",
                    "watch_risk_score": 84.5,
                    "watch_reason": "Sustained high CBT (39.85C) under elevated THI accompanied by 18% yield decrease",
                    "confidence": 0.88,
                    "modalities_present": ["cbt", "neck_imu", "indoor_env", "milk_yield", "ankle"],
                    "modalities_missing": ["uwb"],
                    "missing_modality_impact": "Location confidence lower; utilizing last-seen stall beacon",
                    "recommended_action": "Check for heat abatement and udder inflammation prior to next cycle",
                },
                {
                    "cow_id": "C02",
                    "flag_type": "vet_flagged",
                    "risk_category": "moderate_watch",
                    "watch_risk_score": 68.0,
                    "watch_reason": "Co-resting in cubicle_row_b alongside C01 with 22% activity drop",
                    "confidence": 0.74,
                    "modalities_present": ["neck_imu", "indoor_env", "milk_yield", "cbt"],
                    "modalities_missing": ["uwb"],
                    "missing_modality_impact": "Spatial tracking degraded; relying on rumination variance",
                    "recommended_action": "Monitor evening milking yield and observe gait",
                },
            ]
            return 200, generate_watch_list(flagged)

        if path == "/api/benchmarks":
            return 200, generate_benchmarks_summary()

        if path == "/api/integrations":
            return 200, generate_integrations_feasibility()

        cow_match = re.match(r"^/api/cows/([A-Za-z0-9_]+)$", path)
        if cow_match:
            cid = cow_match.group(1).upper()
            if cid in COW_IDS:
                pts, is_synth = get_cow_timeseries_data(cid, days=7)
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
