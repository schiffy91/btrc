"""Function-pointer conversions and nullable calls, held equal in both compilers (parity wave 3).

Each program goes through the reference compiler's CLI and ``btrcc``
(``parity_wave_harness``). An accepted program must be accepted by both, its
C must build under strict C11 and print what it should; a refused one must be
refused by both with the same rendered diagnostic.

- Function and object pointers. C11 converts a function pointer to no object
  pointer and back (6.3.2.3), and strict C11 has no cast for it either. Both
  compilers took ``void* p = callback`` (and the nullable spelling, a named
  function, a lambda, an argument, a return, a field store, a ternary arm,
  ``void**`` and ``RealtimeFunction``) and emitted C that gcc and clang refuse
  under ``-pedantic-errors``. Both now refuse each with the ordinary mismatch
  and a reason. A pointer to a function pointer, or an array of them, is an
  object pointer and still converts.
- Casts. Both refused ``(void*)callback``, with different words; the
  nullable ``CFunction<...>?`` escaped the rule in both and emitted C gcc
  refuses. Both now name the direction and cover the nullable word.
- Calling ``CFunction<...>?``. Both refused every call, even after a null
  check, and rendered the type as ``CFunction<int, int>*`` (a pointer to a
  function pointer). Now a call the nullable flow proves non-null is
  accepted, and one it does not is refused with how to call it; the type
  renders as ``CFunction<int, int>?``.
- Array decay. ``CFunction<int, int>* p = ops`` is C's decay of an array of
  function pointers, which btrcc took and the reference compiler refused; both
  take it. Both took ``string? s = names`` and btrcc ``CFunction<...>? f =
  ops``, each storing a pointer to the elements in an element slot; both
  refuse those.
- Native bindings. A function a native binding imports from a C header takes
  ``null`` for a function-pointer parameter, as a hosted C function does
  (wave 2); both refused it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.tests.btrc.parity_wave_harness import ParityHarness, message

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the programs include POSIX headers")

FUNCTION_OBJECT = "; C11 has no conversion between a function pointer and an object pointer"


@pytest.fixture
def harness(immutable_btrcc: Path, tmp_path: Path) -> ParityHarness:
    return ParityHarness(immutable_btrcc, tmp_path)


def _program(body: str, prelude: str = "") -> str:
    return (
        prelude + "int twice(int value) { return value * 2; }\n\n"
        "struct Slot {\n\tvoid* context;\n};\n\nint main(int argc, char** argv) {\n" + body + "}\n"
    )


def _named(cases: list[tuple[str, ...]]) -> list[object]:
    """Parametrize cases, each identified by its first element: the program's name."""
    return [pytest.param(*case, id=case[0]) for case in cases]


