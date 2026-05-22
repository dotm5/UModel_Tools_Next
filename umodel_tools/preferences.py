import typing as t

import bpy

from . import PACKAGE_NAME
from . import game_profiles
from . import localization


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

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        layout.prop(self, "display_cur_profile")
        layout.prop(self, "verbose")
        layout.prop(self, "show_advanced_import_validation_settings",
                    icon='TRIA_DOWN' if self.show_advanced_import_validation_settings else 'TRIA_RIGHT')
        layout.prop(self, "show_advanced_path_resolution_settings",
                    icon='TRIA_DOWN' if self.show_advanced_path_resolution_settings else 'TRIA_RIGHT')

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
