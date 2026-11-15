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


if __name__ == "__main__":
    unittest.main()
