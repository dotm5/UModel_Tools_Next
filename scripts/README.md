# Repository Scripts

This directory separates reusable project tooling from local-only probes:

- `audit/`: tracked audit tools that inspect exports or addon behavior without running a full Blender import.
- `export/`: local UModel export helpers. Scripts in this folder can contain machine-specific paths or keys and are ignored unless explicitly promoted.
  - `export_textures_from_material_json.interactive.ps1`: PowerShell 7 TUI helper for extracting texture targets from one material JSON file and exporting them with UModel.
- `probes/`: local Blender/API probes used while investigating behavior. These are ignored by default.
