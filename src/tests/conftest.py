"""Shared fixtures + options for the btrc test tree.

The language corpus under src/tests/<category>/ is run through BOTH compilers
by runner.py; the `--compilers` option selects which (default both). The
compiler-specific suites live under src/tests/python/ (Python reference compiler
white-box unit tests) and src/tests/btrc/ (self-hosted compiler tests).
"""

import contextlib
import hashlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Every input category the self-hosted compiler is generated from. This mirrors
# BTRCC_INPUTS in the Makefile: the fingerprint below must cover exactly what
# can change btrcc.c, or a cached compiler would silently answer for sources it
# was not built from.
_BTRCC_INPUT_GLOBS = (
    ("src/compiler/python", "*.py"),
    ("src/compiler/btrc", "*.btrc"),
    ("src/stdlib", "*.btrc"),
    ("src/language", "*.ebnf"),
    ("src/language", "*.asdl"),
    ("src/language", "*.toml"),
    ("src/runtime/c", "*.c"),
    ("src/runtime/c", "*.h"),
    ("src/runtime/c", "*.toml"),
    ("tools/compiler_codegen", "*.py"),
)


def pytest_addoption(parser):
    parser.addoption(
        "--compilers",
        action="store",
        default="python,btrc",
        help="'both', or a comma-separated list containing 'python' (reference) and/or 'btrc' (self-hosted)",
    )


def _parse_compilers(raw: str) -> list[str]:
    """Parse --compilers without silently weakening the requested matrix."""

    value = raw.strip()
    if value == "both":
        return ["python", "btrc"]
    if not value:
        raise pytest.UsageError("--compilers requires 'both', 'python', 'btrc', or a comma-separated list")
    names = [part.strip() for part in raw.split(",")]
    invalid = [name or "<empty>" for name in names if name not in {"python", "btrc"}]
    if invalid:
        raise pytest.UsageError(
            f"unknown --compilers selection(s): {', '.join(invalid)}; expected 'both', 'python', or 'btrc'"
        )
    return list(dict.fromkeys(names))


def _configured_test_btrcc() -> Path | None:
    """Resolve the explicit, test-only self-host compiler override."""

    raw = os.environ.get("BTRC_TEST_BTRCC")
    if raw is None:
        return None
    if not raw.strip():
        raise pytest.UsageError("BTRC_TEST_BTRCC must name an absolute compiler path")
    configured = Path(raw)
    if not configured.is_absolute():
        raise pytest.UsageError("BTRC_TEST_BTRCC must be an absolute path")
    try:
        binary = configured.resolve(strict=True)
    except OSError as error:
        raise pytest.UsageError(f"BTRC_TEST_BTRCC does not resolve to a compiler: {configured}") from error
    if not binary.is_file():
        raise pytest.UsageError(f"BTRC_TEST_BTRCC is not a regular file: {configured}")
    if os.name != "nt" and not os.access(binary, os.X_OK):
        raise pytest.UsageError(f"BTRC_TEST_BTRCC is not executable: {configured}")
    return binary


def pytest_generate_tests(metafunc):
    """Parametrize any test taking a `compiler` arg from --compilers."""
    if "compiler" in metafunc.fixturenames:
        metafunc.parametrize("compiler", _parse_compilers(metafunc.config.getoption("--compilers")))


@pytest.fixture(scope="session", autouse=True)
def _isolated_btrc_cache(tmp_path_factory):
    """Point every btrc cache at a session-temp dir.

    The cache directory resolves to $BTRC_CACHE_DIR > btrc.toml project root >
    the user cache dir; without this fixture the suite would write stdlib JSON
    AST artifacts and generated C into the developer's real user cache. One
    shared dir per session keeps the stdlib AST cache warm across tests while staying
    hermetic. Tests that exercise the resolution order itself monkeypatch the
    variable away.
    """
    cache = tmp_path_factory.mktemp("btrc-cache")
    old = os.environ.get("BTRC_CACHE_DIR")
    os.environ["BTRC_CACHE_DIR"] = str(cache)
    yield
    if old is None:
        os.environ.pop("BTRC_CACHE_DIR", None)
    else:
        os.environ["BTRC_CACHE_DIR"] = old


