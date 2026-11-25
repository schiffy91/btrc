"""Exercise public wrapped label sizing and compare the full native compositor image."""

import json
import platform
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

import pytest

from src.tests.dependencies import DependencyAudit
from src.tests.python.linux_provider_fixtures import require_linux_reader, transpile_provider_program
from src.tests.python.test_first_party_wayland_window import (
    NATIVE,
    PROVIDER,
    SESSION,
    client,  # noqa: F401
    input_device,  # noqa: F401
    native_wayland_root,  # noqa: F401
    wayland_session_env,
)
from src.tests.python.test_wayland_button_titles import compare
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_public_wayland_label_layout_and_compositor(frontend, native_wayland_root, input_device, tmp_path, request):  # noqa: F811
    require_linux_reader()
    generated, plan, program = (tmp_path / name for name in ("labels.c", "labels.json", "labels"))
    transpile_provider_program(NATIVE / "WaylandLabels.btrc", generated, plan, frontend, request, native_wayland_root)
    native = json.loads(plan.read_text())
    assert {item["name"] for item in native["pkg-config"]} <= {"wgpu-native"}
    linked = {unit["path"] for unit in native["units"]}
    sources = [PROVIDER / name for name in ("ControlText.c", "TextLines.c", "Label.c")]
    sources.append(PROVIDER.parent.parent / "Text/LineBreak.c")
    objects = []
    for source in [
        NATIVE / "WaylandLabels.c",
        *(s for s in sources if not any(path.endswith("/" + s.name) for path in linked)),
    ]:
        obj = tmp_path / (source.stem + ".o")
        subprocess.run(
            [
                "cc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic-errors",
                f"-I{PROVIDER}",
                "-c",
                source,
                "-o",
                obj,
            ],
            check=True,
        )
        objects.append(str(obj))
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=program,
        optimization=0,
        compile_flags=["-ffunction-sections", "-fdata-sections"],
        link_flags=[*objects, "-Wl,--gc-sections", "-lm"],
    )
    assert not DependencyAudit().binary_problems(program, f"linux-{platform.machine()}")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    shutil.copyfile(NATIVE.parent / "fixtures/shaping-fixture.ttf", fonts / "ui.ttf")
    config = tmp_path / "fonts.conf"
    config.write_text(
        f"<fontconfig><dir>{escape(str(fonts))}</dir><alias><family>sans-serif</family><prefer><family>Test</family></prefer></alias></fontconfig>"
    )
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, program, input_device, config],
        env=wayland_session_env(),
        check=True,
        timeout=40,
    )


if __name__ == "__main__":
    compare(*sys.argv[1:], click=(17, 12))
