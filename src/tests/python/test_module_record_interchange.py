"""The two module cache readers exchange the same metadata without conversion."""

import hashlib
import json
import platform
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import ModuleUnitCompiler, ModuleUnitGraph, ModuleUnitRecord
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache
from src.compiler.python.ir.lowering.exceptions import FunctionEffect, ParameterEffect

ROOT = Path(__file__).resolve().parents[3]


def _record(group="/work/Module.btrc"):
    return ModuleUnitRecord(
        group=group,
        text="int marker;\n",
        kept=True,
        exports=("entry", "genericA"),
        has_setjmp=True,
        effects_solved=True,
        exported_effects={
            "entry": FunctionEffect(
                frozenset({ParameterEffect(2, 1), ParameterEffect(10, 1), ParameterEffect(0, 2)}),
                frozenset({ParameterEffect(1, 0)}),
                frozenset({ParameterEffect(2147483647, 2147483647)}),
                True,
            )
        },
        consulted_effects={"external": FunctionEffect()},
        releases_cyclable=True,
        defines_entry=True,
        program_release=True,
        helpers=("__btrc_arc_release",),
        realtime_roots=("entry",),
        realtime_proofs={"entry": ("external", "genericA"), "genericA": ()},
        consulted_sources={"/work/imported.btrc": "abc123"},
        graph=ModuleUnitGraph({"entry": ("genericA",), "genericA": ("external",)}, ("entry",), frozenset({"genericA"})),
        kept_instances=frozenset({"genericA"}),
    )


@pytest.fixture(scope="module")
def module_record_driver(selfhost_driver):
    flags = ["-O0", "-pedantic-errors", "-Wall", "-Wextra", "-Werror"]
    if platform.system() == "Darwin":
        flags.append("-Wl,-stack_size,0x20000000")
    return selfhost_driver(ROOT / "src/tests/btrc/fixtures/ModuleRecordDriver.btrc", compile_flags=flags)


def _driver(binary, mode, path, group):
    return subprocess.run([str(binary), mode, str(path), group], capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("group", ["/work/Module.btrc", "/work/space é/模块.btrc", '/work/colon:pipe|quote".btrc'])
def test_module_records_exchange_without_conversion(tmp_path, module_record_driver, group):
    record = _record(group)
    path = tmp_path / "record.txt"
    path.write_text(record.to_text())
    read = _driver(module_record_driver, "read", path, group)
    assert read.returncode == 0, read.stderr
    assert read.stdout == record.to_text() + "\n"
    made = _driver(module_record_driver, "make", path, group)
    assert made.returncode == 0, made.stderr
    assert made.stdout == read.stdout
    assert ModuleUnitRecord.from_text(made.stdout[:-1], record.text, group) == record


def test_reference_cache_replays_selfhost_reencoded_records(tmp_path, monkeypatch, module_record_driver):
    root = tmp_path.resolve()
    cache = root / "cache"
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache))
    source = root / "Main.btrc"
    source.write_text('import "Shared.btrc";\nint main() { return square(3) - 9; }\n')
    (root / "Shared.btrc").write_text("int square(int value) { return value * value; }\n")
    options = CompilerOptions(include_stdlib=False, module_units=True, units_prefix=str(root / "program"))
    compiler = Compiler(cache=CompilerCache())
    cold = compiler.compile(source.read_text(), str(source), options)
    assert cold.failure is None, cold.failure
    assert cold.module_units_lowered and not cold.module_units_reused
    stored = list(cache.glob("*.module.json"))
    assert len(stored) == len(cold.module_units_lowered)
    for path in stored:
        envelope = json.loads(path.read_text())
        metadata = envelope["record"]
        group = metadata.split("\n")[1].removeprefix("group\t")
        input_path = root / "record.txt"
        input_path.write_text(metadata)
        result = _driver(module_record_driver, "read", input_path, group)
        assert result.returncode == 0, result.stderr
        assert result.stdout == metadata + "\n"
        envelope["record"] = result.stdout[:-1]
        envelope["sha256"] = hashlib.sha256(envelope["record"].encode()).hexdigest()
        path.write_text(json.dumps(envelope))
    # A new output path bypasses the complete-generation cache while retaining
    # the release-mode module identities, so this must exercise record replay.
    warm = compiler.compile(source.read_text(), str(source), replace(options, units_prefix=str(root / "warm")))
    assert warm.failure is None, warm.failure
    assert not warm.module_units_lowered
    assert set(warm.module_units_reused) == set(cold.module_units_lowered)
    assert warm.c_source == cold.c_source and warm.c_units == cold.c_units


