import typing as t
import os
import dataclasses

import bpy

from . import utils
from . import props_txt_parser
from . import umodel_path_resolver
from . import localization
from . import missing_asset_report
from . import import_support
from . import material_cache
from .mesh_backends import backends as mesh_backends


LINKED_ASSET_LIBRARY = "LINKED_ASSET_LIBRARY"

WARN_SKIP = "WARN_SKIP"
USE_PLACEHOLDER = "USE_PLACEHOLDER"
FAIL_IMPORT = "FAIL_IMPORT"

ASSET_CACHE_VERSION = 5
ASSET_CACHE_VERSION_KEY = "umodel_tools_asset_cache_version"
_SKELETAL_CACHE_SUFFIX = ".skeletal"


@dataclasses.dataclass
class ImportRuntimeStats:
    storage_mode: str = LINKED_ASSET_LIBRARY
    missing_mesh_count: int = 0
    missing_material_count: int = 0
    missing_texture_count: int = 0
    skipped_instances: int = 0
    imported_instance_count: int = 0
    linked_object_count: int = 0
    local_object_count: int = 0
    linked_material_count: int = 0
    local_material_count: int = 0
    unsupported_skeletal_mesh_count: int = 0
    skipped_skeletal_mesh_count: int = 0
    static_fallback_skeletal_mesh_count: int = 0
    rigged_skeletal_mesh_count: int = 0
    imported_armature_count: int = 0
    imported_animation_count: int = 0
    template_mesh_fallback_count: int = 0
    procedural_basic_shape_count: int = 0
    approximate_spline_mesh_count: int = 0
    skipped_morph_target_count: int = 0
    skipped_animation_count: int = 0
    skipped_armature_count: int = 0

    def summary(self) -> str:
        return (
            f"storage_mode={self.storage_mode}, "
            f"linked_object_count={self.linked_object_count}, "
            f"local_object_count={self.local_object_count}, "
            f"linked_material_count={self.linked_material_count}, "
            f"local_material_count={self.local_material_count}, "
            f"missing_mesh_count={self.missing_mesh_count}, "
            f"missing_material_count={self.missing_material_count}, "
            f"missing_texture_count={self.missing_texture_count}, "
            f"skipped_instances={self.skipped_instances}, "
            f"imported_instance_count={self.imported_instance_count}, "
            f"unsupported_skeletal_mesh_count={self.unsupported_skeletal_mesh_count}, "
            f"skipped_skeletal_mesh_count={self.skipped_skeletal_mesh_count}, "
            f"static_fallback_skeletal_mesh_count={self.static_fallback_skeletal_mesh_count}, "
            f"rigged_skeletal_mesh_count={self.rigged_skeletal_mesh_count}, "
            f"imported_armature_count={self.imported_armature_count}, "
            f"imported_animation_count={self.imported_animation_count}, "
            f"template_mesh_fallback_count={self.template_mesh_fallback_count}, "
            f"procedural_basic_shape_count={self.procedural_basic_shape_count}, "
            f"approximate_spline_mesh_count={self.approximate_spline_mesh_count}, "
            f"skipped_morph_target_count={self.skipped_morph_target_count}, "
            f"skipped_animation_count={self.skipped_animation_count}, "
            f"skipped_armature_count={self.skipped_armature_count}"
        )


@dataclasses.dataclass
class SkeletalAssetInstance:
    objects: list[bpy.types.Object]
    armature_object: bpy.types.Object
    source_library_path: str


AssetImportPolicyError = material_cache.AssetImportPolicyError


