# First-logon setup of the local Windows 11 guest (tools/target_hosts/windows/vm.py).
# It runs once, as the administrator the answer file created, from the setup disc.
# C:\btrc\ready appears when every step has succeeded; C:\btrc\setup.log keeps the transcript.
$ErrorActionPreference = 'Stop'
$media = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force C:\btrc, C:\btrc\job | Out-Null
Start-Transcript -Path C:\btrc\setup.log -Force

# A test host stays awake, keeps its screen on and does not restart itself for updates.
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /hibernate off
New-Item -Force 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' | Out-Null
Set-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' -Name NoAutoUpdate -Value 1 -Type DWord
# Test programs are unsigned and rebuilt constantly; scanning each one costs minutes.
Add-MpPreference -ExclusionPath C:\btrc

# OpenSSH: the host's key is the only credential, and PowerShell is the shell.
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
New-Item -ItemType Directory -Force C:\ProgramData\ssh | Out-Null
Copy-Item "$media\authorized_keys" C:\ProgramData\ssh\administrators_authorized_keys -Force
icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
New-Item -Force 'HKLM:\SOFTWARE\OpenSSH' | Out-Null
Set-ItemProperty 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Get-NetFirewallRule -Name btrc-sshd -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name btrc-sshd -DisplayName 'btrc OpenSSH' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -Profile Any | Out-Null
}
Set-Service sshd -StartupType Automatic
Start-Service sshd

# Python, as the hosted Windows runners have it, for the target runner and pytest.
$python = Start-Process -Wait -PassThru "$media\python-installer.exe" -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0', 'Include_doc=0'
if ($python.ExitCode -ne 0) { throw "The Python installer exited with $($python.ExitCode)" }

# A task that runs in the logged-on desktop session: a program started over SSH has no desktop.
Copy-Item "$media\RunJob.ps1" C:\btrc\RunJob.ps1 -Force
schtasks /create /f /tn btrc-job /sc once /st 00:00 /it /rl highest /ru $env:USERNAME /tr 'powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\btrc\RunJob.ps1'
if ($LASTEXITCODE -ne 0) { throw "schtasks exited with $LASTEXITCODE" }

Set-Content C:\btrc\ready 'ready'
Stop-Transcript
