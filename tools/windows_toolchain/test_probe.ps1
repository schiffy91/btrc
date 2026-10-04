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
    try { Get-MsvcVersion $banner | Out-Null } catch { $refused = $true }
    if (-not $refused) { throw "Invalid version accepted: $banner" }
}
$temp = [IO.Path]::GetTempFileName()
try {
    Set-Content -LiteralPath $temp -Value 'not the pinned archive'
    $refused = $false
    try { Assert-ArchiveDigest $temp } catch { $refused = $true }
    if (-not $refused) { throw 'Incorrect wgpu archive accepted' }
} finally { Remove-Item -LiteralPath $temp }
$child = 'import time; time.sleep(60)'
$program = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); print('partial',flush=True)"
$clock = [Diagnostics.Stopwatch]::StartNew()
$refused = $false
try { Invoke-Bounded $python @('-c', $program, $child) -TimeoutSeconds 1 | Out-Null }
catch { if ($_.Exception.Message -match 'timed out.*partial') { $refused = $true } else { throw } }
if (-not $refused -or $clock.Elapsed.TotalSeconds -gt 8) { throw 'Inherited output pipe escaped command deadline' }
Write-Output 'PASS: PowerShell parser and six portable version/hash cases plus inherited-pipe deadline (no Windows execution)'
