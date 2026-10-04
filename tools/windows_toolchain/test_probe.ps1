$ErrorActionPreference = 'Stop'
$errorsFound = $null
$tokens = $null
[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'msvc_probe.ps1'), [ref]$tokens, [ref]$errorsFound) | Out-Null
if ($errorsFound.Count) { throw ($errorsFound | Out-String) }
. (Join-Path $PSScriptRoot 'msvc_probe.ps1') -FunctionsOnly
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
Write-Output 'PASS: PowerShell parser and six portable version/hash cases (no Windows execution)'
