"""Group-aware splitting.

The track prompt requires evaluation splits that avoid leakage from repeated
measurements of the same animal. Both Challenge datasets have many rows per
cow, so a row-level random split puts the same animal on both sides of the
split and inflates the score with animal identity instead of signal.

Every role uses `group_split` so the four of us cannot disagree about how the
split was formed. See CONTRACT.md section 2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["group_split", "assert_no_group_leakage"]


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
    if by not in df.columns:
        raise KeyError(
            f"group column {by!r} not in dataframe; columns={list(df.columns)}"
        )
    if not 0.0 < test_frac < 1.0:
        raise ValueError(f"test_frac must be in (0, 1), got {test_frac}")

    if df[by].isna().any():
        n = int(df[by].isna().sum())
        raise ValueError(
            f"{n} row(s) have a null {by!r}. Cleaning drops rows with a missing "
            "key before this point; see CONTRACT.md section 3."
        )

    # sorted() first so the shuffle depends only on the group set, not on the
    # order rows happened to arrive in.
    groups = np.array(sorted(df[by].unique()))
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
