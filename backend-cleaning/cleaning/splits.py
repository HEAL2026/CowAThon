"""Group-aware splitting.

The track prompt requires evaluation splits that avoid leakage from repeated
measurements of the same animal. Both Challenge datasets have many rows per
cow, so a row-level random split puts the same animal on both sides of the
split and inflates the score with animal identity instead of signal.

Every role uses `group_split` (single holdout) or `group_kfold` (cross-
validation) so the four of us cannot disagree about how the split was formed.
See CONTRACT.md section 2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["group_split", "group_kfold", "assert_no_group_leakage"]


def group_split(
    df: pd.DataFrame,
    by: str = "cow_id",
    test_frac: float = 0.25,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split `df` so that every distinct value of `by` is wholly in one side.

    Splits on whole groups, not rows: all records for one cow land entirely in
    train or entirely in test. `test_frac` is the target fraction of *groups*,
    so the realised row fraction differs when animals contribute unequal row
    counts -- that is expected, and preferable to breaking a group.

    Deterministic for a given (group set, test_frac, seed): groups are sorted
    before shuffling, so row order in `df` cannot change the outcome.

    Raises:
        KeyError: `by` is not a column.
        ValueError: `test_frac` is outside (0, 1), or there are too few groups
            to form a non-empty split on both sides.
    """
    if not 0.0 < test_frac < 1.0:
        raise ValueError(f"test_frac must be in (0, 1), got {test_frac}")

    groups = _group_values(df, by)
    if groups.size < 2:
        raise ValueError(
            f"need >= 2 distinct {by!r} values to split without leakage, "
            f"got {groups.size}"
        )

    n_test = int(round(test_frac * groups.size))
    # never let rounding empty either side
    n_test = min(max(n_test, 1), groups.size - 1)

    shuffled = np.random.default_rng(seed).permutation(groups)
    test_groups = set(shuffled[:n_test])

    in_test = df[by].isin(test_groups)
    return df.loc[~in_test].copy(), df.loc[in_test].copy()


def _group_values(df: pd.DataFrame, by: str) -> np.ndarray:
    """Validate the group column and return its distinct values, sorted."""
    if by not in df.columns:
        raise KeyError(
            f"group column {by!r} not in dataframe; columns={list(df.columns)}"
        )
    if df[by].isna().any():
        n = int(df[by].isna().sum())
        raise ValueError(
            f"{n} row(s) have a null {by!r}. Cleaning drops rows with a missing "
            "key before this point; see CONTRACT.md section 3."
        )
    # sorted() first so any shuffle depends only on the group set, not on the
    # order rows happened to arrive in.
    return np.array(sorted(df[by].unique()))


def group_kfold(
    df: pd.DataFrame,
    by: str = "cow_id",
    n_splits: int = 5,
    seed: int = 0,
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Return `n_splits` (train, val) pairs where every `by` value is held out
    exactly once.

    Group-level k-fold: all records for one cow land in exactly one validation
    fold, and in the training side of every other fold. Folds hold an equal
    number of *groups* (plus or minus one), not an equal number of rows -- as
    with `group_split`, that is preferable to breaking a group.

    Deterministic for a given (group set, n_splits, seed), independent of row
    order. `backend-analysis/` and `model/` call this with the same arguments
    so their cross-validated numbers are computed on identical animal folds.

    Every fold is checked with `assert_no_group_leakage` before it is returned.

    Raises:
        KeyError: `by` is not a column.
        ValueError: `n_splits` < 2, a null group key, or fewer distinct groups
            than folds.
    """
    if n_splits < 2:
        raise ValueError(f"n_splits must be >= 2, got {n_splits}")

    groups = _group_values(df, by)
    if groups.size < n_splits:
        raise ValueError(
            f"need >= {n_splits} distinct {by!r} values for {n_splits} folds "
            f"without leakage, got {groups.size}"
        )

    shuffled = np.random.default_rng(seed).permutation(groups)
    folds: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    for val_groups in np.array_split(shuffled, n_splits):
        in_val = df[by].isin(set(val_groups))
        train, val = df.loc[~in_val].copy(), df.loc[in_val].copy()
        assert_no_group_leakage(train, val, by=by)
        folds.append((train, val))
    return folds


def assert_no_group_leakage(
    train: pd.DataFrame,
    test: pd.DataFrame,
    by: str = "cow_id",
) -> None:
    """Raise if any `by` value appears in both splits.

    Cheap enough to call in analysis code right before training. Catches the
    case where a split was formed by hand, or where a merge reintroduced rows
    for a held-out animal.
    """
    overlap = set(train[by]) & set(test[by])
    if overlap:
        shown = sorted(map(str, overlap))[:10]
        raise AssertionError(
            f"{len(overlap)} {by!r} value(s) in both train and test -- this "
            f"leaks repeated measures of the same animal: {shown}"
        )
