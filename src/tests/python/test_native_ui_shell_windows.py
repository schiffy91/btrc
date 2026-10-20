"""Win32 shell rows (CX-UIA-15): cross-built on Linux or macOS, run on hosted Windows.

On a host with the dev shell, the build tests compile the shared NativeShell
fixture and the UI Automation client for windows-x86_64 and windows-aarch64
through both compilers, and link them with zig against wgpu-native v27.0.4.0's
pinned prebuilt DLL (nix/wgpu-native-prebuilt.nix), whose per-slice pkg-config
record they write. With BTRC_WIN32_EVIDENCE_DIR set, each row's executables
and DLL are copied into its own directory there. windows.yml's win32-native
job runs the execution tests on Windows x64 and ARM64 against that directory:
100 measured shell cycles after two initialization cycles, with window counts
and GDI/USER objects after every teardown, 100 fresh-process restores, and the UI Automation tree a separate COM
client process reads. The execution tests skip off Windows; the build tests
skip on Windows, which has no dev shell. Hosted GPU frames are correctness
evidence from Windows' software adapter, never a pacing or hardware result.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.native_bindings import NativeBindingPackage
from src.tests.process_limits import C_COMPILE_TIMEOUT, TOOL_TIMEOUT
from src.tests.python.native_import_fixtures import zig_libc
from src.tests.python.native_ui_shell_fixtures import SHELL, SYMBOLS, transpile, write_evidence
from tools.native_plan import NativePlanBuilder

if sys.platform != "win32":
    import fcntl

REPO = Path(__file__).resolve().parents[3]
PROBE = SHELL / "probes/windows"
PREBUILT = REPO / "nix/wgpu-native-prebuilt.nix"
# The test id, the target row, zig's architecture and the prebuilt archive's slice.
TARGETS = {
    "windows-x64": ("windows-x86_64", "x86_64-w64-windows-gnu", "x86_64", "windows-x64"),
    "windows-arm64": ("windows-aarch64", "aarch64-w64-windows-gnu", "aarch64", "windows-arm64"),
}
FRONTENDS = {"python": "reference", "selfhost": "selfhost"}
# zig's MinGW rows have UBSan (its runtime links statically) but no ASan runtime.
UBSAN = ["-fsanitize=undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]

# The UI Automation client's COM binding: IUIAutomation, its tree walker, the
# elements and the Value pattern, each claim checked by Library.COM. Strings
# are copied out of their BSTRs; scalar, BOOL and RECT outputs are POD.
UIA_MANIFEST = """manifest-version = 1
[package]
name = "uiAutomationProbe"

[[native.sources]]
path = "UIAutomationLoader.c"
language = "c"
standard = "c11"
modules = ["UIAutomation"]
os = ["windows"]

[[native.bindings]]
module = "UIAutomation"
header = "UIAutomation.h"
language = "c"
standard = "c11"
os = ["windows"]
symbols = ["IUnknown", "IUIAutomation", "IUIAutomationElement", "IUIAutomationTreeWalker", "IUIAutomationValuePattern", "IID_IUnknown", "IID_IUIAutomation", "IID_IUIAutomationElement", "IID_IUIAutomationTreeWalker", "IID_IUIAutomationValuePattern", "UIAutomationCreate", "SysFreeString", "RECT"]

[native.bindings.resources.IUnknown]
ownership = "com"
iid = "IID_IUnknown"
release-executor = "apartment"

[native.bindings.resources.IUIAutomation]
ownership = "com"
iid = "IID_IUIAutomation"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.resources.IUIAutomation.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.IUIAutomation.dispatch.methods]
elementFromHandle = "ElementFromHandle"
controlViewWalker = "get_ControlViewWalker"

[native.bindings.resources.IUIAutomationTreeWalker]
ownership = "com"
iid = "IID_IUIAutomationTreeWalker"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.resources.IUIAutomationTreeWalker.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.IUIAutomationTreeWalker.dispatch.methods]
firstChild = "GetFirstChildElement"
nextSibling = "GetNextSiblingElement"

