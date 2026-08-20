"""Dynamic collection literals cross one typed ownership transaction."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python import Compiler, CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _emit(source: str) -> str:
    compiler = Compiler()
    options = CompilerOptions(map_stdlib_positions=True)
    frontend = compiler.compile_frontend(
        source,
        "<collection-literal-ownership>",
        options,
        filename="collection_literal_ownership.btrc",
    )
    assert frontend.analyzed.errors == []
    source_map = frontend.source_bundle.source_map(
        split_spaces=bool(frontend.stdlib_source and frontend.user_program is not None),
    )
    module = IRLowerer(
        frontend.analyzed,
        source_file="collection_literal_ownership.btrc",
        source_map=source_map,
    ).lower()
    return compiler.pipeline.emit(compiler.pipeline.optimize(module, options))


def _compile_and_run(generated: str, tmp_path: Path, compiler: str, stem: str) -> None:
    source = tmp_path / f"{stem}.c"
    executable = tmp_path / stem
    source.write_text(generated)
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert executed.returncode == 0, executed.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("collection_type", ["Vector", "List"])
def test_sequence_literal_releases_fresh_managed_elements(
    tmp_path: Path,
    c_compiler: str,
    collection_type: str,
):
    generated = _emit(f"""
        import std.{"vector" if collection_type == "Vector" else "list"};

        int alive = 0;

        class Box {{
            public Box() {{ alive++; }}
            public void __del__() {{ alive--; }}
        }}

        int main() {{
            {{
                {collection_type}<Box> values = [new Box(), new Box()];
                assert(values.len == 2);
                assert(alive == 2);
            }}
            return alive == 0 ? 0 : 1;
        }}
    """)
    main = generated[generated.index("int main(void)") :]

    assert main.count("= Box_new()") == 2
    assert main.index("_push(") < main.rindex("__btrc_arc_release_acyclic(")
    _compile_and_run(generated, tmp_path, c_compiler, f"{collection_type.lower()}_literal_ownership")


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_sequence_literal_classifies_later_element_after_callable_rebind(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    generated = _emit("""
        import std.vector;

        extern string foreignString();
        string makeOwnedString() { return f"owned={1}"; }

        int main() {
            {
                __fn_ptr<string> callback = foreignString;
                Vector<string> values = [
                    ((bool)(callback = makeOwnedString) ? "marker" : "marker"),
                    (true ? callback() : foreignString())
                ];
                assert(values.len == 2);
                assert(len(values.get(1)) == 7);
            }
            return (int)collectionLiteralLiveStrings();
        }
    """)
    marker = "int main(void) {"
    observer = (
        'char* foreignString(void) { return (char*)"borrowed"; }\n\n'
        "static size_t collectionLiteralLiveStrings(void) {\n"
        "    return __btrc_string_entry_count;\n"
        "}\n\n"
    )
    generated = generated.replace(marker, observer + marker, 1)
    main = generated[generated.index(marker) :]

    callback_call = main.index("callback()")
    push = main.index("_push(", callback_call)
    release = main.index("__btrc_string_release", push)
    assert callback_call < push < release
    _compile_and_run(generated, tmp_path, c_compiler, "sequence_literal_callable_rebind")


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_map_literal_releases_fresh_managed_keys_and_values(tmp_path: Path, c_compiler: str):
    generated = _emit("""
        import std.map;

        int keysAlive = 0;
        int valuesAlive = 0;

        class Key {
            public Key() { keysAlive++; }
            public void __del__() { keysAlive--; }
        }

        class Value {
            public Value() { valuesAlive++; }
            public void __del__() { valuesAlive--; }
        }

        int main() {
            {
                Map<Key, Value> values = {new Key(): new Value()};
                assert(values.len == 1);
                assert(keysAlive == 1 && valuesAlive == 1);
            }
            return keysAlive == 0 && valuesAlive == 0 ? 0 : 1;
        }
    """)
    main = generated[generated.index("int main(void)") :]
    key = main.index("= Key_new()")
    value = main.index("= Value_new()")
    put = main.index("_put(", value)

    assert key < value < put
    assert main.count("__btrc_arc_release_acyclic(") >= 2
    _compile_and_run(generated, tmp_path, c_compiler, "map_literal_ownership")


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_throwing_later_literal_leaf_unwinds_earlier_owned_leaf(tmp_path: Path, c_compiler: str):
    generated = _emit("""
        import std.vector;

        int alive = 0;
        int evaluations = 0;

        class Box {
            public Box() { alive++; }
            public void __del__() { alive--; }
        }

        Box fail() {
            evaluations++;
            if (evaluations > 0) { throw "leaf failed"; }
            return new Box();
        }

        int main() {
            bool caught = false;
            try {
                Vector<Box> values = [new Box(), fail()];
                (void)values;
            } catch (string error) {
                caught = error.equals("leaf failed");
            }
            return caught && evaluations == 1 && alive == 0 ? 0 : 1;
        }
    """)
    main = generated[generated.index("int main(void)") :]
    first = main.index("= Box_new()")
    protection = main.index("__btrc_register_cleanup", first)
    later = main.index("= fail()", protection)

    assert main.count("= fail()") == 1
    assert first < protection < later
    _compile_and_run(generated, tmp_path, c_compiler, "collection_literal_unwind")
