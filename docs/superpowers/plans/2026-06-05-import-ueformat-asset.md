# Import UEFormat Asset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an `Import UEFormat Asset` workflow that imports a selected `.uemodel`, resolves FModel material JSON and texture references with existing three-level path inference, records conflicts without interrupting import, and supports project-local manual resolution plus material rebuild.

**Architecture:** Keep mesh import on the existing `_load_asset` / `AssetDB` pipeline. Add small UEFormat-focused support modules for material descriptor resolution, project-local conflict state, and rebuild context, then wire them into the existing operator, asset importer, and Blender side panel. Conflicts never block import; unresolved slots get simple color-coded PBR placeholders written to the local asset cache.

**Tech Stack:** Python, Blender `bpy`, existing `umodel_tools` path resolver, UEFormat parser, FModel material JSON parser, TOML material rule datasets, pytest/Blender integration tests.

---

## File Structure

- Create `umodel_tools/ueformat/asset_context.py`: dataclasses and object custom-property serialization for UEFormat asset import context.
- Create `umodel_tools/ueformat/material_resolution.py`: resolve `.uemodel` material slots to FModel JSON descriptors, detect ambiguous JSON and texture paths, and produce placeholder instructions.
- Create `umodel_tools/ueformat/conflicts.py`: project-local conflict/override JSON file under the asset cache.
- Modify `umodel_tools/mesh_backends/backends.py`: expose material descriptors with slot index and candidate state.
- Modify `umodel_tools/asset_importer.py`: handle ambiguous descriptors/textures, write color-coded placeholder PBR materials, force material rebuild without touching texture cache.
- Modify `umodel_tools/operators.py`: rename user-facing import to `Import UEFormat Asset`, add ruleset selection, pass path inference settings, initialize conflict reporting, and add rebuild/apply operators.
- Modify `umodel_tools/panels.py`: add 3D View `N` panel with `Material JSON Conflicts` and `Texture Conflicts` sections.
- Modify `umodel_tools/localization.py`: add Chinese/English labels used by the new UI.
- Add tests in `tests/test_ueformat_material_resolution.py`, `tests/test_ueformat_conflicts.py`, and extend Blender tests where possible.

---

### Task 1: Project-Local Conflict Store

**Files:**
- Create: `umodel_tools/ueformat/conflicts.py`
- Test: `tests/test_ueformat_conflicts.py`

- [ ] **Step 1: Write failing tests**

```python
import json
from pathlib import Path

from umodel_tools.ueformat import conflicts


def test_conflict_store_round_trips_project_local_override(tmp_path):
    cache_dir = tmp_path / "asset_cache"
    store = conflicts.UEFormatConflictStore(str(cache_dir))
    key = conflicts.ConflictKey(
        kind="material_json",
        uemodel_asset_path="PM/Content/A/Model.uemodel",
        material_slot="MI_Body",
        parameter_name="",
        original_reference="/Game/A/MI_Body.MI_Body",
    )

    store.set_override(key, "PM/Content/A/MI_Body.json")
    store.save()

    loaded = conflicts.UEFormatConflictStore(str(cache_dir))
    assert loaded.get_override(key) == "PM/Content/A/MI_Body.json"
    assert Path(loaded.path).name == "umodel_tools_conflict_overrides.json"


def test_conflict_store_saves_candidates_without_override(tmp_path):
    store = conflicts.UEFormatConflictStore(str(tmp_path))
    key = conflicts.ConflictKey(
        kind="texture",
        uemodel_asset_path="PM/Content/A/Model.uemodel",
        material_slot="MI_Body",
        parameter_name="BaseMap",
        original_reference="PM/Content/A/T_Body.T_Body",
    )

    store.record_conflict(
        key,
        status="ambiguous",
        candidates=["PM/Content/A/T_Body.png", "PM/Content/B/T_Body.png"],
    )
    store.save()

    payload = json.loads(Path(store.path).read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["conflicts"][0]["status"] == "ambiguous"
    assert payload["conflicts"][0]["candidates"] == [
        "PM/Content/A/T_Body.png",
        "PM/Content/B/T_Body.png",
    ]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_ueformat_conflicts.py -q`
Expected: FAIL with `ModuleNotFoundError` or missing classes.

- [ ] **Step 3: Implement conflict store**

Create `umodel_tools/ueformat/conflicts.py` with `ConflictKey`, `ConflictRecord`, and `UEFormatConflictStore`. Use deterministic key strings, JSON version `1`, and create the asset cache directory on save.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_ueformat_conflicts.py -q`
Expected: PASS.

---

### Task 2: UEFormat Asset Context Serialization

**Files:**
- Create: `umodel_tools/ueformat/asset_context.py`
- Modify: `umodel_tools/panels.py`
- Test: `tests/test_ueformat_asset_context.py`

- [ ] **Step 1: Write failing tests**

```python
from umodel_tools.ueformat.asset_context import UEFormatAssetContext


