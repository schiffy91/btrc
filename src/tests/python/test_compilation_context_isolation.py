"""Concurrent compiler invocations must not share mutable translation state."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from src.compiler.python import pkg
from src.compiler.python.analyzer.core import AnalyzedProgram
from src.compiler.python.ast_nodes import Program, TypeExpr
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.gen.types import type_to_c
from src.compiler.python.pkg import IncludeResolutionError


def _generator(
    return_type: str,
    parameter_type: str,
    *,
    barrier: Barrier | None = None,
    fail: bool = False,
    repeat_in_declarations: bool = False,
) -> IRGenerator:
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
    )
    generator = IRGenerator(analyzed)
    callback_type = TypeExpr(
        base="__fn_ptr",
        generic_args=[
            TypeExpr(base=return_type),
            TypeExpr(base=parameter_type),
        ],
    )

    def register_callback_type():
        type_to_c(callback_type)
        if barrier is not None:
            barrier.wait(timeout=10)
        if fail:
            raise RuntimeError("forced lowering failure")

    # Exercise the real translation-unit scope in generate(), while keeping
    # this regression independent of semantic-analyzer implementation details.
    generator._emit_forward_decls = register_callback_type
    if repeat_in_declarations:
        generator._emit_declarations = lambda: type_to_c(callback_type)
    return generator


def _typedef_shapes(module) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (
            declaration.return_type.text,
            tuple(item.text for item in declaration.param_types),
        )
        for declaration in module.function_pointer_typedefs
    }


def test_function_pointer_typedefs_are_isolated_between_threads():
    barrier = Barrier(2)
    integer = _generator("int", "int", barrier=barrier)
    text = _generator("bool", "string", barrier=barrier)

    with ThreadPoolExecutor(max_workers=2) as executor:
        integer_future = executor.submit(integer.generate)
        text_future = executor.submit(text.generate)
        integer_module = integer_future.result(timeout=20)
        text_module = text_future.result(timeout=20)

    assert _typedef_shapes(integer_module) == {("int", ("int",))}
    assert _typedef_shapes(text_module) == {("bool", ("char*",))}


def test_failed_lowering_cannot_leak_typedefs_into_success():
    barrier = Barrier(2)
    successful = _generator("int", "int", barrier=barrier)
    failing = _generator("bool", "string", barrier=barrier, fail=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        success_future = executor.submit(successful.generate)
        failure_future = executor.submit(failing.generate)
        successful_module = success_future.result(timeout=20)
        with pytest.raises(RuntimeError, match="forced lowering failure"):
            failure_future.result(timeout=20)

    assert _typedef_shapes(successful_module) == {("int", ("int",))}
    fresh = _generator("double", "double").generate()
    assert _typedef_shapes(fresh) == {("double", ("double",))}


def test_function_pointer_typedef_is_emitted_once_across_generation_phases():
    module = _generator(
        "int",
        "int",
        repeat_in_declarations=True,
    ).generate()

    assert len(module.function_pointer_typedefs) == 1
    assert _typedef_shapes(module) == {("int", ("int",))}


def test_package_scopes_are_isolated_between_threads(tmp_path: Path):
    roots = {}
    for name in ("left", "right"):
        root = tmp_path / name
        (root / "src").mkdir(parents=True)
        (root / "src" / "dep.btrc").write_text(f"// {name}\n")
        roots[name] = root
    barrier = Barrier(2)

    def resolve_in_scope(name):
        with pkg.package_context({"dep": {"path": str(roots[name])}}):
            barrier.wait(timeout=10)
            resolved = pkg.package_import_paths("dep")[0]
            barrier.wait(timeout=10)
            active = pkg.configured_packages()["dep"]["path"]
        return resolved, active, pkg.configured_packages()

    with ThreadPoolExecutor(max_workers=2) as executor:
        left = executor.submit(resolve_in_scope, "left")
        right = executor.submit(resolve_in_scope, "right")
        left_result = left.result(timeout=20)
        right_result = right.result(timeout=20)

    assert left_result == (
        str(roots["left"] / "src" / "dep.btrc"),
        str(roots["left"]),
        {},
    )
    assert right_result == (
        str(roots["right"] / "src" / "dep.btrc"),
        str(roots["right"]),
        {},
    )


def test_package_configuration_success_and_failure_are_thread_local(
    tmp_path: Path,
    monkeypatch,
):
    success = tmp_path / "success"
    failure = tmp_path / "failure"
    dependency = tmp_path / "dependency"
    for project in (success, failure):
        project.mkdir()
        (project / "btrc.toml").write_text('[package]\nname = "test"\n')
    (dependency / "src").mkdir(parents=True)
    (dependency / "src" / "dep.btrc").write_text("// dependency\n")
    resolving = Barrier(2)
    configured = Barrier(2)

    def fake_resolve(manifest, refresh=False):
        resolving.wait(timeout=10)
        if Path(manifest).parent == failure:
            raise ValueError("broken dependency")
        return {"dep": {"path": str(dependency)}}

    monkeypatch.setattr(pkg, "resolve", fake_resolve)

    def configure(project, should_fail):
        error = None
        try:
            pkg.configure_for(str(project / "main.btrc"))
        except IncludeResolutionError as caught:
            error = caught
        configured.wait(timeout=10)
        packages = pkg.configured_packages()
        paths = pkg.package_import_paths("dep")
        assert (error is not None) is should_fail
        return packages, paths

    with ThreadPoolExecutor(max_workers=2) as executor:
        success_future = executor.submit(configure, success, False)
        failure_future = executor.submit(configure, failure, True)
        success_packages, success_paths = success_future.result(timeout=20)
        failure_packages, failure_paths = failure_future.result(timeout=20)

    assert success_packages["dep"]["path"] == str(dependency)
    assert success_paths == [str(dependency / "src" / "dep.btrc")]
    assert failure_packages == {}
    assert failure_paths == []
