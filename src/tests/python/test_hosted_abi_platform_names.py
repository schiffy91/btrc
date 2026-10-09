"""Coverage for the deterministic automatic-header namespace snapshot and its per-target availability."""

import copy
import subprocess
import tomllib
from pathlib import Path

import pytest

from src.compiler.python.abi import generated as generated_abi
from src.compiler.python.abi.hosted import HOSTED_ABI
from src.tests.process_limits import RUN_TIMEOUT
from tools.compiler_codegen.hosted_abi import (
    HostedAbiManifest,
    HostedAbiManifestError,
    HostedAbiPlatformTargetSpec,
    TargetManifest,
)
from tools.compiler_codegen.runtime import RuntimeManifest

HOSTED_PLATFORM_FUNCTION_NAMES = HOSTED_ABI.platform_function_names
HOSTED_PLATFORM_MACROS = HOSTED_ABI.platform_macro_names
HOSTED_PLATFORM_OBJECT_NAMES = HOSTED_ABI.platform_object_names
HOSTED_PLATFORM_TYPE_NAMES = HOSTED_ABI.platform_type_names

SOURCE_ROOT = Path(__file__).parents[2]
HOSTED_SPEC = SOURCE_ROOT / "language/hosted_abi.toml"
TARGET_SPEC = SOURCE_ROOT / "language/targets.toml"
RUNTIME_SPEC = SOURCE_ROOT / "runtime/c/manifest.toml"
DRIVER = Path(__file__).parent / "fixtures/PlatformUnavailableDriver.btrc"
KINDS = HostedAbiPlatformTargetSpec.KINDS
UNAVAILABLE = generated_abi.HOSTED_PLATFORM_UNAVAILABLE
PLATFORM = {
    "functions": frozenset(generated_abi.HOSTED_PLATFORM_FUNCTION_NAMES),
    "macros": frozenset(generated_abi.HOSTED_PLATFORM_MACRO_NAMES),
    "objects": frozenset(generated_abi.HOSTED_PLATFORM_OBJECT_NAMES),
    "types": frozenset(generated_abi.HOSTED_PLATFORM_TYPE_NAMES),
    "typedefs": frozenset(generated_abi.HOSTED_PLATFORM_TYPEDEF_NAMES),
}
LABELS = tuple(row.label for row in generated_abi.TARGET_ROWS)
IOS = ("ios-aarch64", "ios-aarch64-simulator")
MACOS = ("macos-aarch64", "macos-x86_64")
LINUX = ("linux-aarch64", "linux-x86_64")
ANDROID = ("android-aarch64", "android-x86_64")
MSVC = "windows-aarch64-msvc"


def test_platform_snapshot_covers_supported_header_families() -> None:
    assert {
        "read",  # unistd.h
        "stat",  # sys/stat.h
        "getpwnam_r",  # pwd.h
        "regexec",  # regex.h
        "inet_pton",  # arpa/inet.h
        "explicit_bzero",  # supported Linux and Darwin libc seam
        "forkpty",  # canonical stdlib prototype outside the baseline headers
        "GetFileAttributesA",  # narrow Windows compatibility seam
        "btrc_gpu_dispatch",  # native runtime header
    } <= HOSTED_PLATFORM_FUNCTION_NAMES
    assert {
        "DIR",
        "pid_t",
        "pollfd",
        "regex_t",
        "sockaddr_storage",
        "BtrcGPUAsyncWaitOutcome",
    } <= HOSTED_PLATFORM_TYPE_NAMES
    assert {
        "environ",
        "in6addr_any",
        "optarg",
        "re_syntax_options",
        "tzname",
    } <= HOSTED_PLATFORM_OBJECT_NAMES
    assert {
        "BTRC_GPU_STORAGE",
        "EINVAL",
        "FILE_ATTRIBUTE_REPARSE_POINT",
        "O_CLOEXEC",
        "POLLIN",
        "WIFEXITED",
    } <= HOSTED_PLATFORM_MACROS


def test_platform_snapshot_contains_only_c_identifiers() -> None:
    for namespace in (
        HOSTED_PLATFORM_FUNCTION_NAMES,
        HOSTED_PLATFORM_TYPE_NAMES,
        HOSTED_PLATFORM_OBJECT_NAMES,
        HOSTED_PLATFORM_MACROS,
    ):
        assert namespace
        assert all(name.isascii() and name.isidentifier() for name in namespace)


def _unavailable(label: str, kind: str, name: str) -> bool:
    assert name in PLATFORM[kind], f"{name} is not a [platform] {kind[:-1]}"
    return name in getattr(UNAVAILABLE[label], kind)


