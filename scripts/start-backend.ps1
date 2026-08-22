$env:PYTHONNOUSERSITE = "1"
Set-Location "$PSScriptRoot\..\backend"
& "D:\anaconda3\envs\price-radar\python.exe" -s -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

