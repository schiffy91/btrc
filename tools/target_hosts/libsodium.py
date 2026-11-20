"""libsodium as a static library for one cross target, built from its pinned source.

Library.Crypto's Sodium provider binds libsodium. Linux and macOS take it from
the dev shell through pkg-config; an iOS or Android program has no pkg-config
search path, so its build is given a directory this recipe fills:
`<output>/include/sodium.h` and `<output>/lib/libsodium.a`.

    python3 -m tools.target_hosts.libsodium --source DIR --target LABEL \
        --cc COMMAND [--sysroot PATH] --output DIR

The recipe is keyed by the `targets.toml` row and knows no toolchain of its
own. `--cc` is the C compiler command for the row (`/usr/bin/xcrun --sdk
iphonesimulator clang`, an NDK's clang), `--sysroot` its SDK or sysroot, and
the row supplies the target arguments. `--source` is libsodium's source tree:
the dev shell exports the one its own libsodium is built from as
BTRC_LIBSODIUM_SOURCE, so every slice links the same version. Nothing is
fetched.

It runs upstream's own build (`./configure` for the row's host, static only,
then `make install`) in a copy of the source, since the pinned tree is
read-only.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from src.compiler.python.frontend.packages import PackageTarget

# What `./configure --host` calls each row's system: the compiler's own target
# argument decides the code, this only tells configure it is cross-compiling
# and for which family.
HOSTS = {
    ("ios", "aarch64"): "aarch64-apple-darwin",
    ("android", "aarch64"): "aarch64-linux-android",
    ("android", "x86_64"): "x86_64-linux-android",
}
BUILD_TIMEOUT = 1800


class LibsodiumBuild:
    """One static build of libsodium for a target row."""

    def __init__(self, source: Path, target: str, compiler: list[str], sysroot: Path | None, output: Path):
        if not (source / "configure").is_file() or not (source / "src/libsodium/include/sodium.h").is_file():
            raise ValueError(f"{source} is not a libsodium source tree with its configure script")
        self.row = PackageTarget.parse(target).row
        key = (self.row.operating_system, self.row.architecture)
        if key not in HOSTS:
            raise ValueError(f"{target} has no libsodium recipe; its providers take libsodium from pkg-config")
        if not compiler:
            raise ValueError("the compiler command is empty")
        self.host = HOSTS[key]
        self.source, self.compiler, self.sysroot, self.output = source, compiler, sysroot, output

    def flags(self) -> list[str]:
        """The row's target arguments and sysroot, for the compile and the link alike."""
        if self.sysroot is None:
            return list(self.row.target_arguments)
        spelling = "-isysroot" if self.row.operating_system == "ios" else "--sysroot"
        return [*self.row.target_arguments, spelling, str(self.sysroot)]

    def run(self, work: Path, *command: str) -> None:
        result = subprocess.run(
            command, cwd=work, capture_output=True, text=True, timeout=BUILD_TIMEOUT, env=self.environment()
        )
        if result.returncode:
            raise RuntimeError(
                f"{command[0]} failed ({result.returncode}):\n{result.stdout[-2000:]}{result.stderr[-4000:]}"
            )

    @staticmethod
    def environment() -> dict[str, str]:
        """The process environment without a Nix shell's compiler settings, which are the host's."""
        dropped = ("CC", "CXX", "LD", "AR", "RANLIB", "CFLAGS", "LDFLAGS", "CPPFLAGS", "SDKROOT", "DEVELOPER_DIR")
        return {
            name: value for name, value in os.environ.items() if name not in dropped and not name.startswith("NIX_")
        }

    def build(self) -> Path:
        library = self.output / "lib/libsodium.a"
        flags = shlex.join(self.flags())
        with tempfile.TemporaryDirectory(prefix="btrc-libsodium-") as scratch:
            work = Path(scratch) / "source"
            shutil.copytree(self.source, work)
            for path in [work, *work.rglob("*")]:
                path.chmod(path.stat().st_mode | 0o200)
            self.run(
                work,
                "./configure",
                f"--host={self.host}",
                f"--prefix={self.output}",
                "--disable-shared",
                "--enable-static",
                "--disable-dependency-tracking",
                f"CC={shlex.join(self.compiler)}",
                f"CFLAGS=-O2 {flags}",
                f"LDFLAGS={flags}",
            )
            self.run(work, "make", f"-j{os.cpu_count() or 2}", "install")
        if not library.is_file() or not (self.output / "include/sodium.h").is_file():
            raise RuntimeError(f"the build left no {library}")
        return library


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="libsodium's source tree (BTRC_LIBSODIUM_SOURCE)")
    parser.add_argument("--target", required=True, help="the targets.toml row, such as ios-aarch64-simulator")
    parser.add_argument("--cc", required=True, help="the row's C compiler command")
    parser.add_argument("--sysroot", type=Path, help="the row's SDK or sysroot")
    parser.add_argument("--output", type=Path, required=True, help="where include/ and lib/ are installed")
    options = parser.parse_args(arguments)
    try:
        build = LibsodiumBuild(
            options.source.resolve(), options.target, shlex.split(options.cc), options.sysroot, options.output.resolve()
        )
        print(build.build())
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"libsodium: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
