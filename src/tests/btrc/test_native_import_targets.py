"""Native header imports through each Apple mobile target's real SDK.

Both compilers derive the reader triple from the selected targets.toml row and
validate the sysroot from its files (platform-target-contract.md section 3).
The test harness, like any build driver, discovers the SDK; the compilers only
read it. The emitted C must also compile for the target.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.btrc.test_native_packages import _environment, _manifest, _reference, _selfhost

REPO = Path(__file__).resolve().parents[3]
HEADER = REPO / "src/tests/native/target_import/target_import.h"
SDKS = {"ios-aarch64": "iphoneos", "ios-aarch64-simulator": "iphonesimulator"}


# Apple's xcrun with Xcode's developer directory: the dev shell's own xcrun
# and DEVELOPER_DIR name only its pinned macOS SDK.
XCRUN = Path("/usr/bin/xcrun")
XCODE = Path("/Applications/Xcode.app/Contents/Developer")
APPLE_ENVIRONMENT = {"DEVELOPER_DIR": str(XCODE), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home())}


def _sdk(name: str) -> str | None:
    if not XCRUN.is_file() or not XCODE.is_dir():
        return None
    result = subprocess.run(
        [str(XCRUN), "--sdk", name, "--show-sdk-path"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=APPLE_ENVIRONMENT,
    )
    path = result.stdout.strip()
    return path if result.returncode == 0 and Path(path).is_dir() else None


def _project(root: Path) -> Path:
    _manifest(
        root,
        "targetimport",
        native=(
            '\n[[native.bindings]]\nmodule = "Api"\nheader = "target_import.h"\nlanguage = "c"\nstandard = "c11"\n'
            'symbols = ["TargetMode", "TargetRecord", "TargetCallback", "targetMake", "targetCount", "TARGET_MODE_ON"]\n'
        ),
    )
    shutil.copyfile(HEADER, root / "target_import.h")
    (root / "src/Api.btrc").write_text("// Native wrapper module.\n", encoding="utf-8")
    source = root / "src/Main.btrc"
    source.write_text(
        "import ./Api.btrc;\n"
        "int main() {\n"
        "\tTargetRecord record = targetMake(4, TARGET_MODE_ON);\n"
        "\treturn targetCount(&record) == 4 ? 0 : 1;\n"
        "}\n",
        encoding="utf-8",
    )
    return source


@pytest.mark.parametrize("target", sorted(SDKS))
def test_ios_rows_import_native_headers_through_their_sdk(semantic_btrcc: Path, tmp_path: Path, target: str) -> None:
    sdk = _sdk(SDKS[target])
    if sdk is None:
        pytest.skip(f"the {SDKS[target]} SDK is Mac-bound (xcrun)")
    row = PackageTarget.parse(target).row
    source = _project(tmp_path / "project")
    environment = {**_environment(), "BTRC_NATIVE_TARGET": row.triple, "BTRC_NATIVE_SYSROOT": sdk}
    generated = tmp_path / "reference.c"
    reference_plan = tmp_path / "reference.json"
    selfhost_plan = tmp_path / "selfhost.json"
    reference = _reference(source, generated, reference_plan, target=target, environment=environment)
    selfhost = _selfhost(semantic_btrcc, source, selfhost_plan, target=target, environment=environment)
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    assert selfhost_plan.read_bytes() == reference_plan.read_bytes()
    assert selfhost.stdout == generated.read_text(encoding="utf-8")
    # Xcode's own clang: the dev shell's wrapper pins a macOS deployment flag.
    compiled = subprocess.run(
        [
            str(XCRUN),
            "--sdk",
            SDKS[target],
            "clang",
            *row.target_arguments,
            "-isysroot",
            sdk,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(tmp_path / "project"),
            "-c",
            str(generated),
            "-o",
            str(tmp_path / "Main.o"),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=APPLE_ENVIRONMENT,
    )
    assert compiled.returncode == 0, compiled.stderr


@pytest.mark.parametrize(
    ("settings", "reason"),
    [
        (None, "SDKSettings.json is missing"),
        ('{"CanonicalName": "macosx14.0", "Version": "14.0"}', "is not a iphoneos SDK"),
        ('{"CanonicalName": "iphoneos16.4", "Version": "16.4"}', "older than 17.0"),
    ],
)
def test_invalid_ios_sysroot_fails_with_frontend_parity(
    semantic_btrcc: Path, tmp_path: Path, settings: str | None, reason: str
) -> None:
    sysroot = tmp_path / "sysroot"
    sysroot.mkdir()
    if settings is not None:
        (sysroot / "SDKSettings.json").write_text(settings, encoding="utf-8")
    source = _project(tmp_path / "project")
    row = PackageTarget.parse("ios-aarch64").row
    environment = {**_environment(), "BTRC_NATIVE_TARGET": row.triple, "BTRC_NATIVE_SYSROOT": str(sysroot)}
    for result in (
        _reference(source, tmp_path / "reference.c", target="ios-aarch64", environment=environment),
        _selfhost(semantic_btrcc, source, target="ios-aarch64", environment=environment),
    ):
        assert result.returncode != 0
        assert "native imports require a valid xcrun sysroot for ios-aarch64" in result.stderr
        assert reason in result.stderr
