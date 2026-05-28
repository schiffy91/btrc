from src.compiler.python.main import resolve_includes


def test_std_brace_import_resolves_stdlib():
    source = "import std.{strings, json}\nint main() { return 0; }"
    resolved = resolve_includes(source, "main.btrc")

    assert "class Strings" in resolved
    assert "class JsonObject" in resolved
    assert "import std" not in resolved


def test_relative_bulk_imports_are_sorted_and_recursive(tmp_path):
    root = tmp_path / "project"
    nested = root / "lib" / "nested"
    nested.mkdir(parents=True)
    (root / "main.btrc").write_text("import ./lib/**\nint main() { return 0; }")
    (root / "lib" / "b.btrc").write_text("class B {}\n")
    (root / "lib" / "a.btrc").write_text("class A {}\n")
    (nested / "c.btrc").write_text("class C {}\n")

    resolved = resolve_includes((root / "main.btrc").read_text(), str(root / "main.btrc"))

    assert resolved.index("class A") < resolved.index("class B")
    assert "class C" in resolved
    assert "import ./lib/**" not in resolved
