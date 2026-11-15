"""Unit tests for ICAR ADE domain models, state store, and replay service."""

import unittest
from apis.icar.models import (
    Animal,
    BacktraceRun,
    BehaviorBucket,
    BodyTempObservation,
    EnvironmentObservation,
    FlagRecord,
    HealthEvent,
    ImuObservation,
    LocationObservation,
    ManualEntry,
    MilkVisit,
    RestingSpot,
    SanitationRecord,
)
from apis.icar.service import IcarAdeService
from apis.icar.store import StateStore


class TestIcarModels(unittest.TestCase):
    def test_animal_serialization(self):
        a = Animal("C01", "US-001-C01", parity=2, days_in_milk=110, pen_number=1, reproductive_status="pregnant")
        d = a.to_dict()
        self.assertEqual(d["animal"]["id"], "C01")
        self.assertEqual(d["parity"], 2)
        self.assertEqual(d["daysInMilk"], 110)
        self.assertTrue(d["is_synthetic"])

    def test_location_serialization(self):
        loc = LocationObservation("C01", "2023-07-25T14:00:00Z", 12.5, 8.2, 1.25, in_pen=True, zone_id="cubicle_row_b")
        d = loc.to_dict()
        self.assertEqual(d["animal"]["id"], "C01")
        self.assertEqual(d["eventDateTime"], "2023-07-25T14:00:00Z")
        self.assertEqual(d["location"]["x_m"], 12.5)
        self.assertTrue(d["location"]["in_pen"])

    def test_behavior_bucket_serialization(self):
        b = BehaviorBucket(
            animal_id="C02",
            start_time="2023-07-25T12:00:00Z",
            end_time="2023-07-25T14:00:00Z",
            duration_minutes=120,
            lying_minutes=75.0,
            feeding_minutes=25.0,
            rumination_proxy=0.62,
            activity_index=0.28,
            behavior_mode="resting",
        )
        d = b.to_dict()
        self.assertEqual(d["animal"]["id"], "C02")
        self.assertEqual(d["period"]["durationMinutes"], 120)
        self.assertEqual(d["metrics"]["predominantBehaviorMode"], "resting")


class TestStateStore(unittest.TestCase):
    def test_manual_entry_flow(self):
        store = StateStore()
        entry = store.add_manual_entry(
            entry_type="bedding",
            details={"bedding_type": "sand", "depth_cm": 12.0},
            recorded_by="barn_tech",
        )
        self.assertIsNotNone(entry.entry_id)
        self.assertEqual(entry.entry_type, "bedding")

        entries = store.get_manual_entries(entry_type="bedding")
        self.assertGreaterEqual(len(entries), 1)

    def test_flag_flow(self):
        store = StateStore()
        flag = store.add_flag(
            animal_id="C03",
            flag_type="manual",
            reason="Limping on rear leg",
            flagged_by="herd_manager",
        )
        self.assertEqual(flag.status, "active")

        # Update flag
        updated = store.update_flag_status(flag.flag_id, "cleared")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "cleared")

    def test_backtrace_run_recording(self):
        store = StateStore()
        run = store.record_backtrace_run(
            target_animal_id="C04",
            lookback_days=7,
            summary={"likelyRoute": "resting_environment"},
        )
        self.assertEqual(run.status, "completed")
        runs = store.get_backtrace_runs(target_animal_id="C04")
        self.assertEqual(len(runs), 1)


