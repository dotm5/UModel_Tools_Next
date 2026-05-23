import os
import shutil
import typing as t

import bpy
import bpy_extras.io_utils

from . import PACKAGE_NAME
from . import game_profiles
from . import localization
from . import material_rules
from . import missing_asset_report


def get_addon_preferences() -> 'UMODELTOOLS_AP_addon_preferences':
    """Returns this addon's preferences.

    :return: Addon preferences.
    """
    return bpy.context.preferences.addons[PACKAGE_NAME].preferences


class UMODELTOOLS_PG_game_profile(bpy.types.PropertyGroup):
    """Game profile settings
    """

    name: bpy.props.StringProperty(
        name="Name",
        description="Name of the profile"
    )

    game: bpy.props.EnumProperty(
        name="Game",
        description="Game of this profile",
        items=game_profiles.SUPPORTED_GAMES,
        default=0
    )

    umodel_export_dir: bpy.props.StringProperty(
        name="UModel Export Directory",
        description="Path to the UModel export directory with game assets",
        subtype='DIR_PATH'
    )

    asset_dir: bpy.props.StringProperty(
        name="Asset Directory",
        description="Path to the directory where the assets for current project are stored",
        subtype='DIR_PATH'
    )


class UMODELTOOLS_UL_game_profiles(bpy.types.UIList):
    """UIlist for displaying game profiles."""

    def draw_item(self,
                  _context: bpy.types.Context,
                  layout: bpy.types.UILayout,
                  _prefs: 'UMODELTOOLS_AP_addon_preferences',
                  game_profile: UMODELTOOLS_PG_game_profile,
                  icon: str,
                  _active_prefs: 'UMODELTOOLS_AP_addon_preferences',
                  _active_propname: str,
                  _index: int,
                  _flt_flag: int):
        layout.prop(game_profile, "name", text="", emboss=False, icon_value=icon)


class UMODELTOOLS_PG_material_rule_dataset(bpy.types.PropertyGroup):
    """Material texture rule dataset settings."""

    name: bpy.props.StringProperty(
        name="Name",
        description="Name of the material rule dataset"
    )

    path: bpy.props.StringProperty(
        name="Rule YAML Path",
        description="Path to a material texture rule YAML file",
        subtype='FILE_PATH'
    )

    enabled: bpy.props.BoolProperty(
        name="Enabled",
        description="Use this dataset when reconstructing material shader nodes",
        default=True
    )


class UMODELTOOLS_UL_material_rule_datasets(bpy.types.UIList):
    """UIlist for displaying material rule datasets."""

    def draw_item(self,
                  _context: bpy.types.Context,
                  layout: bpy.types.UILayout,
                  _prefs: 'UMODELTOOLS_AP_addon_preferences',
                  dataset: UMODELTOOLS_PG_material_rule_dataset,
                  _icon: str,
                  _active_prefs: 'UMODELTOOLS_AP_addon_preferences',
                  _active_propname: str,
                  _index: int,
                  _flt_flag: int):
        row = layout.row(align=True)
        row.prop(dataset, "enabled", text="")
        icon = 'CHECKMARK' if os.path.isfile(_normalize_rule_dataset_path(dataset.path)) else 'ERROR'
        row.prop(dataset, "name", text="", emboss=False, icon=icon)


class UMODELTOOLS_OT_actions(bpy.types.Operator):
    """Move items up and down, add and remove"""

    bl_idname = "umodel_tools.list_action"
    bl_label = "List Actions"
    bl_description = "Move items up and down, add and remove"
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    action: bpy.props.EnumProperty(
        items=(
            ('UP', "Up", ""),
            ('DOWN', "Down", ""),
            ('REMOVE', "Remove", ""),
            ('ADD', "Add", "")
        )
    )

    def invoke(self, _context: bpy.types.Context, _event: bpy.types.Event) -> set[str]:
        addon_prefs = get_addon_preferences()
        idx = addon_prefs.active_profile_index

        try:
            addon_prefs.profiles[idx]
        except IndexError:
            pass
        else:
            if self.action == 'DOWN' and idx < len(addon_prefs.profiles) - 1:
                addon_prefs.profiles.move(idx, idx + 1)
                addon_prefs.active_profile_index += 1

            elif self.action == 'UP' and idx >= 1:
                addon_prefs.profiles.move(idx, idx - 1)
                addon_prefs.active_profile_index -= 1

            elif self.action == 'REMOVE':
                addon_prefs.profiles.remove(idx)
                if addon_prefs.active_profile_index != 0:
                    addon_prefs.active_profile_index -= 1

        if self.action == 'ADD':
            profile = addon_prefs.profiles.add()
            profile.name = "New Profile"
            addon_prefs.active_profile_index = len(addon_prefs.profiles) - 1

        return {"FINISHED"}


