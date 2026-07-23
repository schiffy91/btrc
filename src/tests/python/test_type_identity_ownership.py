"""Ownership and isolation contracts for compiler type identity policy."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.pipeline.pipeline import CompilerPipeline
from src.compiler.python.type_identity import TypeIdentity

PYTHON_COMPILER = Path(__file__).parents[2] / "compiler" / "python"


def test_type_policy_modules_expose_no_loose_behavior_functions() -> None:
    for relative_path in (
        "type_identity.py",
        "operator_semantics.py",
        "index_protocol.py",
        "ir/gen/operator_context.py",
    ):
        tree = ast.parse((PYTHON_COMPILER / relative_path).read_text())
        functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert functions == [], f"{relative_path} exposes loose behavior: {functions}"


def test_pipeline_injects_its_identity_into_custom_analyzer_factory() -> None:
    received = []

    def analyzer_factory(*, type_identity):
        received.append(type_identity)

        class Analyzer:
            pass

        return Analyzer()

    identity = TypeIdentity()
    pipeline = CompilerPipeline(
        analyzer_factory=analyzer_factory,
        type_identity=identity,
    )

    pipeline._new_analyzer()

    assert received == [identity]


def test_identity_policy_is_immutable_and_isolated_per_composition() -> None:
    left = TypeIdentity(reserved_prefix="LEFT")
    right = TypeIdentity(reserved_prefix="RIGHT")
    structural = TypeExpr(
        base="Pair",
        generic_args=[TypeExpr(base="unsigned int")],
    )

    assert left.symbol_component(structural).startswith("LEFT")
    assert right.symbol_component(structural).startswith("RIGHT")
    assert left.symbol_component(structural) != right.symbol_component(structural)
    with pytest.raises(FrozenInstanceError):
        left._reserved_prefix = "MUTATED"


def test_pipeline_passes_one_identity_to_lowerer_factory() -> None:
    source = ast.parse((PYTHON_COMPILER / "pipeline/pipeline.py").read_text())
    lower_method = next(node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == "lower")
    factory_call = next(
        node
        for node in ast.walk(lower_method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_lowerer_factory"
    )
    keyword = next(item for item in factory_call.keywords if item.arg == "type_identity")

    assert isinstance(keyword.value, ast.Attribute)
    assert isinstance(keyword.value.value, ast.Name)
    assert keyword.value.value.id == "self"
    assert keyword.value.attr == "type_identity"
