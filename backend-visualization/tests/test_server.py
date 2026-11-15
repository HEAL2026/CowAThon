"""
Unit and integration tests for backend-visualization HTTP API server.
"""

import os
import sys
import json
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in [REPO_ROOT / "backend-visualization", REPO_ROOT / "backend-cleaning", REPO_ROOT / "apis"]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from visualization.server import create_server, VisualizationAPIHandler


class TestVisualizationServer(unittest.TestCase):

    def test_handler_route_request_unit(self):
        # Health check
        code, data = VisualizationAPIHandler.route_request("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "healthy")

        # Barn overview
        code, data = VisualizationAPIHandler.route_request("/api/barn-overview")
        self.assertEqual(code, 200)
        self.assertIn("cows", data)
        self.assertEqual(len(data["cows"]), 16)

        # Milking stalls
        code, data = VisualizationAPIHandler.route_request("/api/milking-stalls")
        self.assertEqual(code, 200)
        self.assertIn("stalls", data)

        # Watch list
        code, data = VisualizationAPIHandler.route_request("/api/watch-list")
        self.assertEqual(code, 200)
        self.assertIn("items", data)

        # Benchmarks
        code, data = VisualizationAPIHandler.route_request("/api/benchmarks")
        self.assertEqual(code, 200)
        self.assertIn("multimodal_lift_over_env_baseline_auc", data)

        # Integrations
        code, data = VisualizationAPIHandler.route_request("/api/integrations")
        self.assertEqual(code, 200)
        self.assertIn("systems", data)

        # Cow timeseries valid
        code, data = VisualizationAPIHandler.route_request("/api/cows/C01")
        self.assertEqual(code, 200)
        self.assertEqual(data["cow_id"], "C01")

        # Cow timeseries not found
        code, data = VisualizationAPIHandler.route_request("/api/cows/C99")
        self.assertEqual(code, 404)
        self.assertIn("error", data)

        # GET /backtrace alias
        code, data = VisualizationAPIHandler.route_request("/backtrace")
        self.assertEqual(code, 200)
        self.assertIn("likely_route", data)

        # Unknown route
        code, data = VisualizationAPIHandler.route_request("/api/nonexistent")
        self.assertEqual(code, 404)

    def test_handler_route_post_backtrace_unit(self):
        # POST /backtrace with flags
        payload = {
            "flags": [{"cow_id": "C01", "timestamp": "2023-07-28T14:00:00Z", "source": "manual"}],
            "lookback_hours": 72,
        }
        code, data = VisualizationAPIHandler.route_post_request("/backtrace", payload)
        self.assertEqual(code, 200)
        self.assertIn("likely_route", data)
        self.assertIn("p_values", data)
        self.assertIn("resting_areas", data)
        self.assertIn("implicated_resting_areas", data)
        self.assertIn("impact", data)
        self.assertEqual(data["impact"]["flagged_early_count"], 1)

        # POST /api/backtrace with animal_ids
        code2, data2 = VisualizationAPIHandler.route_post_request("/api/backtrace", {"animal_ids": ["C02", "C03"]})
        self.assertEqual(code2, 200)
        self.assertEqual(data2["impact"]["flagged_early_count"], 2)

        # Unknown POST route
        code_err, err_data = VisualizationAPIHandler.route_post_request("/api/unknown", {})
        self.assertEqual(code_err, 404)

    def test_live_http_server_and_cors(self):
        server = create_server("127.0.0.1", 0)  # Bind ephemeral port
        port = server.server_address[1]

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            url = f"http://127.0.0.1:{port}/api/health"
            req = Request(url)
            with urlopen(req, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                # Verify CORS header
                self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
                allow_methods = resp.headers.get("Access-Control-Allow-Methods", "")
                self.assertIn("POST", allow_methods)
                body = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(body["status"], "healthy")

            # Test live POST /backtrace over wire
            post_url = f"http://127.0.0.1:{port}/backtrace"
            post_body = json.dumps({
                "flags": [{"cow_id": "C01", "timestamp": "2023-07-28T14:00:00Z"}],
                "lookback_hours": 72,
            }).encode("utf-8")
            post_req = Request(post_url, data=post_body, headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
            with urlopen(post_req, timeout=3.0) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
                data = json.loads(resp.read().decode("utf-8"))
                self.assertIn("likely_route", data)
                self.assertIn("p_values", data)
                self.assertIn("implicated_resting_areas", data)
                self.assertIn("impact", data)

            # Test 404 handling over wire
            url_404 = f"http://127.0.0.1:{port}/api/cows/INVALID"
            with self.assertRaises(HTTPError) as ctx:
                urlopen(url_404, timeout=3.0)
            self.assertEqual(ctx.exception.code, 404)

        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
