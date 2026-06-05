import json

import bpy

from .preferences import get_addon_preferences
from . import localization
from .ueformat import conflicts as ueformat_conflicts


class UMODELTOOLS_PT_asset(bpy.types.Panel):
    bl_region_type = 'WINDOW'
    bl_space_type = 'PROPERTIES'
    bl_context = "object"
    bl_label = "UModel Tools Asset"

    @classmethod
    def poll(cls, context: bpy.types.Context):
        return (context.scene is not None
                and context.object is not None
                and context.object.type == 'MESH')

    def draw_header(self, context: bpy.types.Context):
        return self.layout.prop(data=context.object.umodel_tools_asset, property='enabled', text="")

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        layout.enabled = context.object.umodel_tools_asset.enabled

        layout.prop(data=context.object.umodel_tools_asset, property='asset_path')


class UMODELTOOLS_PG_asset(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Enabled",
        description="Toggles whether the object is treated as an Unreal asset",
        default=False
    )

    asset_path: bpy.props.StringProperty(
        name="Asset path",
        description="Path of the asset in the Unreal engine game"
    )

    is_ueformat_asset: bpy.props.BoolProperty(default=False)

    ueformat_context_json: bpy.props.StringProperty(default="")

    ueformat_conflict_store_path: bpy.props.StringProperty(default="", subtype='FILE_PATH')

    show_ueformat_material_conflicts: bpy.props.BoolProperty(
        name="Material JSON Conflicts",
        default=True
    )

    show_ueformat_texture_conflicts: bpy.props.BoolProperty(
        name="Texture Conflicts",
        default=True
    )


class UMODELTOOLS_PT_ueformat_asset_tools(bpy.types.Panel):
    bl_region_type = 'UI'
    bl_space_type = 'VIEW_3D'
    bl_category = "UModel Tools"
    bl_label = "UEFormat Asset"

    @classmethod
    def poll(cls, context: bpy.types.Context):
        obj = getattr(context, "object", None)
        props = getattr(obj, "umodel_tools_asset", None) if obj is not None else None
        return bool(props is not None and getattr(props, "is_ueformat_asset", False))

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        props = context.object.umodel_tools_asset
        layout.label(text=getattr(props, "asset_path", ""))
        layout.operator("umodel_tools.rebuild_ueformat_asset_materials", icon='FILE_REFRESH')

        records = _ueformat_conflict_records(props.ueformat_conflict_store_path)
        material_records = [record for record in records if record.key.kind == "material_json"]
        texture_records = [record for record in records if record.key.kind == "texture"]

        _draw_conflict_group(
            layout,
            props,
            prop_name="show_ueformat_material_conflicts",
            title=localization.t_iface("Material JSON Conflicts"),
            records=material_records,
            conflict_store_path=props.ueformat_conflict_store_path,
        )
        _draw_conflict_group(
            layout,
            props,
            prop_name="show_ueformat_texture_conflicts",
            title=localization.t_iface("Texture Conflicts"),
            records=texture_records,
            conflict_store_path=props.ueformat_conflict_store_path,
        )


def _ueformat_conflict_records(conflict_store_path: str) -> tuple[ueformat_conflicts.ConflictRecord, ...]:
    if not conflict_store_path:
        return tuple()
    return ueformat_conflicts.UEFormatConflictStore(conflict_store_path).records()


def _draw_conflict_group(
    layout,
    props: UMODELTOOLS_PG_asset,
    prop_name: str,
    title: str,
    records: list[ueformat_conflicts.ConflictRecord],
    conflict_store_path: str,
) -> None:
    row = layout.row(align=True)
    row.prop(
        props,
        prop_name,
        text=f"{title} ({len(records)})",
        icon='TRIA_DOWN' if getattr(props, prop_name) else 'TRIA_RIGHT',
    )
    if not getattr(props, prop_name):
        return

    box = layout.box()
    if not records:
        box.label(text=localization.t_iface("No conflicts recorded."))
        return

    for record in records:
        item_box = box.box()
        label = record.key.material_slot or record.key.original_reference
        if record.key.parameter_name:
            label = f"{label} / {record.key.parameter_name}"
        item_box.label(text=f"{label}: {record.status}")
        if record.selected_override:
            item_box.label(text=f"{localization.t_iface('Selected')}: {record.selected_override}")
        if not record.candidates:
            item_box.label(text=localization.t_iface("No candidates recorded."))
            continue
        for candidate in record.candidates:
            op = item_box.operator(
                "umodel_tools.apply_ueformat_conflict_choice",
                text=candidate,
                icon='CHECKMARK' if candidate == record.selected_override else 'BLANK1',
            )
            op.conflict_store_path = conflict_store_path
            op.key_json = json.dumps(record.key.to_json(), ensure_ascii=False, sort_keys=True)
            op.selected_path = candidate


def topbar_menu_func(menu: bpy.types.Menu, context: bpy.types.Context):
    if context.region.alignment != 'RIGHT':
        return

    prefs = get_addon_preferences()

    if not prefs.display_cur_profile:
        return

    cur_profile = prefs.get_active_profile()
    menu.layout.label(
        text=f"{localization.t_iface('UMT Active profile')}: {cur_profile.name if cur_profile else None}"
    )


def bl_register() -> None:
    # pylint: disable=assignment-from-no-return

    bpy.types.Object.umodel_tools_asset = bpy.props.PointerProperty(type=UMODELTOOLS_PG_asset)
    bpy.types.TOPBAR_HT_upper_bar.append(topbar_menu_func)


def bl_unregister() -> None:
    del bpy.types.Object.umodel_tools_asset
    bpy.types.TOPBAR_HT_upper_bar.remove(topbar_menu_func)
