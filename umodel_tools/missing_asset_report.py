import csv
import dataclasses
import os
import time
import typing as t


CSV = "CSV"
DIRECTORY_UMODEL_EXPORT = "UMODEL_EXPORT"
DIRECTORY_ASSET_CACHE = "ASSET_CACHE"
DIRECTORY_CUSTOM = "CUSTOM"


@dataclasses.dataclass
class MissingAssetRecord:
    map_name: str = ""
    resource_type: str = "unknown"
    severity: str = "warning"
    policy: str = ""
    json_asset_path: str = ""
    normalized_asset_path: str = ""
    attempted_extensions: tuple[str, ...] = ()
    resolution_status: str = "unresolved"
    expected_path: str = ""
    resolved_candidate_count: int = 0
    actor_name: str = ""
    actor_object_path: str = ""
    component_name: str = ""
    component_object_path: str = ""
    instance_index: str = ""
    material_name: str = ""
    texture_parameter_name: str = ""
    fallback_used: str = "none"
    message: str = ""
    occurrence_count: int = 1
    first_actor_name: str = ""
    first_component_name: str = ""
    path_inference_mode: str = ""
    csv_report_path: str = ""

    def dedupe_key(self) -> tuple[str, str, str, str]:
        return (
            self.resource_type,
            self.normalized_asset_path or self.json_asset_path,
            self.resolution_status,
            self.fallback_used,
        )

    def to_row(self) -> dict[str, t.Any]:
        row = dataclasses.asdict(self)
        row["attempted_extensions"] = ";".join(self.attempted_extensions)
        return row


@dataclasses.dataclass
class ImportReport:
    total_missing_assets: int = 0
    missing_mesh_count: int = 0
    missing_material_count: int = 0
    missing_texture_count: int = 0
    ambiguous_asset_count: int = 0
    skipped_instance_count: int = 0
    placeholder_material_count: int = 0
    placeholder_texture_count: int = 0
    csv_report_path: str = ""