class UMODELTOOLS_OT_material_rule_dataset_actions(bpy.types.Operator):
    """Move and remove material rule datasets."""

    bl_idname = "umodel_tools.material_rule_dataset_action"
    bl_label = "Material Rule Dataset Actions"
    bl_description = "Move and remove material rule datasets"
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    action: bpy.props.EnumProperty(
        items=(
            ('UP', "Up", ""),
            ('DOWN', "Down", ""),
            ('REMOVE', "Remove", "")
        )
    )

    def invoke(self, _context: bpy.types.Context, _event: bpy.types.Event) -> set[str]:
        addon_prefs = get_addon_preferences()
        addon_prefs.ensure_material_rule_datasets()
        idx = addon_prefs.active_material_rule_dataset_index

        try:
            addon_prefs.material_rule_datasets[idx]
        except IndexError:
            return {"FINISHED"}

        if self.action == 'DOWN' and idx < len(addon_prefs.material_rule_datasets) - 1:
            addon_prefs.material_rule_datasets.move(idx, idx + 1)
            addon_prefs.active_material_rule_dataset_index += 1
        elif self.action == 'UP' and idx >= 1:
            addon_prefs.material_rule_datasets.move(idx, idx - 1)
            addon_prefs.active_material_rule_dataset_index -= 1
        elif self.action == 'REMOVE':
            addon_prefs.material_rule_datasets.remove(idx)
            if addon_prefs.active_material_rule_dataset_index != 0:
                addon_prefs.active_material_rule_dataset_index -= 1
            addon_prefs.ensure_material_rule_datasets()

        return {"FINISHED"}


class UMODELTOOLS_OT_add_material_rule_dataset(bpy.types.Operator, bpy_extras.io_utils.ImportHelper):
    """Load a material rule dataset YAML file."""

    bl_idname = "umodel_tools.add_material_rule_dataset"
    bl_label = "Load Material Rule Dataset"
    bl_description = "Add a material texture rule YAML dataset"
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    filename_ext = ".yaml"

    filter_glob: bpy.props.StringProperty(
        default="*.yaml;*.yml",
        options={'HIDDEN'},
        maxlen=255
    )

    def execute(self, _context: bpy.types.Context) -> set[str]:
        if not self.filepath:
            self.report({'ERROR'}, localization.t_report("Asset path was not provided."))
            return {'CANCELLED'}

        addon_prefs = get_addon_preferences()
        addon_prefs.add_material_rule_dataset(self.filepath)
        addon_prefs.active_material_rule_dataset_index = len(addon_prefs.material_rule_datasets) - 1
        return {"FINISHED"}


