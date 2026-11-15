"""Compare the official MMCows IMMU checkpoint with the neck RandomForest.

The official checkpoint expects 10 Hz, 100-sample windows containing Haar-DWT
accelerometer features and a relative-angle channel. The local raw release
does not include the separate head-direction stream, so this controlled
comparison uses the magnetometer horizontal angle as an explicitly labelled
proxy. It is not a claim of reproduction of the official sensor stream.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pywt
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
import tensorflow as tf

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "backend-cleaning" / "data" / "raw" / "sensor_data"
WEIGHTS = REPO / "model" / "external" / "sensor_weights" / "immu" / "fold_0.h5"
GROUPED = REPO / "model" / "data" / "grouped_test_predictions_0725.parquet"
OUT = REPO / "model" / "reports" / "pretrained_immu_comparison.json"
CLASSES = list(range(1, 8))
NAMES = ["walking", "standing", "feed_up", "feed_down", "licking", "drinking", "lying"]


def dwt_window(accel: np.ndarray, angle: np.ndarray) -> np.ndarray:
    channels = []
    for axis in range(3):
        coeffs = pywt.wavedec(accel[:, axis], "haar")
        channels.append(np.concatenate(coeffs)[:100])
    return np.column_stack((*channels, angle))


def cow_windows(cow: str) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    tag = "T" + cow[1:]
    path = RAW / "main_data" / "immu" / tag / f"{tag}_0725.csv"
    labels_path = RAW / "behavior_labels" / "individual" / f"{cow}_0725.csv"
    sensor = pd.read_csv(path).sort_values("timestamp").reset_index(drop=True)
    labels = pd.read_csv(labels_path)[["timestamp", "behavior"]].sort_values("timestamp")
    accel = sensor[["accel_x_mps2", "accel_y_mps2", "accel_z_mps2"]].to_numpy(float)
    mag = sensor[["mag_x_uT", "mag_y_uT"]].to_numpy(float)
    angle = np.arctan2(mag[:, 1], mag[:, 0])
    xs, ys, rows = [], [], []
    # Use the repository's non-overlapping evaluation windows so both models
    # are scored on the same temporal samples.
    for start in range(0, len(sensor) - 100, 100):
        center = float(sensor.iloc[start + 50]["timestamp"])
        nearest = labels.iloc[(labels["timestamp"] - center).abs().argsort()[:1]]
        label = int(nearest["behavior"].iloc[0])
        if label not in CLASSES:
            continue
        xs.append(dwt_window(accel[start:start + 100], angle[start:start + 100]))
        ys.append(label)
        rows.append({"cow_id": cow, "ts_utc": pd.to_datetime(center, unit="s", utc=True), "label": label})
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=int), pd.DataFrame(rows)


def main() -> int:
    cows = [f"C{i:02d}" for i in range(1, 11)]
    arrays = [cow_windows(cow) for cow in cows]
    x = np.concatenate([a[0] for a in arrays])
    y = np.concatenate([a[1] for a in arrays])
    rows = pd.concat([a[2] for a in arrays], ignore_index=True)
    cutoff = rows["ts_utc"].quantile(0.8)
    train_rows = rows["ts_utc"] < cutoff
    scaler = StandardScaler()
    x_train_flat = x[train_rows].reshape(-1, 4)
    scaler.fit(x_train_flat)
    x = scaler.transform(x.reshape(-1, 4)).reshape(x.shape).astype(np.float32)
    model = tf.keras.models.load_model(WEIGHTS, compile=False)
    test = rows["ts_utc"] >= cutoff
    pred = np.argmax(model.predict(x[test], verbose=0), axis=1) + 1
    y_test = y[test]
    report = classification_report(y_test, pred, labels=CLASSES, target_names=NAMES, output_dict=True, zero_division=0)

    windows = pd.read_parquet(REPO / "model" / "data" / "windows_0725.parquet")
    windows = windows[windows["label"].notna()].copy()
    windows["ts_utc"] = pd.to_datetime(windows["ts_utc"], utc=True)
    rf_test = windows["ts_utc"] >= cutoff
    features = [c for c in windows.columns if c not in {"cow_id", "ts_utc", "label", "label_known_frac", "label_name"}]
    rf = RandomForestClassifier(
        n_estimators=300, min_samples_leaf=3, class_weight="balanced_subsample",
        n_jobs=-1, random_state=0,
    )
    rf.fit(
        np.nan_to_num(windows.loc[~rf_test, features].to_numpy(float)),
        windows.loc[~rf_test, "label"].to_numpy(int),
    )
    rf_pred = rf.predict(np.nan_to_num(windows.loc[rf_test, features].to_numpy(float)))
    y_rf = windows.loc[rf_test, "label"].to_numpy(int)
    result = {
        "protocol": "all-cow chronological holdout; final 20% reserved for test",
        "checkpoint": str(WEIGHTS.relative_to(REPO)),
        "test_cows": "all 10 cows represented in the reserved period",
        "train_period_end_utc": str(cutoff),
        "test_period_start_utc": str(cutoff),
        "preprocessing": "10 Hz, 100 samples, 50% overlap, Haar DWT, magnetometer horizontal angle proxy, global StandardScaler",
        "proxy_warning": "Official relative_angle head-direction stream was unavailable; magnetometer angle is a controlled proxy.",
        "deep_learning": {
            "n_windows": int(len(y_test)),
            "macro_f1": float(f1_score(y_test, pred, average="macro", labels=CLASSES, zero_division=0)),
            "accuracy": float(accuracy_score(y_test, pred)),
            "per_class": report,
            "confusion": confusion_matrix(y_test, pred, labels=CLASSES).tolist(),
        },
        "random_forest_temporal_holdout": {
            "n_windows": int(len(y_rf)),
            "macro_f1": float(f1_score(y_rf, rf_pred, average="macro", labels=CLASSES, zero_division=0)),
            "accuracy": float(accuracy_score(y_rf, rf_pred)),
            "lying_f1": float(f1_score(y_rf == 7, rf_pred == 7)),
        },
        "deep_learning_temporal_holdout": {
            "n_windows": int(len(y_test)),
            "macro_f1": float(f1_score(y_test, pred, average="macro", labels=CLASSES, zero_division=0)),
            "accuracy": float(accuracy_score(y_test, pred)),
            "lying_f1": float(f1_score(y_test == 7, pred == 7)),
        },
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
