"""Correctness and complexity contracts for self-hosted member lookup."""

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _run,
    _strict_build_and_run,
)

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def _function(source: str, signature: str) -> str:
    start = source.index(signature)
    first_line = source[start : source.index("\n", start)]
    if first_line.rstrip().endswith("}"):
        return first_line
    end = source.index("\n    }", start)
    return source[start:end]


def test_member_queries_use_complete_constant_time_indexes() -> None:
    # These are semantic source-shape contracts, not indentation-style
    # contracts. Canonicalize tabs solely for the bounded method slices below.
    analyzer = (SELFHOST / "analyzer/Models.btrc").read_text().expandtabs(4)
    index = (SELFHOST / "analyzer/Declarations.btrc").read_text().expandtabs(4)
    types = (SELFHOST / "analyzer/Types.btrc").read_text().expandtabs(4)
    analyzer_stage = (SELFHOST / "analyzer/Stage.btrc").read_text().expandtabs(4)

    for signature in (
        "    public Node? classMember(",
        "    public Node? classMethod(",
        "    public Node? classConstructor(",
        "    public Node? genericClassMethod(",
        "    public Node? genericClassConstructor(",
    ):
        query = _function(analyzer, signature)
        assert ".members" not in query
        assert "while (" not in query
        assert "Index.has(" in query

    generic_query = _function(types, "    class Node? genericMember(")
    assert ".members" not in generic_query
    assert "while (" not in generic_query
    assert "Analyzed.memberKey(" in generic_query
    assert "genericMemberIndex.has(" in generic_query

    registration_end = index.index("/* Canonical physical storage")
    assert index.index("self.indexAnalyzedMembers(self.analyzed);") < registration_end
    assert "analyzed.memberIndexReady = true;" in index
    assert "import ./Models.btrc;" in analyzer_stage
    assert "import ./Types.btrc;" in analyzer_stage
    assert "import ./Declarations.btrc;" in analyzer_stage
    assert "#include" not in analyzer_stage


