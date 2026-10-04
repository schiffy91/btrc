param(
    [string]$OutputDirectory = "build/windows-toolchain-msvc",
    [string]$WgpuArchive,
    [string]$Vswhere,
    [switch]$FunctionsOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-MsvcVersion([string]$Banner) {
    if ($Banner -notmatch 'Compiler Version ([0-9]+\.[0-9]+(?:\.[0-9]+)*)') {
        throw 'Cannot identify MSVC compiler version'
    }
    $version = [version]$Matches[1]
    if ($version -lt [version]'19.40') { throw "MSVC $version is below required 19.40" }
    return $version.ToString()
}

function Assert-ArchiveDigest([string]$Path) {
    $expected = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'pins.json') -Raw | ConvertFrom-Json).wgpu.sha256
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'wgpu-native v27.0.4.0 Windows ARM64 MSVC archive SHA-256 mismatch'
    }
}

function Invoke-Bounded([string]$File, [string[]]$Arguments, [int]$TimeoutSeconds = 120,
                        [int[]]$AllowedExitCodes = @(0)) {
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $File
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in $Arguments) { $start.ArgumentList.Add($argument) }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw "Could not start $File" }
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $process.Kill($true)
            if (-not $process.WaitForExit(10000)) { throw "$File could not be reaped after timeout" }
            throw "$File timed out after $TimeoutSeconds seconds"
        }
        $output = $stdout.GetAwaiter().GetResult()
        $errors = $stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -notin $AllowedExitCodes) { throw "$File exited $($process.ExitCode): $errors" }
        return [pscustomobject]@{ stdout = $output; stderr = $errors; exit_code = $process.ExitCode }
    } finally { $process.Dispose() }
}

if ($FunctionsOnly) { return }
$output = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $output | Out-Null
$report = [ordered]@{ status = 'failed'; target = 'aarch64-pc-windows-msvc19.40.0'; native_execution = 'not-run' }
try {
    if (-not $IsWindows -or [System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -ne 'Arm64') {
        throw 'Requires native ARM64 PowerShell on Windows ARM64'
    }
    if (-not $WgpuArchive) { throw 'Supply the pinned wgpu Windows ARM64 MSVC archive with -WgpuArchive' }
    Assert-ArchiveDigest $WgpuArchive
    $report.wgpu_sha256 = (Get-FileHash -LiteralPath $WgpuArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not $Vswhere) { $Vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe' }
    $installation = (Invoke-Bounded $Vswhere @('-latest', '-products', '*', '-property', 'installationPath')).stdout.Trim()
    if (-not $installation) { throw 'Visual Studio installation not found' }
    $devcmd = Join-Path $installation 'Common7/Tools/VsDevCmd.bat'
    $environment = Invoke-Bounded 'cmd.exe' @('/d', '/s', '/c', ('""{0}" -no_logo -arch=arm64 -host_arch=arm64 >nul && set"' -f $devcmd))
    foreach ($line in ($environment.stdout -split "`r?`n")) {
        if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') }
    }
    $env:VSLANG = '1033'
    $cl = Invoke-Bounded 'cl.exe' @('/Bv') -AllowedExitCodes @(0, 2)
    $report.msvc_version = Get-MsvcVersion ($cl.stdout + $cl.stderr)
    $report.windows_sdk = $env:WindowsSDKVersion.TrimEnd('\')
    if (-not $report.windows_sdk) { throw 'Windows SDK version is absent from the developer environment' }
    $report.clang_version = (Invoke-Bounded 'clang.exe' @('--version')).stdout.Trim()
    $hello = Join-Path $output 'hello.c'
    $helloExe = Join-Path $output 'hello.exe'
    Set-Content -LiteralPath $hello -Encoding utf8NoBOM -Value '#include <stdio.h>
int main(void) { puts("PASS: Windows ARM64 MSVC CRT"); return 0; }'
    $flags = @('--target=aarch64-pc-windows-msvc19.40.0', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic-errors')
    Invoke-Bounded 'clang.exe' ($flags + @($hello, '-o', $helloExe)) | Out-Null
    $helloRun = Invoke-Bounded $helloExe @()
    if ($helloRun.stdout.Trim() -ne 'PASS: Windows ARM64 MSVC CRT') { throw 'MSVC-ABI hello output mismatch' }
    $report.hello = 'passed'
    $report.native_execution = 'partial'
    $extract = Join-Path $output 'wgpu-native-27.0.4.0'
    Expand-Archive -LiteralPath $WgpuArchive -DestinationPath $extract -Force
    $header = @(Get-ChildItem -LiteralPath $extract -Recurse -Filter 'webgpu.h')
    $dll = @(Get-ChildItem -LiteralPath $extract -Recurse -Filter 'wgpu_native.dll')
    $library = @(Get-ChildItem -LiteralPath $extract -Recurse -Filter 'wgpu_native.dll.lib')
    if ($library.Count -eq 0) { $library = @(Get-ChildItem -LiteralPath $extract -Recurse -Filter 'wgpu_native.lib') }
    if ($header.Count -ne 1 -or $dll.Count -ne 1 -or $library.Count -ne 1) { throw 'Ambiguous/missing wgpu header, DLL or import library' }
    $smoke = Join-Path $output 'wgpu-link-smoke.exe'
    Invoke-Bounded 'clang.exe' ($flags + @('-I', $header[0].DirectoryName, (Join-Path $PSScriptRoot 'wgpu_link_smoke.c'), $library[0].FullName, '-o', $smoke)) | Out-Null
    Copy-Item -LiteralPath $dll[0].FullName -Destination (Join-Path $output 'wgpu_native.dll') -Force
    $result = Invoke-Bounded $smoke @() -TimeoutSeconds 30
    $report.wgpu = $result.stdout | ConvertFrom-Json
    if (-not $report.wgpu.instance_created -or -not $report.wgpu.callback_returned) { throw 'wgpu instance/callback smoke failed' }
    $report.native_execution = 'passed'
    $report.status = 'passed'
} catch {
    $report.error = $_.Exception.Message
    Write-Error $_ -ErrorAction Continue
} finally {
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $output 'summary.json') -Encoding utf8NoBOM
}
if ($report.status -ne 'passed') { exit 1 }
