"""Tables derived from the real farm event log, for the brief's "manual"
module (parity, days in milk, pregnancy) -- real where the records allow,
and labelled as derived rather than entered.

Everything here is a deterministic function of `health_records`, so it is
reproducible and auditable back to the event rows it came from.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

STUDY_START_UTC = pd.Timestamp("2023-07-21 17:30:00", tz="UTC")  # first sensor row
STUDY_END_UTC = pd.Timestamp("2023-08-04 12:00:00", tz="UTC")

# DairyComp pregnancy-check result code is the token after "Preg - ".
# F / M = fetus sexed (confirmed pregnant). U and other codes are not treated
# as confirmed; we keep the raw code so analysis can decide for itself.
_PREG = re.compile(r"Preg\s*-\s*([A-Z])\b")


def manual_from_health_records(hr: pd.DataFrame, as_of_utc: pd.Timestamp = STUDY_START_UTC,
                               milk: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per cow as of `as_of_utc`: parity, last calving, DIM, latest
    pregnancy check and its code. `dim_from_milk` cross-checks the derived DIM
    against the DIM column MMCows ships in `milk` when that table is given."""
    hr = hr[hr["ts_utc"] <= as_of_utc]
    rows = []
    for cow, g in hr.groupby("cow_id"):
        fresh = g[g["event"] == "Freshen"].sort_values("ts_utc")
        preg = g[g["event"] == "Preg Check"].sort_values("ts_utc")
        last_fresh = fresh["ts_utc"].max() if len(fresh) else pd.NaT
        last_preg = preg.iloc[-1] if len(preg) else None
        code = None
        if last_preg is not None:
            m = _PREG.search(str(last_preg["description"]))
            code = m.group(1) if m else None
        dry = g[g["event"] == "Dry Off"]
        last_dry = dry["ts_utc"].max() if len(dry) else pd.NaT
        rows.append({
            "cow_id": cow,
            "as_of_utc": as_of_utc,
            "parity": int(len(fresh)),
            "last_freshen_utc": last_fresh,
            "dim": int((as_of_utc - last_fresh).days) if pd.notna(last_fresh) else pd.NA,
            "in_milk": bool(pd.isna(last_dry) or (pd.notna(last_fresh) and last_fresh > last_dry)),
            "last_preg_check_utc": last_preg["ts_utc"] if last_preg is not None else pd.NaT,
            "preg_result_code": code,
            "pregnant_confirmed": code in ("F", "M"),
            "lame_dx_last_60d": bool(((g["event_detail"] == "Lame") & (g["ts_utc"] >= as_of_utc - pd.Timedelta(days=60))).any()),
            "clinical_mastitis_lifetime": int((g["event_detail"] == "Clinical Mastitis").sum()),
            "last_clinical_mastitis_utc": g.loc[g["event_detail"] == "Clinical Mastitis", "ts_utc"].max() if (g["event_detail"] == "Clinical Mastitis").any() else pd.NaT,
            "source": "derived_from_health_records",
            "is_synthetic": False,
        })
    out = pd.DataFrame(rows)
    out["dim"] = out["dim"].astype("Int64")
    if milk is not None and len(milk):
        first = milk.sort_values("ts_utc").groupby("cow_id").first()
        out = out.merge(first[["dim"]].rename(columns={"dim": "dim_from_milk"}), left_on="cow_id", right_index=True, how="left")
        out["dim_from_milk"] = out["dim_from_milk"].astype("Int64")
        out["dim_matches_milk"] = (out["dim"] - out["dim_from_milk"]).abs() <= 1
        # The event log can miss a calving (C09: last Freshen 2021-07, Dry Off
        # 2022-07, yet the farm's own DIM counter reads 182 on 2023-07-21). The
        # farm counter is authoritative for DIM; the log stays authoritative for
        # parity only where the two agree.
        out["dim_best"] = out["dim_from_milk"].fillna(out["dim"]).astype("Int64")
        out["parity_uncertain"] = ~out["dim_matches_milk"].fillna(False)
        out.loc[out["parity_uncertain"], "in_milk"] = True  # a DIM counter running means she is milking
    else:
        out["dim_best"] = out["dim"]
        out["parity_uncertain"] = False
    return out.sort_values("cow_id").reset_index(drop=True)


def mastitis_events(hr: pd.DataFrame) -> pd.DataFrame:
    """Real clinical-mastitis diagnoses, cultures and milk withholds from the
    log, with the quarter parsed from the treatment code where present
    (e.g. 'MOX3RF.' -> RF). Few fall inside the sensor window; they are
    anchors for validation, not training labels."""
    m = hr[hr["event_detail"].isin(["Clinical Mastitis", "Milk Culture", "Withhold Milk"])].copy()
    m["quarter"] = m["description"].str.extract(r"\b(?:[A-Z]+\d*)?(LF|RF|LR|RR|LH|RH)\b", expand=False)
    m["quarter"] = m["quarter"].replace({"LH": "LR", "RH": "RR"})
    m["in_sensor_window"] = (m["ts_utc"] >= STUDY_START_UTC) & (m["ts_utc"] <= STUDY_END_UTC)
    m["days_from_window_end"] = (m["ts_utc"] - STUDY_END_UTC).dt.days
    m["is_synthetic"] = False
    return m.sort_values(["ts_utc", "cow_id"]).reset_index(drop=True)
