"""Header-reader inputs for compiling native bindings for a fixed target from any host.

Both compilers read binding headers only for the target named by
BTRC_NATIVE_TARGET and BTRC_NATIVE_SYSROOT, which must match `--target`. The
dev shell sets them for the host, so a test that pins another target (the
native-package example's canonical `linux-x64` plan, or its macOS and Windows
plans) supplies that target's triple, as a cross build would. The example's
binding headers include no SDK header, so an empty sysroot directory is a
complete one: any SDK include would fail rather than silently read the host's.
The Windows plan selects the example's placeholder pkg-config package, which
the reader resolves like any other, so a stub `.pc` stands in for it.
"""

from __future__ import annotations

import os
from pathlib import Path

TRIPLES = {
    "linux-x64": "x86_64-unknown-linux-gnu",
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "linux-arm64": "aarch64-unknown-linux-gnu",
    "linux-aarch64": "aarch64-unknown-linux-gnu",
    "macos-arm64": "arm64-apple-macosx14.0.0",
    "macos-aarch64": "arm64-apple-macosx14.0.0",
    "macos-x64": "x86_64-apple-macosx14.0.0",
    "macos-x86_64": "x86_64-apple-macosx14.0.0",
    "windows-x64": "x86_64-w64-windows-gnu",
    "windows-x86_64": "x86_64-w64-windows-gnu",
    "windows-arm64": "aarch64-w64-windows-gnu",
    "windows-aarch64": "aarch64-w64-windows-gnu",
}


def cross_target_environment(directory: Path, target: str, base: dict[str, str] | None = None) -> dict[str, str]:
    """`base` (the process environment by default) reading headers for `target`."""

    sysroot = directory / "native-sysroot"
    sysroot.mkdir(parents=True, exist_ok=True)
    packages = directory / "native-pkgconfig"
    packages.mkdir(parents=True, exist_ok=True)
    (packages / "native-package-proof.pc").write_text(
        "Name: native-package-proof\nDescription: cross-target plan proof\nVersion: 1\nCflags:\nLibs:\n",
        encoding="utf-8",
    )
    return {
        **(os.environ if base is None else base),
        "BTRC_NATIVE_TARGET": TRIPLES[target],
        "BTRC_NATIVE_SYSROOT": str(sysroot),
        "PKG_CONFIG_PATH": str(packages),
    }