# Function and object pointers: every conversion that emitted C strict C11
# refuses, with the place it happened.
@pytest.mark.parametrize(
    ("name", "prelude", "body", "diagnostic"),
    _named(
        [
            (
                "VoidFromCFunction",
                "",
                "\tCFunction<int, int> callback = twice;\n\tvoid* p = callback;\n\treturn p == null ? 1 : 0;\n",
                "error: Cannot assign 'CFunction<int, int>' to variable 'p' of type 'void*'" + FUNCTION_OBJECT,
            ),
            (
                "VoidFromFunction",
                "",
                "\tvoid* p = twice;\n\treturn p == null ? 1 : 0;\n",
                "error: Cannot assign 'CFunction<int, int>' to variable 'p' of type 'void*'" + FUNCTION_OBJECT,
            ),
            (
                "VoidFromLambda",
                "",
                "\tvoid* p = (int value) => value * 2;\n\treturn p == null ? 1 : 0;\n",
                "error: Cannot assign 'CFunction<int, int>' to variable 'p' of type 'void*'" + FUNCTION_OBJECT,
            ),
            (
                "VoidFromOptional",
                "",
                "\tCFunction<int, int>? callback = twice;\n\tvoid* p = callback;\n\treturn p == null ? 1 : 0;\n",
                "error: Cannot assign 'CFunction<int, int>?' to variable 'p' of type 'void*'" + FUNCTION_OBJECT,
            ),
            (
                "OptionalFromVoid",
                "",
                "\tvoid* opaque = null;\n\tCFunction<int, int>? callback = opaque;\n\treturn callback == null ? 0 : 1;\n",
                "error: Cannot assign 'void*' to variable 'callback' of type 'CFunction<int, int>?'" + FUNCTION_OBJECT,
            ),
            (
                "OptionalFromVoidPointerPointer",
                "",
                "\tvoid** opaque = null;\n\tCFunction<int, int>? callback = opaque;\n"
                "\treturn callback == null ? 0 : 1;\n",
                "error: Cannot assign 'void**' to variable 'callback' of type 'CFunction<int, int>?'" + FUNCTION_OBJECT,
            ),
            (
                "VoidFromRealtimeFunction",
                "@realtime int next(int value) { return value + 1; }\n\n",
                "\tRealtimeFunction<int, int> callback = next;\n\tvoid* p = callback;\n\treturn p == null ? 1 : 0;\n",
                "error: Cannot assign 'RealtimeFunction<int, int>' to variable 'p' of type 'void*'" + FUNCTION_OBJECT,
            ),
            (
                "Argument",
                "int take(void* context) { return context == null ? 1 : 0; }\n\n",
                "\tCFunction<int, int> callback = twice;\n\treturn take(callback);\n",
                "error: Argument 'context' to 'take()' expects 'void*' but got 'CFunction<int, int>'" + FUNCTION_OBJECT,
            ),
            (
                "HostedArgument",
                "#include <string.h>\n\n",
                "\tCFunction<int, int> callback = twice;\n\tchar buffer[8];\n\tmemcpy(buffer, callback, 4);\n"
                "\treturn 0;\n",
                "error: Argument 2 to hosted function 'memcpy()' expects 'const void*' but got 'CFunction<int, int>'"
                + FUNCTION_OBJECT,
            ),
            (
                "Return",
                "void* expose(CFunction<int, int> callback) { return callback; }\n\n",
                "\treturn expose(twice) == null ? 1 : 0;\n",
                "error: Return type mismatch: expected 'void*' but got 'CFunction<int, int>'" + FUNCTION_OBJECT,
            ),
            (
                "FieldStore",
                "",
                "\tstruct Slot slot;\n\tslot.context = null;\n\tslot.context = twice;\n"
                "\treturn slot.context == null ? 1 : 0;\n",
                "error: Cannot assign 'CFunction<int, int>' to 'void*'" + FUNCTION_OBJECT,
            ),
            (
                "TernaryArm",
                "",
                "\tCFunction<int, int> callback = twice;\n\tvoid* opaque = null;\n"
                "\tvoid* chosen = argc > 5 ? opaque : callback;\n\treturn chosen == null ? 0 : 1;\n",
                "error: Ternary branches have incompatible types 'void*' and 'CFunction<int, int>'",
            ),
            (
                "CastToObject",
                "",
                "\tCFunction<int, int> callback = twice;\n\tvoid* p = (void*)callback;\n\treturn p == null ? 1 : 0;\n",
                "error: Function pointers cannot be cast to object pointers or integer values in strict C11",
            ),
            (
                "CastFromObject",
                "",
                "\tvoid* opaque = null;\n\tCFunction<int, int> callback = (CFunction<int, int>)opaque;\n"
                "\treturn callback == null ? 1 : 0;\n",
                "error: Function pointers cannot be cast from object pointers or integer values in strict C11",
            ),
            (
                "CastOptionalToObject",
                "",
                "\tCFunction<int, int>? callback = twice;\n\tvoid* p = (void*)callback;\n\treturn p == null ? 1 : 0;\n",
                "error: Function pointers cannot be cast to object pointers or integer values in strict C11",
            ),
            (
                "CastObjectToOptional",
                "",
                "\tvoid* opaque = null;\n\tCFunction<int, int>? callback = (CFunction<int, int>?)opaque;\n"
                "\treturn callback == null ? 0 : 1;\n",
                "error: Function pointers cannot be cast from object pointers or integer values in strict C11",
            ),
        ]
    ),
)
def test_a_function_pointer_never_converts_to_or_from_an_object_pointer(
    harness: ParityHarness, name: str, prelude: str, body: str, diagnostic: str
) -> None:
    assert message(harness.refused(name, _program(body, prelude))) == diagnostic


