# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Local development stack: one command, Zitadel first, then the product (deploy/compose.dev.yml).
# Windows PowerShell port of scripts/dev.sh; see that file for the full description.
#
#   scripts/dev.ps1 [up]             start (or re-start) the stack
#   scripts/dev.ps1 down [-Reset]    stop AssetFlow's containers; -Reset also deletes its volumes
#   scripts/dev.ps1 admin-password   print the first Zitadel admin's password (you asked for it)
[CmdletBinding()]
param(
    [ValidateSet("up", "down", "admin-password")]
    [string]$Command = "up",
    [switch]$Reset
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Say([string]$Message) { Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Fail([string]$Message) { Write-Host ""; Write-Host "dev: error: $Message" -ForegroundColor Yellow; exit 1 }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail "Docker is required." }
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 is required." }

$Python = $env:PYTHON
if (-not $Python) {
    foreach ($candidate in @("python3", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" *> $null
            if ($LASTEXITCODE -eq 0) { $Python = $candidate; break }
        }
    }
}
if (-not $Python) { Fail "Python 3.10+ not found (set `$env:PYTHON)." }

$ComposeFile = "deploy/compose.dev.yml"
$ProjectName = "assetflow"

if (-not $env:WEB_PORT) { $env:WEB_PORT = "18080" }
if (-not $env:API_HOST_PORT) { $env:API_HOST_PORT = "18090" }
if ($env:WEB -eq "vite") {
    if (-not $env:APP_URL) { $env:APP_URL = "http://localhost:5173" }
    if (-not $env:API_URL) { $env:API_URL = "http://localhost:$($env:API_HOST_PORT)" }
} else {
    if (-not $env:APP_URL) { $env:APP_URL = "http://localhost:$($env:WEB_PORT)" }
    if (-not $env:API_URL) { $env:API_URL = "http://localhost:$($env:WEB_PORT)" }
}

$Profiles = @()
if ($env:MAIL -eq "1") { $Profiles += @("--profile", "mail") }
if ($env:OBSERVABILITY -eq "1") { $Profiles += @("--profile", "observability") }
$Services = @("api", "worker")
if ($env:WEB -ne "vite") { $Services += "web" }
if ($env:MAIL -eq "1") { $Services += "mailpit" }
if ($env:OBSERVABILITY -eq "1") { $Services += "otel" }

function Invoke-Dc {
    param([string[]]$Args)
    & docker compose -p $ProjectName -f $ComposeFile @Profiles @Args
    if ($LASTEXITCODE -ne 0) { Fail "docker compose $($Args -join ' ') failed." }
}

function Invoke-Setup([string]$Step) {
    & docker compose -p $ProjectName -f $ComposeFile run --rm --no-deps -T --name af-setup setup $Step
    if ($LASTEXITCODE -ne 0) { Fail "af-setup $Step failed." }
}

function Invoke-Up {
    Say "1/7 preflight: ports free, no foreign container owns an af- name"
    & $Python scripts/check-ports.py dev
    if ($LASTEXITCODE -ne 0) { exit 1 }

    Say "2/7 build the two images (assetflow-backend, assetflow-web)"
    $Build = @("api")
    if ($env:WEB -ne "vite") { $Build += "web" }
    Invoke-Dc (@("build") + $Build)

    Say "3/7 af-openbao up, unseal with the local dev key, openbao-apply"
    Invoke-Dc @("up", "-d", "--wait", "openbao")
    Invoke-Setup "openbao"

    Say "4/7 af-postgres up (databases assetflow and zitadel)"
    Invoke-Dc @("up", "-d", "--wait", "postgres")

    Say "5/7 af-zitadel up, zitadel-apply (client secrets go into OpenBao)"
    Invoke-Dc @("up", "-d", "--wait", "zitadel")
    Invoke-Setup "zitadel"

    Say "6/7 migrate, then af-api, af-worker, af-web"
    Invoke-Setup "migrate"
    Invoke-Dc (@("up", "-d", "--wait") + $Services)

    Say "7/7 sign-in check and smoke test"
    Invoke-Setup "signin"
    if (-not $env:ZITADEL_DOMAIN) { $env:ZITADEL_DOMAIN = "zitadel.localhost" }
    & $Python scripts/smoke-full.py --dev
    if ($LASTEXITCODE -ne 0) { exit 1 }

    Write-Host ""
    Write-Host "AssetFlow development stack is up:"
    if ($env:WEB -eq "vite") {
        Write-Host "  web (Vite)   $($env:APP_URL)   run: cd frontend; npm run dev"
        Write-Host "  api          http://localhost:$($env:API_HOST_PORT)"
    } else {
        Write-Host "  web          $($env:APP_URL)"
        Write-Host "  api          http://localhost:$($env:API_HOST_PORT) (direct)"
    }
    $zPort = if ($env:ZITADEL_EXTERNALPORT) { $env:ZITADEL_EXTERNALPORT } else { "19081" }
    Write-Host "  sign-in      http://$($env:ZITADEL_DOMAIN):$zPort (user: admin; password: scripts/dev.ps1 admin-password)"
    $bPort = if ($env:OPENBAO_HOST_PORT) { $env:OPENBAO_HOST_PORT } else { "19200" }
    Write-Host "  openbao      http://127.0.0.1:$bPort"
    $pPort = if ($env:POSTGRES_HOST_PORT) { $env:POSTGRES_HOST_PORT } else { "15432" }
    Write-Host "  postgres     127.0.0.1:$pPort"
    if ($env:MAIL -eq "1") { Write-Host "  mailpit      http://localhost:$(if ($env:MAILPIT_WEB_PORT) {$env:MAILPIT_WEB_PORT} else {'18025'})" }
    if ($env:OBSERVABILITY -eq "1") { Write-Host "  grafana      http://localhost:$(if ($env:GRAFANA_HOST_PORT) {$env:GRAFANA_HOST_PORT} else {'13000'})" }
}

function Invoke-Down {
    $Profiles = @("--profile", "mail", "--profile", "observability", "--profile", "setup")
    if ($Reset) {
        $answer = Read-Host "This deletes every AssetFlow development volume (database, OpenBao data, transit key). Type 'yes' to continue"
        if ($answer -ne "yes") { Fail "aborted." }
        & docker compose -p $ProjectName -f $ComposeFile @Profiles down --volumes
    } else {
        & docker compose -p $ProjectName -f $ComposeFile @Profiles down
    }
}

switch ($Command) {
    "up" { Invoke-Up }
    "down" { Invoke-Down }
    "admin-password" { Invoke-Setup "admin-password" }
}
