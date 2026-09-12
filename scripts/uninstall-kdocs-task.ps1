$ErrorActionPreference = "Stop"
$taskName = "PriceRadar-KDocs-Daily-Sync"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Local task does not exist: $taskName"
    exit 0
}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Removed local task: $taskName. Downloaded workbooks and imported data were preserved."
