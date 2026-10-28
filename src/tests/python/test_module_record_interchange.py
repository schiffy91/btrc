"""The two module cache readers exchange the same metadata without conversion."""

import hashlib
import json
import platform
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import (
    ModuleUnitCompiler,
    ModuleUnitGraph,
    ModuleUnitRecord,
    ProgramInterface,
    SharedDeclarations,
)
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache
from src.compiler.python.frontend.packages import NativeLinkPlan, PackageTarget
from src.compiler.python.frontend.sources import ResolvedSource, SourceDependencyGraph, SourceDependencyKind
from src.compiler.python.frontend.stage import FrontendStage
from src.compiler.python.ir.lowering.exceptions import FunctionEffect, ParameterEffect
from src.compiler.python.ir.nodes import CType, IRFunctionDecl, IRModule
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.codec import AstCanonicalRenderer
from src.compiler.python.syntax.ast.generated import FloatLiteral

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
        declaration_roots=("Alias", "external", "unknown"),
        declaration_digest="a" * 64,
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
    stored = [
        path
        for path in cache.glob("modules-v1/*/record.txt")
        if path.read_text().split("\n", 3)[3].startswith("btrc-module-unit-record\t")
    ]
    assert len(stored) == len(cold.module_units_lowered)
    for path in stored:
        header, key, hashes, metadata = path.read_text().split("\n", 3)
        group = metadata.split("\n")[1].removeprefix("group\t")
        input_path = root / "record.txt"
        input_path.write_text(metadata)
        result = _driver(module_record_driver, "read", input_path, group)
        assert result.returncode == 0, result.stderr
        assert result.stdout == metadata + "\n"
        metadata = result.stdout[:-1]
        hashes = hashlib.sha256(metadata.encode()).hexdigest() + " " + hashes.split(" ")[1]
        path.write_text("\n".join((header, key, hashes, metadata)))
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
        ("record\t6", "record\t5"),
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
        ("declaration-roots\tAlias", "declaration-roots\tAlias\tAlias"),
        ("declaration-digest\t" + "a" * 64, "declaration-digest\tbad"),
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


@pytest.mark.parametrize(
    "damage", ["record", "text", "record-encoding", "text-encoding", "truncated", "missing", "old-layout", "key"]
)
def test_module_cache_verifies_both_payloads(tmp_path, monkeypatch, damage):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    record = _record()
    cache = CompilerCache()
    cache.store_module_unit("identity", record.to_text(), record.text)
    assert cache.load_module_unit("identity") == (record.to_text(), record.text)
    path = next(tmp_path.glob("modules-v1/*/record.txt"))
    unit = path.with_name("unit.c")
    if damage == "record":
        path.write_bytes(path.read_bytes() + b"corrupt")
    elif damage == "text":
        unit.write_bytes(unit.read_bytes() + b"corrupt")
    elif damage == "record-encoding":
        path.write_bytes(path.read_bytes() + b"\xff")
    elif damage == "text-encoding":
        unit.write_bytes(b"\xff")
    elif damage == "missing":
        unit.unlink()
    elif damage == "old-layout":
        path.write_text(record.to_text())
    elif damage == "key":
        path.write_text(path.read_text().replace(path.parent.name, "0" * 64, 1))
    else:
        path.write_text(path.read_text()[:10])
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


def _interface(source):
    program = Parser(Lexer(source).tokenize()).parse()
    return {
        "text": AstCanonicalRenderer.interface_renderer(ProgramInterface.callable_body).render(program),
        "digest": ProgramInterface().digest(program.declarations),
    }


