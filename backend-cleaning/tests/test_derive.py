"""Tests for tables derived from the farm event log."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cleaning.derive import STUDY_START_UTC, manual_from_health_records, mastitis_events  # noqa: E402


def _ev(cow, ts, event, detail=None, desc=""):
    return {"cow_id": cow, "ts_utc": pd.Timestamp(ts, tz="UTC"), "event": event, "event_detail": detail or event, "description": desc}


def test_manual_parity_dim_pregnancy_and_milk_crosscheck():
    hr = pd.DataFrame([
        _ev("C01", "2020-01-01", "Freshen"), _ev("C01", "2022-12-27 05:00", "Freshen"),
        _ev("C01", "2023-07-03", "Preg Check", desc="Preg - F - HEIFER"),
        _ev("C09", "2021-07-24", "Freshen"), _ev("C09", "2022-07-04", "Dry Off"),   # calving missing from log
        _ev("C09", "2023-07-17", "Preg Check", desc="Preg - U - 46 DAYS"),
        _ev("C01", "2024-01-01", "Freshen"),  # after as_of: must be ignored
    ])
    milk = pd.DataFrame({"cow_id": ["C01", "C09"], "ts_utc": [STUDY_START_UTC] * 2, "dim": [206, 182]})
    m = manual_from_health_records(hr, milk=milk).set_index("cow_id")
    assert m.loc["C01", "parity"] == 2 and m.loc["C01", "dim"] == 206 and m.loc["C01", "dim_matches_milk"]
    assert m.loc["C01", "pregnant_confirmed"] and m.loc["C01", "preg_result_code"] == "F"
    assert not m.loc["C09", "pregnant_confirmed"] and m.loc["C09", "preg_result_code"] == "U"
    assert m.loc["C09", "dim_best"] == 182 and m.loc["C09", "parity_uncertain"] and m.loc["C09", "in_milk"]
    assert (m["is_synthetic"] == False).all() and (m["source"] == "derived_from_health_records").all()  # noqa: E712


def test_mastitis_events_quarter_parse_and_window_flag():
    hr = pd.DataFrame([
        _ev("C12", "2023-09-04 05:00", "Medical diagnosis", "Clinical Mastitis", "Clinical Mastitis - MOX3RF.3"),
        _ev("C08", "2022-06-25 05:00", "Medical diagnosis", "Clinical Mastitis", "Clinical Mastitis - SLC3RH."),
        _ev("C01", "2023-07-25 05:00", "Medical diagnosis", "Clinical Mastitis", "Clinical Mastitis - BAN2.15"),
        _ev("C01", "2023-07-25 06:00", "Move", desc="Pen: 6"),
    ])
    me = mastitis_events(hr)
    assert len(me) == 3, "Move is not a mastitis event"
    by = me.set_index(["cow_id", "ts_utc"])
    assert by.loc[("C12", pd.Timestamp("2023-09-04 05:00", tz="UTC")), "quarter"] == "RF"
    assert by.loc[("C08", pd.Timestamp("2022-06-25 05:00", tz="UTC")), "quarter"] == "RR", "RH normalised to RR"
    assert me["in_sensor_window"].tolist() == [False, True, False]
    assert (me["is_synthetic"] == False).all()  # noqa: E712


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
