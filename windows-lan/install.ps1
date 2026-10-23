param([switch]$NoStart, [string]$TeacherIP)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-CompatiblePython([string]$Candidate, [string[]]$PrefixArgs = @()) {
    if (-not $Candidate) { return $null }
    try {
        $command = Get-Command $Candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        # Do not invoke the Windows Store alias on a computer without Python.
        if (-not $command -or $command.Source -like '*\Microsoft\WindowsApps\*') { return $null }
        $result = & $command.Source @PrefixArgs -c "import sys,struct,sysconfig; assert sys.version_info[:2]==(3,14) and sys.version_info.releaselevel=='final' and struct.calcsize('P')==8 and not sysconfig.get_config_var('Py_GIL_DISABLED'); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0) { return ([string]($result | Select-Object -Last 1)).Trim() }
    } catch { }
    return $null
}

function Get-Download([string]$Url, [string]$Target) {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Target -TimeoutSec 180
            return
        } catch {
            if ($attempt -eq 3) { throw }
            Write-Warning ('Download interrupted; retrying ({0}/3): {1}' -f $attempt, $Url)
            Start-Sleep -Seconds 2
        }
    }
}

function Get-VerifiedDownload([string]$Url, [string]$Target, [string]$Hash, [string]$Algorithm = 'SHA256') {
    if ((Test-Path -LiteralPath $Target) -and (Get-FileHash -LiteralPath $Target -Algorithm $Algorithm).Hash -eq $Hash) { return }
    $partial = $Target + '.partial'
    Get-Download $Url $partial
    if ((Get-FileHash -LiteralPath $partial -Algorithm $Algorithm).Hash -ne $Hash) { throw ('Download checksum mismatch: ' + $Url) }
    Move-Item -LiteralPath $partial -Destination $Target -Force
}

function Test-OpenCV([string]$Python) {
    # Print diagnostics to stdout: Windows PowerShell otherwise treats native stderr as an exception.
    $probe = @'
import sys, traceback
try:
    import cv2, numpy
    print('OpenCV ' + cv2.__version__ + ' / NumPy ' + numpy.__version__)
except Exception:
    traceback.print_exc(file=sys.stdout)
    sys.exit(1)
'@
    & $Python -c $probe | Out-Host
    return ($LASTEXITCODE -eq 0)
}

function Install-VisualCppRuntime([string]$Runtime) {
    Write-Host 'OpenCV could not load. Installing the official Microsoft Visual C++ x64 runtime...'
    $downloads = Join-Path $Runtime 'downloads'
    New-Item -ItemType Directory -Force -Path $downloads | Out-Null
    $installer = Join-Path $downloads 'vc_redist.x64.exe'
    $signature = if (Test-Path -LiteralPath $installer) { Get-AuthenticodeSignature -LiteralPath $installer }
    if (-not $signature -or $signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        $partial = $installer + '.partial.exe'
        Get-Download 'https://aka.ms/vc14/vc_redist.x64.exe' $partial
        $signature = Get-AuthenticodeSignature -LiteralPath $partial
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
            throw 'Microsoft runtime download has an invalid publisher signature.'
        }
        Move-Item -LiteralPath $partial -Destination $installer -Force
    }
    $arguments = '/install /quiet /norestart /log "' + (Join-Path $Runtime 'vc-runtime-install.log') + '"'
    $processArgs = @{ FilePath = $installer; ArgumentList = $arguments; WindowStyle = 'Hidden'; PassThru = $true; Wait = $true }
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { $processArgs.Verb = 'RunAs' }
    $installed = Start-Process @processArgs
    if ($installed.ExitCode -notin @(0, 3010, 1638)) { throw ('Microsoft runtime installation failed: ' + $installed.ExitCode) }
    if ($installed.ExitCode -eq 3010) { Write-Host 'Microsoft runtime requests a restart; restart Windows if the next validation fails.' }
}