[native.bindings.resources.IUIAutomationElement]
ownership = "com"
iid = "IID_IUIAutomationElement"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.resources.IUIAutomationElement.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.IUIAutomationElement.dispatch.methods]
controlType = "get_CurrentControlType"
name = "get_CurrentName"
className = "get_CurrentClassName"
automationId = "get_CurrentAutomationId"
hasKeyboardFocus = "get_CurrentHasKeyboardFocus"
isEnabled = "get_CurrentIsEnabled"
boundingRectangle = "get_CurrentBoundingRectangle"
currentPattern = "GetCurrentPattern"

[native.bindings.resources.IUIAutomationValuePattern]
ownership = "com"
iid = "IID_IUIAutomationValuePattern"
base = "IUnknown"
release-executor = "apartment"

[native.bindings.resources.IUIAutomationValuePattern.dispatch]
table = "lpVtbl"
executor = "apartment"
failure = "abort"

[native.bindings.resources.IUIAutomationValuePattern.dispatch.methods]
currentValue = "get_CurrentValue"

[native.bindings.status-results]
"IUIAutomation.elementFromHandle" = "hresult"
"IUIAutomation.controlViewWalker" = "hresult"
"IUIAutomationTreeWalker.firstChild" = "hresult"
"IUIAutomationTreeWalker.nextSibling" = "hresult"
"IUIAutomationElement.name" = "hresult"
"IUIAutomationElement.className" = "hresult"
"IUIAutomationElement.automationId" = "hresult"
"IUIAutomationElement.currentPattern" = "hresult"
"IUIAutomationValuePattern.currentValue" = "hresult"

[native.bindings.copied-outputs."IUIAutomationElement.name.retVal"]
encoding = "utf-16"
free = "SysFreeString"

[native.bindings.copied-outputs."IUIAutomationElement.className.retVal"]
encoding = "utf-16"
free = "SysFreeString"

[native.bindings.copied-outputs."IUIAutomationElement.automationId.retVal"]
encoding = "utf-16"
free = "SysFreeString"

[native.bindings.copied-outputs."IUIAutomationValuePattern.currentValue.retVal"]
encoding = "utf-16"
free = "SysFreeString"

