"""Verifier rule 2 over malformed JNI adapters (native-interop-ownership.md section 4).

In a JNI adapter every throwing env call is immediately followed by its
ExceptionCheck branch, every path a successful PushLocalFrame dominates passes
PopLocalFrame (the translation that pops counts), and an owner created inside
the frame is registered in a cleanup slot before the next throwing env call.
Each case below breaks one clause of a well-formed adapter; the self-hosted
compiler's JavaAdapterValidator gives the same messages (JniAdapterVerifier.btrc).
"""

import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRDeref,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDef,
    IRFunctionRef,
    IRIf,
    IRLiteral,
    IRModule,
    IRReturn,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.ir.verifier import IRVerifier
from src.tests.runner import BTRC_TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]

ENV = "__btrc_java_env"


def env_call(slot, *arguments):
    return IRCall(IRFieldAccess(IRDeref(IRVar(ENV)), slot, arrow=True), [IRVar(ENV), *arguments])


def translate(pop, before=()):
    message = IRVar("message")
    return IRBlock(
        [
            *before,
            IRVarDecl(CType("char"), "message", array_size=IRLiteral("1024")),
            IRExprStmt(IRCall("btrcJavaTakeException", [IRVar(ENV), IRLiteral(pop), message, IRLiteral("1024")])),
            IRExprStmt(IRCall("__btrc_throw", [message], helper_ref="__btrc_throw", never_returns=True)),
        ]
    )


def check():
    return IRIf(env_call("ExceptionCheck"), translate("1"))


def push(pop="0", then=None):
    return IRIf(
        IRBinOp(env_call("PushLocalFrame", IRLiteral("2")), "!=", IRLiteral("0")),
        translate(pop) if then is None else then,
    )


def owner_slot():
    slot = IRVarDecl(CType("struct Owner*"), "object", init=IRLiteral("NULL"), is_volatile=True)
    slot.cleanup_slot = IRCleanupSlot("object", slot.c_type, "take")
    registration = IRCall(
        "__btrc_register_direct_cleanup",
        [IRCast(CType("void*"), IRAddressOf(IRVar("object"))), IRFunctionRef("take"), IRFunctionRef("release")],
        helper_ref="__btrc_register_direct_cleanup",
        cleanup_slot=slot.cleanup_slot,
    )
    return slot, IRExprStmt(registration)


def adapter(case):
    """A well-formed object-returning adapter, with one clause broken per `case`."""
    statements = [IRVarDecl(CType("JNIEnv*"), ENV, init=IRCall("btrcJavaEnvironment", []))]
    if case == "outside-frame":
        statements.extend([IRVarDecl(CType("jobject"), "early", init=env_call("NewStringUTF")), check()])
    statements.append(
        IRExprStmt(env_call("PushLocalFrame", IRLiteral("2")))
        if case == "unchecked-push"
        else push("1")
        if case == "push-pops"
        else push(then=IRBlock([IRExprStmt(IRCall("fputs", []))]))
        if case == "push-continues"
        else push()
    )
    statements.append(IRVarDecl(CType("jclass"), "owner", init=IRCall("btrcJavaClass", [IRVar(ENV)])))
    if case != "unchecked-helper":
        statements.append(check())
    statements.append(IRVarDecl(CType("jobject"), "result", init=env_call("CallStaticObjectMethodA", IRVar("owner"))))
    if case != "unchecked-call":
        statements.append(check())
    if case == "unchecked-copy":
        # A natives thunk's string copy leaves its Java exception pending, as a JNI call does.
        statements.append(
            IRVarDecl(CType("char*"), "text", init=IRCall("btrcJavaCopyString", [IRVar(ENV), IRVar("result")]))
        )
    slot, registration = owner_slot()
    created = IRAssign(IRVar("object"), IRCall("__btrc_unique_Owner_new", []))
    global_reference = IRVarDecl(CType("jobject"), "global", init=env_call("NewGlobalRef", IRVar("result")))
    if case == "unregistered-owner":
        statements.extend([slot, created, global_reference, check(), registration])
    else:
        statements.extend([slot, registration, created, global_reference, check()])
    if case == "throw-pushed":
        statements.append(
            IRExprStmt(IRCall("__btrc_throw", [IRLiteral('"boom"')], helper_ref="__btrc_throw", never_returns=True))
        )
    if case != "missing-pop":
        statements.append(IRExprStmt(env_call("PopLocalFrame", IRLiteral("NULL"))))
    statements.append(IRReturn(IRVar("object")))
    return IRFunctionDef("adapter", CType("struct Owner*"), body=IRBlock(statements), is_static=True)


CASES = [
    ("valid", None),
    ("unchecked-call", "Java adapter adapter: CallStaticObjectMethodA is not followed by its ExceptionCheck branch"),
    ("unchecked-helper", "Java adapter adapter: btrcJavaClass is not followed by its ExceptionCheck branch"),
    ("unchecked-copy", "Java adapter adapter: btrcJavaCopyString is not followed by its ExceptionCheck branch"),
    ("outside-frame", "Java adapter adapter: NewStringUTF runs outside its local frame"),
    ("unchecked-push", "Java adapter adapter: PushLocalFrame must be checked by its failure branch"),
    ("push-pops", "Java adapter adapter: an exception translation pops a frame it did not push"),
    ("push-continues", "Java adapter adapter: a failed PushLocalFrame continues"),
    ("missing-pop", "Java adapter adapter returns with its local frame pushed"),
    ("throw-pushed", "Java adapter adapter throws with its local frame pushed"),
    ("unregistered-owner", "Java adapter adapter: owner object is not registered before NewGlobalRef"),
]


@pytest.mark.parametrize(("case", "message"), CASES, ids=[case for case, _ in CASES])
def test_rule_two_rejects_each_malformed_adapter(case, message):
    verifier = IRVerifier(IRModule(function_defs=[adapter(case)]))
    if message is None:
        verifier.validate_java_adapters()
        return
    with pytest.raises(ValueError) as raised:
        verifier.validate_java_adapters()
    assert str(raised.value) == message


def test_functions_without_a_java_environment_are_not_adapters():
    body = IRBlock([IRExprStmt(IRCall("NewGlobalRef", [])), IRReturn(None)])
    IRVerifier(IRModule(function_defs=[IRFunctionDef("plain", CType("void"), body=body)])).validate_java_adapters()


@pytest.fixture(scope="module", params=["reference", "selfhost"])
def validator_report(request, tmp_path_factory):
    """The self-hosted JavaAdapterValidator's verdict per case, compiled by each compiler."""
    root = tmp_path_factory.mktemp(f"jni-verifier-{request.param}")
    source = REPO / "src/tests/btrc/fixtures/JniAdapterVerifier.btrc"
    generated = root / "Probe.c"
    if request.param == "reference":
        command = [sys.executable, "-m", "src.compiler.python.main", "--no-cache", str(source), "-o", str(generated)]
    else:
        command = [str(request.getfixturevalue("semantic_btrcc")), str(source)]
    compiled = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=BTRC_TRANSPILE_TIMEOUT)
    assert compiled.returncode == 0, compiled.stderr
    if request.param == "selfhost":
        generated.write_text(compiled.stdout, encoding="utf-8")
    executable = root / "Probe"
    built = subprocess.run(
        [
            "cc",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(generated),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    return dict(line.split(": ", 1) for line in ran.stdout.splitlines())


def test_self_hosted_validator_gives_the_same_messages(validator_report):
    expected = {case: message or "" for case, message in CASES}
    expected["plain"] = ""
    assert {case: message.rstrip() for case, message in validator_report.items()} == expected
