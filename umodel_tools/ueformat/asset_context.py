from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UEFormatAssetContext:
    uemodel_asset_path: str
    source_filepath: str
    export_root: str
    asset_cache_dir: str
    game_profile: str
    path_inference_mode: str
    enable_suffix_index: bool
    material_rule_paths: list[str]
    conflict_store_path: str
    material_slots: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {
            "uemodel_asset_path": self.uemodel_asset_path,
            "source_filepath": self.source_filepath,
            "export_root": self.export_root,
            "asset_cache_dir": self.asset_cache_dir,
            "game_profile": self.game_profile,
            "path_inference_mode": self.path_inference_mode,
            "enable_suffix_index": self.enable_suffix_index,
            "material_rule_paths": list(self.material_rule_paths),
            "conflict_store_path": self.conflict_store_path,
            "material_slots": [dict(slot) for slot in self.material_slots],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "UEFormatAssetContext":
        payload = data if isinstance(data, dict) else {}
        return cls(
            uemodel_asset_path=_string_value(payload.get("uemodel_asset_path")),
            source_filepath=_string_value(payload.get("source_filepath")),
            export_root=_string_value(payload.get("export_root")),
            asset_cache_dir=_string_value(payload.get("asset_cache_dir")),
            game_profile=_string_value(payload.get("game_profile")),
            path_inference_mode=_string_value(payload.get("path_inference_mode")),
            enable_suffix_index=_bool_value(payload.get("enable_suffix_index")),
            material_rule_paths=_string_list(payload.get("material_rule_paths")),
            conflict_store_path=_string_value(payload.get("conflict_store_path")),
            material_slots=_dict_list(payload.get("material_slots")),
        )


def _string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _bool_value(value: Any) -> bool:
    return value if isinstance(value, bool) else False


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dict_list(value: Any) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
