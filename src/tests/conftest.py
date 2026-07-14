"""Shared fixtures + options for the btrc test tree.

The language corpus under src/tests/<category>/ is run through BOTH compilers
by runner.py; the `--compilers` option selects which (default both). The
compiler-specific suites live under src/tests/python/ (Python reference compiler
white-box unit tests) and src/tests/btrc/ (self-hosted compiler tests).
"""

import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--compilers",
        action="store",
        default="python,btrc",
        help="comma-separated list of compilers to run the language corpus "
        "through: 'python' (reference), 'btrc' (self-hosted), or both.",
    )


def pytest_generate_tests(metafunc):
    """Parametrize any test taking a `compiler` arg from --compilers."""
    if "compiler" in metafunc.fixturenames:
        raw = metafunc.config.getoption("--compilers")
        sel = [c.strip() for c in raw.split(",") if c.strip() in ("python", "btrc")]
        if not sel:
            sel = ["python"]
        metafunc.parametrize("compiler", sel)


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
