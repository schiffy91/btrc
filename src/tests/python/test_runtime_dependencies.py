"""Structured freestanding-runtime dependency contracts."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.freestanding import RUNTIME_HEADER
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
STDLIB = Path(__file__).parents[2] / "stdlib"


def _generate(source: str):
    program = Parser(Lexer(source, "<runtime-dependencies>").tokenize()).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors
    return IRGenerator(analyzed, freestanding=True).generate()


def test_pure_core_ir_needs_no_runtime_seam():
    module = _generate("int main() { return 0; }")

    assert not module.needs_runtime
    assert "btrc_rt.h" not in CEmitter().emit(module)


def test_managed_string_local_requires_ownership_runtime():
    module = _generate("int main() { string name = \"printf\"; return name[0] == 'p' ? 0 : 1; }")
    emitted = CEmitter().emit(module)

    assert module.needs_runtime
    assert '#include "btrc_rt.h"' in emitted
    assert "__btrc_string_release" in emitted


def test_runtime_name_inside_borrowed_string_literal_is_not_a_dependency():
    module = _generate("int main() { return \"printf\"[0] == 'p' ? 0 : 1; }")

    assert not module.needs_runtime
    assert "btrc_rt.h" not in CEmitter().emit(module)


@pytest.mark.parametrize(
    "source",
    (
        "int main() { bool ready = true; return ready ? 0 : 1; }",
        "int main() { int* value = null; return value == null ? 0 : 1; }",
    ),
)
def test_foundational_c_types_and_macros_require_the_runtime_seam(source: str):
    module = _generate(source)

    assert module.needs_runtime
    assert '#include "btrc_rt.h"' in CEmitter().emit(module)


def test_direct_runtime_call_is_discovered_from_ir_call():
    module = _generate('int main() { print("hello"); return 0; }')

    assert module.needs_runtime
    assert '#include "btrc_rt.h"' in CEmitter().emit(module)


def test_explicit_string_adoption_is_owned_and_materializes_its_helpers():
    module = _generate("""
        int main() {
            char* raw = (char*)__btrc_safe_realloc(NULL, (size_t)2);
            raw[0] = (char)120;
            raw[1] = (char)0;
            string owned = __btrc_str_track(raw);
            return owned[0] == (char)120 ? 0 : 1;
        }
    """)
    emitted = CEmitter().emit(module)

    assert "static inline char* __btrc_str_track" in emitted
    assert "char* owned = __btrc_str_track(raw);" in emitted
    clear = emitted.index("owned = NULL;")
    release = emitted.index("__btrc_string_release(", clear)
    assert clear < release


@pytest.mark.parametrize(
    ("callee", "feature"),
    (
        ("btrc_gpu_available", "BTRC_RT_NEEDS_GPU"),
        ("btrc_gui_surface_width", "BTRC_RT_NEEDS_GUI"),
        ("btrc_tray_show", "BTRC_RT_NEEDS_TRAY"),
    ),
)
def test_native_runtime_calls_select_explicit_header_features(callee, feature):
    module = _generate(f"extern int {callee}(); int main() {{ return {callee}(); }}")
    emitted = CEmitter().emit(module)

    assert f"#define {feature} 1" in emitted
    assert emitted.index(f"#define {feature} 1") < emitted.index('#include "btrc_rt.h"')


def test_user_function_with_gpu_word_does_not_select_feature():
    module = _generate("int user_gpu_local() { return 0; } int main() { return user_gpu_local(); }")

    assert "BTRC_RT_NEEDS_GPU" not in CEmitter().emit(module)


def test_user_function_cannot_claim_reserved_native_prefix():
    program = Parser(
        Lexer(
            "int btrc_gpu_local() { return 0; }",
            "<runtime-dependencies>",
        ).tokenize()
    ).parse()

    errors = Analyzer().analyze(program).errors

    assert any("compiler-reserved 'btrc_' prefix" in error for error in errors)


def test_user_header_override_precedes_generated_feature_and_seam():
    module = _generate(
        '#define BTRC_RT_GPU_HEADER "target_gpu.h"\n'
        "extern int btrc_gpu_available(); int main() { return btrc_gpu_available(); }"
    )
    emitted = CEmitter().emit(module)

    override = '#define BTRC_RT_GPU_HEADER "target_gpu.h"'
    feature = "#define BTRC_RT_NEEDS_GPU 1"
    seam = '#include "btrc_rt.h"'
    assert emitted.index(override) < emitted.index(feature) < emitted.index(seam)


def test_try_runtime_selects_target_owned_setjmp_type():
    module = _generate('int main() { try { throw "boom"; } catch (string error) { return 0; } }')

    emitted = CEmitter().emit(module)
    assert "#define BTRC_RT_NEEDS_SETJMP 1" in emitted


@pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    ("source", "header_macro", "include_dir"),
    (
        (
            "extern int btrc_gui_surface_width(void* surface); int main() { return btrc_gui_surface_width(null); }",
            "BTRC_RT_GUI_HEADER=<btrc_gui.h>",
            STDLIB / "gui",
        ),
        (
            "extern bool btrc_tray_show(void* tray); int main() { return btrc_tray_show(null) ? 0 : 1; }",
            "BTRC_RT_TRAY_HEADER=<btrc_tray.h>",
            STDLIB / "tray",
        ),
    ),
    ids=("gui", "tray"),
)
def test_native_target_header_hooks_compile_strict_c11(
    tmp_path,
    c_compiler,
    source,
    header_macro,
    include_dir,
):
    module = _generate(source)
    optimize(module)
    c_path = tmp_path / "native_seam.c"
    object_path = tmp_path / "native_seam.o"
    c_path.write_text(CEmitter().emit(module))
    (tmp_path / "btrc_rt.h").write_text(RUNTIME_HEADER)

    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-ffreestanding",
            "-fno-builtin",
            "-DBTRC_FREESTANDING",
            f"-D{header_macro}",
            f"-I{tmp_path}",
            f"-I{include_dir}",
            "-c",
            str(c_path),
            "-o",
            str(object_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr


def test_user_function_named_like_libc_is_not_a_runtime_dependency():
    module = _generate("int printf(int value) { return value; } int main() { return printf(0); }")

    assert not module.needs_runtime
    assert "btrc_rt.h" not in CEmitter().emit(module)


def test_runtime_dependency_is_recomputed_after_dead_function_elimination():
    module = _generate('int dead() { print("unreachable"); return 1; } int main() { return 0; }')
    assert module.needs_runtime

    optimize(module)

    assert [function.name for function in module.function_defs] == ["main"]
    assert not module.needs_runtime
    assert "btrc_rt.h" not in CEmitter().emit(module)


@pytest.mark.parametrize("roots", ([], {""}, {7}))
def test_runtime_roots_fail_closed_when_mutated_to_invalid_schema(roots):
    module = IRModule()
    module.runtime_roots = roots

    with pytest.raises(TypeError, match="runtime_roots"):
        module.validate_declarations()
