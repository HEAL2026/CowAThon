"""Train and evaluate the behaviour classifier (brief S4).

RandomForest on the window features from features.py, evaluated with
leave-one-cow-out so the score is for an unseen animal, which is the only
honest number for a herd-monitoring tool (CONTRACT section 2: never split on
rows). Writes the fitted model, a per-class F1 table and confusion matrix.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, classification_report, confusion_matrix, f1_score

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend-cleaning"))
from cleaning.ingest import BEHAVIOR_NAMES  # noqa: E402
from cleaning.splits import assert_no_group_leakage, group_split  # noqa: E402

DATA = REPO / "model" / "data"
REPORTS = REPO / "model" / "reports"
CKPT = REPO / "model" / "checkpoints"
META = ["cow_id", "ts_utc", "label", "label_known_frac", "label_name"]
CLASSES = [c for c in sorted(BEHAVIOR_NAMES) if c != 0]
SEED = 0


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in META]


def make_model(n_estimators: int = 300) -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=n_estimators, min_samples_leaf=3, class_weight="balanced_subsample",
        n_jobs=-1, random_state=SEED,
    )


def _aligned_probabilities(clf, X: np.ndarray) -> np.ndarray:
    """Return probabilities in the stable seven-class order."""
    p = clf.predict_proba(X)
    out = np.zeros((len(X), len(CLASSES)))
    for j, c in enumerate(clf.classes_):
        if c in CLASSES:
            out[:, CLASSES.index(c)] = p[:, j]
    return out


def grouped_train_test(
    df: pd.DataFrame,
    test_frac: float = 0.2,
    calibration_frac: float = 0.2,
    seed: int = SEED,
) -> tuple[pd.DataFrame, dict]:
    """Evaluate on cows absent from fitting and probability calibration.

    The split is hierarchical: test cows are selected first; the remaining
    cows are split into fit and calibration groups. Thus no cow contributes
    repeated windows to more than one of fit, calibration, or test.
    """
    fit_cal, test = group_split(df, by="cow_id", test_frac=test_frac, seed=seed)
    fit, calibration = group_split(
        fit_cal, by="cow_id", test_frac=calibration_frac, seed=seed + 1
    )
    assert_no_group_leakage(fit, calibration)
    assert_no_group_leakage(fit, test)
    assert_no_group_leakage(calibration, test)
    feats = feature_columns(df)
    x_fit = np.nan_to_num(fit[feats].to_numpy(dtype=float), nan=0.0)
    x_cal = np.nan_to_num(calibration[feats].to_numpy(dtype=float), nan=0.0)
    x_test = np.nan_to_num(test[feats].to_numpy(dtype=float), nan=0.0)
    y_fit = fit["label"].to_numpy(dtype=int)
    y_cal = calibration["label"].to_numpy(dtype=int)
    y_test = test["label"].to_numpy(dtype=int)
    print(
        f"[grouped] fit={len(fit):,} windows/{len(fit['cow_id'].unique())} cows; "
        f"calibration={len(calibration):,}; test={len(test):,}",
        flush=True,
    )
    base = make_model().fit(x_fit, y_fit)
    print("[grouped] base fit complete; calibrating probabilities", flush=True)
    calibrated = CalibratedClassifierCV(
        estimator=base, method="sigmoid", cv="prefit"
    ).fit(x_cal, y_cal)
    probabilities = _aligned_probabilities(calibrated, x_test)
    pred = np.array(CLASSES)[probabilities.argmax(axis=1)]
    names = [BEHAVIOR_NAMES[c] for c in CLASSES]
    report = classification_report(
        y_test, pred, labels=CLASSES, target_names=names,
        output_dict=True, zero_division=0,
    )
    metrics = {
        "protocol": "grouped_train_calibration_test_by_cow",
        "seed": seed,
        "fit_cows": sorted(map(str, fit["cow_id"].unique())),
        "calibration_cows": sorted(map(str, calibration["cow_id"].unique())),
        "test_cows": sorted(map(str, test["cow_id"].unique())),
        "n_windows": {"fit": len(fit), "calibration": len(calibration), "test": len(test)},
        "macro_f1": float(f1_score(y_test, pred, average="macro", labels=CLASSES, zero_division=0)),
        "accuracy": float((pred == y_test).mean()),
        "per_class": report,
        "confusion": confusion_matrix(y_test, pred, labels=CLASSES).tolist(),
        "class_order": names,
        "calibration": {
            "method": "sigmoid",
            "calibration_cows": sorted(map(str, calibration["cow_id"].unique())),
            "multiclass_brier_mean": float(np.mean([
                brier_score_loss((y_test == c).astype(int), probabilities[:, i])
                for i, c in enumerate(CLASSES)
            ])),
        },
        "features": feats,
    }
    out = test[["cow_id", "ts_utc", "label", "label_name"]].copy()
    out["pred"] = pred
    out["pred_name"] = pd.Series(pred).map(BEHAVIOR_NAMES).to_numpy()
    out["pred_prob_calibrated"] = probabilities.max(axis=1)
    return out, metrics


def leave_one_cow_out(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Returns per-window out-of-fold predictions and a metrics dict."""
    feats = feature_columns(df)
    X, y, cows = df[feats].to_numpy(dtype=float), df["label"].to_numpy(dtype=int), df["cow_id"].to_numpy()
    X = np.nan_to_num(X, nan=0.0)
    pred = np.zeros_like(y)
    proba = np.zeros((len(y), len(CLASSES)))
    per_cow = {}
    for cow in sorted(set(cows)):
        print(
            f"[loco] fitting held-out cow {cow} "
            f"({int(np.sum(cows == cow)):,} test windows)",
            flush=True,
        )
        te = cows == cow
        clf = make_model().fit(X[~te], y[~te])
        p = clf.predict_proba(X[te])
        # align columns to CLASSES (a held-out fold may lack a class)
        pm = np.zeros((te.sum(), len(CLASSES)))
        for j, c in enumerate(clf.classes_):
            pm[:, CLASSES.index(c)] = p[:, j]
        proba[te] = pm
        pred[te] = np.array(CLASSES)[pm.argmax(axis=1)]
        per_cow[cow] = {"n": int(te.sum()), "macro_f1": float(f1_score(y[te], pred[te], average="macro", labels=CLASSES, zero_division=0)),
                        "accuracy": float((pred[te] == y[te]).mean())}
    names = [BEHAVIOR_NAMES[c] for c in CLASSES]
    rep = classification_report(y, pred, labels=CLASSES, target_names=names, output_dict=True, zero_division=0)
    cm = confusion_matrix(y, pred, labels=CLASSES)
    out = df[["cow_id", "ts_utc", "label", "label_name"]].copy()
    out["pred"] = pred
    out["pred_name"] = pd.Series(pred).map(BEHAVIOR_NAMES).to_numpy()
    out["pred_prob"] = proba.max(axis=1)
    metrics = {"protocol": f"leave_one_cow_out (n={len(per_cow)})", "n_windows": int(len(y)),
               "macro_f1": float(f1_score(y, pred, average="macro", labels=CLASSES, zero_division=0)),
               "accuracy": float((pred == y).mean()), "per_class": rep, "confusion": cm.tolist(),
               "class_order": names, "per_cow": per_cow, "features": feats}
    return out, metrics


