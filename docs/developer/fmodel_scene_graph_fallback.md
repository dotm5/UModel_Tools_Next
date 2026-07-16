# FModel-style map preview fallback

## Scope

UModel Tools Next still accepts an FModel/CUE4Parse JSON package export plus individually exported mesh assets. It does not embed CUE4Parse, mount PAK/IoStore archives, manage AES keys, or guess UE serialization versions inside Blender.

The fallback instead ports the reusable scene-assembly algorithm from FModel's viewer into the existing Blender recovery boundary:

1. Resolve `UWorld.PersistentLevel` and `ULevel.Actors` as package-index references.
2. Discover mesh components through `InstanceComponents`, common component property names, and CUE4Parse JSON's
   `BlueprintCreatedComponents` representation for runtime construction-script components.
3. Resolve `StaticMesh` and `PerInstanceSMData` through the component `Template` chain when the direct export omits them.
4. Compose `AttachParent` transforms recursively with cycle protection.
5. Convert each mesh once through the existing asset cache and create Blender linked instances for placements.
6. Fall back to structural component recognition for partial JSON documents that omit the World/Level/Actor graph.

This is based on the behavior in [FModel Renderer.cs at c5e6900](https://github.com/4sval/FModel/blob/c5e6900bb4a8eb0bd4b2dd749cbda270ab7b6b39/FModel/Views/Snooper/Renderer.cs), cross-checked against CUE4Parse's [UWorld](https://github.com/FabianFG/CUE4Parse/blob/d5dac24c9179b41d79d4da56b243baad2154a127/CUE4Parse/UE4/Objects/Engine/UWorld.cs), [ULevel](https://github.com/FabianFG/CUE4Parse/blob/d5dac24c9179b41d79d4da56b243baad2154a127/CUE4Parse/UE4/Objects/Engine/ULevel.cs), [USceneComponent](https://github.com/FabianFG/CUE4Parse/blob/d5dac24c9179b41d79d4da56b243baad2154a127/CUE4Parse/UE4/Assets/Exports/Component/USceneComponent.cs), and [UStaticMeshComponent](https://github.com/FabianFG/CUE4Parse/blob/d5dac24c9179b41d79d4da56b243baad2154a127/CUE4Parse/UE4/Assets/Exports/Component/StaticMesh/UStaticMeshComponent.cs) at d5dac24.

## Fallback order

For each placed component:

1. Direct component mesh reference.
2. Mesh reference inherited from an internally resolvable `Template`.
3. Existing exported Engine BasicShapes mesh through the normal asset resolver.
4. Procedural Blender Cube, Sphere, Cylinder, Cone, or Plane when that Engine mesh is absent and the mesh policy is not `FAIL_IMPORT`.

Fallback-created objects keep diagnostic custom properties:

- `umodel_tools_asset_fallback = procedural_basic_shape`
- `umodel_tools_reference_fallback = template_mesh_reference`
- `umodel_tools_geometry_fallback = spline_chord_approximation`
- `umodel_tools_unreal_asset_path`

## Deliberate limits

- External package templates and additional worlds still need to be present in the exported inputs; the Blender add-on is not an Unreal package parser.
- Spline mesh fallback preserves the segment midpoint, direction, and chord length, but does not reproduce FModel's full spline deformation.
- Landscapes, geometry collections without an exported proxy mesh, Nanite-only data without a convertible mesh, and game-specific runtime construction remain outside this generic fallback.
- A `FAIL_IMPORT` mesh policy continues to require the exact exported asset and disables procedural BasicShapes substitution.
