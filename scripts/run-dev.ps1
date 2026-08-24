$projectRoot = Resolve-Path "$PSScriptRoot\.."
$backendScript = Join-Path $projectRoot "scripts\start-backend.ps1"
$frontendScript = Join-Path $projectRoot "scripts\start-frontend.ps1"

$backendArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$backendScript`""
$frontendArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$frontendScript`""

$backend = Start-Process -FilePath "powershell.exe" -ArgumentList $backendArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
$frontend = Start-Process -FilePath "powershell.exe" -ArgumentList $frontendArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 2
$backendReady = Test-NetConnection -ComputerName "127.0.0.1" -Port 8000 -InformationLevel Quiet
$frontendReady = Test-NetConnection -ComputerName "127.0.0.1" -Port 5173 -InformationLevel Quiet

if ($backendReady -and $frontendReady) {
    Write-Host "PriceRadar started" -ForegroundColor Green
    Write-Host "Frontend: http://127.0.0.1:5173"
    Write-Host "Backend:  http://127.0.0.1:8000/docs"
    Start-Process "http://127.0.0.1:5173"
} else {
    Write-Host "Startup failed: frontend or backend is not listening." -ForegroundColor Red
    Write-Host "Check MySQL80 and confirm D:\anaconda3\envs\price-radar plus D:\nodejs\npm.cmd exist."
}
Write-Host "Process IDs: backend=$($backend.Id), frontend=$($frontend.Id)"
Write-Host "Stop with: Stop-Process -Id $($backend.Id),$($frontend.Id)"
