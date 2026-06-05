
import json
import os
import typing as t

import numpy as np
import bpy
import bpy_extras.io_utils
import mathutils as mu

from . import utils
from . import asset_importer
from . import map_importer
from . import preferences
from . import import_support
from . import localization
from . import umodel_path_resolver
from . import missing_asset_report
from . import game_profiles
from . import progress
from .materials import rules as rule_module
from .mesh_backends import backends as mesh_backends
from .ueformat import asset_context as ueformat_asset_context
from .ueformat import conflicts as ueformat_conflicts


def _get_object_aabb_verts(obj: bpy.types.Object) -> list[tuple[float, float, float]]:
    return [obj.matrix_world @ mu.Vector(corner) for corner in obj.bound_box]


def _normalize_dir_input(path: str) -> str:
    normalized = os.path.normpath(path) if path else ""
    return normalized[1:] if normalized.startswith(os.sep) else normalized


def _import_params_cache_path() -> str:
    return os.path.join(os.path.dirname(__file__), "last_import_params.json")


_IMPORT_PARAM_CACHE_VERSION = 1
_IMPORT_PARAM_CACHE_FIELDS = (
    "umodel_export_dir",
    "game_profile",
    "import_storage_mode",
    "load_pbr_maps",
    "texture_format",
    "import_backface_culling",
    "import_skeletal_mesh_as_static_fallback",
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


def _preferred_ueformat_export_dir(prefs: bpy.types.AddonPreferences) -> str:
    profile = prefs.get_active_profile()
    if profile is not None and profile.umodel_export_dir:
        return profile.umodel_export_dir
    return getattr(prefs, "recent_umodel_export_dir", "")


def _normalize_ueformat_asset_path(asset_path: str) -> str:
    normalized = os.path.normpath(asset_path.replace("\\", os.sep).replace("/", os.sep)) if asset_path else ""
    return normalized[1:] if normalized.startswith(os.sep) else normalized


def _ueformat_asset_path_from_source(source_path: str, export_dir: str) -> str:
    if source_path and export_dir:
        try:
            relpath = os.path.relpath(os.path.abspath(source_path), os.path.abspath(export_dir))
            if not relpath.startswith(".."):
                return os.path.normpath(relpath)
        except ValueError:
            pass
    return os.path.basename(source_path) if source_path else ""


def _ueformat_export_root_from_source_and_asset_path(source_path: str, asset_path: str) -> str:
    source_abs = os.path.abspath(source_path)
    normalized_asset_path = _normalize_ueformat_asset_path(asset_path)
    if not source_abs or not normalized_asset_path:
        return ""

    source_parts = source_abs.replace("\\", "/").split("/")
    asset_parts = normalized_asset_path.replace("\\", "/").split("/")
    if len(asset_parts) > len(source_parts):
        return ""
    if [part.lower() for part in source_parts[-len(asset_parts):]] != [part.lower() for part in asset_parts]:
        return ""
    root_parts = source_parts[:-len(asset_parts)]
    if not root_parts:
        return ""
    return os.path.normpath("/".join(root_parts))


class UMODELTOOLS_OT_recover_unreal_asset(asset_importer.AssetImporter, bpy.types.Operator):
    bl_idname = "umodel_tools.recover_unreal_asset"
    bl_label = "Recover Unreal Asset"
    bl_description = "Replaces selected object with an Unreal Engine asset from UModel dir, or attempts " \
                     "to transfer data to it, such as UV maps and materials"
    bl_options = {'REGISTER', 'UNDO'}

    asset_path: bpy.props.StringProperty(
        name="Asset path",
        description="Path to an alleged asset within the game"
    )

    def invoke(self, context: bpy.types.Context, _: bpy.types.Event) -> set[int] | set[str]:
        wm: bpy.types.WindowManager = context.window_manager

        return wm.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context) -> set[str]:
        self._unrecognized_texture_types.clear()

        if not self.asset_path:
            return self._op_message('ERROR', "Asset path was not provided.")

        selected_objects: t.Sequence[selected_objects] = context.selected_objects

        profile = preferences.get_addon_preferences().get_active_profile()
        if profile is None:
            return self._op_message('ERROR', "You need to have an active game profile selected.")

        umodel_export_dir: str = os.path.normpath(profile.umodel_export_dir)
        umodel_export_dir = umodel_export_dir[1:] if umodel_export_dir.startswith(os.sep) else umodel_export_dir

        if not umodel_export_dir:
            return self._op_message('ERROR', "You need to specify a UModel export dir in Scene properties.")

        if not os.path.isdir(umodel_export_dir):
            return self._op_message('ERROR', f"Path to UModel export dir {umodel_export_dir} does not exist.")

        asset_dir: str = os.path.normpath(profile.asset_dir)
        asset_dir = asset_dir[1:] if asset_dir.startswith(os.sep) else asset_dir

        if not asset_dir:
            return self._op_message('ERROR', "You need to specify an asset dir in Scene properties.")

        if not os.path.isdir(asset_dir):
            return self._op_message('ERROR', f"Path to asset dir {asset_dir} does not exist.")

        asset_path = os.path.normpath(self.asset_path)
        asset_path = asset_path[1:] if asset_path.startswith(os.sep) else asset_path
        asset = self._load_asset(context=context, asset_dir=asset_dir, asset_path=asset_path,
                                 umodel_export_dir=umodel_export_dir, game_profile=profile.game)

        if asset is None:
            self._op_message('ERROR', "Failed to import asset.")
            return {'CANCELLED'}

        asset_mesh = asset.data

        # attempt replacing selected object with an asset
        if context.selected_objects:
            for obj in context.selected_objects:

                if utils.compare_meshes(asset_mesh, obj.data):
                    vtx_source = np.array([v.co for v in asset_mesh.vertices])
                    vtx_target = np.array([obj.matrix_world @ v.co for v in obj.data.vertices])
                else:
                    vtx_source = np.array(_get_object_aabb_verts(asset))
                    vtx_target = np.array(_get_object_aabb_verts(obj))

                pad = lambda x: np.hstack([x, np.ones((x.shape[0], 1))])
                X = pad(vtx_source)
                Y = pad(vtx_target)

                A, _, _, _ = np.linalg.lstsq(X, Y, rcond=1)

                obj.hide_set(True)

                new_obj = bpy.data.objects.new(
                    name=utils.normalize_ue_name(f"{obj.name}_Replaced", fallback="Recovered_Asset"),
                    object_data=asset_mesh
                )
                new_obj.matrix_world = A
                new_obj.umodel_tools_asset.enabled = True
                new_obj.umodel_tools_asset.asset_path = self.asset_path

                context.collection.objects.link(new_obj)

        # import the asset as a new object
        else:
            new_obj = bpy.data.objects.new(
                name=utils.normalize_ue_name(f"{asset.name}_Instance", fallback="Asset_Instance"),
                object_data=asset_mesh
            )
            new_obj.umodel_tools_asset.enabled = True
            new_obj.umodel_tools_asset.asset_path = self.asset_path
            new_obj.location = context.scene.cursor.location
            new_obj.scale = (5, 5, 5)
            context.collection.objects.link(new_obj)
            new_obj.select_set(True)

        self._print_unrecognized_textures()

        if self._has_warnings:
            self._op_message('WARNING', "Asset import had warnnings. Check console for details.")

        return {'FINISHED'}


