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
from urllib.parse import parse_qs, urlparse

from apis.icar.service import IcarAdeService

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
                entry = self.service.create_manual_entry(
                    entry_type=entry_type,
                    details=details,
                    animal_id=animal_id,
                    recorded_by=recorded_by,
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
                target_ids = payload.get("animal_ids")
                if target_ids and isinstance(target_ids, list):
                    target = target_ids
                else:
                    target = payload.get("animal_id") or payload.get("target_animal_id", "C02")
                lookback_days = int(payload.get("lookback_days", 7))
                run = self.service.run_backtrace(animal_id=target, lookback_days=lookback_days)
                self._set_headers(200)
                self.wfile.write(json.dumps(run).encode("utf-8"))

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
