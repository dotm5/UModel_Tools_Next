"""Pure helpers for traversing FModel/CUE4Parse map JSON references.

FModel previews a world as a graph of individually loaded objects instead of
building one combined map mesh.  The helpers in this module mirror the useful
parts of that approach for exported JSON: package-index references, persistent
level actors, actor component references, template fallbacks, and structural
static-mesh component detection.

This module intentionally has no Blender dependency so the graph rules can be
tested with ordinary Python.
"""

from __future__ import annotations

import dataclasses
import re
import typing as t


_OBJECT_NAME_RE = re.compile(r"^(?P<type>[^']+)'(?P<path>.*)'$")
_OBJECT_PATH_RE = re.compile(r"^(?P<package>.+)\.(?P<index>\d+)$")

STATIC_MESH_COMPONENT_TYPES = frozenset({
    "StaticMeshComponent",
    "InstancedStaticMeshComponent",
    "HierarchicalInstancedStaticMeshComponent",
})

ACTOR_COMPONENT_PROPERTY_NAMES = (
    "StaticMeshComponent",
    "ComponentTemplate",
    "Mesh",
    "LightMesh",
    "SplineMesh",
)

ACTOR_COMPONENT_COLLECTION_NAMES = (
    "InstanceComponents",
    # Runtime construction-script components are emitted under this property
    # in some CUE4Parse map exports rather than InstanceComponents.
    "BlueprintCreatedComponents",
)

_BASIC_SHAPE_NAMES = {
    "cube": "Cube",
    "sphere": "Sphere",
    "cylinder": "Cylinder",
    "cone": "Cone",
    "plane": "Plane",
}


@dataclasses.dataclass(frozen=True)
class ComponentView:
    """Resolved mesh-facing fields for one component export."""

    properties: dict[str, t.Any]
    mesh_reference: dict[str, t.Any] | None
    instance_data: list[dict[str, t.Any]] | None
    mesh_source: str
    instance_source: str
    component_kind: str


