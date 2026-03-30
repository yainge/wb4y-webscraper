Param(
    [string]$Python = "python",
    [string]$Zone = "10YNL----------L",
    [string]$Contract = "A01",
    [int]$Days = 2,
    [string]$ParquetDir = "data/entsoe/parquet"
)

$ErrorActionPreference = 'Stop'

if (-not $env:ENTSOE_TOKEN -and -not $env:ENTSOE_SECURITY_TOKEN) {
  Write-Error "ENTSOE_TOKEN is not set. Set it in the task environment or system env vars."
}

# Resolve repo root from this script's directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

$UpdateScript = Join-Path $RepoRoot "scripts/entsoe_daily_update.py"
if (-not (Test-Path $UpdateScript)) {
  Write-Error "Cannot find entsoe_daily_update.py at $UpdateScript"
}

# Ensure parquet dir exists
$ParquetPath = Join-Path $RepoRoot $ParquetDir
New-Item -ItemType Directory -Force -Path $ParquetPath | Out-Null

Write-Host "Running ENTSO-E daily update for zone=$Zone contract=$Contract days=$Days"

& $Python $UpdateScript --zone $Zone --days $Days --contract $Contract --parquet-dir $ParquetPath

if ($LASTEXITCODE -ne 0) {
  Write-Error "Update failed with exit code $LASTEXITCODE"
}
else {
  Write-Host "Update completed successfully. Dataset at $ParquetPath"
}

