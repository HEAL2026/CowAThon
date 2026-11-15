"""Tests for the synthetic layer's pure helpers (brief S0b / 2.5)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cleaning import synth  # noqa: E402

T0 = pd.Timestamp("2023-07-25 09:00:00", tz="UTC")  # 04:00 local


def _sessions():
    rows = []
    for d, day in enumerate(["2023-07-25", "2023-07-26"]):
        for i, cow in enumerate([f"C{i:02d}" for i in range(1, 7)]):
            rows.append({"cow_id": cow, "local_date": pd.Timestamp(day).date(), "session": "AM",
                         "trip_start_utc": T0 + pd.Timedelta(days=d, minutes=3 * i)})
    return pd.DataFrame(rows)


def test_milking_log_is_seeded_ordered_and_labelled_synthetic():
    a = synth.synth_milking_log(_sessions(), synth._rng(1), n_units=2)
    b = synth.synth_milking_log(_sessions(), synth._rng(1), n_units=2)
    assert a.equals(b), "same seed, same log"
    assert a["is_synthetic"].all() and (a["unit_source"] == "synthetic").all()
    for (_, _), g in a.groupby(["session_id", "unit_id"]):
        g = g.sort_values("order_in_session")
        assert g["order_in_session"].tolist() == list(range(1, len(g) + 1))
        assert g["milking_time"].is_monotonic_increasing, "order follows real trip start"


def test_sanitation_skips_the_exposure_pair_only():
    log = synth.synth_milking_log(_sessions(), synth._rng(2), n_units=2)
    pair = ("2023-07-25_AM", "U1")
    san = synth.synth_sanitation(log, synth._rng(2), skip={pair})
    assert not ((san["session_id"] == pair[0]) & (san["unit_id"] == pair[1])).any()
    assert ((san["session_id"] == "2023-07-26_AM") & (san["unit_id"] == "U1")).any()
    last = log[(log["session_id"] == "2023-07-26_AM") & (log["unit_id"] == "U1")]["milking_time"].max()
    s = san[(san["session_id"] == "2023-07-26_AM") & (san["unit_id"] == "U1")]["sanitized_at"].iloc[0]
    assert s > last, "sanitised after the session's last milking"


def test_cases_carry_true_route_and_secondaries_after_index():
    ep = {"scenario": "milking_route", "index_cow": "C01", "exposure_start_utc": T0, "secondary_cows": ["C02", "C03"],
          "source": {"unit_id": "U1", "session_id": "x", "order_in_session": 1}}
    c = synth.make_cases([ep], synth._rng(3))
    assert c["true_route"].unique().tolist() == ["milking_equipment"] and c["is_synthetic"].all()
    idx = c[c["role"] == "index"].iloc[0]; sec = c[c["role"] == "secondary"]
    assert (sec["dx_utc"] > idx["dx_utc"]).all(), "secondaries are diagnosed after the index cow"
    assert ((c["dx_utc"] - c["onset_utc"]) >= pd.Timedelta(hours=24)).all(), "signature builds over >= 1 day"
    for k, (lo, hi) in synth.SIGNATURE.items():
        assert c[f"sig_{k}"].between(lo, hi).all()


def test_daily_perturbations_ramp_toward_signature():
    c = synth.make_cases([{"scenario": "sporadic", "index_cow": None, "exposure_start_utc": T0, "secondary_cows": ["C05"], "source": {}}], synth._rng(4))
    p = synth.daily_perturbations(c).sort_values("local_date")
    assert p["is_synthetic"].all() and (p["lying_rel"] <= 1).all() and (p["cbt_delta_c"] >= 0).all()
    assert p["lying_rel"].iloc[-1] <= p["lying_rel"].iloc[0], "effect grows (or holds) toward diagnosis"
    assert abs(p["yield_rel"].min() - c["sig_yield_rel"].iloc[0]) < 1e-9, "reaches the drawn signature"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
