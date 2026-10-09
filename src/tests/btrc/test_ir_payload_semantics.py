"""Behavioral ownership and structural contracts for compact fat-tagged IR."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from src.tests.btrc.selfhost_snippet_harness import compile_source, run_in_repo, strict_build_and_run

REPO = Path(__file__).resolve().parents[3]
MODEL = REPO / "src/compiler/btrc/ir/Model.btrc"

DEFAULTS_AND_ALIASING = r"""
int main() {
    IRNode empty = IRNode();
    assert(empty.canFallThrough && empty.payload == null);
    assert(empty.args().len == 0 && empty.stmts().len == 0 && empty.fieldNames().len == 0);
    assert(empty.payload == null && empty.argsStorage == null);

    IRNode leaf = IRNode.variable("leaf");
    IRNode another = IRNode.literal("2");
    Vector<IRNode> statements = [IRNode.expressionStatement(leaf)];
    IRNode clause = IRNode.caseClause(null, statements, true);
    IRNode wrapper = IRNode.block(clause.stmts());
    wrapper.stmtsMut().push(IRNode.returnStatement(another));
    assert(clause.stmts().len == 2 && statements.len == 2);
    assert(((IRControlPayload)clause.payload).value == null);
    assert(((IRControlPayload)clause.payload).fallsThrough);
    assert(!((IRControlPayload)wrapper.payload).fallsThrough);
    ((IRControlPayload)wrapper.payload).stmtsStorage = [];
    assert(wrapper.stmts().len == 0 && clause.stmts().len == 2);

    IRNode unary = IRNode.unary("-", leaf, true);
    IRNode cast = IRNode.cast("id", leaf, "retain");
    IRNode field = IRNode.fieldAccess(leaf, "member", true);
    IRNode call = IRNode.call("invoke", [leaf]);
    IRNode declaration = IRNode.arrayDeclaration("int", "values", another, leaf);
    IRNode statement = IRNode.forStatement(null, leaf, null, wrapper);
    IRNode native = IRNode.cxxExceptionBoundary(wrapper, clause);
    IRNode source = IRNode.lineMarker("quoted\"file.btrc", 17);
    IRNode returned = IRNode.returnStatement(null);
    assert(((IRUnaryPayload)unary.payload).operand == leaf && ((IRUnaryPayload)unary.payload).prefix);
    assert(((IRConversionPayload)cast.payload).bridge == "retain" && cast.expr == leaf);
    assert(((IRProjectionPayload)field.payload).obj == leaf && ((IRProjectionPayload)field.payload).arrow);
    assert(((IRCallPayload)call.payload).callee == "invoke" && !((IRCallPayload)call.payload).neverReturns);
    assert(((IRDeclarationPayload)declaration.payload).arraySize == another && ((IRDeclarationPayload)declaration.payload).init == leaf);
    assert(((IRDeclarationPayload)declaration.payload).isArrayDecl && !((IRDeclarationPayload)declaration.payload).setjmpInferredVolatile);
    assert(((IRControlPayload)statement.payload).init == null && ((IRControlPayload)statement.payload).update == null);
    assert(((IRNativePayload)native.payload).body == wrapper && ((IRNativePayload)native.payload).elseBlock == clause);
    assert(((IRNativePayload)native.payload).thenBlock == null && ((IRNativePayload)native.payload).params == null);
    assert(((IRSourcePayload)source.payload).sourceLine == 17);
    assert(((IRValuePayload)returned.payload).value == null);
    assert(empty.payload == null && leaf.payload == null && another.payload == null);
    return 0;
}
"""

LIFETIME = r"""
int alive = 0;
int destroyed = 0;
class TrackedNode extends IRNode {
    public TrackedNode() {
        self.kind = IRK_NONE;
        self.text = ""; self.name = ""; self.op = "";
        self.storageRoot = ""; self.arrayStorageRoot = "";
        self.canFallThrough = true;
        alive++;
    }
    public void __del__() { alive--; destroyed++; }
}
void acyclic() {
    IRNode owner = IRNode.ifStatement(IRNode.literal("1"), IRNode.block([]), null);
    {
        TrackedNode child = TrackedNode();
        ((IRControlPayload)owner.payload).elseBlock = child;
    }
    assert(alive == 1 && destroyed == 0);
    ((IRControlPayload)owner.payload).elseBlock = null;
    assert(alive == 0 && destroyed == 1);
    {
        TrackedNode child = TrackedNode();
        ((IRControlPayload)owner.payload).thenBlock = child;
    }
    assert(alive == 1);
}
void cyclic() {
    IRNode owner = IRNode.ifStatement(IRNode.literal("1"), IRNode.block([]), null);
    TrackedNode child = TrackedNode();
    ((IRControlPayload)owner.payload).elseBlock = child;
    child.left = owner;
    assert(alive == 1);
}
int main() {
    acyclic();
    assert(alive == 0 && destroyed == 2);
    cyclic();
    assert(alive == 0 && destroyed == 3);
    return 0;
}
"""

CANONICAL_ORDER = r"""
int main() {
    IRNode leaf = IRNode.variable("leaf");
    IRNode block = IRNode.block([]);
    IRNode native = IRNode.cxxExceptionBoundary(block, IRNode.block([]), IRNode.block([]));
    IRNode body = IRNode.statementExpression([native], leaf);
    IRNode declaration = IRNode.arrayDeclaration("int", "values", IRNode.literal("3"), body);
    ((IRDeclarationPayload)declaration.payload).isVolatile = true;
    ((IRDeclarationPayload)declaration.payload).effectiveIsVolatile = true;
    ((IRDeclarationPayload)declaration.payload).setjmpInferredVolatile = true;
    ((IRDeclarationPayload)declaration.payload).isStatic = true;
    ((IRDeclarationPayload)declaration.payload).isExtern = true;
    ((IRDeclarationPayload)declaration.payload).isCycleReturnTemp = true;
    ((IRDeclarationPayload)declaration.payload).cleanupSlot = IRCleanupSlot(7, "values", "int", "takeValues");
    declaration.canFallThrough = false;
    IRFunction fn = IRFunction();
    fn.name = "fixture";
    fn.body = IRNode.block([IRNode.lineMarker("source.btrc", 9), declaration]);
    IRModule module = IRModule();
    module.functions.push(fn);
    string rendered = IRCanonicalRenderer().render(module);
    string expected = "$format btrcc-ir-v1\nmodule language=\"c\"\n  function name=\"fixture\" returnType=\"void\"\n    body: IRK_BLOCK\n      stmt: IRK_LINE_MARKER sourceFile=\"source.btrc\" line=9\n      stmt: IRK_VAR_DECL name=\"values\" cType=\"int\" arrayDecl volatile effectiveVolatile setjmpInferredVolatile static extern cycleReturnTemp noFallThrough\n        cleanupSlot site=7 name=\"values\" cType=\"int\" takeFunction=\"takeValues\"\n        arraySize: IRK_LITERAL text=\"3\"\n        init: IRK_STMT_EXPR\n          stmt: IRK_CXX_EXCEPTION_BOUNDARY\n            thenBlock: IRK_BLOCK\n            elseBlock: IRK_BLOCK\n            body: IRK_BLOCK\n          result: IRK_VAR name=\"leaf\"\n";
    assert(rendered == expected);
    assert(IRCanonicalRenderer().render(module) == expected);
    return 0;
}
"""


RARE_NATIVE_AND_METADATA = r"""
int main() {
    IRNode leaf = IRNode.variable("owner");
    IRNode block = IRNode.block([]);
    IRNode message = IRNode.objectiveCMessage(leaf, "accept:", [leaf]);
    IRNode selector = IRNode.objectiveCSelector("accept:");
    IRNode pool = IRNode.objectiveCAutoreleasePool(block);
    IRNode exception = IRNode.objectiveCExceptionBoundary(block, block);
    IRNode created = IRNode.cxxNew("Widget", [leaf]);
    IRNode deleted = IRNode.cxxDelete(leaf);
    IRNode nativeBlock = IRNode(IRK_OBJECTIVE_C_BLOCK);
    Vector<IRParam> signature = [IRParam("int", "argument")];
    ((IRNativePayload)nativeBlock.payload).params = signature;
    ((IRNativePayload)nativeBlock.payload).targetType = "void";
    ((IRNativePayload)nativeBlock.payload).body = block;
    signature.push(IRParam("long", "second"));
    assert(((IRNativePayload)nativeBlock.payload).params.len == 2);
    assert(((IRNativePayload)nativeBlock.payload).targetType == "void");
    assert(((IRNativePayload)nativeBlock.payload).body == block);
    assert(((IRNativePayload)message.payload).obj == leaf && message.name == "accept:" && message.args().get(0) == leaf);
    assert(selector.payload == null && selector.name == "accept:");
    assert(((IRNativePayload)pool.payload).body == block);
    assert(((IRNativePayload)exception.payload).body == block && ((IRNativePayload)exception.payload).elseBlock == block);
    assert(((IRNativePayload)created.payload).targetType == "Widget" && created.args().get(0) == leaf);
    assert(((IRNativePayload)deleted.payload).value == leaf);
    IRNode size = IRNode.sizeofExpression(leaf);
    assert(((IRConversionPayload)size.payload).operand == leaf);
    IRNode designator = IRNode.designation("", IRNode.literal("2"), leaf);
    assert(((IRProjectionPayload)designator.payload).index.text == "2" && ((IRProjectionPayload)designator.payload).value == leaf);
    Vector<string> names = ["member"];
    IRNode compound = IRNode.compoundLiteral("Record", names, [leaf]);
    names.push("second");
    assert(compound.fieldNames().len == 2 && compound.args().get(0) == leaf);
    IRNode field = IRNode.fieldAccess(leaf, "bits", false);
    ((IRProjectionPayload)field.payload).bitField = true;
    field.sourceAddress = true;
    field.storageRootKnown = true; field.storageRoot = "owner";
    field.arrayStorageKnown = true; field.arrayStorageRoot = "array";
    assert(((IRProjectionPayload)field.payload).bitField && field.sourceAddress);
    assert(IRNode.directStorageRoot(field) == "owner" && IRNode.arrayStorageRootValue(field) == "array");
    IRNode declared = IRNode.variableDeclaration("int", "slot", null);
    IRCleanupSlot slot = IRCleanupSlot(4, "slot", "int", "take");
    ((IRDeclarationPayload)declared.payload).cleanupSlot = slot;
    IRNode call = IRNode.call("invoke", []);
    ((IRCallPayload)call.payload).cleanupSlot = slot;
    ((IRCallPayload)call.payload).helperRef = "runtime";
    ((IRCallPayload)call.payload).realtimeProvenance = "certificate";
    ((IRCallPayload)call.payload).neverReturns = true;
    slot.takeFunction = "changed";
    assert(((IRCallPayload)call.payload).cleanupSlot.takeFunction == "changed");
    assert(((IRDeclarationPayload)declared.payload).cleanupSlot == slot);
    assert(((IRCallPayload)call.payload).helperRef == "runtime" && ((IRCallPayload)call.payload).realtimeProvenance == "certificate");
    assert(((IRCallPayload)call.payload).neverReturns && call.canFallThrough);
    IRNode loop = IRNode.forStatement(declared, leaf, null, block);
    ((IRControlPayload)loop.payload).realtimeBounded = true;
    assert(((IRControlPayload)loop.payload).realtimeBounded && ((IRControlPayload)loop.payload).init == declared);
    IRNode assignment = IRNode.assignment(field, leaf);
    assert(((IRValuePayload)assignment.payload).target == field && ((IRValuePayload)assignment.payload).value == leaf);
    return 0;
}
"""


@pytest.mark.parametrize(
    "body",
    [DEFAULTS_AND_ALIASING, LIFETIME, CANONICAL_ORDER, RARE_NATIVE_AND_METADATA],
    ids=[
        "defaults-and-case-aliasing",
        "payload-child-release-and-cycle",
        "canonical-metadata-order",
        "native-forms-and-shared-metadata",
    ],
)
def test_compact_ir_payload_semantics(compiler: str, request: pytest.FixtureRequest, tmp_path: Path, body: str) -> None:
    source = "import Library.Vector;\n" + f"import {json.dumps(str(MODEL))};\n" + "#include <assert.h>\n" + body
    if compiler == "btrc":
        compiled, generated = compile_source(
            request.getfixturevalue("semantic_btrcc"), tmp_path, source, no_stdlib=False
        )
    else:
        program = tmp_path / "program.btrc"
        generated = tmp_path / "program.c"
        program.write_text(source)
        compiled = run_in_repo(
            [
                sys.executable,
                "-m",
                "src.compiler.python.main",
                str(program),
                "--strict-imports",
                "--no-cache",
                "-o",
                str(generated),
            ],
            env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "reference-cache")},
            timeout=120,
        )
    assert compiled.returncode == 0, compiled.stderr
    strict_build_and_run(generated, tmp_path / "ir-payload-proof")