class UMODELTOOLS_OT_import_unreal_assets(asset_importer.AssetImporter, bpy.types.Operator):
    bl_idname = "umodel_tools.import_unreal_assets"
    bl_label = "Import Unreal Assets"
    bl_description = "Imports a subdirectory of assets to the specified asset directory"
    bl_options = {'REGISTER', 'UNDO'}

    asset_sub_dir: bpy.props.StringProperty(
        name="Asset subdir",
        description="Path to a subdirectory containing assets"
    )

    def invoke(self, context: bpy.types.Context, _: bpy.types.Event) -> set[int] | set[str]:
        wm: bpy.types.WindowManager = context.window_manager

        return wm.invoke_props_dialog(self)

    def execute(self, context: bpy.types.Context) -> set[str]:
        if not self.asset_sub_dir:
            return self._op_message('ERROR', "Asset path was not provided.")

        self._unrecognized_texture_types.clear()

        selected_objects: t.Sequence[selected_objects] = context.selected_objects

        profile = preferences.get_addon_preferences().get_active_profile()
        if profile is None:
            return self._op_message('ERROR', "You need to have an active game profile selected.")

        umodel_export_dir: str = os.path.normpath(profile.umodel_export_dir)
        umodel_export_dir = umodel_export_dir[1:] if umodel_export_dir.startswith(os.sep) else umodel_export_dir

        if not umodel_export_dir:
            return self._op_message('ERROR', "You need to specify a UModel export dir in Scene properties.")

        if not os.path.isdir(umodel_export_dir):
            return self._op_message('ERROR', f"Path to UModel export dir {umodel_export_dir} does not exist.")

        asset_dir: str = os.path.normpath(profile.asset_dir)
        asset_dir = asset_dir[1:] if asset_dir.startswith(os.sep) else asset_dir

        if not asset_dir:
            return self._op_message('ERROR', "You need to specify an asset dir in Scene properties.")

        if not os.path.isdir(asset_dir):
            return self._op_message('ERROR', f"Path to asset dir {asset_dir} does not exist.")

        asset_sub_dir = os.path.normpath(self.asset_sub_dir)
        asset_sub_dir = asset_sub_dir[1:] if asset_sub_dir.startswith(os.sep) else asset_sub_dir
        asset_sub_dir_abs = os.path.join(umodel_export_dir, asset_sub_dir)

        if not os.path.isdir(asset_sub_dir_abs):
            return self._op_message('ERROR', f"Path {asset_sub_dir_abs} does not exist.")

        supported_mesh_extensions = mesh_backends.get_supported_mesh_extensions()

        # count assets to be imported for progress bar display purposes
        total_models = 0
        for root, _, files in os.walk(asset_sub_dir_abs):
            for file in files:
                _, ext = os.path.splitext(file)
                if ext.lower() not in supported_mesh_extensions:
                    continue

                total_models += 1

        db = import_support.AssetDB(asset_dir)
        with progress.ProgressReporter(
            context=context,
            total=total_models,
            desc=localization.t_report("Importing assets"),
        ) as progress_bar:
            for root, _, files in os.walk(asset_sub_dir_abs):
                for file in files:
                    file_base, ext = os.path.splitext(file)
                    if ext.lower() not in supported_mesh_extensions:
                        continue

                    file_abs = os.path.join(root, file_base) + (ext if ext.lower() == ".uemodel" else '.uasset')
                    file_rel = os.path.relpath(file_abs, umodel_export_dir)

                    print(f"\n\n{localization.t_report('Importing asset')} {file_rel}...")
                    self._load_asset(context=context,
                                     asset_dir=asset_dir,
                                     asset_path=file_rel,
                                     umodel_export_dir=umodel_export_dir,
                                     load=False,
                                     db=db,
                                     game_profile=profile.game)

                    progress_bar.update(1)

        db.save_db()

        self._print_unrecognized_textures()

        if self._has_warnings:
            self._op_message('WARNING', "Asset import had warnnings. Check console for details.")

        return {'FINISHED'}


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
            self.report({'ERROR'}, localization.t_report("Asset path was not provided."))
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