def _manifest() -> HostedAbiManifest:
    return HostedAbiManifest.load(HOSTED_SPEC, RuntimeManifest.load(RUNTIME_SPEC))


# --- Every row has a table (platform-target-contract.md §2.2, §2.5) ---------------------------


def test_every_target_row_has_exactly_one_table() -> None:
    assert tuple(UNAVAILABLE) == LABELS
    assert len(LABELS) == 11
    for label, row in UNAVAILABLE.items():
        assert row.target == label
        assert row.source


def test_tables_are_subsets_of_platform_and_never_list_iso_c_or_runtime_names() -> None:
    runtime = {row.name for row in generated_abi.HOSTED_FUNCTION_ROWS if row.origin == "runtime"}
    iso_and_runtime = {
        "functions": set(generated_abi.HOSTED_FUNCTION_NAMES) - PLATFORM["functions"],
        "macros": set(generated_abi.HOSTED_MACRO_NAMES) - PLATFORM["macros"],
        "objects": set(generated_abi.HOSTED_OBJECT_NAMES) - PLATFORM["objects"],
        "types": set(generated_abi.HOSTED_TYPE_NAMES) - PLATFORM["types"],
        "typedefs": set(generated_abi.HOSTED_TYPEDEF_NAMES) - PLATFORM["typedefs"],
    }
    # ISO C names live in [names] only, so the subset rule alone keeps them off every row.
    assert {"malloc", "printf", "strlen", "fopen"} <= iso_and_runtime["functions"]
    assert not {"malloc", "printf", "strlen", "fopen"} & PLATFORM["functions"]
    for label, row in UNAVAILABLE.items():
        for kind in KINDS:
            listed = getattr(row, kind)
            assert listed <= PLATFORM[kind], (label, kind)
            assert not listed & iso_and_runtime[kind], (label, kind)
            assert not listed & runtime, (label, kind)
            assert not {name for name in listed if name.startswith(HostedAbiManifest.RUNTIME_PREFIXES)}, (label, kind)


def test_generated_tables_equal_the_spec_rows() -> None:
    document = tomllib.loads(HOSTED_SPEC.read_text())
    assert document["schema_version"] == 3
    rows = document["platform_targets"]
    assert [row["target"] for row in rows] == list(LABELS)
    for row in rows:
        generated = UNAVAILABLE[row["target"]]
        assert generated.source == row["source"]
        for kind in KINDS:
            assert row[f"unavailable_{kind}"] == sorted(getattr(generated, kind)), (row["target"], kind)


def test_apple_rows_record_the_pinned_xcode_extraction() -> None:
    """MAC-P1-05 uses the four rows extracted with pinned Xcode 27A266a and SDK 27.0."""

    for label in (*IOS, *MACOS):
        assert UNAVAILABLE[label].source.startswith("Xcode 27.0 (27A266a); "), label
        assert "27.0.sdk" in UNAVAILABLE[label].source, label
    assert UNAVAILABLE[MSVC].source == "conservative copy pending runner extraction"
    for label in (*LINUX, *ANDROID, "windows-aarch64", "windows-x86_64"):
        assert "extracted" in UNAVAILABLE[label].source, label


@pytest.mark.parametrize("field", (*KINDS, "source"))
def test_fingerprint_covers_the_availability_tables(field: str) -> None:
    manifest = _manifest()
    assert manifest.fingerprint == generated_abi.HOSTED_ABI_FINGERPRINT == HOSTED_ABI.fingerprint
    linux = next(row for row in manifest.platform_targets if row.target == "linux-x86_64")
    value = getattr(linux, field)
    changed_value = value + " (changed)" if field == "source" else value[:-1]
    changed = linux.__class__(**{**_row_fields(linux), field: changed_value})
    rows = tuple(changed if row is linux else row for row in manifest.platform_targets)
    assert manifest.__class__(**{**_fields(manifest), "platform_targets": rows}).fingerprint != manifest.fingerprint
    tables = (SOURCE_ROOT / "compiler/btrc/generated/hosted_abi/Tables.btrc").read_text()
    assert f'self.fingerprint = "{manifest.fingerprint}";' in tables


def _fields(manifest: HostedAbiManifest) -> dict[str, object]:
    return {
        name: getattr(manifest, name)
        for name in ("schema_version", "provenance", "limits", "names", "platform", "functions", "platform_targets")
    }


# --- Spot names (§2.5; fork replaced by clock_settime in batch 57: iOS declares fork) -----------


