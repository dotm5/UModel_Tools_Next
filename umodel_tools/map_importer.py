import json
import math
import os
import time
import typing as t
import enum

import mathutils as mu
import bpy

from . import import_support
from . import map_asset_cache
from . import utils
from . import localization
from . import missing_asset_report
from . import world_environment
from . import map_support
from . import map_scene_graph
from . import progress

from .map_support import InstanceTransform, StaticMesh, get_reference_transform_matrix


_SKELETAL_ENTITY_TYPES = {"SkeletalMeshComponent", "SkeletalMeshActor"}
_ARMATURE_ENTITY_TYPES = {"Skeleton", "Armature"}


def _classify_non_map_asset(entity_type: str) -> str:
    lowered = entity_type.lower()
    if entity_type in _SKELETAL_ENTITY_TYPES or "skeletalmesh" in lowered or "skeletal_mesh" in lowered:
        return "skeletal_mesh"
    if "morph" in lowered:
        return "morph_target"
    if "anim" in lowered or "psa" in lowered:
        return "animation"
    if entity_type in _ARMATURE_ENTITY_TYPES or "armature" in lowered or "skeleton" in lowered:
        return "armature"
    return ""


def create_light_data(name: t.Any, ue_light_type: str) -> bpy.types.Light | None:
    """Create a Blender light data-block from a supported UE light component type."""
    blender_light_type = GameLight.light_type_mapping.get(ue_light_type)
    if blender_light_type is None:
        utils.warn_ue_mapping("light", name, "Unsupported UE light component type.", ue_type=ue_light_type)
        return None

    light_type_prop = bpy.types.Light.bl_rna.properties["type"]
    supported_light_types = {item.identifier for item in light_type_prop.enum_items}
    if blender_light_type not in supported_light_types:
        utils.warn_ue_mapping(
            "light",
            name,
            "Mapped Blender light type is not supported by this Blender runtime.",
            ue_type=ue_light_type,
            blender_type=blender_light_type,
            supported=sorted(supported_light_types),
        )
        return None

    return bpy.data.lights.new(name=utils.normalize_ue_name(name, fallback="Light"), type=blender_light_type)


def _apply_world_environment_to_visible_scenes(context: bpy.types.Context, json_object: t.Any) -> int:
    scenes: list[bpy.types.Scene] = []
    for scene in (
        getattr(context, "scene", None),
        getattr(bpy.context, "scene", None),
        getattr(getattr(context, "window", None), "scene", None),
    ):
        if scene is not None and scene.name not in {item.name for item in scenes}:
            scenes.append(scene)

    applied = 0
    for scene in scenes:
        if world_environment.apply_world_environment(scene, json_object):
            applied += 1

    return applied