class UMODELTOOLS_OT_select_ueformat_model(bpy.types.Operator, bpy_extras.io_utils.ImportHelper):
    bl_idname = "umodel_tools.select_ueformat_model"
    bl_label = "Import UEFormat Asset"
    bl_description = "Select a UEFormat .uemodel file before setting import paths"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".uemodel"

    filter_glob: bpy.props.StringProperty(
        default="*.uemodel",
        options={'HIDDEN'},
        maxlen=255
    )

    def invoke(self, context: bpy.types.Context, _: bpy.types.Event) -> set[str]:
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, _context: bpy.types.Context) -> set[str]:
        if not self.filepath:
            self.report({'ERROR'}, localization.t_report("Asset path was not provided."))
            return {'CANCELLED'}

        prefs = preferences.get_addon_preferences()
        export_dir = _preferred_ueformat_export_dir(prefs)
        asset_path = _ueformat_asset_path_from_source(self.filepath, export_dir)
        return bpy.ops.umodel_tools.import_ueformat_model(
            'INVOKE_DEFAULT',
            filepath=self.filepath,
            asset_path=asset_path,
            umodel_export_dir=export_dir,
        )


class UMODELTOOLS_OT_import_ueformat_model(asset_importer.AssetImporter, bpy.types.Operator):
    bl_idname = "umodel_tools.import_ueformat_model"
    bl_label = "Import UEFormat Asset"
    bl_description = "Import a UEFormat .uemodel with FModel JSON material reconstruction"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(
        name="UEFormat Model File",
        description="Selected .uemodel source file",
        subtype='FILE_PATH',
        options={'HIDDEN'}
    )

    asset_path: bpy.props.StringProperty(
        name="Asset Path",
        description="Game-relative asset path used inside the export root, for example PM/Content/.../Model.uemodel"
    )

    umodel_export_dir: bpy.props.StringProperty(
        name="UModel/FModel Export Directory",
        description="Root directory containing the .uemodel, material JSON, and textures",
        subtype='DIR_PATH'
    )

    asset_cache_dir: bpy.props.StringProperty(
        name="Asset Cache Directory",
        description="Directory where imported .blend asset caches are written",
        subtype='DIR_PATH'
    )

    game_profile: bpy.props.EnumProperty(
        name="Game Profile",
        description="Material and texture reconstruction profile used for this import",
        items=game_profiles.SUPPORTED_GAMES,
        default='generic'
    )

    path_inference_mode: bpy.props.EnumProperty(
        name="Path Inference Mode",
        description="Controls how aggressively UModel/FModel export paths are resolved",
        items=[
            ('BASIC_DEFAULT', "Basic Default", "Exact lookup plus common UModel mount truncation aliases"),
            ('STRICT_EXACT', "Strict Exact", "Only use direct path matching"),
            ('AGGRESSIVE', "Aggressive", "Use exact matching, mount truncation, and suffix index lookup")
        ],
        default='BASIC_DEFAULT'
    )

    enable_umodel_path_inference: bpy.props.BoolProperty(
        name="Enable UModel Path Inference",
        description="Resolve common UModel/FModel export mount point truncation automatically",
        default=True
    )

    enable_suffix_index: bpy.props.BoolProperty(
        name="Enable Suffix Index",
        description="Allow suffix-index lookup when Path Inference Mode is Aggressive",
        default=True
    )

    use_preferences_material_rules: bpy.props.BoolProperty(
        name="Use Preference Rule Datasets",
        description="Use enabled material rule datasets from add-on preferences",
        default=True
    )

    use_generic_material_rules: bpy.props.BoolProperty(
        name="Generic Rules",
        description="Use the bundled generic material rule dataset for this import",
        default=True
    )

    use_calabiyau_material_rules: bpy.props.BoolProperty(
        name="CalabiyauGame Rules",
        description="Use CalabiyauGame material rules for this import",
        default=False
    )

    use_wuthering_waves_material_rules: bpy.props.BoolProperty(
        name="Wuthering Waves Rules",
        description="Use Wuthering Waves material rules for this import",
        default=False
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        prefs = preferences.get_addon_preferences()
        if not self.umodel_export_dir:
            self.umodel_export_dir = _preferred_ueformat_export_dir(prefs)

        if self.filepath and not self.asset_path:
            self.asset_path = _ueformat_asset_path_from_source(self.filepath, self.umodel_export_dir)

        if self.filepath and self.asset_path and not self.umodel_export_dir:
            self.umodel_export_dir = _ueformat_export_root_from_source_and_asset_path(self.filepath, self.asset_path)

        self.asset_cache_dir = _resolve_asset_cache_dir(self.umodel_export_dir, prefs=prefs)
        self.game_profile = "generic"
        self.enable_umodel_path_inference = getattr(prefs, "enable_umodel_path_inference", True)
        self.path_inference_mode = getattr(prefs, "path_inference_mode", umodel_path_resolver.BASIC_DEFAULT)
        self.enable_suffix_index = getattr(prefs, "enable_suffix_index", True)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context: bpy.types.Context) -> None:
        layout = self.layout
        if self.filepath:
            layout.label(text=os.path.basename(self.filepath))
        layout.prop(self, "asset_path")
        layout.prop(self, "umodel_export_dir")
        layout.prop(self, "asset_cache_dir")
        layout.prop(self, "game_profile")
        layout.prop(self, "path_inference_mode")
        layout.prop(self, "enable_umodel_path_inference")
        path_col = layout.column()
        path_col.enabled = self.enable_umodel_path_inference
        path_col.prop(self, "enable_suffix_index")
        layout.prop(self, "use_preferences_material_rules")
        if not self.use_preferences_material_rules:
            layout.prop(self, "use_generic_material_rules")
            layout.prop(self, "use_calabiyau_material_rules")
            layout.prop(self, "use_wuthering_waves_material_rules")

    def execute(self, context: bpy.types.Context) -> set[str]:
        self._reset_import_runtime_state()
        source_path = os.path.abspath(self.filepath)
        if not source_path or not os.path.isfile(source_path):
            return self._op_message('ERROR', "You need to select an existing .uemodel file.")

        asset_path = _normalize_ueformat_asset_path(self.asset_path)
        if not asset_path:
            return self._op_message('ERROR', "You need to provide an asset path for the selected .uemodel.")
        if not os.path.splitext(asset_path)[1]:
            asset_path += ".uemodel"

        umodel_export_dir = _normalize_dir_input(self.umodel_export_dir)
        if not umodel_export_dir:
            umodel_export_dir = _ueformat_export_root_from_source_and_asset_path(source_path, asset_path)
        if not umodel_export_dir or not os.path.isdir(umodel_export_dir):
            return self._op_message('ERROR', "You need to specify an existing UModel/FModel export directory.")

        expected_source_path = os.path.abspath(os.path.join(umodel_export_dir, asset_path))
        if os.path.normcase(expected_source_path) != os.path.normcase(source_path):
            return self._op_message(
                'ERROR',
                "The selected .uemodel file does not match the provided export directory and asset path."
            )

        asset_dir = _resolve_asset_cache_dir(umodel_export_dir, self.asset_cache_dir)
        os.makedirs(asset_dir, exist_ok=True)

        prefs = preferences.get_addon_preferences()
        self.texture_format = getattr(prefs, "default_texture_format", ".png") if hasattr(prefs, "default_texture_format") else ".png"
        self.load_pbr_maps = getattr(prefs, "default_load_pbr_maps", True)
        self.import_backface_culling = getattr(prefs, "default_import_backface_culling", False)
        self.import_storage_mode = asset_importer.APPEND_AS_LOCAL
        self.mesh_import_backend = "UEMODEL"
        self.import_ueformat_skeleton = True
        self.import_ueformat_morph_targets = True
        rule_paths = _ueformat_rule_paths_from_operator(self, prefs)
        self.material_rule_paths_override = tuple(rule_paths)
        conflict_store_path = ueformat_conflicts.UEFormatConflictStore(asset_dir).path
        self.ueformat_conflict_store_path = conflict_store_path
        self.ueformat_asset_path = asset_path

        db = import_support.AssetDB(asset_dir)
        self._load_asset(
            context=context,
            asset_dir=asset_dir,
            asset_path=asset_path,
            umodel_export_dir=umodel_export_dir,
            load=False,
            db=db,
            game_profile=self.game_profile,
        )
        db.save_db()

        asset_blend = os.path.join(asset_dir, os.path.splitext(asset_path)[0]) + ".blend"
        if not os.path.isfile(asset_blend):
            return self._op_message('ERROR', "Failed to create UEFormat asset cache.")

        imported_objects = _append_asset_cache_objects(asset_blend, context.collection)
        main_object = _find_main_imported_object(imported_objects) or (imported_objects[0] if imported_objects else None)
        if main_object is not None:
            for obj in imported_objects:
                obj.select_set(False)
                _mark_ueformat_object(
                    obj=obj,
                    asset_path=asset_path,
                    source_path=source_path,
                    export_root=umodel_export_dir,
                    asset_cache_dir=asset_dir,
                    game_profile=self.game_profile,
                    path_inference_mode=self.path_inference_mode,
                    enable_suffix_index=self.enable_suffix_index,
                    rule_paths=rule_paths,
                    conflict_store_path=conflict_store_path,
                    material_slots=getattr(self, "_last_ueformat_material_slots", []),
                )
            main_object.select_set(True)
            context.view_layer.objects.active = main_object

        self._print_unrecognized_textures()
        if self._has_warnings:
            return self._op_message('WARNING', "UEFormat import completed with warnings. Check console for details.")
        return {'FINISHED'}


