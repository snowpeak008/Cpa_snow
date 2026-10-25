$ErrorActionPreference='Stop'
try {
    $port=18732
    $python=Get-Command python.exe -ErrorAction SilentlyContinue
    if (!$python) { $python=Get-Item 'C:\Program Files\Python312\python.exe' -ErrorAction Stop }
    $pythonPath=if ($python.Source) {$python.Source} else {$python.FullName}
    $entry=Join-Path $PSScriptRoot 'preview_server.py'
    $listener=Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if (!$listener) {
        Start-Process -FilePath $pythonPath -ArgumentList ('-X utf8 "'+$entry+'"') -WindowStyle Hidden | Out-Null
        for ($i=0;$i -lt 20;$i++) {
            if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {break}
            Start-Sleep -Milliseconds 250
        }
    } else {
        $owner=Get-CimInstance Win32_Process -Filter ('ProcessId='+@($listener)[0].OwningProcess)
        if (!$owner.CommandLine.Contains('preview_server.py')) {throw 'Preview port is occupied by another program.'}
    }
    $response=Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/management.html" -TimeoutSec 8
    if ($response.StatusCode -ne 200) {throw 'Preview server is unavailable.'}
    Start-Process "http://127.0.0.1:$port/management.html"
    Write-Host 'Local preview only. Enter any demo key to view the empty dashboard. No production connection.'
} catch {Write-Host $_.Exception.Message;exit 1}