class GameLight:

    #: all entity types this reader supports
    light_types = [
        'SpotLightComponent',
        'RectLightComponent',
        'PointLightComponent',
        'DirectionalLightComponent'
    ]

    #: maps UE light types to Blender's light types
    light_type_mapping = {
        'SpotLightComponent': 'SPOT',
        'RectLightComponent': 'AREA',
        'PointLightComponent': 'POINT',
        'DirectionalLightComponent': 'SUN'
    }

    class IntensityUnits(enum.Enum):
        """All light intensity units supported by UE lights.
        """
        Unitless = enum.auto()
        Candelas = enum.auto()
        Lumens = enum.auto()

    #: maps intensity unit type json values to the enum
    light_intensity_units_mapping = {
        'ELightUnits::Unitless': IntensityUnits.Unitless,
        'ELightUnits::Candelas': IntensityUnits.Candelas,
        'ELightUnits::Lumens': IntensityUnits.Lumens
    }

    type: str = ""

    entity_name: str = ""
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rot: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    parent_mtx: t.Optional[mu.Matrix] = None
    intensity: float = math.pi
    intensity_units: IntensityUnits = IntensityUnits.Unitless
    cone_angle: float
    inner_cone_angle: float = 0.0
    cast_shadows: bool = False
    source_radius: bool = 0.0
    source_angle: float = 0.0
    attenuation_radius: float = 0.0
    source_width: float = 0.0
    source_height: float = 0.0

    no_entity = False

    color_temp_table_r = [
        [2.52432244e+03, -1.06185848e-03, 3.11067539e+00],
        [3.37763626e+03, -4.34581697e-04, 1.64843306e+00],
        [4.10671449e+03, -8.61949938e-05, 6.41423749e-01],
        [4.66849800e+03, 2.85655028e-05, 1.29075375e-01],
        [4.60124770e+03, 2.89727618e-05, 1.48001316e-01],
        [3.78765709e+03, 9.36026367e-06, 3.98995841e-01],
    ]

    color_temp_table_g = [
        [-7.50343014e+02, 3.15679613e-04, 4.73464526e-01],
        [-1.00402363e+03, 1.29189794e-04, 9.08181524e-01],
        [-1.22075471e+03, 2.56245413e-05, 1.20753416e+00],
        [-1.42546105e+03, -4.01730887e-05, 1.44002695e+00],
        [-1.18134453e+03, -2.18913373e-05, 1.30656109e+00],
        [-5.00279505e+02, -4.59745390e-06, 1.09090465e+00],
    ]

    color_temp_table_b = [
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [-2.02524603e-11, 1.79435860e-07, -2.60561875e-04, -1.41761141e-02],
        [-2.22463426e-13, -1.55078698e-08, 3.81675160e-04, -7.30646033e-01],
        [6.72595954e-13, -2.73059993e-08, 4.24068546e-04, -7.52204323e-01],
    ]

    @staticmethod
    def temp_to_color(temp: float) -> tuple[float, float, float]:
        """Convert kelvin temperature to lamp color

        :param temp: Temperature in Kelvin.
        :return: Color.
        """
        if temp >= 12000.0:
            return (0.826270103, 0.994478524, 1.56626022)
        if temp < 965.0:
            return (4.70366907, 0.0, 0.0)

        i = 0
        if temp >= 6365.0:
            i = 5
        elif temp >= 3315.0:
            i = 4
        elif temp >= 1902.0:
            i = 3
        elif temp >= 1449.0:
            i = 2
        elif temp >= 1167.0:
            i = 1
        else:
            i = 0

        r = GameLight.color_temp_table_r[i]
        g = GameLight.color_temp_table_g[i]
        b = GameLight.color_temp_table_b[i]

        temp_inv = 1 / temp
        return (r[0] * temp_inv + r[1] * temp + r[2],
                g[0] * temp_inv + g[1] * temp + g[2],
                ((b[0] * temp + b[1]) * temp + b[2]) * temp + b[3])

    @staticmethod
    def quaternion_to_euler(quaternion: mu.Quaternion) -> tuple[float, float, float]:
        w, y, x, z = quaternion
        roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
        pitch = math.asin(max(min(2 * (w * y - z * x), 1), -1))
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        return roll, pitch, yaw

    @staticmethod
    def normalize_rotation(x, y, z) -> tuple[float, float, float]:
        """
        Convert rotation from UE's coordinate system to Blender's coordinate system.
        This code seems to be specific for lights.

        :param x: X component.
        :param y: Y component.
        :param z: Z component.
        :return: Euler angle as tuple in Blender's coordinate space.
        """

        euler = mu.Euler((
            math.radians(x),
            math.radians(y),
            math.radians(z)
        ))

        quat = euler.to_quaternion()  # pylint: disable=assignment-from-no-return

        # swizzle the quaternion
        quat = mu.Quaternion([quat.w, quat.x, quat.y, -quat.z])

        x, y, z = GameLight.quaternion_to_euler(quat)

        x = math.degrees(-x) - 90
        y = math.degrees(-y)
        z = math.degrees(z) - 270

        return math.radians(x), math.radians(y), math.radians(z)

    @staticmethod
    def srgb_to_linear(s: int):
        """Converts a color channel from SRGB to linear color space.

        :param s: Color channel in SRGB color space.
        :return: Color channel in linear color space.
        """
        if s <= 0.0404482362771082:
            lin = s / 12.92
        else:
            lin = pow(((s + 0.055) / 1.055), 2.4)
        return lin

    @staticmethod
    def get_linear_rgb(color_prop: dict) -> tuple[float, float, float]:
        """Converts JSON color property to Blender color in linear color space.

        :param color_prop: Color property from .json.
        :return: Blender color in linear color space.
        """
        return (
            GameLight.srgb_to_linear(color_prop["R"] / 255),
            GameLight.srgb_to_linear(color_prop["G"] / 255),
            GameLight.srgb_to_linear(color_prop["B"] / 255)
        )

    @property
    def invalid(self) -> bool:
        return self.no_entity

    def __init__(
        self,
        json_obj,
        json_entity,
        scene_graph: map_scene_graph.FModelSceneGraph | None = None,
    ) -> None:
        self.entity_name = utils.normalize_ue_name(json_entity.get("Outer", 'Error'), fallback="Light")
        self.type = json_entity.get("Type", None)

        if not self.type:
            self.no_entity = True
            return None

        props = json_entity.get("Properties", None)
        if not props:
            print(f"Invalid Entity {self.entity_name}. Lacking properties.")
            self.no_entity = True
            return None

        if (pos := props.get("RelativeLocation", None)) is not None:
            self.pos = [pos.get("X") / 100, pos.get("Y") / -100, pos.get("Z") / 100]

        if (rot := props.get("RelativeRotation", None)) is not None:
            self.rot = GameLight.normalize_rotation(rot.get("Roll"), rot.get("Pitch"), rot.get("Yaw"))

        if (scale := props.get("RelativeScale3D", None)) is not None:
            self.scale = [scale.get("X", 1), scale.get("Y", 1), scale.get("Z", 1)]

        if isinstance((parent := props.get("AttachParent", None)), dict):
            self.parent_mtx = get_reference_transform_matrix(json_obj, parent, scene_graph)

        if (temp := props.get("Temperature", None)) is not None:
            self.color = self.temp_to_color(temp)

        # TODO: for now color overrides the temperature based setting if present. Check if they're mutually exclusive.
        if (color := props.get("LightColor", None)) is not None:
            self.color = self.get_linear_rgb(color)

        if (intensity := props.get("Intensity", None)) is not None:
            self.intensity = intensity

        if (intensity_units := props.get("IntensityUnits", None)) is not None:
            self.intensity_units = GameLight.light_intensity_units_mapping.get(intensity_units)

        self.cone_angle = 44.0 if self.type == 'SpotLightComponent' else 90.0

        if (cone_angle := props.get("OuterConeAngle", None)) is not None:
            self.cone_angle = cone_angle

        if (inner_cone_angle := props.get("InnerConeAngle", None)) is not None:
            self.inner_cone_angle = inner_cone_angle

        if (source_radius := props.get("SourceRadius", None)) is not None:
            self.source_radius = source_radius

        if (source_angle := props.get("LightSourceAngle", props.get("SourceAngle", None))) is not None:
            self.source_angle = source_angle

        if (cast_shadows := props.get("CastShadows", None)) is not None:
            self.cast_shadows = cast_shadows

        if (attenuation_radius := props.get("AttenuationRadius", None)) is not None:
            self.attenuation_radius = attenuation_radius

        if (source_width := props.get("SourceWidth", None)) is not None:
            self.source_width = source_width

        if (source_height := props.get("SourceHeight", None)) is not None:
            self.source_height = source_height

        return None

    def import_light(self, collection) -> bool:
        if self.no_entity:
            print(f"Refusing to import {self.entity_name} due to failed checks.")
            return False

        light_data = create_light_data(self.entity_name, self.type)
        if light_data is None:
            return False

        light_obj = bpy.data.objects.new(name=utils.normalize_ue_name(self.entity_name, fallback="Light"),
                                         object_data=light_data)

        if self.parent_mtx is None:
            light_obj.scale = (self.scale[0], self.scale[1], self.scale[2])
            light_obj.location = (self.pos[0], self.pos[1], self.pos[2])
            light_obj.rotation_mode = 'XYZ'
            light_obj.rotation_euler = mu.Euler((self.rot[0], self.rot[1], self.rot[2]), 'XYZ')
        else:
            local_mtx = InstanceTransform()
            local_mtx.pos = self.pos
            local_mtx.rot_euler = self.rot
            local_mtx.scale = self.scale

            light_obj.matrix_world = self.parent_mtx @ local_mtx.matrix_4x4

        light_data.use_custom_distance = True
        light_data.cutoff_distance = 1000 * 0.01  # default value

        if light_data.type == 'SPOT':
            light_data.spot_size = math.radians(self.cone_angle)
            light_data.spot_blend = 1.0 - (math.radians(self.inner_cone_angle) / math.radians(self.cone_angle))

        match light_data.type:
            case 'SPOT' | 'POINT':
                match self.intensity_units:
                    case GameLight.IntensityUnits.Unitless:
                        light_data.energy = (99.5 * (1 - math.cos(self.cone_angle / 2))) * self.intensity
                    case GameLight.IntensityUnits.Candelas:
                        light_data.energy = self.intensity * 683 / (4 * math.pi)
                    case GameLight.IntensityUnits.Lumens:
                        light_data.energy = self.intensity / 683

            case 'AREA':
                match self.intensity_units:
                    case GameLight.IntensityUnits.Unitless:
                        light_data.energy = self.intensity * 199 / 683
                    case GameLight.IntensityUnits.Candelas:
                        light_data.energy = self.intensity * 683 / (4 * math.pi)
                    case GameLight.IntensityUnits.Lumens:
                        light_data.energy = self.intensity / 683
            case 'SUN':
                light_data.energy = self.intensity
                if self.source_angle:
                    light_data.angle = math.radians(self.source_angle)

        light_data.color = self.color
        light_data.shadow_soft_size = self.source_radius * 0.01
        light_data.use_shadow = self.cast_shadows

        if hasattr(light_data, "cycles") and "cast_shadow" in light_data.cycles.bl_rna.properties:
            light_data.cycles.cast_shadow = self.cast_shadows

        if self.attenuation_radius:
            light_data.use_custom_distance = True
            light_data.cutoff_distance = self.attenuation_radius * 0.01

        if light_data.type == 'AREA':
            light_data.shape = 'RECTANGLE'
            light_data.size = self.source_width * 0.01
            light_data.size_y = self.source_height * 0.01

        collection.objects.link(light_obj)
        bpy.context.scene.collection.objects.link(light_obj)

        return True