def test_ios_rows_refuse_clock_settime_that_macos_declares() -> None:
    for label in IOS:
        assert _unavailable(label, "functions", "clock_settime"), label
    for label in MACOS:
        assert not _unavailable(label, "functions", "clock_settime"), label


def test_windows_api_names_are_unavailable_on_every_non_windows_row() -> None:
    for label in LABELS:
        windows = label.startswith("windows-")
        assert _unavailable(label, "functions", "GetFileAttributesA") != windows, label


def test_arc4random_uniform_exists_on_apple_and_android_but_not_linux_gnu() -> None:
    for label in (*MACOS, *IOS, *ANDROID):
        assert not _unavailable(label, "functions", "arc4random_uniform"), label
    for label in LINUX:
        assert _unavailable(label, "functions", "arc4random_uniform"), label


def test_explicit_bzero_exists_on_linux_and_on_no_android_api_level() -> None:
    for label in LINUX:
        assert not _unavailable(label, "functions", "explicit_bzero"), label
    # Bionic in NDK r29 declares explicit_bzero at no API level.
    for label in ANDROID:
        assert _unavailable(label, "functions", "explicit_bzero"), label


def test_environ_exists_on_linux_and_not_on_the_msvc_row() -> None:
    for label in LINUX:
        assert not _unavailable(label, "objects", "environ"), label
    assert _unavailable(MSVC, "objects", "environ")


@pytest.mark.parametrize(
    ("kind", "name"),
    (
        ("macros", "PATH_MAX"),
        ("macros", "STDIN_FILENO"),
        ("macros", "S_ISDIR"),
        ("macros", "O_ACCMODE"),
        ("macros", "timerisset"),
        ("types", "timezone"),
        ("objects", "daylight"),
        ("objects", "tzname"),
    ),
)
def test_msvc_row_refuses_mingw_posix_additions(kind: str, name: str) -> None:
    assert _unavailable(MSVC, kind, name)
    # The gnu sibling declares them through MinGW-w64, so only the MSVC row refuses them.
    assert not _unavailable("windows-aarch64", kind, name)


def test_msvc_row_is_at_least_as_strict_as_its_gnu_sibling() -> None:
    for kind in KINDS:
        assert getattr(UNAVAILABLE["windows-aarch64"], kind) <= getattr(UNAVAILABLE[MSVC], kind), kind


# --- Generator rules fail closed ----------------------------------------------------------------


def _first(document: dict, label: str) -> dict:
    return next(row for row in document["platform_targets"] if row["target"] == label)


PLATFORM_TARGET_VIOLATIONS = {
    "iso-c": (
        lambda document: _first(document, "linux-x86_64").update(
            unavailable_functions=sorted({*_first(document, "linux-x86_64")["unavailable_functions"], "malloc"})
        ),
        r"unavailable_functions lists names outside platform.functions: \['malloc'\]",
    ),
    "runtime": (
        lambda document: _first(document, "linux-x86_64").update(
            unavailable_functions=sorted(
                {*_first(document, "linux-x86_64")["unavailable_functions"], "btrc_gpu_dispatch"}
            )
        ),
        r"lists btrc runtime names, which are ported, not filtered: \['btrc_gpu_dispatch'\]",
    ),
    "wrong-kind": (
        lambda document: _first(document, "linux-x86_64").update(unavailable_objects=["EINVAL"]),
        "unavailable_objects lists names outside platform.objects",
    ),
    "unsorted": (
        lambda document: _first(document, "linux-x86_64").update(
            unavailable_typedefs=list(reversed(_first(document, "linux-x86_64")["unavailable_typedefs"]))
        ),
        r"platform_targets\[5\]\.unavailable_typedefs must be sorted",
    ),
    "repeated": (
        lambda document: _first(document, "linux-x86_64").update(unavailable_objects=["environ", "environ"]),
        "must not contain duplicates",
    ),
    "empty-source": (
        lambda document: _first(document, "linux-x86_64").update(source=""),
        "source must be a non-empty string",
    ),
    "missing-kind": (
        lambda document: _first(document, "linux-x86_64").pop("unavailable_types"),
        "missing platform_targets.5. keys: unavailable_types",
    ),
    "duplicate-row": (
        lambda document: document["platform_targets"].insert(5, copy.deepcopy(_first(document, "linux-x86_64"))),
        "platform_targets lists target 'linux-x86_64' more than once",
    ),
    "out-of-order": (
        lambda document: document["platform_targets"].reverse(),
        "platform_targets must be listed in target order",
    ),
    "none": (lambda document: document.update(platform_targets=[]), "platform_targets must be a non-empty array"),
}


