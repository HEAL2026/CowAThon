"""Tests for Stage 1 ingest + Stage 2 join on tiny synthetic raw files.

Run from backend-cleaning/:  python3 -m pytest tests/ -q
or without pytest:          python3 tests/test_ingest.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cleaning import ingest, join  # noqa: E402
from cleaning.ingest import shape_uwb, shape_weather, aggregate_collar_minute  # noqa: E402

T0 = 1690261200  # 2023-07-25 00:00:00 America/Chicago (CDT) = 05:00 UTC


def test_uwb_null_coords_become_out_of_pen_not_dropped():
    raw = pd.DataFrame({"timestamp": [T0, T0 + 15, T0 + 30],
                        "coord_x_cm": [119.2, np.nan, 130.0], "coord_y_cm": [49.6, np.nan, 50.0], "coord_z_cm": [117.8, np.nan, 110.0]})
    df = shape_uwb(raw, "T01")
    assert list(df["cow_id"].unique()) == ["C01"]
    assert df["out_of_pen"].tolist() == [False, True, False]
    assert len(df) == 3 and abs(df["uwb_x_m"][0] - 1.192) < 1e-9


def test_uwb_impossible_coordinates_are_flagged_not_dropped():
    raw = pd.DataFrame({"timestamp": [T0, T0 + 15, T0 + 30], "coord_x_cm": [100.0, -2088.0, 100.0],
                        "coord_y_cm": [100.0, 100.0, 100.0], "coord_z_cm": [100.0, 100.0, -1260.0]})
    df = shape_uwb(raw, "T01")
    assert df["uwb_suspect"].tolist() == [False, True, True] and len(df) == 3
    assert not df["out_of_pen"].any()


def test_unmapped_tag_has_no_cow():
    df = shape_uwb(pd.DataFrame({"timestamp": [T0], "coord_x_cm": [1.0], "coord_y_cm": [1.0], "coord_z_cm": [1.0]}), "T13")
    assert df["cow_id"].isna().all() and df["tag_id"].iloc[0] == "T13"


def test_weather_parses_units_and_localises():
    raw = pd.DataFrame({"Time": ["00:04:00", "00:09:00"], "Temperature": ["60.7 °F", "--"], "Dew Point": ["57.1 °F", "57.0 °F"],
                        "Humidity": ["88 %", "89 %"], "Wind": ["NNW", "N"], "Speed": ["2.3 mph", "0.0 mph"], "Gust": ["2.8 mph", "0.0 mph"],
                        "Pressure": ["29.65 in", "29.65 in"], "Precip. Rate.": ["0.00 in", "0.10 in"], "Precip. Accum.": ["0.00 in", "0.10 in"],
                        "UV": [0, 1], "Solar": ["0 w/m²", "12 w/m²"]})
    df = shape_weather(raw, "2023-07-25")
    assert str(df["ts_utc"][0]) == "2023-07-25 05:04:00+00:00"  # CDT -> UTC
    assert abs(df["outdoor_temp_c"][0] - (60.7 - 32) * 5 / 9) < 1e-9 and np.isnan(df["outdoor_temp_c"][1])
    assert abs(df["outdoor_wind_mps"][0] - 2.3 * 0.44704) < 1e-9
    assert abs(df["outdoor_pressure_hpa"][0] - 29.65 * 33.8639) < 1e-6
    assert abs(df["outdoor_precip_mm"][1] - 2.54) < 1e-9 and df["outdoor_solar_wm2"][1] == 12


def test_thi_header_is_not_trusted():
    from cleaning.ingest import shape_thi, thi_from_c
    t_c, rh = pd.Series([25.744, 30.0]), pd.Series([51.772, 60.0])
    thi = thi_from_c(t_c, rh)
    # average.csv case: header says F, values are C -> must pass through unchanged
    mislabeled = pd.DataFrame({"timestamp": [T0, T0 + 60], "temperature_F": t_c, "humidity_per": rh, "THI": thi})
    assert np.allclose(shape_thi(mislabeled, "avg")["indoor_temp_c"], t_c)
    # a genuinely-Fahrenheit file must be converted
    real_f = pd.DataFrame({"timestamp": [T0, T0 + 60], "temperature_F": t_c * 9 / 5 + 32, "humidity_per": rh, "THI": thi})
    assert np.allclose(shape_thi(real_f, "x")["indoor_temp_c"], t_c)


def test_collar_minute_aggregate():
    ts = T0 + np.arange(0, 120, 0.1)  # two minutes at 10 Hz
    immu = pd.DataFrame({"timestamp": ts, "accel_x_mps2": 0.0, "accel_y_mps2": 0.0, "accel_z_mps2": -9.81})
    pres = pd.DataFrame({"timestamp": ts, "pressure_Pa": 98000.0})
    out = aggregate_collar_minute(immu, pres, "C02")
    assert len(out) == 2 and (out["neck_imu_n"] == 600).all()
    assert abs(out["neck_imu_magnitude_mean"][0] - 9.81) < 1e-9 and abs(out["collar_pressure_hpa"][0] - 980.0) < 1e-9


def test_behavior_minute_mode_ignores_unknown():
    from cleaning.ingest import shape_behavior
    from cleaning.join import behavior_minute
    # one minute: 30 s unknown, 20 s lying, 10 s standing -> mode lying, known 0.5, lying_frac 2/3
    raw = pd.DataFrame({"timestamp": [T0 + i for i in range(60)], "datetime": "x", "behavior": [0] * 30 + [7] * 20 + [2] * 10})
    b = shape_behavior(raw, "C01")
    assert b["behavior_name"].iloc[0] == "unknown" and not b["behavior_known"].iloc[0]
    m = behavior_minute(b)
    assert len(m) == 1 and m["behavior_mode"].iloc[0] == 7 and m["behavior_mode_name"].iloc[0] == "lying"
    assert abs(m["behavior_known_frac"].iloc[0] - 0.5) < 1e-9 and abs(m["behavior_lying_frac"].iloc[0] - 2 / 3) < 1e-9


def test_stationary_tags_become_collar_unmapped_fixture():
    tmp = Path(tempfile.mkdtemp())
    try:
        raw, interim = tmp / "main_data", tmp / "interim"
        ts = T0 + np.arange(0, 60, 0.1)
        for tag in ("T01", "T13"):
            (raw / "pressure" / tag).mkdir(parents=True)
            pd.DataFrame({"timestamp": ts, "pressure_Pa": 98000.0, "elevation_m": 1.0}).to_csv(raw / "pressure" / tag / f"{tag}_0725.csv", index=False)
        report = {}
        ingest.ingest_collar(raw, interim, report)
        mapped = pd.read_parquet(interim / "collar_1min.parquet")
        fixture = pd.read_parquet(interim / "collar_unmapped.parquet")
        assert mapped["cow_id"].tolist() == ["C01"] and fixture["tag_id"].tolist() == ["T13"]
        assert "cow_id" not in fixture.columns and abs(fixture["collar_pressure_hpa"].iloc[0] - 980.0) < 1e-9
    finally:
        shutil.rmtree(tmp)


def _write_synthetic_raw(raw: Path) -> None:
    """Two cows (C01 via T01, C02 via T02), 3 minutes, plus unmapped T13."""
    mins = [T0 + 60 * i for i in range(3)]
    for c in ("C01", "C02"):
        (raw / "milk").mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"timestamp": [T0 + 12 * 3600], "milk_weight_kg": [34.9], "DIM": [206]}).to_csv(raw / "milk" / f"{c}.csv", index=False)
        (raw / "cbt").mkdir(exist_ok=True)
        pd.DataFrame({"timestamp": mins, "temperature_C": [38.3, 38.4, np.nan]}).to_csv(raw / "cbt" / f"{c}.csv", index=False)
        (raw / "ankle" / c).mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"timestamp": mins, "datetime": "x", "lying": [1, 0, 1]}).to_csv(raw / "ankle" / c / f"{c}_0725.csv", index=False)
    for t in ("T01", "T02", "T13"):
        (raw / "uwb" / t).mkdir(parents=True, exist_ok=True)
        ts = [T0 + 15 * i for i in range(12)]
        x = [100.0] * 8 + [np.nan] * 4  # third minute: out of pen
        pd.DataFrame({"timestamp": ts, "coord_x_cm": x, "coord_y_cm": x, "coord_z_cm": x}).to_csv(raw / "uwb" / t / f"{t}_0725.csv", index=False)
    (raw.parent / "behavior_labels" / "individual").mkdir(parents=True, exist_ok=True)
    for c in ("C01", "C02", "C11"):  # C11 has labels but no sensors
        pd.DataFrame({"timestamp": [T0 + i for i in range(180)], "datetime": "x", "behavior": [2] * 60 + [7] * 60 + [0] * 60}).to_csv(
            raw.parent / "behavior_labels" / "individual" / f"{c}_0725.csv", index=False)
    (raw / "thi").mkdir(exist_ok=True)
    for s in ("S01", "average"):
        pd.DataFrame({"timestamp": mins, "temperature_C": 25.0, "humidity_per": 50.0, "THI": 73.0}).to_csv(raw / "thi" / f"{s}.csv", index=False)
    (raw / "weather").mkdir(exist_ok=True)
    pd.DataFrame({"Time": ["00:00:00"], "Temperature": ["60.7 °F"], "Dew Point": ["57.1 °F"], "Humidity": ["88 %"], "Wind": ["N"],
                  "Speed": ["2.3 mph"], "Gust": ["2.8 mph"], "Pressure": ["29.65 in"], "Precip. Rate.": ["0.00 in"],
                  "Precip. Accum.": ["0.00 in"], "UV": [0], "Solar": ["0 w/m²"]}).to_excel(raw / "weather" / "07_25_2023.xlsx", index=False)


def test_end_to_end_ingest_and_join():
    tmp = Path(tempfile.mkdtemp())
    try:
        raw, interim, processed = tmp / "raw" / "main_data", tmp / "interim", tmp / "processed"
        _write_synthetic_raw(raw)
        r1 = ingest.run(raw, interim, skip_heavy=True)
        assert (interim / "uwb_unmapped.parquet").exists(), "T13 must be quarantined"
        assert r1["dropped_null_key"]["uwb"] == 0
        r2 = join.run(interim, processed)
        df = pd.read_parquet(processed / "joined_1min.parquet")

        assert sorted(df["cow_id"].unique()) == ["C01", "C02"] and len(df) == 6
        assert df["out_of_pen"].tolist() == [False, False, True] * 2
        assert np.isnan(df["uwb_x_m"].iloc[2]), "out-of-pen minute must not be filled"
        assert (df["uwb_suspect_frac"].fillna(0) == 0).all()
        assert np.isnan(df["cbt_c"].iloc[2]), "per-cow gaps stay NaN"
        assert df["indoor_thi"].notna().all() and not df["indoor_thi_is_imputed"].any()  # native 1-min, same minute
        assert df["outdoor_temp_c"].notna().all()
        assert df["outdoor_temp_c_is_imputed"].tolist() == [False, True, True] * 2
        assert df["outdoor_temp_c_age_s"].tolist() == [0.0, 60.0, 120.0] * 2
        assert (df["milk_yield_kg"] == 34.9).all() and df["milk_yield_kg_is_imputed"].all()
        assert r2["imputed_counts"]["outdoor_temp_c_is_imputed"] == 4
        assert df["behavior_mode_name"].tolist() == ["standing", "lying", pd.NA] * 2 or df["behavior_mode_name"].isna().tolist() == [False, False, True] * 2
        assert df["behavior_known_frac"].tolist() == [1.0, 1.0, 0.0] * 2
        assert sorted(pd.read_parquet(interim / "behavior.parquet")["cow_id"].unique()) == ["C01", "C02", "C11"]

        # byte-identical rerun (CONTRACT section 1)
        before = (processed / "joined_1min.parquet").read_bytes()
        join.run(interim, processed)
        assert (processed / "joined_1min.parquet").read_bytes() == before
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
