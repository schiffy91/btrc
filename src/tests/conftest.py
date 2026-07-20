"""Shared fixtures + options for the btrc test tree.

The language corpus under src/tests/<category>/ is run through BOTH compilers
by runner.py; the `--compilers` option selects which (default both). The
compiler-specific suites live under src/tests/python/ (Python reference compiler
white-box unit tests) and src/tests/btrc/ (self-hosted compiler tests).
"""

import os
import shlex
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


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


@pytest.fixture(scope="session")
def immutable_btrcc(tmp_path_factory, _selfhost_runtime_data) -> Path:
    """Build one strict immutable self-host compiler per pytest worker."""

    configured = _configured_test_btrcc()
    if configured is not None:
        return configured
    compiler = shlex.split(os.environ.get("BTRC_CC", "cc"))
    if not compiler:
        raise ValueError("BTRC_CC must name a C compiler")
    output = tmp_path_factory.mktemp("immutable-btrcc")
    generated = output / "btrcc.c"
    binary = output / "btrcc"
    environment = {**os.environ, "BTRC_CACHE_DIR": str(output / "cache")}
    transpile = subprocess.run(
        [
            "python3",
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
        timeout=300,
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
            str(binary),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert build.returncode == 0 and binary.is_file(), build.stderr
    if os.name != "nt":
        generated.chmod(0o444)
        binary.chmod(0o555)
    return binary


@pytest.fixture(scope="session")
def semantic_btrcc(immutable_btrcc: Path) -> Path:
    """Compatibility name for semantic and focused self-host tests."""

    return immutable_btrcc


@pytest.fixture(scope="session")
def btrcc_bin(immutable_btrcc: Path) -> str:
    """Compatibility name for the unified language-corpus runner."""

    return str(immutable_btrcc)
