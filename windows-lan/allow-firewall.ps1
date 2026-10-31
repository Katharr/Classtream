param([string]$DeploymentRoot = $env:CLASSTREAM_HOME)
$ErrorActionPreference = 'Stop'
if (-not $DeploymentRoot) { $DeploymentRoot = $PSScriptRoot }
$DeploymentRoot = (Resolve-Path -LiteralPath $DeploymentRoot).Path
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $elevationArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -DeploymentRoot "' + $DeploymentRoot + '"'
    $elevated = Start-Process -FilePath powershell.exe -ArgumentList $elevationArgs -Verb RunAs -WindowStyle Hidden -PassThru -Wait
    exit $elevated.ExitCode
}
$config = Get-Content -LiteralPath (Join-Path $DeploymentRoot 'config.json') -Raw | ConvertFrom-Json
$mode = [string]$config.mode
if ($mode -notin @('http', 'https')) { throw 'Invalid mode in config.json.' }
$port = if ($mode -eq 'http') { [int]$config.http_port } else { [int]$config.https_port }
$minimum = if ($mode -eq 'http') { 1 } else { 1024 }
if ($port -lt $minimum -or $port -gt 65535) { throw 'Invalid classroom port.' }
$ruleName = 'Classtream-LAN-' + $mode.ToUpperInvariant() + '-' + $port
$localAddress = if ($mode -eq 'http') { 'Any' } else { [string]$config.teacher_ip }
if (-not (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -LocalAddress $localAddress -RemoteAddress LocalSubnet -Profile Any | Out-Null
} else {
    Set-NetFirewallRule -Name $ruleName -Enabled True -Direction Inbound -Action Allow -Profile Any | Out-Null
    Get-NetFirewallRule -Name $ruleName | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $port | Out-Null
    Get-NetFirewallRule -Name $ruleName | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress $localAddress -RemoteAddress LocalSubnet | Out-Null
}
Write-Host ('Allowed local-subnet TCP ' + $port + ' at ' + $config.teacher_ip)
if ($mode -eq 'http' -and $config.mdns_enabled -ne $false) {
    $mdnsRule = 'Classtream-LAN-mDNS'
    $python = Join-Path $DeploymentRoot '.venv\Scripts\python.exe'
    if (Get-NetFirewallRule -Name $mdnsRule -ErrorAction SilentlyContinue) {
        Remove-NetFirewallRule -Name $mdnsRule | Out-Null
    }
    New-NetFirewallRule -Name $mdnsRule -DisplayName $mdnsRule -Direction Inbound -Action Allow -Protocol UDP -LocalPort 5353 -Program $python -RemoteAddress LocalSubnet -Profile Any | Out-Null
    Write-Host 'Allowed local-subnet mDNS (UDP 5353) for the classroom Python.'
}
New-Item -ItemType Directory -Force -Path (Join-Path $DeploymentRoot 'runtime') | Out-Null
('Allowed TCP {0} on {1}; remote=LocalSubnet' -f $port, $config.teacher_ip) | Set-Content -LiteralPath (Join-Path $DeploymentRoot 'runtime\firewall-ready.txt') -Encoding UTF8