# What still converts: a pointer to a function pointer and an array of them are
# object pointers, null is every pointer's, and an array decays.
OBJECT_POINTERS = """#include <stdio.h>

int twice(int value) { return value * 2; }
int thrice(int value) { return value * 3; }

int sum(CFunction<int, int>* table, int count, int value) {
\tint total = 0;
\tfor (int index = 0; index < count; index++) {
\t\tCFunction<int, int> op = table[index];
\t\ttotal = total + op(value);
\t}
\treturn total;
}

int main() {
\tCFunction<int, int> callback = twice;
\tvoid* slot = &callback;
\tCFunction<int, int>* back = slot;
\tCFunction<int, int> ops[2] = {twice, thrice};
\tvoid* table = ops;
\tCFunction<int, int>* first = ops;
\tCFunction<int, int>*? view = ops;
\tCFunction<int, int> empty = (CFunction<int, int>)null;
\tCFunction<int, int> second = view[1];
\tprintf("%d %d %d %d %d\\n", (*back)(1), first[0](2), second(3), sum(ops, 2, 2), table != null && empty == null ? 1 : 0);
\treturn 0;
}
"""


def test_pointers_to_function_pointers_are_object_pointers(harness: ParityHarness) -> None:
    reference, selfhost = harness.accepted("ObjectPointers", OBJECT_POINTERS)
    assert reference == selfhost == "2 4 9 10 1\n"


# An array decays to a pointer to its first element, never to an element: a
# nullable intrinsic reference (`string?`, `CFunction<...>?`) is one element's
# slot. Diagnostics still print `string?` as `string*`, in both compilers.
@pytest.mark.parametrize(
    ("name", "body", "diagnostic"),
    _named(
        [
            (
                "DecayToOptionalFunction",
                "\tCFunction<int, int> ops[2] = {twice, twice};\n\tCFunction<int, int>? first = ops;\n"
                "\treturn first == null ? 1 : 0;\n",
                "error: Cannot assign 'CFunction<int, int>[]' to variable 'first' of type 'CFunction<int, int>?'",
            ),
            (
                "DecayToOptionalString",
                '\tstring names[2] = {"a", "b"};\n\tstring? first = names;\n\treturn first == null ? 1 : 0;\n',
                "error: Cannot assign 'string[]' to variable 'first' of type 'string*'",
            ),
        ]
    ),
)
def test_an_array_never_decays_into_its_elements_nullable_slot(
    harness: ParityHarness, name: str, body: str, diagnostic: str
) -> None:
    assert message(harness.refused(name, _program(body))) == diagnostic


# Calling CFunction<...>?: every path the nullable flow proves.
NULLABLE_CALLS = """#include <stdio.h>

int twice(int value) { return value * 2; }

struct Slot {
\tCFunction<int, int>? callback;
};

class Holder {
\tpublic CFunction<int, int>? callback = null;
\tpublic Holder() {}
\tpublic int run(int value) {
\t\tif (self.callback != null) { return self.callback(value); }
\t\treturn value;
\t}
}

int guarded(CFunction<int, int>? callback, int value) {
\tif (callback == null) { return value; }
\treturn callback(value);
}

int conditional(CFunction<int, int>? callback, int value) {
\tint both = callback != null && callback(value) > 0 ? 1 : 0;
\tint either = callback == null || callback(value) > 0 ? 1 : 0;
\treturn callback == null ? both + either : callback(value) + both + either;
}

int main() {
\tCFunction<int, int>? local = twice;
\tint direct = 0;
\tif (local != null) { direct = local(1); }
\tstruct Slot slot;
\tslot.callback = twice;
\tint field = slot.callback != null ? slot.callback(2) : 0;
\tHolder holder = Holder();
\tint none = holder.run(3);
\tholder.callback = twice;
\tprintf("%d %d %d %d %d %d %d\\n", direct, field, none, holder.run(3), guarded(twice, 4), guarded(null, 4), conditional(twice, 5));
\treturn 0;
}
"""


def test_a_nullable_function_pointer_the_flow_proves_is_callable(harness: ParityHarness) -> None:
    reference, selfhost = harness.accepted("NullableCalls", NULLABLE_CALLS)
    assert reference == selfhost == "2 4 3 6 8 4 12\n"


# A global, a loop body the guard dominates, and a lambda's own parameter.
NULLABLE_FLOW = """#include <stdio.h>

int twice(int value) { return value * 2; }

CFunction<int, int>? hook = null;

int fire(int value) {
\tif (hook != null) { return hook(value); }
\treturn value;
}

int total(CFunction<int, int>? callback) {
\tif (callback == null) { return 0; }
\tint sum = 0;
\tfor (int index = 0; index < 3; index++) { sum = sum + callback(index); }
\treturn sum;
}

int main() {
\tint before = fire(2);
\thook = twice;
\tCFunction<int, CFunction<int, int>?> apply = (CFunction<int, int>? inner) => inner == null ? 0 : inner(3);
\tprintf("%d %d %d %d %d\\n", before, fire(2), total(twice), total(null), apply(twice));
\treturn 0;
}
"""


