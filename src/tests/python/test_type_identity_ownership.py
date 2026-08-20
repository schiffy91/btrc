"""Ownership and isolation contracts for compiler type identity policy."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.ir.lowering.generics import TypeSubstitution
from src.compiler.python.syntax.ast.generated import TypeExpr

PYTHON_COMPILER = Path(__file__).parents[2] / "compiler" / "python"


def test_type_policy_modules_expose_no_loose_behavior_functions() -> None:
    for relative_path in (
        "analyzer/types.py",
        "ir/lowering/types.py",
    ):
        tree = ast.parse((PYTHON_COMPILER / relative_path).read_text())
        functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert functions == [], f"{relative_path} exposes loose behavior: {functions}"


def test_pipeline_passes_one_identity_to_concrete_analyzer() -> None:
    identity = TypeIdentity()
    pipeline = CompilationPipeline(type_identity=identity)
    analyzer = pipeline._new_analyzer()

    assert analyzer.types._type_identity is identity


def test_pipeline_constructs_concrete_stage_owners_without_factory_seams() -> None:
    source = ast.parse((PYTHON_COMPILER / "application/pipeline.py").read_text())
    annotations = {node.id for node in ast.walk(source) if isinstance(node, ast.Name)}
    assert "Callable" not in annotations
    assert not any(isinstance(node, ast.arg) and node.arg.endswith("_factory") for node in ast.walk(source))


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


def test_type_substitution_deeply_snapshots_mutable_type_inputs() -> None:
    argument = TypeExpr(
        base="Pair",
        generic_args=[TypeExpr(base="int")],
    )
    typedef = TypeExpr(
        base="Box",
        generic_args=[TypeExpr(base="string")],
    )
    arguments = {"T": argument}
    typedefs = {"Alias": typedef}
    substitution = TypeSubstitution(arguments, typedefs, TypeIdentity())

    argument.base = "MutatedPair"
    argument.generic_args[0].base = "float"
    typedef.generic_args[0].base = "bool"
    arguments["T"] = TypeExpr(base="Replacement")
    typedefs.clear()

    first = substitution.resolve(TypeExpr(base="T"))
    alias = substitution._thaw(substitution._typedef_values)["Alias"]
    assert first == TypeExpr(base="Pair", generic_args=[TypeExpr(base="int")])
    assert alias == TypeExpr(base="Box", generic_args=[TypeExpr(base="string")])

    first.base = "LocallyMutated"
    first.generic_args.clear()
    alias.generic_args.clear()
    assert substitution.resolve(TypeExpr(base="T")) == TypeExpr(
        base="Pair",
        generic_args=[TypeExpr(base="int")],
    )
    assert substitution._thaw(substitution._typedef_values)["Alias"] == TypeExpr(
        base="Box",
        generic_args=[TypeExpr(base="string")],
    )
    assert isinstance(substitution._argument_values, tuple)
    assert isinstance(substitution._typedef_values, tuple)
    with pytest.raises(FrozenInstanceError):
        substitution._argument_values = ()


def test_type_substitution_detects_parameters_through_frozen_typedef_chains() -> None:
    substitution = TypeSubstitution(
        {"T": TypeExpr(base="int")},
        {
            "Value": TypeExpr(base="T"),
            "Nested": TypeExpr(base="Vector", generic_args=[TypeExpr(base="Value")]),
        },
        TypeIdentity(),
    )

    assert substitution.applies_to(TypeExpr(base="Nested"))
    assert not substitution.applies_to(TypeExpr(base="Unrelated"))


def test_pipeline_passes_one_identity_to_concrete_lowerer() -> None:
    source = ast.parse((PYTHON_COMPILER / "application/pipeline.py").read_text())
    lower_method = next(node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == "lower")
    lowerer_call = next(
        node
        for node in ast.walk(lower_method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "IRLowerer"
    )
    keyword = next(item for item in lowerer_call.keywords if item.arg == "type_identity")

    assert isinstance(keyword.value, ast.Attribute)
    assert isinstance(keyword.value.value, ast.Name)
    assert keyword.value.value.id == "self"
    assert keyword.value.attr == "type_identity"
