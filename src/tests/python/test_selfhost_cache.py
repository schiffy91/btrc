"""The suite's shared cache of self-hosted compilers and helper drivers (src/tests/selfhost_cache.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import TRANSPILE_TIMEOUT
from src.tests.selfhost_cache import (
    ENTRY,
    REFERENCE,
    REPO,
    SELFHOST,
    ReferenceCompilerInputs,
    SelfhostCompilerCache,
)

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
        "src/stdlib/GUI/Window.btrc",
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


class _Inputs:
    """What building the stand-in compiler reads from its checkout's stdlib."""

    def __init__(self, repo: Path, modules=("Vector.btrc",), owners=(("Vector", ("Vector.btrc",)),)) -> None:
        self.repo, self.modules, self.owners = repo, modules, owners

    def files(self) -> tuple[Path, ...]:
        return tuple(sorted((self.repo / "src/stdlib" / name).resolve() for name in (*self.modules, "btrc.toml")))

    def symbol_owners(self):
        return self.owners


def _cache(compiler: Path, repo: Path, root: Path | None = None, **inputs) -> SelfhostCompilerCache:
    return SelfhostCompilerCache([str(compiler)], repo=repo, root=root, compiler_inputs=_Inputs(repo, **inputs))


def test_fingerprint_follows_the_sources_and_the_toolchain(tmp_path: Path) -> None:
    repo, cc = _checkout(tmp_path / "checkout"), _toolchain(tmp_path / "tools")
    key = _cache(cc, repo).fingerprint()

    assert _cache(cc, repo).fingerprint() == key
    # A second checkout of the same tree, somewhere else, is the same compiler.
    assert _cache(cc, _checkout(tmp_path / "clone")).fingerprint() == key
    # Another toolchain is not, even when it reports the same version.
    assert _cache(_toolchain(tmp_path / "other"), repo).fingerprint() != key
    assert _cache(_toolchain(tmp_path / "newer", "stand-in cc 2.0"), repo).fingerprint() != key
    (repo / "src/compiler/btrc/BtrccMain.btrc").write_text("edited\n")
    assert _cache(cc, repo).fingerprint() != key


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
    first = _cache(cc, _checkout(tmp_path / "checkout"), shared)
    second = _cache(cc, _checkout(tmp_path / "clone"), shared)

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
    cache = _cache(cc, _checkout(tmp_path / "checkout"))
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
        cache = _cache(cc, repo, root)
        # A compiler already in the cache is reused, never rebuilt.
        binary = _script(cache.root / cache.fingerprint() / "btrcc", "exit 0\n")
        current = cache.ensure()
        link = repo / "build" / "btrcc-test"
        assert current == link / "btrcc" and current.resolve() == binary.resolve()
        # Inside the checkout the link is relative, so it holds where the checkout is mounted elsewhere.
        assert os.path.isabs(os.readlink(link)) == (root is not None)


def test_compiler_key_covers_only_the_stdlib_the_compiler_reads(tmp_path: Path) -> None:
    cc, log = _toolchain(tmp_path / "tools"), tmp_path / "transpiled"
    btrcc = _transpiler(tmp_path / "tools", log)
    repo = _checkout(tmp_path / "checkout")
    driver = repo / "src/tests/Driver.btrc"
    compiler = _cache(cc, repo).fingerprint()
    built = _cache(cc, repo).driver(driver, selfhost_compiler=btrcc)

    # A module the compiler does not import: its compiler stays, while a driver, which may import it, is rebuilt.
    (repo / "src/stdlib/GUI/Window.btrc").write_text("edited\n")
    assert _cache(cc, repo).fingerprint() == compiler
    assert _cache(cc, repo).driver(driver, selfhost_compiler=btrcc) != built
    # The same module once the compiler imports it, and a symbol that changes hands.
    assert _cache(cc, repo, modules=("Vector.btrc", "GUI/Window.btrc")).fingerprint() != compiler
    assert _cache(cc, repo, owners=(("Vector", ("Vector.btrc", "List.btrc")),)).fingerprint() != compiler
    # A module the compiler does import.
    (repo / "src/stdlib/Vector.btrc").write_text("edited\n")
    assert _cache(cc, repo).fingerprint() != compiler


def test_another_checkouts_compiler_inputs_must_be_named(tmp_path: Path) -> None:
    # The reference compiler reads the stdlib beside it, so it cannot answer for another tree.
    with pytest.raises(ValueError, match="another checkout's compiler inputs must be named"):
        SelfhostCompilerCache([str(_toolchain(tmp_path / "tools"))], repo=_checkout(tmp_path / "checkout"))


def test_the_compiler_reads_a_small_part_of_this_trees_stdlib() -> None:
    stdlib = REPO / "src" / "stdlib"
    inputs = ReferenceCompilerInputs()
    files = {path.relative_to(stdlib).as_posix() for path in inputs.files()}
    modules = {name for name in files if name.endswith(".btrc")}

    assert {"Vector.btrc", "Process.btrc", "FileSystem/FileSystem.btrc", "Digest/SHA256.btrc"} <= modules
    assert 20 <= len(modules) < len(list(stdlib.rglob("*.btrc"))) // 4
    # Whole packages the compiler never imports contribute their manifest and nothing else.
    for package in ("GUI", "UI", "Audio", "HTTP", "Tray", "App", "Bluetooth", "USB"):
        assert {name for name in files if name.startswith(f"{package}/")} <= {f"{package}/btrc.toml"}, package
    assert {path.relative_to(stdlib).as_posix() for path in stdlib.rglob("btrc.toml")} <= files
    owners = dict(inputs.symbol_owners())
    assert owners["Vector"] == ("Vector.btrc",) and "Regex" in owners


_OPENED_BY_THE_FRONTEND = """
import json, os, sys
stdlib = os.path.realpath(sys.argv[1])
opened = set()
def record(event, arguments):
    if event == "open" and arguments and isinstance(arguments[0], (str, bytes)):
        path = os.path.realpath(os.fsdecode(arguments[0]))
        if path.startswith(stdlib + os.sep):
            opened.add(os.path.relpath(path, stdlib))
sys.addaudithook(record)
from src.compiler.python import Compiler, CompilerOptions
with open(sys.argv[2], encoding="utf-8") as source:
    Compiler().compile_frontend(source.read(), sys.argv[2], CompilerOptions(use_cache=False))
print(json.dumps(sorted(opened)))
"""


def test_every_stdlib_file_the_frontend_opens_for_the_compiler_is_in_its_key() -> None:
    """Ground truth for the narrowed key: what the reference compiler opens while it parses and analyzes the compiler."""

    stdlib = REPO / "src" / "stdlib"
    result = subprocess.run(
        [sys.executable, "-c", _OPENED_BY_THE_FRONTEND, str(stdlib), ENTRY],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    opened = set(json.loads(result.stdout.splitlines()[-1]))
    inputs = ReferenceCompilerInputs()
    keyed = {path.relative_to(stdlib).as_posix() for path in inputs.files()}
    # Beyond the keyed files, strict visibility reads the root modules to learn which one owns each
    # symbol (and the generated index of that); the key holds the owners themselves.
    owners = {name for _symbol, names in inputs.symbol_owners() for name in names}
    root_modules = {path.name for path in stdlib.glob("*.btrc")}
    assert owners <= root_modules
    assert opened - keyed <= root_modules | {"btrc.symbols"}, sorted(opened - keyed - root_modules)
    assert opened & keyed >= {name for name in keyed if name.endswith(".btrc")}
