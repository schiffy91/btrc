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
    IRBinOp,
    IRBlock,
    IRCast,
    IRExprStmt,
    IRFunctionDef,
    IRIf,
    IRInclude,
    IRLiteral,
    IRModule,
    IRObjectiveCAutoreleasePool,
    IRObjectiveCExceptionBoundary,
    IRObjectiveCMessage,
    IRParam,
    IRReturn,
    IRStatementSequence,
    IRVar,
    IRVarDecl,
)
from tools.native_plan import NativePlanBuilder

REPO = Path(__file__).resolve().parents[3]


def adapter_module(mode=""):
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
    pool = IRObjectiveCAutoreleasePool(
        IRBlock(
            [
                IRExprStmt(IRObjectiveCMessage(IRVar("NativeProbe"), "makeMarker")),
                IRVarDecl(CType("NativeProbe*"), "held", IRObjectiveCMessage(IRVar("NativeProbe"), "makeMarker")),
                IRVarDecl(CType("NSString*"), "value", message),
                IRIf(
                    IRVar("fail"),
                    IRBlock(
                        [IRExprStmt(IRObjectiveCMessage(IRVar("value"), "substringFromIndex:", [IRLiteral("999")]))]
                    ),
                ),
                IRExprStmt(IRObjectiveCMessage(IRVar("held"), "description")),
                IRReturn(
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
        "#import <Foundation/Foundation.h>\n@interface NativeProbe : NSObject\n+ (instancetype)makeMarker;\n@end\n"
    )
    (tmp_path / "Probe.m").write_text(
        '#import "Probe.h"\n'
        "static int live;\n"
        "int liveMarkers(void) { return live; }\n"
        "@implementation NativeProbe\n"
        "+ (instancetype)makeMarker { ++live; return [[[self alloc] init] autorelease]; }\n"
        "- (void)dealloc { --live; [super dealloc]; }\n"
        "@end\n"
    )
    (tmp_path / "Caller.c").write_text(
        "#include <assert.h>\n"
        "unsigned long nativeLength(int fail);\n"
        "int liveMarkers(void);\n"
        "int main(void) {\n"
        "  for (int i = 0; i < 1000; ++i) {\n"
        "    assert(nativeLength(0) == 4294967302UL); assert(liveMarkers() == 0);\n"
        "    assert(nativeLength(1) == 999); assert(liveMarkers() == 0);\n"
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