class MapImporter(map_asset_cache.MapAssetCache):
    """Imports Unreal Engine map (FModel .json output). Assets are imported from UModel output directory.
    """

    @staticmethod
    def _library_reload():
        for lib in bpy.data.libraries:
            lib.reload()

    def _get_procedural_basic_shape_source(self, shape_name: str) -> map_support.PreviewMeshSource:
        sources = getattr(self, "_procedural_basic_shape_sources", None)
        if sources is None:
            sources = {}
            self._procedural_basic_shape_sources = sources
        if shape_name not in sources:
            sources[shape_name] = map_support.create_basic_shape_source(shape_name)
        return sources[shape_name]

    def _import_map(self,
                    context: bpy.types.Context,
                    map_path: str,
                    umodel_export_dir: str,
                    asset_dir: str,
                    game_profile: str,
                    db: t.Optional[import_support.AssetDB] = None) -> bool:
        """Imports map placements to the current scene.

        :param map_path: Path to FModel .json output representing a .umap file.
        :param umodel_export_dir: UModel output directory.
        :param asset_dir: Asset library directory.
        :param game_profile: Current game profile.
        :param db: Asset database.
        :return: True if succesful, else False.
        """

        if not os.path.exists(map_path):
            print(f"Error: File {map_path} not found. Skipping.")
            return False

        self._path_resolve_stats.reset()
        self._procedural_basic_shape_sources = {}
        json_filename = utils.normalize_ue_name(os.path.basename(map_path), fallback="Imported_Map")
        map_name_no_ext = os.path.splitext(os.path.basename(map_path))[0]
        self._missing_asset_reporter = missing_asset_report.MissingAssetReporter(
            map_name=map_name_no_ext,
            export_dir=umodel_export_dir,
            asset_dir=asset_dir,
            save_report=getattr(self, "save_missing_asset_report", True),
            report_format=getattr(self, "missing_asset_report_format", missing_asset_report.CSV),
            max_console_records=getattr(self, "max_missing_assets_printed_to_console", 30),
            deduplicate=getattr(self, "deduplicate_missing_assets", True),
            directory_mode=getattr(
                self,
                "missing_asset_report_directory_mode",
                missing_asset_report.DIRECTORY_UMODEL_EXPORT,
            ),
            custom_directory=getattr(self, "custom_missing_asset_report_directory", ""),
            include_actor_context=getattr(self, "include_actor_context_in_missing_report", True),
            verbose=utils.preferences.get_addon_preferences().verbose,
        )
        import_collection = bpy.data.collections.new(json_filename)

        bpy.context.scene.collection.children.link(import_collection)

        import_failed = False
        with open(map_path, mode='r', encoding='utf-8') as file:
            json_object = json.load(file)
            scene_graph = map_scene_graph.FModelSceneGraph(json_object)
            print(f"FModel scene graph summary: {scene_graph.summary()}")
            world_environment_applied = _apply_world_environment_to_visible_scenes(context, json_object)
            if world_environment_applied:
                print(
                    "World environment summary: procedural sky texture configured from map settings "
                    f"for {world_environment_applied} scene(s)."
                )
            else:
                print("World environment summary: no supported map sky/fog settings found.")

            # handle the different entity types (mehses, lights, etc)
            with utils.std_out_err_passthrough():
                total_entities = len(json_object)
                static_mesh_seen = 0
                last_progress_print = time.monotonic()
                progress_desc = (
                    f"{localization.t_report('Importing map')} "
                    f"\"{os.path.splitext(os.path.basename(map_path))[0]}\""
                )
                for entity_index, entity in enumerate(
                    progress.iter_progress(
                        json_object,
                        context=context,
                        total=total_entities,
                        desc=progress_desc,
                    ),
                    start=1,
                ):
                        if import_failed:
                            break

                        if not entity.get('Type', None):
                            continue

                        entity_type = entity.get('Type')

                        # static meshes
                        if scene_graph.should_import_preview_component(entity):
                            static_mesh_seen += 1
                            if map_support.should_print_static_mesh_progress(static_mesh_seen, last_progress_print):
                                print(
                                    map_support.format_static_mesh_progress(
                                        entity_index=entity_index,
                                        total_entities=total_entities,
                                        static_mesh_seen=static_mesh_seen,
                                        imported_instances=self._import_stats.imported_instance_count,
                                        missing_mesh=self._import_stats.missing_mesh_count,
                                    ),
                                    flush=True,
                                )
                                last_progress_print = time.monotonic()

                            static_mesh = StaticMesh(json_object, entity, entity_type, scene_graph=scene_graph)
                            self._set_missing_asset_context(
                                actor_name=entity.get("Name", entity.get("Outer", "")),
                                actor_object_path=entity.get("ObjectPath", ""),
                                component_name=entity_type,
                                component_object_path=static_mesh.raw_object_path,
                                instance_index="",
                            )

                            if static_mesh.invalid:
                                utils.verbose_print(f"Info: Skipping instance of {static_mesh.entity_name}. "
                                                    "Invalid property.")
                                continue

                            try:
                                obj = self._load_map_asset(
                                    context=context,
                                    asset_dir=asset_dir,
                                    asset_path=static_mesh.asset_path,
                                    umodel_export_dir=umodel_export_dir,
                                    load=True,
                                    db=db,
                                    game_profile=game_profile
                                )
                            except map_asset_cache.AssetImportPolicyError as exc:
                                print(f"Error: {exc}")
                                import_failed = True
                                break

                            procedural_basic_shape = False
                            if (
                                obj is None
                                and static_mesh.basic_shape_name
                                and not self._missing_policy_fails("mesh")
                            ):
                                self._import_stats.missing_mesh_count += 1
                                obj = self._get_procedural_basic_shape_source(static_mesh.basic_shape_name)
                                procedural_basic_shape = True
                                self._record_missing_asset(
                                    resource_type="mesh",
                                    json_asset_path=static_mesh.raw_object_path or static_mesh.asset_path,
                                    message=(
                                        f"Mesh \"{static_mesh.asset_path}\" was not exported; "
                                        f"using a procedural Engine BasicShapes/{static_mesh.basic_shape_name} preview."
                                    ),
                                    fallback_used="procedural_basic_shape",
                                    resolution=self._last_missing_resolution,
                                    component_name=entity_type,
                                    resolution_status="procedural_fallback",
                                )

                            if obj is None:
                                skipped_count = static_mesh.expected_instance_count
                                self._import_stats.missing_mesh_count += 1
                                self._import_stats.skipped_instances += skipped_count
                                msg = (f"Warning: Skipping {skipped_count} instance(s) of {static_mesh.entity_name} "
                                       f"because mesh \"{static_mesh.asset_path}\" was not found.")
                                self._record_missing_asset(
                                    resource_type="mesh",
                                    json_asset_path=static_mesh.raw_object_path or static_mesh.asset_path,
                                    message=msg,
                                    fallback_used="skipped_instance",
                                    resolution=self._last_missing_resolution,
                                    component_name=entity_type,
                                )
                                if self._missing_policy_fails("mesh"):
                                    print(f"Error: Missing mesh policy failed import for {static_mesh.asset_path}.")
                                    import_failed = True
                                    break
                                continue

                            imported_objects = static_mesh.link_object_instance(obj, import_collection)
                            self._import_stats.imported_instance_count += len(imported_objects)
                            if procedural_basic_shape:
                                self._import_stats.procedural_basic_shape_count += len(imported_objects)
                                for imported_object in imported_objects:
                                    imported_object["umodel_tools_asset_fallback"] = "procedural_basic_shape"
                                    if not imported_object.get("umodel_tools_preview_fallback"):
                                        imported_object["umodel_tools_preview_fallback"] = "procedural_basic_shape"
                                    imported_object["umodel_tools_unreal_asset_path"] = static_mesh.raw_object_path
                            if static_mesh.mesh_source == "template":
                                self._import_stats.template_mesh_fallback_count += len(imported_objects)
                            if static_mesh.component_kind == "spline":
                                self._import_stats.approximate_spline_mesh_count += len(imported_objects)

                        # lights
                        elif entity_type in GameLight.light_types:
                            light = GameLight(json_object, entity, scene_graph=scene_graph)

                            if light.invalid:
                                utils.verbose_print(f"Info: Skipping instance of {light.entity_name}. "
                                                    "Invalid property.")
                                continue

                            light.import_light(import_collection)

                        else:
                            resource_type = _classify_non_map_asset(entity_type)
                            if resource_type == "skeletal_mesh":
                                self._import_skeletal_mesh_static_fallback(
                                    context=context,
                                    json_object=json_object,
                                    entity=entity,
                                    entity_type=entity_type,
                                    import_collection=import_collection,
                                    asset_dir=asset_dir,
                                    umodel_export_dir=umodel_export_dir,
                                    db=db,
                                    game_profile=game_profile,
                                    scene_graph=scene_graph,
                                )
                            elif resource_type:
                                self._record_non_map_asset_skip(entity, entity_type)

        if import_failed:
            self._finish_map_import_report(import_collection)
            return False

        # TODO: required due to unknown reason, blender bug? Otherwise, some meshes have None materials.
        bpy.app.timers.register(self._library_reload, first_interval=0.010)
        if getattr(self, "report_path_resolution_stats", True):
            print(f"{localization.t_report('Path resolution summary')}: {self._path_resolve_stats.summary()}")

        if world_environment_applied:
            _apply_world_environment_to_visible_scenes(context, json_object)

        self._finish_map_import_report(import_collection)

        return True

    def _finish_map_import_report(self, import_collection: bpy.types.Collection) -> missing_asset_report.ImportReport:
        self._update_storage_counts(import_collection)
        print(f"Import storage summary: {self._import_stats.summary()}")
        report = missing_asset_report.ImportReport()
        if self._missing_asset_reporter is not None:
            report = self._missing_asset_reporter.finish()
        self._last_import_report = report
        return report

    def _record_non_map_asset_skip(self, entity: t.Any, entity_type: str) -> None:
        resource_type = _classify_non_map_asset(entity_type)
        if not resource_type:
            return

        props = entity.get("Properties", {}) or {}
        if resource_type == "skeletal_mesh" and "SkeletalMesh" not in props:
            return

        asset_info = (
            props.get("SkeletalMesh")
            or props.get("MorphTarget")
            or props.get("AnimSequence")
            or props.get("Animation")
            or props.get("Skeleton")
            or {}
        )
        json_asset_path = asset_info.get("ObjectPath") or entity.get("ObjectPath") or entity.get("Name", entity_type)
        actor_name = entity.get("Name", entity.get("Outer", ""))
        component_path = entity.get("ObjectPath", "")
        self._set_missing_asset_context(
            actor_name=actor_name,
            actor_object_path=component_path,
            component_name=entity_type,
            component_object_path=component_path,
            instance_index="",
        )

        if resource_type == "skeletal_mesh":
            self._import_stats.unsupported_skeletal_mesh_count += 1
            self._import_stats.skipped_skeletal_mesh_count += 1
        elif resource_type == "morph_target":
            self._import_stats.skipped_morph_target_count += 1
        elif resource_type == "animation":
            self._import_stats.skipped_animation_count += 1
        elif resource_type == "armature":
            self._import_stats.skipped_armature_count += 1

        self._record_missing_asset(
            resource_type=resource_type,
            json_asset_path=json_asset_path,
            message=(
                f"Skipping unsupported non-map asset type {entity_type}. "
                "Default map import does not import skeletal, morph, armature, or animation data."
            ),
            fallback_used="skipped",
            component_name=entity_type,
            resolution_status="unsupported",
        )

    def _import_skeletal_mesh_static_fallback(
        self,
        context: bpy.types.Context,
        json_object: t.Any,
        entity: t.Any,
        entity_type: str,
        import_collection: bpy.types.Collection,
        asset_dir: str,
        umodel_export_dir: str,
        db: import_support.AssetDB,
        game_profile: str,
        scene_graph: map_scene_graph.FModelSceneGraph | None = None,
    ) -> None:
        props = entity.get("Properties", {}) or {}
        skeletal_mesh_ref = props.get("SkeletalMesh")
        if skeletal_mesh_ref is None:
            self._record_non_map_asset_skip(entity, entity_type)
            return

        if self._skeletal_component_has_animation(props):
            self._record_embedded_non_static_data_skip(
                entity=entity,
                entity_type=entity_type,
                resource_type="animation",
                fallback_used="skipped",
                message="Skipping animation data while importing SkeletalMeshComponent as static fallback.",
            )

        if not getattr(self, "import_skeletal_mesh_as_static_fallback", True):
            self._record_non_map_asset_skip(entity, entity_type)
            return

        static_entity = dict(entity)
        static_props = dict(props)
        static_props["StaticMesh"] = skeletal_mesh_ref
        static_entity["Properties"] = static_props

        skeletal_mesh = StaticMesh(
            json_object,
            static_entity,
            "StaticMeshComponent",
            scene_graph=scene_graph,
        )
        self._set_missing_asset_context(
            actor_name=entity.get("Name", entity.get("Outer", "")),
            actor_object_path=entity.get("ObjectPath", ""),
            component_name=entity_type,
            component_object_path=skeletal_mesh.raw_object_path,
            instance_index="",
        )

        if skeletal_mesh.invalid:
            self._import_stats.unsupported_skeletal_mesh_count += 1
            self._import_stats.skipped_skeletal_mesh_count += 1
            self._record_missing_asset(
                resource_type="skeletal_mesh",
                json_asset_path=skeletal_mesh.raw_object_path or entity.get("ObjectPath", entity.get("Name", "")),
                message="Skipping SkeletalMeshComponent because it cannot be converted to a static fallback.",
                fallback_used="skipped",
                component_name=entity_type,
                resolution_status="unsupported",
            )
            return

        try:
            obj = self._load_map_asset(
                context=context,
                asset_dir=asset_dir,
                asset_path=skeletal_mesh.asset_path,
                umodel_export_dir=umodel_export_dir,
                load=True,
                db=db,
                game_profile=game_profile,
            )
        except map_asset_cache.AssetImportPolicyError as exc:
            self._record_missing_asset(
                resource_type="skeletal_mesh",
                json_asset_path=skeletal_mesh.raw_object_path or skeletal_mesh.asset_path,
                message=f"Skipping SkeletalMeshComponent static fallback after policy error: {exc}",
                fallback_used="skipped",
                resolution=self._last_missing_resolution,
                component_name=entity_type,
            )
            self._import_stats.skipped_skeletal_mesh_count += skeletal_mesh.expected_instance_count
            return

        if obj is None:
            skipped_count = skeletal_mesh.expected_instance_count
            self._import_stats.skipped_skeletal_mesh_count += skipped_count
            self._record_missing_asset(
                resource_type="skeletal_mesh",
                json_asset_path=skeletal_mesh.raw_object_path or skeletal_mesh.asset_path,
                message=(
                    f"Skipping {skipped_count} SkeletalMeshComponent static fallback instance(s) "
                    f"because mesh \"{skeletal_mesh.asset_path}\" was not found."
                ),
                fallback_used="skipped",
                resolution=self._last_missing_resolution,
                component_name=entity_type,
            )
            return

        imported_objects = skeletal_mesh.link_object_instance(obj, import_collection)
        imported_count = len(imported_objects)
        self._import_stats.imported_instance_count += imported_count
        self._import_stats.static_fallback_skeletal_mesh_count += imported_count

    def _record_embedded_non_static_data_skip(
        self,
        entity: t.Any,
        entity_type: str,
        resource_type: str,
        fallback_used: str,
        message: str,
    ) -> None:
        props = entity.get("Properties", {}) or {}
        data = props.get("AnimationData", {}) if resource_type == "animation" else {}
        asset_info = data.get("AnimToPlay", {}) if isinstance(data, dict) else {}
        json_asset_path = asset_info.get("ObjectPath") or entity.get("ObjectPath") or entity.get("Name", entity_type)
        self._set_missing_asset_context(
            actor_name=entity.get("Name", entity.get("Outer", "")),
            actor_object_path=entity.get("ObjectPath", ""),
            component_name=entity_type,
            component_object_path=entity.get("ObjectPath", ""),
            instance_index="",
        )
        if resource_type == "animation":
            self._import_stats.skipped_animation_count += 1
        elif resource_type == "morph_target":
            self._import_stats.skipped_morph_target_count += 1
        elif resource_type == "armature":
            self._import_stats.skipped_armature_count += 1
        self._record_missing_asset(
            resource_type=resource_type,
            json_asset_path=json_asset_path,
            message=message,
            fallback_used=fallback_used,
            component_name=entity_type,
            resolution_status="skipped",
        )

    @staticmethod
    def _skeletal_component_has_animation(props: dict[str, t.Any]) -> bool:
        animation_data = props.get("AnimationData")
        if isinstance(animation_data, dict) and animation_data:
            return True
        animation_mode = props.get("AnimationMode")
        return bool(animation_mode and animation_mode != "EAnimationMode::AnimationBlueprint")

    def _update_storage_counts(self, collection: bpy.types.Collection) -> None:
        mesh_objects = [obj for obj in collection.objects if obj.type == "MESH"]
        self._import_stats.linked_object_count += sum(
            1 for obj in mesh_objects
            if obj.library is not None or (obj.data is not None and obj.data.library is not None)
        )

        materials = {}
        for obj in mesh_objects:
            if obj.data is None:
                continue
            for mat in obj.data.materials:
                if mat is not None:
                    materials[mat.as_pointer()] = mat

        self._import_stats.linked_material_count += sum(1 for mat in materials.values() if mat.library is not None)

    def _print_import_summary(self) -> None:
        print(f"Import storage summary: {self._import_stats.summary()}")
