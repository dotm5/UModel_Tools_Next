
import json
import os
import typing as t

import bpy
import bpy_extras.io_utils

from . import map_importer
from . import preferences
from . import import_support
from . import localization
from . import umodel_path_resolver
from . import missing_asset_report
from . import game_profiles


def _normalize_dir_input(path: str) -> str:
    normalized = os.path.normpath(path) if path else ""
    return normalized[1:] if normalized.startswith(os.sep) else normalized


def _import_params_cache_path() -> str:
    return os.path.join(os.path.dirname(__file__), "last_import_params.json")


_IMPORT_PARAM_CACHE_VERSION = 1
_IMPORT_PARAM_CACHE_FIELDS = (
    "umodel_export_dir",
    "game_profile",
    "load_pbr_maps",
    "texture_format",
    "import_backface_culling",
    "import_skeletal_mesh_as_static_fallback",
    "import_skeletal_mesh_with_armature",
    "import_psa_animations",
    "path_inference_mode",
    "missing_mesh_policy",
    "missing_material_policy",
    "missing_texture_policy",
    "validation_preset",
    "show_advanced_import_settings",
    "enable_umodel_path_inference",
    "enable_suffix_index",
    "report_path_resolution_stats",
    "enable_import_validation",
    "min_mesh_count",
    "min_light_count",
    "min_material_count",
    "require_any_material_assigned",
    "reject_dict_like_names",
    "allow_missing_placeholder_materials",
    "max_missing_asset_warnings_in_console",
    "print_missing_asset_summary",
    "save_missing_asset_report",
    "missing_asset_report_format",
    "max_missing_assets_printed_to_console",
    "deduplicate_missing_assets",
    "missing_asset_report_directory_mode",
    "custom_missing_asset_report_directory",
    "include_actor_context_in_missing_report",
)

_DEFAULT_ASSET_CACHE_SUBDIR = "temp-assets"


def _read_import_params_cache() -> dict[str, t.Any]:
    cache_path = _import_params_cache_path()
    if not os.path.isfile(cache_path):
        return {}

    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    params = payload.get("params", {})
    return params if isinstance(params, dict) else {}


def _write_import_params_cache(params: dict[str, t.Any]) -> None:
    cache_path = _import_params_cache_path()
    payload = {
        "version": _IMPORT_PARAM_CACHE_VERSION,
        "params": params,
    }
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)


def _default_asset_cache_dir(umodel_export_dir: str) -> str:
    if not umodel_export_dir:
        return ""
    return os.path.join(umodel_export_dir, _DEFAULT_ASSET_CACHE_SUBDIR)


def _resolve_asset_cache_dir(
    umodel_export_dir: str,
    operator_asset_cache_dir: str = "",
    prefs: bpy.types.AddonPreferences | None = None
) -> str:
    explicit_dir = _normalize_dir_input(operator_asset_cache_dir)
    if explicit_dir:
        return explicit_dir

    prefs = prefs or preferences.get_addon_preferences()
    manual_dir = _normalize_dir_input(getattr(prefs, "manual_asset_cache_dir", ""))
    if manual_dir:
        return manual_dir

    return _default_asset_cache_dir(umodel_export_dir)


class UMODELTOOLS_OT_select_unreal_map_json(bpy.types.Operator, bpy_extras.io_utils.ImportHelper):
    bl_idname = "umodel_tools.select_unreal_map_json"
    bl_label = "Import Unreal Map"
    bl_description = "Select Unreal Engine 4 map files (.umap -> FModel .json)"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    filter_glob: bpy.props.StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255
    )

    files: bpy.props.CollectionProperty(
        name="Unreal Engine 4 map (FModel .json)",
        type=bpy.types.OperatorFileListElement,
    )

    directory: bpy.props.StringProperty(subtype='DIR_PATH')

    def invoke(self, context: bpy.types.Context, _: bpy.types.Event) -> set[str]:
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        map_paths = self._selected_map_paths()
        if not map_paths:
            self.report({'ERROR'}, localization.t_report("Map JSON path was not provided."))
            return {'CANCELLED'}

        return bpy.ops.umodel_tools.import_unreal_map(
            'INVOKE_DEFAULT',
            map_paths=json.dumps(map_paths, ensure_ascii=False)
        )

    def _selected_map_paths(self) -> list[str]:
        selected_files = list(getattr(self, "files", []))
        if selected_files:
            return [os.path.join(self.directory, file.name) for file in selected_files]

        filepath = getattr(self, "filepath", "")
        return [filepath] if filepath else []