class MapAssetCache(material_cache.MaterialCacheMixin):
    """Builds and links cached mesh/material libraries used by map import."""

    load_pbr_maps: bpy.props.BoolProperty(
        name="Load PBR textures",
        description="Load normal maps, specular, roughness, etc into materials. Experimental",
        default=True
    )

    import_backface_culling: bpy.props.BoolProperty(
        name="Use backface culling",
        description="If this setting is checked, material settings for backface culling will be kept, "
                    "otherwise backface culling is always off",
        default=False
    )

    texture_format: bpy.props.EnumProperty(
        name="Texture format",
        description="Format of textures expected to be in the UModel export directory.",
        items=[
            ('.png', '.png', '', 0),
            ('.dds', '.dds', '', 1),
            ('.tga', '.tga', '', 2)
        ],
        default='.png'
    )

    _unrecognized_texture_types: set[str] = set()

    _has_warnings: bool = False
    _path_resolve_stats: umodel_path_resolver.UModelPathResolveStats = umodel_path_resolver.UModelPathResolveStats()
    _import_stats: ImportRuntimeStats = ImportRuntimeStats()
    _missing_warning_paths: set[tuple[str, str]] = set()
    _missing_warning_printed_count: int = 0
    _linked_library_cache: dict[tuple[str, str], bpy.types.ID] = {}
    _asset_cache_current: dict[str, bool] = {}
    _material_cache_current: dict[str, bool] = {}
    _missing_asset_reporter: missing_asset_report.MissingAssetReporter | None = None
    _missing_asset_context: dict[str, t.Any] = {}
    _last_missing_resolution: umodel_path_resolver.ResolvedUModelPath | None = None
    _last_import_report: missing_asset_report.ImportReport = missing_asset_report.ImportReport()

    def _reset_import_runtime_state(self) -> None:
        self._unrecognized_texture_types.clear()
        self._has_warnings = False
        self._path_resolve_stats = umodel_path_resolver.UModelPathResolveStats()
        self._import_stats = ImportRuntimeStats()
        self._missing_warning_paths = set()
        self._missing_warning_printed_count = 0
        self._linked_library_cache = {}
        self._asset_cache_current = {}
        self._material_cache_current = {}
        self._missing_asset_reporter = None
        self._missing_asset_context = {}
        self._last_missing_resolution = None
        self._last_import_report = missing_asset_report.ImportReport()

    def _path_cache_key(self, path: str) -> str:
        return import_support.path_cache_key(path)

    def _linked_library_cache_key(self, lib_filepath: str, dtype: type[bpy.types.ID]) -> tuple[str, str]:
        return import_support.linked_library_cache_key(lib_filepath, dtype)

    def _linked_libraries_search_cached(
        self,
        lib_filepath: str,
        dtype: type[bpy.types.ID],
    ) -> bpy.types.ID | None:
        return import_support.linked_libraries_search_cached(
            self._linked_library_cache,
            lib_filepath,
            dtype,
        )

    def _remember_linked_library(self, lib_filepath: str, data_block: bpy.types.ID | None) -> None:
        import_support.remember_linked_library(self._linked_library_cache, lib_filepath, data_block)

    def _forget_linked_library(self, lib_filepath: str) -> None:
        import_support.forget_linked_library(self._linked_library_cache, lib_filepath)

    def _load_material_from_library(self, material_lib_path: str) -> bpy.types.Material:
        if (new_mat := self._linked_libraries_search_cached(material_lib_path, bpy.types.Material)) is not None:
            return new_mat

        with utils.redirect_cstdout():
            with bpy.data.libraries.load(filepath=material_lib_path, link=True) as (data_from, data_to):
                data_to.materials = [data_from.materials[0]]

            new_mat = data_to.materials[0]
            self._remember_linked_library(material_lib_path, new_mat)
            return new_mat

    def _is_asset_cache_stale_cached(self, asset_path_abs: str, asset_path: str, umodel_export_dir: str) -> bool:
        key = self._path_cache_key(asset_path_abs)
        if key not in self._asset_cache_current:
            self._asset_cache_current[key] = not self._is_asset_cache_stale(
                asset_path_abs=asset_path_abs,
                asset_path=asset_path,
                umodel_export_dir=umodel_export_dir,
            )
        return not self._asset_cache_current[key]

    def _is_material_cache_current_cached(self, material_lib_path: str) -> bool:
        key = self._path_cache_key(material_lib_path)
        if key not in self._material_cache_current:
            self._material_cache_current[key] = material_cache._material_cache_is_current(material_lib_path)
        return self._material_cache_current[key]

    def _op_message(self, msg_type: t.Literal['INFO'] | t.Literal['ERROR'] | t.Literal['WARNING'], msg: str):
        """Print operator message and return the associated status-code.

        :param msg_type: Type of message.
        :param msg: Message text.
        :raises NotImplementedError: Raise when an incorrect ``type`` is passed.
        :return: Blender operator error code.
        """
        self.report(type={msg_type, }, message=localization.t_report(msg))  # pylint: disable=no-member
        match msg_type:
            case 'INFO':
                return {'FINISHED'}
            case 'ERROR':
                return {'CANCELLED'}
            case 'WARNING':
                return {'FINISHED'}
            case _:
                raise NotImplementedError()

    def _warn_print(self, *args: t.Any) -> None:
        """Print a message and mark that an operation had warnings.
        :param args: Arguments to internal print() call.
        """
        self._has_warnings = True
        print(*args)

    def _warn_missing_asset(self, asset_kind: str, asset_path: str, message: str) -> None:
        key = (asset_kind, asset_path)
        if key in self._missing_warning_paths:
            self._has_warnings = True
            return

        self._missing_warning_paths.add(key)
        if utils.preferences.get_addon_preferences().verbose:
            self._warn_print(message)
            self._missing_warning_printed_count += 1
        else:
            self._has_warnings = True

    def _set_missing_asset_context(self, **kwargs: t.Any) -> None:
        self._missing_asset_context = kwargs

    def _record_missing_asset(
        self,
        resource_type: str,
        json_asset_path: str,
        message: str,
        fallback_used: str,
        resolution: umodel_path_resolver.ResolvedUModelPath | None = None,
        material_name: str = "",
        texture_parameter_name: str = "",
        component_name: str = "",
        resolution_status: str = "",
    ) -> None:
        self._has_warnings = True
        reporter = self._missing_asset_reporter
        if reporter is None:
            self._warn_missing_asset(resource_type, json_asset_path, f"Warning: {message}")
            return

        resolution = resolution or self._last_missing_resolution
        context = self._missing_asset_context
        policy = self._missing_policy(resource_type) if resource_type in {"mesh", "material", "texture"} else ""
        severity = "error" if policy == FAIL_IMPORT else "warning"
        normalized_asset_path = (
            resolution.normalized_asset_path
            if resolution is not None and resolution.normalized_asset_path
            else umodel_path_resolver.normalize_unreal_asset_path(json_asset_path)
        )
        attempted_extensions = (
            resolution.attempted_extensions
            if resolution is not None and resolution.attempted_extensions
            else tuple()
        )
        expected_path = resolution.expected_path if resolution is not None else ""
        resolved_candidate_count = resolution.resolved_candidate_count if resolution is not None else 0
        record_resolution_status = resolution_status or (resolution.status if resolution is not None else "missing_file")
        if record_resolution_status == "unresolved":
            record_resolution_status = "unresolved"

        reporter.add(missing_asset_report.MissingAssetRecord(
            resource_type=resource_type,
            severity=severity,
            policy=missing_asset_report.policy_label(policy, fallback_used),
            json_asset_path=json_asset_path,
            normalized_asset_path=normalized_asset_path,
            attempted_extensions=attempted_extensions,
            resolution_status=record_resolution_status,
            expected_path=expected_path,
            resolved_candidate_count=resolved_candidate_count,
            actor_name=str(context.get("actor_name", "")),
            actor_object_path=str(context.get("actor_object_path", "")),
            component_name=component_name or str(context.get("component_name", "")),
            component_object_path=str(context.get("component_object_path", "")),
            instance_index=str(context.get("instance_index", "")),
            material_name=material_name,
            texture_parameter_name=texture_parameter_name,
            fallback_used=fallback_used,
            message=message,
            path_inference_mode=getattr(self, "path_inference_mode", ""),
        ))

    def _missing_policy(self, asset_kind: t.Literal["mesh", "material", "texture"]) -> str:
        attr_name = f"missing_{asset_kind}_policy"
        default_policy = WARN_SKIP if asset_kind == "mesh" else USE_PLACEHOLDER
        if getattr(self, "validation_preset", "") == "STRICT":
            default_policy = FAIL_IMPORT
        return getattr(self, attr_name, default_policy)

    def _missing_policy_fails(self, asset_kind: t.Literal["mesh", "material", "texture"]) -> bool:
        return self._missing_policy(asset_kind) == FAIL_IMPORT

    def _print_unrecognized_textures(self) -> None:
        """Print all unrecognized texture map names found. Useful for adding support for new games.
        """
        if utils.preferences.get_addon_preferences().verbose:
            print("Unrecognized texture types found:")
            print(self._unrecognized_texture_types)
            self._unrecognized_texture_types.clear()

    def _get_path_inference_settings(self) -> umodel_path_resolver.UModelPathInferenceSettings:
        prefs = utils.preferences.get_addon_preferences()
        return umodel_path_resolver.UModelPathInferenceSettings(
            enable_umodel_path_inference=getattr(
                self, "enable_umodel_path_inference", getattr(prefs, "enable_umodel_path_inference", True)
            ),
            path_inference_mode=getattr(
                self, "path_inference_mode", getattr(prefs, "path_inference_mode", umodel_path_resolver.BASIC_DEFAULT)
            ),
            enable_suffix_index=getattr(self, "enable_suffix_index", getattr(prefs, "enable_suffix_index", True)),
        )

    def _resolve_umodel_path(self,
                             umodel_export_dir: str,
                             asset_path: str,
                             extensions: t.Sequence[str]) -> umodel_path_resolver.ResolvedUModelPath:
        resolved = umodel_path_resolver.resolve_umodel_export_asset_path(
            export_dir=umodel_export_dir,
            asset_path=asset_path,
            extensions=extensions,
            settings=self._get_path_inference_settings(),
            stats=self._path_resolve_stats,
        )

        for warning in resolved.warnings:
            self._warn_print(f"Warning: {warning}")

        if resolved.status in {"inferred", "suffix"} and resolved.relative_path is not None:
            exact_candidate = umodel_path_resolver.build_umodel_asset_path_candidates(
                asset_path=asset_path,
                extensions=extensions,
                settings=umodel_path_resolver.UModelPathInferenceSettings(
                    enable_umodel_path_inference=False,
                    path_inference_mode=umodel_path_resolver.STRICT_EXACT,
                ),
            )[0]
            utils.verbose_print(
                f"{localization.t_report('Resolved truncated UModel path')}:\n"
                f"  {exact_candidate}\n"
                f"  -> {resolved.relative_path}"
            )

        return resolved

    def _load_map_asset(self,
                        context: bpy.types.Context,
                        asset_dir: str,
                        asset_path: str,
                        umodel_export_dir: str,
                        game_profile: str,
                        load: bool = True,
                        db: t.Optional[import_support.AssetDB] = None
                        ) -> bpy.types.Object | None:
        """Return the linked cached Blender object for one mesh referenced by a map.

        If the cache file is missing or stale, rebuild the mesh/material cache first.
        The returned object is linked from the cache; map import is the only supported
        workflow for this path.
        """
        asset_path_abs_no_ext = os.path.join(asset_dir, os.path.splitext(asset_path)[0])
        asset_path_abs = asset_path_abs_no_ext + '.blend'

        try:
            if os.path.isfile(asset_path_abs) and self._is_asset_cache_stale_cached(
                asset_path_abs=asset_path_abs,
                asset_path=asset_path,
                umodel_export_dir=umodel_export_dir,
            ):
                self._asset_cache_current.pop(self._path_cache_key(asset_path_abs), None)
                self._forget_linked_library(asset_path_abs)
                material_cache._remove_loaded_asset_library(asset_path_abs)
                os.remove(asset_path_abs)

            if not os.path.isfile(asset_path_abs):
                self._build_map_asset_cache(
                    context=context,
                    asset_library_dir=asset_dir,
                    asset_path=asset_path,
                    umodel_export_dir=umodel_export_dir,
                    db=db,
                    game_profile=game_profile,
                )
                self._asset_cache_current[self._path_cache_key(asset_path_abs)] = True

            if load:
                if (linked_data := self._linked_libraries_search_cached(asset_path_abs, bpy.types.Object)):
                    return linked_data

                with utils.redirect_cstdout():
                    with bpy.data.libraries.load(asset_path_abs, link=True) as (data_from, data_to):
                        data_to.objects = list(data_from.objects)
                        assert len(data_to.objects) == 1

                    obj = data_to.objects[0]
                    self._remember_linked_library(asset_path_abs, obj)
                    return obj

            return None

        except FileNotFoundError:
            return None

    def _load_map_skeletal_asset(self,
                                 context: bpy.types.Context,
                                 asset_dir: str,
                                 asset_path: str,
                                 umodel_export_dir: str,
                                 game_profile: str,
                                 db: t.Optional[import_support.AssetDB] = None
                                 ) -> SkeletalAssetInstance | None:
        """Append one mesh+armature cache instance for experimental skeletal previews.

        Skeletal previews deliberately use a separate cache file and append local
        objects.  The normal map cache remains a one-object linked library, while
        each armature instance can own an independent Action.
        """

        asset_path_abs_no_ext = os.path.join(asset_dir, os.path.splitext(asset_path)[0])
        asset_path_abs = asset_path_abs_no_ext + _SKELETAL_CACHE_SUFFIX + '.blend'

        try:
            if os.path.isfile(asset_path_abs) and self._is_asset_cache_stale_cached(
                asset_path_abs=asset_path_abs,
                asset_path=asset_path,
                umodel_export_dir=umodel_export_dir,
            ):
                self._asset_cache_current.pop(self._path_cache_key(asset_path_abs), None)
                os.remove(asset_path_abs)

            if not os.path.isfile(asset_path_abs):
                self._build_map_asset_cache(
                    context=context,
                    asset_library_dir=asset_dir,
                    asset_path=asset_path,
                    umodel_export_dir=umodel_export_dir,
                    db=db,
                    game_profile=game_profile,
                    import_skeleton=True,
                )
                self._asset_cache_current[self._path_cache_key(asset_path_abs)] = True

            with utils.redirect_cstdout():
                with bpy.data.libraries.load(asset_path_abs, link=False) as (data_from, data_to):
                    data_to.objects = list(data_from.objects)

            objects = [obj for obj in data_to.objects if obj is not None]
            mesh_object = next(
                (
                    obj for obj in objects
                    if obj.type == "MESH" and bool(obj.get(mesh_backends.MAIN_ASSET_OBJECT_KEY))
                ),
                None,
            )
            if mesh_object is None:
                mesh_object = next((obj for obj in objects if obj.type == "MESH"), None)
            armature_object = next((obj for obj in objects if obj.type == "ARMATURE"), None)
            if mesh_object is None or armature_object is None:
                for loaded_object in objects:
                    bpy.data.objects.remove(loaded_object, do_unlink=True)
                self._asset_cache_current.pop(self._path_cache_key(asset_path_abs), None)
                if os.path.isfile(asset_path_abs):
                    os.remove(asset_path_abs)
                raise RuntimeError(f"Skeletal cache did not contain both a mesh and armature: {asset_path_abs}")

            return SkeletalAssetInstance(
                objects=objects,
                armature_object=armature_object,
                source_library_path=asset_path_abs,
            )

        except FileNotFoundError:
            return None

    def _is_asset_cache_stale(self, asset_path_abs: str, asset_path: str, umodel_export_dir: str) -> bool:
        if not self._asset_cache_is_current(asset_path_abs):
            utils.verbose_print(f"Rebuilding stale asset cache {asset_path_abs}; cache version changed")
            return True

        source_paths = self._asset_cache_source_paths(
            asset_path=asset_path,
            umodel_export_dir=umodel_export_dir,
        )
        if not source_paths:
            return False

        cache_mtime = os.path.getmtime(asset_path_abs)
        stale_sources = [
            source_path for source_path in source_paths
            if os.path.isfile(source_path) and os.path.getmtime(source_path) > cache_mtime
        ]
        if not stale_sources:
            return False

        utils.verbose_print(
            f"Rebuilding stale asset cache {asset_path_abs}; newer source file: {stale_sources[0]}"
        )
        return True

    def _asset_cache_is_current(self, asset_path_abs: str) -> bool:
        return import_support.asset_cache_is_current(
            asset_path_abs,
            ASSET_CACHE_VERSION_KEY,
            ASSET_CACHE_VERSION,
        )

    def _asset_cache_source_paths(self, asset_path: str, umodel_export_dir: str) -> list[str]:
        source_paths: list[str] = []
        asset_path_local_noext = os.path.splitext(asset_path)[0]

        mesh_resolved = self._resolve_umodel_path(
            umodel_export_dir=umodel_export_dir,
            asset_path=asset_path_local_noext,
            extensions=mesh_backends.get_supported_mesh_extensions(),
        )
        if mesh_resolved.found and mesh_resolved.path is not None:
            source_paths.append(mesh_resolved.path)

        mesh_props = self._resolve_umodel_path(
            umodel_export_dir=umodel_export_dir,
            asset_path=asset_path_local_noext,
            extensions=('.props.txt',),
        )
        if not mesh_props.found or mesh_props.path is None:
            return source_paths

        source_paths.append(mesh_props.path)
        try:
            _, material_descriptor_paths = props_txt_parser.parse_props_txt(mesh_props.path, mode='MESH')
        except OSError:
            return source_paths

        for mat_desc_path in material_descriptor_paths:
            material_path_local_no_ext, _material_name = os.path.splitext(mat_desc_path)
            material_path_local_no_ext = os.path.normpath(material_path_local_no_ext)
            if material_path_local_no_ext.startswith(os.sep):
                material_path_local_no_ext = material_path_local_no_ext[1:]

            material_props = self._resolve_umodel_path(
                umodel_export_dir=umodel_export_dir,
                asset_path=material_path_local_no_ext + '.props.txt',
                extensions=('.props.txt',),
            )
            if material_props.found and material_props.path is not None:
                source_paths.append(material_props.path)

        return source_paths

    def _build_map_asset_cache(self,
                               context: bpy.types.Context,
                               asset_library_dir: str,
                               asset_path: str,
                               umodel_export_dir: str,
                               game_profile: str,
                               db: t.Optional[import_support.AssetDB] = None,
                               import_skeleton: bool = False,
                               ) -> None:
        """Build one map mesh cache `.blend` and its material library dependencies.

        :param context: Current Blender context.
        :param asset_library_dir: Directory to store the asset, and its dependencies in.
        :param asset_path: Path to the asset in game format.
        :param umodel_export_dir: UModel output directory to source mesh files from.
        :param game_profile: Game profile to import.
        :param db: Asset database to operate on. If given, no saving is performed, else the function handles
        everything by itself.
        :raises OSError: Raised when an asset was not found in the UModel output dir or failed opening.
        :raises FileNotFounderror: Raised when an asset was not found in the directory.
        :raises RuntimeError: Raised when an asset failed importing due to unknown mesh importer issue.
        :raises NotImplementedError: Raised when requested game profile is not implemented or available.
        """
        has_external_db = db is not None
        if db is None:
            db = import_support.AssetDB(asset_library_dir)

        asset_local_dir = os.path.dirname(asset_path)
        catalog_uid = db.uid_for_entry(asset_local_dir) if asset_local_dir else None
        asset_absolute_dir = os.path.join(asset_library_dir, asset_local_dir)
        asset_path_local_noext = os.path.splitext(asset_path)[0]

        os.makedirs(asset_absolute_dir, exist_ok=True)

        asset_mesh_path_noext = os.path.join(umodel_export_dir, asset_path_local_noext)
        mesh_resolved = self._resolve_umodel_path(
            umodel_export_dir=umodel_export_dir,
            asset_path=asset_path_local_noext,
            extensions=mesh_backends.get_supported_mesh_extensions(),
        )

        found_path: str | None = None

        if mesh_resolved.found and mesh_resolved.path is not None:
            found_path = mesh_resolved.path

        if found_path is None:
            lod0_base_path = asset_mesh_path_noext + '_LOD0'
            lod0_resolved = self._resolve_umodel_path(
                umodel_export_dir=umodel_export_dir,
                asset_path=lod0_base_path,
                extensions=mesh_backends.get_supported_mesh_extensions(),
            )
            if lod0_resolved.found and lod0_resolved.path is not None:
                found_path = lod0_resolved.path
                utils.verbose_print(f"Info: Exact file not found, using LOD0 fallback: \"{found_path}\"")

        if found_path is None:
            self._last_missing_resolution = mesh_resolved
            extensions = "/".join(mesh_backends.get_supported_mesh_extensions())
            raise FileNotFoundError(f"Error: Failed importing asset: {asset_mesh_path_noext} was not found "
                                    f"({extensions}, also tried _LOD0 suffix).")

        utils.verbose_print(f"Importing \"{found_path}\"")

        mesh_context = mesh_backends.MeshImportContext(
            blender_context=context,
            asset_path=asset_path,
            asset_name=os.path.basename(asset_path_local_noext),
            source_filepath=found_path,
            asset_library_dir=asset_library_dir,
            umodel_export_dir=umodel_export_dir,
            game_profile=game_profile,
            import_report=self._last_import_report,
            options={
                "preferred_backend": getattr(self, "mesh_import_backend", "AUTO"),
                "prefer_pskx": True,
                "import_skeleton": import_skeleton,
                "import_morph_targets": False,
                "import_animations": False,
            },
        )
        backend = mesh_backends.get_mesh_backend_for_file(
            found_path,
            mesh_context,
            preferred_backend=mesh_context.options["preferred_backend"],
        )
        if backend is None:
            raise RuntimeError(f"Error: No mesh import backend supports asset {found_path}.")

        result = backend.import_mesh(found_path, mesh_context)
        for warning in result.warnings:
            self._warn_print(f"Warning: {warning}")
        if result.status != mesh_backends.IMPORTED or result.main_object is None:
            raise RuntimeError(f"Error: Failed importing asset {found_path} with backend {backend.id}.")

        obj = result.main_object
        animated = bool(result.metadata.get("animated_material_layout"))
        backend_material_descriptors = result.metadata.get("material_descriptors") or []
        backend_material_format = result.metadata.get("material_descriptor_format", "")
        asset_mesh_path_noext = os.path.splitext(found_path)[0]
        if asset_mesh_path_noext.endswith('_LOD0'):
            asset_mesh_path_noext = asset_mesh_path_noext[:-5]

        # mark object as asset
        obj.asset_mark()
        obj[ASSET_CACHE_VERSION_KEY] = ASSET_CACHE_VERSION
        obj.asset_data.catalog_id = catalog_uid

        # handle materials
        new_materials = []

        # - read material descriptor file and identify associated materials
        try:
            # pylint: disable=unpacking-non-sequence
            if backend_material_descriptors:
                mesh_props = None
                material_descriptor_entries = [
                    {
                        "descriptor_path": str(descriptor.get("descriptor_path", "")),
                        "slot_index": int(descriptor.get("slot_index", fallback_index) or fallback_index),
                        "material_name": str(descriptor.get("material_name", "") or ""),
                        "status": str(descriptor.get("status", "resolved") or "resolved"),
                        "candidates": list(descriptor.get("candidates", []) or []),
                    }
                    for fallback_index, descriptor in enumerate(backend_material_descriptors)
                    if descriptor.get("descriptor_path")
                ]
            else:
                mesh_props = self._resolve_umodel_path(
                    umodel_export_dir=umodel_export_dir,
                    asset_path=asset_path_local_noext,
                    extensions=('.props.txt',),
                )
                if not mesh_props.found or mesh_props.path is None:
                    raise OSError()
                _, mat_descriptors_paths = props_txt_parser.parse_props_txt(mesh_props.path,
                                                                            mode='MESH')
                material_descriptor_entries = [
                    {
                        "descriptor_path": descriptor_path,
                        "slot_index": fallback_index,
                        "material_name": "",
                        "status": "resolved",
                        "candidates": [],
                    }
                    for fallback_index, descriptor_path in enumerate(mat_descriptors_paths)
                ]
        except OSError as exc:
            self._import_stats.missing_material_count += 1
            msg = (f"Warning: Loading material descriptor {asset_mesh_path_noext + '.props.txt'} failed. "
                   "Materials will not be avaialble for the imported object.")
            self._record_missing_asset(
                resource_type="material",
                json_asset_path=asset_path_local_noext + '.props.txt',
                message=msg,
                fallback_used="placeholder_material",
                resolution=mesh_props if mesh_props is not None else None,
                component_name="StaticMesh material descriptor",
            )
            if self._missing_policy_fails("material"):
                raise material_cache.AssetImportPolicyError(msg) from exc
        else:
            # attempt to obtain materials manually if descriptor is not available
            mat_desc_order_map = {mat.name: None for mat in obj.data.materials}

            if animated and not material_descriptor_entries:
                if os.path.isdir(mat_dir := os.path.join(os.path.dirname(found_path), 'Materials')):
                    for root, _, files in os.walk(mat_dir):
                        for file in files:
                            if not file.endswith('.props.txt'):
                                continue

                            file_abs = os.path.splitext(os.path.splitext(os.path.join(root, file))[0])[0]
                            mat_name = os.path.basename(file_abs)

                            if mat_name not in mat_desc_order_map:
                                self._warn_print(f"Warning: Found extra material {mat_name} in the Materials dir. "
                                                 "It won't be imported.")
                                continue

                            mat_desc_order_map[mat_name] = f"{os.path.relpath(file_abs, umodel_export_dir)}.{mat_name}"

                    if any(mat_desc is None for mat_desc in mat_desc_order_map.values()):
                        print(f"Warning: Material count mismatch for asset \"{obj.name}\".")
                        mesh = obj.data

                        bpy.data.objects.remove(obj, do_unlink=True)
                        bpy.data.meshes.remove(mesh, do_unlink=True)

                        old_materials = list(mesh.materials)

                        # perform cleanup before raising
                        for mat in old_materials:
                            try:
                                bpy.data.materials.remove(mat, do_unlink=True)
                            except ReferenceError:  # TODO: figure out why?
                                pass

                        raise FileNotFoundError()

                    material_descriptor_entries = [
                        {
                            "descriptor_path": descriptor_path,
                            "slot_index": fallback_index,
                            "material_name": "",
                            "status": "resolved",
                            "candidates": [],
                        }
                        for fallback_index, descriptor_path in enumerate(mat_desc_order_map.values())
                    ]

            # replace materials
            old_materials = list(obj.data.materials)
            # initialize each material and populate it with data
            for mat_descriptor_entry in material_descriptor_entries:
                mat_desc_path = str(mat_descriptor_entry.get("descriptor_path", ""))
                descriptor_status = str(mat_descriptor_entry.get("status", "resolved") or "resolved")
                descriptor_candidates = list(mat_descriptor_entry.get("candidates", []) or [])
                material_path_local_no_ext, material_name = os.path.splitext(mat_desc_path)
                material_name = material_name[1:]  # removing the .

                # normalize path from config
                material_path_local_no_ext = os.path.normpath(material_path_local_no_ext)

                # remove leading separator
                material_path_local_no_ext = material_path_local_no_ext[1:] \
                    if material_path_local_no_ext.startswith(os.sep) else material_path_local_no_ext

                material_descriptor_extension = '.json' if backend_material_format == "fmodel_json" else '.props.txt'
                material_path_local = material_path_local_no_ext + material_descriptor_extension
                material_lib_path = os.path.join(asset_library_dir, material_path_local_no_ext) + '.blend'

                try:
                    if (
                        backend_material_format == "fmodel_json"
                        and descriptor_status in {material_cache.PLACEHOLDER_MATERIAL_UNRESOLVED, material_cache.PLACEHOLDER_MATERIAL_AMBIGUOUS}
                    ):
                        self._import_stats.missing_material_count += 1
                        candidate_summary = f" Candidates: {descriptor_candidates[:5]!r}." if descriptor_candidates else ""
                        msg = (
                            f"Warning: Material \"{material_name}\" descriptor is {descriptor_status}; "
                            f"placeholder PBR used instead.{candidate_summary}"
                        )
                        self._record_missing_asset(
                            resource_type="material",
                            json_asset_path=material_path_local,
                            message=msg,
                            fallback_used="placeholder_material",
                            material_name=material_name,
                            component_name="Material slot",
                            resolution_status=descriptor_status,
                        )
                        self._material_cache_current.pop(self._path_cache_key(material_lib_path), None)
                        self._forget_linked_library(material_lib_path)
                        material_cache._remove_loaded_material_library(material_lib_path)
                        material_cache._write_placeholder_pbr_material_to_library(
                            material_name=material_name,
                            material_path_local_no_ext=material_path_local_no_ext,
                            status=descriptor_status,
                            material_lib_path=material_lib_path,
                            db=db,
                        )
                        self._material_cache_current[self._path_cache_key(material_lib_path)] = True

                    # add material to asset library if does not exist
                    elif not self._is_material_cache_current_cached(material_lib_path):
                        self._material_cache_current.pop(self._path_cache_key(material_lib_path), None)
                        self._forget_linked_library(material_lib_path)
                        material_cache._remove_loaded_material_library(material_lib_path)
                        if backend_material_format == "fmodel_json":
                            self._import_fmodel_json_material_to_library(material_name=material_name,
                                                                         material_path_local=material_path_local,
                                                                         db=db,
                                                                         umodel_export_dir=umodel_export_dir,
                                                                         asset_library_dir=asset_library_dir,
                                                                         game_profile=game_profile)
                        else:
                            self._import_material_to_library(material_name=material_name,
                                                             material_path_local=material_path_local,
                                                             db=db,
                                                             umodel_export_dir=umodel_export_dir,
                                                                         asset_library_dir=asset_library_dir,
                                                                         game_profile=game_profile)
                        self._material_cache_current[self._path_cache_key(material_lib_path)] = True

                    new_mat = self._load_material_from_library(material_lib_path)

                except FileNotFoundError as e:
                    self._import_stats.missing_material_count += 1
                    msg = f"Warning: Material \"{material_name}\" failed to load, placeholder used instead. ({e})."
                    self._record_missing_asset(
                        resource_type="material",
                        json_asset_path=material_path_local,
                        message=msg,
                        fallback_used="placeholder_material",
                        resolution=self._last_missing_resolution,
                        material_name=material_name,
                        component_name="Material slot",
                    )
                    if backend_material_format != "fmodel_json" and self._missing_policy_fails("material"):
                        raise material_cache.AssetImportPolicyError(
                            f"Missing material \"{material_name}\" while importing \"{asset_path}\"."
                        ) from e
                    self._material_cache_current.pop(self._path_cache_key(material_lib_path), None)
                    self._forget_linked_library(material_lib_path)
                    material_cache._remove_loaded_material_library(material_lib_path)
                    material_cache._write_placeholder_pbr_material_to_library(
                        material_name=material_name,
                        material_path_local_no_ext=material_path_local_no_ext,
                        status=material_cache.PLACEHOLDER_MATERIAL_UNRESOLVED,
                        material_lib_path=material_lib_path,
                        db=db,
                    )
                    self._material_cache_current[self._path_cache_key(material_lib_path)] = True
                    new_mat = self._load_material_from_library(material_lib_path)

                except OSError as exc:
                    self._import_stats.missing_material_count += 1
                    msg = f"Warning: Material \"{material_name}\" failed to load, placeholder used instead."
                    self._record_missing_asset(
                        resource_type="material",
                        json_asset_path=material_path_local,
                        message=msg,
                        fallback_used="placeholder_material",
                        material_name=material_name,
                        component_name="Material slot",
                    )
                    if backend_material_format != "fmodel_json" and self._missing_policy_fails("material"):
                        raise material_cache.AssetImportPolicyError(
                            f"Missing material \"{material_name}\" while importing \"{asset_path}\"."
                        ) from exc
                    self._material_cache_current.pop(self._path_cache_key(material_lib_path), None)
                    self._forget_linked_library(material_lib_path)
                    material_cache._remove_loaded_material_library(material_lib_path)
                    material_cache._write_placeholder_pbr_material_to_library(
                        material_name=material_name,
                        material_path_local_no_ext=material_path_local_no_ext,
                        status=material_cache.PLACEHOLDER_MATERIAL_UNRESOLVED,
                        material_lib_path=material_lib_path,
                        db=db,
                    )
                    self._material_cache_current[self._path_cache_key(material_lib_path)] = True
                    new_mat = self._load_material_from_library(material_lib_path)

                if material_name in obj.data.materials:
                    obj.material_slots[obj.data.materials.find(material_name)].material = new_mat
                else:
                    obj.data.materials.append(new_mat)
                new_materials.append((new_mat, material_name))

            # remove original materials
            for mat in old_materials:
                try:
                    bpy.data.materials.remove(mat, do_unlink=True)
                except ReferenceError:  # TODO: figure out why?
                    pass

        # obj.asset_generate_preview()

        cache_suffix = _SKELETAL_CACHE_SUFFIX if import_skeleton else ""
        asset_abs_lib_path = os.path.join(asset_library_dir, asset_path_local_noext) + cache_suffix + '.blend'
        os.makedirs(os.path.dirname(asset_abs_lib_path), exist_ok=True)
        objects_to_write = set(result.objects or [obj])
        bpy.data.libraries.write(asset_abs_lib_path, objects_to_write, fake_user=True)

        # cleanup
        data_blocks = [
            imported_obj.data
            for imported_obj in objects_to_write
            if getattr(imported_obj, "data", None) is not None
        ]
        for imported_obj in list(objects_to_write):
            try:
                bpy.data.objects.remove(imported_obj, do_unlink=True)
            except ReferenceError:
                pass
        for data_block in data_blocks:
            try:
                if getattr(data_block, "users", 0) == 0:
                    if data_block.bl_rna.identifier == "Mesh":
                        bpy.data.meshes.remove(data_block, do_unlink=True)
                    elif data_block.bl_rna.identifier == "Armature":
                        bpy.data.armatures.remove(data_block, do_unlink=True)
            except ReferenceError:
                pass

        for mat, _ in new_materials:
            try:
                bpy.data.materials.remove(mat, do_unlink=True)
            except ReferenceError:
                pass

        if not has_external_db:
            db.save_db()
