#!/usr/bin/env python3
"""Fetch selected MMCows sensor sections into data/raw/ without pulling the
whole 18 GB sensor_data.zip.

The official HuggingFace release ships all sensor data as one zip. This reads
the zip's central directory over HTTP range requests (remotezip) and extracts
only the requested sections, so RGB and the other heavy sub_data folders are
never downloaded. Resumable: a member whose file already exists at the right
size is skipped; partial writes go to <name>.part and are renamed on success.

Usage (from backend-cleaning/):
    python3 scripts/fetch_mmcows.py                    # default sections
    python3 scripts/fetch_mmcows.py uwb cbt milk       # subset

Output layout mirrors the zip: data/raw/sensor_data/main_data/<section>/...
Data is CC BY-NC-SA 4.0 and never committed (data/ is gitignored).
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from remotezip import RemoteZip

URL = "https://huggingface.co/datasets/neis-lab/mmcows/resolve/main/sensor_data.zip"
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
TIMEOUT = 60      # seconds per HTTP read; see _fetch
SWEEPS = 4        # full passes over failed members before giving up

# Challenge 1 tabular core; RGB (visual_data.zip) deliberately excluded.
# Small sections first so usable data lands before the two multi-GB ones.
DEFAULT_SECTIONS = ["milk", "cbt", "thi", "ankle", "weather", "uwb", "pressure", "immu", "behavior_labels"]

# sections that do not live under main_data/
SECTION_PREFIX = {
    "behavior_labels": "sensor_data/behavior_labels/",   # 7-class behaviour, 1 s, 07/25, all 16 cows
    "health_records": "sensor_data/sub_data/health_records/",
    "visual_location": "sensor_data/sub_data/visual_location/",
}


def section_prefix(section: str) -> str:
    return SECTION_PREFIX.get(section, f"sensor_data/main_data/{section}/")


def main(sections: list[str]) -> int:
    prefixes = tuple(section_prefix(s) for s in sections)
    t0 = time.time()
    # TIMEOUT is passed through to requests: without it a half-open CDN
    # connection blocks a read forever and the whole run silently stalls.
    with RemoteZip(URL, timeout=TIMEOUT) as z:
        members = [i for i in z.infolist() if i.filename.startswith(prefixes) and not i.is_dir()]
    # requested-section order, not zip order, so the small sections land first
    members.sort(key=lambda i: (prefixes.index(next(p for p in prefixes if i.filename.startswith(p))), i.filename))
    total = sum(i.file_size for i in members)
    print(f"{len(members)} files, {total / 1e9:.2f} GB across {sections}", flush=True)

    pending = members
    for sweep in range(1, SWEEPS + 1):
        failed = _fetch(pending, total, t0, len(members))
        if not failed:
            break
        print(f"sweep {sweep}: {len(failed)} member(s) failed, reconnecting and retrying", flush=True)
        time.sleep(30 * sweep)
        pending = failed
    else:
        print(f"GAVE UP on {len(pending)} member(s); rerun to resume", flush=True)
        return 1
    print(f"done in {time.time() - t0:.0f}s -> {RAW}", flush=True)
    return 0


def _fetch(members, total: int, t0: float, n_all: int) -> list:
    """One pass over `members` on a fresh connection; return the ones that failed."""
    failed = []
    done_bytes = sum(i.file_size for i in members if (RAW / i.filename).exists())
    with RemoteZip(URL, timeout=TIMEOUT) as z:
        for n, info in enumerate(members, 1):
            dest = RAW / info.filename
            if dest.exists() and dest.stat().st_size == info.file_size:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_suffix(dest.suffix + ".part")
            for attempt in range(1, 4):
                try:
                    with z.open(info) as src, open(part, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                    if part.stat().st_size != info.file_size:
                        raise OSError(f"size mismatch {part.stat().st_size} != {info.file_size}")
                    part.rename(dest)
                    break
                except Exception as e:  # network hiccup: retry the member
                    print(f"  retry {attempt}/3 {info.filename}: {type(e).__name__}: {str(e)[:120]}", flush=True)
                    time.sleep(5 * attempt)
            else:
                print(f"FAILED {info.filename}", flush=True)
                failed.append(info)
                continue
            done_bytes += info.file_size
            print(
                f"[{n}/{n_all}] {done_bytes / 1e9:6.2f}/{total / 1e9:.2f} GB "
                f"{time.time() - t0:6.0f}s  {info.filename}",
                flush=True,
            )
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or DEFAULT_SECTIONS))
