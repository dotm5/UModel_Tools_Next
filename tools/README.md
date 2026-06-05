# Local Tools

This directory is reserved for local helper tools during development. Do not
commit FModel, UModel, DLLs, EXEs, extracted archives, or generated tool output
from this directory.

Prefer keeping tools under `D:\addon_dev\tools` and pointing the addon or tests
to them with environment variables:

```powershell
$env:UMODEL_TOOLS_FMODEL_EXE = "D:\addon_dev\tools\fmodel\FModel.exe"
$env:UMODEL_TOOLS_UMODEL_DIR = "D:\addon_dev\tools\umodel_win32"
```

The repository may keep this README as a placeholder, but the local tool
payloads themselves are not part of the Git tree or release package.
