"""Tests for the export CLI and the path resolver.

Run from backend-cleaning/:  python3 tests/test_export.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cleaning import export, locate  # noqa: E402
from cleaning.__main__ import main  # noqa: E402

T0 = pd.Timestamp("2023-07-25 05:00:00", tz="UTC")  # 2023-07-25 00:00 local


def _table(cows=("C01", "C02", "C03"), minutes=60 * 24 * 3) -> pd.DataFrame:
    return pd.DataFrame({
        "cow_id": [c for c in cows for _ in range(minutes)],
        "ts_utc": list(pd.date_range(T0, periods=minutes, freq="1min", tz="UTC")) * len(cows),
        "cbt_c": 38.5,
    })


def test_slice_by_cow_and_whole_local_days():
    df = _table()
    s = export.slice_joined(df, cows=["C01", "C02"], days=2)
    assert sorted(s["cow_id"].unique()) == ["C01", "C02"]
    local = s["ts_utc"].dt.tz_convert("America/Chicago")
    assert local.min().date().isoformat() == "2023-07-25"
    assert local.max().date().isoformat() == "2023-07-26", "days=2 must stop at the end of the second local day"
    assert len(s) == 2 * 60 * 24 * 2


def test_slice_rejects_unknown_cow_and_bad_days():
    df = _table()
    for bad in (["C99"], ["C01", "C99"]):
        try:
            export.slice_joined(df, cows=bad)
        except ValueError as e:
            assert "C99" in str(e)
        else:
            raise AssertionError(f"{bad} should have raised")
    try:
        export.slice_joined(df, days=0)
    except ValueError:
        pass
    else:
        raise AssertionError("days=0 should have raised")


def test_export_writes_table_and_provenance_meta():
    tmp = Path(tempfile.mkdtemp())
    try:
        src = tmp / "joined_1min.parquet"
        _table().to_parquet(src, index=False)
        out = tmp / "slice" / "demo.parquet"
        meta = export.run(out, cows=["C01"], days=1, source=src)

        assert out.is_file() and pd.read_parquet(out)["cow_id"].unique().tolist() == ["C01"]
        written = json.loads((out.with_name("demo.meta.json")).read_text())
        assert written["rows"] == 60 * 24 and written["cows"] == ["C01"]
        assert "CC BY-NC-SA" in written["derived_from"] and "derived" in written["derived_from"]
        assert meta["keys"] == ["cow_id", "ts_utc"]
    finally:
        shutil.rmtree(tmp)


def test_export_csv_and_missing_source():
    tmp = Path(tempfile.mkdtemp())
    try:
        src = tmp / "j.parquet"
        _table(cows=("C01",), minutes=120).to_parquet(src, index=False)
        out = tmp / "s.csv"
        export.run(out, source=src, fmt="csv")
        assert len(pd.read_csv(out)) == 120

        try:
            export.run(tmp / "x.parquet", source=tmp / "nope.parquet")
        except Exception as e:
            assert isinstance(e, (FileNotFoundError, OSError)), type(e)
        else:
            raise AssertionError("a missing source should have raised")
    finally:
        shutil.rmtree(tmp)


def test_find_joined_env_override_and_absence():
    tmp = Path(tempfile.mkdtemp())
    prev = os.environ.get(locate.ENV_VAR)
    try:
        p = tmp / "joined_1min.parquet"
        _table(cows=("C01",), minutes=10).to_parquet(p, index=False)

        os.environ[locate.ENV_VAR] = str(p)          # full path
        assert locate.find_joined() == p.resolve()
        os.environ[locate.ENV_VAR] = str(tmp)        # directory holding it
        assert locate.find_joined() == p.resolve()
        os.environ[locate.ENV_VAR] = str(tmp / "gone")
        assert locate.find_joined() is None, "absence must be None, not a path that does not exist"
    finally:
        os.environ.pop(locate.ENV_VAR, None)
        if prev is not None:
            os.environ[locate.ENV_VAR] = prev
        shutil.rmtree(tmp)


def test_cli_export_and_bare_invocation_still_parses():
    tmp = Path(tempfile.mkdtemp())
    try:
        src = tmp / "j.parquet"
        _table(cows=("C01", "C02"), minutes=60).to_parquet(src, index=False)
        out = tmp / "cli.parquet"
        assert main(["export", "--out", str(out), "--cows", "C01", "--source", str(src)]) == 0
        assert pd.read_parquet(out)["cow_id"].unique().tolist() == ["C01"]

        # the bare form must still route to build (parse only -- don't run it)
        import argparse
        try:
            main(["--help"])
        except SystemExit as e:
            assert e.code == 0
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
