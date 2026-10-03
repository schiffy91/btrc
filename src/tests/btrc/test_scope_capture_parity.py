"""Scope-aware captures, realtime types and static addresses in both compilers.

A name resolves through the scope chain: a lambda captures only what its body
reads from enclosing scopes, and a local that shadows a global is never a
static-storage address. Each case must fail with the same diagnostic through
btrcc and the reference compiler.
"""

from pathlib import Path

import pytest

from src.tests.btrc.dual_frontend_harness import compile_reference_snippet, compile_snippet_pair
from src.tests.btrc.selfhost_snippet_harness import compile_source, strict_build_and_run


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        pytest.param(
            "int count = 3; int main() { int count = 4; static int* p = &count; return *p - 4; }",
            "Variable 'p' requires a C constant/address initializer for static storage",
            id="static-address-of-shadowing-local",
        ),
        pytest.param(
            "int values[2] = {1, 2}; int main() { int values[2] = {3, 4}; static int* p = values; return *p - 3; }",
            "Variable 'p' requires a C constant/address initializer for static storage",
            id="static-array-decay-of-shadowing-local",
        ),
        pytest.param(
            "int helper() { return 1; } int main() { int helper = 2; static int* p = &helper; return *p - 2; }",
            "Variable 'p' requires a C constant/address initializer for static storage",
            id="static-address-of-local-shadowing-function",
        ),
        pytest.param(
            "int read(int count) { static int* p = &count; return *p; } int count = 1; int main() { return read(0); }",
            "Variable 'p' requires a C constant/address initializer for static storage",
            id="static-address-of-parameter",
        ),
        pytest.param(
            # The nested lambda reads the outer array, so the spawn captures it.
            "int main() { int values[2] = {1, 2}; Thread<int> worker = spawn(() => { var read = (int index) => values[index]; return read(0); }); return worker.join(); }",
            "spawn cannot capture array storage through 'values'",
            id="spawn-captures-through-nested-lambda",
        ),
        pytest.param(
            # A block local ends with its block; the later read is a capture.
            "int main() { int values[2] = {1, 2}; Thread<int> worker = spawn(() => { { int values = 3; } return values[0]; }); return worker.join(); }",
            "spawn cannot capture array storage through 'values'",
            id="spawn-captures-after-block-local-ends",
        ),
        pytest.param(
            "int main() { int values[2] = {1, 2}; Span<int> view = Span(values); var read = () => (int)view.length(); return read() - 2; }",
            "A lambda cannot capture nonescaping Span 'view'",
            id="lambda-captures-span",
        ),
        pytest.param(
            # A local of a non-realtime callable type shadows the global.
            "@realtime int increment(int value) { return value + 1; } RealtimeFunction<int, int> transform = increment; "
            "@realtime int apply(int value) { CFunction<int, int> transform = increment; return transform(value); } "
            "int main() { return apply(1) - 2; }",
            "reaches forbidden unknown operation 'indirect call through 'transform''",
            id="realtime-call-through-shadowing-local",
        ),
    ],
)
def test_scope_resolved_names_fail_identically(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = compile_reference_snippet(tmp_path, source, "scope-capture-diagnostic")
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert diagnostic in result.stderr


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            # The spawn body's own 'values' is a scalar, not the outer array.
            "int main() { int values[2] = {1, 2}; Thread<int> worker = spawn(() => { int values = 21; return values * 2; }); return worker.join() + values[1] == 44 ? 0 : 1; }",
            id="spawn-local-redeclares-outer-array",
        ),
        pytest.param(
            "int main() { int values[2] = {1, 2}; Thread<int> worker = spawn(() => { var twice = (int values) => values * 2; return twice(4); }); return worker.join() == 8 && values[0] == 1 ? 0 : 1; }",
            id="nested-lambda-parameter-shadows-outer-array",
        ),
        pytest.param(
            # A later block's local does not retype the global for the body.
            "@realtime int increment(int value) { return value + 1; } RealtimeFunction<int, int> transform = increment; "
            "@realtime int apply(int value) { int result = transform(value); "
            "if (value > 100) { float transform = 2.0f; result = result + (int)transform; } return transform(result); } "
            "int main() { return apply(2) == 4 ? 0 : 1; }",
            id="realtime-call-through-global-beside-block-local",
        ),
        pytest.param(
            "int count = 3; int main() { static int* p = &count; int count = 4; return *p == 3 && count == 4 ? 0 : 1; }",
            id="static-address-of-global-before-local",
        ),
        pytest.param(
            "int count = 3; class Box { public int copy = count; public Box(int count) { self.copy = self.copy * 10 + count; } } "
            "int main() { Box box = new Box(9); int copy = box.copy; delete box; return copy == 39 ? 0 : 1; }",
            id="field-initializer-reads-global-not-parameter",
        ),
        pytest.param(
            "int limit = 3; int run(int result = spawn(() => limit * 2).join(), int limit = 50) { return result + limit; } "
            "int main() { return run() == 56 ? 0 : 1; }",
            id="spawn-default-reads-global-not-later-parameter",
        ),
    ],
)
def test_scope_resolved_names_run_identically(semantic_btrcc: Path, tmp_path: Path, source: str) -> None:
    for frontend, generated in compile_snippet_pair(semantic_btrcc, tmp_path, source, "scope-capture-program"):
        strict_build_and_run(generated, tmp_path / f"{frontend}.bin")
