"""Real-array ``for-in`` extent and backing-lifetime parity."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import IRCall, IRFieldAccess, IRFor, IRNode, IRSizeof, IRStmtExpr, IRVar, IRVarDecl
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_gpu_boundary import _compile_with_stub
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _source(*, generic: bool) -> str:
    runner = "class Runner<T> { public int run() { return exercise(); } }" if generic else ""
    invocation = (
        "Runner<int> runner = new Runner<int>(); assert(runner.run() == 171); delete runner;"
        if generic
        else "assert(exercise() == 171);"
    )
    return f"""
        #include <assert.h>
        int drops = 0;
        int makeCalls = 0;
        int globalValues[] = {{19, 23}};

        struct Packet {{ int values[3]; }};

        Packet makePacket() {{
            makeCalls += 1;
            Packet packet;
            packet.values[0] = 11;
            packet.values[1] = 13;
            packet.values[2] = 17;
            return packet;
        }}

        class Holder {{
            public int values[3];
            public Holder(int base) {{
                self.values[0] = base;
                self.values[1] = base + 1;
                self.values[2] = base + 2;
            }}
            public void __del__() {{ drops += 1; }}
        }}

        int exercise() {{
            int ordinary[] = {{2, 3, 5}};
            int ordinarySum = 0;
            int ordinaryCount = 0;
            for ordinaryValue in ordinary {{
                ordinarySum += ordinaryValue;
                ordinaryCount += 1;
            }}
            assert(ordinarySum == 10 && ordinaryCount == 3);

            int globalSum = 0;
            for globalValue in globalValues {{ globalSum += globalValue; }}
            assert(globalSum == 42);

            static int cached[] = {{29, 31}};
            int staticSum = 0;
            for staticValue in cached {{ staticSum += staticValue; }}
            assert(staticSum == 60);

            int holderSum = 0;
            int holderCount = 0;
            for holderValue in (new Holder(5)).values {{
                assert(drops == 0);
                holderSum += holderValue;
                holderCount += 1;
            }}
            assert(holderSum == 18 && holderCount == 3);
            assert(drops == 1);

            int packetSum = 0;
            int packetCount = 0;
            for packetValue in makePacket().values {{
                assert(makeCalls == 1);
                packetSum += packetValue;
                packetCount += 1;
            }}
            assert(packetSum == 41 && packetCount == 3);
            assert(makeCalls == 1);
            return ordinarySum + globalSum + staticSum
                + holderSum + packetSum;
        }}

        {runner}

        int main() {{
            {invocation}
            return 0;
        }}
    """


def test_reference_projection_extent_uses_stable_physical_storage() -> None:
    program = Parser(Lexer(_source(generic=False), "<fixed-array-forin>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    module = IRLowerer(analyzed).lower()
    exercise = next(function for function in module.function_defs if function.name == "exercise")
    statements = exercise.body.stmts

    def call_names(value) -> list[str]:
        return [
            node.callee
            for node in IRNode.walk_value(value)
            if isinstance(node, IRCall) and isinstance(node.callee, str)
        ]

    assert sum(call_names(statement).count("Holder_new") for statement in statements) == 1
    assert sum(call_names(statement).count("makePacket") for statement in statements) == 1

    projection_extents: dict[bool, tuple[int, IRFieldAccess]] = {}
    bare_extent_roots = set()
    for index, statement in enumerate(statements):
        if not isinstance(statement, IRVarDecl):
            continue
        sizeofs = [node for node in IRNode.walk_value(statement.init) if isinstance(node, IRSizeof)]
        for sizeof in sizeofs:
            assert not any(isinstance(node, (IRCall, IRStmtExpr)) for node in IRNode.walk_value(sizeof.operand))
        direct = next(
            (sizeof.operand for sizeof in sizeofs if isinstance(sizeof.operand, (IRFieldAccess, IRVar))),
            None,
        )
        if isinstance(direct, IRVar):
            bare_extent_roots.add(direct.name)
        elif isinstance(direct, IRFieldAccess) and direct.field == "values":
            projection_extents[direct.arrow] = (index, direct)

    assert {"ordinary", "globalValues", "cached"} <= bare_extent_roots
    assert set(projection_extents) == {False, True}
    managed_extent_index, managed_projection = projection_extents[True]
    value_extent_index, value_projection = projection_extents[False]
    assert isinstance(managed_projection.obj, IRVar)
    assert isinstance(value_projection.obj, IRVar)

    managed_call_index = next(
        index for index, statement in enumerate(statements) if "Holder_new" in call_names(statement)
    )
    value_call_index = next(
        index for index, statement in enumerate(statements) if "makePacket" in call_names(statement)
    )
    managed_loop_index = next(
        index
        for index, statement in enumerate(statements)
        if index > managed_extent_index and isinstance(statement, IRFor)
    )
    value_loop_index = next(
        index
        for index, statement in enumerate(statements)
        if index > value_extent_index and isinstance(statement, IRFor)
    )
    release_index = next(
        index
        for index, statement in enumerate(statements)
        if index > managed_loop_index and any(name.startswith("__btrc_arc_release") for name in call_names(statement))
    )
    assert managed_call_index < managed_extent_index < managed_loop_index < release_index
    assert value_call_index < value_extent_index < value_loop_index


def test_generic_gpu_result_array_forin_smoke(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        @gpu int[] copy(int[] values) {
            int index = gpu_id();
            return values[index];
        }
        class Runner<T> {
            public int run() {
                int[] input = {3, 5};
                var output = copy(input);
                int sum = 0;
                for value in output { sum += value; }
                return sum;
            }
        }
        int main() {
            Runner<int> runner = new Runner<int>();
            int result = runner.run();
            delete runner;
            return result == 8 ? 0 : 1;
        }
    """
    for frontend, generated in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        build_dir = tmp_path / f"{frontend}-gpu-result"
        build_dir.mkdir()
        binary = _compile_with_stub(
            generated.read_text(),
            build_dir,
            "gpu_unavailable_stub.c",
        )
        run = _run([str(binary)], timeout=30)
        assert run.returncode == 0, run.stderr