@pytest.mark.parametrize(
    "source",
    [
        "int answer(int count = 3) { return count + 1; }",
        "extern int answer(int count);",
        "class Item { public int value { get; set; } public int read() { return 7; } }",
        "class Item { public int value { get { return 7; } set { print(value); } } }",
        "class Box<T> { public T value; public T get() { return self.value; } }",
        "class Box { public U choose<U>(U left, U right) { return left; } }",
        "void consume(Item first, Item second) { delete second; delete first; return; }",
        "struct Record { int values[3]; double coefficient; }; enum Choice { FIRST, SECOND = 5 };",
        "typedef int (*Callback)(double); unsigned long long count = 18446744073709551615ULL;",
        "long long count = 9223372036854775807LL; unsigned int mask = 0xffffffffU;",
        "double precise = 1.0000000000000002; double tiny = 5e-324;",
        'string title = "café\\n\\t\\"module\\"";',
    ],
)
def test_declaration_interfaces_match_between_frontends(tmp_path, module_record_driver, source):
    path = tmp_path / "Interface.btrc"
    path.write_text(source)
    result = _driver(module_record_driver, "interface", path, "unused")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == _interface(source)


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize(
    ("source", "before", "after", "same"),
    [
        ("int answer() { return 7; }", "7", "8", True),
        ("int answer() { return 7; }", "int answer", "\n\nint answer", True),
        ("int answer(int value) { return value; }", "int value", "long value", False),
        ("int answer(int value = 7) { return value; }", "= 7", "= 8", False),
        ("int answer();", ";", " { return 7; }", False),
        ("void consume(Item item) {}", "{}", "{ delete item; }", False),
        ("void consume(Item item) { delete item; }", "delete item;", "print(item);", False),
        ("class Item { public int value { get { return 7; } } }", "7", "8", True),
        ("class Item { public int value { get; } }", "get;", "get { return 7; }", False),
        ("class Box<T> { public int get() { return 7; } }", "7", "8", False),
        ("class Box<T> { public int value { get { return 7; } } }", "7", "8", False),
        ("class Item { public U choose<U>(U left, U right) { return left; } }", "return left", "return right", False),
        ("double precise = 1.0000000000000002;", "1.0000000000000002", "1.0000000000000004", False),
        ("unsigned long long count = 18446744073709551615ULL;", "18446744073709551615", "18446744073709551614", False),
    ],
)
def test_interface_invalidation_contract(tmp_path, request, frontend, source, before, after, same):
    digests = []
    for text in (source, source.replace(before, after)):
        expected = _interface(text)
        if frontend == "selfhost":
            path = tmp_path / "Interface.btrc"
            path.write_text(text)
            result = _driver(request.getfixturevalue("module_record_driver"), "interface", path, "unused")
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout) == expected
        digests.append(expected["digest"])
    assert (digests[0] == digests[1]) == same


@pytest.mark.parametrize(
    "value",
    ["0.0", "-0.0", "1.0000000000000002", "1.0000000000000004", "1e100", "1e-100", "5e-324", "inf", "-inf", "nan"],
)
def test_position_free_float_keeps_binary64_precision(module_record_driver, value):
    literal = FloatLiteral(value=float(value), raw="")
    expected = AstCanonicalRenderer.position_free_renderer().render(literal)
    result = _driver(module_record_driver, "float", value, "unused")
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected + "\n"


def test_interface_identity_does_not_use_rounded_display_values():
    first = FloatLiteral(value=1.0000000000000002, raw="")
    second = FloatLiteral(value=1.0000000000000004, raw="")
    assert AstCanonicalRenderer().render(first) == AstCanonicalRenderer().render(second)
    assert ProgramInterface().digest([first]) != ProgramInterface().digest([second])


class _InterfaceStore:
    def __init__(self, records):
        self.records = {key: list(value) for key, value in records.items()}
        self.writes = []

    def load_module_unit(self, identity, input_path=None):
        return self.records.get(identity)

    def store_module_unit(self, identity, record, text, input_path=None):
        self.records[identity] = [record, text]
        self.writes.append(identity)


def _grouped_input(root):
    return {
        "use_cache": True,
        "strict_imports": True,
        "include_stdlib": True,
        "stdlib_strict": False,
        "target": "linux-x86_64",
        "lines": [
            [str(root.parent / "café:Module.btrc"), 1, "int answer() { return 7; }"],
            [str(root), 1, "int main() { return 0; }"],
        ],
        "stdlib": "class InlineItem { public int value; }",
        "native": "extern int nativeValue();",
        "other": "int generatedValue = 2;",
        "native_identity": "native-v1",
        "records": {},
    }