[native.bindings.owned-outputs."UIAutomationCreate.automation"]
result = "AutomationCreation"
status = "hresult"
"""


def prebuilt_archive(target):
    """The row's wgpu-native release archive, fetched once and checked against its pin.

    nix/wgpu-native-prebuilt.nix is the one record of each archive's name and
    SHA-256; the devcontainer has no Nix, so the test fetches the same release
    asset itself and refuses any other bytes. The verified archive is kept
    under build/wgpu-native for later runs and other workers.
    """
    text = PREBUILT.read_text(encoding="utf-8")
    version = re.search(r'version = "([^"]+)";', text)[1]
    pin = re.search(rf'^\s*{re.escape(TARGETS[target][3])} = archive "([^"]+)" "sha256-([^"]+)";', text, re.MULTILINE)
    assert pin, f"{PREBUILT} pins no archive for {target}"
    name, digest = pin[1], base64.b64decode(pin[2]).hex()
    cache = REPO / "build/wgpu-native" / name
    cache.parent.mkdir(parents=True, exist_ok=True)
    with (cache.parent / f"{name}.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if not cache.is_file() or hashlib.sha256(cache.read_bytes()).hexdigest() != digest:
            url = f"https://github.com/gfx-rs/wgpu-native/releases/download/v{version}/{name}"
            with urllib.request.urlopen(url, timeout=300) as response:
                payload = response.read()
            actual = hashlib.sha256(payload).hexdigest()
            assert actual == digest, f"{url} has SHA-256 {actual}, not the pinned {digest}"
            partial = cache.with_suffix(".partial")
            partial.write_bytes(payload)
            partial.replace(cache)
    return cache


def wgpu_native(target, directory):
    """The row's pinned wgpu-native archive, extracted, and its pkg-config directory.

    The x64 archive is the MinGW build, whose import library is libwgpu_native.dll.a;
    the only ARM64 asset is the MSVC build, whose DLL a MinGW program reaches through
    the import library wgpu_native.dll.lib. Linking the import library, never the
    static archive, keeps each program on its own C runtime.
    """
    label = TARGETS[target][0]
    archive = prebuilt_archive(target)
    root = directory / f"wgpu-native-{label}"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(root)
    library = root / "lib" / ("libwgpu_native.dll.a" if target == "windows-x64" else "wgpu_native.dll.lib")
    dll = root / "lib/wgpu_native.dll"
    assert library.is_file() and dll.is_file(), sorted(path.name for path in (root / "lib").iterdir())
    pkgconfig = directory / "pkgconfig"
    pkgconfig.mkdir(parents=True, exist_ok=True)
    (pkgconfig / f"wgpu-native-{label}.pc").write_text(
        f"Name: wgpu-native-{label}\n"
        f"Description: wgpu-native v27.0.4.0 prebuilt for {label}\n"
        "Version: 27.0.4.0\n"
        f"Cflags: -I{root / 'include/webgpu'}\n"
        f"Libs: {library}\n",
        encoding="utf-8",
    )
    return pkgconfig, dll


def cross_environment(target, tmp_path, monkeypatch):
    """Point the header reader and the native plan at the row's sysroot and wgpu-native."""
    pkgconfig, dll = wgpu_native(target, tmp_path / "wgpu")
    monkeypatch.setenv("BTRC_NATIVE_TARGET", TARGETS[target][1])
    monkeypatch.setenv("BTRC_NATIVE_SYSROOT", str(zig_libc()))
    monkeypatch.setenv(
        "PKG_CONFIG_PATH", os.pathsep.join(filter(None, [str(pkgconfig), os.environ.get("PKG_CONFIG_PATH")]))
    )
    # The inherited dev shell is already complete. Re-sourcing the container's
    # BASH_ENV inside Nix's wrappers would replace this row's package path.
    monkeypatch.delenv("BASH_ENV", raising=False)
    return dll


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_windows_shell_packages_survive_container_startup(tmp_path, monkeypatch, target):
    if sys.platform == "win32":
        pytest.skip("requires the Linux or macOS cross-build dev shell")
    startup = tmp_path / "container-startup.sh"
    startup.write_text("export PKG_CONFIG_PATH=/missing-container-default\n", encoding="utf-8")
    monkeypatch.setenv("BASH_ENV", str(startup))
    cross_environment(target, tmp_path, monkeypatch)
    result = subprocess.run(
        ["pkg-config", "--cflags", f"wgpu-native-{TARGETS[target][0]}"],
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert str(tmp_path / f"wgpu/wgpu-native-{TARGETS[target][0]}/include/webgpu") in result.stdout


def compile_probe_units(target, directory, units, includes=(), flags=()):
    """The probe's C units for the row, strict C11 through zig with the Windows overlay."""
    zig = shutil.which("zig")
    assert zig, "the dev shell provides zig"
    objects = []
    for unit in units:
        output = directory / f"{unit.stem}.o"
        command = [
            zig,
            "cc",
            "-target",
            f"{TARGETS[target][2]}-windows-gnu",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            *flags,
            # zig's -O2 is ReleaseFast, which defines NDEBUG; the probe and the
            # shared checkpoint units check every native result with assert.
            "-UNDEBUG",
            "-I",
            str(REPO / "src/runtime/windows"),
            "-include",
            str(REPO / "src/runtime/windows/btrc_win_compat.h"),
            f"-I{REPO / 'src/stdlib'}",
            f"-I{PROBE}",
            *(f"-I{path}" for path in includes),
            "-c",
            str(unit),
            "-o",
            str(output),
        ]
        built = subprocess.run(command, capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT, check=False)
        assert built.returncode == 0, built.stderr
        objects.append(str(output))
    return objects


def link(plan, generated, output, objects, flags=()):
    """Link through the emitted plan, adding the probe objects to its final link
    and the sanitizer flags to every zig compile and link it runs."""

    def run(command, **kwargs):
        command = list(command)
        if command[1:2] == ["cc"]:
            command[2:2] = flags
        if "-o" in command and "-c" not in command:
            command.extend(objects)
        return subprocess.run(command, **kwargs)

    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=output, optimization=2)
    assert output.read_bytes()[:2] == b"MZ"
    return output


