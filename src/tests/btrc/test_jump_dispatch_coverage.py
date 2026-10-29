"""Audit terminal-statement dispatchers when the language gains goto.

A helper may intentionally ignore jumps, but that decision belongs here with
its reason. Moving a goto branch into another method does not satisfy the
control-flow visitor's contract.
"""

from __future__ import annotations

import ast
from dataclasses import fields, is_dataclass
from functools import cache
from pathlib import Path

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import (
    BinaryExpr,
    CaseClause,
    ClassDecl,
    FunctionDecl,
    Identifier,
    MethodDecl,
)

ROOT = Path(__file__).resolve().parents[3] / "src/compiler"

# Return-specific inference and structural traversals do not model execution.
# Restricted targets reject jumps through their existing default refusal.
EXCEPTIONS = {
    "python/backend/wgsl_emitter.py:WgslEmitter._emit_stmt": "The default arm raises an unsupported WGSL statement error.",
    "python/analyzer/gpu.py:GpuKernelValidator._validate_statement": "The default arm diagnoses the statement through _STATEMENT_LABELS.",
    "python/analyzer/ownership.py:OwnershipAnalyzer._raw_parameter_uses_are_safe": "Checks every expression for parameter escape; a jump has no expression or parameter reference.",
    "python/analyzer/ownership.py:OwnershipAnalyzer.owned_transfer_param_indices": "Only unconditional leading consumes and an optional final void return qualify; any jump or label rejects the proof.",
    "python/analyzer/expressions.py:ExpressionAnalyzer._collect_lambda_return_types": "Collects syntactic return values, with no completion or reachability decision.",
    "python/analyzer/flow.py:ControlFlowAnalyzer.contains_loop_break": "Finds only break targeting this loop; goto exits are handled by the callable jump index.",
    "btrc/analyzer/Generics.btrc:GenericSpecializer.collectMethodGenericsStmt": "Collects generic types in expressions; jump names are not value expressions.",
    "btrc/analyzer/Generics.btrc:GenericSpecializer.upgradeStmtGenericArgs": "Upgrades type-bearing children; goto and label have none.",
    "btrc/analyzer/Generics.btrc:GenericSpecializer.collectGenericsStmt": "Collects generic types in expressions; jump names are not value expressions.",
    "btrc/analyzer/Generics.btrc:GenericSpecializer.genericClosureWalkNode": "Discovers generic call/conversion demands in structural children, independently of completion.",
    "btrc/analyzer/GPU.btrc:GpuKernelValidator.validateStatement": "The default arm refuses the statement through statementLabel, which names goto and label.",
    "btrc/analyzer/Declarations.btrc:DeclarationRegistry.ownedTransferParameters": "Only leading consumes and an optional final void return qualify; every other statement rejects the proof.",
    "btrc/analyzer/Expressions.btrc:ExpressionTypeResolver.inferredLambdaReturnInStatement": "Finds the first syntactic return type; completion is owned by ControlFlowValidator.",
    "btrc/analyzer/validation/Borrows.btrc:BorrowValidator.rawParamStmtSafe": "Proves all expression uses nonescaping; jumps and labels carry no parameter value.",
    "btrc/analyzer/validation/ControlFlow.btrc:ControlFlowValidator.containsLoopBreak": "Finds only break targeting this loop; goto exits belong to the callable jump index.",
    "btrc/ir/gpu/Pipeline.btrc:GpuPipeline.planStatement": "Plans only kernel calls and CPU fallback returns; other statements remain unhandled for StatementLowerer.",
    "btrc/ir/gpu/Wgsl.btrc:GpuWgslEmitter.gpuWgslStmt": "The default arm calls gpuLoweringFail for every unsupported statement.",
    "btrc/ir/optimization/Cleanup.btrc:JavaAdapterValidator.kindName": "Formats an already rejected JNI-adapter statement; unknown kinds retain the generic diagnostic.",
}


def walk(node):
    yield node
    if is_dataclass(node):
        for field in fields(node):
            value = getattr(node, field.name)
            for child in value if isinstance(value, list) else (value,):
                if is_dataclass(child):
                    yield from walk(child)


@cache
def native_program(path):
    return Parser(Lexer(path.read_text(), str(path)).tokenize()).parse()


def native_methods(path):
    for owner in native_program(path).declarations:
        for method in owner.members if isinstance(owner, ClassDecl) else (owner,):
            if isinstance(method, (MethodDecl, FunctionDecl)):
                yield f"{path.relative_to(ROOT)}:{owner.name}.{method.name}", method


