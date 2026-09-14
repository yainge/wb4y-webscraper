# Registers (or replaces) a Windows Task Scheduler job that runs run_daily.ps1 every day.
# Default 14:30 local: EPEX day-ahead results are published ~13:00 CET and GridHub caches up to 1 h.
# A second run at 07:30 picks up the gas day-ahead price (gas day starts 06:00) and heals any gaps.
#
#   powershell -ExecutionPolicy Bypass -File register_task.ps1            # register
#   powershell -ExecutionPolicy Bypass -File register_task.ps1 -Remove    # unregister
Param(
    [string]$TaskName = "WB4U Market Prices Daily",
    [string[]]$Times = @("07:30", "14:30"),
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "run_daily.ps1"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'"
    exit 0
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`"" `
    -WorkingDirectory $ScriptDir
$triggers = foreach ($t in $Times) { New-ScheduledTaskTrigger -Daily -At $t }
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Force | Out-Null
Write-Host "Registered '$TaskName' at $($Times -join ', ') -> $Runner"
Write-Host "Check with: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
