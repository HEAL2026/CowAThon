"""Compare an unsupervised K-means behavior baseline with RandomForest.

Clusters are fit only on the chronological training period. Cluster-to-state
names are assigned from training labels using a one-to-one Hungarian mapping;
the reserved final period is never used to fit clusters or the mapping.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.preprocessing import StandardScaler

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "model" / "data" / "windows_0725.parquet"
OUT = REPO / "model" / "reports" / "kmeans_comparison.json"
CLASSES = np.arange(1, 8)


def metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float | int]:
    return {
        "n_windows": int(len(y)),
        "macro_f1": float(f1_score(y, pred, average="macro", labels=CLASSES, zero_division=0)),
        "accuracy": float(accuracy_score(y, pred)),
        "lying_f1": float(f1_score(y == 7, pred == 7, zero_division=0)),
    }


def main() -> int:
    df = pd.read_parquet(DATA)
    df = df[df["label"].notna()].copy()
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    features = [c for c in df.columns if c not in {"cow_id", "ts_utc", "label", "label_known_frac", "label_name"}]
    cutoff = df["ts_utc"].quantile(0.8)
    train = df["ts_utc"] < cutoff
    test = ~train
    scaler = StandardScaler()
    x_train = scaler.fit_transform(np.nan_to_num(df.loc[train, features].to_numpy(float)))
    x_test = scaler.transform(np.nan_to_num(df.loc[test, features].to_numpy(float)))
    y_train = df.loc[train, "label"].to_numpy(int)
    y_test = df.loc[test, "label"].to_numpy(int)

    km = KMeans(n_clusters=7, n_init=20, random_state=0)
    train_clusters = km.fit_predict(x_train)
    test_clusters = km.predict(x_test)
    contingency = np.zeros((7, 7), dtype=int)
    for cluster, label in zip(train_clusters, y_train):
        contingency[cluster, label - 1] += 1
    cluster_ids, class_ids = linear_sum_assignment(-contingency)
    mapping = {int(cluster): int(label + 1) for cluster, label in zip(cluster_ids, class_ids)}
    km_pred = np.array([mapping.get(int(cluster), 1) for cluster in test_clusters])

    rf = RandomForestClassifier(
        n_estimators=300, min_samples_leaf=3, class_weight="balanced_subsample",
        n_jobs=-1, random_state=0,
    )
    rf.fit(x_train, y_train)
    rf_pred = rf.predict(x_test)
    result = {
        "protocol": "all-cow chronological holdout; final 20% reserved for test",
        "train_period_end_utc": str(cutoff),
        "test_period_start_utc": str(cutoff),
        "test_cows": "all 10 cows represented in the reserved period",
        "features": features,
        "kmeans": {
            **metrics(y_test, km_pred),
            "n_clusters": 7,
            "mapping_cluster_to_class": mapping,
            "train_cluster_class_counts": contingency.tolist(),
        },
        "random_forest": metrics(y_test, rf_pred),
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
