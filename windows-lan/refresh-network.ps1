param([switch]$Watch, [string]$DeploymentRoot = $env:CLASSTREAM_HOME)
$ErrorActionPreference = 'Stop'
if (-not $DeploymentRoot) { $DeploymentRoot = $PSScriptRoot }
$runtime = Join-Path $deploymentRoot 'runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
function Read-Addresses {
    $up = @(Get-NetAdapter | Where-Object {
        $_.Status -eq 'Up' -and (-not $httpMode -or $_.HardwareInterface)
    } | Select-Object -ExpandProperty ifIndex)
    return @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.AddressState -eq 'Preferred' -and $_.InterfaceIndex -in $up -and
            (-not $httpMode -or -not $_.SkipAsSource) -and
            $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1'
    } | Sort-Object InterfaceIndex, IPAddress)
}
try {
    $configPath = Join-Path $DeploymentRoot 'config.json'
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $httpMode = $config.mode -ne 'https'
    $selectedIp = $config.teacher_ip
    $selectedInterface = $null
    $lastSnapshot = $null
    do {
      try {
        $addresses = @(Read-Addresses)
        $selected = $addresses | Where-Object IPAddress -eq $selectedIp | Select-Object -First 1
        if ($Watch) {
            if ($null -eq $selected) {
                $selected = $addresses | Where-Object InterfaceIndex -eq $selectedInterface | Select-Object -First 1
            }
            if ($null -eq $selected -and @($addresses.InterfaceIndex | Select-Object -Unique).Count -eq 1) {
                $selected = $addresses[0]
            }
            $active = @()
            if ($null -ne $selected) {
                $selectedIp = $selected.IPAddress
                $selectedInterface = $selected.InterfaceIndex
                $active = @($selectedIp)
            }
            $path = Join-Path $runtime 'network-addresses.json'
            $snapshot = ConvertTo-Json -InputObject $active -Compress
            if ($snapshot -ne $lastSnapshot -or -not (Test-Path -LiteralPath $path)) {
                $temp = $path + '.tmp'
                [IO.File]::WriteAllText($temp, $snapshot)
                if ([IO.File]::Exists($path)) {
                    [IO.File]::Replace($temp, $path, [NullString]::Value)
                } else {
                    [IO.File]::Move($temp, $path)
                }
                $lastSnapshot = $snapshot
            }
        } else {
            if (-not $addresses.Count) { throw 'No connected classroom IPv4 adapter. Connect the network, then run start.cmd.' }
            if ($null -eq $selected) {
                $selected = $addresses[0]
                if ($addresses.Count -gt 1 -and (-not $httpMode -or @($addresses.InterfaceIndex | Select-Object -Unique).Count -gt 1)) {
                    Write-Host 'Previous classroom IP is unavailable. Select the address reachable by students:'
                    for ($i = 0; $i -lt $addresses.Count; $i++) {
                        Write-Host ('[{0}] {1} ({2})' -f ($i + 1), $addresses[$i].IPAddress, $addresses[$i].InterfaceAlias)
                    }
                    $choice = Read-Host 'Adapter number'
                    $number = 0
                    if (-not [int]::TryParse($choice, [ref]$number) -or $number -lt 1 -or $number -gt $addresses.Count) { throw 'Invalid adapter number.' }
                    $selected = $addresses[$number - 1]
                }
                Write-Host ('Teacher IP changed: {0} -> {1} ({2})' -f $config.teacher_ip, $selected.IPAddress, $selected.InterfaceAlias)
                $config.teacher_ip = $selected.IPAddress
                $config | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $configPath -Encoding UTF8
            }
        }
      } catch {
        if (-not $Watch) { throw }
        Write-Warning ('Network monitor will retry: ' + $_.Exception.Message)
      }
      if ($Watch) { Start-Sleep -Seconds 3 }
    } while ($Watch)
    exit 0
} catch {
    Write-Host ('Network detection failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
