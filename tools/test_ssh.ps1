$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$script=Join-Path $root 'ssh\control.ps1'
$cfg=Get-Content (Join-Path $root 'ssh\settings.json') -Raw | ConvertFrom-Json
$cfg.LocalPort=18817
$cfg.OpenBrowser=$false
$cfg.LegacySupervisor=''
$config=Join-Path $root 'evidence\ssh-test-settings.json'
$cfg | ConvertTo-Json | Set-Content -LiteralPath $config -Encoding UTF8
$before=@(Get-NetTCPConnection -State Listen -LocalPort 18317 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess)
$checks=[ordered]@{}
function Run-Control([string]$action) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Action $action -ConfigPath $config
    if ($LASTEXITCODE -ne 0) { throw "Control failed: $action" }
}
try {
    Run-Control 'Check'; $checks.configuration=$true
    Run-Control 'Start'
    $first=@(Get-NetTCPConnection -State Listen -LocalPort 18817 | Select-Object -ExpandProperty OwningProcess -Unique)
    $checks.start=$first.Count -eq 1
    Run-Control 'Start'
    $second=@(Get-NetTCPConnection -State Listen -LocalPort 18817 | Select-Object -ExpandProperty OwningProcess -Unique)
    $checks.duplicate_start_did_not_duplicate=($first.Count -eq 1 -and $second.Count -eq 1 -and $first[0] -eq $second[0])
    $page=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:18817/management.html' -TimeoutSec 20
    $checks.tunnel_serves_existing_page=$page.StatusCode -eq 200
    Run-Control 'Stop'
    $checks.stop_released_test_port=!(Get-NetTCPConnection -State Listen -LocalPort 18817 -ErrorAction SilentlyContinue)
    Run-Control 'Stop';$checks.repeat_stop_safe=$true
} finally {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Action Stop -ConfigPath $config
}
$after=@(Get-NetTCPConnection -State Listen -LocalPort 18317 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess)
$checks.original_tunnel_unchanged=(@(Compare-Object $before $after).Count -eq 0)
$checks.login_boundary='SSH authentication verified by test tunnel; interactive terminal layout not automated.'
$checks | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'evidence\ssh-test-results.json') -Encoding UTF8
$checks | ConvertTo-Json
if (@($checks.Values | Where-Object { $_ -is [bool] -and !$_ }).Count) { exit 1 }
