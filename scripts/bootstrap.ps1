# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
#
# One-command identity setup for Windows (PowerShell 5.1+). Same steps as scripts/bootstrap.sh.
# Usually started through setup.bat in the repository root. Needs only Docker Desktop.
#
#   setup.bat              development: .env.local secrets, Zitadel, bootstrap
#   setup.bat -DryRun      print what the bootstrap would change
#   setup.bat -Reset       development: delete the local Zitadel volumes first
#   $env:ASSETFLOW_ENV = "production"; setup.bat
#                          full profile: OpenBao (unsealed, $env:BAO_TOKEN set), openbao-apply,
#                          Zitadel, bootstrap into OpenBao
[CmdletBinding()]
param(
    [switch]$Reset,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Say([string]$Message) { Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Fail([string]$Message) { Write-Host ""; Write-Host "error: $Message" -ForegroundColor Yellow; exit 1 }

# Runs docker with the given arguments; stops the script when it fails.
function Invoke-Docker([string[]]$Arguments, [string]$OnError) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { Fail $OnError }
}

function Show-StartFailure([string[]]$Compose) {
    # Windows PowerShell turns redirected native stderr into errors; only read the text here.
    $ErrorActionPreference = "Continue"
    $logs = (& docker @($Compose + @("logs", "--tail", "200", "zitadel")) 2>&1 | Out-String)
    if ($logs -match "masterkey|cipher: message authentication failed|unable to decrypt") {
        Write-Host "Zitadel cannot decrypt its data: the masterkey differs from the one the volume was created with."
        Write-Host "Restore the original value, or (development only) start over with: setup.bat -Reset"
    } elseif ($logs -match "password authentication failed") {
        Write-Host "Zitadel cannot log in to its database: the database passwords differ from the volume's."
        Write-Host "Restore the original values, or (development only) start over with: setup.bat -Reset"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail "Docker Desktop is required (https://docs.docker.com/get-docker/)." }
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 is required (docker compose)." }

$ApplyArgs = @("apply")
if ($DryRun) { $ApplyArgs += "--dry-run" }

# ---------------------------------------------------------------- production (full profile)
if ($env:ASSETFLOW_ENV -eq "production") {
    if ($Reset) { Fail "-Reset is for local development only." }
    if (-not $env:BAO_TOKEN) { Fail "set `$env:BAO_TOKEN (operator token) first." }
    if (-not (Test-Path "deploy/.secrets/openbao-tls/ca.pem")) { Fail "no OpenBao TLS files; see docs/operations/openbao.md section 2." }
    $DC = @("compose", "-p", "assetflow", "-f", "deploy/compose.full.yml")
    Say "1/4 OpenBao"
    Invoke-Docker ($DC + @("up", "-d", "openbao")) "OpenBao did not start."
    & docker @($DC + @("exec", "-T", "openbao", "bao", "status")) *> $null
    if ($LASTEXITCODE -ne 0) { Fail "OpenBao is not initialized or is sealed. Unseal it (docs/operations/openbao.md section 3), then run this again." }
    Say "2/4 openbao-apply (secrets generated once, fresh secret ids)"
    & bash scripts/openbao-apply.sh --generate-missing --issue-secret-ids
    if ($LASTEXITCODE -ne 0) { Fail "openbao-apply failed (needs Git Bash and Python 3.10+)." }
    Say "3/4 Zitadel"
    & docker @($DC + @("up", "-d", "--wait", "zitadel"))
    if ($LASTEXITCODE -ne 0) { Show-StartFailure $DC; Fail "Zitadel did not become healthy; see: docker $($DC -join ' ') logs zitadel" }
    Say "4/4 Zitadel bootstrap (results go to OpenBao, never to files)"
    Invoke-Docker ($DC + @("--profile", "bootstrap", "run", "--rm", "--build", "zitadel-bootstrap") + $ApplyArgs) "Zitadel bootstrap failed; see the output above."
    Say "Done. Admin initial password: bao kv get -field=initial_password secret/assetflow/zitadel/admin"
    exit 0
}

# ---------------------------------------------------------------- development
$EnvFile = ".env.local"
$DC = @("compose", "-f", "deploy/compose.identity.yml", "--env-file", $EnvFile)
if (-not (Test-Path $EnvFile)) { New-Item -ItemType File -Path $EnvFile | Out-Null }

if ($Reset) {
    Say "Reset: deleting the local Zitadel containers and volumes (secrets in $EnvFile are kept)"
    Invoke-Docker ($DC + @("--profile", "bootstrap", "down", "-v", "--remove-orphans")) "Reset failed."
}

Say "1/4 Bootstrap image"
Invoke-Docker ($DC + @("--profile", "bootstrap", "build", "zitadel-bootstrap")) "Could not build the bootstrap image."

Say "2/4 Local secrets ($EnvFile, git-ignored)"
Invoke-Docker ($DC + @("--profile", "bootstrap", "run", "--rm", "--no-deps", "zitadel-bootstrap", "init-env", "--marker-dir", "/zitadel/bootstrap")) "Local secrets check failed; see the message above."

Say "3/4 Zitadel (first start takes about a minute)"
& docker @($DC + @("up", "-d", "--wait", "zitadel"))
if ($LASTEXITCODE -ne 0) { Show-StartFailure $DC; Fail "Zitadel did not become healthy; see: docker $($DC -join ' ') logs zitadel" }

Say "4/4 Zitadel bootstrap"
Invoke-Docker ($DC + @("--profile", "bootstrap", "run", "--rm", "zitadel-bootstrap") + $ApplyArgs) "Zitadel bootstrap failed; see the output above."

$Domain = if ($env:ZITADEL_DOMAIN) { $env:ZITADEL_DOMAIN } else { "localhost" }
$Port = if ($env:ZITADEL_EXTERNALPORT) { $env:ZITADEL_EXTERNALPORT } else { "19081" }
Write-Host ""
Write-Host "  ============================================================="
Write-Host "   Identity is ready (local development)."
Write-Host "   Console:   http://${Domain}:${Port}/ui/console"
Write-Host "   Admin:     login name printed above; password = ZITADEL_ADMIN_PASSWORD in $EnvFile"
Write-Host "   Results:   ZITADEL_* in $EnvFile (project id, client ids and secrets, organization ids)"
Write-Host "   Stop:      docker $($DC -join ' ') down"
Write-Host "  ============================================================="
