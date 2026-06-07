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