def native_dispatches(method):
    names = set()
    for node in walk(method.body):
        values = ()
        if isinstance(node, BinaryExpr) and node.op in ("==", "!="):
            values = (node.left, node.right)
        elif isinstance(node, CaseClause):
            values = (node.value,)
        names.update(value.name for value in values if isinstance(value, Identifier))
    return names


def python_methods(path):
    for owner in ast.parse(path.read_text()).body:
        for method in owner.body if isinstance(owner, ast.ClassDef) else (owner,):
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = set()
                for node in ast.walk(method):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "isinstance":
                        for value in ast.walk(node.args[1]):
                            if isinstance(value, ast.Name):
                                names.add(value.id)
                            elif isinstance(value, ast.Attribute):
                                names.add(value.attr)
                yield f"{path.relative_to(ROOT)}:{owner.name}.{method.name}", names


def test_terminal_dispatchers_handle_goto_or_have_a_reviewed_reason():
    missing = set()
    checked = set()
    for path in (ROOT / "python").rglob("*.py"):
        if path.name == "generated.py":
            continue
        for name, kinds in python_methods(path):
            for triggers, jump in (({"ReturnStmt", "BreakStmt"}, "GotoStmt"), ({"IRBreak"}, "IRGoto")):
                if kinds & triggers:
                    checked.add(name)
                    if jump not in kinds:
                        missing.add(name)
    for path in (ROOT / "btrc").rglob("*.btrc"):
        if "generated" in path.parts:
            continue
        source = path.read_text()
        if not any(kind in source for kind in ("NK_RETURN_STMT", "NK_BREAK_STMT", "IRK_BREAK")):
            continue
        for name, method in native_methods(path):
            kinds = native_dispatches(method)
            for triggers, jump in (({"NK_RETURN_STMT", "NK_BREAK_STMT"}, "NK_GOTO_STMT"), ({"IRK_BREAK"}, "IRK_GOTO")):
                if kinds & triggers:
                    checked.add(name)
                    if jump not in kinds:
                        missing.add(name)
    assert checked, "the inventory must discover real dispatchers"
    assert all(EXCEPTIONS.values())
    assert missing == EXCEPTIONS.keys(), (
        f"unreviewed: {missing - EXCEPTIONS.keys()}; obsolete: {EXCEPTIONS.keys() - missing}"
    )


# These readers receive a narrower node contract from their caller, construct
# the node themselves, or render its label identity without a value lookup.
NAME_READ_CONTRACTS = {
    "btrc/ir/Emitter.btrc:CEmitter.qualifiedDeclType": (
        {"declaration"},
        "Called only for IRK_VAR_DECL in emitStmt and for-init emission.",
    ),
    "btrc/ir/Emitter.btrc:CEmitter.localDeclarator": (
        {"declaration"},
        "Called only for IRK_VAR_DECL in emitStmt and for-init emission.",
    ),
    "btrc/ir/Model.btrc:IRCanonicalRenderer.child": (
        {"node"},
        "Serializes every node's raw fields; a label name remains label metadata.",
    ),
    "btrc/ir/lowering/Declarations.btrc:DeclarationLowerer.nativeSnapshotPlane": (
        {"dimension", "pointer", "span", "pitch", "stride", "address", "offset"},
        "All named nodes are local IRNode.variable products, including the dimensions vector.",
    ),
    "btrc/ir/lowering/Declarations.btrc:DeclarationLowerer.nativeSnapshotSpan": (
        {"length", "pointer"},
        "Both nodes are constructed locally with IRNode.variable.",
    ),
    "btrc/ir/lowering/Declarations.btrc:DeclarationLowerer.nativeRecordSnapshot": (
        {"pointer", "length", "owner"},
        "All three nodes are constructed locally with IRNode.variable.",
    ),
    "btrc/ir/lowering/Expressions.btrc:ExpressionLowerer.finishOwnedConstruction": (
        {"declaration"},
        "Construction callers pass their freshly created variable declaration, never a statement-list element.",
    ),
    "btrc/ir/lowering/Expressions.btrc:ExpressionLowerer.irEvaluateConcatPart": (
        {"value"},
        "The concat owner passes an IRNode.variable for its materialized operand.",
    ),
    "btrc/ir/lowering/ownership/Calls.btrc:OwnershipBoundary.registerCleanup": (
        {"declaration"},
        "Receives the materialized owner's variable declaration; registerCleanupSlot validates its kind.",
    ),
    "btrc/ir/lowering/ownership/Lifetime.btrc:CleanupSlotRegistry.registerSlot": (
        {"declaration"},
        "An entry guard calls fail for every kind except IRK_VAR_DECL.",
    ),
    "btrc/ir/optimization/setjmp/Analysis.btrc:SetjmpPointerFlow.declare": (
        {"declaration"},
        "Called from the IRK_VAR_DECL flow branch; global declarations are materialized as the same kind.",
    ),
    "btrc/ir/optimization/setjmp/Analysis.btrc:SetjmpEffectAnalysis.flowSequence": (
        {"statement"},
        "The earlier non-label arm continues; this name identifies the backward label's pending edge.",
    ),
    "btrc/ir/optimization/setjmp/Safety.btrc:SetjmpSafetyPlanner.visibleAutomatic": (
        {"declaration"},
        "The visible vector is populated only with IRK_VAR_DECL nodes by scanBlock and scanFor.",
    ),
    "btrc/ir/optimization/setjmp/Safety.btrc:SetjmpSafetyPlanner.registerDeclaration": (
        {"declaration"},
        "Only the declaration visibility path calls this storage-specific helper.",
    ),
    "btrc/ir/optimization/setjmp/Safety.btrc:SetjmpSafetyPlanner.markVisible": (
        {"declaration"},
        "The visible vector contains automatic variable declarations, not arbitrary statements.",
    ),
}