class UMODELTOOLS_AP_addon_preferences(bpy.types.AddonPreferences):
    """Implements preferences storage for the addon.
    """

    bl_idname = PACKAGE_NAME

    profiles: bpy.props.CollectionProperty(
        name="Profiles",
        description="Saved game profiles",
        type=UMODELTOOLS_PG_game_profile
    )

    active_profile_index: bpy.props.IntProperty(
        default=0
    )

    material_rule_datasets: bpy.props.CollectionProperty(
        name="Material Rule Datasets",
        description="Texture pattern rule YAML datasets used for material reconstruction",
        type=UMODELTOOLS_PG_material_rule_dataset
    )

    active_material_rule_dataset_index: bpy.props.IntProperty(
        default=0
    )

    show_material_rule_dataset_settings: bpy.props.BoolProperty(
        name="Show Material Rule Dataset Settings",
        description="Show material texture rule dataset settings",
        default=True
    )

    display_cur_profile: bpy.props.BoolProperty(
        name="Display current profile",
        description="Display current profile on top of Blender's window",
        default=True
    )

    verbose: bpy.props.BoolProperty(
        name="Verbose import",
        description="Print detailed logging information on import",
        default=False
    )

    default_import_storage_mode: bpy.props.EnumProperty(
        name="Default Import Storage Mode",
        description="Default storage behavior for Unreal Map imports",
        items=[
            ('LINKED_ASSET_LIBRARY', "Linked Asset Library", "Reuse cached asset blend files as linked libraries"),
            ('LOCAL_SINGLE_FILE', "Local Single File", "Append imported assets as editable local datablocks"),
            ('APPEND_AS_LOCAL', "Append Asset Library as Local", "Use the asset cache, then append assets locally")
        ],
        default='LINKED_ASSET_LIBRARY'
    )

    editable_materials_by_default: bpy.props.BoolProperty(
        name="Editable Materials by Default",
        description="Suggest Local Single File mode for new map imports",
        default=False
    )

    default_load_pbr_maps: bpy.props.BoolProperty(
        name="Default Load PBR Textures",
        description="Default whether map imports restore normal, roughness, specular, and related texture maps",
        default=True
    )

    default_import_backface_culling: bpy.props.BoolProperty(
        name="Default Use Backface Culling",
        description="Default whether map imports preserve material backface culling settings",
        default=False
    )

    default_texture_format: bpy.props.EnumProperty(
        name="Default Texture Format",
        description="Default texture file extension expected in the UModel export directory",
        items=[
            ('.png', '.png', '', 0),
            ('.dds', '.dds', '', 1),
            ('.tga', '.tga', '', 2)
        ],
        default='.png'
    )

    recent_umodel_export_dir: bpy.props.StringProperty(
        name="Recent UModel Export Directory",
        description="Most recent UModel export directory used from File > Import",
        subtype='DIR_PATH'
    )

    recent_asset_cache_dir: bpy.props.StringProperty(
        name="Recent Asset Cache Directory",
        description="Most recent asset cache directory used from File > Import",
        subtype='DIR_PATH'
    )

    manual_asset_cache_dir: bpy.props.StringProperty(
        name="Manual Asset Cache Directory",
        description=(
            "Optional developer override for map import asset cache; "
            "empty uses UModel Export Directory/temp-assets"
        ),
        subtype='DIR_PATH'
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

    show_advanced_import_validation_settings: bpy.props.BoolProperty(
        name="Show Advanced Import Validation Settings",
        description="Show advanced import validation settings",
        default=False
    )

    enable_import_validation: bpy.props.BoolProperty(
        name="Enable Import Validation",
        description="Validate imported scene counts and common data issues after map import",
        default=True
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

    fail_on_traceback_like_errors: bpy.props.BoolProperty(
        name="Fail on traceback-like CLI errors",
        description="Fail CLI/test validation when captured logs contain API traceback markers",
        default=True
    )

    allow_missing_placeholder_materials: bpy.props.BoolProperty(
        name="Allow Missing Placeholder Materials",
        description="Treat placeholder materials as warnings instead of validation errors",
        default=True
    )

    show_advanced_path_resolution_settings: bpy.props.BoolProperty(
        name="Show Advanced Path Resolution Settings",
        description="Show advanced UModel path resolution settings",
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

    path_inference_mode: bpy.props.EnumProperty(
        name="Path Inference Mode",
        description="Controls how aggressively UModel export paths are resolved",
        items=[
            ('BASIC_DEFAULT', "Basic Default", "Exact lookup plus common UModel mount truncation aliases"),
            ('STRICT_EXACT', "Strict Exact", "Only use direct legacy path matching"),
            ('AGGRESSIVE', "Aggressive", "Use exact matching, mount truncation, and suffix index lookup")
        ],
        default='BASIC_DEFAULT'
    )

    debug: bpy.props.BoolProperty(
        name="Debug",
        description="Enables debugging output, intended for developers only",
        default=False
    )

    def get_active_profile(self) -> t.Optional[UMODELTOOLS_PG_game_profile]:
        try:
            return self.profiles[self.active_profile_index]
        except IndexError:
            return None

    def ensure_material_rule_datasets(self) -> None:
        if len(self.material_rule_datasets):
            return

        name, path = _copy_default_rule_dataset_to_user_dir()
        self.add_material_rule_dataset(path=path, name=name)
        self.active_material_rule_dataset_index = 0

    def add_material_rule_dataset(self,
                                  path: str,
                                  name: str = "",
                                  enabled: bool = True) -> UMODELTOOLS_PG_material_rule_dataset:
        normalized_path = _copy_rule_dataset_to_user_dir(path)
        for index, dataset in enumerate(self.material_rule_datasets):
            if _same_rule_dataset_path(dataset.path, normalized_path):
                dataset.enabled = enabled
                if name:
                    dataset.name = name
                self.active_material_rule_dataset_index = index
                return dataset

        dataset = self.material_rule_datasets.add()
        dataset.path = normalized_path
        dataset.name = name or material_rules.dataset_display_name(normalized_path)
        dataset.enabled = enabled
        return dataset

    def get_active_material_rule_dataset_paths(self) -> list[str]:
        self.ensure_material_rule_datasets()
        paths = [
            _normalize_rule_dataset_path(dataset.path)
            for dataset in self.material_rule_datasets
            if dataset.enabled and dataset.path
        ]
        if paths:
            return paths

        _, fallback_path = _copy_default_rule_dataset_to_user_dir()
        return [fallback_path]

    def draw(self, context: bpy.types.Context):
        self.ensure_material_rule_datasets()
        layout = self.layout
        layout.prop(self, "display_cur_profile")
        layout.prop(self, "verbose")
        layout.prop(self, "default_import_storage_mode")
        layout.prop(self, "editable_materials_by_default")
        layout.prop(self, "default_load_pbr_maps")
        layout.prop(self, "default_texture_format")
        layout.prop(self, "default_import_backface_culling")
        layout.prop(self, "manual_asset_cache_dir")
        layout.prop(self, "save_missing_asset_report")
        layout.prop(self, "max_missing_assets_printed_to_console")
        layout.prop(self, "show_advanced_import_validation_settings",
                    icon='TRIA_DOWN' if self.show_advanced_import_validation_settings else 'TRIA_RIGHT')
        layout.prop(self, "show_advanced_path_resolution_settings",
                    icon='TRIA_DOWN' if self.show_advanced_path_resolution_settings else 'TRIA_RIGHT')
        layout.prop(self, "show_material_rule_dataset_settings",
                    icon='TRIA_DOWN' if self.show_material_rule_dataset_settings else 'TRIA_RIGHT')

        if self.show_advanced_import_validation_settings:
            box = layout.box()
            box.label(text=localization.t_iface("Advanced Import Validation"))
            box.prop(self, "enable_import_validation")
            box.prop(self, "validation_preset")

            col = box.column()
            col.enabled = self.validation_preset == 'CUSTOM'
            col.prop(self, "min_mesh_count")
            col.prop(self, "min_light_count")
            col.prop(self, "min_material_count")
            col.prop(self, "require_any_material_assigned")

            box.prop(self, "reject_dict_like_names")
            box.prop(self, "fail_on_traceback_like_errors")
            box.prop(self, "allow_missing_placeholder_materials")

        if self.show_advanced_path_resolution_settings:
            box = layout.box()
            box.label(text=localization.t_iface("Advanced Path Resolution"))
            box.prop(self, "enable_umodel_path_inference")
            path_col = box.column()
            path_col.enabled = self.enable_umodel_path_inference
            path_col.prop(self, "path_inference_mode")
            path_col.prop(self, "enable_suffix_index")
            box.prop(self, "report_path_resolution_stats")

            box.label(text=localization.t_iface("Advanced Missing Asset Handling"))
            box.prop(self, "missing_asset_report_format")
            box.prop(self, "deduplicate_missing_assets")
            box.prop(self, "missing_asset_report_directory_mode")
            if self.missing_asset_report_directory_mode == missing_asset_report.DIRECTORY_CUSTOM:
                box.prop(self, "custom_missing_asset_report_directory")
            box.prop(self, "include_actor_context_in_missing_report")

        if self.show_material_rule_dataset_settings:
            self._draw_material_rule_datasets(layout)

        if context.preferences.view.show_developer_ui:
            layout.prop(self, "debug")

        layout.label(text=localization.t_iface("Game profiles:"))
        row = layout.row()
        row.template_list("UMODELTOOLS_UL_game_profiles", "", self, "profiles", self, "active_profile_index")

        col = row.column(align=True)
        col.operator(UMODELTOOLS_OT_actions.bl_idname, icon='ADD', text="").action = 'ADD'
        col.operator(UMODELTOOLS_OT_actions.bl_idname, icon='REMOVE', text="").action = 'REMOVE'

        col.separator()
        col.operator(UMODELTOOLS_OT_actions.bl_idname, icon='TRIA_UP', text="").action = 'UP'
        col.operator(UMODELTOOLS_OT_actions.bl_idname, icon='TRIA_DOWN', text="").action = 'DOWN'

        try:
            game_profile = self.profiles[self.active_profile_index]
        except IndexError:
            pass
        else:
            layout.separator()
            layout.label(text=localization.t_iface("Profile settings:"))

            layout.prop(game_profile, "game")
            layout.prop(game_profile, "umodel_export_dir")
            layout.prop(game_profile, "asset_dir")

    def _draw_material_rule_datasets(self, layout: bpy.types.UILayout) -> None:
        box = layout.box()
        box.label(text=localization.t_iface("Material rule datasets:"))

        row = box.row()
        row.template_list(
            "UMODELTOOLS_UL_material_rule_datasets",
            "",
            self,
            "material_rule_datasets",
            self,
            "active_material_rule_dataset_index"
        )

        col = row.column(align=True)
        col.operator(UMODELTOOLS_OT_add_material_rule_dataset.bl_idname, icon='ADD', text="")
        col.operator(UMODELTOOLS_OT_material_rule_dataset_actions.bl_idname, icon='REMOVE', text="").action = 'REMOVE'

        col.separator()
        col.operator(UMODELTOOLS_OT_material_rule_dataset_actions.bl_idname, icon='TRIA_UP', text="").action = 'UP'
        col.operator(UMODELTOOLS_OT_material_rule_dataset_actions.bl_idname, icon='TRIA_DOWN', text="").action = 'DOWN'

        active_dataset = self._active_material_rule_dataset()
        if active_dataset is not None:
            box.prop(active_dataset, "path")

        box.label(
            text=localization.t_iface("Rule files are copied to the user UTM rule directory."),
            icon='FILE_FOLDER'
        )

        enabled_paths = self.get_active_material_rule_dataset_paths()
        _, fallback_path = _copy_default_rule_dataset_to_user_dir()
        if enabled_paths == [fallback_path] and not any(
            dataset.enabled for dataset in self.material_rule_datasets
        ):
            box.label(text=localization.t_iface("No enabled datasets; Generic fallback will be used."), icon='INFO')

    def _active_material_rule_dataset(self) -> t.Optional[UMODELTOOLS_PG_material_rule_dataset]:
        try:
            return self.material_rule_datasets[self.active_material_rule_dataset_index]
        except IndexError:
            return None


def _normalize_rule_dataset_path(path: str) -> str:
    if not path:
        return ""

    return os.path.abspath(os.path.normpath(bpy.path.abspath(path)))


def _copy_default_rule_dataset_to_user_dir() -> tuple[str, str]:
    name, path = material_rules.default_rule_dataset()
    return name, _copy_rule_dataset_to_user_dir(path, preferred_name="generic.yaml")


def _copy_rule_dataset_to_user_dir(path: str, preferred_name: str = "") -> str:
    source_path = _normalize_rule_dataset_path(path)
    if not source_path or not os.path.isfile(source_path):
        return source_path

    rule_dir = _material_rule_user_dir(create=True)
    if not rule_dir:
        return source_path

    try:
        source_real = os.path.realpath(source_path)
        rule_dir_real = os.path.realpath(rule_dir)
        if os.path.commonpath([source_real, rule_dir_real]) == rule_dir_real:
            return source_path
    except ValueError:
        pass

    file_name = _safe_rule_dataset_file_name(preferred_name or os.path.basename(source_path))
    target_path = _available_rule_dataset_path(rule_dir, file_name, allow_existing=bool(preferred_name))
    try:
        if os.path.isfile(target_path):
            return target_path
        if not _same_existing_file(source_path, target_path):
            shutil.copy2(source_path, target_path)
    except OSError as exc:
        print(f"Warning: Could not copy material rule dataset to user directory: {exc}")
        return source_path

    return target_path


def _material_rule_user_dir(create: bool = False) -> str:
    candidates = [
        os.path.join(os.path.expanduser("~"), "Documents", "Blender", "UTM", "rules"),
    ]

    try:
        config_dir = bpy.utils.user_resource(
            'CONFIG',
            path=os.path.join("UTM", "rules"),
            create=create
        )
    except (AttributeError, RuntimeError):
        config_dir = ""
    if config_dir:
        candidates.append(config_dir)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            if create:
                os.makedirs(candidate, exist_ok=True)
            if os.path.isdir(candidate):
                return candidate
        except OSError:
            continue

    return ""


def _safe_rule_dataset_file_name(file_name: str) -> str:
    base_name = os.path.basename(file_name) or "material_rules.yaml"
    stem, ext = os.path.splitext(base_name)
    if ext.lower() not in {".yaml", ".yml"}:
        ext = ".yaml"

    safe_stem = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in stem).strip("._")
    return f"{safe_stem or 'material_rules'}{ext}"


def _available_rule_dataset_path(rule_dir: str, file_name: str, allow_existing: bool) -> str:
    candidate = os.path.join(rule_dir, file_name)
    if allow_existing or not os.path.exists(candidate):
        return candidate

    stem, ext = os.path.splitext(file_name)
    index = 1
    while True:
        candidate = os.path.join(rule_dir, f"{stem}_{index}{ext}")
        if not os.path.exists(candidate):
            return candidate
        index += 1


def _same_existing_file(first: str, second: str) -> bool:
    if not os.path.isfile(second):
        return False
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _same_rule_dataset_path(first: str, second: str) -> bool:
    return os.path.normcase(_normalize_rule_dataset_path(first)) == os.path.normcase(
        _normalize_rule_dataset_path(second)
    )
