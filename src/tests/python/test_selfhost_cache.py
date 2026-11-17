"""The suite's shared cache of self-hosted compilers and helper drivers (src/tests/selfhost_cache.py)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.tests.selfhost_cache import REFERENCE, SELFHOST, SelfhostCompilerCache

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the stand-in compilers are shell scripts")


def _script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _toolchain(directory: Path, version: str = "stand-in cc 1.0") -> Path:
    """A C compiler that reports `version` and writes its output argument."""

    return _script(
        directory / "cc",
        f'if [ "$1" = --version ]; then echo "{version}"; exit 0; fi\n'
        'while [ $# -gt 0 ]; do if [ "$1" = -o ]; then shift; echo built > "$1"; fi; shift; done\n',
    )


def _transpiler(directory: Path, log: Path) -> Path:
    """A self-hosted compiler that records each source it is given and writes its `-o` argument."""

    return _script(
        directory / "btrcc",
        f'echo "$1" >> "{log}"\nwhile [ $# -gt 0 ]; do if [ "$1" = -o ]; then shift; echo c > "$1"; fi; shift; done\n',
    )


def _checkout(root: Path) -> Path:
    """The smallest tree the fingerprint reads: one file of each input category it covers."""

    for relative in (
        "src/compiler/python/main.py",
        "src/compiler/btrc/BtrccMain.btrc",
        "src/stdlib/Vector.btrc",
        "src/stdlib/btrc.toml",
        "src/language/grammar.ebnf",
        "src/runtime/c/core.c",
        "tools/compiler_codegen/main.py",
        "src/tests/Driver.btrc",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n")
    return root


def test_fingerprint_follows_the_sources_and_the_toolchain(tmp_path: Path) -> None:
    repo, cc = _checkout(tmp_path / "checkout"), _toolchain(tmp_path / "tools")
    key = SelfhostCompilerCache([str(cc)], repo=repo).fingerprint()

    assert SelfhostCompilerCache([str(cc)], repo=repo).fingerprint() == key
    # A second checkout of the same tree, somewhere else, is the same compiler.
    assert SelfhostCompilerCache([str(cc)], repo=_checkout(tmp_path / "clone")).fingerprint() == key
    # Another toolchain is not, even when it reports the same version.
    assert SelfhostCompilerCache([str(_toolchain(tmp_path / "other"))], repo=repo).fingerprint() != key
    assert (
        SelfhostCompilerCache([str(_toolchain(tmp_path / "newer", "stand-in cc 2.0"))], repo=repo).fingerprint() != key
    )
    (repo / "src/compiler/btrc/BtrccMain.btrc").write_text("edited\n")
    assert SelfhostCompilerCache([str(cc)], repo=repo).fingerprint() != key


def test_cache_root_is_the_checkouts_unless_one_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SelfhostCompilerCache.ROOT_VARIABLE, raising=False)
    assert SelfhostCompilerCache.configured_root(tmp_path) == tmp_path / "build" / "test-btrcc"
    monkeypatch.setenv(SelfhostCompilerCache.ROOT_VARIABLE, str(tmp_path / "shared"))
    assert SelfhostCompilerCache.configured_root(tmp_path) == tmp_path / "shared"
    for invalid in ("", "relative/cache"):
        monkeypatch.setenv(SelfhostCompilerCache.ROOT_VARIABLE, invalid)
        with pytest.raises(ValueError, match="absolute directory"):
            SelfhostCompilerCache.configured_root(tmp_path)


def test_checkouts_sharing_a_root_build_each_compiler_and_driver_once(tmp_path: Path) -> None:
    cc, log, shared = _toolchain(tmp_path / "tools"), tmp_path / "transpiled", tmp_path / "shared"
    btrcc = _transpiler(tmp_path / "tools", log)
    first = SelfhostCompilerCache([str(cc)], repo=_checkout(tmp_path / "checkout"), root=shared)
    second = SelfhostCompilerCache([str(cc)], repo=_checkout(tmp_path / "clone"), root=shared)

    built = first.driver(
        first.repo / "src/tests/Driver.btrc", compile_flags=("-pedantic-errors",), selfhost_compiler=btrcc
    )
    assert built == shared / "drivers" / built.parent.name / "driver" and built.read_text() == "built\n"
    # The other checkout's copy of the same tracked source is the same driver: nothing is transpiled again.
    again = second.driver(
        second.repo / "src/tests/Driver.btrc", compile_flags=("-pedantic-errors",), selfhost_compiler=btrcc
    )
    assert again == built
    assert log.read_text().splitlines() == [str(first.repo / "src/tests/Driver.btrc")]
    # Other flags, another frontend or an edited source are other drivers.
    assert first.driver(first.repo / "src/tests/Driver.btrc", selfhost_compiler=btrcc) != built
    (second.repo / "src/tests/Driver.btrc").write_text("edited\n")
    edited = second.driver(
        second.repo / "src/tests/Driver.btrc", compile_flags=("-pedantic-errors",), selfhost_compiler=btrcc
    )
    assert edited != built and len(log.read_text().splitlines()) == 3


def test_helper_drivers_are_transpiled_by_the_selfhost_compiler_unless_the_reference_is_asked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cc, log = _toolchain(tmp_path / "tools"), tmp_path / "transpiled"
    btrcc = _transpiler(tmp_path / "tools", log)
    cache = SelfhostCompilerCache([str(cc)], repo=_checkout(tmp_path / "checkout"))
    source = cache.repo / "src/tests/Driver.btrc"
    # The reference compiler is this interpreter running src.compiler.python.main in the checkout.
    package = cache.repo / "src/compiler/python"
    for directory in (cache.repo / "src", cache.repo / "src/compiler", package):
        (directory / "__init__.py").write_text("")
    (package / "main.py").write_text(
        "import sys\n"
        f"open({str(log)!r}, 'a').write('reference ' + sys.argv[1] + '\\n')\n"
        "open(sys.argv[sys.argv.index('-o') + 1], 'w').write('c\\n')\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(cache.repo))

    selfhost = cache.driver(source, selfhost_compiler=btrcc)
    reference = cache.driver(source, frontend=REFERENCE)

    assert selfhost != reference
    assert log.read_text().splitlines() == [str(source), f"reference {source}"]
    assert cache.driver(source, frontend=SELFHOST, selfhost_compiler=btrcc) == selfhost
    with pytest.raises(ValueError, match="unknown driver frontend"):
        cache.driver(source, frontend="python")


def test_ensure_points_the_checkout_at_the_compiler_it_resolved(tmp_path: Path) -> None:
    cc = _toolchain(tmp_path / "tools")
    repo = _checkout(tmp_path / "checkout")
    for root in (None, tmp_path / "shared"):
        cache = SelfhostCompilerCache([str(cc)], repo=repo, root=root)
        # A compiler already in the cache is reused, never rebuilt.
        binary = _script(cache.root / cache.fingerprint() / "btrcc", "exit 0\n")
        current = cache.ensure()
        link = repo / "build" / "btrcc-test"
        assert current == link / "btrcc" and current.resolve() == binary.resolve()
        # Inside the checkout the link is relative, so it holds where the checkout is mounted elsewhere.
        assert os.path.isabs(os.readlink(link)) == (root is not None)