def kind_guards(expression, truth=True):
    """Variables restricted to a specific IR kind on this branch."""
    from src.compiler.python.syntax.ast.generated import FieldAccessExpr

    if not isinstance(expression, BinaryExpr):
        return set()
    if expression.op in ("&&", "||"):
        left = kind_guards(expression.left, truth)
        right = kind_guards(expression.right, truth)
        return left | right if (expression.op == "&&") == truth else left & right
    if expression.op != ("==" if truth else "!="):
        return set()
    for value, kind in ((expression.left, expression.right), (expression.right, expression.left)):
        if (
            isinstance(value, FieldAccessExpr)
            and value.field == "kind"
            and isinstance(value.obj, Identifier)
            and isinstance(kind, Identifier)
            and kind.name.startswith("IRK_")
        ):
            return {value.obj.name}
    return set()


def unchecked_name_reads(node, variables, guarded=frozenset()):
    from src.compiler.python.syntax.ast.generated import AssignExpr, FieldAccessExpr, IfStmt

    if isinstance(node, IfStmt):
        yield from unchecked_name_reads(node.condition, variables, guarded)
        yield from unchecked_name_reads(node.then_block, variables, guarded | kind_guards(node.condition))
        yield from unchecked_name_reads(node.else_block, variables, guarded | kind_guards(node.condition, False))
        return
    if isinstance(node, BinaryExpr) and node.op in ("&&", "||"):
        yield from unchecked_name_reads(node.left, variables, guarded)
        yield from unchecked_name_reads(node.right, variables, guarded | kind_guards(node.left, node.op == "&&"))
        return
    if isinstance(node, AssignExpr) and node.op == "=":
        # A factory's assignment to its new node's name is not a name lookup.
        if not (isinstance(node.target, FieldAccessExpr) and node.target.field == "name"):
            yield from unchecked_name_reads(node.target, variables, guarded)
        yield from unchecked_name_reads(node.value, variables, guarded)
        return
    if isinstance(node, FieldAccessExpr) and node.field == "name" and isinstance(node.obj, Identifier):
        if node.obj.name in variables and node.obj.name not in guarded:
            yield node.obj.name, node.line
    if is_dataclass(node):
        for field in fields(node):
            value = getattr(node, field.name)
            for child in value if isinstance(value, list) else (value,):
                if is_dataclass(child):
                    yield from unchecked_name_reads(child, variables, guarded)


def test_ir_name_readers_keep_label_names_out_of_value_namespaces():
    from src.compiler.python.syntax.ast.generated import Param, VarDeclStmt

    unchecked = {}
    for path in (ROOT / "btrc").rglob("*.btrc"):
        if "generated" in path.parts:
            continue
        source = path.read_text()
        if "IRNode" not in source or ".name" not in source:
            continue
        for name, method in native_methods(path):
            variables = {
                node.name
                for node in walk(method)
                if isinstance(node, (Param, VarDeclStmt)) and node.type is not None and node.type.base == "IRNode"
            }
            reads = list(unchecked_name_reads(method.body, variables))
            if reads:
                unchecked[name] = reads
    actual = {name: {variable for variable, _line in reads} for name, reads in unchecked.items()}
    expected = {name: variables for name, (variables, _reason) in NAME_READ_CONTRACTS.items()}
    assert all(reason for _variables, reason in NAME_READ_CONTRACTS.values())
    assert actual == expected, unchecked
