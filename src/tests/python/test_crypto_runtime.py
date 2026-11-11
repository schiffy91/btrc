"""Library.Crypto against known answers, ssh-keygen and a second process, through both frontends."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder, NativePlanReader

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "crypto"
PASSED = "PASS: signatures, OpenSSH keys, trusted keys and the secure channel\n"
RUN_TIMEOUT = 120
COMPILE_TIMEOUT = 240
STRICT = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors"]
SANITIZED = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]


def _require_host() -> None:
    if sys.platform != "linux":
        pytest.skip("requires Linux: Library.Crypto's libsodium provider has a Linux row only")


def _build(c_compiler: str, plan: Path, generated: Path, executable: Path, *, sanitized: bool = False) -> None:
    """Build from the link plan, which names libsodium for pkg-config."""
    assert NativePlanReader().read(plan).pkg_config == ("libsodium",)
    flags = STRICT + (SANITIZED if sanitized else [])
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc=c_compiler,
        optimization=1 if sanitized else 2,
        compile_flags=flags,
        link_flags=SANITIZED if sanitized else [],
    )


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", False), ("clang", True)])
def test_keys_and_secure_channel_on_both_frontends(
    compiler: str, c_compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    _require_host()
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    generated = tmp_path / f"crypto-{compiler}.c"
    executable = tmp_path / f"crypto-{compiler}"
    plan = _transpile(compiler, FIXTURE / "CryptoConformance.btrc", generated, request)
    _build(c_compiler, plan, generated, executable, sanitized=sanitized)
    environment = {**os.environ, "TMPDIR": str(tmp_path)}
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == PASSED
    assert ran.stderr == ""


def test_reads_the_key_pair_ssh_keygen_writes(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """A fresh OpenSSH key pair loads, and its fingerprint is the one ssh-keygen prints."""
    _require_host()
    private = tmp_path / "identity"
    made = subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "made for one test", "-f", str(private)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert made.returncode == 0, made.stderr
    public = private.with_suffix(".pub")
    listed = subprocess.run(
        ["ssh-keygen", "-l", "-f", str(public)], capture_output=True, text=True, timeout=RUN_TIMEOUT
    )
    assert listed.returncode == 0, listed.stderr
    generated = tmp_path / f"key-file-{compiler}.c"
    executable = tmp_path / f"key-file-{compiler}"
    plan = _transpile(compiler, FIXTURE / "CryptoKeyFile.btrc", generated, request)
    _build("cc", plan, generated, executable)
    ran = subprocess.run(
        [str(executable), str(private), str(public)], capture_output=True, text=True, timeout=RUN_TIMEOUT
    )
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == listed.stdout.split()[1]

    protected = tmp_path / "protected"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "a passphrase", "-f", str(protected)],
        check=True,
        capture_output=True,
        timeout=RUN_TIMEOUT,
    )
    refused = subprocess.run(
        [str(executable), str(protected), str(protected.with_suffix(".pub"))],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert refused.returncode == 3

    # And the other way: ssh-keygen reads a key btrc wrote and derives the same public key.
    written = tmp_path / "written"
    wrote = subprocess.run(
        [str(executable), "write", str(written)], capture_output=True, text=True, timeout=RUN_TIMEOUT
    )
    assert wrote.returncode == 0, wrote.stderr
    derived = subprocess.run(
        ["ssh-keygen", "-y", "-f", str(written)], capture_output=True, text=True, timeout=RUN_TIMEOUT
    )
    assert derived.returncode == 0, derived.stderr
    assert derived.stdout.split()[:2] == wrote.stdout.split()[:2]


def test_both_frontends_plan_the_crypto_group_alike(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    _require_host()
    plan = _transpile("btrc", FIXTURE / "CryptoConformance.btrc", tmp_path / "selfhost.c", request)
    reference = _transpile("python", FIXTURE / "CryptoConformance.btrc", tmp_path / "reference.c", request)
    assert plan.read_bytes() == reference.read_bytes()


def test_windows_builds_base64_but_no_keys(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """Base64 is portable; keys and the channel need a provider."""
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_HOME": str(ROOT / "src")}

    def transpile(source: Path) -> subprocess.CompletedProcess[str]:
        if compiler == "python":
            command = [sys.executable, "-m", "src.compiler.python.main", str(source), "--strict-imports"]
            command += ["--target", "windows-x86_64", "--no-cache", "-o", str(source.with_suffix(".c"))]
        else:
            btrcc = request.getfixturevalue("immutable_btrcc")
            command = [str(btrcc), "--strict-imports", "--target", "windows-x86_64", str(source)]
        return subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )

    values = tmp_path / "Values.btrc"
    values.write_text(
        "import Library.Bytes;\nimport Library.Crypto.Base64;\n\n"
        'int main() { return Base64.encode(Bytes.fromString("f")).equals("Zg==") ? 0 : 1; }\n'
    )
    portable = transpile(values)
    assert portable.returncode == 0, portable.stderr
    for module in ("Sodium", "SigningKey", "SecureChannel", "TrustedKeys"):
        source = tmp_path / f"{module}.btrc"
        source.write_text(f"import Library.Crypto.{module};\n\nint main() {{ return 0; }}\n")
        refused = transpile(source)
        assert refused.returncode != 0
        assert "provider" in refused.stderr
