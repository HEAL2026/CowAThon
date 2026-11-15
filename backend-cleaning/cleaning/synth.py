"""S0b: seeded synthetic layer for what MMCows does not have (brief 2.5, S0b).

Everything here is labelled `is_synthetic=True` and written to its own
directory, never mixed into the real tables. One seeded "world" over the 14
real days with three episodes:

  days 1-5    resting_route   cases cluster among cows that lay in the index
                              cow's cells (real lying_bouts) inside one
                              bedding window
  days 6-10   milking_route   cases follow the index cow on the same unit in
                              the same session, with no cluster cleaning in
                              between (every cleaning on that unit is skipped
                              that session; elsewhere clusters are cleaned
                              between cows about half the time)
  days 11-14  sporadic        cases share no route

Real inputs used only for *timing and geometry*: UWB out_of_pen gives each
cow's actual milking-trip start; lying_bouts gives where cows actually lay.
Unit assignment, order, sanitation, conductivity/SCC, case onsets and
signatures are synthetic. Ground truth goes to synthetic_labels.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

TZ = "America/Chicago"
N_UNITS = 4
CELL_M = 1.0
RESTING_MIN = 20          # brief S8: resting occupancy = bouts >= 20 min
BEDDING_EVERY_DAYS = 7    # synthetic bedding windows; Aster's real table replaces this
P_CLEAN_BETWEEN = 0.5     # share of cow-to-cow handovers on a unit that get a cluster clean (backflush)

# Literature-style acute signatures, applied over the 1-3 days before dx
# (sources: Kitchen 1981 conductivity; Harmon 1994 SCC; Rajala-Schultz 1999 yield;
# Medrano-Galarza 2012 lying; Siivonen 2011 feeding/rumination). Ranges, not points.
SIGNATURE = {
    "cond_rel": (1.15, 1.40),     # conductivity x
    "scc_log10_delta": (0.6, 1.2), # +0.6..1.2 log10 cells/mL
    "yield_rel": (0.70, 0.88),     # yield x
    "lying_rel": (0.70, 0.90),     # lying time x
    "feeding_rel": (0.75, 0.90),   # feeding time x
    "cbt_delta_c": (0.3, 0.9),     # core body temp +
}


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


# ------------------------------------------------------------- milking log

def milking_sessions(joined: pd.DataFrame) -> pd.DataFrame:
    """Each cow's real trip start per session, from out_of_pen runs that fall in
    the two milking windows (03-07h and 14-18h local). Rows: cow_id, local_date,
    session (AM/PM), trip_start_utc."""
    d = joined[["cow_id", "ts_utc", "out_of_pen"]].sort_values(["cow_id", "ts_utc"]).copy()
    loc = d["ts_utc"].dt.tz_convert(TZ)
    d["local_date"] = loc.dt.date
    d["hour"] = loc.dt.hour
    d["session"] = np.where((d["hour"] >= 3) & (d["hour"] < 7), "AM", np.where((d["hour"] >= 14) & (d["hour"] < 18), "PM", None))
    d = d[d["out_of_pen"] & d["session"].notna()]
    first = d.groupby(["cow_id", "local_date", "session"], as_index=False)["ts_utc"].min().rename(columns={"ts_utc": "trip_start_utc"})
    return first


def synth_milking_log(sessions: pd.DataFrame, rng: np.random.Generator, n_units: int = N_UNITS) -> pd.DataFrame:
    """Order = order of real trip start within the session; unit = seeded
    assignment that keeps each cow mostly on a preferred unit (as parlours do),
    with occasional swaps so sequences differ day to day."""
    cows = sorted(sessions["cow_id"].unique())
    preferred = {c: int(rng.integers(n_units)) for c in cows}
    rows = []
    for (day, sess), g in sessions.groupby(["local_date", "session"]):
        g = g.sort_values("trip_start_utc")
        session_id = f"{day}_{sess}"
        per_unit: dict[int, int] = {}
        last_on_unit: dict[int, pd.Timestamp] = {}
        for _, r in g.iterrows():
            unit = preferred[r["cow_id"]] if rng.random() < 0.8 else int(rng.integers(n_units))
            per_unit[unit] = per_unit.get(unit, 0) + 1
            # a unit milks one cow at a time: attach time >= previous cow on that unit + 4-8 min
            earliest = r["trip_start_utc"] + pd.Timedelta(minutes=3)
            if unit in last_on_unit:
                earliest = max(earliest, last_on_unit[unit] + pd.Timedelta(minutes=int(rng.integers(4, 9))))
            last_on_unit[unit] = earliest
            rows.append({"cow_id": r["cow_id"], "milking_time": earliest,
                         "unit_id": f"U{unit + 1}", "session_id": session_id, "order_in_session": per_unit[unit],
                         "milking_time_source": "uwb_out_of_pen", "unit_source": "synthetic", "is_synthetic": True})
    return pd.DataFrame(rows).sort_values(["session_id", "unit_id", "order_in_session"]).reset_index(drop=True)


def synth_sanitation(log: pd.DataFrame, rng: np.random.Generator, skip: set[tuple[str, str]] = frozenset(),
                     p_between: float = P_CLEAN_BETWEEN) -> pd.DataFrame:
    """Cluster cleanings per unit: one after each session's last milking, plus a
    between-cow clean (backflush) on a share `p_between` of handovers, 1-3 min
    after the earlier cow. The (session_id, unit_id) pairs in `skip` get no
    cleaning at all that session -- that is the exposure chain. `kind` says
    which; backtrace treats both as a sanitation boundary."""
    rows = []
    for (sess, unit), g in log.groupby(["session_id", "unit_id"]):
        if (sess, unit) in skip:
            continue
        times = g.sort_values("milking_time")["milking_time"].tolist()
        for t in times[:-1]:
            if rng.random() < p_between:
                rows.append({"unit_id": unit, "sanitized_at": t + pd.Timedelta(minutes=int(rng.integers(1, 4))),
                             "session_id": sess, "kind": "between_cows", "is_synthetic": True})
        rows.append({"unit_id": unit, "sanitized_at": times[-1] + pd.Timedelta(minutes=int(rng.integers(20, 50))),
                     "session_id": sess, "kind": "end_of_session", "is_synthetic": True})
    return pd.DataFrame(rows).sort_values(["sanitized_at", "unit_id"]).reset_index(drop=True)


def synth_bedding(start_utc: pd.Timestamp, end_utc: pd.Timestamp, every_days: int = BEDDING_EVERY_DAYS) -> pd.DataFrame:
    """Placeholder bedding changes for the one MMCows pen; Aster's table replaces it."""
    changes = pd.date_range(start_utc.floor("D") + pd.Timedelta(hours=14), end_utc, freq=f"{every_days}D", tz="UTC")
    return pd.DataFrame({"barn_id": "mmcows", "pen_id": "4a", "zone_id": "pen_4a", "bedding_type": "sand",
                         "changed_at": changes, "is_synthetic": True})


