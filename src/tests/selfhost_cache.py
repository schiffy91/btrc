"""The suite's one cache of self-hosted compilers and the helper drivers built with them.

Every gate takes its self-hosted compiler from here: the `immutable_btrcc`
fixture, the helper drivers of `selfhost_driver`, and the Makefile's shard
and strict-C11 targets, which run ``python3 -m src.tests.selfhost_cache
ensure`` first (``make test-btrcc``) and hand the result to pytest through
``BTRC_TEST_BTRCC``. One build therefore serves `make test`, `make test-c11`
and every shard of a tree, instead of one in ``bin/`` for the shards and a
second under ``build/`` for the fixture.

The cache is content-addressed. A compiler lives at ``<root>/<fingerprint>/btrcc``
and a driver at ``<root>/drivers/<key>/driver``; an entry whose key does not
match the tree is never used, so the root can be shared between checkouts:
``BTRC_TEST_COMPILER_CACHE`` names it, and the default is this checkout's
``build/test-btrcc``. The fingerprint includes the C compiler's resolved path
and version, so a shared root never hands one toolchain's binary to another.

A helper driver is a btrc program that imports compiler modules. It is
transpiled by the cached self-hosted compiler, which takes a third to a half
of the reference compiler's time on the same source. `REFERENCE` builds one
through the reference compiler instead; `test_reference_built_drivers.py`
does that for a small sample and compares the pair on real input, so the
path that builds the compiler itself stays covered on other programs.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import inspect
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from src.tests.c_toolchains import configured_c_compiler, selfhost_link_flags
from src.tests.process_limits import C_COMPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[2]
SELFHOST = "selfhost"
REFERENCE = "reference"


@contextlib.contextmanager
def exclusive(lock_path: Path, *, timeout: float | None = None, owner: str = ""):
    """Serialize shared resources across workers; bounded leases identify their holder."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":  # pragma: no cover - POSIX advisory locks only
        yield
        return
    import fcntl

    # Do not truncate before acquiring: waiting processes need the holder's
    # diagnostic record. The file stays in place; the kernel owns the lease.
    with lock_path.open("a+") as handle:
        if timeout is None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        handle.seek(0)
                        holder = handle.read().strip() or "not yet recorded"
                        raise TimeoutError(
                            f"Timed out after {timeout:g}s waiting for {lock_path}; last recorded holder: {holder}"
                        ) from None
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            if owner:
                handle.seek(0)
                handle.truncate()
                json.dump({"pid": os.getpid(), "owner": owner}, handle)
                handle.flush()
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SelfhostCompilerCache:
    """Content-addressed self-hosted compilers and helper drivers for one tree and one C toolchain."""

    ROOT_VARIABLE = "BTRC_TEST_COMPILER_CACHE"
    # The checkout's pointer at the compiler `ensure` last resolved, for the Makefile to name.
    CURRENT = Path("build") / "btrcc-test"
    # Every input category the self-hosted compiler is generated from. This
    # mirrors BTRCC_INPUTS in the Makefile: the fingerprint must cover exactly
    # what can change btrcc.c, or a cached compiler would silently answer for
    # sources it was not built from.
    INPUT_GLOBS = (
        ("src/compiler/python", "*.py"),
        ("src/compiler/btrc", "*.btrc"),
        ("src/stdlib", "*.btrc"),
        ("src/stdlib", "*.toml"),
        ("src/stdlib", "*.h"),
        ("src/language", "*.ebnf"),
        ("src/language", "*.asdl"),
        ("src/language", "*.toml"),
        ("src/runtime/c", "*.c"),
        ("src/runtime/c", "*.h"),
        ("src/runtime/c", "*.toml"),
        ("tools/compiler_codegen", "*.py"),
    )
    BUILD_TIMEOUT = 900

    def __init__(self, compiler: Sequence[str], *, repo: Path = REPO, root: Path | None = None) -> None:
        if not compiler:
            raise ValueError("BTRC_CC must name a C compiler")
        self.compiler = list(compiler)
        self.repo = repo
        self.root = root if root is not None else self.configured_root(repo)
        self._fingerprint: str | None = None

    @classmethod
    def configured(cls) -> SelfhostCompilerCache:
        """The cache for this checkout and the C compiler the suite is configured with."""

        return cls(configured_c_compiler())

    @classmethod
    def configured_root(cls, repo: Path = REPO) -> Path:
        raw = os.environ.get(cls.ROOT_VARIABLE)
        if raw is None:
            return repo / "build" / "test-btrcc"
        if not raw.strip() or not Path(raw).is_absolute():
            raise ValueError(f"{cls.ROOT_VARIABLE} must be an absolute directory path")
        return Path(raw)

    def fingerprint(self) -> str:
        """Identify one self-host compiler by everything that can change it.

        The artifact is a pure function of the compiler sources, the shared
        specifications, the runtime C, the generators, the C toolchain that
        links it, and the recipe that drives them. Hashing all of them lets one
        build serve every worker, every gate and every later run, while a
        single edited byte anywhere produces a different key. The recipe is
        included because changing a build flag changes the artifact without
        touching any input file, and the toolchain's resolved path because two
        environments can report one version for compilers that link against
        different libraries.
        """

        if self._fingerprint is None:
            digest = hashlib.sha256()
            digest.update(b"btrcc-test-fixture-v2")
            digest.update(b"\0".join(flag.encode() for flag in selfhost_link_flags()))
            for relative, pattern in self.INPUT_GLOBS:
                for source in sorted((self.repo / relative).rglob(pattern)):
                    if "__pycache__" in source.parts:
                        continue
                    digest.update(str(source.relative_to(self.repo)).encode())
                    digest.update(source.read_bytes())
            digest.update(self._toolchain_identity())
            digest.update(inspect.getsource(SelfhostCompilerCache._build_compiler).encode())
            self._fingerprint = digest.hexdigest()[:32]
        return self._fingerprint

    def _toolchain_identity(self) -> bytes:
        executable = shutil.which(self.compiler[0])
        version = subprocess.run(
            [self.compiler[0], "--version"], capture_output=True, text=True, check=False, timeout=C_COMPILE_TIMEOUT
        )
        resolved = os.path.realpath(executable) if executable else ""
        host = f"{sys.platform} {platform.machine()}"
        return b"\0".join(
            [*(part.encode() for part in self.compiler), resolved.encode(), version.stdout.encode(), host.encode()]
        )

    def compiler_binary(self) -> Path:
        """The tree's self-hosted compiler, built here at most once per fingerprint."""

        output = self.root / self.fingerprint()
        binary = output / "btrcc"
        with exclusive(output.parent / f"{output.name}.lock"):
            if not binary.is_file():
                self._build_compiler(output, binary)
        return binary

    def _build_compiler(self, output: Path, binary: Path) -> None:
        """Transpile and link one self-host compiler, publishing it atomically."""

        output.mkdir(parents=True, exist_ok=True)
        generated = output / "btrcc.c"
        staged = output / "btrcc.partial"
        transpile = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.compiler.python.main",
                "src/compiler/btrc/cli/WindowsMain.btrc" if os.name == "nt" else "src/compiler/btrc/BtrccMain.btrc",
                "--no-cache",
                "-o",
                str(generated),
            ],
            cwd=self.repo,
            env=self._environment(output),
            capture_output=True,
            text=True,
            timeout=self.BUILD_TIMEOUT,
        )
        assert transpile.returncode == 0 and generated.is_file(), transpile.stderr
        # The compiler's own sources analyze clean, as its C builds with -Werror.
        assert "warning:" not in transpile.stderr, transpile.stderr
        build = subprocess.run(
            [
                *self.compiler,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                str(generated),
                "-o",
                str(staged),
                *selfhost_link_flags(),
                "-lm",
                "-lpthread",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=self.BUILD_TIMEOUT,
        )
        assert build.returncode == 0 and staged.is_file(), build.stderr
        if os.name != "nt":
            generated.chmod(0o444)
            staged.chmod(0o555)
        # Publish only a complete binary: a crashed build must not leave a partial
        # artifact that the next worker trusts because the path exists.
        staged.replace(binary)

    def _environment(self, output: Path) -> dict[str, str]:
        """A build's environment: this tree's data root and a cache of its own."""

        return {**os.environ, "BTRC_HOME": str(self.repo / "src"), "BTRC_CACHE_DIR": str(output / "cache")}

    def driver(
        self,
        source: Path | str,
        *,
        compile_flags: Sequence[str] = (),
        frontend: str = SELFHOST,
        selfhost_compiler: Path | None = None,
    ) -> Path:
        """One helper driver per source, flags and frontend, built at most once per fingerprint.

        `selfhost_compiler` is the compiler a `SELFHOST` build transpiles
        with; it defaults to this cache's own, and a session that was handed
        one through ``BTRC_TEST_BTRCC`` passes that.
        """

        if frontend not in (SELFHOST, REFERENCE):
            raise ValueError(f"unknown driver frontend: {frontend!r}")
        origin = Path(source).resolve()
        key = hashlib.sha256()
        key.update(self.fingerprint().encode())
        key.update(frontend.encode())
        # A checkout's path is not part of a tracked driver's identity, so checkouts can share one root.
        key.update(
            (origin.relative_to(self.repo).as_posix() if origin.is_relative_to(self.repo) else str(origin)).encode()
        )
        key.update(origin.read_bytes())
        key.update(b"\0".join(flag.encode() for flag in compile_flags))
        digest = key.hexdigest()[:32]
        output = self.root / "drivers" / digest
        binary = output / "driver"
        with exclusive(output.parent / f"{digest}.lock"):
            if binary.is_file():
                return binary
            output.mkdir(parents=True, exist_ok=True)
            generated = output / "driver.c"
            staged = output / "driver.partial"
            if frontend == SELFHOST:
                transpiler = [str(selfhost_compiler if selfhost_compiler is not None else self.compiler_binary())]
            else:
                transpiler = [sys.executable, "-m", "src.compiler.python.main"]
            transpile = subprocess.run(
                [*transpiler, str(origin), "--no-cache", "-o", str(generated)],
                cwd=self.repo,
                env=self._environment(output),
                capture_output=True,
                text=True,
                timeout=self.BUILD_TIMEOUT,
            )
            assert transpile.returncode == 0 and generated.is_file(), transpile.stderr
            built = subprocess.run(
                [*self.compiler, "-std=c11", *compile_flags, str(generated), "-o", str(staged), "-lm", "-lpthread"],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=self.BUILD_TIMEOUT,
            )
            assert built.returncode == 0 and staged.is_file(), built.stderr
            # Publish only a complete binary, as the compiler cache does.
            staged.replace(binary)
        return binary

    def ensure(self) -> Path:
        """Build or reuse the compiler and point the checkout's `CURRENT` link at it."""

        binary = self.compiler_binary()
        link = self.repo / self.CURRENT
        link.parent.mkdir(parents=True, exist_ok=True)
        target = binary.parent
        # A link inside the checkout stays valid where the checkout is mounted at another path.
        destination = os.path.relpath(target, link.parent) if target.is_relative_to(self.repo) else str(target)
        staged = link.with_name(f"{link.name}.{os.getpid()}")
        staged.unlink(missing_ok=True)
        staged.symlink_to(destination, target_is_directory=True)
        staged.replace(link)
        return link / binary.name


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The suite's cache of self-hosted compilers.")
    parser.add_argument(
        "action",
        choices=("ensure", "fingerprint"),
        help="ensure: build or reuse this tree's compiler and print its path; fingerprint: print its cache key",
    )
    action = parser.parse_args(arguments).action
    cache = SelfhostCompilerCache.configured()
    print(cache.ensure() if action == "ensure" else cache.fingerprint())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
