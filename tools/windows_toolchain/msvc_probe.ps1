param(
    [string]$OutputDirectory = "build/windows-toolchain-msvc",
    [string]$WgpuArchive,
    [string]$Vswhere,
    [string]$PythonExecutable = "python",
    [switch]$FunctionsOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-MsvcVersion([string]$Banner) {
    if ($Banner -notmatch 'Compiler Version ([0-9]+\.[0-9]+(?:\.[0-9]+)*)') {
        throw 'Cannot identify MSVC compiler version'
    }
    $version = [version]$Matches[1]
    return $version.ToString()
}

function Assert-MsvcVersion([string]$Version) {
    if ([version]$Version -lt [version]'19.40') { throw "MSVC $Version is below required 19.40" }
}

function Get-WindowsSdkVersion {
    if (-not $env:WindowsSDKVersion) { throw 'Windows SDK version is absent from the developer environment' }
    return $env:WindowsSDKVersion.TrimEnd('\')
}

function Enter-Arm64Environment([string]$DevCmd) {
    if ($DevCmd -match '[%\^"\r\n]') { throw 'VsDevCmd path contains unsupported cmd metacharacters' }
    # A simple relative .cmd filename avoids passing nested cmd.exe quoting
    # through Python's list2cmdline. Keep the script beside the module's cwd.
    $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    $name = 'btrc-vsenv-' + [Guid]::NewGuid().ToString('N') + '.cmd'
    $script = Join-Path $root $name
    try {
        Set-Content -LiteralPath $script -Encoding utf8NoBOM -Value @"
@echo off
setlocal DisableDelayedExpansion
call "$DevCmd" -no_logo -arch=arm64 -host_arch=arm64 1>&2
if errorlevel 1 exit /b %errorlevel%
set
"@
        $environment = Invoke-Bounded 'cmd.exe' @('/d', '/c', $name)
        foreach ($line in ($environment.stdout -split "`r?`n")) {
            if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') }
        }
    } finally { Remove-Item -LiteralPath $script -ErrorAction SilentlyContinue }
}

function Assert-ArchiveDigest([string]$Path) {
    $expected = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'pins.json') -Raw | ConvertFrom-Json).wgpu.sha256
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'wgpu-native v27.0.4.0 Windows ARM64 MSVC archive SHA-256 mismatch'
    }
}

function Invoke-Bounded([string]$File, [string[]]$Arguments, [int]$TimeoutSeconds = 120,
                        [int[]]$AllowedExitCodes = @(0)) {
    $resultPath = [IO.Path]::GetTempFileName()
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $PythonExecutable
    $start.WorkingDirectory = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
    $start.UseShellExecute = $false
    # Python captures output; the shared WindowsJob owns the entire target tree.
    foreach ($argument in @('-m', 'tools.windows_toolchain.process_runner', '--output', $resultPath,
                             '--timeout', $TimeoutSeconds.ToString(), '--', $File) + $Arguments) {
        $start.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw "Could not start process owner for $File" }
        if (-not $process.WaitForExit(($TimeoutSeconds + 30) * 1000)) {
            $process.Kill($true)
            if (-not $process.WaitForExit(10000)) { throw 'Process owner could not be reaped' }
            throw "Process owner timed out for $File"
        }
        $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
        if ($process.ExitCode -ne 0) { throw $result.error }
        if ($result.error -or $result.timed_out -or $result.returncode -notin $AllowedExitCodes) {
            $reason = if ($result.error) { $result.error } elseif ($result.timed_out) { 'timed out' } else { "exited $($result.returncode)" }
            $failure = [InvalidOperationException]::new("$File $reason; stdout: $($result.stdout); stderr: $($result.stderr)")
            $failure.Data['result'] = $result
            throw $failure
        }
        return [pscustomobject]@{ stdout = $result.stdout; stderr = $result.stderr; exit_code = $result.returncode }
    } finally {
        $process.Dispose()
        Remove-Item -LiteralPath $resultPath -ErrorAction SilentlyContinue
    }
}

if ($FunctionsOnly) { return }
$output = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $output | Out-Null
$report = [ordered]@{ status = 'failed'; target = 'aarch64-pc-windows-msvc19.40.0'; native_execution = 'not-run'; containment = 'windows-job' }
try {
    if (-not $IsWindows -or [System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -ne 'Arm64') {
        throw 'Requires native ARM64 PowerShell on Windows ARM64'
    }
    if (-not $WgpuArchive) { throw 'Supply the pinned wgpu Windows ARM64 MSVC archive with -WgpuArchive' }
    Assert-ArchiveDigest $WgpuArchive
    $report.wgpu_sha256 = (Get-FileHash -LiteralPath $WgpuArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not $Vswhere) { $Vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe' }
    $installations = @((Invoke-Bounded $Vswhere @('-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.ARM64', 'Microsoft.VisualStudio.Component.VC.Llvm.Clang',
        '-format', 'json', '-utf8')).stdout | ConvertFrom-Json)
    if ($installations.Count -ne 1) { throw 'Visual Studio with ARM64 and Clang components not found' }
    $report.visual_studio_version = $installations[0].installationVersion
    $report.visual_studio_path = $installations[0].installationPath
    $devcmd = Join-Path $report.visual_studio_path 'Common7/Tools/VsDevCmd.bat'
    Enter-Arm64Environment $devcmd
    $env:VSLANG = '1033'
    $cl = Invoke-Bounded 'cl.exe' @('/Bv') -AllowedExitCodes @(0, 2)
    $report.msvc_version = Get-MsvcVersion ($cl.stdout + $cl.stderr)
    Assert-MsvcVersion $report.msvc_version
    $report.windows_sdk = Get-WindowsSdkVersion
    $report.clang_version = (Invoke-Bounded 'clang.exe' @('--version')).stdout.Trim()
    $hello = Join-Path $output 'hello.c'
    $helloExe = Join-Path $output 'hello.exe'
    Set-Content -LiteralPath $hello -Encoding utf8NoBOM -Value '#include <stdio.h>
int main(void) { puts("PASS: Windows ARM64 MSVC CRT"); return 0; }'
    $flags = @('--target=aarch64-pc-windows-msvc19.40.0', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic-errors')
    Invoke-Bounded 'clang.exe' ($flags + @($hello, '-o', $helloExe)) | Out-Null
    $report.native_execution = 'running'
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
    $result = Invoke-Bounded $smoke @() -TimeoutSeconds 30 -AllowedExitCodes @(0, 2)
    $report.wgpu_exit_code = $result.exit_code
    $report.wgpu_stdout = $result.stdout
    $report.wgpu_stderr = $result.stderr
    $report.wgpu = $result.stdout | ConvertFrom-Json
    if ($result.exit_code -ne 0 -or -not $report.wgpu.instance_created -or -not $report.wgpu.callback_returned) { throw 'wgpu instance/callback smoke failed' }
    $report.native_execution = 'passed'
    $report.status = 'passed'
} catch {
    if ($report.native_execution -eq 'running') { $report.native_execution = 'failed' }
    $report.error = $_.Exception.Message
    if ($_.Exception.Data.Contains('result')) { $report.failed_command = $_.Exception.Data['result'] }
    Write-Error $_ -ErrorAction Continue
} finally {
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $output 'summary.json') -Encoding utf8NoBOM
}
if ($report.status -ne 'passed') { exit 1 }
