"""Tests for group-aware splitting.

Run from backend-cleaning/:  python3 -m pytest tests/ -q
or without pytest:          python3 tests/test_splits.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cleaning.splits import assert_no_group_leakage, group_split  # noqa: E402


def _frame(n_cows: int = 8, rows_per_cow: int = 5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cow_id": [f"cow{c:02d}" for c in range(n_cows) for _ in range(rows_per_cow)],
            "milk_yield_kg": range(n_cows * rows_per_cow),
        }
    )


def test_no_cow_spans_both_sides():
    train, test = group_split(_frame(), test_frac=0.25, seed=0)
    assert not set(train["cow_id"]) & set(test["cow_id"])
    assert len(train) + len(test) == len(_frame())


def test_deterministic_for_a_seed():
    a, _ = group_split(_frame(), seed=7)
    b, _ = group_split(_frame(), seed=7)
    assert sorted(a["cow_id"].unique()) == sorted(b["cow_id"].unique())


def test_row_order_does_not_change_the_split():
    df = _frame()
    shuffled = df.sample(frac=1.0, random_state=3).reset_index(drop=True)
    _, t1 = group_split(df, seed=1)
    _, t2 = group_split(shuffled, seed=1)
    assert sorted(t1["cow_id"].unique()) == sorted(t2["cow_id"].unique())


def test_uneven_group_sizes_still_split_whole_groups():
    # cow00 contributes far more rows than the rest
    df = pd.concat([_frame(4, 2), pd.DataFrame({"cow_id": ["cow00"] * 50, "milk_yield_kg": 0})])
    train, test = group_split(df, test_frac=0.25, seed=0)
    assert not set(train["cow_id"]) & set(test["cow_id"])


def test_both_sides_non_empty_even_at_extreme_fracs():
    for frac in (0.01, 0.99):
        train, test = group_split(_frame(4, 2), test_frac=frac, seed=0)
        assert len(train) > 0 and len(test) > 0, frac


def test_rejects_bad_input():
    for frac in (0.0, 1.0, -0.5, 2.0):
        try:
            group_split(_frame(), test_frac=frac)
        except ValueError:
            pass
        else:
            raise AssertionError(f"test_frac={frac} should have raised")

    try:
        group_split(_frame(), by="missing_col")
    except KeyError:
        pass
    else:
        raise AssertionError("missing group column should have raised")

    try:
        group_split(pd.DataFrame({"cow_id": ["only_one"], "x": [1]}))
    except ValueError:
        pass
    else:
        raise AssertionError("single group should have raised")

    try:
        group_split(pd.DataFrame({"cow_id": ["a", None], "x": [1, 2]}))
    except ValueError:
        pass
    else:
        raise AssertionError("null group key should have raised")


def test_leakage_assertion_catches_a_bad_split():
    df = _frame()
    assert_no_group_leakage(*group_split(df, seed=0))  # clean split passes

    try:
        assert_no_group_leakage(df, df)  # same cows both sides
    except AssertionError as e:
        assert "leaks repeated measures" in str(e)
    else:
        raise AssertionError("overlapping splits should have raised")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
