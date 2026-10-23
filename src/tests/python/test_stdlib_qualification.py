"""Full-library qualification includes private providers and cannot omit failed bodies."""

from __future__ import annotations

import copy
import json
import shlex
import shutil

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.python.test_ci_workflow_contracts import _yaml
from tools.qualification.stdlib import REPO, StdlibCheck, StdlibCoverage, StdlibInventory


@pytest.fixture
def inventory(tmp_path):
    root = tmp_path / "stdlib"
    root.mkdir()
    (root / "Windows").mkdir()
    (root / "API.btrc").write_text("class API {}")
    (root / "Windows/Provider.btrc").write_text("class Provider {}")
    (root / "Provider.btrc").write_text("class Provider {}")
    (root / "Caller.btrc").write_text("import Library.API;\n")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "fixture"
exports = ["API", "Caller"]
[[package.providers]]
module = "API"
implementation = "Windows.Provider"
os = ["windows"]
[[package.providers]]
module = "API"
implementation = "Provider"
os = ["linux", "macos"]
""")
    return StdlibInventory(root)


def test_inventory_selects_private_providers_and_follows_imports(inventory):
    windows = {row["module"]: row for row in inventory.rows(PackageTarget.parse("windows-x64"))}
    linux = {row["module"]: row for row in inventory.rows(PackageTarget.parse("linux-x64"))}
    assert windows["Windows/Provider.btrc"]["excluded"] is None
    assert "provider implementation" in windows["Provider.btrc"]["excluded"]
    assert linux["Provider.btrc"]["excluded"] is None
    assert "belongs to windows" in linux["Windows/Provider.btrc"]["excluded"]
    assert windows["Caller.btrc"]["excluded"] is None
    assert linux["Caller.btrc"]["excluded"] is None


def test_native_owner_restriction_reaches_callers_after_conditioning(inventory):
    root = inventory.root
    (root / "Native.btrc").write_text("class Native {}")
    (root / "Native.h").write_text("int nativeCall(void);\n")
    with (root / "btrc.toml").open("a") as manifest:
        manifest.write("""
