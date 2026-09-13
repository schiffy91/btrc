"""Typed adapter emission, executed against Foundation behind a strict C11 ABI."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.frontend.packages import NativeGeneratedUnit, NativeLinkPlan, PackageTarget
from src.compiler.python.ir.nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRExprStmt,
    IRFunctionDecl,
    IRFunctionDef,
    IRIf,
    IRInclude,
    IRLiteral,
    IRModule,
    IRObjectiveCAutoreleasePool,
    IRObjectiveCBlock,
    IRObjectiveCClass,
    IRObjectiveCExceptionBoundary,
    IRObjectiveCMessage,
    IRObjectiveCMethod,
    IRObjectiveCSelector,
    IRParam,
    IRReturn,
    IRStatementSequence,
    IRStructField,
    IRVar,
    IRVarDecl,
)
from tools.native_plan import NativePlanBuilder, NativePlanError

REPO = Path(__file__).resolve().parents[3]


def context_module(mode="class"):
    configure = IRObjectiveCMethod(
        "configure:count:",
        CType("void"),
        [IRParam(CType("NativeProbe*"), "marker"), IRParam(CType("int"), "count")],
        IRBlock([IRAssign(IRVar("_marker"), IRVar("marker")), IRAssign(IRVar("_count"), IRVar("count"))]),
    )
    context = IRObjectiveCClass(
        "GeneratedContext",
        "NSObject",
        [IRStructField(CType("NativeProbe*"), "_marker"), IRStructField(CType("int"), "_count")],
        [
            configure,
            IRObjectiveCMethod(
                "value",
                CType("int"),
                [],
                IRBlock([IRReturn(IRBinOp(IRVar("_count"), "+", IRObjectiveCMessage(IRVar("_marker"), "value")))]),
            ),
            IRObjectiveCMethod("kind", CType("int"), [], IRBlock([IRReturn(IRLiteral("7"))]), is_class_method=True),
            IRObjectiveCMethod("dealloc", CType("void"), [], IRBlock([IRExprStmt(IRCall("contextDidClose"))])),
        ],
        protocols=["ContextValue"],
    )
    install = IRFunctionDef(
        "installNativeContext",
        CType("void"),
        [],
        IRBlock(
            [
                IRObjectiveCAutoreleasePool(
                    IRBlock(
                        [
                            IRVarDecl(
                                CType("GeneratedContext*"),
                                "context",
                                IRObjectiveCMessage(IRVar("GeneratedContext"), "new"),
                            ),
                            IRExprStmt(
                                IRObjectiveCMessage(
                                    IRVar("context"),
                                    "configure:count:",
                                    [
                                        IRObjectiveCMessage(IRVar("NativeProbe"), "makeMarker"),
                                        IRObjectiveCMessage(IRVar("GeneratedContext"), "kind"),
                                    ],
                                )
                            ),
                            IRExprStmt(
                                IRObjectiveCMessage(
                                    IRVar("NativeProbe"),
                                    "store:context:",
                                    [
                                        IRObjectiveCBlock(
                                            CType("int"),
                                            [],
                                            IRBlock([IRReturn(IRObjectiveCMessage(IRVar("context"), "value"))]),
                                        ),
                                        IRVar("context"),
                                    ],
                                )
                            ),
                        ]
                    )
                )
            ]
        ),
    )
    module = IRModule(
        language="objective-c",
        preprocessor_decls=[IRInclude("Probe.h", is_system=False)],
        objective_c_classes=[context],
        function_decls=[IRFunctionDecl("contextDidClose", CType("void"), is_static=True)],
        function_defs=[
            IRFunctionDef(
                "contextDidClose", CType("void"), [], IRBlock([IRExprStmt(IRCall("contextReleased"))]), is_static=True
            ),
            install,
        ],
    )
    if mode == "class-c":
        module.language = "c"
    elif mode == "class-name":
        context.name = "bad;name"
    elif mode == "class-super":
        context.superclass = context.name
    elif mode == "class-duplicate":
        module.objective_c_classes.append(context)
    elif mode == "class-order":
        module.objective_c_classes.insert(0, IRObjectiveCClass("Child", context.name))
    elif mode == "class-field":
        context.fields[0].name = "isa"
    elif mode == "class-field-duplicate":
        context.fields.append(context.fields[0])
    elif mode == "class-field-void":
        context.fields[0].c_type = CType("void")
    elif mode == "class-field-array":
        context.fields[0].array_size = IRLiteral("2")
    elif mode == "class-method":
        context.methods.append(configure)
    elif mode == "class-arity":
        configure.selector = "configure:"
    elif mode == "class-param":
        configure.params[0].name = "self"
    elif mode == "class-param-duplicate":
        configure.params[1].name = "marker"
    elif mode == "class-param-void":
        configure.params[0].c_type = CType("void")
    elif mode == "class-body":
        configure.body = IRLiteral("0")
    elif mode == "class-protocol-name":
        context.protocols = ["Invalid;Protocol"]
    elif mode == "class-protocol-duplicate":
        context.protocols = ["ContextValue", "ContextValue"]
    elif mode == "class-protocol-list":
        context.protocols = None
    elif mode == "class-cleanup":
        configure.body = IRBlock(
            [
                IRVarDecl(
                    CType("void*"),
                    "unregistered",
                    is_volatile=True,
                    cleanup_slot=IRCleanupSlot("unregistered", CType("void*"), "takeContext"),
                )
            ]
        )
    return module


def adapter_module(mode=""):
    if mode.startswith("class"):
        return context_module(mode)
    if mode.startswith("bridge-"):
        operation = mode.removeprefix("bridge-")
        cast = IRCast(CType("void*"), IRVar("value"), bridge="borrow")
        cast.bridge = "borrow" if operation in {"c", "realtime"} else operation
        definition = IRFunctionDef(
            "bridgeValue",
            CType("void*"),
            [IRParam(CType("void*"), "value")],
            IRBlock([IRReturn(cast)]),
            is_realtime=operation == "realtime",
        )
        return IRModule(language="c" if operation == "c" else "objective-c", function_defs=[definition])
    message = IRObjectiveCMessage(IRVar("NSString"), "stringWithUTF8String:", [IRLiteral('"guitar"')])
    block = IRObjectiveCBlock(
        CType("int"),
        [IRParam(CType("int"), "delta")],
        IRBlock(
            [
                IRIf(
                    IRBinOp(IRVar("fail"), "==", IRVar("delta")),
                    IRBlock(
                        [IRExprStmt(IRObjectiveCMessage(IRVar("value"), "substringFromIndex:", [IRLiteral("999")]))]
                    ),
                ),
                IRExprStmt(IRObjectiveCMessage(IRVar("held"), "description")),
                IRReturn(
                    IRBinOp(IRVar("delta"), "+", IRCast(CType("int"), IRObjectiveCMessage(IRVar("value"), "length")))
                ),
            ]
        ),
    )
    notification = IRObjectiveCBlock(
        CType("void"),
        [],
        IRBlock([IRExprStmt(IRObjectiveCMessage(IRVar("held"), "recordDelivery")), IRReturn()]),
    )
    pool = IRObjectiveCAutoreleasePool(
        IRBlock(
            [
                IRExprStmt(IRObjectiveCMessage(IRVar("NativeProbe"), "makeMarker")),
                IRVarDecl(CType("NativeProbe*"), "held", IRObjectiveCMessage(IRVar("NativeProbe"), "makeMarker")),
                IRVarDecl(CType("NSString*"), "value", message),
                IRVarDecl(
                    CType("int"),
                    "transformed",
                    IRObjectiveCMessage(IRVar("NativeProbe"), "apply:notify:", [block, notification]),
                ),
                IRExprStmt(IRObjectiveCMessage(IRVar("held"), "description")),
                IRReturn(
                    IRBinOp(
                        IRBinOp(
                            IRBinOp(
                                IRObjectiveCMessage(IRVar("value"), "length"),
                                "+",
                                IRObjectiveCMessage(
                                    IRObjectiveCMessage(
                                        IRVar("NSNumber"), "numberWithUnsignedLong:", [IRLiteral("4294967296UL")]
                                    ),
                                    "unsignedLongValue",
                                ),
                            ),
                            "+",
                            IRVar("transformed"),
                        ),
                        "+",
                        IRObjectiveCMessage(IRVar("value"), "compare:options:", [IRVar("value"), IRLiteral("0")]),
                    )
                ),
            ]
        )
    )
    boundary = IRObjectiveCExceptionBoundary(pool.body, IRBlock([IRReturn(IRLiteral("999"))]))
    pool.body = IRBlock([boundary])
    definition = IRFunctionDef("nativeLength", CType("unsigned long"), [IRParam(CType("int"), "fail")], IRBlock([pool]))
    module = IRModule(
        language="objective-c", preprocessor_decls=[IRInclude("Probe.h", False)], function_defs=[definition]
    )
    if mode == "c":
        module.language = "c"
    elif mode == "language":
        module.language = "swift"
    elif mode == "arity":
        message.selector = "stringWithUTF8String"
    elif mode == "identifier":
        message.selector = "invalid];:"
    elif mode == "pool":
        pool.body = IRLiteral("0")
    elif mode == "failure":
        boundary.failure = IRLiteral("0")
    elif mode == "realtime":
        definition.is_realtime = True
    elif mode.startswith("block-"):
        operation = mode.removeprefix("block-")
        block.body = IRBlock([IRReturn(IRVar("delta"))])
        definition.body = IRBlock([IRExprStmt(block)])
        if operation == "c":
            module.language = "c"
        elif operation == "realtime":
            definition.is_realtime = True
        elif operation == "body":
            block.body = IRLiteral("0")
        elif operation == "name":
            block.params[0].name = "delta);"
        elif operation == "duplicate":
            block.params.append(IRParam(CType("int"), "delta"))
        elif operation == "void":
            block.params[0].c_type = CType("void")
        elif operation == "result":
            block.return_type = ""
        elif operation == "params":
            block.params = None
    return module


@pytest.fixture(scope="module", params=["reference", "selfhost"])
def emitter_probe(request, tmp_path_factory):
    root = tmp_path_factory.mktemp(f"objc-emitter-{request.param}")
    source = REPO / "src/tests/native/objective_c/ObjectiveCEmitter.btrc"
    generated = root / "Emitter.c"
    if request.param == "reference":
        command = [sys.executable, "-m", "src.compiler.python.main", "--no-cache", str(source), "-o", str(generated)]
    else:
        command = [str(request.getfixturevalue("semantic_btrcc")), str(source)]
    compiled = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=180)
    assert compiled.returncode == 0, compiled.stderr
    if request.param == "selfhost":
        generated.write_text(compiled.stdout)
    executable = root / "Emitter"
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
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert built.returncode == 0, built.stderr
    return executable


@pytest.mark.parametrize(
    "mode",
    [
        "c",
        "language",
        "arity",
        "identifier",
        "pool",
        "failure",
        "realtime",
        "bridge-invalid",
        "bridge-c",
        "bridge-realtime",
        "block-c",
        "block-realtime",
        "block-body",
        "block-name",
        "block-duplicate",
        "block-void",
        "block-result",
        "block-params",
        "class-c",
        "class-name",
        "class-super",
        "class-duplicate",
        "class-order",
        "class-field",
        "class-field-duplicate",
        "class-field-void",
        "class-field-array",
        "class-method",
        "class-arity",
        "class-param",
        "class-param-duplicate",
        "class-param-void",
        "class-body",
        "class-protocol-name",
        "class-protocol-duplicate",
        "class-protocol-list",
    ],
)
def test_adapter_rejects_invalid_ir(emitter_probe, mode):
    with pytest.raises((ValueError, TypeError)):
        CEmitter().emit(adapter_module(mode))
    result = subprocess.run([str(emitter_probe), mode], capture_output=True, text=True, timeout=15)
    assert result.returncode != 0, result.stdout
    assert "Objective-C" in result.stderr or "translation-unit language" in result.stderr


def test_adapter_emission_parity(emitter_probe):
    result = subprocess.run([str(emitter_probe)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout == CEmitter().emit(adapter_module())
    assert not IRStatementSequence(adapter_module().function_defs[0].body.stmts).may_fall_through()


@pytest.mark.parametrize(
    "selector", ["invoke", "btrcInvoke:", "configure:source:", "", ":", "bad::", "bad:tail", "bad];:", "9bad", "écho"]
)
@pytest.mark.parametrize("language", ["objective-c", "c"])
def test_native_selector_emission(emitter_probe, selector, language):
    module = IRModule(
        language=language,
        function_defs=[
            IRFunctionDef("actionSelector", CType("SEL"), [], IRBlock([IRReturn(IRObjectiveCSelector(selector))]))
        ],
    )
    result = subprocess.run(
        [str(emitter_probe), "selector", selector, language], capture_output=True, text=True, timeout=15
    )
    if language == "objective-c" and selector in {"invoke", "btrcInvoke:", "configure:source:"}:
        assert result.returncode == 0, result.stderr
        assert result.stdout == CEmitter().emit(module)
    else:
        with pytest.raises((ValueError, TypeError)):
            CEmitter().emit(module)
        assert result.returncode != 0
        assert "Objective-C" in result.stderr


def test_native_class_emission_parity(emitter_probe):
    result = subprocess.run([str(emitter_probe), "class"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout == CEmitter().emit(context_module())


def test_native_method_roots_survive_selfhost_optimizer(emitter_probe):
    result = subprocess.run([str(emitter_probe), "class-roots"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "roots-ok\n"


def test_native_methods_validate_cleanup_metadata(emitter_probe):
    with pytest.raises(ValueError, match="cleanup slot metadata has no registration"):
        CEmitter().emit(context_module("class-cleanup"))
    result = subprocess.run([str(emitter_probe), "class-cleanup"], capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "cleanup slot metadata has no registration" in result.stderr


@pytest.mark.parametrize("entrypoint", ["header", "implementation"])
def test_native_classes_cannot_be_silently_dropped_from_c_archives(entrypoint):
    with pytest.raises(ValueError, match="separate translation units"):
        if entrypoint == "header":
            CEmitter().emit_header(context_module())
        else:
            CEmitter().emit_impl(context_module(), "Program.h")


@pytest.mark.parametrize("operation", ["borrow", "retain", "transfer"])
def test_native_bridge_emission_parity(emitter_probe, operation):
    mode = f"bridge-{operation}"
    result = subprocess.run([str(emitter_probe), mode], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout == CEmitter().emit(adapter_module(mode))


def test_generated_adapter_plan_parity(emitter_probe):
    result = subprocess.run([str(emitter_probe), "plan"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    plan = NativeLinkPlan(
        PackageTarget.parse("macos-arm64"),
        generated_units=(
            NativeGeneratedUnit("ObjectiveCAdapters", "objective-c", "c11", "arc", CEmitter().emit(adapter_module())),
        ),
    )
    assert result.stdout == plan.canonical_json()


@pytest.mark.parametrize("optimization", ["-O0", "-O2", "sanitize"])
@pytest.mark.parametrize("protocol_contract", ["complete", "inherited", "missing-required", "wrong-result"])
def test_generated_context_survives_stored_block_and_releases_once(
    emitter_probe, tmp_path, optimization, protocol_contract
):
    if sys.platform != "darwin":
        pytest.skip("requires the Apple Foundation runtime")
    result = subprocess.run([str(emitter_probe), "class"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout == CEmitter().emit(context_module())
    (tmp_path / "Adapter.m").write_text(result.stdout)
    protocol = {
        "complete": "@protocol ContextValue\n- (int)value;\n@end\n",
        "inherited": "@protocol ContextParent <NSObject>\n- (int)value;\n@end\n"
        "@protocol ContextValue <ContextParent>\n@optional\n- (BOOL)shouldClose;\n@end\n",
        "missing-required": "@protocol ContextParent\n- (BOOL)requiredAnswer;\n@end\n"
        "@protocol ContextValue <ContextParent>\n- (int)value;\n@end\n",
        "wrong-result": "@protocol ContextValue\n- (double)value;\n@end\n",
    }[protocol_contract]
    (tmp_path / "Probe.h").write_text(
        "#import <Foundation/Foundation.h>\n"
        "void contextReleased(void);\n" + protocol + "@interface NativeProbe : NSObject\n"
        "+ (instancetype)makeMarker;\n+ (void)store:(int (^)(void))action context:(id<ContextValue>)context;\n- (int)value;\n@end\n"
    )
    (tmp_path / "Probe.m").write_text(
        '#import "Probe.h"\n#include <assert.h>\n'
        "static int live, released; static int (^stored)(void);\n"
        "void contextReleased(void) { ++released; }\n"
        "int liveMarkers(void) { return live; }\nint releasedContexts(void) { return released; }\n"
        "int invokeStored(void) { assert(stored); return stored(); }\n"
        "void clearStored(void) { [stored release]; stored = nil; }\n"
        "@implementation NativeProbe\n"
        "+ (instancetype)makeMarker { ++live; return [[[self alloc] init] autorelease]; }\n"
        "+ (void)store:(int (^)(void))action context:(id<ContextValue>)context { assert(!stored); assert([context value] == 13); stored = [action copy]; }\n"
        "- (int)value { return 6; }\n"
        "- (void)dealloc { --live; [super dealloc]; }\n@end\n"
    )
    (tmp_path / "Caller.c").write_text(
        "#include <assert.h>\nvoid installNativeContext(void);\n"
        "int liveMarkers(void); int releasedContexts(void); int invokeStored(void); void clearStored(void);\n"
        "int main(void) { for (int i = 0; i < 1000; ++i) {\n"
        "installNativeContext(); assert(liveMarkers() == 1); assert(releasedContexts() == i);\n"
        "assert(invokeStored() == 13); assert(invokeStored() == 13);\n"
        "assert(releasedContexts() == i); clearStored();\n"
        "assert(liveMarkers() == 0); assert(releasedContexts() == i + 1);\n"
        "clearStored(); assert(releasedContexts() == i + 1); } return 0; }\n"
    )
    environment = os.environ.copy()
    environment.pop("DEVELOPER_DIR", None)
    environment.pop("SDKROOT", None)
    instrumentation = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if optimization == "sanitize" else []
    payload = NativeLinkPlan(
        PackageTarget.parse(None),
        generated_units=(NativeGeneratedUnit("Context", "objective-c", "c11", "arc", result.stdout),),
    ).as_dict()
    payload["packages"] = [{"dependencies": {}, "name": "probe", "root": str(tmp_path)}]
    payload["include-directories"] = [{"package": "probe", "path": str(tmp_path)}]
    payload["frameworks"] = [{"name": "Foundation", "package": "probe"}]
    payload["units"] = [
        {"language": "objective-c", "package": "probe", "path": str(tmp_path / "Probe.m"), "standard": "c11"}
    ]
    plan_path = tmp_path / "Program.link.json"
    plan_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")

    def run_command(command, **kwargs):
        return subprocess.run([command[0], *instrumentation, *command[1:]], env=environment, timeout=60, **kwargs)

    executable = tmp_path / "Caller"
    builder = NativePlanBuilder(runner=run_command)
    build_arguments = dict(
        plan_path=plan_path,
        generated_c=tmp_path / "Caller.c",
        output=executable,
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
        optimization=1 if instrumentation else int(optimization[-1]),
    )
    if protocol_contract in {"missing-required", "wrong-result"}:
        diagnostic = (
            "method 'requiredAnswer' in protocol 'ContextParent' not implemented"
            if protocol_contract == "missing-required"
            else "conflicting return type in declaration of 'value'"
        )
        with pytest.raises(NativePlanError, match=diagnostic):
            builder.build(**build_arguments)
        assert not executable.exists()
        return
    builder.build(**build_arguments)
    run = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("optimization", ["-O0", "-O2", "sanitize", "plan"])
def test_foundation_adapter_lifetime_and_exception(emitter_probe, tmp_path, optimization):
    if sys.platform != "darwin":
        pytest.skip("requires the Apple Foundation runtime")
    result = subprocess.run([str(emitter_probe)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    # Both independent emitters must produce the actual code that is executed.
    assert result.stdout == CEmitter().emit(adapter_module())
    (tmp_path / "Adapter.m").write_text(result.stdout)
    (tmp_path / "Probe.h").write_text(
        "#import <Foundation/Foundation.h>\n@interface NativeProbe : NSObject\n+ (instancetype)makeMarker;\n"
        "+ (int)apply:(int (^)(int))transform notify:(void (^)(void))notify;\n"
        "- (void)recordDelivery;\n@end\n"
    )
    (tmp_path / "Probe.m").write_text(
        '#import "Probe.h"\n'
        "static int live;\n"
        "static int delivered;\n"
        "int liveMarkers(void) { return live; }\n"
        "int deliveredNotifications(void) { return delivered; }\n"
        "@implementation NativeProbe\n"
        "+ (instancetype)makeMarker { ++live; return [[[self alloc] init] autorelease]; }\n"
        "+ (int)apply:(int (^)(int))transform notify:(void (^)(void))notify {\n"
        "  int first = transform(1);\n"
        "  int second = transform(2);\n"
        "  [[NSProcessInfo processInfo] performActivityWithOptions:NSActivityUserInitiated\n"
        '    reason:@"Native block adapter test" usingBlock:notify];\n'
        "  return first + second;\n}\n"
        "- (void)recordDelivery { ++delivered; }\n"
        "- (void)dealloc { --live; [super dealloc]; }\n"
        "@end\n"
    )
    (tmp_path / "Caller.c").write_text(
        "#include <assert.h>\n"
        "unsigned long nativeLength(int fail);\n"
        "int liveMarkers(void);\n"
        "int deliveredNotifications(void);\n"
        "int main(void) {\n"
        "  for (int i = 0; i < 1000; ++i) {\n"
        "    assert(nativeLength(0) == 4294967317UL); assert(liveMarkers() == 0);\n"
        "    assert(deliveredNotifications() == i + 1);\n"
        "    assert(nativeLength(1) == 999); assert(liveMarkers() == 0);\n"
        "    assert(nativeLength(2) == 999); assert(liveMarkers() == 0);\n"
        "    assert(deliveredNotifications() == i + 1);\n"
        "  }\n"
        "  return 0;\n"
        "}\n"
    )
    environment = os.environ.copy()
    environment.pop("DEVELOPER_DIR", None)
    environment.pop("SDKROOT", None)
    if optimization == "plan":
        (tmp_path / "Adapter.m").write_text('#error "the plan must use its embedded adapter, not this file"\n')
        result = subprocess.run([str(emitter_probe), "plan"], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        payload["packages"] = [{"dependencies": {}, "name": "probe", "root": str(tmp_path)}]
        payload["include-directories"] = [{"package": "probe", "path": str(tmp_path)}]
        payload["frameworks"] = [{"name": "Foundation", "package": "probe"}]
        payload["units"] = [
            {"language": "objective-c", "package": "probe", "path": str(tmp_path / "Probe.m"), "standard": "c11"}
        ]
        plan_path = tmp_path / "Program.link.json"
        plan_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
        commands = []

        def run_command(command, **kwargs):
            commands.append(command)
            return subprocess.run(command, env=environment, **kwargs)

        executable = tmp_path / "Caller"
        NativePlanBuilder(runner=run_command).build(
            plan_path=plan_path,
            generated_c=tmp_path / "Caller.c",
            output=executable,
            cc="/usr/bin/clang",
            cxx="/usr/bin/clang++",
        )
        assert len([command for command in commands if "-fobjc-arc-exceptions" in command]) == 1
        assert not list(tmp_path.glob(".btrc-native-*"))
        run = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stderr
        return
    sdk = subprocess.run(
        ["/usr/bin/xcrun", "--show-sdk-path"], env=environment, capture_output=True, text=True, check=True
    ).stdout.strip()
    instrumentation = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if optimization == "sanitize" else []
    common = [
        "/usr/bin/clang",
        "-isysroot",
        sdk,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-O1" if instrumentation else optimization,
        *instrumentation,
    ]
    for name, flags in [
        ("Adapter.m", ["-fobjc-arc", "-fobjc-exceptions", "-fobjc-arc-exceptions"]),
        ("Probe.m", ["-fno-objc-arc"]),
        ("Caller.c", ["-pedantic-errors"]),
    ]:
        built = subprocess.run(
            [*common, *flags, "-c", str(tmp_path / name), "-o", str(tmp_path / f"{name}.o")],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert built.returncode == 0, built.stderr
    executable = tmp_path / "Caller"
    linked = subprocess.run(
        [
            "/usr/bin/clang",
            *instrumentation,
            *(str(tmp_path / f"{name}.o") for name in ("Adapter.m", "Probe.m", "Caller.c")),
            "-framework",
            "Foundation",
            "-o",
            str(executable),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert linked.returncode == 0, linked.stderr
    run = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
