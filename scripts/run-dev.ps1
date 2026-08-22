$projectRoot = Resolve-Path "$PSScriptRoot\.."
$backendScript = Join-Path $projectRoot "scripts\start-backend.ps1"
$frontendScript = Join-Path $projectRoot "scripts\start-frontend.ps1"

$backend = Start-Process powershell.exe -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $backendScript -WindowStyle Hidden -PassThru
$frontend = Start-Process powershell.exe -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $frontendScript -WindowStyle Hidden -PassThru

Write-Host "PriceRadar started"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Backend:  http://127.0.0.1:8000/docs"
Write-Host "Process IDs: backend=$($backend.Id), frontend=$($frontend.Id)"
Write-Host "Stop with: Stop-Process -Id $($backend.Id),$($frontend.Id)"