[[native.bindings]]
module = "Native"
header = "Native.h"
language = "c"
standard = "c11"
symbols = ["nativeCall"]
os = ["windows"]
""")
    (root / "Caller.btrc").write_text("import Library.Native;\n")
    restricted = StdlibInventory(root)
    target = PackageTarget.parse("linux-x64")
    assert "Native.btrc has no native bindings" in restricted.exclusion(root / "Caller.btrc", target)
    (root / "Caller.btrc").write_text("#if _WIN32\nimport Library.Native;\n#endif\n")
    assert StdlibInventory(root).exclusion(root / "Caller.btrc", target) is None


def reports_for(inventory, targets):
    reports = []
    for target in targets:
        for frontend in ("python", "selfhost"):
            rows = inventory.rows(target)
            for row in rows:
                row["status"] = "passed" if row["excluded"] is None else "not-applicable"
            reports.append(
                {
                    "schema": 1,
                    "inventory_sha256": inventory.sha256,
                    "target": target.label,
                    "frontend": frontend,
                    "complete": True,
                    "partial": False,
                    "stdlib_strict": True,
                    "strict_imports": True,
                    "modules": rows,
                }
            )
    return reports


def test_coverage_requires_every_module_with_both_frontends(inventory):
    targets = (PackageTarget.parse("linux-x64"), PackageTarget.parse("windows-x64"))
    reports = reports_for(inventory, targets)
    assert StdlibCoverage(inventory).validate(reports, targets)["modules"] == 4
    with pytest.raises(ValueError, match="missing stdlib reports"):
        StdlibCoverage(inventory).validate(reports[:-1], targets)
    with pytest.raises(ValueError, match="no python coverage"):
        StdlibCoverage(inventory).validate(reports[:2], targets[:1])


@pytest.mark.parametrize("defect", ["partial", "incomplete", "failed", "omitted", "duplicate", "stale", "exclusion"])
def test_coverage_refuses_incomplete_or_changed_evidence(inventory, defect):
    targets = (PackageTarget.parse("linux-x64"), PackageTarget.parse("windows-x64"))
    reports = copy.deepcopy(reports_for(inventory, targets))
    report = reports[0]
    if defect == "partial":
        report["partial"] = True
    elif defect == "incomplete":
        report["complete"] = False
    elif defect == "failed":
        report["modules"][0]["status"] = "failed"
    elif defect == "omitted":
        report["modules"].pop()
    elif defect == "duplicate":
        report["modules"][-1] = report["modules"][0]
    elif defect == "stale":
        report["inventory_sha256"] = "old"
    else:
        report["modules"][0]["excluded"] = "invented exclusion"
    with pytest.raises(ValueError):
        StdlibCoverage(inventory).validate(reports, targets)


def test_current_inventory_has_desktop_coverage_for_every_source():
    inventory = StdlibInventory()
    targets = tuple(PackageTarget.parse(name) for name in ("linux-x64", "macos-arm64", "windows-x64"))
    covered = set()
    for target in targets:
        covered.update(row["module"] for row in inventory.rows(target) if row["excluded"] is None)
    assert covered == {path.relative_to(inventory.root).as_posix() for path in inventory.modules}
    assert "GUI/MacOS/MacOSApplication.btrc" in covered
    assert "GUI/Windows/WindowsApplication.btrc" in covered


def test_ci_requires_all_matrix_reports_even_when_a_compiler_fails():
    workflow = _yaml((REPO / ".github/workflows/stdlib.yml").read_text())
    check = workflow["jobs"]["check"]
    coverage = workflow["jobs"]["coverage"]
    matrix = check["strategy"]["matrix"]["include"]
    assert check["strategy"]["fail-fast"] == "false"
    commands = [step for step in check["steps"] if "--frontend" in step.get("run", "")]
    assert len(commands) == 2
    assert "--frontend python" in commands[0]["run"]
    assert "--frontend selfhost" in commands[1]["run"]
    assert "!cancelled() && steps.compiler.outcome == 'success'" in commands[1]["if"]
    upload = next(step for step in check["steps"] if "actions/upload-artifact@" in step.get("uses", ""))
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    assert coverage["needs"] == "check"
    assert coverage["if"] == "always()"
    script = next(step["run"] for step in coverage["steps"] if "run" in step)
    arguments = shlex.split(script.replace("\\\n", ""))
    targets = {arguments[index + 1] for index, arg in enumerate(arguments) if arg == "--target"}
    reports = {arguments[index + 1] for index, arg in enumerate(arguments) if arg == "--report"}
    assert targets == {row["target"] for row in matrix}
    assert reports == {
        f"build/stdlib-reports/stdlib-strict-{row['id']}/{frontend}/report.json"
        for row in matrix
        for frontend in ("python", "selfhost")
    }


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_strict_check_catches_unused_imported_body_without_writing_sources(tmp_path, request, frontend):
    root = tmp_path / "stdlib"
    root.mkdir()
    for module in (REPO / "src/stdlib").glob("*.btrc"):
        shutil.copy2(module, root / module.name)
    (root / "Probe.btrc").write_text("class Probe { public int broken() { return missingValue; } }")
    (root / "Caller.btrc").write_text("import Library.Probe;\nclass Caller {}\n")
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    binary = request.getfixturevalue("semantic_btrcc") if frontend == "selfhost" else None
    target = PackageTarget.parse(None)
    checker = StdlibCheck(StdlibInventory(root), target, frontend, binary)
    output = tmp_path / "result"
    report = checker.run(output, modules=("Caller.btrc",))
    row = next(row for row in report["modules"] if row["module"] == "Caller.btrc")
    assert row["status"] == "failed"
    assert "missingValue" in (output / row["log"]).read_text()
    assert json.loads((output / "report.json").read_text())["complete"]
    assert before == {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("with_sdk", [False, True])
def test_strict_check_composes_native_bindings_from_sibling_packages(
    tmp_path, request, monkeypatch, frontend, with_sdk
):
    root = tmp_path / "stdlib"
    root.mkdir()
    for module in (REPO / "src/stdlib").glob("*.btrc"):
        shutil.copy2(module, root / module.name)
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "btrc_stdlib_runtime"
[dependencies]
Left = { path = "Left" }
Right = { path = "Right" }
""")
    sdk = None
    if with_sdk:
        sdk = tmp_path / "sdk"
        (sdk / "include").mkdir(parents=True)
        (sdk / "lib/pkgconfig").mkdir(parents=True)
        (sdk / "include/qualification-sdk.h").write_text(
            '#ifndef BTRC_QUALIFICATION_SDK\n#error "target package flags are missing"\n#endif\n'
        )
        (sdk / "lib/pkgconfig/qualification-sdk.pc").write_text(
            "Name: qualification-sdk\nDescription: test SDK\nVersion: 1\nCflags: -DBTRC_QUALIFICATION_SDK=1\n"
        )
        startup = tmp_path / "startup.sh"
        startup.write_text("export CPATH=/missing-sdk\nexport PKG_CONFIG_PATH=/missing-sdk\n")
        monkeypatch.setenv("BASH_ENV", str(startup))
    for group, symbol in (("Left", "leftValue"), ("Right", "rightValue")):
        directory = root / group
        directory.mkdir()
        (directory / "Native.h").write_text(
            ("#include <qualification-sdk.h>\n" if with_sdk else "")
            + f"static inline int {symbol}(void) {{ return 7; }}\n"
        )
        (directory / "Native.btrc").write_text("// Native declarations belong to this module.\n")
        (directory / "btrc.toml").write_text(f'''manifest-version = 1
[package]
name = "btrc_stdlib_{group.lower()}"
exports = ["Native"]
[[native.bindings]]
module = "Native"
header = "Native.h"
language = "c"
standard = "c11"
symbols = ["{symbol}"]
''')
        if with_sdk:
            with (directory / "btrc.toml").open("a") as manifest:
                manifest.write('[[native.pkg-config]]\nname = "qualification-sdk"\nmodules = ["Native"]\n')
    (root / "Left/Native.btrc").write_text(
        "import Library.Right.Native;\nint answer() { return leftValue() + rightValue(); }\n"
    )
    binary = request.getfixturevalue("semantic_btrcc") if frontend == "selfhost" else None
    checker = StdlibCheck(StdlibInventory(root), PackageTarget.parse(None), frontend, binary, sdk)
    output = tmp_path / "result"
    report = checker.run(output, modules=("Left/Native.btrc",))
    row = next(row for row in report["modules"] if row["module"] == "Left/Native.btrc")
    assert row["status"] == "passed", (output / row["log"]).read_text()