# ------------------------------------------------------------- scenarios

def _cells(bouts: pd.DataFrame) -> pd.DataFrame:
    b = bouts[(bouts["duration_min"] >= RESTING_MIN) & bouts["x_m"].notna()].copy()
    b["cx"] = np.floor(b["x_m"] / CELL_M).astype(int)
    b["cy"] = np.floor(b["y_m"] / CELL_M).astype(int)
    return b


def resting_route_episode(bouts: pd.DataFrame, bedding: pd.DataFrame, day_range: tuple[int, int], rng: np.random.Generator,
                          n_secondary: int = 3, exclude: set[str] = frozenset()) -> dict:
    """Index cow + the cows that really lay in/next to its cells afterwards,
    inside the same bedding window. Returns the episode spec."""
    b = _cells(bouts)
    t0 = b["start_utc"].min().normalize() + pd.Timedelta(days=day_range[0] - 1)
    t1 = b["start_utc"].min().normalize() + pd.Timedelta(days=day_range[1])
    w = b[(b["start_utc"] >= t0) & (b["start_utc"] < t1)]
    # keep to one bedding window
    changes = bedding["changed_at"].sort_values().to_numpy()
    cut = [c for c in changes if t0 < c < t1]
    if cut:
        w = w[w["start_utc"] >= cut[-1]] if (t1 - cut[-1]) > (cut[-1] - t0) else w[w["start_utc"] < cut[0]]
    best = None
    for idx_cow in rng.permutation(sorted(set(w["cow_id"].unique()) - set(exclude))):
        ic = w[w["cow_id"] == idx_cow].sort_values("start_utc")
        if len(ic) < 3:
            continue
        exposure_start = ic["start_utc"].iloc[len(ic) // 3]  # index cow becomes infectious a third of the way in
        ic_cells = set(zip(ic.loc[ic["start_utc"] >= exposure_start, "cx"], ic.loc[ic["start_utc"] >= exposure_start, "cy"]))
        nb = {(x + dx, y + dy) for (x, y) in ic_cells for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        others = w[(w["cow_id"] != idx_cow) & ~w["cow_id"].isin(exclude) & (w["start_utc"] > exposure_start)]
        hit = others[[(x, y) in nb for x, y in zip(others["cx"], others["cy"])]]
        exposed = hit.groupby("cow_id")["duration_min"].sum().sort_values(ascending=False)
        if len(exposed) >= n_secondary and (best is None or exposed.iloc[:n_secondary].sum() > best[3]):
            best = (idx_cow, exposure_start, exposed, exposed.iloc[:n_secondary].sum(), sorted(ic_cells))
    idx_cow, exposure_start, exposed, _, cells = best
    secondaries = list(exposed.index[:n_secondary])
    return {"scenario": "resting_route", "index_cow": idx_cow, "exposure_start_utc": exposure_start,
            "secondary_cows": secondaries, "source": {"cells": [list(c) for c in cells]},
            "window": [t0, t1]}


def milking_route_episode(log: pd.DataFrame, day_range: tuple[int, int], rng: np.random.Generator, n_secondary: int = 3,
                          exclude: set[str] = frozenset()) -> dict:
    """Index cow milked at order k on unit u; the next cows on that unit in the
    same session are the cases; every cleaning of (session, unit) is skipped so
    nothing separates the index cow from its successors. Prefers a session where
    the index cow is not first on the unit, so order alone does not give it away."""
    days = sorted(log["session_id"].str[:10].unique())
    cand = [s for s in sorted(log["session_id"].unique()) if days[day_range[0] - 1] <= s[:10] <= days[day_range[1] - 1]]
    for sess in rng.permutation(cand):
        for unit, g in log[log["session_id"] == sess].groupby("unit_id"):
            g = g.sort_values("order_in_session")
            if len(g) >= n_secondary + 1:
                k = int(rng.integers(1, len(g) - n_secondary)) if len(g) >= n_secondary + 2 else 0
                idx = g.iloc[k]
                sec = g.iloc[k + 1:k + 1 + n_secondary]
                if idx["cow_id"] in exclude or sec["cow_id"].isin(exclude).any():
                    continue
                return {"scenario": "milking_route", "index_cow": idx["cow_id"], "exposure_start_utc": idx["milking_time"],
                        "secondary_cows": list(sec["cow_id"]), "source": {"unit_id": unit, "session_id": sess, "order_in_session": int(idx["order_in_session"])},
                        "skip_sanitation": (sess, unit)}
    raise RuntimeError("no unit with enough cows in one session for a milking-route episode")


def sporadic_episode(cows: list[str], log: pd.DataFrame, bouts: pd.DataFrame, day_range: tuple[int, int], rng: np.random.Generator, n: int = 3,
                     exclude: set[str] = frozenset()) -> dict:
    """n cows with no shared route in the window: different units in every
    shared session, no shared resting cells (best effort, seeded)."""
    b = _cells(bouts)
    t0 = b["start_utc"].min().normalize() + pd.Timedelta(days=day_range[0] - 1)
    t1 = b["start_utc"].min().normalize() + pd.Timedelta(days=day_range[1])
    w = b[(b["start_utc"] >= t0) & (b["start_utc"] < t1)]
    cells = {c: set(zip(g["cx"], g["cy"])) for c, g in w.groupby("cow_id")}
    lg = log[(log["milking_time"] >= t0) & (log["milking_time"] < t1)]
    units = {c: set(zip(g["session_id"], g["unit_id"])) for c, g in lg.groupby("cow_id")}
    pool = [c for c in cows if c not in exclude]
    best, best_score = None, None
    for _ in range(300):
        pick = list(rng.choice(pool, size=min(n, len(pool)), replace=False))
        shared_cells = sum(len(cells.get(a, set()) & cells.get(b_, set())) for i, a in enumerate(pick) for b_ in pick[i + 1:])
        shared_units = sum(len(units.get(a, set()) & units.get(b_, set())) for i, a in enumerate(pick) for b_ in pick[i + 1:])
        score = shared_cells * 1.0 + shared_units * 3.0
        if best is None or score < best_score:
            best, best_score = pick, score
    return {"scenario": "sporadic", "index_cow": None, "exposure_start_utc": t0, "secondary_cows": best,
            "source": {"shared_cells": int(best_score)}, "window": [t0, t1]}


# ------------------------------------------------------------- cases + signatures

def make_cases(episodes: list[dict], rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for ep in episodes:
        cows = ([ep["index_cow"]] if ep["index_cow"] else []) + ep["secondary_cows"]
        for i, cow in enumerate(cows):
            role = "index" if (ep["index_cow"] and i == 0) else "secondary"
            # Causal timing: the index cow is already shedding at the exposure event
            # (onset before it); a secondary's onset follows the exposure by an
            # incubation lag, and its diagnosis follows its onset. Sporadic cases
            # (no index) keep a free spread inside their window.
            if role == "index":
                onset = ep["exposure_start_utc"] - pd.Timedelta(hours=int(rng.integers(18, 42)))
                dx = ep["exposure_start_utc"] + pd.Timedelta(hours=int(rng.integers(6, 30)))
            elif ep["index_cow"]:
                onset = ep["exposure_start_utc"] + pd.Timedelta(hours=int(rng.integers(12, 48)))
                dx = onset + pd.Timedelta(hours=int(rng.integers(24, 72)))
            else:
                dx = ep["exposure_start_utc"] + pd.Timedelta(hours=int(rng.integers(36, 96)))
                onset = dx - pd.Timedelta(hours=int(rng.integers(24, 72)))
            sig = {k: float(rng.uniform(*v)) for k, v in SIGNATURE.items()}
            rows.append({"scenario": ep["scenario"], "cow_id": cow, "role": role, "onset_utc": onset, "dx_utc": dx,
                         "true_route": {"resting_route": "resting_area", "milking_route": "milking_equipment", "sporadic": "no_common_route"}[ep["scenario"]],
                         "true_source": json.dumps(ep["source"] | ({"index_cow": ep["index_cow"]} if ep["index_cow"] else {}), default=str),
                         **{f"sig_{k}": v for k, v in sig.items()}, "is_synthetic": True})
    return pd.DataFrame(rows).sort_values(["scenario", "dx_utc"]).reset_index(drop=True)


def synth_milk_visits(log: pd.DataFrame, milk_daily: pd.DataFrame, cases: pd.DataFrame, manual: pd.DataFrame | None, rng: np.random.Generator) -> pd.DataFrame:
    """Per-visit milk with per-quarter conductivity and SCC (Aster's shape).
    Baseline from each cow's real daily yield split AM/PM; healthy-cow noise;
    case signatures ramp in over onset..dx and persist 2 days after."""
    daily = milk_daily.assign(local_date=milk_daily["ts_utc"].dt.tz_convert(TZ).dt.date).set_index(["cow_id", "local_date"])["milk_yield_kg"]
    rows = []
    for _, r in log.iterrows():
        day = r["milking_time"].tz_convert(TZ).date()
        base = daily.get((r["cow_id"], day), np.nan)
        if pd.isna(base):
            continue
        share = 0.55 if r["session_id"].endswith("AM") else 0.45
        y = base * share * rng.normal(1.0, 0.05)
        cond = rng.normal(5.0, 0.25, size=4)            # mS/cm, healthy
        scc_log = rng.normal(np.log10(80_000), 0.15)      # cells/mL, healthy
        cbt_delta = 0.0
        c = cases[(cases["cow_id"] == r["cow_id"])]
        for _, k in c.iterrows():
            if k["onset_utc"] <= r["milking_time"] <= k["dx_utc"] + pd.Timedelta(days=2):
                ramp = min(1.0, (r["milking_time"] - k["onset_utc"]) / (k["dx_utc"] - k["onset_utc"]))
                q = int(rng.integers(4)) if "q" not in k else k["q"]
                cond[q] *= 1 + (k["sig_cond_rel"] - 1) * ramp
                scc_log += k["sig_scc_log10_delta"] * ramp
                y *= 1 - (1 - k["sig_yield_rel"]) * ramp
                cbt_delta = k["sig_cbt_delta_c"] * ramp
        rows.append({"cow_id": r["cow_id"], "milking_time": r["milking_time"], "unit_id": r["unit_id"], "session_id": r["session_id"],
                     "yield_kg": round(float(y), 3), "cond_lf": round(float(cond[0]), 3), "cond_lr": round(float(cond[1]), 3),
                     "cond_rf": round(float(cond[2]), 3), "cond_rr": round(float(cond[3]), 3), "cond_max": round(float(cond.max()), 3),
                     "scc_kcells_ml": round(float(10 ** scc_log / 1000), 1), "cbt_delta_c_synthetic": round(float(cbt_delta), 2),
                     "is_synthetic": True})
    return pd.DataFrame(rows).sort_values(["milking_time", "cow_id"]).reset_index(drop=True)


def daily_perturbations(cases: pd.DataFrame) -> pd.DataFrame:
    """Multipliers/deltas analysis applies to its own daily features for case
    cows on case days: lying_rel, feeding_rel, yield_rel, cbt_delta_c. Kept as
    a separate table so the real daily tables are never edited."""
    rows = []
    for _, k in cases.iterrows():
        d0, d1 = k["onset_utc"].tz_convert(TZ).date(), (k["dx_utc"] + pd.Timedelta(days=2)).tz_convert(TZ).date()
        days = pd.date_range(d0, d1, freq="D").date
        for i, day in enumerate(days):
            ramp = min(1.0, (i + 1) / max(1, len(days) - 2))
            rows.append({"scenario": k["scenario"], "cow_id": k["cow_id"], "local_date": day,
                         "lying_rel": 1 - (1 - k["sig_lying_rel"]) * ramp, "feeding_rel": 1 - (1 - k["sig_feeding_rel"]) * ramp,
                         "yield_rel": 1 - (1 - k["sig_yield_rel"]) * ramp, "cbt_delta_c": k["sig_cbt_delta_c"] * ramp, "is_synthetic": True})
    return pd.DataFrame(rows)


# ------------------------------------------------------------- driver

def run(processed: Path, interim: Path, out: Path, seed: int = 0) -> dict:
    rng = _rng(seed)
    joined = pd.read_parquet(processed / "joined_1min.parquet")
    bouts = pd.read_parquet(processed / "lying_bouts.parquet")
    milk = pd.read_parquet(interim / "milk.parquet")
    manual = pd.read_parquet(processed / "manual.parquet") if (processed / "manual.parquet").exists() else None
    cows = sorted(joined["cow_id"].unique())

    sessions = milking_sessions(joined)
    log = synth_milking_log(sessions, rng)
    bedding = synth_bedding(joined["ts_utc"].min(), joined["ts_utc"].max())
    # case cows are disjoint across episodes so attribution is scored cleanly
    ep_rest = resting_route_episode(bouts, bedding, (1, 5), rng)
    used = {ep_rest["index_cow"], *ep_rest["secondary_cows"]}
    ep_milk = milking_route_episode(log, (6, 10), rng, n_secondary=2, exclude=used)
    used |= {ep_milk["index_cow"], *ep_milk["secondary_cows"]}
    ep_spor = sporadic_episode(cows, log, bouts, (11, 14), rng, n=min(3, len(cows) - len(used)), exclude=used)
    sanitation = synth_sanitation(log, rng, skip={ep_milk["skip_sanitation"]})
    cases = make_cases([ep_rest, ep_milk, ep_spor], rng)
    visits = synth_milk_visits(log, milk, cases, manual, rng)
    perturb = daily_perturbations(cases)

    out.mkdir(parents=True, exist_ok=True)
    tables = {"milking_log": log, "sanitation": sanitation, "bedding_synthetic": bedding, "milk_visits_synthetic": visits,
              "synthetic_labels": cases, "daily_perturbations": perturb}
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    summary = {
        "seed": seed, "n_units": N_UNITS, "tables": {k: int(len(v)) for k, v in tables.items()},
        "episodes": [
            {"scenario": ep_rest["scenario"], "index_cow": ep_rest["index_cow"], "secondary": ep_rest["secondary_cows"], "n_cells": len(ep_rest["source"]["cells"])},
            {"scenario": ep_milk["scenario"], "index_cow": ep_milk["index_cow"], "secondary": ep_milk["secondary_cows"], **ep_milk["source"]},
            {"scenario": ep_spor["scenario"], "cows": ep_spor["secondary_cows"], "shared_route_score": ep_spor["source"]["shared_cells"]},
        ],
        "sanitation": {"p_clean_between_cows": P_CLEAN_BETWEEN, "skipped_session_unit": list(ep_milk["skip_sanitation"])},
        "note": "all tables is_synthetic=true; timing/geometry from real UWB + lying_bouts, everything else seeded synthetic",
    }
    (out / "synthetic_world.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    return summary
