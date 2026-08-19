"""Default-argument lowering state is owned by one compiler invocation."""

from __future__ import annotations

import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

from src.compiler.python.frontend.sources import SourceMap
from src.compiler.python.ir.lowering.calls import DefaultArgumentLoweringContext
from src.compiler.python.syntax.ast.generated import Identifier, TypeExpr

_LOWERING_DIR = Path(__file__).resolve().parents[2] / "compiler/python/ir/lowering"
_LEGACY_NAMES = {
    "call_argument_type",
    "default_argument_scope",
    "in_call_argument_context",
    "lower_call_argument",
    "resolve_default_predefined_identifier",
    "resolve_default_type",
}


def _parameter(**substitutions: TypeExpr):
    return SimpleNamespace(default_type_map=substitutions)


def test_nested_default_scopes_restore_types_and_declaration_provenance():
    context = DefaultArgumentLoweringContext()
    generic_type = TypeExpr(base="T")

    assert context.resolve_type(generic_type) == generic_type
    with context.scope(
        _parameter(T=TypeExpr(base="int")),
        function_name="outer",
        source_file="mapped.btrc",
        source_map=SourceMap(
            positions=tuple(("mapped.btrc", line + 10) for line in range(1, 5)),
            user_line_count=4,
            stdlib_line_count=0,
            split_spaces=True,
        ),
    ):
        assert context.resolve_type(generic_type) == TypeExpr(base="int")
        assert context.predefined_identifier(Identifier(name="__func__")) == '"outer"'
        assert context.predefined_identifier(Identifier(name="__LINE__", line=4)) == "14"
        assert context.predefined_identifier(Identifier(name="__FILE__", line=4)) == '"mapped.btrc"'

        # A scope with no replacement inherits the active declaration default.
        with context.scope(None):
            assert context.resolve_type(generic_type) == TypeExpr(base="int")

        with context.scope(
            _parameter(T=TypeExpr(base="string")),
            function_name="inner",
            source_file="inner.btrc",
        ):
            assert context.resolve_type(generic_type) == TypeExpr(base="string")
            assert context.predefined_identifier(Identifier(name="__func__")) == '"inner"'
            assert context.predefined_identifier(Identifier(name="__FILE__")) == '"inner.btrc"'

        assert context.resolve_type(generic_type) == TypeExpr(base="int")
        assert context.predefined_identifier(Identifier(name="__func__")) == '"outer"'

    assert context.resolve_type(generic_type) == generic_type
    assert context.predefined_identifier(Identifier(name="__func__")) is None


def test_one_owner_is_task_local_and_cannot_leak_into_another_owner():
    context = DefaultArgumentLoweringContext()
    independent = DefaultArgumentLoweringContext()
    generic_type = TypeExpr(base="T")

    async def resolve_in_scope(base: str) -> TypeExpr | None:
        with context.scope(_parameter(T=TypeExpr(base=base))):
            await asyncio.sleep(0)
            assert independent.resolve_type(generic_type) == generic_type
            await asyncio.sleep(0)
            return context.resolve_type(generic_type)

    async def exercise() -> list[TypeExpr | None]:
        return list(
            await asyncio.gather(
                resolve_in_scope("int"),
                resolve_in_scope("string"),
            )
        )

    assert asyncio.run(exercise()) == [TypeExpr(base="int"), TypeExpr(base="string")]
    assert context.resolve_type(generic_type) == generic_type


def test_one_owner_is_isolated_between_compiler_threads():
    context = DefaultArgumentLoweringContext()
    barrier = Barrier(2)
    generic_type = TypeExpr(base="T")

    def resolve_in_scope(base: str) -> TypeExpr | None:
        with context.scope(_parameter(T=TypeExpr(base=base))):
            barrier.wait(timeout=10)
            return context.resolve_type(generic_type)

    with ThreadPoolExecutor(max_workers=2) as executor:
        integer = executor.submit(resolve_in_scope, "int")
        text = executor.submit(resolve_in_scope, "string")
        assert integer.result(timeout=20) == TypeExpr(base="int")
        assert text.result(timeout=20) == TypeExpr(base="string")

    assert context.resolve_type(generic_type) == generic_type


def test_default_argument_state_has_one_explicit_owner_and_no_legacy_api():
    assert not (_LOWERING_DIR / "default_argument_context.py").exists()

    owner_module = ast.parse((_LOWERING_DIR / "calls.py").read_text())
    loose_functions = [
        node.name for node in owner_module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert loose_functions == []
    module_context_vars = [
        node
        for statement in owner_module.body
        if not isinstance(statement, ast.ClassDef)
        for node in ast.walk(statement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ContextVar"
    ]
    assert module_context_vars == []

    constructions = []
    legacy_references = []
    reachthrough = []
    for path in _LOWERING_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DefaultArgumentLoweringContext"
            ):
                constructions.append(path.relative_to(_LOWERING_DIR))
            if isinstance(node, ast.Name) and node.id in _LEGACY_NAMES:
                legacy_references.append((path, node.id))
            if isinstance(node, ast.Attribute) and node.attr in _LEGACY_NAMES:
                legacy_references.append((path, node.attr))
            if (
                isinstance(node, ast.Attribute)
                and node.attr in {"default_arguments", "_default_arguments"}
                and isinstance(node.value, ast.Name)
                and node.value.id in {"gen", "lowerer"}
            ):
                reachthrough.append((path, node.value.id, node.attr))

    assert constructions == [Path("lowerer.py")]
    assert legacy_references == []
    assert reachthrough == []
