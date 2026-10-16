# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
#
# AssetFlow database and keys restoration script for Windows (§B11.4, §B13.5, M1.6-T9).
# Delegates to WSL2 bash scripts/restore.sh or executes native restore steps.
#
# Usage:
#   .\scripts\restore.ps1 -Keys <path-to-keys.tar.gz> [-Target latest|<timestamp>] [-Profile minimal|full]

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Keys,
    [string]$Target = "latest",
    [ValidateSet("minimal", "full")]
    [string]$Profile = "minimal"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path $Keys)) {
    Write-Host "error: keys archive not found at: $Keys" -ForegroundColor Red
    exit 1
}

# Delegate to WSL if available
$hasWsl = Get-Command wsl -ErrorAction SilentlyContinue
if ($hasWsl) {
    Write-Host "WSL2 detected: delegating restore to scripts/restore.sh" -ForegroundColor Cyan
    & wsl -e bash scripts/restore.sh --keys "$Keys" --target "$Target" --profile "$Profile"
    exit $LASTEXITCODE
}

Write-Host "error: native restore on Windows requires WSL2 or Git Bash environment." -ForegroundColor Red
exit 1