def _reference_grouped(data, root, *, split=False):
    options = CompilerOptions(
        **{key: data[key] for key in ("use_cache", "strict_imports", "include_stdlib", "stdlib_strict")}
    )
    user_source = "\n".join(row[2] for row in data["lines"])
    stdlib = data["stdlib"]
    graph = SourceDependencyGraph()
    graph.ensure_source(str(root))
    for path, _, _ in data["lines"]:
        if path != str(root):
            graph.add(str(root), path, SourceDependencyKind.IMPORT)
    native = Parser(Lexer(data["native"]).tokenize()).parse().declarations
    source = ResolvedSource(
        user_source=user_source,
        source=stdlib + "\n" + user_source if stdlib else user_source,
        stdlib_source=stdlib,
        source_positions=tuple((path, line) for path, line, _ in data["lines"]),
        graph=graph,
        strict_imports=data["strict_imports"],
        root_source_path=str(root),
        native_plan=NativeLinkPlan.empty(PackageTarget.parse(data["target"])),
        native_declarations=tuple(native),
        native_cache_identity=data["native_identity"] or None,
    )
    parsed = FrontendStage().parse(source, str(root), use_ast_cache=split)
    others = Parser(Lexer(data["other"]).tokenize()).parse().declarations
    for declaration in others:
        declaration.line = 0
    parsed.program.declarations.extend(others)
    store = _InterfaceStore(data["records"])
    digest = ProgramInterface().capture(
        parsed.program.declarations,
        source,
        options,
        inline_stdlib_declarations=parsed.inline_stdlib_declarations,
        store=store,
    )
    return {
        "digest": digest,
        "validation_digest": digest,
        "context": ProgramInterface.context(options, data["target"]),
        "records": store.records,
        "writes": sorted(store.writes),
    }


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize(
    "change",
    [
        "none",
        "body",
        "signature",
        "native",
        "stdlib",
        "other",
        "move",
        "target",
        "stdlib-strict",
        "no-cache",
        "malformed",
        "split",
    ],
)
def test_grouped_interfaces_share_cache_and_invalidation(tmp_path, request, monkeypatch, frontend, change):
    root = tmp_path.resolve() / "Main.btrc"
    data = _grouped_input(root)
    if change == "split":
        data["strict_imports"] = False
    cold = _reference_grouped(data, root, split=change == "split")
    assert len(cold["writes"]) == 4  # two source groups, inline stdlib, native
    data["records"] = cold["records"]
    if change == "body":
        data["lines"][0][2] = data["lines"][0][2].replace("return 7", "return 8")
    elif change == "signature":
        data["lines"][0][2] = data["lines"][0][2].replace("int answer", "long answer")
    elif change == "native":
        data["native"] = data["native"].replace("int nativeValue", "long nativeValue")
        data["native_identity"] = "native-v2"
    elif change == "stdlib":
        data["stdlib"] = data["stdlib"].replace("int value", "long value")
    elif change == "other":
        data["other"] = data["other"].replace("= 2", "= 3")
    elif change == "move":
        data["lines"].reverse()
    elif change == "target":
        data["target"] = "windows-x86_64"
    elif change == "stdlib-strict":
        data["stdlib_strict"] = True
    elif change == "no-cache":
        data["use_cache"] = False
    elif change == "malformed":
        key = next(iter(data["records"]))
        data["records"][key] = [data["records"][key][0], "z" * 64]
    rendered = []
    original = AstCanonicalRenderer.render

    def observe(renderer, node):
        if renderer._callable_body is not None:
            rendered.append(getattr(node, "name", ""))
        return original(renderer, node)

    monkeypatch.setattr(AstCanonicalRenderer, "render", observe)
    expected = _reference_grouped(data, root, split=change == "split")
    changed = change in {"signature", "native", "stdlib", "other"}
    assert (cold["digest"] != expected["digest"]) == changed
    if change in {"none", "move", "split"}:
        assert not expected["writes"]
        assert rendered == ["generatedValue"]
    if change == "body":
        assert len(expected["writes"]) == 1
        assert rendered == ["answer", "generatedValue"]
    if change == "no-cache":
        assert not expected["writes"]
        assert len(rendered) == 5
    if frontend == "selfhost":
        path = tmp_path / "input.json"
        path.write_text(json.dumps(data))
        result = _driver(request.getfixturevalue("module_record_driver"), "grouped", path, str(root))
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == expected


