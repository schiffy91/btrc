"""Lexical call targets win before global and compiler special forms."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from src.tests.btrc.production_readiness_harness import (
    compile_diagnostic_pair,
    run_strict_pair,
)
from src.tests.btrc.string_coercion_harness import compile_pair
from src.tests.btrc.test_semantic_validation import REPO

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


CALLABLE_SHADOW_SOURCE = """
    int combine(int left, int right) { return left + right; }
    int len(int left, int right) { return left + right; }
    int print(int left, int right) { return left + right; }
    int Mutex(int left, int right) { return left + right; }
    int gpu_id(int value) { return value + 1; }
    int plusOne(int value) { return value + 1; }
    int add(int left, int right) { return left + right; }
    int answer() { return 42; }

    class FieldSpelling {}
    class MethodSpelling {}
    class MemberNamespaceProbe {
        public int FieldSpelling;
        public MemberNamespaceProbe() { self.FieldSpelling = 0; }
        public int MethodSpelling() { return self.FieldSpelling + 1; }
    }

    int invokeClosureShadow() {
        int offset = 2;
        var print = (int value) => value + offset;
        return print(40);
    }

    int invoke(
        __fn_ptr<int, int> combine,
        __fn_ptr<int, int, int> len,
        __fn_ptr<int> Mutex,
        __fn_ptr<int, int> gpu_id,
        __fn_ptr<int, int> print
    ) {
        return combine(41) + len(20, 22) + Mutex()
            + gpu_id(41) + print(41);
    }

    class GenericInvoker<T> {
        public int invoke(
            __fn_ptr<int, int> combine,
            __fn_ptr<int, int, int> len,
            __fn_ptr<int> Mutex,
            __fn_ptr<int, int> print
        ) {
            return combine(41) + len(20, 22)
                + Mutex() + print(41);
        }

        public int constructOrdinaryClass() {
            MemberNamespaceProbe probe = MemberNamespaceProbe();
            probe.FieldSpelling = 41;
            int result = probe.MethodSpelling();
            delete probe;
            return result;
        }
    }

    int main() {
        GenericInvoker<int> generic = new GenericInvoker<int>();
        MemberNamespaceProbe probe = new MemberNamespaceProbe();
        int tm = 0;
        probe.FieldSpelling = 41;
        int result = invoke(
            plusOne, add, answer, plusOne, plusOne);
        return result == 210
            && generic.invoke(plusOne, add, answer, plusOne) == 168
            && generic.constructOrdinaryClass() == 42
            && invokeClosureShadow() == 42
            && combine(20, 22) == 42
            && len(20, 22) == 42
            && print(20, 22) == 42
            && Mutex(20, 22) == 42
            && gpu_id(41) == 42
            && probe.MethodSpelling() == 42
            && tm == 0
            ? 0 : 1;
    }
"""


HOSTED_SHADOW_SOURCE = """
    import std.bytes;
    import std.vector;

    size_t strlen(string value, int marker = 40) {
        return (size_t)(value.length() + marker);
    }

    void* memcpy(
        void* destination,
        const void* source,
        size_t count,
        int marker = 7
    ) {
        if (source == null && count == (size_t)marker) { return null; }
        return destination;
    }

    void free(Bytes value, int marker = 7) {
        delete value;
    }

    int main() {
        Bytes bytes = Bytes.fromString("abc");
        Vector<string> parts = [];
        parts.push("a");
        parts.push("b");
        string joined = parts.join("-");
        size_t sourceLength = strlen("abc");
        bool valid = bytes.len == 3
            && joined == "a-b"
            && sourceLength == (size_t)43;
        delete bytes;
        delete parts;
        return valid ? 0 : 1;
    }
"""


HOSTED_VALUE_PROBE = """
    #include <string.h>

    size_t wrapperDirect(string value) {
        return strlen(value);
    }

    size_t wrapperIndirect(string value) {
        __fn_ptr<size_t, string> callback = strlen;
        return callback(value);
    }

"""


HOSTED_VALUE_USER = """
    size_t strlen(string value) {
        (void)value;
        return (size_t)777;
    }

    int main() {
        return wrapperDirect("abc") == (size_t)3
            && wrapperIndirect("abc") == (size_t)3
            && strlen("abc") == (size_t)777 ? 0 : 1;
    }
"""


HOSTED_VALUE_GENERIC_PROBE = """
    #include <string.h>

    class HostedValueGeneric<T> {
        public size_t measure(string value) {
            __fn_ptr<size_t, string> callback = strlen;
            return callback(value);
        }
    }
