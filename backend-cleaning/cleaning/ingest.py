"""Stage 1: raw MMCows sections -> one interim parquet per section, native rate.

Every function that shapes data takes and returns DataFrames so it can be
tested on tiny synthetic frames; the `ingest_*` wrappers only do file IO.
Output columns follow CONTRACT.md section 5.1. Rows are dropped only for a
missing key (`cow_id`/`ts_utc`); feature nulls are preserved.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

TZ = "America/Chicago"
TAG_TO_COW = {f"T{i:02d}": f"C{i:02d}" for i in range(1, 11)}  # 10 instrumented cows

# Manually annotated behaviour, 1 s, 07/25 only, all 16 cows. Legend from the
# official benchmark code (benchmarks/1_behavior_cls/immu/*.py: behav_list).
# 0 is UNKNOWN, not a class -- the official loaders drop it; we keep the row
# and flag it so coverage stays honest.
BEHAVIOR_NAMES = {0: "unknown", 1: "walking", 2: "standing", 3: "feed_up", 4: "feed_down",
                  5: "licking", 6: "drinking", 7: "lying"}

# units per output column, written into every sidecar
UNITS = {
    "ts_utc": "UTC timestamp", "cow_id": "C-scheme id", "tag_id": "collar tag",
    "sensor_id": "THI sensor id", "milk_yield_kg": "kg", "dim": "days in milk",
    "cbt_c": "degC", "indoor_temp_c": "degC", "indoor_rh_pct": "%", "indoor_thi": "THI",
    "lying": "0/1", "uwb_x_m": "m", "uwb_y_m": "m", "uwb_z_m": "m", "out_of_pen": "bool", "uwb_suspect": "bool", "uwb_suspect_frac": "fraction of 15 s samples",
    "collar_pressure_hpa": "hPa", "elevation_m": "m",
    "outdoor_temp_c": "degC", "outdoor_dewpoint_c": "degC", "outdoor_rh_pct": "%",
    "outdoor_wind_dir": "compass", "outdoor_wind_mps": "m/s", "outdoor_gust_mps": "m/s",
    "outdoor_pressure_hpa": "hPa", "outdoor_precip_rate_mm_h": "mm/h", "outdoor_precip_mm": "mm",
    "outdoor_uv": "UV index", "outdoor_solar_wm2": "W/m2",
    "neck_imu_magnitude_mean": "m/s2", "neck_imu_magnitude_std": "m/s2", "neck_imu_n": "samples",
    "collar_pressure_n": "samples",
    "behavior": "code 0-7, see BEHAVIOR_NAMES", "behavior_name": "label", "behavior_known": "bool",
    "behavior_mode": "most frequent known code in the minute", "behavior_mode_name": "label",
    "behavior_known_frac": "fraction of the minute's seconds with a known label",
    "behavior_lying_frac": "fraction of known seconds labelled lying",
}


# ---------------------------------------------------------------- helpers

def epoch_to_utc(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, unit="s", utc=True)


def _finish(df: pd.DataFrame, keys: list[str], report: dict, table: str) -> pd.DataFrame:
    """Drop rows with a null key (counted), sort, reset index."""
    before = len(df)
    df = df.dropna(subset=keys)
    report.setdefault("dropped_null_key", {})[table] = before - len(df)
    return df.sort_values(keys).reset_index(drop=True)


def write_table(df: pd.DataFrame, out_dir: Path, name: str, cadence: str, keys: list[str],
                notes: dict | None = None) -> Path:
    """Write <name>.parquet + <name>.schema.json. No wall-clock in the sidecar so
    a rerun on the same raw input is byte-identical (CONTRACT section 1)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.parquet"
    df.to_parquet(path, index=False)
    sidecar = {
        "table": name, "cadence": cadence, "keys": keys, "rows": int(len(df)),
        "columns": {
            c: {"dtype": str(df[c].dtype), "units": UNITS.get(c, ""), "null_count": int(df[c].isna().sum())}
            for c in df.columns
        },
        **(notes or {}),
    }
    (out_dir / f"{name}.schema.json").write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    return path