def _compile_both(semantic_btrcc: Path, tmp_path: Path, source: str):
    self_dir = tmp_path / "selfhost"
    reference_dir = tmp_path / "reference"
    self_dir.mkdir()
    reference_dir.mkdir()
    selfhost, selfhost_c = _compile_source(semantic_btrcc, self_dir, source)
    reference, reference_c = _compile_reference_source(reference_dir, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return (("selfhost", selfhost_c), ("reference", reference_c))


def _strict_build_and_run(compiler: str, generated: Path, output: Path) -> None:
    build = _run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(output),
            "-lm",
            "-lpthread",
        ],
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    run = _run([str(output)], timeout=30)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("generic", [False, True], ids=["normal", "generic"])
def test_fixed_array_forin_is_strict_gcc_and_clang_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    generated = _compile_both(semantic_btrcc, tmp_path, _source(generic=generic))
    compilers = [path for name in ("gcc", "clang") if (path := shutil.which(name))]
    if not compilers:
        pytest.skip("strict GCC/Clang toolchains unavailable")
    for compiler in compilers:
        compiler_name = Path(compiler).name
        for frontend, source in generated:
            _strict_build_and_run(
                compiler,
                source,
                tmp_path / f"{frontend}-{compiler_name}",
            )


@pytest.mark.parametrize("generic", [False, True], ids=["normal", "generic"])
def test_fixed_array_forin_is_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    toolchain = require_sanitizers(tmp_path)
    for frontend, generated in _compile_both(
        semantic_btrcc,
        tmp_path,
        _source(generic=generic),
    ):
        sanitized_build_and_run(
            generated,
            tmp_path / f"{frontend}-fixed-array-forin-san",
            toolchain,
        )