class TestIcarAdeService(unittest.TestCase):
    def setUp(self):
        self.service = IcarAdeService()

    def test_get_animals(self):
        animals = self.service.get_animals(["C01", "C02"])
        self.assertEqual(len(animals), 2)
        self.assertEqual(animals[0]["animal"]["id"], "C01")

    def test_get_locations(self):
        locs = self.service.get_locations(
            start_utc="2023-07-25T14:00:00Z",
            end_utc="2023-07-25T14:05:00Z",
            cow_ids=["C01"],
        )
        self.assertGreater(len(locs), 0)
        first = locs[0]
        self.assertEqual(first["animal"]["id"], "C01")
        self.assertIn("location", first)

    def test_get_imu(self):
        imus = self.service.get_imu(
            start_utc="2023-07-25T14:00:00Z",
            end_utc="2023-07-25T14:03:00Z",
            cow_ids=["C01"],
        )
        self.assertGreater(len(imus), 0)
        self.assertIn("kinematics", imus[0])

    def test_get_behaviors_2h_buckets(self):
        buckets = self.service.get_behaviors(
            start_utc="2023-07-25T00:00:00Z",
            end_utc="2023-07-25T06:00:00Z",
            cow_ids=["C01"],
            bucket_hours=2,
        )
        # 6 hours with 2h buckets -> 3 buckets
        self.assertEqual(len(buckets), 3)
        self.assertEqual(buckets[0]["period"]["durationMinutes"], 120)

    def test_get_milkvisits(self):
        visits = self.service.get_milkvisits(
            start_utc="2023-07-25T00:00:00Z",
            end_utc="2023-07-25T23:59:59Z",
            cow_ids=["C01"],
        )
        # 2 milking visits per day
        self.assertEqual(len(visits), 2)
        self.assertEqual(visits[0]["animal"]["id"], "C01")
        self.assertGreater(visits[0]["milking"]["yield_kg"], 10.0)

    def test_get_environment(self):
        env = self.service.get_environment(
            start_utc="2023-07-25T12:00:00Z",
            end_utc="2023-07-25T12:05:00Z",
        )
        self.assertGreater(len(env), 0)
        self.assertIn("indoorClimate", env[0])
        self.assertIn("outdoorClimate", env[0])

    def test_get_bodytemp(self):
        cbt = self.service.get_bodytemp(
            start_utc="2023-07-25T14:00:00Z",
            end_utc="2023-07-25T14:05:00Z",
            cow_ids=["C02"],
        )
        self.assertGreater(len(cbt), 0)
        self.assertIn("bodyTemperature_c", cbt[0])

    def test_healthevents(self):
        events = self.service.get_healthevents(
            start_utc="2023-07-21T00:00:00Z",
            end_utc="2023-07-26T00:00:00Z",
            cow_ids=["C02"],
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["animal"]["id"], "C02")

    def test_manual_crud(self):
        entry = self.service.create_manual_entry(
            entry_type="sanitation",
            details={"unit_id": "STALL-03", "chemical": "iodine"},
        )
        self.assertEqual(entry["entryType"], "sanitation")
        entries = self.service.get_manual_entries(entry_type="sanitation")
        self.assertGreaterEqual(len(entries), 1)

    def test_flag_crud(self):
        flag = self.service.create_flag("C05", "manual", "Resting drop", flagged_by="vet")
        self.assertEqual(flag["status"], "active")
        active_flags = self.service.get_flags(animal_id="C05", status="active")
        self.assertEqual(len(active_flags), 1)

    def test_backtrace_run(self):
        run = self.service.run_backtrace(animal_id="C02", lookback_days=7)
        self.assertEqual(run["status"], "completed")
        self.assertIn("likelyRoute", run["summary"])
        self.assertIn("disclaimer", run["summary"])
        self.assertIn("delegatedToAnalysis", run["summary"])

    def test_backtrace_flag_timestamps_forwarding(self):
        self.service.create_flag(
            animal_id="C02",
            flag_type="manual",
            reason="Elevated SCC and heat spike",
            flagged_at_utc="2026-10-14T08:00:00Z",
        )
        self.service.create_flag(
            animal_id="C05",
            flag_type="auto",
            reason="Conductivity anomaly",
            flagged_at_utc="2026-10-14T09:30:00Z",
        )
        run = self.service.run_backtrace(animal_id="C02", lookback_days=3)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["targetAnimalId"], "C02")
        self.assertEqual(run["lookbackDays"], 3)

    def test_group_flags_and_backtrace_circles(self):
        # 1. Multi-cow group flag creation
        flags = self.service.create_flags(
            animal_ids=["C02", "C06"],
            flag_type="manual",
            reason="Group outbreak cluster",
            flagged_by="operator",
        )
        self.assertEqual(len(flags), 2)
        self.assertEqual(flags[0]["animalId"], "C02")
        self.assertEqual(flags[1]["animalId"], "C06")

        # 2. Multi-cow group backtrace
        run = self.service.run_backtrace(animal_id=["C02", "C06"], lookback_days=5)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["targetAnimalId"], "C02")
        self.assertEqual(run["targetAnimalIds"], ["C02", "C06"])
        self.assertIn("implicatedRestingCircles", run["summary"])
        if "resting" in run["summary"]["likelyRoute"]:
            circles = run["summary"]["implicatedRestingCircles"]
            self.assertGreaterEqual(len(circles), 1)
            first_c = circles[0]
            self.assertEqual(first_c["radius_m"], 1.5)
            self.assertIn("center_x_m", first_c)
            self.assertIn("center_y_m", first_c)
            self.assertIn("until_bedding_change_utc", first_c)
            self.assertNotIn("cell_X", run["summary"]["implicatedResource"])


class TestIcarServerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import HTTPServer
        from apis.icar.server import IcarAdeHandler

        cls.server = HTTPServer(("127.0.0.1", 0), IcarAdeHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_s12_endpoints(self):
        import json
        from urllib.request import urlopen

        url = f"http://127.0.0.1:{self.port}/api/integrations"
        with urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIn("systems", data)

    def test_get_s12_endpoint_with_query_params(self):
        import json
        from urllib.request import urlopen

        url = f"http://127.0.0.1:{self.port}/api/pen-map?ts_utc=2023-07-28T10:00:00Z&pen_id=pen_02"
        with urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data.get("ts_utc"), "2023-07-28T10:00:00Z")
            self.assertEqual(data.get("pen_id"), "pen_02")

    def test_post_backtrace_frontend_payload(self):
        import json
        from urllib.request import Request, urlopen

        url = f"http://127.0.0.1:{self.port}/backtrace"
        payload = {
            "flags": [
                {"cow_id": "C02", "timestamp": "2023-07-28T12:00:00Z", "source": "manual"},
                {"cow_id": "C05", "timestamp": "2023-07-28T14:00:00Z", "source": "manual"},
            ],
            "lookback_hours": 72,
        }
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("likely_route", data)
            self.assertIn("p_values", data)
            self.assertIn("implicated_resting_areas", data)
            self.assertIn("transmission_source", data)
            self.assertIn("impact", data)
            self.assertEqual(data["transmission_source"]["primary_index_cow"], "C02")
            # Verify Section 6 root keys in wire response
            self.assertIn("investigation_window", data)
            self.assertIn("flagged_cows", data)
            self.assertIn("resources", data)
            self.assertIn("resting_spots", data["resources"])
            self.assertIn("milking_units", data["resources"])
            self.assertIn("route", data)
            self.assertIn("provenance", data)
            self.assertTrue(data["is_model_suggestion"])
            for s in data["resources"]["resting_spots"]:
                self.assertIn("spot_id", s)
                self.assertEqual(s["radius_m"], 1.5)

    def test_http_sanitation_endpoints(self):
        import json
        from urllib.request import Request, urlopen

        # POST /sanitation with kind
        url = f"http://127.0.0.1:{self.port}/sanitation"
        payload = {
            "unit_id": "U3",
            "session_id": "2023-07-29_PM",
            "kind": "between_cows",
            "sanitized_at": "2023-07-29T19:30:00Z",
        }
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["unit_id"], "U3")
            self.assertEqual(data["kind"], "between_cows")

        # GET /sanitation query
        get_url = f"http://127.0.0.1:{self.port}/sanitation?unit_id=U3"
        with urlopen(get_url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("sanitationRecords", data)
            records = data["sanitationRecords"]
            self.assertTrue(any(r["kind"] == "between_cows" for r in records))


class TestIcarSpecV2AndSanitation(unittest.TestCase):
    def test_sanitation_record_model(self):
        rec = SanitationRecord(
            unit_id="U2",
            sanitized_at="2023-07-29T21:00:00Z",
            session_id="2023-07-29_PM",
            kind="end_of_session",
            is_synthetic=True,
        )
        d = rec.to_dict()
        self.assertEqual(d["unitId"], "U2")
        self.assertEqual(d["kind"], "end_of_session")
        self.assertEqual(d["sessionId"], "2023-07-29_PM")
        self.assertTrue(d["is_synthetic"])

    def test_resting_spot_model(self):
        spot = RestingSpot(
            spot_id="spot_01",
            center_x_m=0.06,
            center_y_m=-0.00,
            radius_m=1.5,
            n_flagged=2,
            flagged_cows=["C06", "C07"],
            dwell_min_by_flagged={"C06": 413.0, "C07": 2077.0},
            successors=[{"cow_id": "C01", "rank": 1, "lag_h": 1.2, "w": 1.0}],
            until_bedding_change_utc="2023-07-28T14:00:00Z",
            provenance="real",
            n_bouts=231,
            n_cows=10,
            dwell_min=41206.0,
            is_synthetic=False,
        )
        d = spot.to_dict()
        self.assertEqual(d["spot_id"], "spot_01")
        self.assertEqual(d["radius_m"], 1.5)
        self.assertEqual(d["n_flagged"], 2)
        self.assertEqual(d["provenance"], "real")
        self.assertFalse(d["is_synthetic"])

    def test_store_sanitation_kind_validation(self):
        store = StateStore()
        # Valid kind
        rec = store.add_sanitation_record(
            unit_id="U1",
            sanitized_at="2023-07-25T11:00:00Z",
            session_id="2023-07-25_AM",
            kind="between_cows",
        )
        self.assertEqual(rec.kind, "between_cows")

        # Invalid kind raises ValueError
        with self.assertRaises(ValueError):
            store.add_sanitation_record(
                unit_id="U1",
                sanitized_at="2023-07-25T11:00:00Z",
                session_id="2023-07-25_AM",
                kind="invalid_kind",
            )

        # Invalid manual sanitation kind raises ValueError
        with self.assertRaises(ValueError):
            store.add_manual_entry(
                entry_type="sanitation",
                details={"unit_id": "U1"},
                kind="invalid_clean_kind",
            )

    def test_service_run_backtrace_spec_v2_and_real_tables(self):
        svc = IcarAdeService()
        run = svc.run_backtrace(animal_id=["C06", "C07"], lookback_days=7)

        # Check BacktraceRun root fields
        self.assertIn("investigation_window", run)
        self.assertIn("flagged_cows", run)
        self.assertIn("resources", run)
        self.assertIn("route", run)
        self.assertIn("provenance", run)
        self.assertTrue(run["is_model_suggestion"])

        # Check resources.resting_spots
        spots = run["resources"]["resting_spots"]
        self.assertEqual(len(spots), 5)
        spot_ids = [s["spot_id"] for s in spots]
        self.assertEqual(sorted(spot_ids), ["spot_01", "spot_02", "spot_03", "spot_04", "spot_05"])
        for s in spots:
            self.assertEqual(s["radius_m"], 1.5)
            self.assertEqual(s["provenance"], "real")
            self.assertFalse(s["is_synthetic"])
            self.assertIn("dwell_min_by_flagged", s)

        # Check resources.milking_units
        units = run["resources"]["milking_units"]
        self.assertGreaterEqual(len(units), 4)
        for u in units:
            self.assertIn("unit_id", u)
            self.assertIn("sanitized_between", u)
            self.assertEqual(u["provenance"], "synthetic")
            self.assertTrue(u["is_synthetic"])

        # Check legacy keys in summary
        summary = run["summary"]
        self.assertIn("likelyRoute", summary)
        self.assertIn("likely_route", summary)
        self.assertIn("routeConfidencePValue", summary)
        self.assertIn("implicatedRestingCircles", summary)
        self.assertEqual(len(summary["implicatedRestingCircles"]), 5)


if __name__ == "__main__":
    unittest.main()
