"""Build, start and drive the local Windows 11 guest that runs Windows GUI rows.

docs/design/native-ui-surfaces-and-hosts.md, section 4: hosted runners stay the
recorded Windows evidence, and this guest is the fast loop on a real Windows
with a desktop session. It runs under QEMU/KVM on an x86_64 Linux host from
the `.#platforms` dev shell (nix/platforms.nix), which supplies QEMU, the
software TPM, the Secure Boot firmware and the ISO writer.

    nix develop .#platforms --command python3 -m tools.target_hosts.windows.vm install
    nix develop .#platforms --command python3 -m tools.target_hosts.windows.vm start
    ... vm sync
    ... vm run -- 'cd C:\\btrc\\src; python -m pytest src/tests/python/test_native_ui_shell_windows.py'
    ... vm stop

`install` is unattended: Microsoft's Windows 11 Enterprise evaluation image, an
answer file, and a first-logon script (vm/Setup.ps1) that turns on OpenSSH for
one generated key, installs Python and Git, and registers the desktop-session
job task. `sync` then makes C:\\btrc\\src this checkout.
The evaluation runs for 90 days; `destroy` and `install` rebuild it.

A program started over SSH has no desktop, so `run` hands its command to a
scheduled task that runs in the logged-on session (vm/RunJob.ps1) and follows
its output; `ssh` is for everything that needs no window.

Everything the guest owns lives in one state directory (default
~/.cache/btrc/windows-vm). QEMU and the TPM run as transient systemd user
units, so the guest has a memory limit and survives the shell that started it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import shutil
import socket
import string
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

MEDIA = Path(__file__).resolve().parent / "vm"


class PinnedDownload:
    """A file fetched once and admitted only with the recorded SHA-256."""

    def __init__(self, name, url, sha256):
        self.name, self.url, self.sha256 = name, url, sha256

    def fetch(self, directory):
        target = Path(directory) / self.name
        if target.is_file() and self.digest(target) == self.sha256:
            return target
        partial = target.with_name(target.name + ".part")
        with urllib.request.urlopen(self.url, timeout=60) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output, 1 << 20)
        found = self.digest(partial)
        if found != self.sha256:
            partial.unlink()
            raise ValueError(f"{self.name}: expected SHA-256 {self.sha256}, the download has {found}")
        partial.replace(target)
        return target

    @classmethod
    def digest(cls, path):
        with Path(path).open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()


class WindowsGuest:
    USER = "btrc"
    UNIT = "btrc-windows-vm"
    TPM_UNIT = "btrc-windows-vm-tpm"
    # The x64 English image on Microsoft's public evaluation page
    # (microsoft.com/evalcenter/download-windows-11-enterprise), 26H2.
    IMAGE = PinnedDownload(
        "windows11-enterprise-eval-26h2-x64.iso",
        "https://go.microsoft.com/fwlink/?LinkId=2382600&clcid=0x409&culture=en-us&country=us",
        "bc3f24086ebadc94489066b5ad78089e2cf5c3491e90e790bb81a2b199c10e38",
    )
    # The version windows.yml's native jobs set up.
    PYTHON = PinnedDownload(
        "python-3.13.17-amd64.exe",
        "https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe",
        "5da012101ba2e17113a9a1cd901e9ce1441086f2b7ecb5de06ec94163899a190",
    )

    # Git for Windows without its shell or editors: the tests record the revision they ran.
    GIT = PinnedDownload(
        "MinGit-2.56.1-64-bit.zip",
        "https://github.com/git-for-windows/git/releases/download/v2.56.1.windows.1/MinGit-2.56.1-64-bit.zip",
        "4a92850b6e917da4fd010669b614b55dccf5b0ec333a534cc4be4700dfefdafd",
    )

    def __init__(self, state=None, *, firmware=None, port=2222, cpus=8, memory_mib=12288, disk_gib=80):
        self.state = Path(state or Path.home() / ".cache/btrc/windows-vm").resolve()
        self.firmware = Path(firmware or os.environ.get("BTRC_WINDOWS_VM_FIRMWARE", ""))
        self.port, self.cpus, self.memory_mib, self.disk_gib = port, cpus, memory_mib, disk_gib
        self.disk = self.state / "disk.qcow2"
        self.variables = self.state / "firmware-variables.fd"
        self.key = self.state / "ssh-key"
        self.setup = self.state / "setup.iso"
        self.monitor_socket = self.state / "monitor.sock"
        self.tpm_socket = self.state / "tpm.sock"

    # Host tools and units

    def tool(self, name):
        path = shutil.which(name)
        if path is None:
            raise FileNotFoundError(f"{name} is not on PATH; run this from `nix develop .#platforms`")
        return path

    def unit(self, name, *command, properties=()):
        arguments = ["systemd-run", "--user", "--collect", "--quiet", "--unit", name]
        for assignment in properties:
            arguments += ["-p", assignment]
        subprocess.run([*arguments, "--", *command], check=True, timeout=30)

    def active(self, name=None):
        return (
            subprocess.run(["systemctl", "--user", "is-active", "--quiet", name or self.UNIT], timeout=15).returncode
            == 0
        )

    def machine(self, *, installing):
        """QEMU's arguments: what Windows 11 requires (UEFI with Secure Boot, a
        TPM 2.0, 64 GiB of disk) on devices its installer has drivers for."""
        code = self.firmware / "OVMF_CODE.ms.fd"
        if not code.is_file():
            raise FileNotFoundError(
                f"no Secure Boot firmware at {code}; BTRC_WINDOWS_VM_FIRMWARE comes from `.#platforms`"
            )
        arguments = [
            self.tool("qemu-system-x86_64"),
            "-name", "btrc-windows",
            "-machine", "q35,accel=kvm,smm=on",
            "-global", "driver=cfi.pflash01,property=secure,value=on",
            "-cpu", "host,hv_relaxed,hv_vapic,hv_spinlocks=0x1fff,hv_time",
            "-smp", str(self.cpus),
            "-m", f"{self.memory_mib}M",
            "-rtc", "base=utc",
            "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
            "-drive", f"if=pflash,format=raw,unit=1,file={self.variables}",
            "-chardev", f"socket,id=tpm,path={self.tpm_socket}",
            "-tpmdev", "emulator,id=tpm0,chardev=tpm",
            "-device", "tpm-tis,tpmdev=tpm0",
            "-drive", f"if=none,id=system,format=qcow2,discard=unmap,file={self.disk}",
            "-device", "ide-hd,drive=system,bus=ide.0,bootindex=1",
            "-netdev", f"user,id=network,hostfwd=tcp:127.0.0.1:{self.port}-:22",
            "-device", "e1000e,netdev=network",
            "-device", "qemu-xhci",
            "-device", "usb-tablet",
            "-vga", "std",
            "-display", "none",
            "-monitor", f"unix:{self.monitor_socket},server=on,wait=off",
        ]  # fmt: skip
        if installing:
            arguments += [
                "-drive", f"if=none,id=windows,media=cdrom,readonly=on,file={self.state / self.IMAGE.name}",
                "-device", "ide-cd,drive=windows,bus=ide.1,bootindex=2",
                "-drive", f"if=none,id=setup,media=cdrom,readonly=on,file={self.setup}",
                "-device", "ide-cd,drive=setup,bus=ide.2",
            ]  # fmt: skip
        return arguments

    def monitor(self, command):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(5)
            connection.connect(str(self.monitor_socket))
            connection.sendall(command.encode() + b"\n")
            time.sleep(0.3)
            return connection.recv(65536).decode(errors="replace")

    # Lifecycle

    def start(self, *, installing=False):
        if self.active():
            return
        if not self.disk.is_file():
            raise FileNotFoundError(f"no guest at {self.disk}; run `install` first")
        (self.state / "tpm").mkdir(exist_ok=True)
        for stale in (self.monitor_socket, self.tpm_socket):
            stale.unlink(missing_ok=True)
        self.unit(
            self.TPM_UNIT, self.tool("swtpm"), "socket", "--tpm2", "--terminate",
            "--tpmstate", f"dir={self.state / 'tpm'}", "--ctrl", f"type=unixio,path={self.tpm_socket}",
        )  # fmt: skip
        self.wait(lambda: self.tpm_socket.exists(), 15, "the software TPM's socket")
        self.unit(self.UNIT, *self.machine(installing=installing), properties=[f"MemoryMax={self.memory_mib + 2048}M"])
        self.wait(lambda: self.monitor_socket.exists(), 15, "QEMU's monitor socket")

    def stop(self, *, timeout=180):
        if not self.active():
            return
        if self.ssh("shutdown /s /t 0", timeout=30, check=False).returncode != 0:
            self.monitor("system_powerdown")
        try:
            self.wait(lambda: not self.active(), timeout, "the guest to shut down")
        except TimeoutError:
            subprocess.run(["systemctl", "--user", "stop", self.UNIT], check=True, timeout=60)

    def destroy(self):
        if self.active():
            subprocess.run(["systemctl", "--user", "stop", self.UNIT], check=True, timeout=60)
        if self.state.is_dir():
            shutil.rmtree(self.state)

    def install(self, *, timeout=3 * 3600):
        if self.disk.exists():
            raise FileExistsError(f"a guest already exists at {self.disk}; `destroy` it first")
        self.state.mkdir(parents=True, exist_ok=True)
        self.state.chmod(0o700)
        image = self.IMAGE.fetch(self.state)
        python = self.PYTHON.fetch(self.state)
        git = self.GIT.fetch(self.state)
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "btrc-windows-vm", "-f", str(self.key)],
            check=True,
            timeout=30,
        )
        password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))
        media = self.state / "setup"
        media.mkdir()
        answers = (MEDIA / "autounattend.xml").read_text().replace("@USER@", self.USER).replace("@PASSWORD@", password)
        (media / "autounattend.xml").write_text(answers)
        for script in ("Setup.ps1", "RunJob.ps1"):
            shutil.copy(MEDIA / script, media / script)
        shutil.copy(self.key.with_name(self.key.name + ".pub"), media / "authorized_keys")
        shutil.copy(python, media / "python-installer.exe")
        shutil.copy(git, media / "mingit.zip")
        subprocess.run(
            [self.tool("xorriso"), "-as", "mkisofs", "-quiet", "-J", "-r", "-V", "BTRC_SETUP", "-o", str(self.setup), str(media)],
            check=True, timeout=300,
        )  # fmt: skip
        shutil.rmtree(media)
        subprocess.run(
            [self.tool("qemu-img"), "create", "-q", "-f", "qcow2", str(self.disk), f"{self.disk_gib}G"],
            check=True,
            timeout=60,
        )
        shutil.copy(self.firmware / "OVMF_VARS.ms.fd", self.variables)
        self.variables.chmod(0o600)
        self.start(installing=True)
        # The image's boot loader waits a few seconds for "any key" before it gives up on the disc.
        for _ in range(25):
            self.monitor("sendkey ret")
            time.sleep(1)
        try:
            self.wait(self.ready, timeout, "Windows Setup and the first-logon script", interval=30)
        except TimeoutError:
            self.screenshot(self.state / "install-failure.png")
            raise
        self.stop()
        # Nothing below is needed again: the answers hold the password, and a rebuild fetches the images anew.
        for spent in (self.setup, image, python, git):
            spent.unlink()

    def ready(self):
        return self.ssh("Test-Path C:\\btrc\\ready", timeout=30, check=False).stdout.strip() == "True"

    def wait(self, condition, timeout, what, *, interval=0.5):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise TimeoutError(f"timed out after {timeout} s waiting for {what}")
            time.sleep(interval)

    # Reaching the guest

    def transport(self):
        return [
            "-F", "/dev/null", "-i", str(self.key), "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
            "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", f"UserKnownHostsFile={self.state / 'known-hosts'}",
        ]  # fmt: skip

    def ssh(self, command, *, timeout=600, check=True):
        return subprocess.run(
            ["ssh", *self.transport(), "-p", str(self.port), f"{self.USER}@127.0.0.1", command],
            capture_output=True, text=True, timeout=timeout, check=check,
        )  # fmt: skip

    def copy(self, source, destination, *, timeout=1800):
        """Copy with scp; the guest side of a pair is spelled `guest:C:/path`."""
        remote = f"{self.USER}@127.0.0.1:"
        pair = [
            name.replace("guest:", remote, 1) if name.startswith("guest:") else name for name in (source, destination)
        ]
        subprocess.run(["scp", *self.transport(), "-q", "-r", "-P", str(self.port), *pair], check=True, timeout=timeout)

    def run(self, command, *, timeout=3600):
        """Run a PowerShell command in the logged-on desktop session; returns its exit status and output."""
        script = self.state / "command.ps1"
        script.write_text(command + "\nexit $LASTEXITCODE\n")
        self.ssh("Remove-Item C:\\btrc\\job\\exit, C:\\btrc\\job\\output.log -ErrorAction SilentlyContinue; exit 0")
        self.copy(str(script), "guest:C:/btrc/job/command.ps1")
        script.unlink()
        self.ssh("schtasks /run /tn btrc-job")
        status = []

        def finished():
            status[:] = self.ssh(
                "if (Test-Path C:\\btrc\\job\\exit) { Get-Content C:\\btrc\\job\\exit }", check=False
            ).stdout.split()
            return bool(status)

        self.wait(finished, timeout, "the desktop-session job", interval=2)
        output = self.ssh(
            "if (Test-Path C:\\btrc\\job\\output.log) { Get-Content -Raw C:\\btrc\\job\\output.log }", check=False
        ).stdout
        return int(status[0]), output

    def sync(self, repository=".", *, timeout=1800):
        """Make C:\\btrc\\src this checkout: its HEAD, then the working tree's changes laid over it,
        with the test dependencies installed whenever pyproject.toml has changed."""
        repository = Path(repository).resolve()

        def git(*arguments):
            return subprocess.run(
                ["git", "-C", str(repository), *arguments], capture_output=True, text=True, check=True, timeout=300
            ).stdout

        revision = git("rev-parse", "HEAD").strip()
        bundle = self.state / "head.bundle"
        git("bundle", "create", "-q", str(bundle), "HEAD")
        changed = [name for name in git("ls-files", "-z", "-m", "-o", "--exclude-standard").split("\0") if name]
        overlay = self.state / "changes.tar"
        subprocess.run(
            ["tar", "-C", str(repository), "-cf", str(overlay), "--null", "--files-from=-"],
            input="\0".join(name for name in changed if (repository / name).is_file()), text=True, check=True, timeout=300,
        )  # fmt: skip
        try:
            self.copy(str(bundle), "guest:C:/btrc/head.bundle", timeout=timeout)
            self.copy(str(overlay), "guest:C:/btrc/changes.tar", timeout=timeout)
        finally:
            bundle.unlink(missing_ok=True)
            overlay.unlink(missing_ok=True)
        self.ssh(
            "$ErrorActionPreference = 'Stop'; "
            "if (-not (Test-Path C:\\btrc\\src\\.git)) { git init -q C:\\btrc\\src }; "
            "Set-Location C:\\btrc\\src; "
            "git fetch -q C:\\btrc\\head.bundle HEAD; "
            f"git checkout -q -f --detach {revision}; "
            "git clean -q -fd; "
            "tar -xf C:\\btrc\\changes.tar; "
            "Remove-Item C:\\btrc\\head.bundle, C:\\btrc\\changes.tar; "
            "$wanted = (Get-FileHash pyproject.toml).Hash; "
            "if (-not (Test-Path C:\\btrc\\dependencies) -or (Get-Content C:\\btrc\\dependencies) -ne $wanted) { "
            "python -m pip install --quiet --disable-pip-version-check '.[dev]'; "
            "if ($LASTEXITCODE -ne 0) { throw 'pip could not install the test dependencies' }; "
            "Set-Content C:\\btrc\\dependencies $wanted }",
            timeout=timeout,
        )
        return revision

    def screenshot(self, path):
        self.monitor(f"screendump {path} -f png")


class WindowsGuestCommand:
    """The command line: one subcommand per guest operation."""

    def __init__(self, arguments):
        parser = argparse.ArgumentParser(
            prog="python3 -m tools.target_hosts.windows.vm", description=__doc__.splitlines()[0]
        )
        parser.add_argument("--state", help="the guest's directory (default ~/.cache/btrc/windows-vm)")
        commands = parser.add_subparsers(dest="command", required=True)
        for name in ("install", "start", "stop", "status", "destroy"):
            commands.add_parser(name)
        for name in ("ssh", "run"):
            commands.add_parser(name).add_argument("line", nargs="+", help="the PowerShell command")
        copy = commands.add_parser("copy", help="scp; write the guest side as guest:C:/path")
        copy.add_argument("source")
        copy.add_argument("destination")
        commands.add_parser("sync", help="make C:\\btrc\\src this checkout, uncommitted changes included")
        commands.add_parser("screenshot").add_argument("path")
        self.options = parser.parse_args(arguments)
        self.guest = WindowsGuest(self.options.state)

    def execute(self):
        options, guest = self.options, self.guest
        if options.command in ("install", "start", "stop", "destroy"):
            getattr(guest, options.command)()
        elif options.command == "status":
            print("running" if guest.active() else "stopped" if guest.disk.is_file() else "not installed")
        elif options.command == "ssh":
            result = guest.ssh(" ".join(options.line), check=False)
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode
        elif options.command == "run":
            status, output = guest.run(" ".join(options.line))
            sys.stdout.write(output)
            return status
        elif options.command == "sync":
            print(guest.sync())
        elif options.command == "copy":
            guest.copy(options.source, options.destination)
        elif options.command == "screenshot":
            guest.screenshot(Path(options.path).resolve())
        return 0


if __name__ == "__main__":
    sys.exit(WindowsGuestCommand(sys.argv[1:]).execute())