@pytest.mark.parametrize("frontend", ["python", "btrc"])
@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("record\t5", "record\t4"),
        ("flags\t1", "flags\ttrue"),
        ("@exported-effects\t1", "@exported-effects\t-1"),
        ("@exported-effects\t1", "@exported-effects\t01"),
        ("@exported-effects\t1", "@exported-effects\t1junk"),
        ("@exported-effects\t1", "@exported-effects\t2147483647"),
        ("@exported-effects\t1", "@exported-effects\t2147483648"),
        ("@exported-effects\t1", "@exported-effects\t1\t0"),
        ("0:2", "-1:2"),
        ("0:2", "0:2,0:2"),
        ("0:2", "0:02"),
        ("0:2", "junk:2"),
        ("0:2", "2147483648:2"),
        ("genericA\texternal", "genericA\t"),
        ("graph-instances\tgenericA", "graph-instances\tgenericA\tgenericA"),
        ("graph-instances\tgenericA", "graph-instances\tgenericA\tmissing"),
        ("kept-instances\tgenericA", "kept-instances\tmissing"),
        ("kept-instances\tgenericA", "kept-instances\tgenericA\tgenericA"),
        ("/work/imported.btrc\tabc123", "/work/imported.btrc\t"),
        ("@consulted-sources\t1", "@consulted-sources\t0"),
        ("@consulted-effects\t1\nexternal\t|||0", "@consulted-effects\t2\nexternal\t|||0\nexternal\t|||0"),
    ],
)
def test_both_record_readers_reject_malformed_metadata(tmp_path, request, frontend, before, after):
    record = _record()
    original = record.to_text()
    assert before in original
    metadata = original.replace(before, after)
    if frontend == "python":
        assert ModuleUnitRecord.from_text(metadata, record.text, record.group) is None
    else:
        binary = request.getfixturevalue("module_record_driver")
        path = tmp_path / "record.txt"
        path.write_text(metadata)
        result = _driver(binary, "read", path, record.group)
        assert result.returncode == 2, (result.stdout, result.stderr)


@pytest.mark.parametrize("damage", ["record", "text", "record-type", "text-type", "truncated", "missing", "old-layout"])
def test_module_cache_verifies_both_payloads(tmp_path, monkeypatch, damage):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    record = _record()
    cache = CompilerCache()
    cache.store_module_unit("identity", record.to_text(), record.text)
    assert cache.load_module_unit("identity") == (record.to_text(), record.text)
    path = next(tmp_path.glob("*.module.json"))
    value = json.loads(path.read_text())
    if damage in {"record", "text"}:
        value[damage] += "corrupt"
    elif damage.endswith("-type"):
        value[damage.removesuffix("-type")] = 42
    elif damage == "missing":
        del value["text-sha256"]
    elif damage == "old-layout":
        del value["text"]
        del value["text-sha256"]
    path.write_text(json.dumps(value) if damage != "truncated" else "{")
    assert cache.load_module_unit("identity") is None


@pytest.mark.parametrize("group", ["/work/tab\t.btrc", "/work/line\n.btrc", ""])
def test_unrepresentable_group_forgoes_cache(tmp_path, monkeypatch, group):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    record = replace(_record(), group=group)
    assert record.to_text() == ""
    cache = CompilerCache()
    cache.store_module_unit("identity", record.to_text(), record.text)
    assert cache.load_module_unit("identity") is None


def _key_input(path):
    return {
        "debug": False,
        "dce": True,
        "strict_imports": True,
        "include_stdlib": True,
        "stdlib_strict": False,
        "target": "macos-aarch64",
        "units_prefix": "/output/program",
        "generated_c_path": "/output/program.c",
        "native_defines": {"SECOND": "2", "FIRST": "1"},
        "lines": [[str(path), 1, "int value = 7;"], [str(path), 2, ""]],
        "program": "interface-and-program-facts",
    }


