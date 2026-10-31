param(
    [Parameter(Mandatory = $true)][string]$DeploymentRoot,
    [string]$CodeRoot
)
$ErrorActionPreference = 'Stop'
if (-not $CodeRoot) { $CodeRoot = Split-Path -Parent $PSCommandPath }
$DeploymentRoot = [IO.Path]::GetFullPath($DeploymentRoot).TrimEnd('\')
$CodeRoot = [IO.Path]::GetFullPath($CodeRoot).TrimEnd('\')
$runtime = Join-Path $DeploymentRoot 'runtime'
$config = Get-Content -LiteralPath (Join-Path $DeploymentRoot 'config.json') -Raw | ConvertFrom-Json
if ($config.mode -notin @('http', 'https')) { throw 'Invalid classroom mode.' }
$Ports = @([int]$config.backend_port, [int]$config.($config.mode + '_port'))
$publicMinimum = if ($config.mode -eq 'http') { 1 } else { 1024 }
if ($Ports[0] -lt 1024 -or $Ports[0] -gt 65535 -or $Ports[1] -lt $publicMinimum -or $Ports[1] -gt 65535) { throw 'Invalid classroom ports.' }
$python = Join-Path $DeploymentRoot '.venv\Scripts\python.exe'
$scripts = @((Join-Path $CodeRoot 'lan.py'), (Join-Path $DeploymentRoot 'lan.py'))

function Get-Arguments($Process) {
    return @([regex]::Matches([string]$Process.CommandLine, '"[^"]*"|\S+') | ForEach-Object { $_.Value.Trim('"') })
}

function Is-ClassroomProcess($Process) {
    $argv = @(Get-Arguments $Process)
    if ($argv.Count -lt 2) { return $false }
    if ($Process.Name -match '^python(w)?\.exe$') {
        $index = 1
        while ($index -lt $argv.Count -and $argv[$index] -in @('-u', '-B')) { $index++ }
        if ($index -ge $argv.Count) { return $false }
        $script = $argv[$index]
        if ($script -notin $scripts -and $script -ne 'lan.py') { return $false }
        $hasHome = $false
        for ($i = $index + 1; $i -lt $argv.Count - 1; $i++) {
            if ($argv[$i] -eq '--home') {
                $hasHome = $true
                if ([IO.Path]::GetFullPath($argv[$i + 1]).TrimEnd('\') -ne $DeploymentRoot) { return $false }
            }
        }
        # Older launchers omitted --home; only accept this deployment's venv.
        $legacy = $false
        try { $legacy = [IO.Path]::GetFullPath($argv[0]) -eq $python } catch { return $false }
        return (($script -in $scripts -or ($legacy -and $script -eq 'lan.py')) -and
                ($hasHome -or $legacy) -and
                @($argv | Where-Object { $_ -in @('start', 'serve', 'launch') }).Count -gt 0)
    }
    if ($Process.Name -eq 'powershell.exe') {
        $fileIndex = [Array]::IndexOf($argv, '-File')
        if ($fileIndex -lt 0 -or $fileIndex + 1 -ge $argv.Count) { return $false }
        $file = $argv[$fileIndex + 1]
        if ($file -ne (Join-Path $CodeRoot 'refresh-network.ps1') -and
            $file -ne (Join-Path $DeploymentRoot 'refresh-network.ps1')) { return $false }
        $homeIndex = [Array]::IndexOf($argv, '-DeploymentRoot')
        if ($homeIndex -ge 0 -and $homeIndex + 1 -lt $argv.Count) {
            return [IO.Path]::GetFullPath($argv[$homeIndex + 1]).TrimEnd('\') -eq $DeploymentRoot
        }
        # Legacy watcher is stopped by its launcher's Job Object.
        return $file -eq (Join-Path $DeploymentRoot 'refresh-network.ps1')
    }
    if ($Process.Name -eq 'caddy.exe') {
        $configIndex = [Array]::IndexOf($argv, '--config')
        return ($argv[0] -eq (Join-Path $DeploymentRoot 'bin\caddy.exe') -and
                $configIndex -ge 0 -and $configIndex + 1 -lt $argv.Count -and
                $argv[$configIndex + 1] -eq (Join-Path $runtime 'Caddyfile'))
    }
    return $false
}

function Get-Listeners {
    # Query all listeners once: an empty result must not hide permission/query failures.
    return @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in $Ports })
}

$processes = @(Get-CimInstance Win32_Process)
$ancestors = @{}
$ancestorId = $PID
while ($ancestorId -and -not $ancestors.ContainsKey([int]$ancestorId)) {
    $ancestors[[int]$ancestorId] = $true
    $ancestor = $processes | Where-Object { $_.ProcessId -eq $ancestorId } | Select-Object -First 1
    if (-not $ancestor) { break }
    $ancestorId = $ancestor.ParentProcessId
}
$owned = @($processes | Where-Object { -not $ancestors.ContainsKey([int]$_.ProcessId) -and (Is-ClassroomProcess $_) })
$ownedIds = @($owned | ForEach-Object { [int]$_.ProcessId })
foreach ($listener in @(Get-Listeners)) {
    if ([int]$listener.OwningProcess -notin $ownedIds) {
        $other = $processes | Where-Object { $_.ProcessId -eq $listener.OwningProcess } | Select-Object -First 1
        throw ('Port {0} is used by another application: PID {1}, {2}. Close that application and retry.' -f $listener.LocalPort, $listener.OwningProcess, $other.Name)
    }
}
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if ($owned.Count) {
    Write-Host ('Stopping previous classroom processes: ' + ($ownedIds -join ', '))
    'stop' | Set-Content -LiteralPath (Join-Path $runtime 'stop.request') -Encoding ASCII
    $deadline = (Get-Date).AddSeconds(8)
    do {
        $remaining = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in $ownedIds })
        if (-not $remaining.Count) { break }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    foreach ($old in $owned) {
        $current = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $old.ProcessId)
        # Revalidate identity immediately before termination; never trust a stale PID file.
        if ($current -and $current.CreationDate -eq $old.CreationDate -and (Is-ClassroomProcess $current)) {
            Write-Host ('Cleaning residual classroom process: ' + $current.ProcessId)
            Stop-Process -Id $current.ProcessId -Force -ErrorAction Stop
        }
    }
}
$deadline = (Get-Date).AddSeconds(8)
do {
    $listeners = @(Get-Listeners)
    if (-not $listeners.Count) { break }
    Start-Sleep -Milliseconds 250
} while ((Get-Date) -lt $deadline)
if ($listeners.Count) { throw 'Classroom ports are still occupied; startup canceled.' }
foreach ($name in @('ready.json', 'launcher.pid', 'stop.request')) {
    $path = Join-Path $runtime $name
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
}
Write-Host ('Classroom ports are free: ' + ($Ports -join ', '))