def build_shell(tmp_path, frontend, target, request, monkeypatch, sanitized):
    NativeBindingPackage.require_reader()
    dll = cross_environment(target, tmp_path, monkeypatch)
    source = NativeBindingPackage.write(
        SHELL / "NativeShell.btrc", tmp_path / "package", PROBE / "ShellProbe.h", SYMBOLS
    )
    manifest = tmp_path / "package/btrc.toml"
    manifest.write_text(manifest.read_text() + 'read-only-borrows = ["shellStateCheckpoint.draft"]\n')
    generated, plan = tmp_path / "Shell.c", tmp_path / "Shell.json"
    result = transpile(source, generated, plan, frontend, request, TARGETS[target][0])
    assert result.returncode == 0, result.stderr
    assert "warning:" not in result.stderr.lower(), result.stderr
    libraries = [record["name"] for record in json.loads(plan.read_text())["libraries"]]
    assert {"user32", "gdi32", "comctl32"} <= set(libraries), libraries
    # The probe reports the adapter its own WebGPU instance finds.
    webgpu = dll.parent.parent / "include/webgpu"
    flags = UBSAN if sanitized else []
    units = [PROBE / "ShellProbe.c", SHELL / "ShellState.c"]
    objects = compile_probe_units(target, tmp_path, units, [webgpu], flags)
    executable = link(plan, generated, tmp_path / shell_name(frontend, target, sanitized), objects, flags)
    return executable, dll


def shell_name(frontend, target, sanitized):
    return f"native-shell-{FRONTENDS[frontend]}-{target}{'-ubsan' if sanitized else ''}.exe"


def build_uia_client(tmp_path, frontend, target, request):
    """The UI Automation client through one compiler, linked through its plan."""
    root = tmp_path / "uia"
    (root / "src").mkdir(parents=True)
    (root / "btrc.toml").write_text(UIA_MANIFEST, encoding="utf-8")
    for name in ("UIAutomation.h", "UIAutomationLoader.c"):
        shutil.copyfile(PROBE / name, root / name)
    (root / "src/UIAutomation.btrc").write_text("// The UI Automation binding's module.\n", encoding="utf-8")
    source = root / "src/UIAutomationProbe.btrc"
    shutil.copyfile(PROBE / "UIAutomationProbe.btrc", source)
    generated, plan = root / "Client.c", root / "Client.json"
    label = TARGETS[target][0]
    if frontend == "python":
        result = Compiler().compile(
            source.read_text(encoding="utf-8"),
            str(source),
            CompilerOptions(include_stdlib=False, use_cache=False, target=label),
        )
        assert result.successful, (result.failure, [str(item) for item in result.diagnostics])
        generated.write_text(result.c_source, encoding="utf-8")
        plan.write_text(result.native_plan.canonical_json(), encoding="utf-8")
    else:
        completed = subprocess.run(
            [
                str(request.getfixturevalue("immutable_btrcc")),
                "--no-stdlib",
                "--no-cache",
                "--target",
                label,
                "--emit-link-plan",
                str(plan),
                str(source),
            ],
            env={**os.environ, "BTRC_HOME": str(REPO / "src")},
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        generated.write_text(completed.stdout, encoding="utf-8")
    libraries = [record["name"] for record in json.loads(plan.read_text(encoding="utf-8"))["libraries"]]
    assert {"ole32", "oleaut32", "uuid"} <= set(libraries), libraries
    return link(plan, generated, tmp_path / f"uia-probe-{FRONTENDS[frontend]}-{target}.exe", [])


def publish(target, paths):
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if not evidence:
        return None
    directory = Path(evidence) / f"native-shell-{target}"
    directory.mkdir(parents=True, exist_ok=True)
    for path in paths:
        shutil.copy2(path, directory / path.name)
    return directory


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "ubsan"])
@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize("frontend", sorted(FRONTENDS))
def test_windows_native_shell_builds(tmp_path, request, monkeypatch, frontend, target, sanitized):
    if sys.platform == "win32":
        pytest.skip("cross-builds on a Linux or macOS host with the dev shell; Windows runs the published executables")
    executable, dll = build_shell(tmp_path, frontend, target, request, monkeypatch, sanitized)
    # One UI Automation client per compiler serves both of its shell builds.
    published = (
        [executable, dll] if sanitized else [executable, build_uia_client(tmp_path, frontend, target, request), dll]
    )
    publish(target, published)


def tree_nodes(node):
    yield node
    for child in node.get("children", []):
        yield from tree_nodes(child)


