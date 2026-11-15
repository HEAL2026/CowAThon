"""Window the 10 Hz neck IMU and compute per-window features (brief S4).

Windows are fixed-length, non-overlapping, aligned to whole seconds so each
window maps onto the 1 s ground-truth labels. A window's label is the
majority known label over its seconds; windows with < `min_known_frac`
labelled seconds are dropped from training (kept for inference).

Features per window (accel xyz m/s^2, mag xyz uT):
  per-axis mean/std/min/max; |a| mean/std; ODBA, VeDBA; pitch/roll from the
  gravity estimate; dominant FFT frequency + spectral energy of |a|;
  heading (yaw) mean + circular std from the magnetometer; delta-heading.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend-cleaning"))
from cleaning.locate import INTERIM_DIR  # noqa: E402
from cleaning.ingest import TAG_TO_COW, BEHAVIOR_NAMES  # noqa: E402

RAW_IMMU = REPO / "backend-cleaning" / "data" / "raw" / "sensor_data" / "main_data" / "immu"
WINDOW_S = 10
HZ = 10
ACC = ["accel_x_mps2", "accel_y_mps2", "accel_z_mps2"]
MAG = ["mag_x_uT", "mag_y_uT", "mag_z_uT"]


def _circ_std(theta: np.ndarray) -> float:
    r = np.hypot(np.nanmean(np.cos(theta)), np.nanmean(np.sin(theta)))
    return float(np.sqrt(-2.0 * np.log(max(r, 1e-12))))


def window_features(a: np.ndarray, m: np.ndarray, hz: int = HZ) -> dict:
    """a, m: (n, 3) arrays for one window. NaNs tolerated (nan-aware stats)."""
    f: dict = {}
    for i, ax in enumerate("xyz"):
        col = a[:, i]
        f[f"a{ax}_mean"], f[f"a{ax}_std"] = np.nanmean(col), np.nanstd(col)
        f[f"a{ax}_min"], f[f"a{ax}_max"] = np.nanmin(col), np.nanmax(col)
    mag = np.sqrt(np.nansum(a ** 2, axis=1))
    f["amag_mean"], f["amag_std"] = np.nanmean(mag), np.nanstd(mag)
    # dynamic body acceleration: remove the per-axis running gravity (window mean)
    dyn = a - np.nanmean(a, axis=0)
    f["odba"] = float(np.nanmean(np.nansum(np.abs(dyn), axis=1)))
    f["vedba"] = float(np.nanmean(np.sqrt(np.nansum(dyn ** 2, axis=1))))
    g = np.nanmean(a, axis=0)
    gn = np.linalg.norm(g) or 1.0
    f["pitch"] = float(np.arctan2(g[0], np.hypot(g[1], g[2])))
    f["roll"] = float(np.arctan2(g[1], g[2]))
    f["g_norm"] = float(gn)
    # spectrum of |a| (detrended)
    s = mag - np.nanmean(mag)
    s = np.nan_to_num(s)
    if len(s) >= 4:
        spec = np.abs(np.fft.rfft(s)) ** 2
        freqs = np.fft.rfftfreq(len(s), d=1.0 / hz)
        spec[0] = 0.0
        f["fft_dom_hz"] = float(freqs[int(np.argmax(spec))])
        f["fft_energy"] = float(spec.sum() / len(s))
        band = (freqs >= 0.5) & (freqs <= 2.5)
        f["fft_band_0p5_2p5"] = float(spec[band].sum() / max(spec.sum(), 1e-12))
    else:
        f["fft_dom_hz"] = f["fft_energy"] = f["fft_band_0p5_2p5"] = np.nan
    # heading from the magnetometer in the horizontal plane
    yaw = np.arctan2(m[:, 1], m[:, 0])
    f["yaw_mean"] = float(np.arctan2(np.nanmean(np.sin(yaw)), np.nanmean(np.cos(yaw))))
    f["yaw_cstd"] = _circ_std(yaw)
    dyaw = np.angle(np.exp(1j * np.diff(yaw)))
    f["dyaw_abs_mean"] = float(np.nanmean(np.abs(dyaw))) if len(dyaw) else np.nan
    f["mmag_mean"] = float(np.nanmean(np.sqrt(np.nansum(m ** 2, axis=1))))
    f["n_samples"] = int(np.isfinite(a).all(axis=1).sum())
    return f


def windows_for_cow_day(tag: str, day: str, labels: pd.DataFrame | None, window_s: int = WINDOW_S,
                        min_known_frac: float = 0.8) -> pd.DataFrame:
    """One row per window: cow_id, ts_utc (window start), features, label (code) or NA."""
    path = RAW_IMMU / tag / f"{tag}_{day}.csv"
    im = pd.read_csv(path)
    im["sec"] = np.floor(im["timestamp"].to_numpy()).astype("int64")
    w0 = (im["sec"].min() // window_s) * window_s
    im["win"] = (im["sec"] - w0) // window_s
    cow = TAG_TO_COW[tag]

    lab_by_sec = None
    if labels is not None and len(labels):
        l = labels[labels["cow_id"] == cow]
        lab_by_sec = pd.Series(l["behavior"].to_numpy(), index=(l["ts_utc"].astype("int64") // 10**9).to_numpy())

    rows = []
    for win, g in im.groupby("win", sort=True):
        a = g[ACC].to_numpy(dtype=float)
        m = g[MAG].to_numpy(dtype=float)
        if np.isfinite(a).all(axis=1).sum() < 0.5 * window_s * HZ:
            continue  # mostly-missing window: no feature row
        f = window_features(a, m)
        start = int(w0 + win * window_s)
        f["cow_id"], f["ts_utc"] = cow, pd.Timestamp(start, unit="s", tz="UTC")
        label, known_frac = pd.NA, 0.0
        if lab_by_sec is not None:
            secs = lab_by_sec.reindex(range(start, start + window_s))
            known = secs[(secs.notna()) & (secs != 0)]
            known_frac = len(known) / window_s
            if known_frac >= min_known_frac:
                label = int(known.mode().iloc[0])
        f["label"], f["label_known_frac"] = label, known_frac
        rows.append(f)
    out = pd.DataFrame(rows)
    if len(out):
        out["label"] = out["label"].astype("Int8")
        out["label_name"] = out["label"].map(BEHAVIOR_NAMES).astype("string")
    return out


def build_labelled_day(day: str = "0725", tags: list[str] | None = None) -> pd.DataFrame:
    labels = pd.read_parquet(INTERIM_DIR / "behavior.parquet")
    tags = tags or sorted(TAG_TO_COW)
    return pd.concat([windows_for_cow_day(t, day, labels) for t in tags], ignore_index=True)


if __name__ == "__main__":
    import time
    t0 = time.time()
    df = build_labelled_day()
    out = REPO / "model" / "data" / "windows_0725.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    lab = df[df["label"].notna()]
    print(f"{len(df)} windows, {len(lab)} labelled ({len(lab)/len(df):.1%}), {df['cow_id'].nunique()} cows, {time.time()-t0:.0f}s -> {out}")
    print(lab["label_name"].value_counts().to_dict())
