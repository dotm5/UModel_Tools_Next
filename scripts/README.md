# Repository Scripts

This directory separates reusable project tooling from local-only probes:

- `audit/`: tracked audit tools that inspect exports or addon behavior without running a full Blender import.
- `export/`: local UModel export helpers. Scripts in this folder can contain machine-specific paths or keys and are ignored unless explicitly promoted.
- `probes/`: local Blender/API probes used while investigating behavior. These are ignored by default.
