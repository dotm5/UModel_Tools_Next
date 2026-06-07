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
    Assert-Equal $tags[0].Tag "ue4.[0-27]" "first tag should preserve the generic UE4 pattern"
    Assert-Equal $tags[2].Tag "cal" "Calabiyau tag should be cal"
    Assert-Equal $tags[2].Name "Calabiyau / Strinova" "Calabiyau readable name should be preserved"
    Assert-Equal $tags[3].Tag "cal_old" "old Calabiyau tag should be cal_old"

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