def write_report(metrics: dict, path: Path) -> None:
    names = metrics["class_order"]
    lines = [
        "# Behaviour classifier — evaluation", "",
        f"Protocol: **{metrics['protocol']}**, {metrics['n_windows']:,} labelled 10 s windows, 10 cows, 2023‑07‑25.",
        f"RandomForest (300 trees, balanced subsample), {len(metrics['features'])} IMU features. Seed {SEED}.", "",
        f"**Macro F1 {metrics['macro_f1']:.3f} · accuracy {metrics['accuracy']:.3f}** on unseen animals.", "",
        "## Per class", "", "| class | precision | recall | F1 | support |", "|---|---|---|---|---|",
    ]
    for n in names:
        r = metrics["per_class"][n]
        lines.append(f"| {n} | {r['precision']:.3f} | {r['recall']:.3f} | {r['f1-score']:.3f} | {int(r['support'])} |")
    lines += ["", "## Confusion matrix (rows = true, cols = predicted)", "", "| | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for n, row in zip(names, metrics["confusion"]):
        lines.append(f"| **{n}** | " + " | ".join(str(v) for v in row) + " |")
    lines += ["", "## Per cow (held out)", "", "| cow | windows | macro F1 | accuracy |", "|---|---|---|---|"]
    for c, m in metrics["per_cow"].items():
        lines.append(f"| {c} | {m['n']} | {m['macro_f1']:.3f} | {m['accuracy']:.3f} |")
    lines += ["", "## Reading it", "",
              "- Lying vs not‑lying is the decision the health index depends on most; see its row.",
              "- `licking`, `drinking`, `walking` have < 1.5 % of windows each; low F1 there is expected and is why the",
              "  pipeline maps them to `other` for daily features (brief S4).",
              "- Lying from the ankle sensor overrides the classifier wherever they disagree (brief S4).", ""]
    path.write_text("\n".join(lines))


def append_grouped_report(metrics: dict, path: Path) -> None:
    """Document the independent grouped holdout beside the LOCO report."""
    names = metrics["class_order"]
    lines = [
        "",
        "## Independent grouped train/calibration/test benchmark",
        "",
        "This is a fixed cow-disjoint holdout, separate from the primary LOCO score.",
        "Fit, calibration, and test windows come from disjoint cows; no rows are split",
        "independently. The classifier uses neck IMU only. The ankle signal remains a",
        "downstream production override and is not used in this benchmark.",
        "",
        f"- Fit cows: {', '.join(metrics['fit_cows'])}",
        f"- Calibration cows: {', '.join(metrics['calibration_cows'])}",
        f"- Test cows: {', '.join(metrics['test_cows'])}",
        f"- Calibrated macro F1: **{metrics['macro_f1']:.3f}**",
        f"- Calibrated accuracy: **{metrics['accuracy']:.3f}**",
        f"- Mean one-vs-rest Brier score: **{metrics['calibration']['multiclass_brier_mean']:.4f}**",
        "",
        "The seven-state report is intentional: lying, standing, walking, feed-up,",
        "feed-down, licking, and drinking are all retained so daily state patterns",
        "can be compared with each cow's baseline. The health pipeline should allow",
        "normal cow-to-cow and day-to-day variation rather than treating one state",
        "as universally abnormal.",
        "",
        "Probability calibration uses cows outside the fit and test groups. It makes",
        "`pred_prob_calibrated` interpretable as a confidence signal, but does not",
        "turn a behavior state into a clinical diagnosis.",
    ]
    path.write_text(path.read_text() + "\n".join(lines) + "\n")


def main() -> int:
    t0 = time.time()
    df = pd.read_parquet(DATA / "windows_0725.parquet")
    lab = df[df["label"].notna()].reset_index(drop=True)
    print(f"[training] loaded {len(lab):,} labelled windows from {lab['cow_id'].nunique()} cows", flush=True)
    preds, metrics = leave_one_cow_out(lab)
    grouped_preds, grouped_metrics = grouped_train_test(lab)
    REPORTS.mkdir(exist_ok=True); CKPT.mkdir(exist_ok=True); DATA.mkdir(exist_ok=True)
    preds.to_parquet(DATA / "loco_predictions_0725.parquet", index=False)
    grouped_preds.to_parquet(DATA / "grouped_test_predictions_0725.parquet", index=False)
    write_report(metrics, REPORTS / "behavior_eval.md")
    append_grouped_report(grouped_metrics, REPORTS / "behavior_eval.md")
    metrics["grouped_train_calibration_test"] = {
        k: v for k, v in grouped_metrics.items() if k != "features"
    }
    (REPORTS / "behavior_eval.json").write_text(json.dumps({k: v for k, v in metrics.items() if k != "features"}, indent=2))
    # final model on all labelled windows
    import joblib
    feats = feature_columns(lab)
    clf = make_model().fit(np.nan_to_num(lab[feats].to_numpy(dtype=float)), lab["label"].to_numpy(dtype=int))
    joblib.dump({"model": clf, "features": feats, "classes": CLASSES, "names": BEHAVIOR_NAMES, "window_s": 10,
                 "trained_on": "MMCows 2023-07-25, 10 cows, LOCO macro_f1=%.3f" % metrics["macro_f1"]}, CKPT / "behavior_rf.joblib")
    print(f"LOCO macro F1 {metrics['macro_f1']:.3f}  acc {metrics['accuracy']:.3f}  ({time.time()-t0:.0f}s)")
    for n in metrics["class_order"]:
        print(f"  {n:10s} F1 {metrics['per_class'][n]['f1-score']:.3f}  n={int(metrics['per_class'][n]['support'])}")
    print(f"-> {REPORTS / 'behavior_eval.md'}, {CKPT / 'behavior_rf.joblib'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