class FModelSceneGraph:
    """Index and traverse one CUE4Parse package JSON export."""

    def __init__(self, entities: t.Any) -> None:
        # Preserve null/unknown export slots because FPackageIndex values are
        # zero-based positions in the original export array.
        self.entities: list[t.Any] = list(entities) if isinstance(entities, list) else []
        self.package_name = ""
        self._name_index: dict[tuple[str, str], list[dict[str, t.Any]]] = {}
        self._entity_ids: set[int] = set()
        for entity in self.entities:
            if not isinstance(entity, dict):
                continue
            self._entity_ids.add(id(entity))
            if not self.package_name and entity.get("Type") == "World" and entity.get("Package"):
                self.package_name = str(entity["Package"])
            key = (str(entity.get("Type", "")), str(entity.get("Name", "")))
            self._name_index.setdefault(key, []).append(entity)
        self._persistent_level_resolved = False
        self._persistent_level_cache: dict[str, t.Any] | None = None
        self._persistent_level_actors_cache: list[dict[str, t.Any]] | None = None
        self._actor_components_cache: dict[int, list[dict[str, t.Any]]] = {}
        self._actor_component_id_cache: set[int] | None = None
        self._component_view_cache: dict[int, ComponentView] = {}

    def resolve_reference(self, reference: t.Any) -> dict[str, t.Any] | None:
        """Resolve an internal FPackageIndex-style JSON reference.

        CUE4Parse serializes package export references as ``Package.Path.N``;
        ``N`` is the zero-based export index and therefore maps directly to the
        JSON array index.  Object-name validation prevents an external package
        with a coincidentally small index from resolving into this package.
        """

        if not isinstance(reference, dict):
            return None

        object_path = reference.get("ObjectPath")
        if isinstance(object_path, str):
            match = _OBJECT_PATH_RE.match(object_path)
            if match is not None:
                package_name = match.group("package")
                if self.package_name and package_name != self.package_name:
                    return None
                index = int(match.group("index"))
                if 0 <= index < len(self.entities):
                    candidate = self.entities[index]
                    if isinstance(candidate, dict) and _reference_matches_entity(reference, candidate):
                        return candidate

        ref_type, ref_name = parse_object_name(reference.get("ObjectName"))
        if not ref_type or not ref_name:
            return None
        matches = self._name_index.get((ref_type, ref_name), [])
        return matches[0] if len(matches) == 1 else None

    def template_chain(self, entity: dict[str, t.Any]) -> t.Iterator[dict[str, t.Any]]:
        """Yield an entity followed by resolvable templates, cycle-safe."""

        current: dict[str, t.Any] | None = entity
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            yield current
            current = self.resolve_reference(current.get("Template"))

    def component_view(self, entity: dict[str, t.Any]) -> ComponentView:
        """Resolve the fields FModel uses to preview a mesh component."""

        entity_id = id(entity)
        cacheable = entity_id in self._entity_ids
        if cacheable:
            cached = self._component_view_cache.get(entity_id)
            if cached is not None:
                return cached

        properties = entity.get("Properties")
        if not isinstance(properties, dict):
            properties = {}

        mesh_reference = None
        mesh_source = "missing"
        instance_data = None
        instance_source = "missing"
        for depth, candidate in enumerate(self.template_chain(entity)):
            candidate_props = candidate.get("Properties")
            if not isinstance(candidate_props, dict):
                candidate_props = {}
            if mesh_reference is None and is_static_mesh_reference(candidate_props.get("StaticMesh")):
                mesh_reference = candidate_props["StaticMesh"]
                mesh_source = "direct" if depth == 0 else "template"

            candidate_instances = candidate.get("PerInstanceSMData")
            if instance_data is None and isinstance(candidate_instances, list) and candidate_instances:
                instance_data = candidate_instances
                instance_source = "direct" if depth == 0 else "template"

            if mesh_reference is not None and instance_data is not None:
                break

        entity_type = str(entity.get("Type", ""))
        view = ComponentView(
            properties=properties,
            mesh_reference=mesh_reference,
            instance_data=instance_data,
            mesh_source=mesh_source,
            instance_source=instance_source,
            component_kind=_component_kind(entity_type, properties, instance_data),
        )
        if cacheable:
            self._component_view_cache[entity_id] = view
        return view

    def is_preview_mesh_component(self, entity: dict[str, t.Any]) -> bool:
        """Return whether an export can be handled as preview mesh geometry."""

        entity_type = str(entity.get("Type", ""))
        if entity_type in STATIC_MESH_COMPONENT_TYPES:
            return True
        if entity_type.endswith("StaticMeshComponent") or entity_type.endswith("SplineMeshComponent"):
            return True
        props = entity.get("Properties")
        return (
            entity_type.endswith("Component")
            and isinstance(props, dict)
            and is_static_mesh_reference(props.get("StaticMesh"))
        )

    def should_import_preview_component(self, entity: dict[str, t.Any]) -> bool:
        """Use actor reachability when a persistent level graph is available.

        Template/default component exports can contain valid meshes but are not
        placed scene instances.  FModel avoids importing them by starting from
        ``ULevel.Actors``.  Flat structural scanning remains the fallback for
        partial JSON documents that omit World/Level/Actor references.
        """

        if not self.is_preview_mesh_component(entity):
            return False
        actors = self.persistent_level_actors()
        if not actors:
            return True
        if self._actor_component_id_cache is None:
            self._actor_component_id_cache = {
                id(component)
                for actor in actors
                for component in self.actor_components(actor)
            }
        return id(entity) in self._actor_component_id_cache

    def persistent_level(self) -> dict[str, t.Any] | None:
        if self._persistent_level_resolved:
            return self._persistent_level_cache
        for entity in self.entities:
            if not isinstance(entity, dict):
                continue
            if entity.get("Type") != "World":
                continue
            level = self.resolve_reference(entity.get("PersistentLevel"))
            if level is not None:
                self._persistent_level_cache = level
                break
        self._persistent_level_resolved = True
        return self._persistent_level_cache

    def persistent_level_actors(self) -> list[dict[str, t.Any]]:
        if self._persistent_level_actors_cache is not None:
            return self._persistent_level_actors_cache
        level = self.persistent_level()
        if level is None:
            self._persistent_level_actors_cache = []
            return self._persistent_level_actors_cache
        actors = level.get("Actors")
        if not isinstance(actors, list):
            self._persistent_level_actors_cache = []
            return self._persistent_level_actors_cache
        resolved: list[dict[str, t.Any]] = []
        for reference in actors:
            actor = self.resolve_reference(reference)
            if actor is not None and actor.get("Type") != "LODActor":
                resolved.append(actor)
        self._persistent_level_actors_cache = resolved
        return self._persistent_level_actors_cache

    def actor_components(self, actor: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        """Resolve FModel's common actor-to-component reference shapes."""

        actor_id = id(actor)
        if actor_id in self._actor_components_cache:
            return self._actor_components_cache[actor_id]
        props = actor.get("Properties")
        if not isinstance(props, dict):
            self._actor_components_cache[actor_id] = []
            return self._actor_components_cache[actor_id]

        references: list[t.Any] = []
        for name in ACTOR_COMPONENT_COLLECTION_NAMES:
            component_references = props.get(name)
            if isinstance(component_references, list):
                references.extend(component_references)
        for name in ACTOR_COMPONENT_PROPERTY_NAMES:
            references.append(props.get(name))

        components: list[dict[str, t.Any]] = []
        seen: set[int] = set()
        for reference in references:
            component = self.resolve_reference(reference)
            if component is None or id(component) in seen or not self.is_preview_mesh_component(component):
                continue
            seen.add(id(component))
            components.append(component)
        self._actor_components_cache[actor_id] = components
        return self._actor_components_cache[actor_id]

    def summary(self) -> str:
        actors = self.persistent_level_actors()
        preview_components = [
            entity for entity in self.entities
            if isinstance(entity, dict) and self.is_preview_mesh_component(entity)
        ]
        importable_components = [
            entity for entity in preview_components if self.should_import_preview_component(entity)
        ]
        template_meshes = sum(
            1 for entity in preview_components if self.component_view(entity).mesh_source == "template"
        )
        return (
            f"package={self.package_name or '<unknown>'}, "
            f"entities={len(self.entities)}, actors={len(actors)}, "
            f"actor_components={len(self._actor_component_id_cache or ())}, "
            f"preview_components={len(preview_components)}, "
            f"importable_components={len(importable_components)}, template_meshes={template_meshes}"
        )


def parse_object_name(value: t.Any) -> tuple[str, str]:
    """Return the Unreal export type and leaf object name."""

    if not isinstance(value, str):
        return "", ""
    match = _OBJECT_NAME_RE.match(value)
    if match is None:
        return "", ""
    object_path = match.group("path")
    leaf = object_path.rsplit(".", 1)[-1].rsplit(":", 1)[-1]
    return match.group("type"), leaf


def is_static_mesh_reference(value: t.Any) -> bool:
    if not isinstance(value, dict):
        return False
    object_type, _ = parse_object_name(value.get("ObjectName"))
    return object_type == "StaticMesh" and bool(value.get("ObjectPath"))


def basic_shape_name(object_path: str) -> str:
    """Return a supported Engine BasicShapes primitive name, if any."""

    normalized = str(object_path).replace("\\", "/")
    marker = "/BasicShapes/"
    if marker.lower() not in normalized.lower():
        return ""
    asset_name = normalized.rsplit("/", 1)[-1].split(".", 1)[0].lower()
    return _BASIC_SHAPE_NAMES.get(asset_name, "")


def _reference_matches_entity(reference: dict[str, t.Any], entity: dict[str, t.Any]) -> bool:
    ref_type, ref_name = parse_object_name(reference.get("ObjectName"))
    if ref_type and ref_type != str(entity.get("Type", "")):
        return False
    if ref_name and ref_name != str(entity.get("Name", "")):
        return False
    return True


def _component_kind(
    entity_type: str,
    properties: dict[str, t.Any],
    instance_data: list[dict[str, t.Any]] | None,
) -> str:
    if entity_type.endswith("SplineMeshComponent"):
        return "spline"
    if "InstancedStaticMeshComponent" in entity_type or instance_data:
        return "instanced"
    if is_static_mesh_reference(properties.get("StaticMesh")) or entity_type.endswith("StaticMeshComponent"):
        return "static"
    return "unknown"
