# Daily update: market prices (electricity 15-min + gas) and KNMI weather (temperature + irradiance) -> parquet + charts.
# Run manually:   powershell -ExecutionPolicy Bypass -File "run_daily.ps1"
# Scheduled:      see register_task.ps1
Param(
    [int]$DaysBack = 3,
    [int]$ChartDays = 14,
    [string]$WeatherStations = "260",   # KNMI station codes, comma-separated; first one is charted (260 = De Bilt)
    [switch]$SkipWeather
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$Python    = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$LogDir = Join-Path $ScriptDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("daily_{0:yyyy-MM-dd}.log" -f (Get-Date))

Set-Location $ScriptDir
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') start ===" | Tee-Object -FilePath $Log -Append
& $Python "daily_market_prices.py" --days-back $DaysBack --chart-days $ChartDays 2>&1 | Tee-Object -FilePath $Log -Append
$code = $LASTEXITCODE

if (-not $SkipWeather) {
    $stations = $WeatherStations -split '[,; ]+' | Where-Object { $_ }
    & $Python "daily_weather.py" --station @stations --days-back 5 --chart-days $ChartDays 2>&1 | Tee-Object -FilePath $Log -Append
    if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }
}
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') exit $code ===" | Tee-Object -FilePath $Log -Append
exit $code
