"""Structured C++ ownership operations executed behind an actual C11 ABI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.frontend.packages import NativeGeneratedUnit, NativeLinkPlan, PackageTarget
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRCast,
    IRCxxDelete,
    IRCxxExceptionBoundary,
    IRCxxNew,
    IRExprStmt,
    IRFunctionDef,
    IRInclude,
    IRLiteral,
    IRModule,
    IRParam,
    IRReturn,
    IRVar,
)
from src.compiler.python.ir.verifier import IRVerifier
from src.tests.python.test_native_import_consumer import apple_environment
from tools.native_plan import NativePlanBuilder

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", params=["reference", "selfhost"])
def emitted_adapter(request, tmp_path_factory):
    root = tmp_path_factory.mktemp("cpp-emitter")
    source = REPO / "src/tests/btrc/fixtures/CppEmitter.btrc"
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
            "/usr/bin/clang",
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
    emitted = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
    assert emitted.returncode == 0, emitted.stderr
    assert emitted.stdout.rstrip() == CEmitter().emit(adapter_module()).rstrip()
    return emitted.stdout


def adapter_module():
    failure = IRBlock([IRExprStmt(IRCall("abort"))])
    return IRModule(
        language="c++",
        preprocessor_decls=[IRInclude("Probe.hpp", is_system=False)],
        function_defs=[
            IRFunctionDef(
                "createProbe",
                CType("void*"),
                [IRParam(CType("int"), "mode")],
                IRBlock(
                    [
                        IRCxxExceptionBoundary(
                            IRBlock([IRReturn(IRCxxNew(CType("sdk::Probe"), [IRVar("mode")]))]),
                            failure,
                            IRBlock([IRReturn(IRLiteral("NULL"))]),
                        )
                    ]
                ),
                c_linkage=True,
            ),
            IRFunctionDef(
                "deleteProbe",
                CType("void"),
                [IRParam(CType("void*"), "value")],
                IRBlock(
                    [
                        IRCxxExceptionBoundary(
                            IRBlock([IRCxxDelete(IRCast(CType("sdk::Probe*"), IRVar("value")))]),
                            failure,
                        )
                    ]
                ),
                c_linkage=True,
            ),
            IRFunctionDef("livingProbes", CType("int"), [], IRBlock([IRReturn(IRVar("sdk::living"))]), c_linkage=True),
        ],
    )


@pytest.mark.parametrize("mode", ["wrong-language", "static-linkage", "new-arguments", "delete-value", "failure-body"])
def test_cpp_ir_rejects_invalid_adapter_contract(mode):
    module = adapter_module()
    if mode == "wrong-language":
        module.language = "c"
    elif mode == "static-linkage":
        module.function_defs[0].is_static = True
    elif mode == "new-arguments":
        module.function_defs[0].body.stmts[0].body.stmts[0].value.args = ["raw"]
    elif mode == "delete-value":
        module.function_defs[1].body.stmts[0].body.stmts[0].value = "raw"
    else:
        module.function_defs[0].body.stmts[0].allocation_failure = IRLiteral("0")
    with pytest.raises((TypeError, ValueError), match=r"C\+\+|C language"):
        IRVerifier(module).validate()


@pytest.mark.parametrize("sanitize", [False, True])
def test_cpp_new_delete_and_exception_boundary_cross_c_abi(tmp_path, sanitize, emitted_adapter):
    if sys.platform != "darwin":
        pytest.skip("actual SDK compiler qualification runs on macOS")
    (tmp_path / "Probe.hpp").write_text("""#include <new>
#include <cstdlib>
namespace sdk {
static int living = 0;
class Probe {
public:
    explicit Probe(int mode) { if (mode == 1) throw std::bad_alloc(); if (mode == 2) throw 42; ++living; }
    ~Probe() { --living; }
};
}
""")
    main = tmp_path / "Main.c"
    main.write_text("""#include <assert.h>
#include <stdlib.h>
void *createProbe(int mode);
void deleteProbe(void *value);
int livingProbes(void);
int main(int argc, char **argv) {
    (void)argv;
    if (argc > 1) { createProbe(2); return 9; }
    for (int i = 0; i < 100; ++i) {
        void *value = createProbe(0); assert(value && livingProbes() == 1);
        deleteProbe(value); assert(livingProbes() == 0);
        assert(createProbe(1) == NULL && livingProbes() == 0);
    }
    return 0;
}
""")
    unit = NativeGeneratedUnit("Probe", "c++", "c++17", "raii", emitted_adapter)
    payload = NativeLinkPlan(PackageTarget.parse(None), generated_units=(unit,)).as_dict()
    payload["packages"] = [{"dependencies": {}, "name": "probe", "root": str(tmp_path)}]
    payload["include-directories"] = [{"package": "probe", "path": str(tmp_path)}]
    plan = tmp_path / "Main.link.json"
    plan.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    environment = apple_environment()
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []

    def run_command(command, **kwargs):
        return subprocess.run([command[0], *flags, *command[1:]], env=environment, timeout=60, **kwargs)

    executable = tmp_path / "Main"
    NativePlanBuilder(runner=run_command).build(
        plan_path=plan,
        generated_c=main,
        output=executable,
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
        optimization=1 if sanitize else 2,
    )
    result = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    unexpected = subprocess.run([str(executable), "throw"], env=environment, capture_output=True, text=True, timeout=10)
    assert unexpected.returncode == -6, unexpected.stderr
