#requires -version 7.0
param(
    [switch]$SelfTest,
    [string]$ConfigJson = "",
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

function Assert-Equal {
    param(
        [object]$Actual,
        [object]$Expected,
        [string]$Message
    )

    if ($Actual -ne $Expected) {
        throw "ASSERT EQUAL FAILED: $Message`nExpected: $Expected`nActual:   $Actual"
    }
}

function Assert-ArrayEqual {
    param(
        [object[]]$Actual,
        [object[]]$Expected,
        [string]$Message
    )

    if ($Actual.Count -ne $Expected.Count) {
        throw "ASSERT ARRAY FAILED: $Message`nExpected count: $($Expected.Count)`nActual count:   $($Actual.Count)"
    }

    for ($i = 0; $i -lt $Expected.Count; $i++) {
        if ($Actual[$i] -ne $Expected[$i]) {
            throw "ASSERT ARRAY FAILED: $Message`nIndex: $i`nExpected: $($Expected[$i])`nActual:   $($Actual[$i])"
        }
    }
}

function Parse-UModelTagList {
    param([string]$Text)

    $items = [System.Collections.Generic.List[object]]::new()
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $items.ToArray()
    }

    $lines = $Text -split "`r?`n"
    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        if ($trimmed.EndsWith(":")) {
            continue
        }

        $match = [regex]::Match($line, '^\s*(?<tag>[A-Za-z0-9_.+\-\[\]]+)\s{2,}(?<name>.+?)\s*$')
        if (-not $match.Success) {
            continue
        }

        $items.Add([pscustomobject]@{
            Tag = $match.Groups["tag"].Value
            Name = $match.Groups["name"].Value.Trim()
        })
    }

    return $items.ToArray()
}

function Normalize-UModelTargetPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }

    $normalized = $Path.Trim().Replace("\", "/")
    $normalized = [regex]::Replace($normalized, "^/+", "")
    $normalized = [regex]::Replace($normalized, "\.\d+$", "")

    $lastSlash = $normalized.LastIndexOf("/")
    $leafStart = $lastSlash + 1
    $leaf = $normalized.Substring($leafStart)
    $lastDot = $leaf.LastIndexOf(".")

    if ($lastDot -gt 0) {
        $baseName = $leaf.Substring(0, $lastDot)
        $suffix = $leaf.Substring($lastDot + 1)

        if ([string]::Equals($suffix, $baseName, [System.StringComparison]::OrdinalIgnoreCase)) {
            $normalized = $normalized.Substring(0, $leafStart) + $baseName
        }
    }

    return $normalized
}

function Add-NormalizedTextureTarget {
    param(
        [System.Collections.Generic.Dictionary[string,string]]$TargetsByKey,
        [string]$TargetPath
    )

    $normalized = Normalize-UModelTargetPath $TargetPath
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return
    }

    if (-not $TargetsByKey.ContainsKey($normalized)) {
        $TargetsByKey.Add($normalized, $normalized)
    }
}