# ---------------------------------------------------------------- per-section shaping (pure)

def shape_milk(raw: pd.DataFrame, cow_id: str) -> pd.DataFrame:
    return pd.DataFrame({
        "cow_id": cow_id, "ts_utc": epoch_to_utc(raw["timestamp"]),
        "milk_yield_kg": raw["milk_weight_kg"].astype(float), "dim": raw["DIM"].astype("Int64"),
    })


def shape_cbt(raw: pd.DataFrame, cow_id: str) -> pd.DataFrame:
    return pd.DataFrame({"cow_id": cow_id, "ts_utc": epoch_to_utc(raw["timestamp"]),
                         "cbt_c": raw["temperature_C"].astype(float)})


def thi_from_c(temp_c: pd.Series, rh_pct: pd.Series) -> pd.Series:
    """NRC (1971) THI, the dairy heat-stress index, from degC and %RH."""
    return 0.8 * temp_c + (rh_pct / 100.0) * (temp_c - 14.4) + 46.4


def shape_thi(raw: pd.DataFrame, sensor_id: str) -> pd.DataFrame:
    """S01-S06 are headed `temperature_C`; `average.csv` is headed
    `temperature_F` but holds Celsius values. Do not trust the header: take
    whichever column exists, then check it against the source's own THI
    column, which only agrees if the temperature is in degC. Convert from F
    only when the Celsius reading of the data disagrees with its THI."""
    col = "temperature_C" if "temperature_C" in raw.columns else "temperature_F"
    temp = raw[col].astype(float)
    rh = raw["humidity_per"].astype(float)
    thi = raw["THI"].astype(float)
    err_as_c = (thi_from_c(temp, rh) - thi).abs().median()
    err_as_f = (thi_from_c((temp - 32.0) * 5.0 / 9.0, rh) - thi).abs().median()
    if err_as_f < err_as_c:
        temp = (temp - 32.0) * 5.0 / 9.0
    return pd.DataFrame({"sensor_id": sensor_id, "ts_utc": epoch_to_utc(raw["timestamp"]),
                         "indoor_temp_c": temp, "indoor_rh_pct": rh, "indoor_thi": thi})


def shape_ankle(raw: pd.DataFrame, cow_id: str) -> pd.DataFrame:
    # the raw `datetime` string is redundant with `timestamp`; dropped
    return pd.DataFrame({"cow_id": cow_id, "ts_utc": epoch_to_utc(raw["timestamp"]),
                         "lying": raw["lying"].astype("Int8")})


# The UWB frame is pen-centred: in-pen readings span x ~[-10, 10] m and
# y ~[-8.7, 5.7] m (the 20 x 12 m pen plus alley), neck height z ~[0.4, 1.7] m.
# Anything well outside that is a ranging error, not a cow. ~0.4 % of rows.
UWB_BOUNDS = {"uwb_x_m": (-12.0, 12.0), "uwb_y_m": (-9.0, 8.0), "uwb_z_m": (-0.5, 3.0)}


def shape_uwb(raw: pd.DataFrame, tag_id: str) -> pd.DataFrame:
    """cm -> m. A null coordinate means the tag reported nothing: the cow is
    out of the pen (milking). Row is kept with out_of_pen=True, never filled.
    A coordinate outside UWB_BOUNDS is kept too, flagged uwb_suspect=True."""
    coords = raw[["coord_x_cm", "coord_y_cm", "coord_z_cm"]].astype(float)
    out = pd.DataFrame({
        "cow_id": TAG_TO_COW.get(tag_id), "tag_id": tag_id,
        "ts_utc": epoch_to_utc(raw["timestamp"]),
        "uwb_x_m": coords["coord_x_cm"] / 100.0,
        "uwb_y_m": coords["coord_y_cm"] / 100.0,
        "uwb_z_m": coords["coord_z_cm"] / 100.0,
        "out_of_pen": coords.isna().any(axis=1),
    })
    suspect = pd.Series(False, index=out.index)
    for c, (lo, hi) in UWB_BOUNDS.items():
        suspect |= (out[c] < lo) | (out[c] > hi)
    out["uwb_suspect"] = suspect & ~out["out_of_pen"]
    return out


