"""The @gpu compute runtime for the iOS simulator row, built with Xcode's own tools.

`src/runtime/gpu` is compiled for the row's triple against wgpu-native's
pinned archive and archived as libbtrc_gpu.a. A dispatching corpus program
then links it, wgpu-native's static library and the frameworks Metal draws
through; the target runner takes those flags from the two variables this
prints (src/tests/target_runner.py, ComputeRuntime.cross_flags):

    eval "$(python3 -m tools.target_hosts.ios.compute --wgpu-native DIR --output DIR)"

`--wgpu-native` is the extracted archive: its `include/webgpu` headers and a
directory holding libwgpu_native.a alone (beside its shared library the
linker would take that one, which a program run by `simctl spawn` cannot
find). Nothing is fetched.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from src.compiler.python.frontend.packages import PackageTarget
from tools.target_hosts.ios.simhost import AppleEnvironment

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "src/runtime/gpu"
SOURCES = ("btrc_gpu.c", "btrc_gpu_async.c")
TARGET = "ios-aarch64-simulator"
FRAMEWORKS = ("Metal", "QuartzCore", "CoreGraphics", "Foundation")
STRICT = ("-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2")


class ComputeRuntimeBuild:
    """One build of libbtrc_gpu.a for the simulator, and the flags a program links it with."""

    def __init__(self, include: Path, libraries: Path, output: Path):
        if not (include / "webgpu.h").is_file():
            raise ValueError(f"{include} has no webgpu.h")
        if not (libraries / "libwgpu_native.a").is_file() or (libraries / "libwgpu_native.dylib").exists():
            raise ValueError(f"{libraries} must hold libwgpu_native.a and not its shared library")
        self.include, self.libraries, self.output = include, libraries, output

    @staticmethod
    def xcrun(*arguments: str) -> str:
        result = subprocess.run(
            [str(AppleEnvironment.XCRUN), "--sdk", "iphonesimulator", *arguments],
            capture_output=True,
            text=True,
            timeout=300,
            env=AppleEnvironment.variables(),
        )
        if result.returncode:
            raise RuntimeError(f"xcrun {arguments[0]} failed ({result.returncode}): {result.stderr.strip()}")
        return result.stdout.strip()

    def build(self) -> Path:
        row = PackageTarget.parse(TARGET).row
        sysroot = self.xcrun("--show-sdk-path")
        self.output.mkdir(parents=True, exist_ok=True)
        objects = []
        for source in SOURCES:
            compiled = self.output / f"{Path(source).stem}.o"
            self.xcrun(
                "clang",
                *row.target_arguments,
                "-isysroot",
                sysroot,
                *STRICT,
                "-DBTRC_GPU_WGPU_NATIVE",
                f"-I{self.include}",
                f"-I{RUNTIME}",
                "-c",
                str(RUNTIME / source),
                "-o",
                str(compiled),
            )
            objects.append(compiled)
        archive = self.output / "libbtrc_gpu.a"
        archive.unlink(missing_ok=True)
        self.xcrun("ar", "rcs", str(archive), *(str(path) for path in objects))
        return archive

    def flags(self) -> tuple[list[str], list[str]]:
        """(compile flags, link flags) of a dispatching program on the row."""
        frameworks = [argument for name in FRAMEWORKS for argument in ("-framework", name)]
        return (
            [f"-I{RUNTIME}", f"-I{self.include}"],
            [f"-L{self.output}", "-lbtrc_gpu", f"-L{self.libraries}", "-lwgpu_native", *frameworks],
        )


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wgpu-native", type=Path, required=True, help="the extracted archive's directory")
    parser.add_argument("--static", default="static", help="its directory holding libwgpu_native.a alone")
    parser.add_argument("--output", type=Path, required=True, help="where libbtrc_gpu.a is built")
    options = parser.parse_args(arguments)
    try:
        archive = options.wgpu_native.resolve()
        build = ComputeRuntimeBuild(archive / "include/webgpu", archive / options.static, options.output.resolve())
        build.build()
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"compute runtime: {error}", file=sys.stderr)
        return 1
    compile_flags, link_flags = build.flags()
    print(f"export BTRC_TARGET_COMPUTE_CFLAGS={shlex.quote(shlex.join(compile_flags))}")
    print(f"export BTRC_TARGET_COMPUTE_LDFLAGS={shlex.quote(shlex.join(link_flags))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
