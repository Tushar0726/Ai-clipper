# One-command installer for SupoClip on Windows (PowerShell)
# Usage: powershell -ExecutionPolicy Bypass -File .\setup.ps1 [-NoStart]
param([switch]$NoStart)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Dir = "supoclip"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required: https://git-scm.com/downloads" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker Desktop is required: https://docs.docker.com/get-docker/" }
docker info *> $null; if ($LASTEXITCODE -ne 0) { throw "Docker is not running. Start Docker Desktop and retry." }

if (Test-Path "$Dir\.git") { git -C $Dir pull --ff-only }
else { git clone --depth 1 https://github.com/FujiwaraChoki/supoclip.git $Dir }

$EnvFile = "$Dir\.env"
if (-not (Test-Path $EnvFile)) { Copy-Item "$Dir\.env.example" $EnvFile }

function Get-EnvVal($k) { $l = Get-Content $EnvFile | Where-Object { $_ -match "^$k=" } | Select-Object -Last 1; if ($l) { $l.Substring($k.Length + 1) } else { "" } }
function Set-EnvVal($k, $v) {
  $lines = @(Get-Content $EnvFile | Where-Object { $_ -notmatch "^$k=" }) + "$k=$v"
  [IO.File]::WriteAllLines((Resolve-Path $EnvFile), $lines)   # UTF-8 without BOM, LF-safe for Docker
}
function Ask($k, $prompt) {
  $suffix = if (Get-EnvVal $k) { " [already set, Enter to keep]" } else { "" }
  $s = Read-Host "$prompt$suffix" -AsSecureString
  $v = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
  if ($v) { Set-EnvVal $k $v }
}
function Rand { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ }) }

Write-Host "`n== API keys (input is hidden; press Enter to skip one) =="
Ask ASSEMBLY_AI_API_KEY "AssemblyAI API key (transcription)"
Ask GOOGLE_API_KEY      "Google Gemini API key"
Ask OPENAI_API_KEY      "OpenAI API key"
Ask ANTHROPIC_API_KEY   "Anthropic API key"

if (Get-EnvVal ASSEMBLY_AI_API_KEY) { Set-EnvVal TRANSCRIPTION_PROVIDER assemblyai }
else { Write-Host "No AssemblyAI key: using local Whisper."; Set-EnvVal TRANSCRIPTION_PROVIDER whisper }

Write-Host "`nWhich AI model should pick the clips?"
Write-Host "  1) Google Gemini 3 Flash  (fast, cheap - recommended)"
Write-Host "  2) OpenAI GPT-5.2"
Write-Host "  3) Anthropic Claude Sonnet"
switch (Read-Host "Choose 1-3 [1]") {
  "2" { Set-EnvVal LLM "openai:gpt-5.2" }
  "3" { Set-EnvVal LLM "anthropic:claude-sonnet-5-5" }
  default { Set-EnvVal LLM "google-gla:gemini-3-flash-preview" }
}

if ((Get-EnvVal BETTER_AUTH_SECRET) -eq "supoclip_dev_secret_change_in_production") { Set-EnvVal BETTER_AUTH_SECRET (Rand) }
if ((Get-EnvVal BACKEND_AUTH_SECRET) -eq "change_me_backend_auth_secret") { Set-EnvVal BACKEND_AUTH_SECRET (Rand) }
Set-EnvVal SELF_HOST true

Write-Host "`nConfig written to $EnvFile"
if ($NoStart) { exit 0 }

Write-Host "Building and starting SupoClip (first run takes several minutes)..."
Push-Location $Dir; docker compose up -d --build; Pop-Location

$Port = Get-EnvVal FRONTEND_PORT; if (-not $Port) { $Port = "3107" }
Write-Host "`nSupoClip is starting up."
Write-Host "  App:      http://localhost:$Port   (create an account, then paste a YouTube link)"
Write-Host "  API docs: http://localhost:8000/docs"
Write-Host "  Logs:     cd $Dir; docker compose logs -f"
Write-Host "  Stop:     cd $Dir; docker compose down"
