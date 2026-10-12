"""A compiler data root whose GUI package also exports its native providers.

Products import ``Library.GUI`` and the portable contracts; the GUI manifest
exports no provider module beyond the AppKit seam ``Library.Tray`` uses. The
providers' own conformance fixtures still assert native state through their
modules: on macOS the action queue, view capture, the GPU surface and AppKit
readback through ``IMacOSView``; on Linux synthetic SDL input and a drawn
``LinuxNodeView`` whose shutdown stalls. They compile against this copy of
``src/``, which differs only in that manifest's export list. The shared private semantic
queue is also exposed solely for these white-box fixtures.

``python -m src.tests.gui_provider_root <root> <compiler arguments>`` runs the
Python compiler's CLI against such a root, as ``BTRC_HOME`` does for btrcc.
"""

import shutil
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class GUIProviderRoot:
    """Build and use the white-box data root for native provider fixtures."""

    PROVIDERS = ("MacOS", "Linux")

    @classmethod
    def create(cls, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        (root / "language").symlink_to(REPO / "src/language", target_is_directory=True)
        shutil.copytree(REPO / "src/stdlib", root / "stdlib")
        manifest = root / "stdlib/GUI/btrc.toml"
        text = manifest.read_text(encoding="utf-8")
        exported = set(tomllib.loads(text)["package"]["exports"])
        # GUIProvider stays private: fixtures reach the provider through GUI.
        provider = [
            f"{platform}.{path.stem}"
            for platform in cls.PROVIDERS
            for path in sorted((root / "stdlib/GUI" / platform).glob("*.btrc"))
            if path.stem != "GUIProvider" and f"{platform}.{path.stem}" not in exported
        ]
        # Shared receipt tests inspect this private owner; it is not a product API.
        if (root / "stdlib/GUI/ControlEventQueue.btrc").is_file() and "ControlEventQueue" not in exported:
            provider.append("ControlEventQueue")
        assert text.count("exports = [") == 1, "the GUI manifest declares one export list"
        manifest.write_text(
            text.replace("exports = [", "exports = [" + "".join(f'"{name}", ' for name in provider)), encoding="utf-8"
        )
        return root

    @classmethod
    def compile(cls, arguments: list[str]) -> int:
        """Run the Python compiler CLI with ``arguments[0]`` as its data root."""

        from src.compiler.python.frontend import sources

        sources._DEFAULT_STDLIB_DIRECTORY = str(Path(arguments[0]) / "stdlib")
        from src.compiler.python.main import main

        sys.argv = [sys.argv[0], *arguments[1:]]
        return main()


if __name__ == "__main__":
    sys.exit(GUIProviderRoot.compile(sys.argv[1:]))
