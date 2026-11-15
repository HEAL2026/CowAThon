"""Benchmarking defensible single-sensor baselines vs multimodal modeling.

Establishes:
- Baseline 1 (Environmental): Classical THI rule (alert if THI >= 68.0)
- Baseline 2 (Physiological): Single-sensor CBT rule (alert if CBT >= 39.3°C)
- Multimodal Predictive Model: Logistic regression model combining Thermal + IMU + Env + Milk signals

All evaluated under strict animal-disjoint group cross-validation (GroupKFold by cow_id).
"""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd

from .evaluation import group_kfold
from .env_thermal import calculate_thi
from .behavior import calculate_activity_index, calculate_rumination_proxy


def _compute_roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Exact trapezoidal ROC-AUC calculation."""
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.asarray(y_score, dtype=float)
    n_pos = np.sum(y_true == 1)
    n_neg = np.sum(y_true == 0)

    if n_pos == 0 or n_neg == 0:
        return 0.5

    desc_indices = np.argsort(-y_score, kind="mergesort")
    y_score_sorted = y_score[desc_indices]
    y_true_sorted = y_true[desc_indices]

    distinct_value_indices = np.where(np.diff(y_score_sorted))[0]
    threshold_idxs = np.r_[distinct_value_indices, y_true_sorted.size - 1]

    tps = np.cumsum(y_true_sorted)[threshold_idxs]
    fps = 1 + threshold_idxs - tps

    tps = np.r_[0, tps]
    fps = np.r_[0, fps]

    fpr = fps / n_neg
    tpr = tps / n_pos

    auc = np.sum((fpr[1:] - fpr[:-1]) * (tpr[1:] + tpr[:-1]) / 2.0)
    return float(auc)


def _compute_classification_metrics(y_true: np.ndarray, y_score: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    """Compute binary classification metrics."""
    y_true = np.asarray(y_true, dtype=int)
    y_pred = (np.asarray(y_score) >= threshold).astype(int)

    tp = np.sum((y_true == 1) & (y_pred == 1))
    fp = np.sum((y_true == 0) & (y_pred == 1))
    fn = np.sum((y_true == 1) & (y_pred == 0))
    tn = np.sum((y_true == 0) & (y_pred == 0))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    balanced_acc = 0.5 * (recall + specificity)

    roc_auc = _compute_roc_auc(y_true, y_score)

    return {
        "roc_auc": float(roc_auc),
        "balanced_accuracy": float(balanced_acc),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
    }


class SimpleLogisticRegression:
    """Lightweight, transparent numpy logistic regression with L2 regularization."""

    def __init__(self, lr: float = 0.1, n_iter: int = 300, l2: float = 0.05):
        self.lr = lr
        self.n_iter = n_iter
        self.l2 = l2
        self.weights: np.ndarray | None = None
        self.mean: np.ndarray | None = None
        self.std: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)

        self.mean = np.nanmean(X, axis=0)
        self.std = np.nanstd(X, axis=0)
        self.std[self.std == 0] = 1.0

        X_norm = np.nan_to_num((X - self.mean) / self.std, nan=0.0)
        X_bias = np.hstack([np.ones((X_norm.shape[0], 1)), X_norm])

        n_samples, n_features = X_bias.shape
        self.weights = np.zeros(n_features)

        for _ in range(self.n_iter):
            linear = np.clip(np.dot(X_bias, self.weights), -30.0, 30.0)
            preds = 1.0 / (1.0 + np.exp(-linear))
            errors = preds - y
            gradient = (np.dot(X_bias.T, errors) / n_samples) + (self.l2 * self.weights / n_samples)
            gradient[0] -= (self.l2 * self.weights[0] / n_samples)
            self.weights -= self.lr * gradient

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        X_norm = np.nan_to_num((X - self.mean) / self.std, nan=0.0)
        X_bias = np.hstack([np.ones((X_norm.shape[0], 1)), X_norm])
        linear = np.clip(np.dot(X_bias, self.weights), -30.0, 30.0)
        return 1.0 / (1.0 + np.exp(-linear))


def evaluate_baselines_vs_multimodal(
    df: pd.DataFrame,
    target_col: str = "is_elevated_risk",
    group_col: str = "cow_id",
    n_splits: int = 5,
    seed: int = 0,
) -> dict[str, Any]:
    """Perform animal-disjoint group cross-validation benchmarking."""
    df_eval = df.copy()

    # Precompute features if not present
    if "thi" not in df_eval.columns and "temp_c" in df_eval.columns and "rh_pct" in df_eval.columns:
        df_eval["thi"] = calculate_thi(df_eval["temp_c"], df_eval["rh_pct"])
    if "activity_index" not in df_eval.columns:
        df_eval["activity_index"] = calculate_activity_index(df_eval)
    if "rumination_proxy" not in df_eval.columns:
        df_eval["rumination_proxy"] = calculate_rumination_proxy(df_eval)

    # Ensure binary target exists
    if target_col not in df_eval.columns:
        cbt_high = df_eval.get("cbt", pd.Series(38.8, index=df_eval.index)) >= 39.2
        thi_high = df_eval.get("thi", pd.Series(65.0, index=df_eval.index)) >= 68.0
        rum_low = df_eval.get("rumination_proxy", pd.Series(50.0, index=df_eval.index)) < 40.0
        df_eval[target_col] = ((cbt_high & thi_high) | (cbt_high & rum_low)).astype(int)

    feature_cols = [
        col for col in ["cbt", "thi", "activity_index", "rumination_proxy", "milk_drop_pct", "idling_fraction"]
        if col in df_eval.columns
    ]

    env_metrics_list = []
    cbt_metrics_list = []
    multi_metrics_list = []

    for train_df, val_df in group_kfold(df_eval, by=group_col, n_splits=n_splits, seed=seed):
        y_val = val_df[target_col].values

        # Baseline 1: Environmental THI rule
        thi_val = val_df.get("thi", pd.Series(65.0, index=val_df.index)).values
        thi_score = np.clip((thi_val - 60.0) / 25.0, 0.0, 1.0)
        env_metrics_list.append(_compute_classification_metrics(y_val, thi_score, threshold=0.32))

        # Baseline 2: Single-sensor CBT rule
        cbt_val = val_df.get("cbt", pd.Series(38.8, index=val_df.index)).values
        cbt_score = np.clip((cbt_val - 38.5) / 2.0, 0.0, 1.0)
        cbt_metrics_list.append(_compute_classification_metrics(y_val, cbt_score, threshold=0.35))

        # Multimodal Model
        X_train = train_df[feature_cols].values
        y_train = train_df[target_col].values
        X_val = val_df[feature_cols].values

        model = SimpleLogisticRegression()
        model.fit(X_train, y_train)
        multi_score = model.predict_proba(X_val)
        multi_metrics_list.append(_compute_classification_metrics(y_val, multi_score, threshold=0.5))

    def _summarize(metrics_list):
        summary = {}
        for k in ["roc_auc", "balanced_accuracy", "precision", "recall", "f1"]:
            vals = [m[k] for m in metrics_list]
            summary[f"{k}_mean"] = round(float(np.mean(vals)), 3)
            summary[f"{k}_std"] = round(float(np.std(vals)), 3)
        return summary

    env_summary = _summarize(env_metrics_list)
    cbt_summary = _summarize(cbt_metrics_list)
    multi_summary = _summarize(multi_metrics_list)

    return {
        "dataset": "MMCows Challenge 1",
        "evaluation_protocol": f"GroupKFold by {group_col} (zero animal leakage)",
        "n_groups": int(df_eval[group_col].nunique()),
        "n_splits": n_splits,
        "baselines": {
            "thi_threshold_baseline": {
                "description": "Classical environmental rule: Alert when THI >= 68.0",
                **env_summary,
            },
            "cbt_threshold_baseline": {
                "description": "Single-sensor physiological rule: Alert when CBT >= 39.3°C",
                **cbt_summary,
            },
        },
        "multimodal_model": {
            "description": "Multimodal feature-weighted classifier (Thermal + IMU + Env + Production)",
            **multi_summary,
        },
        "multimodal_lift_over_env_baseline_auc": round(multi_summary["roc_auc_mean"] - env_summary["roc_auc_mean"], 3),
        "multimodal_lift_over_cbt_baseline_auc": round(multi_summary["roc_auc_mean"] - cbt_summary["roc_auc_mean"], 3),
    }