def test_context_round_trips_through_plain_dict():
    context = UEFormatAssetContext(
        uemodel_asset_path="PM/Content/A/Model.uemodel",
        source_filepath="D:/exports/PM/Content/A/Model.uemodel",
        export_root="D:/exports",
        asset_cache_dir="D:/exports/temp-assets",
        game_profile="generic",
        path_inference_mode="BASIC_DEFAULT",
        enable_suffix_index=True,
        material_rule_paths=["D:/rules/generic.toml", "D:/rules/calabiyau_game.toml"],
        conflict_store_path="D:/exports/temp-assets/umodel_tools_conflict_overrides.json",
        material_slots=[
            {"slot_index": 0, "material_name": "MI_Body", "descriptor_ref": "PM/Content/A/MI_Body.MI_Body"},
        ],
    )

    restored = UEFormatAssetContext.from_dict(context.to_dict())
    assert restored == context
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/test_ueformat_asset_context.py -q`
Expected: FAIL because module is missing.

- [ ] **Step 3: Implement dataclass**

Create `UEFormatAssetContext` with `to_dict()` and `from_dict()`. Keep values JSON-serializable and avoid storing candidate lists on Blender objects.

- [ ] **Step 4: Add object properties**

Extend `UMODELTOOLS_PG_asset` in `panels.py` with string fields:
`ueformat_context_json`, `ueformat_conflict_store_path`, and bool `is_ueformat_asset`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_ueformat_asset_context.py -q`
Expected: PASS.

---

### Task 3: Material JSON Resolution

**Files:**
- Create: `umodel_tools/ueformat/material_resolution.py`
- Modify: `umodel_tools/mesh_backends/backends.py`
- Test: `tests/test_ueformat_material_resolution.py`

- [ ] **Step 1: Write failing tests for JSON priority**

Create fixtures in a temp export tree with:
`PM/Content/A/Mesh3D/Model.uemodel`, `MI_Body.json`, and `Materials/MI_Hair.json`.
Assert resolution order:
`material_path` JSON first, same-dir name second, `Materials/name.json` third.

- [ ] **Step 2: Write failing test for ambiguous aggressive suffix**

Create two `MI_Body.json` files in different folders. With `AGGRESSIVE`, assert status is `ambiguous` and both candidates are returned. With `BASIC_DEFAULT`, assert unresolved or direct match only.

- [ ] **Step 3: Implement resolver**

Define:
`MaterialSlotReference(slot_index, material_name, material_path, first_index, num_faces)`
`ResolvedMaterialDescriptor(slot_index, material_name, descriptor_ref, json_path, status, candidates)`
`resolve_material_descriptors(slots, uemodel_filepath, export_root, settings, overrides)`

Use existing `fmodel_material_json.json_path_from_material_reference()` and `umodel_path_resolver.resolve_umodel_export_asset_path()`.

- [ ] **Step 4: Wire backend metadata**

In `mesh_backends/backends.py`, replace `_build_material_descriptors()` internals with calls to the new resolver, but keep the existing metadata shape plus `slot_index`, `status`, and `candidates` fields.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_ueformat_material_resolution.py -q`
Expected: PASS.

---

### Task 4: Placeholder PBR Materials and Non-Blocking Missing JSON

**Files:**
- Modify: `umodel_tools/asset_importer.py`
- Test: extend `tests/test_ueformat_pipeline.py`

- [ ] **Step 1: Write failing test**

Use a `.uemodel` fixture or synthetic backend metadata where one material descriptor has `status="unresolved"`. Assert import completes and writes a material named like `MI_Body_Unresolved_PBR` with Principled BSDF base color gray.

- [ ] **Step 2: Implement placeholder helper**

Add `_create_placeholder_pbr_material(material_name, status)` with colors:
`unresolved` gray, `ambiguous` yellow, `texture_missing` blue, `texture_ambiguous` pink.
Write it through the same material library path used by normal materials.

- [ ] **Step 3: Update material assignment**

When descriptor status is unresolved/ambiguous and no override exists, record conflict/missing info and use placeholder. Do not raise unless mesh itself is missing.

- [ ] **Step 4: Run relevant tests**

Run: `python -m pytest tests/test_ueformat_pipeline.py tests/test_ueformat_material_resolution.py -q`
Expected: PASS.

---

### Task 5: Texture Conflict Handling Without Texture Cache Rebuild

**Files:**
- Modify: `umodel_tools/asset_importer.py`
- Test: extend `tests/test_ueformat_conflicts.py` or add `tests/test_ueformat_texture_resolution.py`

- [ ] **Step 1: Write failing test**

Create a material JSON with `BaseMap` pointing to a texture name that has two suffix matches. Assert the conflict store records kind `texture`, parameter `BaseMap`, and candidates, while material creation completes using placeholder color for that texture input.

- [ ] **Step 2: Implement texture conflict recording**

In the texture loop around `_resolve_umodel_path()`, when status is `ambiguous`, record candidates and continue without importing image. Do not rebuild or delete existing texture `.blend` files.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_ueformat_conflicts.py -q`
Expected: PASS.

---

### Task 6: Import UEFormat Asset Operator UI

**Files:**
- Modify: `umodel_tools/operators.py`
- Modify: `umodel_tools/localization.py`
- Test: extend `tests/test_import_operator_ui.py`

