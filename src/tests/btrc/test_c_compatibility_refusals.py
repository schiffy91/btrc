"""C that btrc rejects on purpose (C rows 19-24) fails identically in both compilers.

docs/known-language-gaps.md ("C that btrc rejects on purpose") states each
policy. Every refusal here is pinned to one diagnostic -- message, line and
column -- that the reference compiler and btrcc must both report, so a
refusal cannot drift into a generic parse error in one of them. The accepted
neighbours of each refusal (``_Bool`` as a spelling of ``bool``, a void call
followed by a bare ``return``) run under strict C11 through both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair
from src.tests.btrc.test_mutex_value_contract import _compile_pair, _strict_matrix
from src.tests.btrc.test_realtime_primitives_parity import _diagnostic_identity

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

RESERVED = "'{}' is a reserved word and cannot be used as a name"
ATOMIC = "C11 '_Atomic' is not supported; use btrc's Atomic<T> for atomic storage"
COMPLEX = "C11 '_Complex' is not supported; btrc has no complex types"

REFUSALS = [
    # Row 19: a parenthesized comma list is a tuple literal, not the comma operator.
    pytest.param(
        "int main() { int value = (1, 2); return value; }",
        ("Cannot assign 'Tuple<int, int>' to variable 'value' of type 'int'", 1, 14),
        id="r19-comma-operator",
    ),
    # Row 20: grammar keywords never name a declaration.
    pytest.param(
        "int main() { int string = 0; return string; }",
        (RESERVED.format("string"), 1, 18),
        id="r20-local-string",
    ),
    pytest.param(
        "int main() { int in = 0; return 0; }",
        (RESERVED.format("in"), 1, 18),
        id="r20-local-in",
    ),
    pytest.param(
        "int main() { var keep = 1; return 0; }",
        (RESERVED.format("keep"), 1, 18),
        id="r20-var-keep",
    ),
    pytest.param(
        "int main() { int while = 0; return 0; }",
        (RESERVED.format("while"), 1, 18),
        id="r20-c-keyword",
    ),
    pytest.param(
        "int main() { for (int null = 0; ; ) { break; } return 0; }",
        (RESERVED.format("null"), 1, 23),
        id="r20-for-initializer",
    ),
    pytest.param(
        "int class = 0;\nint main() { return 0; }",
        (RESERVED.format("class"), 1, 5),
        id="r20-global",
    ),
    pytest.param(
        "int identity(int self) { return 0; }\nint main() { return 0; }",
        (RESERVED.format("self"), 1, 18),
        id="r20-parameter",
    ),
    pytest.param(
        "struct Record { int new; };\nint main() { return 0; }",
        (RESERVED.format("new"), 1, 21),
        id="r20-struct-field",
    ),
    pytest.param(
        "int spawn() { return 0; }\nint main() { return 0; }",
        (RESERVED.format("spawn"), 1, 5),
        id="r20-function-name",
    ),
    # Row 21: ABI-dependent integers never mix implicitly with built-in ones.
    pytest.param(
        '#include <string.h>\nint main() { char* text = "ab"; return strlen(text) == 2 ? 0 : 1; }',
        (
            "Operator '==' mixes ABI-dependent integer type 'size_t' with 'int'; "
            "cast explicitly to a fixed-width or built-in integer type",
            2,
            40,
        ),
        id="r21-size-t-int",
    ),
    # Row 22: _Bool is bool, and an integer never converts to it implicitly.
    pytest.param(
        "int main() { _Bool ready = 1; return 0; }",
        ("Cannot assign 'int' to variable 'ready' of type 'bool'", 1, 14),
        id="r22-c-bool-from-int",
    ),
    pytest.param(
        "int main() { bool ready = 1; return 0; }",
        ("Cannot assign 'int' to variable 'ready' of type 'bool'", 1, 14),
        id="r22-bool-from-int",
    ),
    # Row 22: returning a void expression violates C11 6.8.6.4.
    pytest.param(
        "void first() {}\nvoid second() { return first(); }\nint main() { second(); return 0; }",
        ("Void function or method cannot return a value", 2, 17),
        id="r22-return-void-call",
    ),
    pytest.param(
        "class Box { public void first() {} public void second() { return self.first(); } }\nint main() { return 0; }",
        ("Void function or method cannot return a value", 1, 59),
        id="r22-return-void-method-call",
    ),
    # Row 24: C11 _Atomic and _Complex are deferred; btrc's Atomic<T> is separate.
    pytest.param(
        "int main() { _Atomic int counter = 0; return 0; }",
        (ATOMIC, 1, 14),
        id="r24-atomic-qualifier",
    ),
    pytest.param(
        "int main() { _Atomic(int) counter = 0; return 0; }",
        (ATOMIC, 1, 14),
        id="r24-atomic-specifier",
    ),
    pytest.param(
        "struct Counter { _Atomic int value; };\nint main() { return 0; }",
        (ATOMIC, 1, 18),
        id="r24-atomic-field",
    ),
    pytest.param(
        "void bump(_Atomic int* value) {}\nint main() { return 0; }",
        (ATOMIC, 1, 11),
        id="r24-atomic-parameter",
    ),
    pytest.param(
        "int main() { double _Complex value; return 0; }",
        (COMPLEX, 1, 21),
        id="r24-complex-trailing",
    ),
    pytest.param(
        "int main() { _Complex double value; return 0; }",
        (COMPLEX, 1, 14),
        id="r24-complex-leading",
    ),
    pytest.param(
        "double _Complex root;\nint main() { return 0; }",
        (COMPLEX, 1, 8),
        id="r24-complex-global",
    ),
]


@pytest.mark.parametrize(("source", "expected"), REFUSALS)
def test_refusal_is_identical_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    expected: tuple[str, int, int],
) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)

    assert selfhost.returncode != 0 and reference.returncode != 0
    assert _diagnostic_identity(selfhost.stderr) == expected
    assert _diagnostic_identity(reference.stderr) == expected


ACCEPTED = [
    pytest.param(
        """
        #include <assert.h>
        _Bool flip(_Bool value) { return !value; }
        _Bool globalFlag = false;
        struct Holder { _Bool set; };
        class Switch { public _Bool on; public Switch(_Bool on) { self.on = on; } }
        int main() {
            _Bool ready = true;
            bool alias = ready;
            _Bool* pointer = &ready;
            _Bool cast = (_Bool)(alias && *pointer);
            _Bool compared = 3 > 2;
            struct Holder holder = {true};
            Switch light = new Switch(compared);
            assert(flip(globalFlag) && cast && holder.set && light.on);
            assert(sizeof(_Bool) == sizeof(bool));
            print(f"{ready} {alias}");
            return 0;
        }
        """,
        id="r22-c-bool-spelling",
    ),
    pytest.param(
        """
        #include <assert.h>
        int calls = 0;
        void first() { calls++; }
        void second() { first(); return; }
        int main() {
            second();
            assert(calls == 1);
            return 0;
        }
        """,
        id="r22-void-call-then-return",
    ),
    pytest.param(
        """
        int main() {
            Atomic<int> counter = Atomic(0);
            counter.store(2, MemoryOrder.RELEASE);
            return counter.load(MemoryOrder.ACQUIRE) == 2 ? 0 : 1;
        }
        """,
        id="r24-btrc-atomic-unaffected",
    ),
]


@pytest.mark.parametrize("source", ACCEPTED)
def test_accepted_neighbour_runs_strictly_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    source: str,
) -> None:
    name = request.node.callspec.id
    for artifact in _compile_pair(semantic_btrcc, tmp_path, source, name):
        _strict_matrix(artifact, tmp_path)
