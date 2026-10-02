"""C that btrc rejects on purpose (C rows 1 and 19-24) fails identically in both compilers.

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

VOID_LIST = "A 'void' parameter must be the only one, unnamed and unqualified: write '(void)'"
UNNAMED = "Parameter name required: only a function prototype without a body may omit it"

REFUSALS = [
    # Row 1: `(void)` is the only void parameter list, and only a prototype
    # without a body may leave a parameter unnamed (C11 6.9.1p5).
    pytest.param(
        "int f(void x) { return 0; }\nint main() { return 0; }",
        (VOID_LIST, 1, 7),
        id="r01-named-void",
    ),
    pytest.param(
        "int f(void, int y) { return y; }\nint main() { return 0; }",
        (VOID_LIST, 1, 7),
        id="r01-void-first-of-two",
    ),
    pytest.param(
        "int f(int, void);\nint main() { return 0; }",
        (VOID_LIST, 1, 12),
        id="r01-void-second-of-two",
    ),
    pytest.param(
        "int f(const void);\nint main() { return 0; }",
        (VOID_LIST, 1, 7),
        id="r01-qualified-void",
    ),
    pytest.param(
        "int f(void[]);\nint main() { return 0; }",
        (VOID_LIST, 1, 7),
        id="r01-void-array",
    ),
    pytest.param(
        "int f(int)\nint main() { return 0; }",
        ("Expected LBRACE, got INT 'int'", 2, 1),
        id="r01-prototype-missing-semicolon",
    ),
    pytest.param(
        "int f(int, int y) { return y; }\nint main() { return 0; }",
        (UNNAMED, 1, 7),
        id="r01-unnamed-definition",
    ),
    pytest.param(
        "void f(keep int);\nint main() { return 0; }",
        ("A 'keep' parameter requires a name", 1, 8),
        id="r01-unnamed-keep",
    ),
    pytest.param(
        "int f(int = 3);\nint main() { return 0; }",
        ("An unnamed parameter cannot have a default value", 1, 11),
        id="r01-unnamed-default",
    ),
    pytest.param(
        "int f(int);\nint f(int a, int b) { return a + b; }\nint main() { return 0; }",
        ("Conflicting declarations for function 'f'", 2, 1),
        id="r01-prototype-arity",
    ),
    pytest.param(
        "int f(int, double);\nint f(int a, int b) { return a + b; }\nint main() { return 0; }",
        ("Conflicting declarations for function 'f'", 2, 1),
        id="r01-prototype-type",
    ),
    pytest.param(
        "int f(int);\nint f(int a);\nint f(int b) { return b; }\nint main() { return 0; }",
        ("Conflicting declarations for function 'f'", 3, 1),
        id="r01-named-prototype-after-unnamed",
    ),
    pytest.param(
        "class Box { public int get(int) { return 0; } }\nint main() { return 0; }",
        (UNNAMED, 1, 28),
        id="r01-unnamed-method",
    ),
    pytest.param(
        "interface Shape { int area(int); }\nint main() { return 0; }",
        (UNNAMED, 1, 28),
        id="r01-unnamed-interface",
    ),
    pytest.param(
        "int main() { var g = (int) => 1; return 0; }",
        (UNNAMED, 1, 23),
        id="r01-unnamed-lambda",
    ),
    pytest.param(
        "enum class Signal { Level(int) }\nint main() { return 0; }",
        (UNNAMED, 1, 27),
        id="r01-unnamed-variant",
    ),
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


DECLARATION_BODY = "A declaration cannot be the body of a control statement; enclose it in braces"

# C itself rejects these (C11 6.8, 6.9): a declaration is not a statement, so
# it cannot be an unbraced body (row 2), and a file-scope ';' is no external
# declaration (row 6). The constructs that stay braced in btrc keep refusing
# an unbraced body.
C_REFUSALS = [
    pytest.param(
        "int main() { int flag = 1; if (flag) int hidden = 2; return 0; }",
        (DECLARATION_BODY, 1, 38),
        id="r02-declaration-if-body",
    ),
    pytest.param(
        "int main() { int flag = 1; if (flag) {} else var hidden = 2; return 0; }",
        (DECLARATION_BODY, 1, 46),
        id="r02-declaration-else-body",
    ),
    pytest.param(
        "int main() { int flag = 0; while (flag) string text; return 0; }",
        (DECLARATION_BODY, 1, 41),
        id="r02-declaration-while-body",
    ),
    pytest.param(
        "int main() { for (int i = 0; i < 2; i++) int doubled = i * 2; return 0; }",
        (DECLARATION_BODY, 1, 42),
        id="r02-declaration-for-body",
    ),
    pytest.param(
        "int main() { do int once = 1; while (false); return 0; }",
        (DECLARATION_BODY, 1, 17),
        id="r02-declaration-do-body",
    ),
    pytest.param(
        "int main() { int total = 0; for value in [1, 2] total += value; return total; }",
        ("Expected LBRACE, got IDENT 'total'", 1, 49),
        id="r02-for-in-stays-braced",
    ),
    pytest.param(
        "int main() { int total = 0; try total = 1; catch (e) {} return total; }",
        ("Expected LBRACE, got IDENT 'total'", 1, 33),
        id="r02-try-stays-braced",
    ),
    pytest.param(
        "int main() { int total = 0; switch (total) total = 1; return total; }",
        ("Expected LBRACE, got IDENT 'total'", 1, 44),
        id="r02-switch-stays-braced",
    ),
    pytest.param(
        "int main() { return 0; }\n;",
        ("Unexpected token ';' at top level", 2, 1),
        id="r06-file-scope-semicolon",
    ),
    pytest.param(
        "int helper() { return 1; };\nint main() { return helper() - 1; }",
        ("Unexpected token ';' at top level", 1, 27),
        id="r06-semicolon-after-function",
    ),
]

# Row 5: adjacent string literals concatenate (src/tests/c_compat/AdjacentStringLiterals.btrc);
# a piece that is no string literal is refused at the first piece (D20).
ADJACENT_FSTRING = "An f-string cannot be concatenated with an adjacent string literal"
ADJACENT_PIECE = (
    "Cannot concatenate '{}' with an adjacent string literal: it is not a source macro that expands to a string literal"
)
ADJACENT_STRING_REFUSALS = [
    pytest.param(
        'int main() { int n = 1; string text = f"{n}" " tail"; return 0; }',
        (ADJACENT_FSTRING, 1, 39),
        id="r05-fstring-then-literal",
    ),
    pytest.param(
        'int main() { int n = 1; string text = "head " f"{n}"; return 0; }',
        (ADJACENT_FSTRING, 1, 39),
        id="r05-literal-then-fstring",
    ),
    pytest.param(
        'int main() { int n = 1; string text = "a" "b" f"{n}"; return 0; }',
        (ADJACENT_FSTRING, 1, 39),
        id="r05-fstring-after-two-pieces",
    ),
    pytest.param(
        'int main() { char* tail = "b"; char* text = "a" tail; return 0; }',
        (ADJACENT_PIECE.format("tail"), 1, 45),
        id="r05-variable-piece",
    ),
    pytest.param(
        'int main() { char* text = "a" missing "c"; return 0; }',
        (ADJACENT_PIECE.format("missing"), 1, 27),
        id="r05-undeclared-piece",
    ),
    pytest.param(
        '#define COUNT 3\nint main() { char* text = COUNT "a"; return 0; }',
        (ADJACENT_PIECE.format("COUNT"), 2, 27),
        id="r05-integer-macro-piece",
    ),
    pytest.param(
        '#define QUOTE(x) "x"\nint main() { char* text = "a" QUOTE; return 0; }',
        (ADJACENT_PIECE.format("QUOTE"), 2, 27),
        id="r05-function-like-macro-piece",
    ),
    pytest.param(
        '#define LOOP "a" LOOP\nint main() { char* text = "b" LOOP; return 0; }',
        (ADJACENT_PIECE.format("LOOP"), 2, 27),
        id="r05-self-referential-macro-piece",
    ),
    pytest.param(
        '#include <inttypes.h>\nint main() { char* text = "%" PRId64; return 0; }',
        (ADJACENT_PIECE.format("PRId64"), 2, 27),
        id="r05-native-macro-piece",
    ),
    # A constant context that never analyzes its operand still refuses a piece.
    pytest.param(
        'int values[(int)sizeof("a" missing)];\nint main() { return 0; }',
        (ADJACENT_PIECE.format("missing"), 1, 24),
        id="r05-global-array-bound-piece",
    ),
    pytest.param(
        'int main() { char text[sizeof("a" missing)]; return 0; }',
        (ADJACENT_PIECE.format("missing"), 1, 31),
        id="r05-local-array-bound-piece",
    ),
    pytest.param(
        'struct Holder { char text[sizeof("a" missing)]; };\nint main() { return 0; }',
        (ADJACENT_PIECE.format("missing"), 1, 34),
        id="r05-struct-field-bound-piece",
    ),
    pytest.param(
        'enum Size { SMALL = (int)sizeof("a" missing), LARGE };\nint main() { return 0; }',
        (ADJACENT_PIECE.format("missing"), 1, 33),
        id="r05-enum-value-piece",
    ),
    # Each piece decodes on its own, so the folded extent is the decoded total.
    pytest.param(
        'int main() { int extent[(int)sizeof("\\x4" "1") - 3]; return 0; }',
        ("Array bound for Variable 'extent' must be positive", 1, 25),
        id="r05-sizeof-folds-decoded-pieces",
    ),
    pytest.param(
        '#define WORD "hello"\nint main() { int extent[(int)sizeof("a" WORD) - 7]; return 0; }',
        ("Array bound for Variable 'extent' must be positive", 2, 25),
        id="r05-sizeof-folds-macro-pieces",
    ),
]


# Row 4: a narrow string literal initializes a char array
# (src/tests/c_compat/CharArrayStringInit.btrc). The exact fit drops the
# terminator and is refused (D20), as is overflow; extents count UTF-8 bytes.
# Only a literal initializes one, and wide literals wait for row 16.
EXACT_FIT = (
    "String literal fills all {0} elements of the char array and leaves no room for its terminator; "
    "declare {1} elements or leave the bound empty"
)
OVERFLOW = "String literal needs {0} elements with its terminator but the char array has {1}"
NOT_A_LITERAL = "A char array can only be initialized from a string literal or a brace list, not a string value"

CHAR_ARRAY_REFUSALS = [
    pytest.param(
        'int main() { char text[3] = "abc"; return 0; }',
        (EXACT_FIT.format(3, 4), 1, 29),
        id="r04-exact-fit",
    ),
    pytest.param(
        'int main() { char text[2] = "abc"; return 0; }',
        (OVERFLOW.format(4, 2), 1, 29),
        id="r04-overflow",
    ),
    pytest.param(
        'int main() { char text[4] = "caf\\u00e9"; return 0; }',
        (OVERFLOW.format(6, 4), 1, 29),
        id="r04-universal-character-counts-bytes",
    ),
    pytest.param(
        'char text[5] = "hello";\nint main() { return 0; }',
        (EXACT_FIT.format(5, 6), 1, 16),
        id="r04-global-exact-fit",
    ),
    pytest.param(
        'int main() { static unsigned char text[2] = "ab"; return 0; }',
        (EXACT_FIT.format(2, 3), 1, 45),
        id="r04-static-exact-fit",
    ),
    pytest.param(
        'enum Size { THREE = 3 };\nint main() { char text[THREE] = "abc"; return 0; }',
        (EXACT_FIT.format(3, 4), 2, 33),
        id="r04-constant-bound-exact-fit",
    ),
    pytest.param(
        'struct Label { int id; char tag[3]; };\nint main() { struct Label label = {1, "abc"}; return label.id; }',
        (EXACT_FIT.format(3, 4), 2, 39),
        id="r04-field-exact-fit",
    ),
    pytest.param(
        'int main() { int n = 1; char text[8] = f"n{n}"; return 0; }',
        ("A char array cannot be initialized from an f-string; only a string literal initializes one", 1, 40),
        id="r04-f-string",
    ),
    pytest.param(
        'int main() { string name = "ab"; char text[8] = name; return 0; }',
        (NOT_A_LITERAL, 1, 49),
        id="r04-string-value",
    ),
    pytest.param(
        "struct Label { int id; char tag[4]; };\n"
        'int main() { string name = "ab"; struct Label label = {1, name}; return label.id; }',
        (NOT_A_LITERAL, 2, 59),
        id="r04-field-string-value",
    ),
    pytest.param(
        "struct Label { int id; char tag[4]; };\n"
        'int main() { struct Label label = {1, "a"}; label = {2, "abcd"}; return label.id; }',
        (EXACT_FIT.format(4, 5), 2, 57),
        id="r04-assignment-field-exact-fit",
    ),
    pytest.param(
        "struct Label { int id; char tag[4]; };\n"
        "int take(struct Label label) { return label.id; }\n"
        'int main() { return take({2, "abcd"}); }',
        (EXACT_FIT.format(4, 5), 3, 30),
        id="r04-argument-field-exact-fit",
    ),
    pytest.param(
        "struct Label { int id; char tag[4]; };\n"
        'struct Label make() { return {1, "abcd"}; }\n'
        "int main() { return make().id; }",
        (EXACT_FIT.format(4, 5), 2, 34),
        id="r04-return-field-exact-fit",
    ),
    pytest.param(
        "struct Inner { char tag[2]; };\nstruct Outer { struct Inner inner; int n; };\n"
        'int main() { struct Outer outer = {{"ab"}, 1}; return outer.n; }',
        (EXACT_FIT.format(2, 3), 3, 37),
        id="r04-nested-field-exact-fit",
    ),
    pytest.param(
        'class Box { public char name[8] = "box"; }\nint main() { return 0; }',
        (
            "A class field char array cannot take a string literal default; copy the text into it in the constructor",
            1,
            35,
        ),
        id="r04-class-field-default",
    ),
    pytest.param(
        'int main() { int count = 4; char text[count] = "abc"; return 0; }',
        ("Variable 'text' is a variable-length array and cannot have an initializer", 1, 29),
        id="r04-variable-length-array",
    ),
    pytest.param(
        'int main() { char text[0] = ""; return 0; }',
        ("Array bound for Variable 'text' must be positive", 1, 24),
        id="r04-zero-bound",
    ),
    pytest.param(
        'string source = "a";\nchar text[4] = source;\nint main() { return 0; }',
        ("Global 'text' requires a C constant/address initializer for static storage", 2, 1),
        id="r04-global-string-value",
    ),
    pytest.param(
        'int count = 1;\nchar text[4] = f"{count}";\nint main() { return 0; }',
        ("Global 'text' requires a C constant/address initializer for static storage", 2, 1),
        id="r04-global-f-string",
    ),
    pytest.param(
        'int main() { char text[] = L"abc"; return 0; }',
        ("Expected SEMICOLON, got STRING_LIT '\"abc\"'", 1, 29),
        id="r04-wide-literal",
    ),
]

# Row 23: block-scope VLAs are supported (src/tests/c_compat/VariableLengthArrays.btrc);
# every context that would need a constant extent or an initializer refuses one.
VLA_REFUSALS = [
    pytest.param(
        "int count = 3;\nint values[count];\nint main() { return 0; }",
        ("Array bound for Global 'values' must be a constant expression", 2, 12),
        id="r23-global",
    ),
    pytest.param(
        "int main() { int count = 2; static int values[count]; return 0; }",
        ("Array bound for Variable 'values' must be a constant expression", 1, 47),
        id="r23-static-local",
    ),
    pytest.param(
        "int count = 2;\nstruct Holder { int values[count]; };\nint main() { return 0; }",
        ("Array bound for struct field 'Holder.values' must be a constant expression", 2, 28),
        id="r23-struct-field",
    ),
    pytest.param(
        "int count = 2;\nclass Holder { public int values[count]; }\nint main() { return 0; }",
        ("Array bound for Field 'Holder.values' must be a constant expression", 2, 34),
        id="r23-class-field",
    ),
    pytest.param(
        "int main() { int count = 2; int values[count] = {1, 2}; return 0; }",
        ("Variable 'values' is a variable-length array and cannot have an initializer", 1, 29),
        id="r23-initializer",
    ),
]

# Row 23 refusals where the compilers agree on the refusal but not on its
# diagnostic. Each is pre-existing and shared with fixed-size arrays; the pair
# is pinned so a change to either side is deliberate.
VLA_DIVERGENT_REFUSALS = [
    pytest.param(
        "int main() { int count = 2; int values[count]; int copy[count] = values; return 0; }",
        ("Initializer for 'copy' requires an array initializer", 1, 48),
        ("Variable 'copy' is a variable-length array and cannot have an initializer", 1, 48),
        id="r23-copy-initializer",
    ),
    pytest.param(
        "int main() { int count = 2; int values[count]; values[0] = 1; "
        "var worker = spawn(() => values[0]); return worker.join() - 1; }",
        (
            "spawn cannot capture array storage through 'values'; "
            "copy it into a scalar-only struct or managed collection",
            1,
            76,
        ),
        (
            "spawn cannot capture array storage through 'values'; "
            "copy it into a scalar-only struct or managed collection",
            1,
            82,
        ),
        id="r23-spawn-capture",
    ),
]


@pytest.mark.parametrize(
    ("source", "expected"), REFUSALS + C_REFUSALS + ADJACENT_STRING_REFUSALS + CHAR_ARRAY_REFUSALS + VLA_REFUSALS
)
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
        static int clampTo(int, int);
        extern int shift(int, int);
        int shift(int value, int by);
        int shift(int, int);
        int shift(int value, int by) { return value << by; }
        static int clampTo(int value, int limit) { return value > limit ? limit : value; }
        int main(void) {
            assert(clampTo(9, 4) == 4 && shift(1, 3) == 8);
            assert(shift(by = 1, value = 2) == 4);
            return 0;
        }
        """,
        id="r01-static-and-extern-prototypes",
    ),
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
    pytest.param(
        """
        #include <assert.h>
        class Box { static unsigned char code[8] = "a"; static signed char sign[2] = "b"; }
        int main() {
            assert(Box.code[0] == 'a' && Box.code[1] == 0 && Box.sign[0] == 'b');
            return 0;
        }
        """,
        id="r04-class-static-char-array",
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


# Only expressions concatenate: an import path stays one literal, so a second
# literal after it is refused. The two import parsers already reported this
# differently before row 5 landed (btrcc has no same-line import check); the
# pair is pinned so a change to either side is deliberate.
IMPORT_PATH_REFUSALS = [
    pytest.param(
        'import "a.btrc" "b.btrc";\nint main() { return 0; }',
        (
            "import must be the only statement on its line "
            "(an import sharing a line with other code is never resolved)",
            1,
            17,
        ),
        ("Expected IDENT, got SEMICOLON ';'", 1, 25),
        id="r05-import-path",
    ),
]


@pytest.mark.parametrize(
    ("source", "reference_expected", "selfhost_expected"), VLA_DIVERGENT_REFUSALS + IMPORT_PATH_REFUSALS
)
def test_divergent_refusal_is_pinned_per_compiler(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    reference_expected: tuple[str, int, int],
    selfhost_expected: tuple[str, int, int],
) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)

    assert selfhost.returncode != 0 and reference.returncode != 0
    assert _diagnostic_identity(reference.stderr) == reference_expected
    assert _diagnostic_identity(selfhost.stderr) == selfhost_expected


def test_managed_vla_elements_are_borrowed_storage(semantic_btrcc: Path, tmp_path: Path) -> None:
    """A VLA of managed elements is a shallow aggregate, like a fixed array."""
    source = 'int main() { int count = 2; string names[count]; names[0] = f"a{count}"; return 0; }'
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)
    message = (
        "caller-owned temporary cannot be stored in a shallow aggregate; "
        "bind the owner to a local and store only its borrowed reference"
    )
    assert selfhost.returncode != 0 and reference.returncode != 0
    # The reference raises this during lowering, where it has no source position.
    assert reference.stderr.startswith(f"error: {message}\n")
    assert _diagnostic_identity(selfhost.stderr) == (message, 1, 61)
