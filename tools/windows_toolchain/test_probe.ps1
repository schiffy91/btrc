$ErrorActionPreference = 'Stop'
$errorsFound = $null
$tokens = $null
[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'msvc_probe.ps1'), [ref]$tokens, [ref]$errorsFound) | Out-Null
if ($errorsFound.Count) { throw ($errorsFound | Out-String) }
$python = if ($IsWindows) { 'python' } else { 'python3' }
. (Join-Path $PSScriptRoot 'msvc_probe.ps1') -FunctionsOnly -PythonExecutable $python
foreach ($version in @('19.40.33811', '19.44.35219', '20.0.1')) {
    if ((Get-MsvcVersion "Microsoft (R) C/C++ Optimizing Compiler Version $version for ARM64") -ne $version) {
        throw "Version $version was parsed incorrectly"
    }
}
foreach ($banner in @('Compiler Version 19.39.0', 'unknown version')) {
    $refused = $false
    try { Assert-MsvcVersion (Get-MsvcVersion $banner) } catch { $refused = $true }
    if (-not $refused) { throw "Invalid version accepted: $banner" }
}
$temp = [IO.Path]::GetTempFileName()
try {
    Set-Content -LiteralPath $temp -Value 'not the pinned archive'
    $refused = $false
    try { Assert-ArchiveDigest $temp } catch { $refused = $true }
    if (-not $refused) { throw 'Incorrect wgpu archive accepted' }
} finally { Remove-Item -LiteralPath $temp }
# External containment tests need a real disposable Windows runner. The pipe
# regression below specifically exercises the POSIX process-group path.
if ($IsWindows) {
    $program = "import time; print('CHILD-STDOUT-7d38',flush=True); time.sleep(60)"
    $child = ''
} else {
    $child = 'import time; time.sleep(60)'
}
if (-not $IsWindows) { $program = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); print('CHILD-STDOUT-7d38',flush=True)" }
$clock = [Diagnostics.Stopwatch]::StartNew()
$refused = $false
try { Invoke-Bounded $python @('-c', $program, $child) -TimeoutSeconds 3 | Out-Null }
catch { if ($_.Exception.Message -match 'timed out.*CHILD-STDOUT-7d38') { $refused = $true } else { throw } }
if (-not $refused -or $clock.Elapsed.TotalSeconds -gt 15) { throw 'Inherited output pipe escaped command deadline' }
Write-Output 'PASS: PowerShell parser and six portable version/hash cases plus command deadline (portable checks, no native compiler or MSVC proof)'

if ((Get-MsvcVersion 'Compiler Version 19.39.0') -ne '19.39.0') { throw 'Rejected MSVC version was lost' }
$previousSdk = $env:WindowsSDKVersion
try {
    $env:WindowsSDKVersion = $null
    try { Get-WindowsSdkVersion; throw 'Missing SDK accepted' }
    catch { if ($_.Exception.Message -ne 'Windows SDK version is absent from the developer environment') { throw } }
} finally { $env:WindowsSDKVersion = $previousSdk }
try { Invoke-Bounded $python @('-c', "import sys; print('WGPU-INSTANCE-OBSERVED'); print('EXACT-STDERR',file=sys.stderr); sys.exit(2)"); throw 'Failure accepted' }
catch {
    if ($_.Exception.Message -notmatch '(?s)WGPU-INSTANCE-OBSERVED.*EXACT-STDERR') { throw }
    if ($_.Exception.Data['result'].stdout.Trim() -ne 'WGPU-INSTANCE-OBSERVED') { throw 'Structured partial stdout lost' }
}
try { Invoke-Bounded 'btrc-nonexistent-command-7d38' @(); throw 'Missing executable accepted' }
catch { if ($_.Exception.Message -notmatch 'btrc-nonexistent-command-7d38') { throw } }
Write-Output 'PASS: partial failure output, absent SDK, old MSVC version and launch diagnostic regressions'

$originalInvoke = (Get-Item Function:Invoke-Bounded).ScriptBlock
$previousProbe = $env:BTRC_VSENV_TEST
try {
    function Invoke-Bounded([string]$File, [string[]]$Arguments) {
        if ($File -ne 'cmd.exe' -or $Arguments.Count -ne 3 -or $Arguments[2] -notmatch '^btrc-vsenv-[a-f0-9]+\.cmd$') { throw 'Unsafe cmd quoting' }
        $script:capturedScript = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) $Arguments[2]
        $body = Get-Content -LiteralPath $script:capturedScript -Raw
        if (-not $body.Contains('call "C:\Program Files\Visual Studio\VsDevCmd.bat" -no_logo -arch=arm64 -host_arch=arm64 >nul')) { throw 'Developer command not quoted inside script' }
        if (-not $body.Contains('if errorlevel 1 exit /b %errorlevel%')) { throw 'Developer failure not propagated' }
        return [pscustomobject]@{ stdout = "BTRC_VSENV_TEST=imported`n" }
    }
    Enter-Arm64Environment 'C:\Program Files\Visual Studio\VsDevCmd.bat'
    if ($env:BTRC_VSENV_TEST -ne 'imported' -or (Test-Path -LiteralPath $script:capturedScript)) { throw 'Environment import or script cleanup failed' }
} finally {
    Set-Item Function:Invoke-Bounded $originalInvoke
    $env:BTRC_VSENV_TEST = $previousProbe
}
Write-Output 'PASS: developer script quoting and environment import stand-in'
