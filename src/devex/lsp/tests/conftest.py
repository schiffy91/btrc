"""Shared test fixtures for the LSP suite."""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolated_btrc_cache(tmp_path_factory):
    """Point every btrc cache at a session-temp dir.

    The cache directory resolves to $BTRC_CACHE_DIR > btrc.toml project root >
    the user cache dir; without this fixture the suite would write LSP unit
    pickles into the developer's real user cache (it previously littered the
    invoking cwd). One shared dir per session keeps the stdlib unit cache warm
    across tests while staying hermetic.
    """
    cache = tmp_path_factory.mktemp("btrc-cache")
    old = os.environ.get("BTRC_CACHE_DIR")
    os.environ["BTRC_CACHE_DIR"] = str(cache)
    yield
    if old is None:
        os.environ.pop("BTRC_CACHE_DIR", None)
    else:
        os.environ["BTRC_CACHE_DIR"] = old