- [ ] **Step 1: Write failing UI test**

Assert operator `umodel_tools.import_ueformat_model` label is `Import UEFormat Asset` or add a new `umodel_tools.import_ueformat_asset` alias. Assert draw exposes export dir, asset cache dir, path inference mode, and material rule dataset controls.

- [ ] **Step 2: Implement label and rule override selection**

Keep compatibility with existing id if needed. Add collection-like transient rule selection from preference datasets. Default enabled paths come from preferences; local testing can enable `generic + calabiyau_game`, release defaults remain preference-driven.

- [ ] **Step 3: Record context on imported object**

After appending the asset cache objects, write `UEFormatAssetContext.to_dict()` JSON to `main_object.umodel_tools_asset.ueformat_context_json`, set `is_ueformat_asset=True`, and set conflict store path.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_import_operator_ui.py -q`
Expected: PASS.

---

### Task 7: N Panel Conflict Browser

**Files:**
- Modify: `umodel_tools/panels.py`
- Modify: `umodel_tools/operators.py`
- Test: Blender UI smoke test if available; otherwise unit-test store read helpers.

- [ ] **Step 1: Add panel classes**

Create `UMODELTOOLS_PT_ueformat_asset_tools` in `VIEW_3D`, `UI`, category `UModel Tools`. Poll on selected object with `umodel_tools_asset.is_ueformat_asset`.

- [ ] **Step 2: Add two expandable sections**

Use scene bools or object bools:
`show_ueformat_material_conflicts`
`show_ueformat_texture_conflicts`.
Render counts and candidate enum/dropdown rows from the project conflict store.

- [ ] **Step 3: Add apply operator**

Add `UMODELTOOLS_OT_apply_ueformat_conflict_choice` that writes selected override into the project conflict store. Default mode updates asset cache, with optional scene-only mode.

- [ ] **Step 4: Verify manually**

Run Blender, import reference asset, press `N`, open `UModel Tools`, confirm both conflict groups appear and no import flow is interrupted.

---

### Task 8: Rebuild Materials for Selected Asset

**Files:**
- Modify: `umodel_tools/operators.py`
- Modify: `umodel_tools/asset_importer.py`
- Test: Blender integration test where possible

- [ ] **Step 1: Write failing integration test**

Import UEFormat asset with missing/ambiguous material, write an override into the conflict store, run `bpy.ops.umodel_tools.rebuild_ueformat_asset_materials()`, and assert material cache `.blend` is rewritten and current object material slot is no longer the unresolved placeholder.

- [ ] **Step 2: Implement rebuild operator**

Read `UEFormatAssetContext` from selected object. Rebuild only material `.blend` caches for that asset's slots. Do not delete or rewrite texture `.blend` files.

- [ ] **Step 3: Rebind scene materials**

After rebuilding, load the new material libraries and replace the selected object's material slots by slot/material name.

- [ ] **Step 4: Run integration test**

Run the Blender test command used by the repository for `tests/test_ueformat_pipeline.py`.
Expected: PASS and no bulk texture cache IO.

---

### Task 9: Manual QA Against Reference Data

**Files:**
- No source files unless failures are found.

- [ ] **Step 1: Import simple reference**

Use `D:\addon\reference\my real project\model unpack\PM\Content\PaperMan\SkinAssets\Characters\Kanami\S103\Mesh3D\Kanami_Mesh_103.uemodel`.
Export root: `D:\addon\reference\my real project\model unpack`.
Rules: `generic + calabiyau_game`.
Path mode: `BASIC_DEFAULT`, then `AGGRESSIVE`.

- [ ] **Step 2: Confirm behavior**

Import completes, missing JSON uses colored PBR placeholders, conflicts appear in N panel, and rebuild does not touch texture cache files.

- [ ] **Step 3: Import difficult references**

Try `SK_Chiyo_Lobby_S102` and `SK_HuiXing_Lobby_S211` from `reference\calabiyau_references`.
Record unresolved shader classes and decide whether they are rule-data work or importer bugs.

---

## Verification

- Run unit tests:
  `python -m pytest tests/test_ueformat_conflicts.py tests/test_ueformat_asset_context.py tests/test_ueformat_material_resolution.py -q`
- Run existing non-Blender tests:
  `python -m pytest tests/test_material_decision.py tests/test_material_mapping_audit.py -q`
- Run Blender integration tests already used by this repo:
  `tests/test_ueformat_pipeline.py`, `tests/test_blender_material_nodes.py`, and `tests/test_import_operator_ui.py`.
- Manually verify in Blender with `Kanami_Mesh_103.uemodel`.

## Self-Review

- Spec coverage: covers two-stage import, three-level path inference, JSON-first texture path parsing, non-blocking conflicts, project-local overrides, N panel grouping, default local resource library update, material rebuild, no texture cache rebuild, missing JSON PBR placeholders, and manual rule selection.
- Placeholder scan: no `TBD`/`TODO` steps remain.
- Type consistency: planned modules use stable names `UEFormatConflictStore`, `UEFormatAssetContext`, and `ResolvedMaterialDescriptor` across tasks.