def test_indexed_method_namespace_ignores_child_value_member(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Base {
            public int action() { return 42; }
        }
        class Child extends Base {
            public int action;
            public Child() { self.action = 0; }
        }
        int main() {
            Child value = new Child();
            int result = value.action();
            delete value;
            return result == 42 ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "indexed-member-namespace")


def test_native_class_queries_do_not_scan_sdk_declarations() -> None:
    models = (SELFHOST / "analyzer/Models.btrc").read_text().expandtabs(4)
    for signature in ("    public string nativeClassLanguage(", "    public bool isSubclass("):
        assert "self.nativeDeclarations" not in _function(models, signature)
    analyzer = (SELFHOST / "analyzer/Analyzer.btrc").read_text()
    assert "self.analysis.setNativeDeclarations(declarations);" in analyzer


@pytest.mark.parametrize("frontend", ("reference", "selfhost"))
def test_native_class_index_preserves_lookup_and_replacement(
    semantic_btrcc: Path, tmp_path: Path, frontend: str
) -> None:
    source = f'''
import Library.Datetime;
import Library.Vector;
import "{SELFHOST / "analyzer/Models.btrc"}";
import "{SELFHOST / "frontend/Models.btrc"}";
import "{SELFHOST / "generated/ast/Node.btrc"}";

FeNativeImportedDeclaration nativeClass(string name, string language, Vector<string> ancestors) {{
	var node = Node();
	node.kind = NK_CLASS_DECL;
	node.name = name;
	var imported = FeNativeImportedDeclaration(node, "Lookup", "Lookup.h");
	imported.language = language;
	imported.nativeAncestors = ancestors;
	return imported;
}}

string linearLanguage(Vector<FeNativeImportedDeclaration> declarations, string name) {{
	for imported in declarations {{
		if (imported.declaration.kind == NK_CLASS_DECL && imported.declaration.name == name) {{ return imported.language; }}
	}}
	return "";
}}

int main() {{
	var analyzed = Analyzed();
	assert(analyzed.nativeClassLanguage("Missing") == "");
	Vector<string> noAncestors = [];
	Vector<FeNativeImportedDeclaration> declarations = [];
	for (int index = 0; index < 1000; index++) {{
		var node = Node();
		node.kind = NK_STRUCT_DECL;
		node.name = f"SDKRecord{{index}}";
		declarations.push(FeNativeImportedDeclaration(node, "Lookup", "Lookup.h"));
	}}
	declarations.push(nativeClass("NativeBase", "objective-c", noAncestors));
	declarations.push(nativeClass("NativeChild", "objective-c", ["NativeBase"]));
	declarations.push(nativeClass("NativeSibling", "objective-c", ["NativeBase"]));
	declarations.push(nativeClass("CppClass", "c++", noAncestors));
	// The original query chooses the first declaration when SDK imports overlap.
	declarations.push(nativeClass("NativeChild", "c++", noAncestors));
	analyzed.setNativeDeclarations(declarations);
	Vector<string> names = ["Missing", "NativeChild", "NativeBase", "NativeSibling", "CppClass", "SDKRecord500"];
	for name in names {{ assert(analyzed.nativeClassLanguage(name) == linearLanguage(declarations, name)); }}
	assert(analyzed.isSubclass("NativeChild", "NativeBase"));
	assert(analyzed.isSubclass("NativeChild", "NativeChild"));
	assert(!analyzed.isSubclass("NativeBase", "NativeChild"));
	assert(!analyzed.isSubclass("NativeChild", "NativeSibling"));
	assert(!analyzed.isSubclass("NativeChild", "Missing"));
	assert(!analyzed.isSubclass("NativeChild", "CppClass"));
	var base = Node(); base.kind = NK_CLASS_DECL; base.name = "OwnedBase";
	var child = Node(); child.kind = NK_CLASS_DECL; child.name = "OwnedChild"; child.parent = "OwnedBase";
	analyzed.classTable.put(base.name, base);
	analyzed.classTable.put(child.name, child);
	assert(analyzed.isSubclass("OwnedChild", "OwnedBase"));
	assert(!analyzed.isSubclass("OwnedBase", "OwnedChild"));
	assert(!analyzed.isSubclass("NativeChild", "OwnedBase"));
	assert(!analyzed.isSubclass("OwnedChild", "NativeBase"));
	var timer = Timer();
	timer.start();
	for (int index = 0; index < 4096; index++) {{ assert(linearLanguage(declarations, "NativeChild") == "objective-c"); }}
	float linear = timer.elapsedMillis();
	timer.start();
	for (int index = 0; index < 4096; index++) {{ assert(analyzed.nativeClassLanguage("NativeChild") == "objective-c"); }}
	fprintf(stderr, "Native lookup (1005 declarations, 4096 queries): linear=%f ms indexed=%f ms\\n", linear, timer.elapsedMillis());
	// Reinstallation replaces the complete index, even at identical cardinality.
	analyzed.setNativeDeclarations([nativeClass("Old", "objective-c", noAncestors)]);
	assert(analyzed.nativeClassLanguage("NativeChild") == "");
	analyzed.setNativeDeclarations([nativeClass("New", "objective-c", noAncestors)]);
	assert(analyzed.nativeClassLanguage("Old") == "" && analyzed.nativeClassLanguage("New") == "objective-c");
	Vector<FeNativeImportedDeclaration> empty = [];
	analyzed.setNativeDeclarations(empty);
	assert(analyzed.nativeClassLanguage("New") == "");
	return 0;
}}
'''
    if frontend == "reference":
        result, generated = _compile_reference_source(tmp_path, source)
    else:
        result, generated = _compile_source(semantic_btrcc, tmp_path, source, no_stdlib=False)
    assert result.returncode == 0, result.stderr
    executable = tmp_path / "native-class-index"
    _strict_build_and_run(generated, executable, optimization="-O2")
    measured = _run([str(executable)], timeout=30)
    assert measured.returncode == 0, measured.stderr
    print(f"{frontend}: {measured.stderr.strip()}")
