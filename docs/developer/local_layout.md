# Local Development Layout

UModel Tools Next keeps the Git checkout small and reproducible. Large tools,
exports, cache databases, and manual validation output should live beside the
repository instead of inside it.

Recommended layout on Windows:

```text
D:\addon
D:\addon_dev\tools
D:\addon_dev\reference
D:\addon_dev\manual_tests
D:\addon_dev\cache
```

## Directories

`D:\addon` is the Git repository. Keep source code, tests, small fixtures, and
project documentation here.

`D:\addon_dev\tools` is the local tool area for FModel, UModel, and other
external helper programs. Prefer environment variables over committing local
tool paths.

`D:\addon_dev\reference` is the large ground truth and upstream reference area.
Use it for exports, original upstream archives, screenshots, and comparison
assets that are too large or too volatile for Git.

`D:\addon_dev\manual_tests` is the output area for manual Blender validation
runs. Files here can be recreated and should not be packaged with the addon.

`D:\addon_dev\cache` is for generated caches, SQLite databases, temporary
indexes, and other runtime artifacts.

## Environment Variables

Use these variables when local tools are needed:

```powershell
$env:UMODEL_TOOLS_FMODEL_EXE = "D:\addon_dev\tools\fmodel\FModel.exe"
$env:UMODEL_TOOLS_UMODEL_DIR = "D:\addon_dev\tools\umodel_win32"
```

Do not move or rewrite existing `reference\my real project` content during this
cleanup phase. It remains a local reference area until a later migration.
