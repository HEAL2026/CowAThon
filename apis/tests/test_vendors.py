"""Unit tests for commercial vendor API adapters and reprocessing pipeline."""

import unittest

from apis.vendors.lely import LelyHorizonAdapter, compute_thi as lely_thi
from apis.vendors.sensehub import SenseHubAdapter, compute_thi as sensehub_thi
from apis.vendors.cowmanager import CowManagerAdapter
from apis.vendors.reprocessor import VendorReprocessor


class TestVendorAdapters(unittest.TestCase):
    def test_thi_computation(self):
        # 25 deg C, 60% RH
        # THI = 0.8 * 25 + 0.6 * (25 - 14.4) + 46.3 = 20.0 + 6.36 + 46.3 = 72.66
        thi = lely_thi(25.0, 60.0)
        self.assertAlmostEqual(thi, 72.66, places=1)
        self.assertEqual(lely_thi(25.0, 60.0), sensehub_thi(25.0, 60.0))

    def test_lely_horizon_adapter(self):
        adapter = LelyHorizonAdapter()
        self.assertTrue(adapter.is_attached)
        self.assertEqual(adapter.metadata.vendor, "Lely Industries N.V.")

        records = adapter.fetch_window(
            start_utc="2023-07-25T08:00:00Z",
            end_utc="2023-07-25T12:00:00Z",
            cow_ids=["C01", "C02"],
        )
        self.assertGreater(len(records), 0)

        # Check milking visit record
        milk_recs = [r for r in records if "milk_yield_kg" in r.values]
        self.assertGreater(len(milk_recs), 0)
        rec = milk_recs[0]
        self.assertEqual(rec.values["source_adapter"], "lely_horizon")
        self.assertTrue(rec.is_synthetic)
        self.assertIn("cond_lf_ms_cm", rec.values)
        self.assertIn("cond_max_ms_cm", rec.values)
        self.assertGreaterEqual(rec.values["cond_max_ms_cm"], rec.values["cond_lf_ms_cm"])

        # Check collar record
        collar_recs = [r for r in records if "rumination_minutes" in r.values]
        self.assertGreater(len(collar_recs), 0)
        self.assertIn("activity_index", collar_recs[0].values)
        self.assertIn("lying", collar_recs[0].values)

        # Check climate record
        clim_recs = [r for r in records if r.cow_id is None]
        self.assertGreater(len(clim_recs), 0)
        self.assertIn("indoor_thi", clim_recs[0].values)

    def test_sensehub_adapter(self):
        adapter = SenseHubAdapter()
        self.assertTrue(adapter.is_attached)
        self.assertEqual(adapter.metadata.adapter_id, "merck_sensehub")

        records = adapter.fetch_window(
            start_utc="2023-07-25T08:00:00Z",
            end_utc="2023-07-25T12:00:00Z",
            cow_ids=["C03"],
        )
        self.assertGreater(len(records), 0)

        milk_recs = [r for r in records if "milk_yield_kg" in r.values]
        self.assertGreater(len(milk_recs), 0)
        self.assertIn("cond_lr_ms_cm", milk_recs[0].values)
        self.assertIn("peak_flow_rate_kg_min", milk_recs[0].values)

        act_recs = [r for r in records if "rumination_minutes" in r.values]
        self.assertGreater(len(act_recs), 0)
        self.assertIn("resting_minutes", act_recs[0].values)
        self.assertIn("panting_minutes", act_recs[0].values)

    def test_cowmanager_adapter(self):
        adapter = CowManagerAdapter()
        self.assertTrue(adapter.is_attached)
        self.assertEqual(adapter.metadata.adapter_id, "cowmanager")

        records = adapter.fetch_window(
            start_utc="2023-07-25T08:00:00Z",
            end_utc="2023-07-25T11:00:00Z",
            cow_ids=["C04"],
        )
        self.assertGreater(len(records), 0)

        rec = records[0]
        self.assertIn("ear_temp_c", rec.values)
        self.assertIn("cbt_c", rec.values)
        self.assertTrue(rec.imputation_flags.get("cbt_c"))
        self.assertIn("activity_index", rec.values)
        self.assertIn("lying", rec.values)

    def test_vendor_reprocessor(self):
        reprocessor = VendorReprocessor()

        # Fetch records from all three adapters
        lely = LelyHorizonAdapter().fetch_window("2023-07-25T09:00:00Z", "2023-07-25T10:00:00Z", ["C01"])
        sensehub = SenseHubAdapter().fetch_window("2023-07-25T09:00:00Z", "2023-07-25T10:00:00Z", ["C01"])
        cowman = CowManagerAdapter().fetch_window("2023-07-25T09:00:00Z", "2023-07-25T10:00:00Z", ["C01"])

        all_records = lely + sensehub + cowman
        rows = reprocessor.reprocess_records(all_records, fill_manual_defaults=True)

        self.assertEqual(len(rows), len(all_records))
        for r in rows:
            self.assertIn("ts_utc", r)
            self.assertIn("source_adapter", r)
            self.assertTrue(r["is_synthetic"])
            if r["cow_id"] == "C01":
                self.assertIn("parity", r)
                self.assertIn("dim", r)
                self.assertIn("pregnant_confirmed", r)

    def test_reprocessor_optional_physiology_columns(self):
        from apis.base import ObservationRecord

        reprocessor = VendorReprocessor()
        rec = ObservationRecord(
            cow_id="C01",
            ts_utc="2023-07-25T10:00:00Z",
            values={
                "source_adapter": "mendeley_optional_source",
                "milk_yield_kg": 24.5,
                "milk_fat_pct": 3.85,
                "milk_protein_pct": 3.25,
                "milk_lactose_pct": 4.75,
                "scc": 140,
                "respiration_rate_bpm": 38.0,
                "pulse_rate_bpm": 68.0,
                "rectal_temp_c": 38.8,
                "dmi_kg": 22.4,
                "thi_category": "mild",
            },
            is_synthetic=False,
        )
        rows = reprocessor.reprocess_records([rec])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["milk_fat_pct"], 3.85)
        self.assertEqual(r["milk_protein_pct"], 3.25)
        self.assertEqual(r["milk_lactose_pct"], 4.75)
        self.assertEqual(r["scc"], 140)
        self.assertEqual(r["respiration_rate_bpm"], 38.0)
        self.assertEqual(r["pulse_rate_bpm"], 68.0)
        self.assertEqual(r["rectal_temp_c"], 38.8)
        self.assertEqual(r["dmi_kg"], 22.4)
        self.assertEqual(r["thi_category"], "mild")

    def test_compatibility_audit_report(self):
        reprocessor = VendorReprocessor()
        audit = reprocessor.generate_compatibility_audit()

        self.assertIn("supported_commercial_ecosystems", audit)
        self.assertEqual(len(audit["supported_commercial_ecosystems"]), 3)

        self.assertIn("omitted_academic_modalities", audit)
        omitted = {o["modality"] for o in audit["omitted_academic_modalities"]}
        self.assertIn("top_down_rgb_multi_camera_video", omitted)
        self.assertIn("continuous_15s_3d_uwb_coordinates", omitted)

        self.assertIn("manual_dummy_data_policy", audit)
        self.assertTrue(audit["manual_dummy_data_policy"]["is_synthetic"])


if __name__ == "__main__":
    unittest.main()
