<p align="center">
  <img src="docs/source/images/umodel-tools-next-logo.svg" alt="UModel Tools Next" width="840">
</p>

# UModel Tools Next

UModel Tools Next is dotm5's fork of the UModel Tools Blender add-on.
It turns UModel and FModel exports into a more practical Blender map recovery pipeline, with stronger path matching, local single-file imports, and broader shader reconstruction for packed Unreal texture patterns.

Repository: https://github.com/dotm5/UModel_Tools_Next

## Why This Fork

- Recovers Unreal Engine map JSON exports into Blender scenes, including static mesh placement and reusable asset caches.
- Matches assets across UModel/FModel-style export layouts, local single-file imports, and mixed path conventions.
- Reconstructs common packed PBR material layouts, including ORM/RMO masks, roughness/metallic/specular routing, and alpha-packed emission masks.
- Converts DirectX normal maps for Blender's OpenGL-style tangent space.
- Applies shader hints for glass, water, emissive, foliage-like alpha, and other Unreal material patterns.
- Produces missing-asset diagnostics so incomplete exports are easier to fix instead of silently failing.
- Keeps packaging lean: only runtime site packages are bundled, while fork-maintained reference importers live inline.

## Showcase

![UModel Tools Next imported map and reconstructed shader graph](docs/source/images/readme-blender-viewport-overview.png)

Imported Unreal map content in Blender, shown alongside the reconstructed material node graph for packed PBR textures, DirectX normal conversion, and shader routing.

## Features

- Map import from Unreal Engine JSON exports with static mesh placement.
- Blender asset cache generation and reuse for repeated map recovery work.
- UModel/FModel path inference for exports that do not share one exact directory shape.
- PBR shader reconstruction from Unreal texture parameter patterns.
- Packed ORM/RMO support, DirectX normal conversion, glass/water hints, and packed diffuse alpha emission masks.
- Missing-asset reports for diagnosing partial or inconsistent exports.

## Packaging

The distributed Blender add-on keeps only runtime site packages in `umodel_tools/third_party`.
Reference importer code that is part of this fork, such as the PSK/PSKX importer integration, lives inline under `umodel_tools` so the vendored dependency folder does not grow into a mixed plugin dump.

## Visual Identity

The project icon uses an abstract viewport, map grid, package cube, and shader node links to represent the recovery workflow without copying Unreal Engine, Blender, FModel, or UModel marks.

## Credits

- Skarn for the original UModel Tools add-on.
- Gildor for [UEViewer](https://www.gildor.org/en/projects/umodel).
- Developers of [FModel](https://fmodel.app).
- Developers of the original UE map import scripts.
- Befzz for the Blender PSK/PSA importer foundation.

## Disclaimer

Game assets and maps are copyrighted by their respective owners.
This software is intended for artistic, archival, and research workflows.
