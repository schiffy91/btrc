"""Build a public Library.GUI application with the opt-in native Wayland backend."""

import argparse
import os
import platform
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.cli.compiler import CompilerCommand
from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[2]
TOOLKIT_UNITS = {
    "Linux/GtkShim.c",
    "Linux/Viewport.c",
    "Linux/GtkCanvas.c",
    "Linux/GtkControls.c",
    "Linux/GtkSurface.c",
    "Linux/GtkPortalParent.c",
    "Linux/DmaBufReceiver.c",
    "Linux/GtkSharedFrame.c",
}
TOOLKIT_PACKAGES = {"gtk4", "gtk4-wayland", "gtk4-x11", "wayland-client", "x11"}
WAYLAND_UNITS = (
    "Wire",
    "Window",
    "Input",
    "Keymap",
    "GPUWire",
    "Cursor",
    "TextInput",
    "Clipboard",
    "Platform",
    "PortalParent",
    "Scene",
    "Slider",
    "Button",
    "ControlText",
    "Tooltip",
    "Alert",
    "Label",
    "Select",
    "TextLines",
    "EditBuffer",
    "TextField",
    "Surface",
)
PROVIDERS = {
    "Shim.ToolkitFeatures": "Linux.Wayland.PreviewFeatures",
    "Shim.WebViewProvider": "Linux.Wayland.PreviewWeb",
    "Linux.SharedFrameViewProvider": "Unavailable.SharedFrameViewProvider",
}


def configure(root: Path) -> None:
    """Select the Linux backend in an isolated compiler data root, retaining public exports."""
    for name in ("stdlib", "runtime", "language"):
        shutil.copytree(ROOT / "src" / name, root / name)
    manifest = root / "stdlib/GUI/btrc.toml"
    sections = []
    for section in re.split(r"(?=^\[\[)", manifest.read_text(), flags=re.MULTILINE):
        if (
            section.startswith("[[native.sources]]")
            and tomllib.loads(section)["native"]["sources"][0]["path"] in TOOLKIT_UNITS
        ):
            continue
        if section.startswith("[[native.pkg-config]]"):
            row = tomllib.loads(section)["native"]["pkg-config"][0]
            if row.get("os") == ["linux"] and row["name"] in TOOLKIT_PACKAGES:
                continue
        if section.startswith("[[package.providers]]"):
            row = tomllib.loads(section)["package"]["providers"][0]
            if "linux" in row.get("os", []) and row["implementation"] in PROVIDERS:
                section = re.sub(r"^os = \[.*?\]$", 'os = ["linux"]', section, flags=re.MULTILINE)
                section = section.replace(
                    f'implementation = "{row["implementation"]}"',
                    f'implementation = "{PROVIDERS[row["implementation"]]}"',
                )
        sections.append(section)
    units = [f"Linux/Wayland/{unit}.c" for unit in WAYLAND_UNITS] + ["Text/LineBreak.c", "Text/Grapheme.c"]
    for unit in units:
        module = "Shim.ShimSurface" if unit.endswith("/Surface.c") else "Shim.Shim"
        sections.append(
            f'\n[[native.sources]]\npath = "{unit}"\nlanguage = "c"\nstandard = "c11"\nmodules = ["{module}"]\nos = ["linux"]\n'
        )
    manifest.write_text("".join(sections))


def build(source: Path, output: Path, compiler: str, folder: Path) -> int:
    configure(folder)
    target = f"linux-{platform.machine()}"
    generated, plan = folder / "app.c", folder / "plan.json"
    arguments = ["--target", target, "--emit-link-plan", str(plan), str(source.resolve())]
    if compiler == "python":
        repository = StdlibRepository(directory=str(folder / "stdlib"))
        frontend = FrontendStage(imports=ImportResolver(stdlib=repository))
        command = CompilerCommand(Compiler(pipeline=CompilationPipeline(frontend=frontend)))
        status = command.run(["--no-cache", *arguments, "-o", str(generated)])
        if status:
            return status
    else:
        with generated.open("wb") as result:
            subprocess.run(
                [compiler, *arguments], stdout=result, check=True, env={**os.environ, "BTRC_HOME": str(folder)}
            )
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
        parser.error("the native Wayland preview requires a Linux build host")
    with tempfile.TemporaryDirectory(prefix="btrc-wayland-") as folder:
        return build(options.source, options.output, options.compiler, Path(folder))


if __name__ == "__main__":
    raise SystemExit(main())
