param([Parameter(Mandatory = $true)][string]$ProjectZip)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$target = Join-Path $repository ('.artifacts\online-install-' + [guid]::NewGuid().ToString('N'))
$oldHome = $env:CLASSTREAM_HOME
try {
    Expand-Archive -LiteralPath (Resolve-Path -LiteralPath $ProjectZip).Path -DestinationPath $target
    $code = Join-Path $target 'Classtream-LAN\windows-lan'
    $env:CLASSTREAM_HOME = $code
    if (Test-Path -LiteralPath (Join-Path $code 'offline')) { throw 'Main project unexpectedly bundles offline dependencies.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $code 'install.ps1') -DependenciesOnly
    if ($LASTEXITCODE -ne 0) { throw 'Fresh online dependency installation failed.' }
    $python = Join-Path $code '.venv\Scripts\python.exe'
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Fresh online dependency check failed.' }
    & $python -c "import sys,cv2,numpy,dxcam,comtypes; from importlib.metadata import version; from pathlib import Path; pins=[line.split('==') for line in Path(sys.argv[1]).read_text(encoding='utf-8-sig').splitlines() if '==' in line and not line.startswith('#')]; assert all(version(n)==v for n,v in pins); assert version('pip')=='26.2.2'; print('PASS: online pinned dependencies and native/GPU imports')" (Join-Path $code 'requirements-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Online dependency imports or pinned versions failed.' }
    $log = [IO.File]::ReadAllText((Join-Path $code 'runtime\install.log'))
    if ($log -notmatch 'ONLINE MODE' -or $log -match 'OFFLINE MODE') { throw 'Expected default online installation.' }
    if (Test-Path -LiteralPath (Join-Path $code 'runtime\data')) { throw 'Dependency test unexpectedly created classroom data.' }
    Write-Host ('PASS: actual source-only package installed online in a fresh environment. Artifacts: ' + $target)
} finally {
    $env:CLASSTREAM_HOME = $oldHome
}
