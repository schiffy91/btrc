"""Library.Crypto against known answers, ssh-keygen and a second process, through both frontends.

The primitives are first-party btrc, so a program that imports the group links
nothing beyond its operating system. The link plans say so here, and so do the
binary imports on each host.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.python.native_import_fixtures import zig_libc
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder, NativePlanReader
from tools.qualification.dependencies import DependencyAudit

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "crypto"
VECTORS = ROOT / "src" / "tests" / "stdlib" / "CryptoPrimitives.btrc"
PASSED = "PASS: signatures, OpenSSH keys, trusted keys and the secure channel\n"
SEAM_PASSED = "PASS: hashes, key exchange, signatures, message stream and random bytes\n"
RUN_TIMEOUT = 120
COMPILE_TIMEOUT = 240
STRICT = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors"]
SANITIZED = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
# The Windows rows and the triples their headers are read for.
WINDOWS = {"windows-x86_64": "x86_64-w64-windows-gnu", "windows-aarch64": "aarch64-w64-windows-gnu"}
ANDROID = ("android-aarch64", "android-x86_64")
# A program that needs the seam whole: keys from the system's generator, a signature, random bytes.
KEYS = """\
import Library.Bytes;
import Library.Crypto.SigningKey;
import Library.Crypto.Sodium;