def assert_shell_tree(tree):
    """The window's control view holds the fixture's controls, read with no live COM claim.

    UI Automation's control types: Window 50032, Edit 50004, Button 50000, Text 50020.
    The dump runs before the draft is typed, so the edit's Value is still empty.
    """
    assert isinstance(tree, dict), f"UI Automation tree unavailable: {tree}"
    assert tree["client"] == "uia-com" and tree["claims"] == 0, tree.get("claims")
    root = tree["root"]
    assert root["control_type"] == 50032 and root["name"] == "BTRC native shell", root["name"]
    nodes = list(tree_nodes(root))
    edits = [node for node in nodes if node["control_type"] == 50004]
    buttons = [node for node in nodes if node["control_type"] == 50000 and node["name"] == "Commit"]
    labels = {node["name"] for node in nodes if node["control_type"] == 50020 and node["class"] == "Static"}
    assert len(edits) == 1 and edits[0]["class"] == "Edit" and edits[0].get("value") == "", edits
    assert len(buttons) == 1 and buttons[0]["class"] == "Button" and buttons[0]["enabled"], buttons
    assert labels == {f"Row {row}" for row in range(50)}, sorted(labels)


def uia_summary(trees):
    """How many cycles read a UI Automation tree, why the others did not, and what the first tree held."""
    available = [tree for tree in trees if isinstance(tree, dict)]
    summary = {
        "cycles_with_tree": len(available),
        "unavailable": sorted({tree for tree in trees if isinstance(tree, str)})[:3],
    }
    if available:
        types, names = Counter(), []

        def walk(node):
            types[node["control_type"]] += 1
            if node.get("name"):
                names.append(node["name"])
            for child in node.get("children", []):
                walk(child)

        walk(available[0]["root"])
        summary.update(control_types=dict(types), names=names[:12], claims=available[0].get("claims"))
    return summary


def run_shell(command, environment, timeout):
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        return subprocess.CompletedProcess(command, 124, stdout, stderr + f"\nShell exceeded {timeout}-second timeout")


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "ubsan"])
@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize("frontend", sorted(FRONTENDS))
def test_windows_native_shell_runs(tmp_path, monkeypatch, frontend, target, sanitized):
    if sys.platform != "win32":
        pytest.skip("requires Windows: windows.yml's win32-native job runs the executables the build tests publish")
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if not evidence:
        pytest.skip("BTRC_WIN32_EVIDENCE_DIR names no published Windows shell executables")
    directory = (Path(evidence) / f"native-shell-{target}").resolve()
    executable = directory / shell_name(frontend, target, sanitized)
    assert executable.is_file(), sorted(path.name for path in directory.iterdir()) if directory.is_dir() else directory
    diagnostic_mode = os.environ.get("BTRC_UI_SHELL_USER_DIAGNOSTIC", "")
    if diagnostic_mode:
        assert diagnostic_mode in {"count-only", "query-bracket"}
        assert (frontend, target, sanitized) == ("python", "windows-x64", True)
    measured_cycles = int(os.environ.get("BTRC_UI_SHELL_CYCLES", "100"))
    if diagnostic_mode:
        assert measured_cycles == 100
    assert 1 <= measured_cycles <= 100
    warmup_cycles = 2
    cycles = measured_cycles + warmup_cycles
    state = tmp_path / "state"
    state.mkdir()
    environment = {**os.environ}
    for flag_name in ("BTRC_UI_SHELL_NO_AX", "BTRC_UI_SHELL_NO_SCROLL"):
        environment.pop(flag_name, None)
    client = directory / f"uia-probe-{FRONTENDS[frontend]}-{target}.exe"
    if client.is_file():
        environment["BTRC_UI_SHELL_UIA_PROBE"] = str(client)
    result = run_shell([str(executable), str(cycles), str(state)], environment, 1200)
    artifacts = REPO / "build/ui-shell" / shell_name(frontend, target, sanitized).removesuffix(".exe")
    if diagnostic_mode:
        artifacts = artifacts / diagnostic_mode
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "shell.stdout").write_text(result.stdout, encoding="utf-8")
    (artifacts / "shell.stderr").write_text(result.stderr, encoding="utf-8")
    message = f"Shell returncode={result.returncode}\n{result.stderr[-6000:]}\n{result.stdout[-6000:]}"
    assert result.returncode == 0, message
    summary = re.search(
        r"SHELL cycles=(\d+) frames=(\d+) native=(\d+) private=(\d+) registrations=(\d+) dirty-close=missing",
        result.stdout,
    )
    assert summary and int(summary[1]) == cycles, message
    native, private, registrations = map(int, summary.group(3, 4, 5))
    assert native == registrations == 0, message
    teardown = re.findall(r"SHELL teardown provider=(\d+) private=(\d+) registrations=(\d+)", result.stdout)
    assert len(teardown) == cycles and all(int(row[0]) == int(row[2]) == 0 for row in teardown), message
    resources = [
        tuple(map(int, row))
        for row in re.findall(
            r"^SHELL resources cycle=(\d+) gdi=(\d+) user=(\d+) provider=(\d+) private=(\d+)\r?$",
            result.stderr,
            re.MULTILINE,
        )
    ]
    assert [row[0] for row in resources] == list(range(1, cycles + 1)), message
    assert all(row[3] == 0 for row in resources), resources
    # Hosted run 39286206398 reached the same 18 GDI / 9 USER baseline in
    # cycle one in three rows, and cycle two in the fourth. Initialize those
    # process caches before the census, then require 100 further teardowns
    # to match. Provider windows must reach zero even during initialization.
    baseline = resources[warmup_cycles - 1][1:3]
    assert {row[1:3] for row in resources[warmup_cycles:]} == {baseline}, resources
    probes = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    trees = [probe["accessibility"] for probe in probes]
    (artifacts / "uia-trees.json").write_text(json.dumps(trees, indent=1), encoding="utf-8")
    assert len(probes) == cycles, message
    assert all(probe["probe"] == "windows-win32" for probe in probes)
    assert all(probe["dpi_awareness_v2"] and probe["comctl32_v6_cue_banner"] for probe in probes), probes[0]
    for tree in trees:
        assert_shell_tree(tree)
    frames = int(summary[2])
    # Hosted Windows has WARP (Microsoft Basic Render Driver): a correctness adapter, not hardware.
    assert frames == cycles, f"GPU frames {frames}/{cycles}: {probes[0].get('gpu_adapter')}"
    journal = (state / "journal").read_bytes()
    assert journal.decode().splitlines() == [f"commit {index}" for index in range(1, cycles + 1)]
    checkpoint = (state / "checkpoint").read_text().splitlines()
    assert checkpoint[0] == "draft" and int(checkpoint[1]) > 0 and int(checkpoint[2]) == cycles
    expected = f"RESTORE draft=draft anchor={checkpoint[1]} commits={cycles} actions=0"
    for restart in range(100):
        restored = run_shell([str(executable), str(state), "restore"], environment, 60)
        (artifacts / f"restore-{restart}.stdout").write_text(restored.stdout, encoding="utf-8")
        if diagnostic_mode:
            (artifacts / f"restore-{restart}.stderr").write_text(restored.stderr, encoding="utf-8")
        assert restored.returncode == 0, restored.stderr + restored.stdout
        assert expected in restored.stdout.splitlines(), restored.stdout
        restored_teardown = re.search(
            r"SHELL teardown provider=(\d+) private=(\d+) registrations=(\d+)", restored.stdout
        )
        assert restored_teardown and int(restored_teardown[1]) == int(restored_teardown[3]) == 0, restored.stdout
        assert (state / "journal").read_bytes() == journal
    gpu = re.findall(r"^GPU: (.*)$", result.stdout, re.MULTILINE)
    monkeypatch.setenv("BTRC_TEST_RUNNER", os.environ.get("BTRC_TEST_RUNNER", "windows"))
    write_evidence(
        "native-shell" if measured_cycles == 100 else "native-shell-smoke",
        target,
        frontend,
        sanitized,
        {
            "cycles": cycles,
            "warmup_cycles": warmup_cycles,
            "measured_cycles": measured_cycles,
            "frames": frames,
            "gpu": gpu[:3],
            "native_handles": native,
            "private_windows": private,
            "live_registrations": registrations,
            "teardown": teardown,
            "resources": resources,
            "fresh_process_restores": 100,
            "e46": "missing",
            "e47": "fixture-only; stdlib missing",
            "accessibility": uia_summary(trees),
            "probe": {key: value for key, value in probes[0].items() if key != "accessibility"},
            "gate_cycles": measured_cycles == 100,
        },
        build_mode="ubsan" if sanitized else "plain",
    )
