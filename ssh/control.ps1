param(
    [ValidateSet('Login','Start','Stop','Status','Check')][string]$Action = 'Status',
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'settings.json')
)
$ErrorActionPreference = 'Stop'

function Quote-Argument([string]$Value) {
    if ($Value -match '["\r\n]') { throw 'Invalid quotation or newline in configuration.' }
    return '"' + $Value + '"'
}
function Save-State($Value) {
    $Value | ConvertTo-Json | Set-Content -LiteralPath ($statePath + '.new') -Encoding UTF8
    Move-Item -LiteralPath ($statePath + '.new') -Destination $statePath -Force
}
function Get-TunnelProcess([int]$ProcessNumber) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessNumber" -ErrorAction SilentlyContinue
    if ($proc -and $proc.Name -eq 'ssh.exe' -and $proc.CommandLine -and
        $proc.CommandLine.Contains($forward) -and $proc.CommandLine.Contains($target)) { return $proc }
    return $null
}
function Get-OwnState {
    if (!(Test-Path -LiteralPath $statePath)) { return $null }
    $s = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $p = Get-TunnelProcess ([int]$s.ProcessId)
    if (!$p) { return $null }
    $actual = (Get-Process -Id $p.ProcessId).StartTime.ToUniversalTime().Ticks.ToString()
    if ($actual -ne [string]$s.StartTicks) { return $null }
    return $s
}
function Stop-Legacy {
    if (!$cfg.LegacySupervisor) { return 0 }
    $legacy = [IO.Path]::GetFullPath((Join-Path $configDir $cfg.LegacySupervisor))
    $all = @(Get-CimInstance Win32_Process)
    $parents = @($all | Where-Object { $_.Name -in @('powershell.exe','pwsh.exe') -and $_.CommandLine -and
        $_.CommandLine.IndexOf('-File "' + $legacy + '"', [StringComparison]::OrdinalIgnoreCase) -ge 0 })
    $count = 0
    foreach ($parent in $parents) {
        $children = @($all | Where-Object { $_.ParentProcessId -eq $parent.ProcessId -and $_.Name -eq 'ssh.exe' -and
            $_.CommandLine -and $_.CommandLine.Contains($forward) -and $_.CommandLine.Contains($target) })
        if ($children.Count -eq 0) { continue }
        # Stop only the explicitly configured tunnel supervisor, then its exact SSH child.
        Stop-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            if (Get-TunnelProcess $child.ProcessId) { Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue; $count++ }
        }
    }
    return $count
}

$mutex = $null
$locked = $false
try {
    $ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
    $configDir = Split-Path -Parent $ConfigPath
    $cfg = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    foreach ($n in @('Port','LocalPort','RemotePort')) {
        if ([int]$cfg.$n -lt 1 -or [int]$cfg.$n -gt 65535) { throw "Invalid port: $n" }
    }
    if ($cfg.Host -notmatch '^[A-Za-z0-9.-]+$' -or $cfg.User -notmatch '^[A-Za-z0-9_-]+$' -or
        $cfg.RemoteHost -notmatch '^[A-Za-z0-9.:-]+$') { throw 'Invalid SSH host or user.' }
    $identity = [Environment]::ExpandEnvironmentVariables($cfg.IdentityFile)
    if (![IO.Path]::IsPathRooted($identity)) { $identity = Join-Path $configDir $identity }
    $ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
    $target = $cfg.User + '@' + $cfg.Host
    $forward = '127.0.0.1:' + $cfg.LocalPort + ':' + $cfg.RemoteHost + ':' + $cfg.RemotePort
    $stateDir = Join-Path $configDir '.state'
    $statePath = Join-Path $stateDir ('tunnel-' + $cfg.LocalPort + '.json')
    $baseArgs = @('-i',$identity,'-p',[string]$cfg.Port,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o','ConnectTimeout=15','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3')
    if ($Action -eq 'Check') {
        if (!(Test-Path -LiteralPath $identity -PathType Leaf)) { throw 'SSH private key is missing.' }
        Write-Host 'Configuration and SSH client are ready. No connection was opened.'
        exit 0
    }
    if ($Action -eq 'Login') {
        if (!(Test-Path -LiteralPath $identity -PathType Leaf)) { throw 'SSH private key is missing.' }
        Write-Host 'Opening the server terminal. Type exit to disconnect.'
        & $ssh @baseArgs '-tt' $target
        exit $LASTEXITCODE
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    $lockName = 'Local\SnowTunnel-' + ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($ConfigPath)))).Replace('-','')
    $sha.Dispose()
    $mutex = New-Object Threading.Mutex($false, $lockName)
    $locked = $mutex.WaitOne(10000)
    if (!$locked) { throw 'Another tunnel operation is running.' }
    $own = Get-OwnState
    if ($Action -eq 'Status') {
        [pscustomobject]@{ ManagedTunnelRunning=[bool]$own; LocalPort=$cfg.LocalPort;
            Listening=[bool](Get-NetTCPConnection -State Listen -LocalPort $cfg.LocalPort -ErrorAction SilentlyContinue) } | ConvertTo-Json
        exit 0
    }
    if ($Action -eq 'Stop') {
        if ($own) { Stop-Process -Id ([int]$own.ProcessId) -ErrorAction SilentlyContinue }
        $legacyCount = Stop-Legacy
        if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
        Write-Host ('Tunnel closed. Managed={0}; previous launcher={1}. Other SSH sessions were not stopped.' -f [bool]$own,$legacyCount)
        exit 0
    }
    if (!(Test-Path -LiteralPath $identity -PathType Leaf)) { throw 'SSH private key is missing.' }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $cfg.LocalPort -ErrorAction SilentlyContinue)
    if ($listeners.Count) {
        $same = @($listeners | Where-Object { Get-TunnelProcess $_.OwningProcess })
        if (!$same.Count) { throw 'Local port is occupied by another program. No process was stopped.' }
        Write-Host 'The same SSH tunnel is already running. No duplicate was started.'
    } else {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
        $sshArgs = $baseArgs + @('-N','-T','-L',$forward,'-o','ExitOnForwardFailure=yes',$target)
        $argLine = ($sshArgs | ForEach-Object { Quote-Argument $_ }) -join ' '
        $proc = Start-Process -FilePath $ssh -ArgumentList $argLine -WindowStyle Hidden -PassThru `
            -RedirectStandardError (Join-Path $stateDir 'tunnel-error.log') -RedirectStandardOutput (Join-Path $stateDir 'tunnel-output.log')
        $ticks = $proc.StartTime.ToUniversalTime().Ticks.ToString()
        Save-State @{ ProcessId=$proc.Id; StartTicks=$ticks; Forward=$forward; Target=$target }
        $ready = $false
        for ($i=0; $i -lt 40; $i++) {
            $proc.Refresh()
            if ($proc.HasExited) { break }
            $listening = @(Get-NetTCPConnection -State Listen -LocalPort $cfg.LocalPort -ErrorAction SilentlyContinue |
                Where-Object OwningProcess -eq $proc.Id)
            if ($listening.Count) { $ready=$true; break }
            Start-Sleep -Milliseconds 500
        }
        if (!$ready) {
            if (Get-OwnState) { Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue }
            throw "Tunnel failed. See $stateDir\tunnel-error.log. No automatic retry was made."
        }
        Write-Host 'SSH tunnel is ready and runs in the background.'
    }
    $url = 'http://127.0.0.1:' + $cfg.LocalPort + '/management.html'
    Write-Host $url
    if ($cfg.OpenBrowser) { Start-Process $url }
} catch {
    Write-Host ('FAILED: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
