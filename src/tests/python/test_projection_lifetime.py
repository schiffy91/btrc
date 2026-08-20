"""Lifetime contracts for raw projections into temporary owner storage."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import IRCall, IRNode
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

PROJECTION_SOURCE = r"""
#include <assert.h>

int holderDestructions = 0;

class ProjectionHolder {
    public int values[2];

    public ProjectionHolder(int first, int second) {
        self.values[0] = first;
        self.values[1] = second;
    }

    public void __del__() { holderDestructions++; }
}

ProjectionHolder makeProjectionHolder(int first, int second) {
    return new ProjectionHolder(first, second);
}

void consumeProjection(int[] values, int expected, int destructionsBefore) {
    assert(holderDestructions == destructionsBefore);
    assert(values[0] == expected);
}

void exerciseOrdinary() {
    int before = holderDestructions;
    consumeProjection(makeProjectionHolder(11, 13).values, 11, before);
    assert(holderDestructions == before + 1);
}

void exerciseImmediateLambda() {
    int before = holderDestructions;
    ((int[] values) => {
        assert(holderDestructions == before);
        assert(values[0] == 23);
    })(makeProjectionHolder(23, 29).values);
    assert(holderDestructions == before + 1);
}

class ProjectionReader<T> {
    public ProjectionReader() {}

    public void exercise() {
        int before = holderDestructions;
        consumeProjection(makeProjectionHolder(17, 19).values, 17, before);
        assert(holderDestructions == before + 1);
    }
}

int main() {
    exerciseOrdinary();
    exerciseImmediateLambda();
    ProjectionReader<int> reader = new ProjectionReader<int>();
    reader.exercise();
    delete reader;
    return 0;
}
"""

CALLABLE_PROJECTION_SOURCE = r"""
#include <assert.h>

extern string foreignString();

string makeOwnedString() { return f"owned={1}"; }

class CallableProjectionHolder {
    public int values[1];

    public CallableProjectionHolder(bool initialized) {
        self.values[0] = initialized ? 1 : 0;
    }
}

CallableProjectionHolder makeCallableProjectionHolder(bool initialized) {
    return new CallableProjectionHolder(initialized);
}

void consumeProjectionString(int[] values, string value) {
    assert(values[0] == 1);
    assert(len(value) == 7);
}

void exerciseCallableProjection() {
    __fn_ptr<string> callback = foreignString;
    consumeProjectionString(
        makeCallableProjectionHolder((bool)(callback = makeOwnedString)).values,
        callback()
    );
}

void exerciseCallableProjectionLambda() {
    __fn_ptr<string> callback = foreignString;
    ((int[] values, string value) => {
        assert(values[0] == 1);
        assert(len(value) == 7);
    })(
        makeCallableProjectionHolder((bool)(callback = makeOwnedString)).values,
        callback()
    );
}

class CallableProjectionReader<T> {
    public CallableProjectionReader() {}

    public void exercise() {
        __fn_ptr<string> callback = foreignString;
        consumeProjectionString(
            makeCallableProjectionHolder((bool)(callback = makeOwnedString)).values,
            callback()
        );
    }
}

int main() {
    exerciseCallableProjection();
    assert((int)callableProjectionLiveStrings() == 0);

    exerciseCallableProjectionLambda();
    assert((int)callableProjectionLiveStrings() == 0);

    CallableProjectionReader<int> reader = new CallableProjectionReader<int>();
    reader.exercise();
    delete reader;
    assert((int)callableProjectionLiveStrings() == 0);
    return 0;
}
"""


def _lower_projection_source():
    program = Parser(Lexer(PROJECTION_SOURCE, "<projection-lifetime>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    return IRLowerer(analyzed).lower()


def test_projection_owner_release_follows_outer_call_in_direct_generic_and_lambda_ir() -> None:
    module = _lower_projection_source()
    functions = {
        function.name: function
        for function in module.function_defs
        if function.name
        in {
            "exerciseOrdinary",
            "exerciseImmediateLambda",
            "btrc_ProjectionReader_int_exercise",
        }
    }
    assert set(functions) == {
        "exerciseOrdinary",
        "exerciseImmediateLambda",
        "btrc_ProjectionReader_int_exercise",
    }

    for function_name, function in functions.items():
        callees = [
            node.callee
            for node in IRNode.walk_value(function.body)
            if isinstance(node, IRCall) and isinstance(node.callee, str)
        ]
        make = callees.index("makeProjectionHolder")
        consume = next(
            index
            for index, callee in enumerate(callees)
            if callee == "consumeProjection"
            or (function_name == "exerciseImmediateLambda" and callee.startswith("__btrc_lambda_"))
        )
        release = next(
            index for index, callee in enumerate(callees) if index > consume and callee.startswith("__btrc_arc_release")
        )
        assert make < consume < release


def test_borrowed_hosted_projection_keeps_guard_before_later_effect() -> None:
    emitted = emit_c(r"""
        #include <string.h>

        string needle() { return "x"; }

        bool matchesAt(string text, int offset) {
            return strncmp((char*)text + offset, needle(), 1) == 0;
        }

        int main() { return matchesAt("ax", 1) ? 0 : 1; }
    """)

    start = emitted.rindex("bool matchesAt(")
    end = emitted.index("\n}", start)
    body = emitted[start:end]
    assert "__btrc_kept_operand" in body
    assert "__btrc_string_retain" in body


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_temporary_projection_owner_survives_call_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    source = tmp_path / "projection-lifetime.c"
    executable = tmp_path / f"projection-lifetime-{Path(c_compiler).name}"
    source.write_text(emit_c(PROJECTION_SOURCE))
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr

    executed = subprocess.run([executable], capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_deferred_projection_preserves_later_callable_ownership_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    emitted = emit_c(CALLABLE_PROJECTION_SOURCE)
    marker = "int main(void) {"
    observer = (
        'char* foreignString(void) { return (char*)"borrowed"; }\n\n'
        "static size_t callableProjectionLiveStrings(void) {\n"
        "    return __btrc_string_entry_count;\n"
        "}\n\n"
    )
    emitted = emitted.replace(marker, observer + marker, 1)
    source = tmp_path / "callable-projection-lifetime.c"
    executable = tmp_path / f"callable-projection-lifetime-{Path(c_compiler).name}"
    source.write_text(emitted)

    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr

    executed = subprocess.run([executable], capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr
