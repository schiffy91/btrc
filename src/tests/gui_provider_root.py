"""A compiler data root whose GUI package also exports its native providers.

Products import ``Library.GUI`` and the portable contracts; the GUI manifest
exports no provider module beyond the AppKit seam ``Library.Tray`` uses. The
providers' own conformance fixtures still assert native state through their
modules: on macOS the action queue, view capture, the GPU surface and AppKit
readback through ``IMacOSView``; on Linux synthetic SDL input and a drawn
``LinuxNodeView`` whose shutdown stalls. They compile against this copy of
``src/``, which differs only in that manifest's export list. Shared semantic and numeric owners are also exposed solely for these
white-box fixtures.

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

    PROVIDERS = ("MacOS", "Linux", "Linux.Gtk")

    @classmethod
    def create(cls, root: Path, *, linux: str = "Linux") -> Path:
        """`linux` names the provider package Linux builds select: the shipped
        one, or `Linux.Gtk` while the GTK provider is built beside it
        (docs/design/native-ui-surfaces-and-hosts.md, section 3)."""
        root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(REPO / "src/language", root / "language")
        shutil.copytree(REPO / "src/stdlib", root / "stdlib")
        shutil.copytree(REPO / "src/runtime", root / "runtime")
        manifest = root / "stdlib/GUI/btrc.toml"
        text = manifest.read_text(encoding="utf-8")
        exported = set(tomllib.loads(text)["package"]["exports"])
        # The providers stay private: fixtures reach them through GUI and WebView.
        provider = [
            f"{platform}.{path.stem}"
            for platform in cls.PROVIDERS
            for path in sorted((root / "stdlib/GUI" / platform.replace(".", "/")).glob("*.btrc"))
            if path.stem not in ("GUIProvider", "WebViewProvider") and f"{platform}.{path.stem}" not in exported
        ]
        # White-box fixtures inspect these private owners.
        for name in (
            "ControlEvents",
            "ControlEventQueue",
            "ActionMailbox",
            "SliderValue",
            "SliderInteraction",
            "ApplicationPublisher",
            "ApplicationScheduler",
            "ApplicationNativeWake",
        ):
            if name not in exported:
                provider.append(name)
        assert text.count("exports = [") == 1, "the GUI manifest declares one export list"
        text = text.replace("exports = [", "exports = [" + "".join(f'"{name}", ' for name in provider))
        # The GUI facade and the web view facade each name one Linux provider.
        for facade in ("GUIProvider", "WebViewProvider"):
            shipped = f'implementation = "Linux.{facade}"'
            assert text.count(shipped) == 1, f"the GUI manifest names one Linux {facade}"
            text = text.replace(shipped, f'implementation = "{linux}.{facade}"')
        manifest.write_text(text, encoding="utf-8")
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