def test_the_nullable_flow_proves_globals_loops_and_lambdas(harness: ParityHarness) -> None:
    reference, selfhost = harness.accepted("NullableFlow", NULLABLE_FLOW)
    assert reference == selfhost == "2 4 6 0 6\n"


NULLABLE_CALL = (
    "error: Nullable function pointer of type 'CFunction<int, int>?' may be null; "
    "compare it with null before calling it"
)


@pytest.mark.parametrize(
    ("name", "source"),
    _named(
        [
            (
                "UncheckedParameter",
                "int apply(CFunction<int, int>? callback, int value) {\n\treturn callback(value);\n}\n\n"
                "int main() { return apply(null, 1); }\n",
            ),
            (
                "ClearedAfterCheck",
                "int twice(int value) { return value * 2; }\n\n"
                "int main() {\n\tCFunction<int, int>? callback = twice;\n"
                "\tif (callback != null) {\n\t\tcallback = null;\n\t\treturn callback(1);\n\t}\n\treturn 0;\n}\n",
            ),
            (
                "UncheckedField",
                "class Holder {\n\tpublic CFunction<int, int>? callback = null;\n\tpublic Holder() {}\n"
                "\tpublic int run(int value) { return self.callback(value); }\n}\n\n"
                "int main() { Holder holder = Holder(); return holder.run(1); }\n",
            ),
            (
                "WrongArm",
                "int apply(CFunction<int, int>? callback, int value) {\n"
                "\treturn callback == null ? callback(value) : value;\n}\n\n"
                "int main() { return apply(null, 1); }\n",
            ),
            (
                "UncheckedGlobal",
                "CFunction<int, int>? hook = null;\n\n"
                "int fire(int value) { return hook(value); }\n\nint main() { return fire(1); }\n",
            ),
            # An element is no access path the flow can prove; bind it first.
            (
                "Element",
                "int twice(int value) { return value * 2; }\n\n"
                "int main() {\n\tCFunction<int, int>? table[2] = {twice, null};\n\treturn table[0](1);\n}\n",
            ),
        ]
    ),
)
def test_a_nullable_function_pointer_call_needs_a_null_check(harness: ParityHarness, name: str, source: str) -> None:
    assert message(harness.refused(name, source)) == NULLABLE_CALL


# Native bindings: a header's function-pointer parameter takes null, as a
# hosted C function's does.
NATIVE_HEADER = """#include <stddef.h>

static inline int visit(int (*callback)(int), int value) { return callback == NULL ? -value : callback(value); }
"""

NATIVE_MANIFEST = """manifest-version = 1

[package]
name = "nativeCallbacks"

[[native.bindings]]
module = "Api"
header = "Native.h"
language = "c"
standard = "c11"
symbols = ["visit"]
"""

NATIVE_PROGRAM = """import ./Api.btrc;
#include <stdio.h>

int twice(int value) { return value * 2; }

int main() {
\tCFunction<int, int>? none = null;
\tprintf("%d %d %d\\n", visit(null, 3), visit(twice, 3), visit(none, 1));
\treturn 0;
}
"""


@pytest.mark.skipif(
    not os.environ.get("BTRC_NATIVE_HEADER_READER"), reason="requires the native header reader the dev shell builds"
)
def test_a_native_function_pointer_parameter_takes_null(harness: ParityHarness, tmp_path: Path) -> None:
    root = tmp_path / "package"
    (root / "src").mkdir(parents=True)
    (root / "btrc.toml").write_text(NATIVE_MANIFEST, encoding="utf-8")
    (root / "Native.h").write_text(NATIVE_HEADER, encoding="utf-8")
    (root / "src/Api.btrc").write_text("// The native binding's module.\n", encoding="utf-8")
    program = root / "src/Main.btrc"
    program.write_text(NATIVE_PROGRAM, encoding="utf-8")
    reference, selfhost = harness.accepted_outcomes(*harness.compile_path(program))
    assert reference == selfhost == "-3 6 -1\n"