def _reference_keys(data, group):
    options = CompilerOptions(
        **{
            name: data[name]
            for name in (
                "debug",
                "dce",
                "strict_imports",
                "include_stdlib",
                "stdlib_strict",
                "units_prefix",
                "generated_c_path",
            )
        }
    )
    context = ModuleUnitCompiler._cache_context(options, data["target"], tuple(data["native_defines"].items()))
    digest = hashlib.sha256()
    groups = {}
    for path, line, text in data["lines"]:
        ModuleUnitCompiler._append_source_line(digest, path, line, text)
        ModuleUnitCompiler._append_source_line(groups.setdefault(path, hashlib.sha256()), path, line, text)
    source = digest.hexdigest()
    return {
        "context": context,
        "source": source,
        "key": ModuleUnitCompiler._cache_key(context, group, source, data["program"]),
        "validation": {name: digest.hexdigest() for name, digest in groups.items()},
    }


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "debug",
        "dce",
        "strict_imports",
        "include_stdlib",
        "stdlib_strict",
        "target",
        "define",
        "define-order",
        "release-path",
        "debug-path",
        "text",
        "line",
        "source-path",
        "source-order",
        "unicode",
        "program",
        "empty-source",
    ],
)
def test_module_key_inputs_match_between_frontends(tmp_path, module_record_driver, change):
    path = tmp_path.resolve() / "Main.btrc"
    path.write_text("")
    group = str(path)
    data = _key_input(path)
    baseline = _reference_keys(data, group)
    if change in {"debug", "dce", "strict_imports", "include_stdlib", "stdlib_strict"}:
        data[change] = not data[change]
    elif change == "target":
        data["target"] = "linux-x86_64"
    elif change == "define":
        data["native_defines"]["FIRST"] = "value;define=OTHER:é"
    elif change == "define-order":
        data["native_defines"] = dict(reversed(list(data["native_defines"].items())))
    elif change in {"release-path", "debug-path"}:
        data["debug"] = change == "debug-path"
        data["units_prefix"] = "/output/é;output=elsewhere"
        data["generated_c_path"] = "/output/模块.c"
    elif change == "text":
        data["lines"][0][2] = "int value = 9;"
    elif change == "line":
        data["lines"][0][1] = 2147483647
    elif change == "source-path":
        other = tmp_path.resolve() / "Imported.btrc"
        other.write_text("")
        data["lines"][0][0] = str(other)
    elif change == "source-order":
        data["lines"].reverse()
    elif change == "unicode":
        data["lines"][0][2] = 'string label = "é\t模块";'
    elif change == "program":
        data["program"] = "changed-interface-and-facts"
    elif change == "empty-source":
        data["lines"] = []
    expected = _reference_keys(data, group)
    assert (expected["key"] == baseline["key"]) == (change in {"none", "define-order", "release-path"})
    input_path = tmp_path / "keys.json"
    input_path.write_text(json.dumps(data))
    result = _driver(module_record_driver, "keys", input_path, group)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


def test_source_fields_cannot_shift_across_delimiters():
    # These distinct records collided under tab-separated source hashing.
    records = [("/work/path\t1", 2, "body"), ("/work/path", 1, "2\tbody")]
    old = [f"{path}\t{line}\t{text}\n" for path, line, text in records]
    assert old[0] == old[1]
    digests = []
    for path, line, text in records:
        digest = hashlib.sha256()
        ModuleUnitCompiler._append_source_line(digest, path, line, text)
        digests.append(digest.hexdigest())
    assert digests[0] != digests[1]


@pytest.mark.parametrize(
    ("group", "slug"),
    [
        ("/work/Module.btrc", "Module"),
        ("/work/éModule.btrc", "Module"),
        ("/work/模块.btrc", "group"),
        ("/work/SomeéName.btrc", "Some--Name"),
        ("/work/--Module--.btrc", "Module"),
        ("/work/.btrc", "group"),
        (r"C:\work\Module.btrc", "Module"),
        ("/work/Upper.BTRC", "Upper-BTRC"),
    ],
)
def test_module_output_names_match_between_frontends(module_record_driver, group, slug):
    expected = f"unit-{slug}-{hashlib.sha256(group.encode()).hexdigest()[:12]}"
    assert ModuleUnitCompiler.unit_name(group) == expected
    result = _driver(module_record_driver, "name", "unused", group)
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected + "\n"
