"""Apply the trained behaviour classifier to all 14 days (brief S4).

Writes behavior_10s and behavior_minute to backend-cleaning/data/processed so
the rest of the stack finds them next to joined_1min. Ankle `lying` overrides
the classifier at the minute level wherever they disagree.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend-cleaning"))
sys.path.insert(0, str(REPO / "model"))
from cleaning.ingest import BEHAVIOR_NAMES, TAG_TO_COW, write_table  # noqa: E402
from cleaning.locate import PROCESSED_DIR, find_joined  # noqa: E402
from behavior.features import RAW_IMMU, windows_for_cow_day  # noqa: E402

CKPT = REPO / "model" / "checkpoints" / "behavior_rf.joblib"
LYING = 7


def predict_windows(df: pd.DataFrame, bundle: dict) -> pd.DataFrame:
    X = np.nan_to_num(df[bundle["features"]].to_numpy(dtype=float), nan=0.0)
    p = bundle["model"].predict_proba(X)
    cls = np.array(bundle["model"].classes_)
    out = df[["cow_id", "ts_utc"]].copy()
    out["behavior"] = cls[p.argmax(axis=1)].astype("int8")
    out["prob"] = p.max(axis=1)
    out["behavior_name"] = out["behavior"].map(BEHAVIOR_NAMES).astype("string")
    out["is_synthetic"] = False
    return out


def to_minute(b10: pd.DataFrame, joined: pd.DataFrame) -> pd.DataFrame:
    """Majority class per minute (prob-weighted), then the ankle override."""
    d = b10.assign(ts_utc=b10["ts_utc"].dt.floor("min"))
    w = d.groupby(["cow_id", "ts_utc", "behavior"])["prob"].sum().reset_index()
    idx = w.groupby(["cow_id", "ts_utc"])["prob"].idxmax()
    m = w.loc[idx, ["cow_id", "ts_utc", "behavior"]].rename(columns={"behavior": "behavior_clf"})
    conf = d.groupby(["cow_id", "ts_utc"])["prob"].mean().rename("prob").reset_index()
    m = m.merge(conf, on=["cow_id", "ts_utc"])
    m = m.merge(joined[["cow_id", "ts_utc", "lying"]], on=["cow_id", "ts_utc"], how="left")
    m["behavior"] = m["behavior_clf"].astype("int16")
    ankle_lying = m["lying"].notna() & (m["lying"] >= 0.5)
    ankle_up = m["lying"].notna() & (m["lying"] < 0.5)
    m.loc[ankle_lying, "behavior"] = LYING
    # ankle says up but classifier says lying: fall back to standing (2), the most common upright state
    m.loc[ankle_up & (m["behavior_clf"] == LYING), "behavior"] = 2
    m["ankle_override"] = (m["behavior"] != m["behavior_clf"])
    m["behavior"] = m["behavior"].astype("int8")
    m["behavior_name"] = m["behavior"].map(BEHAVIOR_NAMES).astype("string")
    m["is_synthetic"] = False
    return m.sort_values(["cow_id", "ts_utc"]).reset_index(drop=True)


def main() -> int:
    t0 = time.time()
    bundle = joblib.load(CKPT)
    days = sorted({p.stem.split("_")[1] for p in RAW_IMMU.glob("T*/T*_*.csv")})
    parts = []
    for tag in sorted(TAG_TO_COW):
        for day in days:
            if not (RAW_IMMU / tag / f"{tag}_{day}.csv").exists():
                continue
            w = windows_for_cow_day(tag, day, labels=None)
            if len(w):
                parts.append(predict_windows(w, bundle))
        print(f"  {tag} done ({time.time()-t0:.0f}s)", flush=True)
    b10 = pd.concat(parts, ignore_index=True).sort_values(["cow_id", "ts_utc"]).reset_index(drop=True)
    joined = pd.read_parquet(find_joined())
    bmin = to_minute(b10, joined)
    for c, u in (("behavior", "code 0-7"), ("behavior_clf", "classifier code before ankle override"), ("prob", "mean max-class probability"),
                 ("ankle_override", "bool"), ("behavior_name", "label")):
        from cleaning import ingest
        ingest.UNITS.setdefault(c, u)
    write_table(b10, PROCESSED_DIR, "behavior_10s", "10s", ["cow_id", "ts_utc"],
                {"model": bundle["trained_on"], "note": "RandomForest on neck-IMU windows; no ankle override at this level"})
    write_table(bmin, PROCESSED_DIR, "behavior_minute", "1min", ["cow_id", "ts_utc"],
                {"model": bundle["trained_on"], "note": "prob-weighted majority per minute; ankle lying overrides (brief S4)",
                 "ankle_override_minutes": int(bmin["ankle_override"].sum())})
    print(f"{len(b10):,} windows -> {len(bmin):,} minutes, ankle overrides {int(bmin['ankle_override'].sum()):,} "
          f"({bmin['ankle_override'].mean():.1%}), {time.time()-t0:.0f}s")
    print(bmin["behavior_name"].value_counts(normalize=True).round(3).to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