int main() {
	SigningKey key = SigningKey.generate();
	Bytes message = Bytes.fromString("signed by a fresh key");
	if (!key.publicKey().verify(message, key.sign(message))) { return 1; }
	Bytes first = Sodium.randomBytes(300);
	Bytes second = Sodium.randomBytes(300);
	if (first.length() != 300 || first.equals(second)) { return 2; }
	print("PASS: keys and random bytes");
	return 0;
}
"""


def _require_host() -> None:
    if sys.platform not in ("linux", "darwin"):
        pytest.skip("Library.Crypto's conformance programs fork their peers and read ssh-keygen's files")


def _build(
    c_compiler: str,
    plan: Path,
    generated: Path,
    executable: Path,
    *,
    sanitized: bool = False,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> None:
    """Build from the link plan, which names no package, library or framework: only the system's own."""
    read = NativePlanReader().read(plan)
    assert (read.pkg_config, read.libraries, read.frameworks) == ((), (), ())
    flags = STRICT + (SANITIZED if sanitized else [])
    if sanitized and sys.platform == "darwin":
        # Xcode's clang and its sanitizer runtime, as the network and jobs
        # drivers use: the dev shell's compiler-rt ASan deadlocks in its own
        # initialization on this macOS, before main.
        assert monkeypatch is not None
        monkeypatch.delenv("DEVELOPER_DIR", raising=False)
        monkeypatch.delenv("SDKROOT", raising=False)
        flags += ["-isysroot", os.environ["BTRC_NATIVE_SYSROOT"], "-target", os.environ["BTRC_NATIVE_TARGET"]]
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc=c_compiler,
        optimization=1 if sanitized else 2,
        compile_flags=flags,
        link_flags=SANITIZED if sanitized else [],
    )
    assert DependencyAudit().binary_problems(executable, PackageTarget.parse(None).label) == []


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", False), ("clang", True)])
def test_keys_and_secure_channel_on_both_frontends(
    compiler: str,
    c_compiler: str,
    sanitized: bool,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_host()
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    if sanitized and sys.platform == "darwin":
        c_compiler = "/usr/bin/clang"
    generated = tmp_path / f"crypto-{compiler}.c"
    executable = tmp_path / f"crypto-{compiler}"
    plan = _transpile(compiler, FIXTURE / "CryptoConformance.btrc", generated, request)
    _build(c_compiler, plan, generated, executable, sanitized=sanitized, monkeypatch=monkeypatch)
    environment = {**os.environ, "TMPDIR": str(tmp_path)}
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == PASSED
    assert ran.stderr == ""


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", True)])
def test_the_seam_against_known_answers(
    compiler: str,
    c_compiler: str,
    sanitized: bool,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hashes, the key exchange and the message stream as libsodium computes them, and the system's random bytes."""
    _require_host()
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    if sanitized and sys.platform == "darwin":
        c_compiler = "/usr/bin/clang"
    generated = tmp_path / f"seam-{compiler}.c"
    executable = tmp_path / f"seam-{compiler}"
    plan = _transpile(compiler, FIXTURE / "SodiumVectors.btrc", generated, request)
    _build(c_compiler, plan, generated, executable, sanitized=sanitized, monkeypatch=monkeypatch)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == SEAM_PASSED
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


def _transpile_for(
    compiler: str, source: Path, target: str, request: pytest.FixtureRequest, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """One compiler's C and link plan for `target`, written beside the source."""
    plan = source.with_suffix(".json")
    generated = source.with_suffix(".c")
    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main", str(source), "--strict-imports"]
        command += ["--target", target, "--emit-link-plan", str(plan), "--no-cache", "-o", str(generated)]
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        command = [str(btrcc), "--strict-imports", "--target", target, "--emit-link-plan", str(plan), str(source)]
    done = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
    if compiler != "python" and done.returncode == 0:
        generated.write_text(done.stdout, encoding="utf-8")
    return done


def _importer(directory: Path, module: str) -> Path:
    """A program that only imports one module of the group, or the whole group for `Crypto`."""
    source = directory / f"{module}.btrc"
    name = "Library.Crypto" if module == "Crypto" else f"Library.Crypto.{module}"
    source.write_text(f"import {name};\n\nint main() {{ return 0; }}\n", encoding="utf-8")
    return source


def _links_nothing(plan: Path) -> bool:
    record = json.loads(plan.read_text(encoding="utf-8"))
    return (record["pkg-config"], record["frameworks"], record.get("libraries", [])) == ([], [], [])


def _no_header_reader(tmp_path: Path) -> dict[str, str]:
    """The compilers' environment with no SDK to read: a native import for another target would be refused."""
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_HOME": str(ROOT / "src")}
    environment.pop("BTRC_NATIVE_TARGET", None)
    environment.pop("BTRC_NATIVE_SYSROOT", None)
    return environment


@pytest.mark.parametrize("target", [*ANDROID, *sorted(WINDOWS)])
def test_the_primitives_and_base64_are_btrc_on_every_system(
    compiler: str, target: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Base64 and the primitives read no header and link nothing, whatever the target."""
    environment = _no_header_reader(tmp_path)
    values = tmp_path / "Values.btrc"
    values.write_text(
        "import Library.Bytes;\nimport Library.Crypto.Base64;\n\n"
        'int main() { return Base64.encode(Bytes.fromString("f")).equals("Zg==") ? 0 : 1; }\n'
    )
    portable = _transpile_for(compiler, values, target, request, environment)
    assert portable.returncode == 0, portable.stderr
    vectors = tmp_path / VECTORS.name
    shutil.copyfile(VECTORS, vectors)
    built = _transpile_for(compiler, vectors, target, request, environment)
    assert built.returncode == 0, built.stderr
    assert _links_nothing(vectors.with_suffix(".json"))


@pytest.mark.parametrize("target", ANDROID)
def test_android_builds_keys_but_no_channel(
    compiler: str, target: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """The seam, keys and the trusted-key file need only the kernel's generator; the channel needs Library.Network."""
    environment = _no_header_reader(tmp_path)
    for module in ("Sodium", "SigningKey", "TrustedKeys"):
        source = _importer(tmp_path, module)
        built = _transpile_for(compiler, source, target, request, environment)
        assert built.returncode == 0, built.stderr
        assert _links_nothing(source.with_suffix(".json"))
    keys = tmp_path / "Keys.btrc"
    keys.write_text(KEYS, encoding="utf-8")
    built = _transpile_for(compiler, keys, target, request, environment)
    assert built.returncode == 0, built.stderr
    assert built.stderr == "", built.stderr
    assert _links_nothing(keys.with_suffix(".json"))
    # The kernel's generator, called directly: no library stands between.
    assert "getrandom(" in keys.with_suffix(".c").read_text(encoding="utf-8")
    for module in ("SecureChannel", "Crypto"):
        refused = _transpile_for(compiler, _importer(tmp_path, module), target, request, environment)
        assert refused.returncode != 0
        assert "provider" in refused.stderr


@pytest.mark.parametrize("target", sorted(WINDOWS))
def test_windows_builds_keys_but_no_channel(
    compiler: str, target: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Windows has the seam and the keys, linked with the system's bcrypt alone; the rest has no row.

    zig's MinGW-w64 headers stand in for the SDK on any host and zig links the
    executable, which runs where it can: on a Windows host of its architecture.
    """
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(tmp_path / "cache"),
        "BTRC_HOME": str(ROOT / "src"),
        "BTRC_NATIVE_TARGET": WINDOWS[target],
        "BTRC_NATIVE_SYSROOT": str(zig_libc()),
    }
    for module in ("TrustedKeys", "SecureChannel", "Crypto"):
        refused = _transpile_for(compiler, _importer(tmp_path, module), target, request, environment)
        assert refused.returncode != 0
        assert "provider" in refused.stderr

    source = tmp_path / "Keys.btrc"
    source.write_text(KEYS, encoding="utf-8")
    built = _transpile_for(compiler, source, target, request, environment)
    assert built.returncode == 0, built.stderr
    assert built.stderr == "", built.stderr
    plan = json.loads(source.with_suffix(".json").read_text(encoding="utf-8"))
    assert [record["name"] for record in plan["libraries"]] == ["bcrypt"]
    assert (plan["pkg-config"], plan["frameworks"]) == ([], [])
    executable = tmp_path / "Keys.exe"
    with pytest.MonkeyPatch.context() as patched:
        patched.setenv("BTRC_NATIVE_TARGET", environment["BTRC_NATIVE_TARGET"])
        patched.setenv("BTRC_NATIVE_SYSROOT", environment["BTRC_NATIVE_SYSROOT"])
        NativePlanBuilder().build(
            plan_path=source.with_suffix(".json"),
            generated_c=source.with_suffix(".c"),
            output=executable,
            optimization=2,
            compile_flags=STRICT,
        )
    assert executable.read_bytes()[:2] == b"MZ"
    assert DependencyAudit().binary_problems(executable, target) == []
    host_is_arm = os.environ.get("PROCESSOR_ARCHITECTURE", "").lower() == "arm64"
    if sys.platform == "win32" and host_is_arm == (target == "windows-aarch64"):
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
        assert ran.returncode == 0, ran.stderr
        assert ran.stdout.replace("\r\n", "\n") == "PASS: keys and random bytes\n"