def test_pipeline_captures_interfaces_before_analysis(tmp_path, monkeypatch):
    from src.compiler.python.application.pipeline import CompilationPipeline

    events = []
    capture = ProgramInterface.capture
    analyze = CompilationPipeline.analyze
    compile_units = ModuleUnitCompiler.compile

    def capture_before(self, *args, **kwargs):
        digest = capture(self, *args, **kwargs)
        events.append(("capture", digest))
        return digest

    def analyze_after(self, *args, **kwargs):
        assert events and events[-1][0] == "capture"
        events.append(("analyze", None))
        return analyze(self, *args, **kwargs)

    def lower_after(self, *args, **kwargs):
        assert events[-1][0] == "analyze"
        assert kwargs["interface_digest"] == events[-2][1]
        return compile_units(self, *args, **kwargs)

    monkeypatch.setattr(ProgramInterface, "capture", capture_before)
    monkeypatch.setattr(CompilationPipeline, "analyze", analyze_after)
    monkeypatch.setattr(ModuleUnitCompiler, "compile", lower_after)
    result = Compiler().compile(
        "int main() { return 0; }",
        str(tmp_path / "Main.btrc"),
        CompilerOptions(
            include_stdlib=False, use_cache=False, module_units=True, units_prefix=str(tmp_path / "program")
        ),
    )
    assert result.successful, result.failure
    assert [kind for kind, _ in events] == ["capture", "analyze"]


