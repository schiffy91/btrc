"""Structured freestanding-runtime dependency contracts."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.abi.freestanding import FreestandingRuntime
from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import IRInclude, IRModule
from src.compiler.python.ir.verifier import IRVerifier
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
STDLIB = Path(__file__).parents[2] / "stdlib"


def _generate(source: str, *, freestanding: bool = True) -> IRModule:
    program = Parser(Lexer(source, "<runtime-dependencies>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    return IRLowerer(analyzed, freestanding=freestanding).lower()


def _emit(module: IRModule) -> str:
    pipeline = CompilationPipeline()
    module = pipeline.optimize(module, CompilerOptions(freestanding=True))
    return pipeline.emit(module)


def _optimize_hosted(source: str) -> IRModule:
    module = _generate(source, freestanding=False)
    return CompilationPipeline().optimize(module, CompilerOptions())


def _system_headers(module: IRModule) -> list[str]:
    return [
        declaration.header
        for declaration in module.preprocessor_decls
        if isinstance(declaration, IRInclude) and declaration.is_system
    ]


def test_pure_core_ir_needs_no_runtime_seam():
    module = _generate("int main() { return 0; }")
    emitted = _emit(module)

    assert not module.needs_runtime
    assert "btrc_rt.h" not in emitted


def test_managed_string_local_requires_ownership_runtime():
    module = _generate("int main() { string name = \"printf\"; return name[0] == 'p' ? 0 : 1; }")
    emitted = _emit(module)

    assert module.needs_runtime
    assert '#include "btrc_rt.h"' in emitted
    assert "__btrc_string_release" in emitted


def test_runtime_name_inside_borrowed_string_literal_is_not_a_dependency():
    module = _generate("int main() { return \"printf\"[0] == 'p' ? 0 : 1; }")
    emitted = _emit(module)

    assert not module.needs_runtime
    assert "btrc_rt.h" not in emitted


@pytest.mark.parametrize(
    "source",
    (
        "int main() { bool ready = true; return ready ? 0 : 1; }",
        "int main() { int* value = null; return value == null ? 0 : 1; }",
    ),
)
def test_foundational_c_types_and_macros_require_the_runtime_seam(source: str):
    module = _generate(source)
    emitted = _emit(module)

    assert module.needs_runtime
    assert '#include "btrc_rt.h"' in emitted


def test_direct_runtime_call_is_discovered_from_ir_call():
    module = _generate('int main() { print("hello"); return 0; }')
    emitted = _emit(module)

    assert module.needs_runtime
    assert '#include "btrc_rt.h"' in emitted


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
    emitted = _emit(module)

    assert "static inline char* __btrc_str_track" in emitted
    assert "char* owned = __btrc_str_track(raw);" in emitted
    clear = emitted.index("owned = NULL;")
    release = emitted.index("__btrc_string_release(", clear)
    assert clear < release


@pytest.mark.parametrize(
    ("declaration", "call", "feature"),
    (
        ("extern bool btrc_gpu_available();", "btrc_gpu_available()", "BTRC_RT_NEEDS_GPU"),
        (
            "extern int btrc_gui_surface_width(void* surface);",
            "btrc_gui_surface_width(null)",
            "BTRC_RT_NEEDS_GUI",
        ),
        (
            "extern bool btrc_tray_show(void* tray);",
            "btrc_tray_show(null)",
            "BTRC_RT_NEEDS_TRAY",
        ),
    ),
)
def test_native_runtime_calls_select_explicit_header_features(declaration, call, feature):
    module = _generate(f"{declaration} int main() {{ {call}; return 0; }}")
    emitted = _emit(module)

    assert f"#define {feature} 1" in emitted
    assert emitted.index(f"#define {feature} 1") < emitted.index('#include "btrc_rt.h"')


def test_user_function_with_gpu_word_does_not_select_feature():
    module = _generate("int user_gpu_local() { return 0; } int main() { return user_gpu_local(); }")

    assert "BTRC_RT_NEEDS_GPU" not in _emit(module)


def test_user_function_cannot_claim_reserved_native_prefix():
    program = Parser(
        Lexer(
            "int btrc_gpu_local() { return 0; }",
            "<runtime-dependencies>",
        ).tokenize()
    ).parse()

    errors = SemanticAnalyzer().analyze(program).errors

    assert any("compiler-reserved 'btrc_' prefix" in error for error in errors)


def test_user_header_override_precedes_generated_feature_and_seam():
    module = _generate(
        '#define BTRC_RT_GPU_HEADER "target_gpu.h"\n'
        "extern bool btrc_gpu_available(); "
        "int main() { return btrc_gpu_available() ? 0 : 1; }"
    )
    emitted = _emit(module)

    override = '#define BTRC_RT_GPU_HEADER "target_gpu.h"'
    feature = "#define BTRC_RT_NEEDS_GPU 1"
    seam = '#include "btrc_rt.h"'
    assert emitted.index(override) < emitted.index(feature) < emitted.index(seam)


def test_try_runtime_selects_target_owned_setjmp_type():
    module = _generate('int main() { try { throw "boom"; } catch (string error) { return 0; } }')

    emitted = _emit(module)
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
    pipeline = CompilationPipeline()
    module = pipeline.optimize(module, CompilerOptions(freestanding=True))
    c_path = tmp_path / "native_seam.c"
    object_path = tmp_path / "native_seam.o"
    c_path.write_text(pipeline.emit(module))
    (tmp_path / "btrc_rt.h").write_text(FreestandingRuntime().header)

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
    emitted = _emit(module)

    assert not module.needs_runtime
    assert "btrc_rt.h" not in emitted


def test_runtime_dependency_is_recomputed_after_dead_function_elimination():
    source = 'int dead() { print("unreachable"); return 1; } int main() { return 0; }'
    unpruned = _generate(source)
    CompilationPipeline().optimize(
        unpruned,
        CompilerOptions(freestanding=True, dce=False),
    )
    assert unpruned.needs_runtime

    module = _generate(source)
    pipeline = CompilationPipeline()
    module = pipeline.optimize(module, CompilerOptions(freestanding=True))

    assert [function.name for function in module.function_defs] == ["main"]
    assert not module.needs_runtime
    assert "btrc_rt.h" not in pipeline.emit(module)


_DERIVED_HOSTED_HEADERS = frozenset({"pthread.h", "setjmp.h", "stdatomic.h"})


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (
            "int main() { try { return 0; } catch (string error) { return 1; } }",
            frozenset({"setjmp.h", "stdatomic.h"}),
        ),
        (
            "int dead() { try { return 1; } catch (string error) { return 2; } } int main() { return 0; }",
            frozenset(),
        ),
        (
            "int main() { var thread = spawn(() => 7); return thread.join(); }",
            _DERIVED_HOSTED_HEADERS,
        ),
        (
            "int dead() { var thread = spawn(() => 7); return thread.join(); } int main() { return 0; }",
            frozenset(),
        ),
    ),
    ids=("live-setjmp", "dead-setjmp", "live-thread", "dead-thread"),
)
def test_generated_hosted_headers_follow_surviving_typed_dependencies(
    source: str,
    expected: frozenset[str],
) -> None:
    headers = _system_headers(_optimize_hosted(source))

    assert set(headers) & _DERIVED_HOSTED_HEADERS == expected
    assert all(headers.count(header) == 1 for header in expected)


def test_explicit_user_headers_survive_dead_runtime_dependency_pruning() -> None:
    module = _optimize_hosted(
        "#include <pthread.h>\n"
        "#include <setjmp.h>\n"
        "#include <stdatomic.h>\n"
        "int dead() { var thread = spawn(() => 7); return thread.join(); } "
        "int main() { return 0; }"
    )
    headers = _system_headers(module)

    assert not module.helper_decls
    assert all(headers.count(header) == 1 for header in _DERIVED_HOSTED_HEADERS)


def test_dead_managed_type_does_not_retain_its_runtime_type_provider() -> None:
    module = _optimize_hosted("class Dead {} int main() { return 0; }")

    assert not module.struct_defs
    assert "__btrc_arc_callback_types" not in {helper.name for helper in module.helper_decls}
    assert "__btrc_arc_callback_types" not in module.runtime_roots
    assert not module.needs_runtime


def test_live_managed_ctype_retains_its_runtime_type_provider() -> None:
    module = _optimize_hosted("class Kept {} int main() { return (int)sizeof(Kept); }")

    assert [declaration.name for declaration in module.struct_defs] == ["Kept"]
    assert "__btrc_arc_callback_types" in {helper.name for helper in module.helper_decls}
    assert "__btrc_arc_callback_types" not in module.runtime_roots
    assert module.needs_runtime


@pytest.mark.parametrize("roots", ([], {""}, {7}))
def test_runtime_roots_fail_closed_when_mutated_to_invalid_schema(roots):
    module = IRModule()
    module.runtime_roots = roots

    with pytest.raises(TypeError, match="runtime_roots"):
        IRVerifier(module).validate()
