"""Typed runtime-provider reachability and strict-C contracts."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.abi.freestanding import FreestandingRuntime
from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
TYPE_CASES = (
    ("Mutex", "__btrc_mutex_val_types", "__btrc_mutex_val_t"),
    ("Thread", "__btrc_thread_types", "__btrc_thread_t"),
)
EXTERN_MUTEX_SOURCE = "extern Mutex<int> acquire(); int main(){ Mutex<int> m = acquire(); return 0; }"


def _lower(source: str, *, freestanding: bool = False) -> IRModule:
    program = Parser(Lexer(source, "<runtime-type-provider>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    return IRLowerer(analyzed, freestanding=freestanding).lower()


def _optimize(module: IRModule, *, freestanding: bool = False) -> tuple[CompilationPipeline, IRModule]:
    pipeline = CompilationPipeline()
    options = CompilerOptions(freestanding=freestanding)
    return pipeline, pipeline.optimize(module, options)


def test_runtime_catalog_owns_provider_lookups() -> None:
    catalog = RuntimeHelperCatalog()
    type_providers = catalog.helper_names_providing_types(
        {"__btrc_arc_type", "__btrc_mutex_val_t", "__btrc_thread_t", "user_type"}
    )
    object_providers = catalog.helper_names_providing_objects({"__btrc_mutex_arc_descriptor", "user_object"})

    assert type_providers == frozenset(
        {
            "__btrc_arc_callback_types",
            "__btrc_mutex_val_types",
            "__btrc_thread_types",
        }
    )
    assert object_providers == frozenset({"__btrc_mutex_arc_type"})


@pytest.mark.parametrize(("base", "provider", "c_type"), TYPE_CASES)
def test_type_only_sizeof_selects_and_preserves_its_live_provider(base: str, provider: str, c_type: str) -> None:
    module = _lower(f"int main() {{ return (int)sizeof({base}<int>); }}")
    assert provider in {helper.name for helper in module.helper_decls}
    assert "__btrc_thread_spawn" not in {helper.name for helper in module.helper_decls}

    pipeline, module = _optimize(module)
    emitted = pipeline.emit(module)

    assert provider in {helper.name for helper in module.helper_decls}
    assert f"sizeof({c_type}*)" in emitted
    assert f"}} {c_type};" in emitted
    assert "static __btrc_thread_t* __btrc_thread_spawn(" not in emitted


@pytest.mark.parametrize(("base", "provider", "c_type"), TYPE_CASES)
def test_dead_type_only_sizeof_does_not_pin_its_provider(base: str, provider: str, c_type: str) -> None:
    module = _lower(f"int dead() {{ return (int)sizeof({base}<int>); }} int main() {{ return 0; }}")
    pipeline, module = _optimize(module)
    emitted = pipeline.emit(module)

    assert [function.name for function in module.function_defs] == ["main"]
    assert provider not in {helper.name for helper in module.helper_decls}
    assert c_type not in emitted


@pytest.mark.parametrize(("base", "provider", "c_type"), TYPE_CASES)
def test_specialized_sizeof_preserves_runtime_type_provider(base: str, provider: str, c_type: str) -> None:
    module = _lower(
        f"""
        class Probe<T> {{
            public Probe() {{}}
            public int size() {{ return (int)sizeof({base}<T>); }}
        }}
        int main() {{
            Probe<int> probe = new Probe<int>();
            return probe.size();
        }}
        """
    )
    pipeline, module = _optimize(module)
    emitted = pipeline.emit(module)

    assert provider in {helper.name for helper in module.helper_decls}
    assert f"sizeof({c_type}*)" in emitted


def test_extern_owned_mutex_preserves_live_descriptor_provider() -> None:
    module = _lower(EXTERN_MUTEX_SOURCE)
    assert "__btrc_mutex_arc_type" in {helper.name for helper in module.helper_decls}

    pipeline, module = _optimize(module)
    emitted = pipeline.emit(module)

    assert "__btrc_mutex_arc_type" in {helper.name for helper in module.helper_decls}
    assert "static const __btrc_arc_type __btrc_mutex_arc_descriptor" in emitted
    assert "&__btrc_mutex_arc_descriptor" in emitted


def test_dead_extern_owned_mutex_does_not_pin_descriptor_provider() -> None:
    module = _lower(
        "extern Mutex<int> acquire(); int dead(){ Mutex<int> m = acquire(); return 0; } int main(){ return 0; }"
    )
    pipeline, module = _optimize(module)
    emitted = pipeline.emit(module)

    assert [function.name for function in module.function_defs] == ["main"]
    assert "__btrc_mutex_arc_type" not in {helper.name for helper in module.helper_decls}
    assert "__btrc_mutex_arc_descriptor" not in emitted


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_extern_owned_mutex_descriptor_compiles_strict_c11(tmp_path: Path, c_compiler: str) -> None:
    pipeline, module = _optimize(_lower(EXTERN_MUTEX_SOURCE))
    emitted = pipeline.emit(module)
    c_path = tmp_path / "extern-owned-mutex.c"
    object_path = tmp_path / "extern-owned-mutex.o"
    c_path.write_text(emitted)

    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
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


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("freestanding", (False, True), ids=("hosted", "freestanding"))
@pytest.mark.parametrize(("base", "provider", "c_type"), TYPE_CASES)
def test_type_only_sizeof_compiles_strict_c11(
    tmp_path: Path,
    c_compiler: str,
    freestanding: bool,
    base: str,
    provider: str,
    c_type: str,
) -> None:
    module = _lower(
        f"int main() {{ return (int)sizeof({base}<int>); }}",
        freestanding=freestanding,
    )
    pipeline, module = _optimize(module, freestanding=freestanding)
    emitted = pipeline.emit(module)

    assert provider in {helper.name for helper in module.helper_decls}
    assert f"}} {c_type};" in emitted

    c_path = tmp_path / f"{base.lower()}-type-only.c"
    object_path = tmp_path / f"{base.lower()}-type-only.o"
    c_path.write_text(emitted)
    command = [
        c_compiler,
        "-std=c11",
        "-pedantic-errors",
        "-Wall",
        "-Wextra",
        "-Werror",
    ]
    if freestanding:
        (tmp_path / "btrc_rt.h").write_text(FreestandingRuntime().header)
        (tmp_path / "pthread_shim.h").write_text(
            "typedef unsigned long pthread_t;\ntypedef struct { unsigned long opaque; } pthread_mutex_t;\n"
        )
        command.extend(
            (
                "-ffreestanding",
                "-fno-builtin",
                "-DBTRC_FREESTANDING",
                '-DBTRC_RT_PTHREAD_HEADER="pthread_shim.h"',
                f"-I{tmp_path}",
            )
        )
    else:
        command.append("-pthread")
    command.extend(("-c", str(c_path), "-o", str(object_path)))

    compiled = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