function Get-TextureTargetsFromJsonFile {
    param([string]$Path)

    $json = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -NoEnumerate
    $targetsByKey = [System.Collections.Generic.Dictionary[string,string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $foundSupportedShape = $false

    if ($json -is [System.Array]) {
        foreach ($item in $json) {
            $textureParameterValues = $item.Properties.TextureParameterValues
            if ($null -eq $textureParameterValues) {
                continue
            }

            $foundSupportedShape = $true
            foreach ($textureParameterValue in @($textureParameterValues)) {
                Add-NormalizedTextureTarget $targetsByKey ([string]$textureParameterValue.ParameterValue.ObjectPath)
            }
        }
    } else {
        $texturesProperty = $json.PSObject.Properties["Textures"]
        if ($null -ne $texturesProperty) {
            $foundSupportedShape = $true

            foreach ($property in $texturesProperty.Value.PSObject.Properties) {
                Add-NormalizedTextureTarget $targetsByKey ([string]$property.Value)
            }
        }
    }

    if (-not $foundSupportedShape) {
        throw "Texture JSON shape is not supported: $Path"
    }

    return @($targetsByKey.Values | Sort-Object)
}

function Get-TextureTargetsFromJsonFiles {
    param([string[]]$Paths)

    throw "Multi-file texture target extraction is not supported yet."
}

function Test-TuiAvailable {
    if ($NonInteractive) {
        return $false
    }

    try {
        $null = $Host.UI.RawUI.KeyAvailable
        return $true
    } catch {
        return $false
    }
}

function New-ManualGameTagItem {
    return [pscustomobject]@{
        Tag = "__manual__"
        Name = "Manual input"
    }
}

function Filter-GameTagItems {
    param(
        [object[]]$Items,
        [string]$Filter
    )

    if ([string]::IsNullOrWhiteSpace($Filter)) {
        return @($Items)
    }

    $needle = $Filter.Trim()
    return @($Items | Where-Object {
        ([string]$_.Tag).IndexOf($needle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        ([string]$_.Name).IndexOf($needle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    })
}

function Read-TextWithDefault {
    param(
        [string]$Prompt,
        [string]$Default = "",
        [switch]$Required,
        [switch]$AllowBlankCancel
    )

    while ($true) {
        $displayPrompt = $Prompt
        if (-not [string]::IsNullOrWhiteSpace($Default)) {
            $displayPrompt = "$Prompt [$Default]"
        }

        $value = Read-Host $displayPrompt
        if ([string]::IsNullOrWhiteSpace($value)) {
            if ($AllowBlankCancel) {
                return $null
            }

            $value = $Default
        }

        if (-not $Required -or -not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }

        Write-Host "A value is required."
    }
}

function Read-YesNo {
    param(
        [string]$Prompt,
        [bool]$Default = $true
    )

    $defaultText = if ($Default) { "Y/n" } else { "y/N" }
    while ($true) {
        $choice = (Read-Host "$Prompt [$defaultText]").Trim()
        if ([string]::IsNullOrWhiteSpace($choice)) {
            return $Default
        }

        if ([string]::Equals($choice, "y", [System.StringComparison]::OrdinalIgnoreCase) -or
            [string]::Equals($choice, "yes", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }

        if ([string]::Equals($choice, "n", [System.StringComparison]::OrdinalIgnoreCase) -or
            [string]::Equals($choice, "no", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }

        Write-Host "Enter yes or no."
    }
}

function Select-GameTag {
    param(
        [object[]]$Items,
        [string]$Prompt = "Select -game tag"
    )

    $allItems = @($Items) + (New-ManualGameTagItem)

    if (-not (Test-TuiAvailable)) {
        Write-Host $Prompt
        for ($i = 0; $i -lt $allItems.Count; $i++) {
            Write-Host ("[{0}] {1} {2}" -f ($i + 1), $allItems[$i].Tag, $allItems[$i].Name)
        }

        while ($true) {
            $choice = (Read-Host "Enter number or manual -game tag").Trim()
            if ([string]::IsNullOrWhiteSpace($choice)) {
                return $null
            }

            [int]$number = 0
            if ([int]::TryParse($choice, [ref]$number)) {
                if ($number -ge 1 -and $number -le $allItems.Count) {
                    $selected = $allItems[$number - 1]
                    if ($selected.Tag -eq "__manual__") {
                        $manualTag = Read-TextWithDefault "Manual -game tag" "" -Required -AllowBlankCancel
                        if ([string]::IsNullOrWhiteSpace($manualTag)) {
                            continue
                        }

                        return $manualTag
                    }

                    return $selected.Tag
                }
            } else {
                return $choice
            }

            Write-Host "Enter a number from 1 to $($allItems.Count), or type a manual tag."
        }
    }

    $filter = ""
    $selectedIndex = 0

    while ($true) {
        $visibleItems = @(Filter-GameTagItems $allItems $filter)
        if ($selectedIndex -ge $visibleItems.Count) {
            $selectedIndex = [Math]::Max(0, $visibleItems.Count - 1)
        }

        Clear-Host
        Write-Host $Prompt
        Write-Host ("Filter: {0}" -f $filter)
        Write-Host ""

        if ($visibleItems.Count -eq 0) {
            Write-Host "No matching tags."
        } else {
            for ($i = 0; $i -lt $visibleItems.Count; $i++) {
                $marker = if ($i -eq $selectedIndex) { ">" } else { " " }
                Write-Host ("{0} {1,-12} {2}" -f $marker, $visibleItems[$i].Tag, $visibleItems[$i].Name)
            }
        }

        $key = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
        switch ($key.VirtualKeyCode) {
            13 {
                if ($visibleItems.Count -eq 0) {
                    continue
                }

                $selected = $visibleItems[$selectedIndex]
                if ($selected.Tag -eq "__manual__") {
                    $manualTag = Read-TextWithDefault "Manual -game tag" "" -Required -AllowBlankCancel
                    if ([string]::IsNullOrWhiteSpace($manualTag)) {
                        continue
                    }

                    return $manualTag
                }

                return $selected.Tag
            }
            27 {
                return $null
            }
            8 {
                if ($filter.Length -gt 0) {
                    $filter = $filter.Substring(0, $filter.Length - 1)
                    $selectedIndex = 0
                }
            }
            38 {
                if ($visibleItems.Count -gt 0) {
                    $selectedIndex = ($selectedIndex + $visibleItems.Count - 1) % $visibleItems.Count
                }
            }
            40 {
                if ($visibleItems.Count -gt 0) {
                    $selectedIndex = ($selectedIndex + 1) % $visibleItems.Count
                }
            }
            default {
                if (-not [char]::IsControl($key.Character)) {
                    $filter += $key.Character
                    $selectedIndex = 0
                }
            }
        }
    }
}

function Resolve-TextureFormatArg {
    param([string]$TextureFormat)

    $format = if ($null -eq $TextureFormat) { "" } else { $TextureFormat.Trim().ToLowerInvariant() }
    switch ($format) {
        "png" { return "-png" }
        "dds" { return "-dds" }
        "tga" { return "" }
        default { throw "Unsupported texture format: $TextureFormat. Use png, dds, or tga." }
    }
}

function Load-ConfigFromJson {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Config JSON was not found: $Path"
    }

    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 32
    $format = if ($raw.PSObject.Properties["TextureFormat"] -and -not [string]::IsNullOrWhiteSpace([string]$raw.TextureFormat)) {
        [string]$raw.TextureFormat
    } else {
        "png"
    }

    return [pscustomobject]@{
        UModelExe = [string]$raw.UModelExe
        PakRoot = [string]$raw.PakRoot
        JsonPath = [string]$raw.JsonPath
        OutDir = [string]$raw.OutDir
        AesKey = [string]$raw.AesKey
        GameTag = [string]$raw.GameTag
        TextureFormat = $format
        TextureFormatArg = Resolve-TextureFormatArg $format
        DryRun = [bool]$raw.DryRun
        Overwrite = [bool]$raw.Overwrite
        TryPathVariants = [bool]$raw.TryPathVariants
    }
}

function Test-ExportConfig {
    param([object]$Config)

    if ([string]::IsNullOrWhiteSpace($Config.UModelExe) -or -not (Test-Path -LiteralPath $Config.UModelExe)) {
        throw "UModel executable was not found: $($Config.UModelExe)"
    }
    if ([string]::IsNullOrWhiteSpace($Config.PakRoot) -or -not (Test-Path -LiteralPath $Config.PakRoot)) {
        throw "Pak/root path was not found: $($Config.PakRoot)"
    }
    if ([string]::IsNullOrWhiteSpace($Config.JsonPath) -or -not (Test-Path -LiteralPath $Config.JsonPath)) {
        throw "Material JSON was not found: $($Config.JsonPath)"
    }
    if ([string]::IsNullOrWhiteSpace($Config.GameTag)) {
        throw "UModel game tag is required."
    }
    if ([string]::IsNullOrWhiteSpace($Config.OutDir)) {
        throw "Output directory is required."
    }

    Resolve-TextureFormatArg $Config.TextureFormat | Out-Null
    [System.IO.Directory]::CreateDirectory($Config.OutDir) | Out-Null
}

function New-UModelTextureExportConfig {
    if (-not [string]::IsNullOrWhiteSpace($ConfigJson)) {
        $config = Load-ConfigFromJson $ConfigJson
        Test-ExportConfig $config
        return $config
    }

    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $defaultUModel = Join-Path $repoRoot "tools\umodel_win32\umodel_acl_2.1.exe"

    $umodelExe = Read-TextWithDefault "UModel executable" $defaultUModel -Required
    if (-not (Test-Path -LiteralPath $umodelExe)) {
        throw "UModel executable was not found: $umodelExe"
    }

    $tagText = & $umodelExe -taglist 2>&1 | Out-String
    $tagItems = @(Parse-UModelTagList $tagText)
    if ($tagItems.Count -eq 0) {
        Write-Host "Could not parse UModel tag list. Manual input will be used." -ForegroundColor Yellow
        $gameTag = Read-TextWithDefault "Manual -game tag" "" -Required
    } else {
        $gameTag = Select-GameTag $tagItems
    }

    $pakRoot = Read-TextWithDefault "Paks/root path for -path" "" -Required
    $jsonPath = Read-TextWithDefault "Material JSON path" "" -Required
    $outDir = Read-TextWithDefault "Output directory" (Join-Path ([Environment]::GetFolderPath("Desktop")) "UModelTextureExport") -Required
    $aesKey = Read-TextWithDefault "AES key, blank for none" ""
    $format = Read-TextWithDefault "Texture format: png, dds, or tga" "png" -Required
    $dryRun = Read-YesNo "Dry run" $false
    $overwrite = Read-YesNo "Overwrite existing files" $false
    $tryPathVariants = Read-YesNo "Try common path variants" $true

    $config = [pscustomobject]@{
        UModelExe = $umodelExe
        PakRoot = $pakRoot
        JsonPath = $jsonPath
        OutDir = $outDir
        AesKey = $aesKey
        GameTag = $gameTag
        TextureFormat = $format
        TextureFormatArg = Resolve-TextureFormatArg $format
        DryRun = $dryRun
        Overwrite = $overwrite
        TryPathVariants = $tryPathVariants
    }

    Test-ExportConfig $config
    return $config
}

function Invoke-SelfTest {
    Write-Host "SELFTEST: tag parser"

    $tagListText = @"
Unreal engine 4:
   ue4.[0-27]  Unreal engine 4.0-4.27
      ue4.25+  Unreal engine 4.25 Plus
          cal  Calabiyau / Strinova
      cal_old  Calabiyau / Strinova (old)
          ce2  Caligula Effect 2
"@

    $tags = @(Parse-UModelTagList $tagListText)
    Assert-Equal $tags.Count 5 "tag parser should parse five tag rows"
    Assert-Equal $tags[2].Tag "cal" "Calabiyau tag should be cal"
    Assert-Equal $tags[3].Tag "cal_old" "old Calabiyau tag should be cal_old"

    Write-Host "SELFTEST: target normalization"

    Assert-Equal (Normalize-UModelTargetPath "/Game/A/T_Body.T_Body") "Game/A/T_Body" "matching Unreal object suffix should be removed"
    Assert-Equal (Normalize-UModelTargetPath "PM\Content\A\T_Body.0") "PM/Content/A/T_Body" "numeric suffix and backslashes should be normalized"
    Assert-Equal (Normalize-UModelTargetPath "PM/Content/A/T_Body.uasset") "PM/Content/A/T_Body.uasset" "ordinary file extensions should be preserved"

    Write-Host "SELFTEST: dictionary JSON targets"

    $selfTestRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("umodel-json-selftest-" + [guid]::NewGuid().ToString("N"))
    New-Item -Path $selfTestRoot -ItemType Directory | Out-Null

    try {
        $dictJsonPath = Join-Path $selfTestRoot "dictionary.json"
        @{
            Textures = @{
                Body = "/Game/A/T_Body.T_Body"
                Normal = "PM\Content\A\T_Body_N.0"
                Duplicate = "game/a/t_body.t_body"
            }
        } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $dictJsonPath -Encoding UTF8

        $dictTargets = @(Get-TextureTargetsFromJsonFile $dictJsonPath)
        Assert-ArrayEqual $dictTargets @("Game/A/T_Body", "PM/Content/A/T_Body_N") "dictionary JSON texture values should normalize to sorted unique targets"

        Write-Host "SELFTEST: FModel array JSON targets"

        $fmodelJsonPath = Join-Path $selfTestRoot "fmodel.json"
        @"
[
  {
    "Properties": {
      "TextureParameterValues": [
        { "ParameterValue": { "ObjectPath": "/Game/B/T_Face.T_Face" } }
      ]
    }
  },
  {
    "Properties": {
      "TextureParameterValues": [
        { "ParameterValue": { "ObjectPath": "PM\\Content\\B\\T_Mask.0" } }
      ]
    }
  }
]
"@ | Set-Content -LiteralPath $fmodelJsonPath -Encoding UTF8

        $fmodelTargets = @(Get-TextureTargetsFromJsonFile $fmodelJsonPath)
        Assert-ArrayEqual $fmodelTargets @("Game/B/T_Face", "PM/Content/B/T_Mask") "FModel array texture values should normalize to sorted unique targets"

        Write-Host "SELFTEST: multi-file unsupported mode"

        try {
            Get-TextureTargetsFromJsonFiles @($dictJsonPath, $fmodelJsonPath) | Out-Null
            throw "Expected Get-TextureTargetsFromJsonFiles to throw"
        } catch {
            if ($_.Exception.Message -notlike "*not supported*") {
                throw "ASSERT FAILED: multi-file unsupported error should contain 'not supported'`nActual: $($_.Exception.Message)"
            }
        }
    } finally {
        Remove-Item -Path $selfTestRoot -Recurse -Force
    }

    $emptyTags = @(Parse-UModelTagList "Unreal engine 4:`n")
    Assert-Equal $emptyTags.Count 0 "section-only tag list should produce no tags"

    Write-Host "SELFTEST: game tag selector helpers"

    $menuItems = @(
        [pscustomobject]@{ Tag = "cal"; Name = "Calabiyau / Strinova" },
        [pscustomobject]@{ Tag = "cal_old"; Name = "Calabiyau / Strinova (old)" },
        [pscustomobject]@{ Tag = "hog"; Name = "Hogwarts Legacy" }
    )
    $filteredMenuItems = @(Filter-GameTagItems $menuItems "stri")
    Assert-Equal $filteredMenuItems.Count 2 "filter should return two Strinova items"
    Assert-Equal $filteredMenuItems[0].Tag "cal" "filter should preserve original order"
    Assert-Equal (@(Filter-GameTagItems $menuItems "q").Count) 0 "q should be treated as ordinary filter text"
    Assert-Equal (New-ManualGameTagItem).Tag "__manual__" "manual item should use sentinel tag"

    Write-Host "SELFTEST: config loading"

    $configRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("umodel-config-selftest-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $configRoot | Out-Null
    try {
        $fakeUModel = Join-Path $configRoot "umodel.exe"
        Set-Content -LiteralPath $fakeUModel -Value "fake" -Encoding UTF8
        $pakRoot = Join-Path $configRoot "Paks"
        New-Item -ItemType Directory -Force -Path $pakRoot | Out-Null
        $jsonPath = Join-Path $configRoot "material.json"
        Set-Content -LiteralPath $jsonPath -Value '{"Textures":{"BaseMap":"/Game/A/T_A.T_A"}}' -Encoding UTF8
        $outDir = Join-Path $configRoot "Out"
        $configPath = Join-Path $configRoot "config.json"

        @{
            UModelExe = $fakeUModel
            PakRoot = $pakRoot
            JsonPath = $jsonPath
            OutDir = $outDir
            AesKey = ""
            GameTag = "cal"
            TextureFormat = "png"
            DryRun = $true
            Overwrite = $false
            TryPathVariants = $false
        } | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8

        $config = Load-ConfigFromJson $configPath
        Assert-Equal $config.GameTag "cal" "config should load game tag"
        Assert-Equal $config.TextureFormatArg "-png" "png texture format should map to -png"
        Assert-Equal $config.Overwrite $false "overwrite flag should load"
        Test-ExportConfig $config
        Assert-Equal (Test-Path -LiteralPath $outDir) $true "config validation should create output directory"
        Assert-Equal (Resolve-TextureFormatArg "tga") "" "tga should use UModel default texture output"
    } finally {
        Remove-Item -LiteralPath $configRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "SELFTEST PASS"
}

function Main {
    if ($SelfTest) {
        Invoke-SelfTest
        return
    }

    Write-Host "UModel texture export TUI is not implemented in this skeleton."
}

Main
