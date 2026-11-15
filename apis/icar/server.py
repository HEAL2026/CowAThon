"""HTTP Server serving ICAR ADE mock vendor APIs.

Owner: @uiobio (Lei)
Provides:
- Lightweight HTTP server with CORS support.
- REST endpoints for replay feeds, manual farm logs, flags, and backtrace runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from apis.icar.models import now_utc_iso
from apis.icar.service import IcarAdeService

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VISUALIZATION_PATH = REPO_ROOT / "backend-visualization"
if str(VISUALIZATION_PATH) not in sys.path:
    sys.path.insert(0, str(VISUALIZATION_PATH))

DEFAULT_PORT = 8001


class IcarAdeHandler(BaseHTTPRequestHandler):
    """HTTP Request handler for ICAR ADE endpoints."""

    service = IcarAdeService()

    def _set_headers(self, status_code: int = 200) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self._set_headers(204)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        start_utc = query.get("start", ["2023-07-25T00:00:00Z"])[0]
        end_utc = query.get("end", ["2023-07-25T04:00:00Z"])[0]
        cow_ids = query.get("cows", query.get("cow_id", None))

        try:
            if path == "/health":
                self._send_json({"status": "ok", "service": "ICAR ADE Mock Vendor API", "port": self.server.server_port})
            elif path == "/animals":
                data = self.service.get_animals(cow_ids=cow_ids)
                self._send_json({"animals": data})
            elif path == "/locations":
                data = self.service.get_locations(start_utc, end_utc, cow_ids=cow_ids)
                self._send_json({"locations": data})
            elif path == "/imu":
                data = self.service.get_imu(start_utc, end_utc, cow_ids=cow_ids)
                self._send_json({"imuObservations": data})
            elif path == "/behaviors":
                hours = int(query.get("bucket_hours", [2])[0])
                data = self.service.get_behaviors(start_utc, end_utc, cow_ids=cow_ids, bucket_hours=hours)
                self._send_json({"behaviorBuckets": data})
            elif path == "/milkvisits":
                data = self.service.get_milkvisits(start_utc, end_utc, cow_ids=cow_ids)
                self._send_json({"milkVisits": data})
            elif path == "/environment":
                data = self.service.get_environment(start_utc, end_utc)
                self._send_json({"environment": data})
            elif path == "/bodytemp":
                data = self.service.get_bodytemp(start_utc, end_utc, cow_ids=cow_ids)
                self._send_json({"bodyTemperatures": data})
            elif path == "/healthevents":
                data = self.service.get_healthevents(start_utc, end_utc, cow_ids=cow_ids)
                self._send_json({"healthEvents": data})
            elif path == "/manual":
                entry_type = query.get("type", [None])[0]
                animal_id = query.get("animal_id", [None])[0]
                data = self.service.get_manual_entries(entry_type=entry_type, animal_id=animal_id)
                self._send_json({"manualEntries": data})
            elif path == "/flags":
                animal_id = query.get("animal_id", [None])[0]
                status = query.get("status", [None])[0]
                data = self.service.get_flags(animal_id=animal_id, status=status)
                self._send_json({"flags": data})
            elif path == "/sanitation":
                unit_id = query.get("unit_id", [None])[0]
                kind = query.get("kind", [None])[0]
                session_id = query.get("session_id", [None])[0]
                data = self.service.get_sanitation_records(unit_id=unit_id, kind=kind, session_id=session_id)
                self._send_json({"sanitationRecords": data})
            elif path.startswith("/api/"):
                if path == "/api/integrations":
                    from apis.registry import create_default_registry
                    reg = create_default_registry()
                    self._send_json(reg.to_feasibility_payload())
                else:
                    try:
                        from visualization.server import VisualizationAPIHandler
                        params = {k: v[0] if len(v) == 1 else v for k, v in query.items()}
                        status_code, payload = VisualizationAPIHandler.route_request(path, params)
                        self._set_headers(status_code)
                        self.wfile.write(json.dumps(payload, indent=2).encode("utf-8"))
                    except Exception:
                        self._set_headers(404)
                        self.wfile.write(json.dumps({"error": f"Endpoint '{path}' not found."}).encode("utf-8"))
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": f"Endpoint '{path}' not found."}).encode("utf-8"))
        except Exception as exc:
            self._set_headers(500)
            self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)

        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": "Invalid JSON body."}).encode("utf-8"))
            return

        try:
            if path == "/manual":
                entry_type = payload.get("entry_type", "general")
                details = payload.get("details", {})
                animal_id = payload.get("animal_id")
                recorded_by = payload.get("recorded_by", "operator")
                kind = payload.get("kind")
                entry = self.service.create_manual_entry(
                    entry_type=entry_type,
                    details=details,
                    animal_id=animal_id,
                    recorded_by=recorded_by,
                    kind=kind,
                )
                self._set_headers(201)
                self.wfile.write(json.dumps(entry).encode("utf-8"))

            elif path == "/sanitation":
                unit_id = payload.get("unit_id") or payload.get("unitId") or "STALL-01"
                sanitized_at = payload.get("sanitized_at") or payload.get("sanitizedAt") or now_utc_iso()
                session_id = payload.get("session_id") or payload.get("sessionId") or "unknown_session"
                kind = payload.get("kind", "end_of_session")
                is_synthetic = bool(payload.get("is_synthetic", True))
                entry = self.service.create_sanitation_record(
                    unit_id=unit_id,
                    sanitized_at=sanitized_at,
                    session_id=session_id,
                    kind=kind,
                    is_synthetic=is_synthetic,
                )
                self._set_headers(201)
                self.wfile.write(json.dumps(entry).encode("utf-8"))

            elif path == "/flags":
                animal_ids = payload.get("animal_ids")
                flag_type = payload.get("flag_type", "manual")
                reason = payload.get("reason", "Watch request")
                flagged_by = payload.get("flagged_by", "operator")

                if animal_ids and isinstance(animal_ids, list):
                    flags = self.service.create_flags(
                        animal_ids=animal_ids,
                        flag_type=flag_type,
                        reason=reason,
                        flagged_by=flagged_by,
                    )
                    self._set_headers(201)
                    self.wfile.write(json.dumps({"flags": flags}).encode("utf-8"))
                    return

                animal_id = payload.get("animal_id")
                if not animal_id:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({"error": "animal_id or animal_ids required."}).encode("utf-8"))
                    return
                flag = self.service.create_flag(
                    animal_id=animal_id,
                    flag_type=flag_type,
                    reason=reason,
                    flagged_by=flagged_by,
                )
                self._set_headers(201)
                self.wfile.write(json.dumps(flag).encode("utf-8"))

            elif path == "/backtrace":
                target_ids = []
                if "flags" in payload and isinstance(payload["flags"], list):
                    for f in payload["flags"]:
                        if isinstance(f, dict):
                            cid = f.get("cow_id") or f.get("animal_id")
                            if cid:
                                target_ids.append(cid)
                        elif isinstance(f, str):
                            target_ids.append(f)
                elif "animal_ids" in payload and isinstance(payload["animal_ids"], list):
                    target_ids = payload["animal_ids"]
                elif "animal_id" in payload:
                    target_ids = [payload["animal_id"]]
                elif "target_animal_id" in payload:
                    target_ids = [payload["target_animal_id"]]

                if not target_ids:
                    target_ids = ["C02"]

                if "lookback_hours" in payload:
                    lookback_days = max(1, int(payload["lookback_hours"]) // 24)
                elif "lookback_days" in payload:
                    lookback_days = int(payload["lookback_days"])
                else:
                    lookback_days = 7

                run = self.service.run_backtrace(animal_id=target_ids, lookback_days=lookback_days)
                summary = run.get("summary", {})

                # Align with frontend/app.js S12 attribution & resting overlays contract
                route = summary.get("likelyRoute", "resting_environment")
                likely_route = "resting_area" if "resting" in route else ("milking_equipment" if "milking" in route else route)
                p_val = summary.get("routeConfidencePValue", 0.02)
                resting_p = p_val if "resting" in route else round(1.0 - p_val, 3)
                milking_p = p_val if "milking" in route else round(1.0 - p_val, 3)

                resting_circles = summary.get("implicatedRestingCircles", [])
                primary_cow = summary.get("targetCow", target_ids[0])
                contacts = summary.get("primaryContactCows", [])

                response_obj = {
                    # Spec v2 Section 6 root keys
                    "investigation_window": summary.get("investigation_window", {
                        "start_utc": "2023-07-25T14:00:00Z",
                        "end_utc": now_utc_iso(),
                        "anchor": "flagged_at",
                    }),
                    "flagged_cows": summary.get("flagged_cows", [
                        {"cow_id": cid, "role": "index" if i == 0 else "secondary", "flagged_at": now_utc_iso()}
                        for i, cid in enumerate(target_ids)
                    ]),
                    "resources": summary.get("resources", {
                        "resting_spots": resting_circles,
                        "milking_units": [],
                    }),
                    "exposed_cows": summary.get("exposed_cows", []),
                    "route": summary.get("route", {
                        "likely_route": likely_route,
                        "z_rest": 0.0,
                        "z_milk": 0.0,
                        "p_rest": resting_p,
                        "p_milk": milking_p,
                        "p_floor": 0.012,
                        "n_permutations": 200,
                    }),
                    "provenance": summary.get("provenance", {
                        "lying_bouts": "real",
                        "milking_log": "synthetic",
                        "sanitation": "synthetic",
                        "bedding": "synthetic",
                    }),
                    "is_model_suggestion": True,
                    "is_synthetic": summary.get("is_synthetic", True),
                    # Legacy frontend and test compatibility keys
                    "likely_route": likely_route,
                    "likelyRoute": route,
                    "p_values": {
                        "resting_permutation_p": resting_p,
                        "milking_permutation_p": milking_p,
                    },
                    "implicated_resting_areas": resting_circles,
                    "resting_areas": resting_circles,
                    "implicated_circles": resting_circles,
                    "contact_cows": contacts,
                    "transmission_source": {
                        "identifier": summary.get("implicatedResource", "Resting circle 1.5m"),
                        "primary_index_cow": primary_cow,
                    },
                    "recommended_actions": summary.get("recommended_actions", [summary.get("recommendedIntervention", "Sanitize resting zones.")]),
                    "pathogen_group_likelihood": summary.get("pathogenGroupLikelihood", "environmental_streptococci"),
                    "disclaimer": summary.get("disclaimer", "Attribution reflects epidemiological transmission probability, not clinical diagnosis."),
                    "impact": {
                        "total_affected_cows": len(contacts) + len(target_ids),
                        "flagged_early_count": len(target_ids),
                        "mean_lead_time_hours": 18.5,
                        "estimated_milk_saved_kg": round(142.0 * len(target_ids), 1),
                        "is_synthetic": summary.get("is_synthetic", True),
                    },
                    "runId": run.get("runId"),
                    "targetAnimalId": primary_cow,
                    "targetAnimalIds": target_ids,
                    "summary": summary,
                }
                self._send_json(response_obj)

            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": f"POST endpoint '{path}' not found."}).encode("utf-8"))
        except Exception as exc:
            self._set_headers(500)
            self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))

    def _send_json(self, data: Any) -> None:
        self._set_headers(200)
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard request log lines during test runs
        pass


def run_server(port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> None:
    server = HTTPServer((host, port), IcarAdeHandler)
    print(f"ICAR ADE Mock Vendor Server running on http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ICAR ADE Mock Vendor Server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ICAR ADE Mock Vendor HTTP Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind (default: 8001)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    args = parser.parse_args()
    run_server(port=args.port, host=args.host)
