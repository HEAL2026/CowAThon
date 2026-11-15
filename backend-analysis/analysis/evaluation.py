"""Group-aware cross-validation engine enforcing zero animal leakage.

Groups strictly on `cow_id` so all observations for any single animal reside
wholly in either train or test, never across both.
Consumes the shared canonical split functions from `cleaning.splits`.
"""

from __future__ import annotations
import sys
from pathlib import Path
from typing import Callable, Any
import numpy as np
import pandas as pd

# Add repo root to path for importing cleaning.splits
REPO_ROOT = Path(__file__).resolve().parents[2]
CLEANING_PATH = REPO_ROOT / "backend-cleaning"
if str(CLEANING_PATH) not in sys.path:
    sys.path.insert(0, str(CLEANING_PATH))

from cleaning.splits import group_split, group_kfold, assert_no_group_leakage

__all__ = [
    "group_split",
    "group_kfold",
    "assert_no_group_leakage",
    "run_group_cross_validation",
]


def run_group_cross_validation(
    df: pd.DataFrame,
    model_fn: Callable[[pd.DataFrame], Any],
    eval_metric_fn: Callable[[Any, pd.DataFrame], float],
    by: str = "cow_id",
    n_splits: int = 5,
    seed: int = 0,
) -> dict[str, float]:
    """Execute cross-validation and return mean and std of evaluation metrics.

    Guarantees:
    - Every unique animal is entirely in train or entirely in val.
    - Verified by `assert_no_group_leakage` on each fold.
    """
    scores: list[float] = []

    for train_df, val_df in group_kfold(df, by=by, n_splits=n_splits, seed=seed):
        assert_no_group_leakage(train_df, val_df, by=by)
        model = model_fn(train_df)
        score = eval_metric_fn(model, val_df)
        scores.append(score)

    return {
        "mean": float(np.mean(scores)),
        "std": float(np.std(scores)),
        "scores": [float(s) for s in scores],
    }
