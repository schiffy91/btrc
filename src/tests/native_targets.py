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

import json
import os
from pathlib import Path

from src.compiler.python.frontend.packages import PackageTarget

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


def stub_sysroot(sysroot: Path, target: str) -> None:
    """Write the files that identify `target`'s sysroot kind, and no SDK headers.

    Both compilers validate a sysroot from its files (NativeSysroot): an
    Apple SDK names itself in SDKSettings.json, and a MinGW sysroot has its
    any-windows-any headers. The stubs satisfy that check; a binding header
    that includes a real SDK header still fails, as it should.
    """

    row = PackageTarget.parse(target).row
    if row.sysroot_kind == "xcrun":
        settings = {"CanonicalName": f"{row.sysroot_name}{row.minimum_version}", "Version": row.minimum_version}
        (sysroot / "SDKSettings.json").write_text(json.dumps(settings), encoding="utf-8")
    elif row.sysroot_kind == "zig-mingw":
        headers = sysroot / "include" / "any-windows-any"
        headers.mkdir(parents=True, exist_ok=True)
        (headers / "windows.h").write_text("/* stub */\n", encoding="utf-8")
        (headers / "_mingw_mac.h").write_text("#define __MINGW64_VERSION_MAJOR 0\n", encoding="utf-8")
    elif row.sysroot_kind == "ndk":
        (sysroot / "usr" / "include" / "android").mkdir(parents=True, exist_ok=True)
        (sysroot / "usr" / "include" / "android" / "api-level.h").write_text("/* stub */\n", encoding="utf-8")
        (sysroot / "usr" / "lib" / f"{row.architecture}-linux-android" / row.minimum_version).mkdir(
            parents=True, exist_ok=True
        )


def cross_target_environment(directory: Path, target: str, base: dict[str, str] | None = None) -> dict[str, str]:
    """`base` (the process environment by default) reading headers for `target`."""

    sysroot = directory / "native-sysroot"
    sysroot.mkdir(parents=True, exist_ok=True)
    stub_sysroot(sysroot, target)
    packages = directory / "native-pkgconfig"
    packages.mkdir(parents=True, exist_ok=True)
    (packages / "native-package-proof.pc").write_text(
        "Name: native-package-proof\nDescription: cross-target plan proof\nVersion: 1\nCflags:\nLibs:\n",
        encoding="utf-8",
    )
    environment = {
        **(os.environ if base is None else base),
        "BTRC_NATIVE_TARGET": TRIPLES[target],
        "BTRC_NATIVE_SYSROOT": str(sysroot),
        "PKG_CONFIG_PATH": str(packages),
    }
    # The devcontainer sets BASH_ENV to the dev shell's environment, so every
    # bash process re-sources it -- including Nix's pkg-config wrapper, which
    # would then search the dev shell's PKG_CONFIG_PATH instead of this one.
    # The child already inherits the dev shell, so it needs no re-sourcing.
    environment.pop("BASH_ENV", None)
    return environment
