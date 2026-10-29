param([Parameter(Mandatory = $true)][string]$DependencyZip, [string]$ProjectZip)
$ErrorActionPreference = 'Stop'
$archive = (Resolve-Path -LiteralPath $DependencyZip).Path
$repository = Split-Path -Parent $PSScriptRoot
$target = Join-Path $repository ('.artifacts\offline-install-' + [guid]::NewGuid().ToString('N'))
$proxyNames = @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')
$oldProxies = @{}
$oldHome = $env:CLASSTREAM_HOME
foreach ($name in $proxyNames) { $oldProxies[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    if ($ProjectZip) {
        Expand-Archive -LiteralPath (Resolve-Path -LiteralPath $ProjectZip).Path -DestinationPath $target
        $target = Join-Path $target 'Classtream-LAN\windows-lan'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $target -Force
    $env:CLASSTREAM_HOME = $target
    $lock = Join-Path $target 'requirements-lock.txt'
    Copy-Item -LiteralPath (Join-Path $repository 'windows-lan/requirements-lock.txt') -Destination $lock
    foreach ($name in $proxyNames) { [Environment]::SetEnvironmentVariable($name, 'http://127.0.0.1:9', 'Process') }
    $installer = Join-Path $target 'install.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -DependenciesOnly
    if ($LASTEXITCODE -ne 0) { throw 'Fresh offline dependency installation failed.' }
    $python = Join-Path $target '.venv/Scripts/python.exe'
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Fresh environment dependency check failed.' }
    & $python -c "import sys,cv2,numpy,dxcam,comtypes; from importlib.metadata import version; from pathlib import Path; rows=Path(sys.argv[1]).read_text(encoding='utf-8-sig').splitlines(); pins=[line.split('==') for line in rows if '==' in line and not line.startswith('#')]; assert all(version(n)==v for n,v in pins); assert version('pip')=='26.2.2'; print('PASS: all pinned packages and native/GPU imports in a fresh environment')" $lock
    if ($LASTEXITCODE -ne 0) { throw 'Fresh environment imports or pinned versions failed.' }
    $log = [IO.File]::ReadAllText((Join-Path $target 'runtime/install.log'))
    if ($log -notmatch 'OFFLINE MODE' -or $log -match 'Downloading https?://') { throw 'Expected a verified offline installation.' }
    if ((-not $ProjectZip -and (Test-Path -LiteralPath (Join-Path $target 'config.json'))) -or (Test-Path -LiteralPath (Join-Path $target 'runtime/data'))) {
        throw 'DependenciesOnly unexpectedly configured classroom data.'
    }
    $wheel = Get-ChildItem -LiteralPath (Join-Path $target 'offline/wheels') -File | Select-Object -First 1
    $originalWheel = [IO.File]::ReadAllBytes($wheel.FullName)
    [IO.File]::WriteAllText($wheel.FullName, 'damaged file')
    $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -DependenciesOnly
    if ($LASTEXITCODE -eq 0 -or ($output -join "`n") -notmatch 'missing or damaged') { throw 'Damaged offline wheel was not rejected.' }
    [IO.File]::WriteAllBytes($wheel.FullName, $originalWheel)
    Add-Content -LiteralPath $lock -Value '# different application dependency lock'
    $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -DependenciesOnly
    if ($LASTEXITCODE -eq 0 -or ($output -join "`n") -notmatch 'requirements-lock.txt differ') { throw 'Mismatched dependency lock was not rejected.' }
    Write-Host 'PASS: actual installer used local wheels without pip cache; damaged files and mismatched locks rejected.'
    Write-Host ('Test artifacts: ' + $target)
} finally {
    $env:CLASSTREAM_HOME = $oldHome
    foreach ($name in $proxyNames) { [Environment]::SetEnvironmentVariable($name, $oldProxies[$name], 'Process') }
}