def test_production_pipelines_share_interface_records_across_edit_builds(tmp_path, monkeypatch, module_record_driver):
    root = tmp_path.resolve()
    main = root / "Main.btrc"
    shared = root / "Shared.btrc"
    main.write_text('import "Shared.btrc";\nint main() { return answer() - 7; }\n')
    shared.write_text("int answer() { return 7; }\n")
    cache = root / "cache"
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache))
    compiler = Compiler(cache=CompilerCache())
    reference_records = {}
    store_record = CompilerCache.store_module_unit

    def observe_record(self, identity, record, text, input_path=None):
        if record == "validation-interface-v2":
            reference_records[identity] = [record, text]
        return store_record(self, identity, record, text, input_path)

    monkeypatch.setattr(CompilerCache, "store_module_unit", observe_record)
    records = {}
    previous = None
    for phase, counts in (("cold", (2, 0)), ("warm", (0, 2)), ("edit", (1, 1)), ("no-cache", (2, 0))):
        if phase == "edit":
            shared.write_text("int answer() { return 8; }\n")
        options = CompilerOptions(
            include_stdlib=False, module_units=True, units_prefix=str(root / phase), use_cache=phase != "no-cache"
        )
        expected = compiler.compile(main.read_text(), str(main), options)
        assert expected.successful, expected.failure
        assert (len(expected.module_units_lowered), len(expected.module_units_reused)) == counts
        data = {"prefix": options.units_prefix, "use_cache": options.use_cache, "records": records}
        path = root / "pipeline.json"
        path.write_text(json.dumps(data))
        completed = _driver(module_record_driver, "pipeline", path, str(main))
        assert completed.returncode == 0, completed.stderr
        actual = json.loads(completed.stdout)
        assert (actual["lowered"], actual["reused"]) == counts
        records = actual["records"]
        selfhost_records = {key: value for key, value in records.items() if value[0] == "validation-interface-v2"}
        assert selfhost_records == reference_records
        if phase == "warm":
            assert (actual["output"], actual["units"]) == previous
        if phase == "no-cache":
            assert (actual["output"], actual["units"]) == previous
        previous = actual["output"], actual["units"]


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("edit", ["addition", "signature", "transitive", "include-cycle", "macro", "tuple"])
def test_module_interface_edit_reuses_unrelated_group(tmp_path, monkeypatch, request, frontend, edit):
    root = tmp_path.resolve()
    main, alpha, beta = (root / name for name in ("Main.btrc", "Alpha.btrc", "Beta.btrc"))
    main.write_text('import "Alpha.btrc";\nimport "Beta.btrc";\nint main() { return alpha() + beta() - 3; }\n')
    alpha.write_text("int alpha() { return 1; }\n")
    beta.write_text("int beta() { return 2; }\n")
    changed = alpha
    if edit == "transitive":
        changed = root / "Leaf.btrc"
        alpha.write_text('import "Leaf.btrc";\nint alpha() { return leaf(); }\n')
        changed.write_text("int leaf() { return 1; }\n")
    elif edit == "include-cycle":
        changed = root / "Part.btrc"
        alpha.write_text('#include "Part.btrc"\nint alpha() { return leaf(); }\n')
        changed.write_text("int leaf() { return 1; }\n")
    elif edit == "macro":
        alpha.write_text("#define FACTOR 1\nint alpha() { return FACTOR; }\n")
    elif edit == "tuple":
        alpha.write_text('int alpha() { (int, string) pair = (1, "a"); return pair._0; }\n')
        beta.write_text("int beta() { (double, int) pair = (0.5, 2); return pair._1; }\n")
    monkeypatch.setenv("BTRC_CACHE_DIR", str(root / "cache"))
    compiler = Compiler(cache=CompilerCache())
    binary = request.getfixturevalue("module_record_driver") if frontend == "selfhost" else None
    records = {}

    def compile_phase(phase, use_cache=True):
        nonlocal records
        if frontend == "reference":
            options = CompilerOptions(
                include_stdlib=False, module_units=True, units_prefix=str(root / phase), use_cache=use_cache
            )
            result = compiler.compile(main.read_text(), str(main), options)
            assert result.successful, result.failure
            return len(result.module_units_lowered), len(result.module_units_reused), (result.c_source, result.c_units)
        path = root / "pipeline.json"
        path.write_text(json.dumps({"prefix": str(root / phase), "use_cache": use_cache, "records": records}))
        completed = _driver(binary, "pipeline", path, str(main))
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        records = result["records"]
        return result["lowered"], result["reused"], (result["output"], result["units"])

    count = 4 if edit == "transitive" else 3
    cold = compile_phase("cold")
    assert cold[:2] == (count, 0)
    warm = compile_phase("warm")
    assert warm[:2] == (0, count)
    assert warm[2] == cold[2]
    if edit == "signature":
        alpha.write_text("int alpha(int value = 1) { return value; }\n")
    elif edit == "macro":
        alpha.write_text("#define FACTOR 2\nint alpha() { return FACTOR; }\n")
    elif edit == "tuple":
        alpha.write_text(
            'int alpha() { (int, string) pair = (1, "a"); (int, int) extra = (2, 3); return pair._0 + extra._1; }\n'
        )
    else:
        changed.write_text(changed.read_text() + "int extra() { return 4; }\n")
    edited = compile_phase("edited")
    expected_counts = (count, 0) if edit == "macro" else (1, count - 1) if edit == "tuple" else (count - 1, 1)
    assert edited[:2] == expected_counts
    uncached = compile_phase("uncached", False)
    assert uncached[:2] == (count, 0)
    assert edited[2] == uncached[2]


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_declaration_certificate_checks_content_order_and_new_providers(tmp_path, request, frontend):
    binary = request.getfixturevalue("module_record_driver") if frontend == "selfhost" else None
    roots = ["left", "right", "unknown"]

    def digest(declarations):
        if frontend == "reference":
            unit = IRModule(function_decls=[IRFunctionDecl(name, CType(kind)) for name, kind in declarations])
            return SharedDeclarations(unit).dependency_digest(roots)
        path = tmp_path / "dependencies.json"
        path.write_text(
            json.dumps({"roots": roots, "declarations": [{"name": name, "type": kind} for name, kind in declarations]})
        )
        completed = _driver(binary, "dependencies", path, "unused")
        assert completed.returncode == 0, completed.stderr
        return completed.stdout.strip()

    original = [("left", "int"), ("right", "int")]
    baseline = digest(original)
    assert digest([("unrelated", "int"), *original]) == baseline
    assert digest([("left", "long"), ("right", "int")]) != baseline
    assert digest(list(reversed(original))) != baseline
    assert digest([*original, ("unknown", "int")]) != baseline
