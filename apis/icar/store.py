"""State store for manual entries, cow flags, and backtrace runs.

Owner: @uiobio (Lei)
Provides:
- Thread-safe in-memory storage for manual farm entries, flags, and backtrace executions.
- JSON persistence support.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from apis.icar.models import (
    BacktraceRun,
    FlagRecord,
    ManualEntry,
    RestingSpot,
    SanitationRecord,
    now_utc_iso,
)


VALID_SANITATION_KINDS = {"end_of_session", "between_cows"}


class StateStore:
    """In-memory state store with optional JSON serialization."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self._storage_path = Path(storage_path) if storage_path else None
        self._manual_entries: Dict[str, ManualEntry] = {}
        self._flags: Dict[str, FlagRecord] = {}
        self._backtrace_runs: Dict[str, BacktraceRun] = {}
        self._sanitation_records: List[SanitationRecord] = []
        self._seed_initial_state()

    def _seed_initial_state(self) -> None:
        """Seed representative initial manual entries and watch flags."""
        # Initial bedding changes
        self.add_manual_entry(
            entry_type="bedding",
            animal_id=None,
            details={
                "pen_id": "pen_cubicles_01",
                "bedding_type": "recycled_sand",
                "depth_cm": 15.0,
                "moisture_pct": 12.5,
            },
            recorded_by="pen_manager",
            event_datetime="2023-07-21T08:00:00Z",
        )
        # Initial milking parlor sanitation log with kind support
        self.add_manual_entry(
            entry_type="sanitation",
            animal_id=None,
            details={
                "unit_id": "STALL-01",
                "kind": "end_of_session",
                "cycle_type": "hot_water_acid_wash",
                "chemical": "peracetic_acid",
                "water_temp_c": 75.0,
            },
            recorded_by="parlor_operator",
            event_datetime="2023-07-25T11:00:00Z",
            kind="end_of_session",
        )
        self.add_sanitation_record(
            unit_id="STALL-01",
            sanitized_at="2023-07-25T11:00:00Z",
            session_id="2023-07-25_AM",
            kind="end_of_session",
            is_synthetic=True,
        )
        self.add_sanitation_record(
            unit_id="STALL-02",
            sanitized_at="2023-07-25T11:15:00Z",
            session_id="2023-07-25_AM",
            kind="between_cows",
            is_synthetic=True,
        )
        # Seed an initial watch-list flag
        self.add_flag(
            animal_id="C02",
            flag_type="manual",
            reason="Mild udder asymmetry noted at morning milking",
            flagged_by="herd_manager",
            flagged_at_utc="2023-07-24T16:00:00Z",
        )

    def add_manual_entry(
        self,
        entry_type: str,
        details: Dict[str, Any],
        animal_id: Optional[str] = None,
        recorded_by: str = "operator",
        event_datetime: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> ManualEntry:
        with self._lock:
            entry_id = f"man_{uuid4().hex[:8]}"
            ts = event_datetime or now_utc_iso()
            k = kind or details.get("kind")
            if entry_type == "sanitation" and k is not None and k not in VALID_SANITATION_KINDS:
                raise ValueError(f"Invalid sanitation kind '{k}'. Must be one of {sorted(VALID_SANITATION_KINDS)}")
            entry = ManualEntry(
                entry_id=entry_id,
                entry_type=entry_type,
                animal_id=animal_id,
                event_datetime=ts,
                details=details,
                recorded_by=recorded_by,
                kind=k,
            )
            self._manual_entries[entry_id] = entry
            return entry

    def add_sanitation_record(
        self,
        unit_id: str,
        sanitized_at: str,
        session_id: str,
        kind: str = "end_of_session",
        is_synthetic: bool = True,
    ) -> SanitationRecord:
        if kind not in VALID_SANITATION_KINDS:
            raise ValueError(f"Invalid sanitation kind '{kind}'. Must be one of {sorted(VALID_SANITATION_KINDS)}")
        record = SanitationRecord(
            unit_id=unit_id,
            sanitized_at=sanitized_at,
            session_id=session_id,
            kind=kind,
            is_synthetic=is_synthetic,
        )
        with self._lock:
            self._sanitation_records.append(record)
        return record

    def get_sanitation_records(
        self,
        unit_id: Optional[str] = None,
        kind: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[SanitationRecord]:
        with self._lock:
            records = list(self._sanitation_records)
            if unit_id:
                records = [r for r in records if r.unit_id == unit_id]
            if kind:
                records = [r for r in records if r.kind == kind]
            if session_id:
                records = [r for r in records if r.session_id == session_id]
            return records

    def get_manual_entries(
        self,
        entry_type: Optional[str] = None,
        animal_id: Optional[str] = None,
    ) -> List[ManualEntry]:
        with self._lock:
            entries = list(self._manual_entries.values())
            if entry_type:
                entries = [e for e in entries if e.entry_type == entry_type]
            if animal_id:
                entries = [e for e in entries if e.animal_id == animal_id]
            return entries

    def add_flag(
        self,
        animal_id: str,
        flag_type: str,
        reason: str,
        flagged_by: str = "operator",
        flagged_at_utc: Optional[str] = None,
    ) -> FlagRecord:
        with self._lock:
            flag_id = f"flag_{uuid4().hex[:8]}"
            ts = flagged_at_utc or now_utc_iso()
            flag = FlagRecord(
                flag_id=flag_id,
                animal_id=animal_id,
                flag_type=flag_type,
                flagged_at_utc=ts,
                status="active",
                reason=reason,
                flagged_by=flagged_by,
            )
            self._flags[flag_id] = flag
            return flag

    def add_flags(
        self,
        animal_ids: List[str],
        flag_type: str,
        reason: str,
        flagged_by: str = "operator",
        flagged_at_utc: Optional[str] = None,
    ) -> List[FlagRecord]:
        created: List[FlagRecord] = []
        for aid in animal_ids:
            created.append(self.add_flag(
                animal_id=aid,
                flag_type=flag_type,
                reason=reason,
                flagged_by=flagged_by,
                flagged_at_utc=flagged_at_utc,
            ))
        return created

    def update_flag_status(
        self,
        flag_id: str,
        new_status: str,
    ) -> Optional[FlagRecord]:
        with self._lock:
            flag = self._flags.get(flag_id)
            if flag:
                flag.status = new_status
                return flag
            return None

    def get_flags(
        self,
        animal_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[FlagRecord]:
        with self._lock:
            flags = list(self._flags.values())
            if animal_id:
                flags = [f for f in flags if f.animal_id == animal_id]
            if status:
                flags = [f for f in flags if f.status == status]
            return flags

    def record_backtrace_run(
        self,
        target_animal_id: str,
        lookback_days: int,
        summary: Dict[str, Any],
        target_animal_ids: Optional[List[str]] = None,
    ) -> BacktraceRun:
        with self._lock:
            run_id = f"trace_{uuid4().hex[:8]}"
            targets = target_animal_ids or ([target_animal_id] if target_animal_id else [])
            run = BacktraceRun(
                run_id=run_id,
                target_animal_id=target_animal_id,
                target_animal_ids=targets,
                initiated_at_utc=now_utc_iso(),
                status="completed",
                lookback_days=lookback_days,
                summary=summary,
            )
            self._backtrace_runs[run_id] = run
            return run

    def get_backtrace_runs(
        self,
        target_animal_id: Optional[str] = None,
    ) -> List[BacktraceRun]:
        with self._lock:
            runs = list(self._backtrace_runs.values())
            if target_animal_id:
                runs = [r for r in runs if r.target_animal_id == target_animal_id]
            return runs