class UMODELTOOLS_OT_import_unreal_map(map_importer.MapImporter, bpy.types.Operator):
    bl_idname = "umodel_tools.import_unreal_map"
    bl_label = "Import Unreal Map"
    bl_description = "Imports Unreal Engine 4 maps after JSON selection"
    bl_options = {'REGISTER', 'UNDO'}

    map_paths: bpy.props.StringProperty(
        name="Map JSON Paths",
        description="JSON-encoded selected map paths",
        options={'HIDDEN'}
    )

    filepath: bpy.props.StringProperty(
        name="Map JSON Path",
        description="Selected map JSON path",
        subtype='FILE_PATH',
        options={'HIDDEN'}
    )

    umodel_export_dir: bpy.props.StringProperty(
        name="UModel Export Directory",
        description="Path to the UModel export directory with game assets",
        subtype='DIR_PATH'
    )

    asset_cache_dir: bpy.props.StringProperty(
        name="Asset Cache Directory",
        description="Path to the directory where imported asset blend files are cached",
        subtype='DIR_PATH',
        options={'HIDDEN'}
    )

    game_profile: bpy.props.EnumProperty(
        name="Game Profile",
        description="Material and texture reconstruction profile used for this import",
        items=game_profiles.SUPPORTED_GAMES,
        default='generic'
    )

    path_inference_mode: bpy.props.EnumProperty(
        name="Path Inference Mode",
        description="Controls how aggressively UModel export paths are resolved",
        items=[
            ('BASIC_DEFAULT', "Basic Default", "Exact lookup plus common UModel mount truncation aliases"),
            ('STRICT_EXACT', "Strict Exact", "Only use direct path matching"),
            ('AGGRESSIVE', "Aggressive", "Use exact matching, mount truncation, and suffix index lookup")
        ],
        default='BASIC_DEFAULT'
    )

    missing_mesh_policy: bpy.props.EnumProperty(
        name="Missing Mesh Policy",
        description="How map import handles missing mesh files",
        items=[
            ('WARN_SKIP', "Warn and Skip", "Skip the missing mesh instance and continue importing"),
            ('FAIL_IMPORT', "Fail Import", "Cancel the import when a mesh is missing")
        ],
        default='WARN_SKIP'
    )

    missing_material_policy: bpy.props.EnumProperty(
        name="Missing Material Policy",
        description="How map import handles missing material descriptors",
        items=[
            ('USE_PLACEHOLDER', "Use Placeholder Material", "Create an editable placeholder material and continue"),
            ('FAIL_IMPORT', "Fail Import", "Cancel the import when a material is missing")
        ],
        default='USE_PLACEHOLDER'
    )

    missing_texture_policy: bpy.props.EnumProperty(
        name="Missing Texture Policy",
        description="How map import handles missing texture files",
        items=[
            ('USE_PLACEHOLDER', "Use Placeholder Color", "Leave the material usable with shader defaults"),
            ('FAIL_IMPORT', "Fail Import", "Cancel the import when a texture is missing")
        ],
        default='USE_PLACEHOLDER'
    )

    validation_preset: bpy.props.EnumProperty(
        name="Validation Preset",
        description="Import validation strictness",
        items=[
            ('BASIC_DEFAULT', "Basic Default", "Conservative validation for normal importing"),
            ('STRICT', "Strict", "Developer-oriented validation with high mesh/light expectations"),
            ('CUSTOM', "Custom", "Use the manually configured validation thresholds")
        ],
        default='BASIC_DEFAULT'
    )

    show_advanced_import_settings: bpy.props.BoolProperty(
        name="Show Advanced Import Settings",
        description="Show advanced import settings",
        default=False
    )

    enable_umodel_path_inference: bpy.props.BoolProperty(
        name="Enable UModel Path Inference",
        description="Resolve common UModel export mount point truncation automatically",
        default=True
    )

    enable_suffix_index: bpy.props.BoolProperty(
        name="Enable Suffix Index",
        description="Allow suffix-index lookup when Path Inference Mode is Aggressive",
        default=True
    )

    report_path_resolution_stats: bpy.props.BoolProperty(
        name="Report Path Resolution Stats",
        description="Print path resolution counters after map import",
        default=True
    )

    enable_import_validation: bpy.props.BoolProperty(
        name="Enable Import Validation",
        description="Validate imported scene counts and common data issues after map import",
        default=True
    )

    import_skeletal_mesh_as_static_fallback: bpy.props.BoolProperty(
        name="Import Skeletal Meshes as Static Fallback",
        description=(
            "Place SkeletalMeshComponent geometry as static map meshes while skipping armatures, "
            "morph targets, and animations"
        ),
        default=True
    )

    import_skeletal_mesh_with_armature: bpy.props.BoolProperty(
        name="Import Skeletal Mesh Armatures (Experimental)",
        description=(
            "Append local mesh and armature objects for SkeletalMeshComponent entries; "
            "morph targets remain disabled and failures use the normal static fallback"
        ),
        default=False
    )

    import_psa_animations: bpy.props.BoolProperty(
        name="Import Basic PSA Animation (Experimental)",
        description=(
            "Load one AnimationData.AnimToPlay PSA sequence onto each imported armature; "
            "does not support animation blueprints, montages, retargeting, or root motion"
        ),
        default=False
    )

    min_mesh_count: bpy.props.IntProperty(
        name="Min Mesh Count",
        description="Minimum mesh object count required by Custom validation",
        default=1,
        min=0
    )

    min_light_count: bpy.props.IntProperty(
        name="Min Light Count",
        description="Minimum light object count required by Custom validation",
        default=0,
        min=0
    )

    min_material_count: bpy.props.IntProperty(
        name="Min Material Count",
        description="Minimum material datablock count required by Custom validation",
        default=0,
        min=0
    )

    require_any_material_assigned: bpy.props.BoolProperty(
        name="Require Any Material Assigned",
        description="Fail validation if no imported mesh has any assigned material",
        default=False
    )

    reject_dict_like_names: bpy.props.BoolProperty(
        name="Reject Dict-like Names",
        description="Fail validation when Blender datablock names look like stringified JSON dictionaries",
        default=True
    )

    allow_missing_placeholder_materials: bpy.props.BoolProperty(
        name="Allow Missing Placeholder Materials",
        description="Treat placeholder materials as warnings instead of validation errors",
        default=True
    )

    max_missing_asset_warnings_in_console: bpy.props.IntProperty(
        name="Max Missing Asset Warnings in Console",
        description="Maximum individual missing asset warnings printed before suppressing repeats",
        default=50,
        min=0
    )

    print_missing_asset_summary: bpy.props.BoolProperty(
        name="Print Missing Asset Summary",
        description="Print a summary of missing assets and storage counts after import",
        default=True
    )

    save_paths_as_recent: bpy.props.BoolProperty(
        name="Save Paths as Recent",
        description="Remember this import's directories without changing profile defaults",
        default=True
    )

    save_missing_asset_report: bpy.props.BoolProperty(
        name="Save Missing Asset Report",
        description="Write a structured missing asset report after map import",
        default=True
    )

    missing_asset_report_format: bpy.props.EnumProperty(
        name="Missing Asset Report Format",
        description="File format for missing asset reports",
        items=[
            (missing_asset_report.CSV, "CSV", "Write a CSV report")
        ],
        default=missing_asset_report.CSV
    )

    max_missing_assets_printed_to_console: bpy.props.IntProperty(
        name="Max Missing Assets Printed to Console",
        description="Maximum missing asset rows printed to the console summary",
        default=30,
        min=0
    )

    deduplicate_missing_assets: bpy.props.BoolProperty(
        name="Deduplicate Missing Assets",
        description="Merge repeated missing references to the same asset in the report",
        default=True
    )

    missing_asset_report_directory_mode: bpy.props.EnumProperty(
        name="Missing Asset Report Directory",
        description="Where missing asset reports should be saved",
        items=[
            (
                missing_asset_report.DIRECTORY_UMODEL_EXPORT,
                "UModel Export Directory",
                "Save reports next to UModel exports",
            ),
            (missing_asset_report.DIRECTORY_ASSET_CACHE, "Asset Cache Directory", "Save reports in the asset cache"),
            (missing_asset_report.DIRECTORY_CUSTOM, "Custom", "Save reports in a custom directory")
        ],
        default=missing_asset_report.DIRECTORY_UMODEL_EXPORT
    )

    custom_missing_asset_report_directory: bpy.props.StringProperty(
        name="Custom Missing Asset Report Directory",
        description="Directory for missing asset reports when Directory is Custom",
        subtype='DIR_PATH'
    )

    include_actor_context_in_missing_report: bpy.props.BoolProperty(
        name="Include Actor Context in Missing Report",
        description="Include actor and component fields in missing asset reports",
        default=True
    )

    def invoke(self, context: bpy.types.Context, _: bpy.types.Event) -> set[str]:
        self._apply_cached_or_default_parameters()
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text=localization.t_iface("Map JSON"))
        if hasattr(self, "_selected_map_paths"):
            map_paths = self._selected_map_paths()
        else:
            filepath = getattr(self, "filepath", "")
            map_paths = [filepath] if filepath else []
        if len(map_paths) == 1:
            layout.label(text=os.path.basename(map_paths[0]))
        elif map_paths:
            layout.label(text=localization.t_iface(f"{len(map_paths)} files selected"))

        layout.prop(self, "umodel_export_dir")
        layout.prop(self, "game_profile")
        layout.prop(self, "load_pbr_maps")
        layout.prop(self, "texture_format")
        layout.prop(self, "path_inference_mode")
        layout.prop(self, "missing_mesh_policy")
        layout.prop(self, "missing_material_policy")
        layout.prop(self, "missing_texture_policy")
        layout.prop(self, "validation_preset")

        layout.prop(
            self,
            "show_advanced_import_settings",
            icon='TRIA_DOWN' if self.show_advanced_import_settings else 'TRIA_RIGHT'
        )
        if not self.show_advanced_import_settings:
            return

        box = layout.box()
        box.prop(self, "enable_umodel_path_inference")
        path_col = box.column()
        path_col.enabled = self.enable_umodel_path_inference
        path_col.prop(self, "enable_suffix_index")
        box.prop(self, "report_path_resolution_stats")
        box.prop(self, "import_backface_culling")
        box.prop(self, "import_skeletal_mesh_as_static_fallback")
        box.prop(self, "import_skeletal_mesh_with_armature")
        animation_col = box.column()
        animation_col.enabled = self.import_skeletal_mesh_with_armature
        animation_col.prop(self, "import_psa_animations")
        box.prop(self, "enable_import_validation")
        box.prop(self, "min_mesh_count")
        box.prop(self, "min_light_count")
        box.prop(self, "min_material_count")
        box.prop(self, "require_any_material_assigned")
        box.prop(self, "reject_dict_like_names")
        box.prop(self, "allow_missing_placeholder_materials")
        box.prop(self, "max_missing_asset_warnings_in_console")
        box.prop(self, "print_missing_asset_summary")
        box.prop(self, "save_missing_asset_report")
        box.prop(self, "missing_asset_report_format")
        box.prop(self, "max_missing_assets_printed_to_console")
        box.prop(self, "deduplicate_missing_assets")
        box.prop(self, "missing_asset_report_directory_mode")
        if self.missing_asset_report_directory_mode == missing_asset_report.DIRECTORY_CUSTOM:
            box.prop(self, "custom_missing_asset_report_directory")
        box.prop(self, "include_actor_context_in_missing_report")
        box.prop(self, "save_paths_as_recent")

    def execute(self, context: bpy.types.Context) -> set[str]:
        self._reset_import_runtime_state()
        self._apply_cached_or_default_parameters(fill_empty_only=True)

        umodel_export_dir: str = _normalize_dir_input(self.umodel_export_dir)

        if not umodel_export_dir:
            return self._op_message('ERROR', "You need to specify a UModel export dir.")

        if not os.path.isdir(umodel_export_dir):
            return self._op_message('ERROR', f"Path to UModel export dir {umodel_export_dir} does not exist.")

        asset_dir: str = _resolve_asset_cache_dir(
            umodel_export_dir=umodel_export_dir,
            operator_asset_cache_dir=self.asset_cache_dir
        )

        if not asset_dir:
            return self._op_message('ERROR', "You need to specify an asset cache dir.")

        if not os.path.isdir(asset_dir):
            try:
                os.makedirs(asset_dir, exist_ok=True)
            except OSError as exc:
                return self._op_message('ERROR', f"Path to asset dir {asset_dir} could not be created: {exc}.")

        db = import_support.AssetDB(asset_dir)
        game_profile = getattr(self, "game_profile", "") or "generic"
        self._save_import_params_cache(umodel_export_dir=umodel_export_dir, asset_cache_dir=asset_dir)

        import_ok = True
        map_paths = self._selected_map_paths()
        if not map_paths:
            return self._op_message('ERROR', "Map JSON path was not provided.")

        for map_file_path in map_paths:
            import_ok = self._import_map(context=context, umodel_export_dir=umodel_export_dir, asset_dir=asset_dir,
                                         db=db, map_path=map_file_path,
                                         game_profile=game_profile) and import_ok

        db.save_db()

        self._print_unrecognized_textures()

        if not import_ok:
            report = getattr(self, "_last_import_report", None)
            if report is not None and report.total_missing_assets:
                self.report(
                    {"WARNING"},
                    localization.t_report("Import completed with missing assets. CSV report saved.")
                )
            return self._op_message('ERROR', "Map import failed. Check console for details.")

        if self.save_paths_as_recent:
            prefs = preferences.get_addon_preferences()
            prefs.recent_umodel_export_dir = umodel_export_dir
            prefs.recent_asset_cache_dir = asset_dir

        validation_settings = import_support.get_import_validation_settings(self)
        validation_result = import_support.validate_import_result(context.scene, validation_settings)
        validation_status = import_support.report_import_validation(self, validation_result)
        if validation_status == {"CANCELLED"}:
            return validation_status

        report = getattr(self, "_last_import_report", None)
        if report is not None and report.total_missing_assets:
            self.report(
                {"WARNING"},
                localization.t_report(
                    f"Import completed with {report.total_missing_assets} missing assets. CSV report saved."
                )
            )

        if self._has_warnings:
            self._op_message('WARNING', "Map import had warnings. Check console for details.")

        return {'FINISHED'}

    def _apply_cached_or_default_parameters(self, fill_empty_only: bool = False) -> None:
        prefs = preferences.get_addon_preferences()
        cached_params = _read_import_params_cache()

        def set_if_needed(attr_name: str, value: t.Any) -> None:
            if fill_empty_only:
                current_value = getattr(self, attr_name)
                if current_value not in ("", None):
                    return
            setattr(self, attr_name, value)

        default_params = {
            "game_profile": "generic",
            "load_pbr_maps": getattr(prefs, "default_load_pbr_maps", True),
            "import_backface_culling": getattr(prefs, "default_import_backface_culling", False),
            "import_skeletal_mesh_as_static_fallback": getattr(
                prefs, "default_import_skeletal_mesh_as_static_fallback", True
            ),
            "import_skeletal_mesh_with_armature": getattr(
                prefs, "default_import_skeletal_mesh_with_armature", False
            ),
            "import_psa_animations": getattr(prefs, "default_import_psa_animations", False),
            "texture_format": getattr(prefs, "default_texture_format", ".png"),
            "path_inference_mode": getattr(prefs, "path_inference_mode", umodel_path_resolver.BASIC_DEFAULT),
            "enable_umodel_path_inference": getattr(prefs, "enable_umodel_path_inference", True),
            "enable_suffix_index": getattr(prefs, "enable_suffix_index", True),
            "report_path_resolution_stats": getattr(prefs, "report_path_resolution_stats", True),
            "enable_import_validation": getattr(prefs, "enable_import_validation", True),
            "validation_preset": getattr(prefs, "validation_preset", import_support.BASIC_DEFAULT),
            "min_mesh_count": getattr(prefs, "min_mesh_count", 1),
            "min_light_count": getattr(prefs, "min_light_count", 0),
            "min_material_count": getattr(prefs, "min_material_count", 0),
            "require_any_material_assigned": getattr(prefs, "require_any_material_assigned", False),
            "reject_dict_like_names": getattr(prefs, "reject_dict_like_names", True),
            "allow_missing_placeholder_materials": getattr(prefs, "allow_missing_placeholder_materials", True),
            "save_missing_asset_report": getattr(prefs, "save_missing_asset_report", True),
            "missing_asset_report_format": getattr(
                prefs, "missing_asset_report_format", missing_asset_report.CSV
            ),
            "max_missing_assets_printed_to_console": getattr(prefs, "max_missing_assets_printed_to_console", 30),
            "deduplicate_missing_assets": getattr(prefs, "deduplicate_missing_assets", True),
            "missing_asset_report_directory_mode": getattr(
                prefs, "missing_asset_report_directory_mode", missing_asset_report.DIRECTORY_UMODEL_EXPORT
            ),
            "custom_missing_asset_report_directory": getattr(prefs, "custom_missing_asset_report_directory", ""),
            "include_actor_context_in_missing_report": getattr(prefs, "include_actor_context_in_missing_report", True),
        }
        manual_asset_cache_dir = getattr(prefs, "manual_asset_cache_dir", "")
        if manual_asset_cache_dir:
            default_params["asset_cache_dir"] = manual_asset_cache_dir

        for attr_name, value in default_params.items():
            set_if_needed(attr_name, value)

        for attr_name in _IMPORT_PARAM_CACHE_FIELDS:
            if attr_name in cached_params:
                set_if_needed(attr_name, cached_params[attr_name])

    def _save_import_params_cache(self, umodel_export_dir: str, asset_cache_dir: str) -> None:
        params = {}
        for attr_name in _IMPORT_PARAM_CACHE_FIELDS:
            value = getattr(self, attr_name, None)
            if isinstance(value, set):
                continue
            params[attr_name] = value

        params["umodel_export_dir"] = umodel_export_dir
        try:
            _write_import_params_cache(params)
        except OSError as exc:
            self.report({"WARNING"}, localization.t_report(f"Could not save import parameter cache: {exc}"))

    def _selected_map_paths(self) -> list[str]:
        raw_map_paths = getattr(self, "map_paths", "")
        if raw_map_paths:
            try:
                map_paths = json.loads(raw_map_paths)
            except json.JSONDecodeError:
                return []
            if isinstance(map_paths, list):
                return [path for path in map_paths if isinstance(path, str) and path]

        filepath = getattr(self, "filepath", "")
        return [filepath] if filepath else []


def menu_func_import(menu: bpy.types.Menu, _: bpy.types.Context) -> None:
    menu.layout.operator(UMODELTOOLS_OT_select_unreal_map_json.bl_idname)


def bl_register() -> None:
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def bl_unregister() -> None:
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
