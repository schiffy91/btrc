"""Focused typed-box, lifetime-domain, and helper-DCE Mutex contracts."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python import Compiler, CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _emit_with_stdlib(source: str) -> str:
    compiler = Compiler()
    options = CompilerOptions(map_stdlib_positions=True)
    frontend = compiler.compile_frontend(
        source,
        "<mutex-lowering>",
        options,
        filename="mutex_lowering.btrc",
    )
    assert frontend.analyzed.errors == []
    source_map = frontend.source_bundle.source_map(
        split_spaces=bool(frontend.stdlib_source and frontend.user_program is not None),
    )
    module = IRLowerer(
        frontend.analyzed,
        source_file="mutex_lowering.btrc",
        source_map=source_map,
    ).lower()
    return compiler.pipeline.emit(compiler.pipeline.optimize(module, options))


def _compile_and_run_strict_c11(generated: str, tmp_path: Path, c_compiler: str, stem: str) -> None:
    source = tmp_path / f"{stem}.c"
    executable = tmp_path / stem
    source.write_text(generated)
    compiled = subprocess.run(
        [
            c_compiler,
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
def test_language_mutex_constructor_executes_under_strict_c11(tmp_path: Path, c_compiler: str):
    generated = emit_c("""
        int main() {
            Mutex<int> value = Mutex(1);
            return value.get() == 1 ? 0 : 1;
        }
    """)

    assert re.search(r"\bMutex\s*\(", generated) is None
    assert "__btrc_mutex_val_create" in generated

    source = tmp_path / "mutex_constructor.c"
    executable = tmp_path / "mutex_constructor"
    source.write_text(generated)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror=implicit-function-declaration",
            "-O1",
            str(source),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_mutex_destroy_consumes_only_its_slot_under_strict_c11(tmp_path: Path, c_compiler: str):
    generated = emit_c("""
        int main() {
            Mutex<int> original = Mutex(7);
            Mutex<int> alias = original;
            original.destroy();
            int result = alias.get();
            alias.destroy();
            alias.destroy();
            bool caught = false;
            try {
                Mutex<int> temporary = Mutex(9);
                temporary.destroy();
                throw "after destroy";
            } catch (string error) {
                caught = error.equals("after destroy");
            }
            return result == 7 && caught ? 0 : 1;
        }
    """)

    source = tmp_path / "mutex_destroy.c"
    executable = tmp_path / "mutex_destroy"
    source.write_text(generated)
    subprocess.run(
        [
            c_compiler,
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
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_mutex_set_evaluates_receiver_before_value_under_strict_c11(tmp_path: Path, c_compiler: str):
    generated = emit_c("""
        #include <assert.h>

        int step = 0;
        int nextValue() {
            assert(step == 1);
            step = 2;
            return 7;
        }

        int main() {
            Mutex<int> value = Mutex(0);
            ((step = 1) ? value : value).set(nextValue());
            int result = value.get();
            value.destroy();
            return step == 2 && result == 7 ? 0 : 1;
        }
    """)
    setter = next(
        line for line in generated.splitlines() if "__btrc_mutex_val_set(" in line and not line.startswith("static ")
    )

    assert setter.index("step = 1") < setter.index("nextValue()")
    assert re.search(r"__btrc_mutex_receiver_\d+ = ", setter)

    source = tmp_path / "mutex_set_order.c"
    executable = tmp_path / "mutex_set_order"
    source.write_text(generated)
    compiled = subprocess.run(
        [
            c_compiler,
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
def test_owned_temporary_mutex_set_and_get_release_receiver_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    generated = emit_c("""
        #include <assert.h>

        int alive = 0;

        class Box {
            public int id;
            public Box(int id) { self.id = id; alive++; }
            public void __del__() { alive--; }
        }

        Mutex<Box> makeMutex(int id) {
            Box item = new Box(id);
            return Mutex(item);
        }

        int main() {
            Box replacement = new Box(2);
            makeMutex(1).set(replacement);
            release replacement;
            assert(alive == 0);

            Box got = makeMutex(3).get();
            assert(got.id == 3);
            assert(alive == 1);
            release got;
            return alive == 0 ? 0 : 1;
        }
    """)
    main = generated[generated.index("int main(void)") :]
    setter = next(line for line in main.splitlines() if "__btrc_mutex_val_set(" in line)
    getter = next(line for line in main.splitlines() if "__btrc_mutex_val_get(" in line)

    assert setter.index("makeMutex(1)") < setter.index("__btrc_mutex_val_set(")
    assert setter.index("__btrc_mutex_val_set(") < setter.index("__btrc_arc_release_acyclic(")
    assert "(&__btrc_mutex_arc_descriptor)" in setter
    assert getter.index("__btrc_mutex_val_get(") < getter.index("__btrc_arc_release_acyclic(")
    assert re.search(r"__btrc_call_result_\d+ = .*__btrc_mutex_val_get", getter)
    assert "(&__btrc_mutex_arc_descriptor)" in getter

    _compile_and_run_strict_c11(generated, tmp_path, c_compiler, "mutex_owned_receiver")


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_mutex_set_releases_owned_managed_rhs_under_strict_c11(tmp_path: Path, c_compiler: str):
    generated = emit_c("""
        #include <assert.h>

        int alive = 0;

        class Box {
            public int id;
            public Box(int id) { self.id = id; alive++; }
            public void __del__() { alive--; }
        }

        int main() {
            Mutex<Box> value = Mutex(new Box(1));
            assert(alive == 1);
            value.set(new Box(2));
            assert(alive == 1);
            value.destroy();
            return alive == 0 ? 0 : 1;
        }
    """)
    setter = next(
        line for line in generated.splitlines() if "__btrc_mutex_val_set(" in line and not line.startswith("static ")
    )

    assert setter.index("Box_new(2)") < setter.index("__btrc_mutex_val_set(")
    assert setter.index("__btrc_mutex_val_set(") < setter.rindex("__btrc_arc_release_acyclic(")
    assert setter.count("__btrc_arc_release_acyclic(") >= 2

    _compile_and_run_strict_c11(generated, tmp_path, c_compiler, "mutex_owned_rhs")


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_mutex_set_contextually_types_builtin_collection_result_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    generated = _emit_with_stdlib("""
        import std.map;

        int main() {
            Map<string, int> values = new Map<string, int>();
            values.put("key", 7);
            Mutex<int> result = new Mutex<int>(0);
            result.set(values.get("key"));
            int observed = result.get();
            result.destroy();
            return observed == 7 ? 0 : 1;
        }
    """)
    main = generated[generated.index("int main(void)") :]
    lookup = main.index("btrc_Map_string_int_get(")
    setter = main.index("__btrc_mutex_val_set(", lookup)

    assert lookup < setter
    assert main.count("btrc_Map_string_int_get(") == 1

    _compile_and_run_strict_c11(generated, tmp_path, c_compiler, "mutex_contextual_collection_get")


def test_new_managed_constructors_use_constructor_ownership() -> None:
    generated = emit_c("""
        class Box { public Box() {} }

        int main() {
            Box item = new Box();
            Mutex<Box> guarded = new Mutex<Box>(item);
            guarded.destroy();
            release item;
            return 0;
        }
    """)

    assert "Box_new()" in generated
    assert "__btrc_mutex_val_create(" in generated


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_new_mutex_constructor_shares_the_owned_call_boundary(tmp_path: Path, c_compiler: str):
    generated = emit_c("""
        #include <assert.h>

        int alive = 0;

        class Box {
            public Box() { alive++; }
            public void __del__() { alive--; }
        }

        int main() {
            Mutex<Box> inferred = Mutex(new Box());
            Mutex<Box> explicit = new Mutex<Box>(new Box());
            assert(alive == 2);
            inferred.destroy();
            explicit.destroy();
            return alive == 0 ? 0 : 1;
        }
    """)
    main = generated[generated.index("int main(void)") :]
    constructors = [line for line in main.splitlines() if "__btrc_mutex_val_create(" in line]

    assert len(constructors) == 2
    for constructor in constructors:
        assert constructor.index("Box_new()") < constructor.index("__btrc_mutex_val_create(")
        assert constructor.index("__btrc_mutex_val_create(") < constructor.index("__btrc_arc_release_acyclic(")

    _compile_and_run_strict_c11(generated, tmp_path, c_compiler, "new_mutex_owned_boundary")


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_new_mutex_constructor_is_single_evaluation_and_exception_safe(
    tmp_path: Path,
    c_compiler: str,
):
    generated = emit_c("""
        #include <assert.h>

        int alive = 0;
        int evaluations = 0;

        class Box {
            public Box() { alive++; }
            public void __del__() { alive--; }
        }

        Box makeBox() {
            evaluations++;
            return new Box();
        }

        int main() {
            bool caught = false;
            try {
                new Mutex<Box>(makeBox());
                throw "boom";
            } catch (string error) {
                caught = error.equals("boom");
            }
            assert(evaluations == 1);
            return caught && alive == 0 ? 0 : 1;
        }
    """)
    main = generated[generated.index("int main(void)") :]
    evaluation = main.index("= makeBox()")
    payload_guard = main.index("__btrc_register_cleanup", evaluation)
    constructor = main.index("__btrc_mutex_val_create(", payload_guard)
    result_guard = main.index("__btrc_register_cleanup", constructor)

    assert main.count("= makeBox()") == 1
    assert evaluation < payload_guard < constructor < result_guard

    _compile_and_run_strict_c11(generated, tmp_path, c_compiler, "new_mutex_exception_boundary")


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_owned_temporary_mutex_receiver_is_protected_before_throwing_rhs_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    generated = emit_c("""
        int alive = 0;

        class Box {
            public int id;
            public Box(int id) { self.id = id; alive++; }
            public void __del__() { alive--; }
        }

        Mutex<Box> makeMutex() {
            Box item = new Box(1);
            return Mutex(item);
        }

        Box failValue() {
            if (alive >= 0) { throw "boom"; }
            return null;
        }

        int main() {
            bool caught = false;
            try {
                makeMutex().set(failValue());
            } catch (string error) {
                caught = error.equals("boom");
            }
            return caught && alive == 0 ? 0 : 1;
        }
    """)
    main = generated[generated.index("int main(void)") :]
    receiver = main.index("= makeMutex()")
    protection = main.index("__btrc_register_cleanup", receiver)
    rhs = main.index("= failValue()", protection)

    assert receiver < protection < rhs
    assert "__btrc_mutex_arc_destroy" in main[protection:rhs]

    _compile_and_run_strict_c11(generated, tmp_path, c_compiler, "mutex_exception_receiver_cleanup")


def test_plain_mutex_omits_managed_lifetime_domains():
    generated = emit_c("""
        int main() {
            Mutex<int> value = Mutex(1);
            value.set(2);
            int result = value.get();
            value.destroy();
            return result;
        }
    """)

    assert "__btrc_mutex_val_create" in generated
    assert "__btrc_mutex_arc_retain" not in generated
    assert "__btrc_mutex_string_retain" not in generated
    assert "__btrc_arc_retain(" not in generated
    assert "__btrc_string_registry" not in generated


def test_mutex_selects_exact_managed_lifetime_callback_domain():
    class_generated = emit_c("""
        class Box { public Box() {} }
        int main() {
            Box item = new Box();
            Mutex<Box> value = Mutex(item);
            value.destroy();
            release item;
            return 0;
        }
    """)
    string_generated = emit_c("""
        int main() {
            Mutex<string> value = Mutex("literal");
            value.destroy();
            return 0;
        }
    """)

    assert "static void __btrc_mutex_arc_retain(" in class_generated
    assert "static void __btrc_mutex_arc_release(" in class_generated
    assert "__btrc_mutex_string_retain" not in class_generated
    assert "static void __btrc_mutex_string_retain(" in string_generated
    assert "static void __btrc_mutex_string_release(" in string_generated
    assert "__btrc_mutex_arc_retain" not in string_generated


def test_mutex_evaluates_initializer_before_transport_allocation():
    generated = emit_c("""
        int nextValue() { return 7; }
        int main() {
            Mutex<int> value = Mutex(nextValue());
            value.destroy();
            return 0;
        }
    """)
    initializer = next(line for line in generated.splitlines() if "__btrc_mutex_val_t* value =" in line)

    assert initializer.index("nextValue()") < initializer.index("__btrc_safe_realloc")


def test_mutex_destroy_clears_and_releases_an_owned_arc_slot():
    generated = emit_c("""
        int main() {
            Mutex<int> value = Mutex(1);
            value.destroy();
            return 0;
        }
    """)

    assert "__btrc_mutex_val_take" not in generated
    assert "__btrc_mutex_val_destroy" not in generated
    slot = generated.index("__btrc_mutex_val_t* volatile* __btrc_release_slot")
    clear = generated.index("= NULL", slot)
    release = generated.index("__btrc_arc_release_acyclic", clear)
    assert slot < clear < release
    assert "(&__btrc_mutex_arc_descriptor)" in generated[release:]