_NUM = re.compile(r"([-+]?\d+(?:\.\d+)?)")  # one capture group: str.extract needs it


def _num(s: pd.Series) -> pd.Series:
    """'60.7 °F' -> 60.7 ; '--' / NaN -> NaN."""
    return s.astype(str).str.extract(_NUM.pattern, expand=False).astype(float)


WEATHER_COLS = {  # xlsx header -> (output column, converter from imperial)
    "Temperature": ("outdoor_temp_c", lambda f: (f - 32.0) * 5.0 / 9.0),
    "Dew Point": ("outdoor_dewpoint_c", lambda f: (f - 32.0) * 5.0 / 9.0),
    "Humidity": ("outdoor_rh_pct", lambda x: x),
    "Speed": ("outdoor_wind_mps", lambda mph: mph * 0.44704),
    "Gust": ("outdoor_gust_mps", lambda mph: mph * 0.44704),
    "Pressure": ("outdoor_pressure_hpa", lambda inhg: inhg * 33.8639),
    "Precip. Rate.": ("outdoor_precip_rate_mm_h", lambda inch: inch * 25.4),
    "Precip. Accum.": ("outdoor_precip_mm", lambda inch: inch * 25.4),
    "UV": ("outdoor_uv", lambda x: x),
    "Solar": ("outdoor_solar_wm2", lambda x: x),
}


