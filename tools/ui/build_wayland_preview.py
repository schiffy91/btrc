"""Build a public Library.GUI application for Linux (native Wayland)."""

import argparse
import os
import platform
import subprocess
import tempfile
from pathlib import Path

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.cli.compiler import CompilerCommand
from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[2]


def emit_plan(source: Path, compiler: str, folder: Path, generated: Path, plan: Path) -> int:
    """Compile a Linux Library.GUI program against the repository's default native Wayland provider."""
    folder.mkdir(parents=True, exist_ok=True)
    target = f"linux-{platform.machine()}"
    arguments = ["--target", target, "--emit-link-plan", str(plan), str(source.resolve())]
    if compiler == "python":
        repository = StdlibRepository(directory=str(ROOT / "src/stdlib"))
        frontend = FrontendStage(imports=ImportResolver(stdlib=repository))
        command = CompilerCommand(Compiler(pipeline=CompilationPipeline(frontend=frontend)))
        status = command.run(["--no-cache", *arguments, "-o", str(generated)])
        if status:
            return status
    else:
        with generated.open("wb") as result:
            subprocess.run(
                [compiler, *arguments], stdout=result, check=True, env={**os.environ, "BTRC_HOME": str(ROOT / "src")}
            )
    return 0


def build(source: Path, output: Path, compiler: str, folder: Path) -> int:
    generated, plan = folder / "app.c", folder / "plan.json"
    status = emit_plan(source, compiler, folder, generated, plan)
    if status:
        return status
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=output.resolve(),
        optimization=0,
        compile_flags=["-ffunction-sections", "-fdata-sections"],
        link_flags=["-Wl,--gc-sections", "-lm"],
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--compiler", default="python", help="python or a path to a self-hosted btrcc")
    options = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("building a Linux GUI executable requires a Linux build host")
    with tempfile.TemporaryDirectory(prefix="btrc-wayland-") as folder:
        return build(options.source, options.output, options.compiler, Path(folder))


if __name__ == "__main__":
    raise SystemExit(main())
