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

function Invoke-SelfTest {
    Write-Host "SELFTEST: skeleton"
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
