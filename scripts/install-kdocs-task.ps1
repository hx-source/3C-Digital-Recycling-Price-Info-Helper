param(
    [string]$DailyAt = "12:00"
)

$ErrorActionPreference = "Stop"
$taskName = "PriceRadar-KDocs-Daily-Sync"
$syncScript = Join-Path $PSScriptRoot "kdocs-daily-sync.ps1"
$powerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$action = New-ScheduledTaskAction -Execute $powerShell -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$syncScript`""
$trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Download the KDocs quote workbook daily and import changed content into PriceRadar review." -Force | Out-Null
Write-Host "Installed local task: $taskName (daily at $DailyAt; missed runs start when available)."
