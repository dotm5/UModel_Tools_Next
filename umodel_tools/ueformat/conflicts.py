"""Project-local conflict override storage for UEFormat imports."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_CONFLICT_STORE_NAME = "umodel_tools_conflict_overrides.json"


@dataclass(frozen=True)
class ConflictKey:
    kind: str
    uemodel_asset_path: str
    material_slot: str
    parameter_name: str
    original_reference: str

    def to_json(self):
        return asdict(self)


@dataclass
class ConflictRecord:
    key: ConflictKey
    status: str
    candidates: List[str]
    selected_override: Optional[str] = None

    def to_json(self):
        return {
            "key": asdict(self.key),
            "status": self.status,
            "candidates": list(self.candidates),
            "selected_override": self.selected_override,
        }


class UEFormatConflictStore:
    def __init__(self, asset_cache_dir_or_path: str):
        path = Path(asset_cache_dir_or_path)
        if path.suffix.lower() != ".json":
            path = path / DEFAULT_CONFLICT_STORE_NAME
        self.path = str(path)
        self._records: Dict[str, ConflictRecord] = {}
        self._load()

    def set_override(self, key: ConflictKey, selected_path: str) -> None:
        record = self._records.get(self._serialize_key(key))
        if record is None:
            record = ConflictRecord(
                key=key,
                status="overridden",
                candidates=[],
                selected_override=selected_path,
            )
        else:
            record.selected_override = selected_path
        self._records[self._serialize_key(key)] = record

    def get_override(self, key: ConflictKey) -> Optional[str]:
        record = self._records.get(self._serialize_key(key))
        if record is None:
            return None
        return record.selected_override

    def records(self, kind: str = "") -> tuple[ConflictRecord, ...]:
        records = [
            self._records[key]
            for key in sorted(self._records)
        ]
        if kind:
            records = [record for record in records if record.key.kind == kind]
        return tuple(records)

    def record_conflict(self, key: ConflictKey, status: str, candidates) -> None:
        serialized_key = self._serialize_key(key)
        existing = self._records.get(serialized_key)
        selected_override = existing.selected_override if existing is not None else None
        self._records[serialized_key] = ConflictRecord(
            key=key,
            status=status,
            candidates=list(candidates),
            selected_override=selected_override,
        )

    def save(self) -> None:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "conflicts": [
                self._records[key].to_json()
                for key in sorted(self._records)
            ],
        }
        path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _load(self) -> None:
        path = Path(self.path)
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = self._parse_payload(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return
        self._records = records

    def _parse_payload(self, payload) -> Dict[str, ConflictRecord]:
        if not isinstance(payload, dict):
            return {}
        raw_conflicts = payload.get("conflicts")
        if not isinstance(raw_conflicts, list):
            return {}

        records: Dict[str, ConflictRecord] = {}
        for raw_record in raw_conflicts:
            record = self._parse_record(raw_record)
            if record is None:
                continue
            records[self._serialize_key(record.key)] = record
        return records

    def _parse_record(self, raw_record) -> Optional[ConflictRecord]:
        if not isinstance(raw_record, dict):
            return None
        key = self._parse_key(raw_record.get("key"))
        status = raw_record.get("status")
        candidates = raw_record.get("candidates")
        selected_override = raw_record.get("selected_override")

        if key is None or not isinstance(status, str):
            return None
        if not isinstance(candidates, list) or not all(
            isinstance(candidate, str) for candidate in candidates
        ):
            return None
        if selected_override is not None and not isinstance(selected_override, str):
            return None

        return ConflictRecord(
            key=key,
            status=status,
            candidates=list(candidates),
            selected_override=selected_override,
        )

    def _parse_key(self, raw_key) -> Optional[ConflictKey]:
        if not isinstance(raw_key, dict):
            return None
        fields = {
            "kind": raw_key.get("kind"),
            "uemodel_asset_path": raw_key.get("uemodel_asset_path"),
            "material_slot": raw_key.get("material_slot"),
            "parameter_name": raw_key.get("parameter_name"),
            "original_reference": raw_key.get("original_reference"),
        }
        if not all(isinstance(value, str) for value in fields.values()):
            return None
        return ConflictKey(**fields)

    @staticmethod
    def _serialize_key(key: ConflictKey) -> str:
        return json.dumps(
            asdict(key),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