@pytest.fixture(scope="session", autouse=True)
def _selfhost_runtime_data():
    """Give temp-built self-host compilers an explicit, hermetic data root.

    Relocation/security tests pass a subprocess environment with ``BTRC_HOME``
    removed when they need to exercise executable-relative discovery.  Making
    the ordinary test-session configuration explicit avoids teaching temporary
    binaries to trust the repository working directory.
    """

    old = os.environ.get("BTRC_HOME")
    os.environ["BTRC_HOME"] = str(REPO / "src")
    yield
    if old is None:
        os.environ.pop("BTRC_HOME", None)
    else:
        os.environ["BTRC_HOME"] = old


def _btrcc_fingerprint(compiler: list[str]) -> str:
    """Identify one self-host compiler by everything that can change it.

    The artifact is a pure function of the compiler sources, the shared
    specifications, the runtime C, the generators, and the C toolchain that
    links it. Hashing all of them lets one build serve every worker and every
    later run, while a single edited byte anywhere produces a different key.
    """

    digest = hashlib.sha256()
    digest.update(b"btrcc-test-fixture-v1")
    for relative, pattern in _BTRCC_INPUT_GLOBS:
        for source in sorted((REPO / relative).rglob(pattern)):
            if "__pycache__" in source.parts:
                continue
            digest.update(str(source.relative_to(REPO)).encode())
            digest.update(source.read_bytes())
    digest.update(b"\0".join(part.encode() for part in compiler))
    version = subprocess.run(
        [compiler[0], "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    digest.update(version.stdout.encode())
    return digest.hexdigest()[:32]


@contextlib.contextmanager
def _exclusive(lock_path: Path):
    """Serialize one build across xdist workers and concurrent runs."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":  # pragma: no cover - POSIX advisory locks only
        yield
        return
    import fcntl

    with lock_path.open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@pytest.fixture(scope="session")
def immutable_btrcc(_selfhost_runtime_data) -> Path:
    """Return one strict immutable self-host compiler for the whole run.

    Building it costs minutes -- a 431k-line single translation unit -- so it is
    content-addressed and built at most once. Every xdist worker and every later
    run over unchanged sources reuses the same binary; any source edit changes
    the key and forces a rebuild.
    """

    configured = _configured_test_btrcc()
    if configured is not None:
        return configured
    compiler = shlex.split(os.environ.get("BTRC_CC", "cc"))
    if not compiler:
        raise ValueError("BTRC_CC must name a C compiler")
    output = REPO / "build" / "test-btrcc" / _btrcc_fingerprint(compiler)
    binary = output / "btrcc"
    with _exclusive(output.parent / f"{output.name}.lock"):
        if binary.is_file():
            return binary
        _build_immutable_btrcc(compiler, output, binary)
    return binary


def _build_immutable_btrcc(compiler: list[str], output: Path, binary: Path) -> None:
    """Transpile and link one self-host compiler, publishing it atomically."""

    output.mkdir(parents=True, exist_ok=True)
    generated = output / "btrcc.c"
    staged = output / "btrcc.partial"
    environment = {**os.environ, "BTRC_CACHE_DIR": str(output / "cache")}
    transpile = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "src/compiler/btrc/btrcc_main.btrc",
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert transpile.returncode == 0 and generated.is_file(), transpile.stderr
    build = subprocess.run(
        [
            *compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(generated),
            "-o",
            str(staged),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert build.returncode == 0 and staged.is_file(), build.stderr
    if os.name != "nt":
        generated.chmod(0o444)
        staged.chmod(0o555)
    # Publish only a complete binary: a crashed build must not leave a partial
    # artifact that the next worker trusts because the path exists.
    staged.replace(binary)


@pytest.fixture(scope="session")
def semantic_btrcc(immutable_btrcc: Path) -> Path:
    """Compatibility name for semantic and focused self-host tests."""

    return immutable_btrcc


@pytest.fixture(scope="session")
def btrcc_bin(immutable_btrcc: Path) -> str:
    """Compatibility name for the unified language-corpus runner."""

    return str(immutable_btrcc)