class UMODELTOOLS_OT_apply_ueformat_conflict_choice(bpy.types.Operator):
    bl_idname = "umodel_tools.apply_ueformat_conflict_choice"
    bl_label = "Apply UEFormat Conflict Choice"
    bl_description = "Save a project-local override for a UEFormat material or texture conflict"
    bl_options = {'REGISTER', 'UNDO'}

    conflict_store_path: bpy.props.StringProperty(
        name="Conflict Store Path",
        subtype='FILE_PATH',
        options={'HIDDEN'}
    )

    key_json: bpy.props.StringProperty(
        name="Conflict Key",
        options={'HIDDEN'}
    )

    selected_path: bpy.props.StringProperty(
        name="Selected Path",
        subtype='FILE_PATH'
    )

    def execute(self, _context: bpy.types.Context) -> set[str]:
        if not self.conflict_store_path:
            return self._finish('ERROR', "UEFormat conflict store path is missing.")
        if not self.key_json or not self.selected_path:
            return self._finish('ERROR', "UEFormat conflict choice is incomplete.")

        try:
            raw_key = json.loads(self.key_json)
            key = ueformat_conflicts.ConflictKey(
                kind=str(raw_key.get("kind", "")),
                uemodel_asset_path=str(raw_key.get("uemodel_asset_path", "")),
                material_slot=str(raw_key.get("material_slot", "")),
                parameter_name=str(raw_key.get("parameter_name", "")),
                original_reference=str(raw_key.get("original_reference", "")),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._finish('ERROR', f"Invalid UEFormat conflict key: {exc}")

        store = ueformat_conflicts.UEFormatConflictStore(self.conflict_store_path)
        store.set_override(key, self.selected_path)
        store.save()
        return self._finish('INFO', "UEFormat conflict choice saved.")

    def _finish(self, msg_type: str, message: str) -> set[str]:
        self.report({msg_type}, localization.t_report(message))
        return {'CANCELLED'} if msg_type == 'ERROR' else {'FINISHED'}


class UMODELTOOLS_OT_rebuild_ueformat_asset_materials(asset_importer.AssetImporter, bpy.types.Operator):
    bl_idname = "umodel_tools.rebuild_ueformat_asset_materials"
    bl_label = "Rebuild UEFormat Asset Materials"
    bl_description = "Rebuild material caches for the selected UEFormat asset without rebuilding texture caches"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        obj = getattr(context, "object", None)
        props = getattr(obj, "umodel_tools_asset", None) if obj is not None else None
        return bool(props is not None and getattr(props, "is_ueformat_asset", False))

    def execute(self, context: bpy.types.Context) -> set[str]:
        self._reset_import_runtime_state()
        obj = context.object
        props = obj.umodel_tools_asset
        try:
            asset_context = ueformat_asset_context.UEFormatAssetContext.from_dict(
                json.loads(props.ueformat_context_json or "{}")
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._finish('ERROR', f"Invalid UEFormat asset context: {exc}")

        if not asset_context.asset_cache_dir or not asset_context.export_root:
            return self._finish('ERROR', "UEFormat asset context is missing cache or export paths.")

        prefs = preferences.get_addon_preferences()
        self.texture_format = getattr(prefs, "default_texture_format", ".png") if hasattr(prefs, "default_texture_format") else ".png"
        self.load_pbr_maps = getattr(prefs, "default_load_pbr_maps", True)
        self.import_backface_culling = getattr(prefs, "default_import_backface_culling", False)
        self.enable_umodel_path_inference = True
        self.path_inference_mode = asset_context.path_inference_mode or umodel_path_resolver.BASIC_DEFAULT
        self.enable_suffix_index = asset_context.enable_suffix_index
        self.material_rule_paths_override = tuple(asset_context.material_rule_paths)
        self.ueformat_conflict_store_path = asset_context.conflict_store_path
        self.ueformat_asset_path = asset_context.uemodel_asset_path

        db = import_support.AssetDB(asset_context.asset_cache_dir)
        rebuilt_materials_by_path: dict[str, bpy.types.Material] = {}
        for index, slot in enumerate(asset_context.material_slots):
            material_name = _ueformat_slot_material_name(slot)
            descriptor_ref = str(slot.get("descriptor_ref", "") or "")
            if not material_name or not descriptor_ref:
                continue

            material_path_local, material_path_local_no_ext, status = _ueformat_material_rebuild_target(
                slot=slot,
                asset_context=asset_context,
            )
            material_lib_path = os.path.join(asset_context.asset_cache_dir, material_path_local_no_ext) + ".blend"
            material = rebuilt_materials_by_path.get(self._path_cache_key(material_lib_path))
            if material is None:
                self._material_cache_current.pop(self._path_cache_key(material_lib_path), None)
                self._forget_linked_library(material_lib_path)
                asset_importer._remove_loaded_material_library(material_lib_path)  # pylint: disable=protected-access

                try:
                    if status in {
                        asset_importer.PLACEHOLDER_MATERIAL_UNRESOLVED,
                        asset_importer.PLACEHOLDER_MATERIAL_AMBIGUOUS,
                    }:
                        asset_importer._write_placeholder_pbr_material_to_library(  # pylint: disable=protected-access
                            material_name=material_name,
                            material_path_local_no_ext=material_path_local_no_ext,
                            status=status,
                            material_lib_path=material_lib_path,
                            db=db,
                        )
                    else:
                        self._import_fmodel_json_material_to_library(
                            material_name=material_name,
                            material_path_local=material_path_local,
                            db=db,
                            umodel_export_dir=asset_context.export_root,
                            asset_library_dir=asset_context.asset_cache_dir,
                            game_profile=asset_context.game_profile or "generic",
                        )
                except (FileNotFoundError, OSError):
                    asset_importer._write_placeholder_pbr_material_to_library(  # pylint: disable=protected-access
                        material_name=material_name,
                        material_path_local_no_ext=material_path_local_no_ext,
                        status=asset_importer.PLACEHOLDER_MATERIAL_UNRESOLVED,
                        material_lib_path=material_lib_path,
                        db=db,
                    )

                self._material_cache_current[self._path_cache_key(material_lib_path)] = True
                material = self._load_material_from_library(material_lib_path)
                rebuilt_materials_by_path[self._path_cache_key(material_lib_path)] = material

            slot_index = int(slot.get("slot_index", index) or index)
            if slot_index < len(obj.data.materials):
                obj.material_slots[slot_index].material = material
            elif obj.data.materials.find(material_name) >= 0:
                obj.material_slots[obj.data.materials.find(material_name)].material = material
            else:
                obj.data.materials.append(material)

        db.save_db()

        return self._finish('INFO', "UEFormat asset materials rebuilt.")

    def _finish(self, msg_type: str, message: str) -> set[str]:
        self.report({msg_type}, localization.t_report(message))
        return {'CANCELLED'} if msg_type == 'ERROR' else {'FINISHED'}


def _ueformat_material_rebuild_target(
    *,
    slot: dict[str, t.Any],
    asset_context: ueformat_asset_context.UEFormatAssetContext,
) -> tuple[str, str, str]:
    material_name = _ueformat_slot_material_name(slot)
    descriptor_ref = str(slot.get("descriptor_ref", "") or "")
    status = str(slot.get("status", "resolved") or "resolved")
    conflict_key = ueformat_conflicts.ConflictKey(
        kind="material_json",
        uemodel_asset_path=asset_context.uemodel_asset_path,
        material_slot=material_name,
        parameter_name="",
        original_reference=descriptor_ref,
    )
    override = ueformat_conflicts.UEFormatConflictStore(asset_context.conflict_store_path).get_override(conflict_key)
    if override:
        material_path_local = _relative_ueformat_json_path(override, asset_context.export_root)
        return material_path_local, os.path.splitext(material_path_local)[0], "resolved"

    material_path_local_no_ext = os.path.splitext(descriptor_ref)[0]
    return material_path_local_no_ext + ".json", material_path_local_no_ext, status


def _relative_ueformat_json_path(path: str, export_root: str) -> str:
    if os.path.isabs(path):
        try:
            path = os.path.relpath(path, export_root)
        except ValueError:
            pass
    normalized = os.path.normpath(path)
    if normalized.startswith(os.sep):
        normalized = normalized[1:]
    if not normalized.lower().endswith(".json"):
        normalized += ".json"
    return normalized


def _ueformat_slot_material_name(slot: dict[str, t.Any]) -> str:
    material_name = str(slot.get("material_name", "") or "")
    if material_name:
        return material_name
    descriptor_ref = str(slot.get("descriptor_ref", "") or "")
    if descriptor_ref:
        _path, dotted_name = os.path.splitext(descriptor_ref)
        if dotted_name.startswith("."):
            return dotted_name[1:]
    return ""


def _ueformat_rule_paths_from_operator(
    operator: UMODELTOOLS_OT_import_ueformat_model,
    prefs: preferences.UMODELTOOLS_AP_addon_preferences,
) -> list[str]:
    if getattr(operator, "use_preferences_material_rules", True):
        return prefs.get_active_material_rule_dataset_paths()

    selected_rule_ids = []
    if getattr(operator, "use_generic_material_rules", True):
        selected_rule_ids.append("generic")
    if getattr(operator, "use_calabiyau_material_rules", False):
        selected_rule_ids.append("calabiyau_game")
    if getattr(operator, "use_wuthering_waves_material_rules", False):
        selected_rule_ids.append("wuthering_waves")
    if not selected_rule_ids:
        selected_rule_ids.append("generic")
    return [rule_module.default_rule_path(rule_id) for rule_id in selected_rule_ids]


def _mark_ueformat_object(
    *,
    obj: bpy.types.Object,
    asset_path: str,
    source_path: str,
    export_root: str,
    asset_cache_dir: str,
    game_profile: str,
    path_inference_mode: str,
    enable_suffix_index: bool,
    rule_paths: t.Sequence[str],
    conflict_store_path: str,
    material_slots: t.Sequence[dict[str, t.Any]],
) -> None:
    props = obj.umodel_tools_asset
    props.enabled = True
    props.asset_path = asset_path
    props.is_ueformat_asset = True
    props.ueformat_conflict_store_path = conflict_store_path

    slots = list(material_slots) or [
        {
            "slot_index": index,
            "material_name": getattr(material, "name", ""),
            "descriptor_ref": "",
        }
        for index, material in enumerate(getattr(getattr(obj, "data", None), "materials", []) or [])
    ]
    context = ueformat_asset_context.UEFormatAssetContext(
        uemodel_asset_path=asset_path,
        source_filepath=source_path,
        export_root=export_root,
        asset_cache_dir=asset_cache_dir,
        game_profile=game_profile,
        path_inference_mode=path_inference_mode,
        enable_suffix_index=enable_suffix_index,
        material_rule_paths=list(rule_paths),
        conflict_store_path=conflict_store_path,
        material_slots=slots,
    )
    props.ueformat_context_json = json.dumps(context.to_dict(), ensure_ascii=False, sort_keys=True)


def _append_asset_cache_objects(asset_blend: str, collection: bpy.types.Collection) -> list[bpy.types.Object]:
    with bpy.data.libraries.load(asset_blend, link=False) as (data_from, data_to):
        data_to.objects = list(data_from.objects)

    imported_objects = [obj for obj in data_to.objects if obj is not None]
    for obj in imported_objects:
        collection.objects.link(obj)
    return imported_objects


def _find_main_imported_object(objects: t.Sequence[bpy.types.Object]) -> bpy.types.Object | None:
    for obj in objects:
        if obj.get("umodel_tools_main_asset_object"):
            return obj
    for obj in objects:
        if obj.type == "MESH":
            return obj
    return None


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

    import_storage_mode: bpy.props.EnumProperty(
        name="Import Storage Mode",
        description="Controls whether imported assets stay linked from the cache or become editable local data",
        items=[
            ('LINKED_ASSET_LIBRARY', "Linked Asset Library", "Reuse cached asset blend files as linked libraries"),
            ('LOCAL_SINGLE_FILE', "Local Single File", "Append imported assets as editable local datablocks"),
            ('APPEND_AS_LOCAL', "Append Asset Library as Local", "Use the asset cache, then append assets locally")
        ],
        default='LINKED_ASSET_LIBRARY'
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
        layout.prop(self, "import_storage_mode")
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
            return self._op_message('ERROR', "Asset path was not provided.")

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
            self._op_message('WARNING', "Asset import had warnnings. Check console for details.")

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

        storage_mode = getattr(prefs, "default_import_storage_mode", asset_importer.LINKED_ASSET_LIBRARY)
        if getattr(prefs, "editable_materials_by_default", False):
            storage_mode = asset_importer.LOCAL_SINGLE_FILE
        default_params = {
            "game_profile": "generic",
            "import_storage_mode": storage_mode,
            "load_pbr_maps": getattr(prefs, "default_load_pbr_maps", True),
            "import_backface_culling": getattr(prefs, "default_import_backface_culling", False),
            "import_skeletal_mesh_as_static_fallback": getattr(
                prefs, "default_import_skeletal_mesh_as_static_fallback", True
            ),
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


class UMODELTOOLS_OT_realign_asset(bpy.types.Operator):
    bl_idname = "umodel_tools.realign_asset"
    bl_label = "Realign Unreal Asset"
    bl_description = "Attempt realigning the asset with a selected object boundary"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: bpy.types.Context) -> set[str]:

        if not len(context.selected_objects) == 2:
            self.report({'ERROR'}, localization.t_report("Exactly 2 objects must be selected."))
            return {'CANCELLED'}

        asset_idx = None
        for i, obj in enumerate(context.selected_objects):
            if obj.umodel_tools_asset.enabled:
                asset_idx = i
                break

        if asset_idx is None:
            self.report({'ERROR'}, localization.t_report("One of the objects must be an Unreal asset."))
            return {'CANCELLED'}

        asset_obj = context.selected_objects[asset_idx]
        target_obj = context.selected_objects[int(not asset_idx)]

        bpy.ops.object.select_all(action='DESELECT')

        asset_obj_copy = utils.copy_object(asset_obj)
        target_obj_copy = utils.copy_object(target_obj)

        context.collection.objects.link(asset_obj_copy)
        context.collection.objects.link(target_obj_copy)

        asset_obj_copy.select_set(True)
        target_obj_copy.select_set(True)

        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        vtx_source = np.array(_get_object_aabb_verts(asset_obj_copy))
        vtx_target = np.array(_get_object_aabb_verts(target_obj_copy))

        pad = lambda x: np.hstack([x, np.ones((x.shape[0], 1))])
        unpad = lambda x: x[:, :-1]
        X = pad(vtx_source)
        Y = pad(vtx_target)

        A, _, _, _ = np.linalg.lstsq(X, Y, rcond=1)

        transform = lambda x: unpad(pad(x) @ A)
        transformed_verts = transform(np.array([v.co for v in asset_obj_copy.data.vertices]))
        vtx_source_local = np.array([v.co for v in asset_obj.data.vertices])

        X = pad(vtx_source_local)
        Y = pad(transformed_verts)

        A, _, _, _ = np.linalg.lstsq(X, Y, rcond=1)

        target_obj.hide_set(True)
        asset_obj.matrix_world = A
        asset_obj.select_set(True)

        bpy.data.objects.remove(asset_obj_copy, do_unlink=True)
        bpy.data.objects.remove(target_obj_copy, do_unlink=True)

        return {'FINISHED'}


def menu_func_object(menu: bpy.types.Menu, _: bpy.types.Context) -> None:
    menu.layout.operator(UMODELTOOLS_OT_recover_unreal_asset.bl_idname)
    menu.layout.operator(UMODELTOOLS_OT_import_unreal_assets.bl_idname)
    menu.layout.operator(UMODELTOOLS_OT_realign_asset.bl_idname)


def menu_func_import(menu: bpy.types.Menu, _: bpy.types.Context) -> None:
    menu.layout.operator(UMODELTOOLS_OT_select_unreal_map_json.bl_idname)
    menu.layout.operator(UMODELTOOLS_OT_select_ueformat_model.bl_idname)


def bl_register() -> None:
    bpy.types.VIEW3D_MT_object.append(menu_func_object)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def bl_unregister() -> None:
    bpy.types.VIEW3D_MT_object.remove(menu_func_object)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