def shape_weather(raw: pd.DataFrame, local_date: str) -> pd.DataFrame:
    """One day's Weather Underground export. Cells are strings with imperial
    units and there is no date column -- `local_date` (YYYY-MM-DD) comes from
    the filename. Times are barn-local; converted to UTC."""
    raw = raw.rename(columns=lambda c: str(c).strip())
    time_str = raw["Time"].astype(str).str.extract(r"(\d{1,2}:\d{2}(?::\d{2})?)", expand=False)
    ts_local = pd.to_datetime(local_date + " " + time_str, errors="coerce")
    out = pd.DataFrame({"ts_utc": ts_local.dt.tz_localize(TZ, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")})
    out["outdoor_wind_dir"] = raw["Wind"].astype(str).str.strip().where(raw["Wind"].notna())
    for src, (dst, conv) in WEATHER_COLS.items():
        out[dst] = conv(_num(raw[src])) if src in raw.columns else np.nan
    return out


def shape_behavior(raw: pd.DataFrame, cow_id: str) -> pd.DataFrame:
    code = raw["behavior"].astype("Int8")
    return pd.DataFrame({
        "cow_id": cow_id, "ts_utc": epoch_to_utc(raw["timestamp"]), "behavior": code,
        "behavior_name": code.map(BEHAVIOR_NAMES).astype("string"),
        "behavior_known": code.ne(0).fillna(False).astype(bool),
    })


def aggregate_collar_minute(immu: pd.DataFrame | None, pressure: pd.DataFrame | None, cow_id: str) -> pd.DataFrame:
    """10 Hz collar channels -> per-minute. |accel| mean/std from IMU, mean
    pressure in hPa. The native-rate rows stay in raw CSV (7 + 4 GB); only this
    aggregate is materialised."""
    parts = []
    if immu is not None and len(immu):
        mag = np.sqrt(immu["accel_x_mps2"] ** 2 + immu["accel_y_mps2"] ** 2 + immu["accel_z_mps2"] ** 2)
        g = pd.DataFrame({"ts_utc": epoch_to_utc(immu["timestamp"]).dt.floor("min"), "mag": mag}).groupby("ts_utc")["mag"]
        parts.append(g.agg(neck_imu_magnitude_mean="mean", neck_imu_magnitude_std="std", neck_imu_n="count"))
    if pressure is not None and len(pressure):
        g = pd.DataFrame({"ts_utc": epoch_to_utc(pressure["timestamp"]).dt.floor("min"),
                          "hpa": pressure["pressure_Pa"].astype(float) / 100.0}).groupby("ts_utc")["hpa"]
        parts.append(g.agg(collar_pressure_hpa="mean", collar_pressure_n="count"))
    if not parts:
        return pd.DataFrame(columns=["cow_id", "ts_utc"])
    out = pd.concat(parts, axis=1).reset_index()
    out.insert(0, "cow_id", cow_id)
    return out


# ---------------------------------------------------------------- IO wrappers

def _per_cow_files(section_dir: Path, pattern: str) -> list[tuple[str, Path]]:
    """[(id, path)] sorted, id = first token of the filename (C01 / T01 / S01)."""
    return sorted((p.name.split("_")[0].split(".")[0], p) for p in section_dir.rglob(pattern))


def ingest_simple(raw_dir: Path, out_dir: Path, report: dict, section: str, shaper, pattern: str,
                  keys: list[str], cadence: str, name: str | None = None) -> pd.DataFrame | None:
    files = _per_cow_files(raw_dir / section, pattern)
    if not files:
        report.setdefault("skipped", []).append(section)
        return None
    frames = [shaper(pd.read_csv(p), ident) for ident, p in files]
    df = _finish(pd.concat(frames, ignore_index=True), keys, report, name or section)
    write_table(df, out_dir, name or section, cadence, keys, {"source_files": len(files)})
    return df


def ingest_uwb(raw_dir: Path, out_dir: Path, report: dict) -> None:
    files = _per_cow_files(raw_dir / "uwb", "T*_*.csv")
    if not files:
        report.setdefault("skipped", []).append("uwb")
        return
    df = pd.concat([shape_uwb(pd.read_csv(p), tag) for tag, p in files], ignore_index=True)
    mapped = df[df["cow_id"].notna()].drop(columns="tag_id")
    unmapped = df[df["cow_id"].isna()].drop(columns="cow_id")
    mapped = _finish(mapped, ["cow_id", "ts_utc"], report, "uwb")
    write_table(mapped, out_dir, "uwb", "15s", ["cow_id", "ts_utc"],
                {"source_files": len(files), "out_of_pen_rows": int(mapped["out_of_pen"].sum()),
                 "uwb_suspect_rows": int(mapped["uwb_suspect"].sum()), "uwb_bounds_m": UWB_BOUNDS})
    if len(unmapped):
        unmapped = _finish(unmapped, ["tag_id", "ts_utc"], report, "uwb_unmapped")
        write_table(unmapped, out_dir, "uwb_unmapped", "15s", ["tag_id", "ts_utc"],
                    {"note": "tags not among the 10 instrumented cows; quarantined, not guessed",
                     "tags": sorted(unmapped["tag_id"].unique())})


def ingest_thi(raw_dir: Path, out_dir: Path, report: dict) -> None:
    files = sorted((raw_dir / "thi").glob("*.csv"))
    if not files:
        report.setdefault("skipped", []).append("thi")
        return
    frames = [shape_thi(pd.read_csv(p), "avg" if p.stem == "average" else p.stem) for p in files]
    df = _finish(pd.concat(frames, ignore_index=True), ["sensor_id", "ts_utc"], report, "thi")
    write_table(df, out_dir, "thi", "1min", ["sensor_id", "ts_utc"],
                {"source_files": len(files),
                 "note": "barn-level; no cow_id. sensor_id 'avg' is the source's average.csv, whose header says "
                         "temperature_F but whose values are degC (verified against its own THI column)"})


def ingest_weather(raw_dir: Path, out_dir: Path, report: dict) -> None:
    files = sorted((raw_dir / "weather").glob("??_??_????.xlsx"))
    if not files:
        report.setdefault("skipped", []).append("weather")
        return
    frames = []
    for p in files:
        m, d, y = p.stem.split("_")
        frames.append(shape_weather(pd.read_excel(p), f"{y}-{m}-{d}"))
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset="ts_utc", keep="last")
    df = _finish(df, ["ts_utc"], report, "weather")
    write_table(df, out_dir, "weather", "5min", ["ts_utc"],
                {"source_files": len(files), "note": "outdoor station; imperial source converted to SI"})


def ingest_collar(raw_dir: Path, out_dir: Path, report: dict) -> None:
    """immu + pressure, one (cow, day) file at a time -> collar_1min."""
    immu_files = dict(((t, p.stem.split("_")[1]), p) for t, p in _per_cow_files(raw_dir / "immu", "T*_*.csv"))
    pres_files = dict(((t, p.stem.split("_")[1]), p) for t, p in _per_cow_files(raw_dir / "pressure", "T*_*.csv"))
    keys = sorted(set(immu_files) | set(pres_files))
    if not keys:
        report.setdefault("skipped", []).append("collar_1min")
        return
    parts = []
    for tag, day in keys:
        cow = TAG_TO_COW.get(tag)
        if cow is None:
            report.setdefault("unmapped_tags_skipped", {}).setdefault("collar_1min", []).append(f"{tag}_{day}")
            continue
        immu = pd.read_csv(immu_files[(tag, day)]) if (tag, day) in immu_files else None
        pres = pd.read_csv(pres_files[(tag, day)], usecols=["timestamp", "pressure_Pa"]) if (tag, day) in pres_files else None
        parts.append(aggregate_collar_minute(immu, pres, cow))
    df = _finish(pd.concat(parts, ignore_index=True), ["cow_id", "ts_utc"], report, "collar_1min")
    write_table(df, out_dir, "collar_1min", "1min", ["cow_id", "ts_utc"],
                {"source_files": len(immu_files) + len(pres_files),
                 "note": "per-minute aggregate of 10 Hz immu/pressure; native rate stays in raw CSV",
                 "immu_cow_days": len(immu_files), "pressure_cow_days": len(pres_files)})


def ingest_behavior(raw_dir: Path, out_dir: Path, report: dict) -> None:
    labels_dir = raw_dir.parent / "behavior_labels" / "individual"  # sibling of main_data/
    files = _per_cow_files(labels_dir, "C*_*.csv")
    if not files:
        report.setdefault("skipped", []).append("behavior")
        return
    df = pd.concat([shape_behavior(pd.read_csv(p), c) for c, p in files], ignore_index=True)
    df = _finish(df, ["cow_id", "ts_utc"], report, "behavior")
    write_table(df, out_dir, "behavior", "1s", ["cow_id", "ts_utc"],
                {"source_files": len(files), "legend": BEHAVIOR_NAMES,
                 "unknown_rows": int((~df["behavior_known"]).sum()),
                 "note": "ground truth, 2023-07-25 only, all 16 cows; code 0 = unknown is kept and flagged, never a class"})


def run(raw_dir: Path, interim_dir: Path, skip_heavy: bool = False) -> dict:
    report: dict = {"stage": "ingest"}
    ingest_simple(raw_dir, interim_dir, report, "milk", shape_milk, "C*.csv", ["cow_id", "ts_utc"], "1D")
    ingest_simple(raw_dir, interim_dir, report, "cbt", shape_cbt, "C*.csv", ["cow_id", "ts_utc"], "1min")
    ingest_simple(raw_dir, interim_dir, report, "ankle", shape_ankle, "C*_*.csv", ["cow_id", "ts_utc"], "1min")
    ingest_thi(raw_dir, interim_dir, report)
    ingest_uwb(raw_dir, interim_dir, report)
    ingest_weather(raw_dir, interim_dir, report)
    ingest_behavior(raw_dir, interim_dir, report)
    if not skip_heavy:
        ingest_collar(raw_dir, interim_dir, report)
    interim_dir.mkdir(parents=True, exist_ok=True)
    (interim_dir / "ingest.report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