"""


HOSTED_VALUE_GENERIC_USER = """
    size_t strlen(string value) {
        (void)value;
        return (size_t)777;
    }

    int main() {
        HostedValueGeneric<int> probe = new HostedValueGeneric<int>();
        size_t result = probe.measure("abc");
        delete probe;
        return result == (size_t)3 ? 0 : 1;
    }
"""


HOSTED_VALUE_NO_SHADOW = """
    #include <string.h>

    int main() {
        __fn_ptr<size_t, string> callback = strlen;
        return callback("abc") == (size_t)3 ? 0 : 1;
    }
"""


SOURCE_VALUE_HOSTED_SPELLING = """
    #include <string.h>

    size_t strlen(string value) {
        return value.length();
    }

    int main() {
        __fn_ptr<size_t, string> callback = strlen;
        return callback("abc") == (size_t)3 ? 0 : 1;
    }
"""


def _custom_stdlib_root(tmp_path: Path, probe: str, user_path: Path) -> Path:
    root = tmp_path / "hosted-value-data"
    language = root / "language"
    stdlib = root / "stdlib"
    language.mkdir(parents=True)
    stdlib.mkdir()
    shutil.copy2(REPO / "src/language/grammar.ebnf", language / "grammar.ebnf")
    for source in (REPO / "src/stdlib").glob("*.btrc"):
        shutil.copy2(source, stdlib / source.name)
    (stdlib / "hosted_value_probe.btrc").write_text(f"import {json.dumps(str(user_path))};\n{probe}")
    return root


NONCALLABLE_SHADOWS = (
    pytest.param(
        "int helper(int value) { return value; } int main() { int helper = 1; return helper(1); }",
        id="source-function",
    ),
    pytest.param(
        "int main() { int len = 1; return len(1); }",
        id="len-builtin",
    ),
    pytest.param(
        "int main() { int print = 1; return print(1); }",
        id="print-builtin",
    ),
    pytest.param(
        "int main() { int Mutex = 1; return Mutex(1); }",
        id="mutex-special-form",
    ),
    pytest.param(
        "int main() { int gpu_id = 1; return gpu_id(); }",
        id="gpu-special-form",
    ),
)


TYPE_SHADOWS = (
    pytest.param(
        "class Box {} int main() { int Box = 1; Box value = new Box(); bool valid = Box == 1 && value != null; delete value; return valid ? 0 : 1; }",
        id="class-local",
    ),
    pytest.param(
        "struct Point { int x; }; int run(int Point) { Point value = {Point}; return value.x == Point ? 0 : 1; } int main() { return run(7); }",
        id="struct-parameter",
    ),
    pytest.param(
        "typedef int Count; int main() { int Count = 1; Count other = 2; return Count + other == 3 ? 0 : 1; }",
        id="typedef-local",
    ),
    pytest.param(
        "class Box<T> { public T run(T T) { T value = T; return value; } } int main() { Box<int> box = new Box<int>(); bool valid = box.run(7) == 7; delete box; return valid ? 0 : 1; }",
        id="active-generic-parameter",
    ),
    pytest.param(
        "class Item {} int main() { for Item in range(1) {} return 0; }",
        id="loop-binding",
    ),
    pytest.param(
        'class Problem {} int main() { try { throw "x"; } catch (string Problem) { return 0; } }',
        id="catch-binding",
    ),
    pytest.param(
        "class Item {} int main() { var identity = (int Item) => Item; return identity(1) == 1 ? 0 : 1; }",
        id="lambda-parameter",
    ),
    pytest.param(
        "int main() { int size_t = 1; return size_t == 1 ? 0 : 1; }",
        id="hosted-typedef-local",
    ),
)


def test_lexical_callables_shadow_global_and_special_targets(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        CALLABLE_SHADOW_SOURCE,
        "lexical-callable-shadow",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


def test_hosted_stdlib_calls_do_not_borrow_source_shadow_abi_or_effects(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        HOSTED_SHADOW_SOURCE,
        "hosted-source-shadow",
        include_stdlib=True,
    )
    run_strict_pair(compiled, tmp_path)


@pytest.mark.parametrize(
    ("probe", "user_source"),
    [
        pytest.param(HOSTED_VALUE_PROBE, HOSTED_VALUE_USER, id="ordinary"),
        pytest.param(
            HOSTED_VALUE_GENERIC_PROBE,
            HOSTED_VALUE_GENERIC_USER,
            id="generic",
        ),
    ],
)
def test_hosted_stdlib_function_values_fail_closed_under_user_shadows(
    semantic_btrcc: Path,
    tmp_path: Path,
    probe: str,
    user_source: str,
) -> None:
    program = tmp_path / "hosted-value-shadow.btrc"
    data_root = _custom_stdlib_root(tmp_path, probe, program)
    source = f"import std.hosted_value_probe;\n{user_source}"
    program.write_text(source)

    selfhost = subprocess.run(
        [str(semantic_btrcc), str(program)],
        cwd=REPO,
        env={**os.environ, "BTRC_HOME": str(data_root)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert selfhost.returncode != 0
    diagnostic = "cannot be stored or forwarded as a value because bare __fn_ptr"
    assert diagnostic in selfhost.stderr

    stdlib = data_root / "stdlib"
    repository = StdlibRepository(directory=str(stdlib))
    pipeline = CompilationPipeline(frontend=FrontendStage(repository))
    options = CompilerOptions(
        include_stdlib=True,
        map_stdlib_positions=True,
        use_ast_cache=False,
    )
    resolved = pipeline.resolve(
        source,
        str(program),
        options,
    )
    parsed = pipeline.parse(resolved, program.name, options)
    analyzed = pipeline.analyze(parsed.program)
    assert any(diagnostic in error for error in analyzed.errors), analyzed.errors


def test_unshadowed_hosted_function_value_is_rejected_before_c_abi_mismatch(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    diagnostic = "cannot be stored or forwarded as a value because bare __fn_ptr"
    for result in compile_diagnostic_pair(
        semantic_btrcc,
        tmp_path,
        HOSTED_VALUE_NO_SHADOW,
    ):
        assert result.returncode != 0
        assert diagnostic in result.stderr


def test_exact_source_function_with_hosted_spelling_remains_a_valid_value(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        SOURCE_VALUE_HOSTED_SPELLING,
        "source-value-hosted-spelling",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


@pytest.mark.parametrize("source", NONCALLABLE_SHADOWS)
def test_noncallable_lexical_values_fail_before_special_resolution(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "not callable" in result.stderr


@pytest.mark.parametrize("source", TYPE_SHADOWS)
def test_lexical_values_shadow_types_without_colliding_in_generated_c(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "type-shadow",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


def test_source_gpu_id_cannot_be_reinterpreted_as_a_gpu_builtin(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int gpu_id() { return 0; }
        @gpu void update(int[] values) { values[0] = gpu_id(); }
        int main() { return 0; }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "resolves to a source symbol" in result.stderr


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
                int helper(int value) { return value; }
                @gpu void update(int[] values) {
                    values[0] = helper(values[0]);
                }
                int main() { return 0; }
            """,
            id="ordinary-helper",
        ),
        pytest.param(
            """
                float sqrt(float value) { return value; }
                @gpu void update(float[] values) {
                    values[0] = sqrt(values[0]);
                }
                int main() { return 0; }
            """,
            id="math-spelling",
        ),
    ],
)
def test_source_calls_are_rejected_in_dormant_gpu_bodies(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "resolves to a source symbol" in result.stderr


def test_source_calls_in_gpu_defaults_remain_host_evaluated(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int defaultScale() { return 2; }
        @gpu void update(int[] values, int scale = defaultScale()) {
            int index = gpu_id();
            values[index] *= scale;
        }
        int main() { return 0; }
    """
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "host-evaluated-gpu-default",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


@pytest.mark.parametrize(
    ("call", "diagnostic"),
    [
        pytest.param("gpu_id(1)", "gpu_id() takes no arguments", id="arity"),
        pytest.param(
            "gpu_id(value=1)",
            "WGSL built-ins do not accept named arguments",
            id="named-argument",
        ),
    ],
)
def test_gpu_id_call_shape_is_checked_in_dormant_gpu_bodies(
    semantic_btrcc: Path,
    tmp_path: Path,
    call: str,
    diagnostic: str,
) -> None:
    source = f"""
        @gpu void update(int[] values) {{ values[0] = {call}; }}
        int main() {{ return 0; }}
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert diagnostic in result.stderr


def test_gpu_id_without_gpu_context_is_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = "int main() { return gpu_id(); }"
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "gpu_id() can only be called inside @gpu functions" in result.stderr


def test_source_gpu_id_remains_an_ordinary_call_outside_gpu(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int gpu_id(int value) { return value + 1; }
        int main() { return gpu_id(41) == 42 ? 0 : 1; }
    """
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "ordinary-source-gpu-id",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)