@pytest.mark.parametrize("violation", tuple(PLATFORM_TARGET_VIOLATIONS))
def test_platform_target_rules_fail_closed(violation: str, tmp_path: Path) -> None:
    mutate, message = PLATFORM_TARGET_VIOLATIONS[violation]
    document = tomllib.loads(HOSTED_SPEC.read_text())
    mutate(document)
    with pytest.raises(HostedAbiManifestError, match=message):
        _load(document, tmp_path)


def _load(document: dict, tmp_path: Path) -> HostedAbiManifest:
    """Load a mutated hosted spec through the generator's own reader."""

    path = tmp_path / "hosted_abi.toml"
    path.write_text(_toml(document))
    return HostedAbiManifest.load(path, RuntimeManifest.load(RUNTIME_SPEC))


def _toml(document: dict) -> str:
    """A minimal TOML writer for the hosted spec's shapes (tables, arrays of tables, scalars, arrays)."""

    def value(item: object) -> str:
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, int):
            return str(item)
        if isinstance(item, str):
            return '"' + item.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if isinstance(item, list):
            return "[" + ", ".join(value(element) for element in item) + "]"
        assert isinstance(item, dict)
        return "{ " + ", ".join(f"{key} = {value(element)}" for key, element in item.items()) + " }"

    lines = [f"{key} = {value(item)}" for key, item in document.items() if not isinstance(item, (dict, list))]
    lines += [f"{key} = {value(item)}" for key, item in document.items() if isinstance(item, list) and not item]
    for key, item in document.items():
        if isinstance(item, dict):
            lines.append(f"[{key}]")
            lines.extend(f"{name} = {value(element)}" for name, element in item.items())
        elif isinstance(item, list) and item:
            for table in item:
                lines.append(f"[[{key}]]")
                lines.extend(f"{name} = {value(element)}" for name, element in table.items())
    return "\n".join(lines) + "\n"


def test_toml_writer_round_trips_the_spec(tmp_path: Path) -> None:
    document = tomllib.loads(HOSTED_SPEC.read_text())
    assert _load(document, tmp_path).fingerprint == _manifest().fingerprint


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda rows: rows.pop(),
            r"hosted platform_targets lack a table for targets \['windows-x86_64'\]",
        ),
        (
            lambda rows: rows.append(rows[-1].__class__(**{**_row_fields(rows[-1]), "target": "windows-x86_64-msvc"})),
            r"hosted platform_targets name unknown targets \['windows-x86_64-msvc'\]",
        ),
    ),
)
def test_every_target_label_needs_exactly_one_table(mutate, message: str) -> None:
    """A missing extraction fails the generator, so no row can ship without a table."""

    manifest = _manifest()
    rows = list(manifest.platform_targets)
    mutate(rows)
    changed = manifest.__class__(**{**_fields(manifest), "platform_targets": tuple(rows)})
    with pytest.raises(HostedAbiManifestError, match=message):
        TargetManifest.load(TARGET_SPEC, changed)


def _row_fields(row: HostedAbiPlatformTargetSpec) -> dict[str, object]:
    return {name: getattr(row, name) for name in ("target", *KINDS, "source")}


# --- The self-hosted tables (GeneratedHostedAbiData.platformUnavailable) -------------------------


@pytest.fixture(scope="module")
def platform_driver(selfhost_driver) -> Path:
    return selfhost_driver(DRIVER, compile_flags=("-pedantic-errors",))


def test_self_hosted_tables_equal_the_reference_tables(platform_driver: Path) -> None:
    result = subprocess.run(
        [str(platform_driver), *LABELS, "linux-x86_64", "riscv64-linux"],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    names: dict[tuple[str, str], set[str]] = {}
    sources: dict[str, list[str]] = {}
    missing = []
    for line in result.stdout.splitlines():
        label, kind, *rest = line.split(" ", 2)
        assert kind != "not", line  # "LABEL not memoized"
        if kind == "missing":
            missing.append(label)
        elif kind == "source":
            sources.setdefault(label, []).append(rest[0])
        else:
            names.setdefault((label, kind), set()).add(rest[0])
    assert missing == ["riscv64-linux"]
    assert {label: values for label, values in sources.items()} == {
        label: [UNAVAILABLE[label].source] * (2 if label == "linux-x86_64" else 1) for label in LABELS
    }
    for label in LABELS:
        for kind in KINDS:
            assert names.get((label, kind), set()) == set(getattr(UNAVAILABLE[label], kind)), (label, kind)
