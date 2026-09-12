param(
    [switch]$Login,
    [switch]$Headed
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $projectRoot "backend"
$pythonPath = "D:\anaconda3\envs\price-radar\python.exe"
$logDir = Join-Path $backendDir "storage\logs"
$logFile = Join-Path $logDir ("kdocs-sync-{0}.log" -f (Get-Date -Format "yyyy-MM"))
$mutex = [System.Threading.Mutex]::new($false, "Local\PriceRadarKDocsDailySync")
$hasMutex = $false

try {
    $hasMutex = $mutex.WaitOne(0)
    if (-not $hasMutex) {
        Write-Host "KDocs sync is already running; this run was skipped."
        exit 0
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "Project Python was not found: $pythonPath"
    }
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $arguments = @("-s", "-m", "scripts.sync_kdocs")
    if ($Login) { $arguments += "--login" }
    if ($Headed) { $arguments += "--headed" }

    "`n[{0}] Starting KDocs sync" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Tee-Object -FilePath $logFile -Append
    Push-Location $backendDir
    try {
        & $pythonPath @arguments 2>&1 | Tee-Object -FilePath $logFile -Append
        $syncExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($syncExitCode -ne 0) {
        throw "KDocs sync failed. See log: $logFile"
    }
    Write-Host "KDocs sync completed. Log: $logFile"
}
finally {
    if ($hasMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