class MissingAssetReporter:
    csv_fields = (
        "map_name",
        "resource_type",
        "severity",
        "policy",
        "json_asset_path",
        "normalized_asset_path",
        "attempted_extensions",
        "resolution_status",
        "expected_path",
        "resolved_candidate_count",
        "actor_name",
        "actor_object_path",
        "component_name",
        "component_object_path",
        "instance_index",
        "material_name",
        "texture_parameter_name",
        "fallback_used",
        "message",
        "occurrence_count",
        "first_actor_name",
        "first_component_name",
        "path_inference_mode",
        "csv_report_path",
    )

    def __init__(
        self,
        map_name: str,
        export_dir: str,
        asset_dir: str,
        save_report: bool = True,
        report_format: str = CSV,
        max_console_records: int = 30,
        deduplicate: bool = True,
        directory_mode: str = DIRECTORY_UMODEL_EXPORT,
        custom_directory: str = "",
        include_actor_context: bool = True,
        verbose: bool = False,
    ) -> None:
        self.map_name = map_name
        self.export_dir = export_dir
        self.asset_dir = asset_dir
        self.save_report = save_report
        self.report_format = report_format
        self.max_console_records = max(max_console_records, 0)
        self.deduplicate = deduplicate
        self.directory_mode = directory_mode
        self.custom_directory = custom_directory
        self.include_actor_context = include_actor_context
        self.verbose = verbose
        self._records: list[MissingAssetRecord] = []
        self._dedupe: dict[tuple[str, str, str, str], MissingAssetRecord] = {}
        self._write_fallback_message = ""

    @property
    def records(self) -> tuple[MissingAssetRecord, ...]:
        return tuple(self._records)

    def add(self, record: MissingAssetRecord) -> MissingAssetRecord:
        record.map_name = record.map_name or self.map_name
        record.first_actor_name = record.first_actor_name or record.actor_name
        record.first_component_name = record.first_component_name or record.component_name

        if not self.include_actor_context:
            record.actor_name = ""
            record.actor_object_path = ""
            record.component_name = ""
            record.component_object_path = ""
            record.instance_index = ""
            record.first_actor_name = ""
            record.first_component_name = ""

        if self.deduplicate:
            key = record.dedupe_key()
            existing = self._dedupe.get(key)
            if existing is not None:
                existing.occurrence_count += 1
                return existing
            self._dedupe[key] = record

        self._records.append(record)
        return record

    def build_report(self) -> ImportReport:
        report = ImportReport(total_missing_assets=len(self._records))
        for record in self._records:
            if record.resource_type == "mesh":
                report.missing_mesh_count += 1
            elif record.resource_type == "material":
                report.missing_material_count += 1
            elif record.resource_type == "texture":
                report.missing_texture_count += 1

            if record.resolution_status == "ambiguous":
                report.ambiguous_asset_count += 1
            if record.fallback_used == "skipped_instance":
                report.skipped_instance_count += record.occurrence_count
            elif record.fallback_used == "placeholder_material":
                report.placeholder_material_count += record.occurrence_count
            elif record.fallback_used == "placeholder_color":
                report.placeholder_texture_count += record.occurrence_count

        return report

    def finish(self) -> ImportReport:
        report = self.build_report()
        if not self._records:
            print("[UModelTools] No missing assets detected.")
            return report

        if self.save_report and self.report_format == CSV:
            report.csv_report_path = self.write_csv()

        self._print_summary(report)
        return report

    def write_csv(self) -> str:
        report_dir = self._resolve_report_dir()
        os.makedirs(report_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_map_name = _safe_filename(self.map_name or "Imported_Map")
        csv_path = os.path.join(report_dir, f"umodel_tools_missing_assets_{safe_map_name}_{timestamp}.csv")

        with open(csv_path, mode="w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self.csv_fields, extrasaction="ignore")
            writer.writeheader()
            for record in self._records:
                record.csv_report_path = csv_path
                writer.writerow(record.to_row())

        return csv_path

    def _resolve_report_dir(self) -> str:
        preferred = self.export_dir
        if self.directory_mode == DIRECTORY_ASSET_CACHE:
            preferred = self.asset_dir
        elif self.directory_mode == DIRECTORY_CUSTOM and self.custom_directory:
            preferred = self.custom_directory

        if _ensure_writable_dir(preferred):
            return preferred

        if preferred != self.asset_dir and _ensure_writable_dir(self.asset_dir):
            self._write_fallback_message = (
                f"[UModelTools] Missing asset report directory is not writable, "
                f"falling back to Asset Cache Directory: {self.asset_dir}"
            )
            return self.asset_dir

        return preferred

    def _print_summary(self, report: ImportReport) -> None:
        print("[UModelTools] Import completed with missing assets.")
        print(f"Map: {self.map_name}")
        print(
            "[UModelTools] Missing assets: "
            f"total={report.total_missing_assets}, "
            f"mesh={report.missing_mesh_count}, "
            f"material={report.missing_material_count}, "
            f"texture={report.missing_texture_count}"
        )
        print(f"[UModelTools] Skipped instances: {report.skipped_instance_count}")
        print(f"[UModelTools] Placeholder materials: {report.placeholder_material_count}")
        print(f"[UModelTools] Placeholder textures/colors: {report.placeholder_texture_count}")
        if self._write_fallback_message:
            print(self._write_fallback_message)
        if report.csv_report_path:
            print("[UModelTools] Full missing asset report:")
            print(report.csv_report_path)

        shown_records = self._records if self.verbose else self._records[:self.max_console_records]
        if shown_records:
            print(f"[UModelTools] First {len(shown_records)} missing assets:")
            for idx, record in enumerate(shown_records, start=1):
                print(_format_console_record(idx, record))

        remaining = len(self._records) - len(shown_records)
        if remaining > 0:
            print(f"[UModelTools] Remaining {remaining} missing assets are written to CSV.")


def policy_label(policy: str, fallback_used: str = "none") -> str:
    if policy == "FAIL_IMPORT":
        return "fail_import"
    if fallback_used == "skipped_instance":
        return "warn_and_skip"
    if fallback_used == "placeholder_material":
        return "placeholder_material"
    if fallback_used == "placeholder_color":
        return "placeholder_texture"
    return policy.lower()


def _safe_filename(name: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in name)


def _ensure_writable_dir(path: str) -> bool:
    if not path:
        return False
    if not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            return False
    if not os.path.isdir(path):
        return False
    return os.access(path, os.W_OK)


def _format_console_record(index: int, record: MissingAssetRecord) -> str:
    path = record.json_asset_path or record.normalized_asset_path
    context_parts = []
    if record.actor_name:
        context_parts.append(f"actor={record.actor_name}")
    if record.material_name:
        context_parts.append(f"material={record.material_name}")
    if record.texture_parameter_name:
        context_parts.append(f"texture_param={record.texture_parameter_name}")
    if record.fallback_used:
        context_parts.append(f"fallback={record.fallback_used}")
    if record.occurrence_count > 1:
        context_parts.append(f"occurrences={record.occurrence_count}")

    context_text = " | ".join(context_parts)
    if context_text:
        return f"{index:02d}. [{record.resource_type}] {path} | {context_text}"
    return f"{index:02d}. [{record.resource_type}] {path}"
