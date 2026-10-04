# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
#
# One-command bootstrap for Windows (PowerShell 5.1+ / Core).
# Checks prerequisites and delegates to WSL2 bash or runs native Docker Compose commands.
#
# Usage:
#   setup.bat [-Profile minimal|full] [-DryRun] [-Reset] [-NoDemo]
#   .\scripts\bootstrap.ps1 [-Profile minimal|full] [-DryRun] [-Reset] [-NoDemo]
[CmdletBinding()]
param(
    [ValidateSet("minimal", "full")]
    [string]$Profile = "minimal",
    [switch]$DryRun,
    [switch]$Reset,
    [switch]$NoDemo
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Say([string]$Message) { Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Fail([string]$Message) { Write-Host ""; Write-Host "error: $Message" -ForegroundColor Yellow; exit 1 }

# Check Docker prerequisites
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker Desktop is required (https://docs.docker.com/get-docker/)."
}
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "Docker Compose v2 is required (docker compose)."
}

# If WSL is available, delegate to scripts/bootstrap.sh under WSL2
$hasWsl = Get-Command wsl -ErrorAction SilentlyContinue
if ($hasWsl) {
    Say "WSL2 detected: delegating bootstrap execution to scripts/bootstrap.sh"
    $wslArgs = @("-e", "bash", "scripts/bootstrap.sh", "--profile", $Profile)
    if ($DryRun) { $wslArgs += "--dry-run" }
    if ($Reset) { $wslArgs += "--reset" }
    if ($NoDemo) { $wslArgs += "--no-demo" }
    & wsl @wslArgs
    exit $LASTEXITCODE
}

# Native PowerShell fallback
Say "Running native PowerShell bootstrap for profile '$Profile'"
$ComposeFile = "deploy/compose.$Profile.yml"
$DC = @("compose", "-p", "assetflow", "-f", $ComposeFile)

if ($Reset) {
    Say "Reset: stopping and removing containers and volumes"
    & docker @($DC + @("down", "-v", "--remove-orphans"))
}

if ($DryRun) {
    Say "Dry run: would run docker $($DC -join ' ') up -d --wait"
    exit 0
}

# Generate local secrets if needed
$SecretsDir = ".secrets"
$Folders = @(
    "database/app", "database/migrator", "database/worker", "database/readonly",
    "auth", "crypto"
)
foreach ($f in $Folders) {
    $dirPath = Join-Path $SecretsDir $f
    if (-not (Test-Path $dirPath)) {
        New-Item -ItemType Directory -Force -Path $dirPath | Out-Null
    }
}

function Gen-SecretFile([string]$RelPath) {
    $fullPath = Join-Path $SecretsDir $RelPath
    if (-not (Test-Path $fullPath) -or ((Get-Item $fullPath).Length -eq 0)) {
        $bytes = New-Object byte[] 32
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
        $hex = -join ($bytes | ForEach-Object { "{0:x2}" -f $_ })
        [System.IO.File]::WriteAllText($fullPath, $hex)
    }
}

Gen-SecretFile "database/app/password"
Gen-SecretFile "database/migrator/password"
Gen-SecretFile "database/worker/password"
Gen-SecretFile "database/readonly/password"
Gen-SecretFile "auth/cookie_key"
Gen-SecretFile "crypto/field_key"

Say "Starting stack ($Profile profile)..."
& docker @($DC + @("up", "-d", "--wait"))
if ($LASTEXITCODE -ne 0) {
    Fail "Failed to start AssetFlow stack."
}

Say "Applying database migrations..."
& docker @($DC + @("--profile", "tools", "run", "--rm", "migrate"))
if ($LASTEXITCODE -ne 0) {
    & docker @($DC + @("exec", "-T", "api", "uv", "run", "--no-sync", "alembic", "upgrade", "head"))
}

if (-not $NoDemo) {
    Say "Creating demo organization and admin..."
    & docker @($DC + @("exec", "-T", "api", "python", "-m", "app.cli.org_create", "--slug", "example-alpha", "--admin-email", "admin@example.test"))
}

$WebPort = if ($env:WEB_PORT) { $env:WEB_PORT } else { "18080" }
Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host " AssetFlow ($Profile profile) is ready." -ForegroundColor Green
Write-Host " Web Application:  http://localhost:$WebPort"
Write-Host " Demo Sign-In:     admin@example.test / demo-admin"
Write-Host "=============================================================" -ForegroundColor Green
