param([switch]$Watch, [string]$DeploymentRoot = $env:CLASSTREAM_HOME)
$ErrorActionPreference = 'Stop'
if (-not $DeploymentRoot) { $DeploymentRoot = $PSScriptRoot }
$runtime = Join-Path $deploymentRoot 'runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
function Read-Addresses {
    $up = @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -ExpandProperty ifIndex)
    return @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.AddressState -eq 'Preferred' -and $_.InterfaceIndex -in $up -and $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1'
    } | Sort-Object InterfaceIndex, IPAddress | Select-Object -ExpandProperty IPAddress)
}
try {
    do {
      try {
        $addresses = @(Read-Addresses)
        if ($Watch) {
            $path = Join-Path $runtime 'network-addresses.json'
            $temp = $path + '.tmp'
            ConvertTo-Json -InputObject @($addresses) -Compress | Set-Content -LiteralPath $temp -Encoding UTF8
            Move-Item -LiteralPath $temp -Destination $path -Force
        } else {
            $path = Join-Path $deploymentRoot 'config.json'
            $config = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
            if (-not $addresses.Count) { throw 'No connected classroom IPv4 adapter. Connect the network, then run start.cmd.' }
            if ($config.teacher_ip -notin $addresses) {
                $selected = $addresses[0]
                if ($addresses.Count -gt 1) {
                    Write-Host 'Previous classroom IP is unavailable. Select the address reachable by students:'
                    for ($i = 0; $i -lt $addresses.Count; $i++) { Write-Host ('[{0}] {1}' -f ($i + 1), $addresses[$i]) }
                    $choice = Read-Host 'Adapter number'
                    $number = 0
                    if (-not [int]::TryParse($choice, [ref]$number) -or $number -lt 1 -or $number -gt $addresses.Count) { throw 'Invalid adapter number.' }
                    $selected = $addresses[$number - 1]
                }
                Write-Host ('Teacher IP changed: {0} -> {1}' -f $config.teacher_ip, $selected)
                $config.teacher_ip = $selected
                $config | ConvertTo-Json | Set-Content -LiteralPath $path -Encoding UTF8
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