try {
    Write-Host 'Classtream LAN / teacher installation' -ForegroundColor Cyan
    Write-Host 'First installation needs Internet access. Students install nothing in HTTP mode.'
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'This package requires Windows 10/11 x64 (Intel/AMD).'
    }
    $runtime = Join-Path $PSScriptRoot 'runtime'
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    Start-Transcript -Path (Join-Path $runtime 'install.log') -Append | Out-Null

    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $pythonExe = Get-CompatiblePython $venvPython
    if ((Test-Path -LiteralPath $venvPython) -and -not $pythonExe) {
        throw 'Existing .venv uses an unsupported or moved Python. Rename .venv, then retry.'
    }
    if (-not $pythonExe) { $pythonExe = Get-CompatiblePython 'py' @('-3.14') }
    if (-not $pythonExe) { $pythonExe = Get-CompatiblePython 'python' }
    if (-not $pythonExe) {
        $pythonExe = Get-CompatiblePython (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe')
    }
    if (-not $pythonExe) {
        Write-Host 'Installing Python 3.14.9 x64 for the current Windows user...'
        $downloads = Join-Path $runtime 'downloads'
        New-Item -ItemType Directory -Force -Path $downloads | Out-Null
        $installer = Join-Path $downloads 'python-3.14.9-amd64.exe'
        Get-VerifiedDownload 'https://www.python.org/ftp/python/3.14.9/python-3.14.9-amd64.exe' $installer 'a247a0b612244a803f507b39fb7121e3602e4160d59c3b99d98e735289c53394'
        $pythonTarget = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314'
        $arguments = '/quiet InstallAllUsers=0 Include_launcher=0 PrependPath=0 Include_test=0 Include_doc=0 Include_pip=1 TargetDir="' + $pythonTarget + '" /log "' + (Join-Path $runtime 'python-install.log') + '"'
        $installed = Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
        if ($installed.ExitCode -notin @(0, 3010)) { throw ('Python installer failed: ' + $installed.ExitCode) }
        $pythonExe = Get-CompatiblePython (Join-Path $pythonTarget 'python.exe')
        if (-not $pythonExe) { throw 'Python installation is not ready. Restart Windows if requested, then retry.' }
    }
    Write-Host ('Python: ' + $pythonExe)
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $pythonExe -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv.' }
    }
    # Pin the installer tool as well; application versions remain in requirements-lock.txt.
    & $venvPython -m pip install --disable-pip-version-check 'pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70'
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the pinned pip. Check Internet/proxy access.' }
    & $venvPython -m pip install --disable-pip-version-check --index-url https://pypi.org/simple --retries 3 --timeout 30 -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check runtime/install.log and retry.' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed.' }
    if (-not (Test-OpenCV $venvPython)) {
        Install-VisualCppRuntime $runtime
        if (-not (Test-OpenCV $venvPython)) { throw 'OpenCV still cannot load. Check install.log/vc-runtime-install.log; restart Windows if requested. Windows N editions may require the Media Feature Pack.' }
    }
    & $venvPython -c "import mss, pyautogui, pydantic_core, uvicorn, websockets, importlib.util; assert importlib.util.find_spec('dxcam'); print('Native/application dependencies OK')"
    if ($LASTEXITCODE -ne 0) { throw 'Application dependency import failed. See runtime/install.log.' }

    $configPath = Join-Path $PSScriptRoot 'config.json'
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    # Show every active IPv4 adapter so a VPN/default route cannot silently choose the classroom network.
    $up = @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -ExpandProperty ifIndex)
    $adapters = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.AddressState -eq 'Preferred' -and $_.InterfaceIndex -in $up -and $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*'
    } | Sort-Object InterfaceIndex, IPAddress)
    if (-not $adapters.Count) { throw 'No active LAN IPv4 address. Connect the teacher PC to the classroom network.' }
    $selected = $null
    if ($TeacherIP) {
        $selected = $adapters | Where-Object { $_.IPAddress -eq $TeacherIP } | Select-Object -First 1
        if (-not $selected) { throw 'TeacherIP is not assigned to an active local adapter.' }
    }
    elseif ($adapters.Count -eq 1) { $selected = $adapters[0] }
    else {
        Write-Host 'Select the adapter reachable by students:'
        for ($i = 0; $i -lt $adapters.Count; $i++) {
            Write-Host ('[{0}] {1}  {2}' -f ($i + 1), $adapters[$i].IPAddress, $adapters[$i].InterfaceAlias)
        }
        $defaultIndex = 1
        for ($i = 0; $i -lt $adapters.Count; $i++) {
            if ($adapters[$i].IPAddress -eq $config.teacher_ip) { $defaultIndex = $i + 1 }
        }
        $choice = Read-Host ('Adapter number [default {0}]' -f $defaultIndex)
        $number = $defaultIndex
        if ($choice -and (-not [int]::TryParse($choice, [ref]$number))) { throw 'Invalid adapter number.' }
        if ($number -lt 1 -or $number -gt $adapters.Count) { throw 'Invalid adapter number.' }
        $selected = $adapters[$number - 1]
    }
    if ((Test-Path -LiteralPath (Join-Path $runtime 'ready.json')) -and $selected.IPAddress -ne $config.teacher_ip) {
        throw 'Stop the service before changing the classroom adapter.'
    }
    $config.teacher_ip = $selected.IPAddress
    $config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
    if ($config.mode -eq 'https' -and -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'bin\caddy.exe'))) {
        $downloads = Join-Path $runtime 'downloads'
        New-Item -ItemType Directory -Force -Path $downloads | Out-Null
        $caddyZip = Join-Path $downloads 'caddy_2.11.7_windows_amd64.zip'
        Get-VerifiedDownload 'https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_windows_amd64.zip' $caddyZip 'c308154504e53755958ffc62d8a2657ab17eefd6dd25c45dbb2c3d93d29519971f77ca652f7d0f2bcb7f980b9ba3822478865e29969d0272d7613550a43152b1' 'SHA512'
        $unpacked = Join-Path $downloads 'caddy'
        Expand-Archive -LiteralPath $caddyZip -DestinationPath $unpacked -Force
        $bin = Join-Path $PSScriptRoot 'bin'
        New-Item -ItemType Directory -Force -Path $bin | Out-Null
        Copy-Item -LiteralPath (Join-Path $unpacked 'caddy.exe') -Destination (Join-Path $bin 'caddy.exe')
    }
    & $venvPython lan.py prepare
    if ($LASTEXITCODE -ne 0) { throw 'Configuration validation failed.' }
    & $venvPython -c "import os; from pathlib import Path; os.environ['CLASSTREAM_DATA']=str(Path('runtime/data').resolve()); from compat import create_application; create_application('http://127.0.0.1:8080'); print('Classtream adapter OK')"
    if ($LASTEXITCODE -ne 0) { throw 'Classtream compatibility validation failed. See runtime/install.log.' }
    $passwordPending = Join-Path $runtime 'password-required'
    if (-not (Test-Path -LiteralPath (Join-Path $runtime 'data\classtream.db')) -or (Test-Path -LiteralPath $passwordPending)) {
        'pending' | Set-Content -LiteralPath $passwordPending -Encoding ASCII
        Write-Host 'Create the teacher password for this new deployment (username: admin).'
        & $venvPython lan.py password
        if ($LASTEXITCODE -ne 0) { throw 'Teacher password setup failed. Run password.cmd before starting classes.' }
        Remove-Item -LiteralPath $passwordPending
    }
    Write-Host 'Windows will request administrator approval for the classroom firewall rule.'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'allow-firewall.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Firewall setup failed or was canceled. Retry install.cmd or ask the school administrator.' }
    Write-Host 'Installation complete. Keep the service window and teacher page open.' -ForegroundColor Green
    Stop-Transcript | Out-Null
    if (-not $NoStart) {
        if (Test-Path -LiteralPath (Join-Path $runtime 'ready.json')) {
            & $venvPython lan.py check
            if ($LASTEXITCODE -ne 0) { throw 'Old ready marker found. Run stop.cmd and start.cmd.' }
            & $venvPython lan.py open-teacher
        } else {
            & $venvPython lan.py start --open-browser
            if ($LASTEXITCODE -ne 0) { throw 'Service startup failed. Check the message above.' }
        }
    }
    exit 0
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}
