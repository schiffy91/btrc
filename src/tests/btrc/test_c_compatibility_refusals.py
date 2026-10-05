"""C that btrc rejects on purpose (C rows 1, 7 and 18-24) fails identically in both compilers.

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

from src.tests.btrc.diagnostic_harness import diagnostic_identity
from src.tests.btrc.dual_frontend_harness import compile_snippet_pair, strict_c11_matrix
from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair

RESERVED = "'{}' is a reserved word and cannot be used as a name"
ATOMIC = "C11 '_Atomic' is not supported; use btrc's Atomic<T> for atomic storage"
COMPLEX = "C11 '_Complex' is not supported; btrc has no complex types"

VOID_LIST = "A 'void' parameter must be the only one, unnamed and unqualified: write '(void)'"
UNNAMED = "Parameter name required: only a function prototype without a body may omit it"
TUPLE_HINT = "; btrc reads a parenthesized comma list as a tuple, not C's comma operator"

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
    # Row 19: outside a for header a parenthesized comma list is a tuple
    # literal, not the comma operator, and the diagnostic says so.
    pytest.param(
        "int main() { int value = (1, 2); return value; }",
        ("Cannot assign 'Tuple<int, int>' to variable 'value' of type 'int'" + TUPLE_HINT, 1, 14),
        id="r19-comma-operator",
    ),
    pytest.param(
        "int main() { int value = 0; value = (1, 2); return value; }",
        ("Cannot assign 'Tuple<int, int>' to 'int'" + TUPLE_HINT, 1, 29),
        id="r19-comma-operator-assignment",
    ),
    pytest.param(
        "int main() { int i; int j = 0; for (i = 0; i < 2, j < 3; i++) {} return 0; }",
        ("Expected SEMICOLON, got COMMA ','", 1, 49),
        id="r19-comma-in-for-condition",
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

FUNCTION_BESIDE = "Function '{}' must be declared on its own, not beside other declarators"

# Row 3: several declarators (src/tests/c_compat/MultipleDeclarators.btrc). C
# itself rejects a missing declarator and a repeated name; btrc also refuses a
# function declarator beside others (legal C), several declarators on a
# nullable specifier and on `var`. Each declarator is checked on its own, so
# `int a[], b;` meets the unsized-array rule and a later name is not yet in
# scope in an earlier initializer.
DECLARATOR_REFUSALS = [
    pytest.param(
        "int main() {\n\tint first, ;\n\treturn 0;\n}",
        ("Expected declarator name, got SEMICOLON ';'", 2, 13),
        id="r03-missing-declarator",
    ),
    pytest.param(
        "int main() { for (int i = 0, ; i < 2; i++) {} return 0; }",
        ("Expected declarator name, got SEMICOLON ';'", 1, 30),
        id="r03-missing-for-declarator",
    ),
    pytest.param(
        "int main() { for (int i = 0, int j = 0; i < 2; i++) {} return 0; }",
        ("Expected declarator name, got INT 'int'", 1, 30),
        id="r03-repeated-specifier",
    ),
    pytest.param(
        "int f(), x;\nint main() { return 0; }",
        (FUNCTION_BESIDE.format("f"), 1, 5),
        id="r03-function-first",
    ),
    pytest.param(
        "int x, f();\nint main() { return 0; }",
        (FUNCTION_BESIDE.format("f"), 1, 8),
        id="r03-function-later",
    ),
    pytest.param(
        "int main() { int x, f(); return 0; }",
        (FUNCTION_BESIDE.format("f"), 1, 21),
        id="r03-block-function-later",
    ),
    pytest.param(
        "int main() { int a, a; return 0; }",
        ("Duplicate variable name 'a' in the same scope", 1, 21),
        id="r03-duplicate-local",
    ),
    pytest.param(
        "int main() { int *a, *a; return 0; }",
        ("Duplicate variable name 'a' in the same scope", 1, 23),
        id="r03-duplicate-local-at-name",
    ),
    pytest.param(
        "int main() { for (int i = 0, i = 1; i < 2; i++) {} return 0; }",
        ("Duplicate variable name 'i' in the same scope", 1, 30),
        id="r03-duplicate-for-declarator",
    ),
    pytest.param(
        "int main() { switch (1) { default: int a = 1, a = 2; break; } return 0; }",
        ("Duplicate variable name 'a' in the same scope", 1, 47),
        id="r03-duplicate-case-declarator",
    ),
    pytest.param(
        "int main() { switch (1) { case 1: int a; int a; break; default: break; } return 0; }",
        ("Duplicate variable name 'a' in the same scope", 1, 46),
        id="r03-duplicate-case-local",
    ),
    pytest.param(
        "int g, g;\nint main() { return 0; }",
        ("Duplicate definition of global 'g'", 1, 8),
        id="r03-duplicate-global",
    ),
    pytest.param(
        "struct P { int x, x; };\nint main() { return 0; }",
        ("Duplicate field 'x' in struct 'P'", 1, 19),
        id="r03-duplicate-struct-field",
    ),
    pytest.param(
        "int main() { int a[], b; return 0; }",
        ("Variable 'a' requires an array bound or initializer", 1, 14),
        id="r03-unsized-array-declarator",
    ),
    pytest.param(
        "typedef int A, A;\nint main() { return 0; }",
        ("Duplicate typedef name 'A'", 1, 16),
        id="r03-duplicate-typedef",
    ),
    pytest.param(
        "int main() { int a = b, b = 1; return a; }",
        ("Unresolved identifier 'b' used as a value", 1, 22),
        id="r03-later-declarator-not-in-scope",
    ),
    pytest.param(
        "int main() { int a = 1, *b = a; return 0; }",
        ("Cannot assign 'int' to variable 'b' of type 'int*'", 1, 25),
        id="r03-star-binds-per-declarator",
    ),
    pytest.param(
        "int main() { int x = 1, string = 2; return x; }",
        (RESERVED.format("string"), 1, 25),
        id="r03-reserved-later-declarator",
    ),
    pytest.param(
        "int main() { int? a, b; return 0; }",
        ("A nullable declaration declares one variable: write one declaration per nullable variable", 1, 20),
        id="r03-nullable-declarators",
    ),
    pytest.param(
        "int main() { var a = 1, b = 2; return 0; }",
        ("'var' declares one variable: write one 'var' declaration per variable", 1, 23),
        id="r03-var-declarators",
    ),
    pytest.param(
        "var a = 1, b = 2;\nint main() { return 0; }",
        ("'var' declares one variable: write one 'var' declaration per variable", 1, 10),
        id="r03-global-var-declarators",
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
        'int main() { char text[3] = "ab" "c"; return 0; }',
        (EXACT_FIT.format(3, 4), 1, 29),
        id="r04-adjacent-literals-exact-fit",
    ),
    pytest.param(
        'int main() { char text[4] = "ab" "\\x4" "1" "z"; return 0; }',
        (OVERFLOW.format(6, 4), 1, 29),
        id="r04-adjacent-literals-overflow",
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
    # Both compilers report a refused spawn capture at the spawn since CL-REQ-06.
    pytest.param(
        "int main() { int count = 2; int values[count]; values[0] = 1; "
        "var worker = spawn(() => values[0]); return worker.join() - 1; }",
        (
            "spawn cannot capture array storage through 'values'; "
            "copy it into a scalar-only struct or managed collection",
            1,
            76,
        ),
        id="r23-spawn-capture",
    ),
]

# Row 7: function-pointer declarators that a typedef spells instead, and
# variadic pointees, deferred to row 14. A head that names no type is the
# analyzer's ordinary unknown-type refusal; a signature mismatch is the
# CFunction assignment refusal.
FUNCTION_POINTER_RETURN = (
    "A function returning a function pointer needs a typedef: write 'typedef R (*Name)(...);' and return 'Name'"
)
FUNCTION_POINTER_ARRAY_TYPEDEF = (
    "A typedef cannot name an array of function pointers: write 'typedef R (*Name)(...);' and declare 'Name ops[n]'"
)
VARIADIC_POINTEE = "A variadic function-pointer type is not supported until variadic definitions (C row 14)"
FUNCTION_POINTER_REFUSALS = [
    pytest.param(
        "int (*pick(int))(int, int);\nint main() { return 0; }",
        (FUNCTION_POINTER_RETURN, 1, 11),
        id="r07-function-returning-function-pointer",
    ),
    pytest.param(
        "struct Table { int (*lookup(int))(int); };\nint main() { return 0; }",
        (FUNCTION_POINTER_RETURN, 1, 28),
        id="r07-field-returning-function-pointer",
    ),
    pytest.param(
        "void (*report)(const char*, ...);\nint main() { return 0; }",
        (VARIADIC_POINTEE, 1, 29),
        id="r07-variadic-pointee",
    ),
    pytest.param(
        "int apply(int (*)(int, ...), int);\nint main() { return 0; }",
        (VARIADIC_POINTEE, 1, 24),
        id="r07-variadic-abstract-parameter",
    ),
    pytest.param(
        "int (**indirect)(int);\nint main() { return 0; }",
        ("A pointer to a function pointer needs a typedef: write 'typedef R (*Name)(...);' and use 'Name*'", 1, 7),
        id="r07-pointer-to-function-pointer",
    ),
    pytest.param(
        "int main() { int (* const fixed)(int); return 0; }",
        (
            "A qualified function pointer needs a typedef: write 'typedef R (*Name)(...);' and use 'const Name'",
            1,
            21,
        ),
        id="r07-qualified-function-pointer",
    ),
    pytest.param(
        "typedef int Unary(int);\nint main() { return 0; }",
        ("A function type typedef is not supported: write 'typedef R (*Name)(...);' for the pointer", 1, 18),
        id="r07-function-type-typedef",
    ),
    pytest.param(
        "int main() { return (int)sizeof(int (*[3])(int)); }",
        ("An array of function pointers needs a name: write 'typedef R (*Name)(...);' and use 'Name[n]'", 1, 39),
        id="r07-abstract-array",
    ),
    pytest.param(
        "int apply(int (*callback)(void, int));\nint main() { return 0; }",
        (VOID_LIST, 1, 27),
        id="r07-void-beside-pointee-parameter",
    ),
    pytest.param(
        "int apply(int (*callback)(int, void));\nint main() { return 0; }",
        (VOID_LIST, 1, 32),
        id="r07-void-after-pointee-parameter",
    ),
    pytest.param(
        "int apply(int (*)(int)) { return 0; }\nint main() { return 0; }",
        (UNNAMED, 1, 11),
        id="r07-unnamed-definition-parameter",
    ),
    pytest.param(
        "int main() { Missing (*handler)(int); return 0; }",
        ("Generic argument 1 of Variable 'handler' uses unknown by-value type 'Missing'", 1, 14),
        id="r07-head-names-no-type",
    ),
    pytest.param(
        "int add(int a, int b) { return a + b; }\nint main() { int (*unary)(int) = add; return unary(1); }",
        ("Cannot assign 'CFunction<int, int, int>' to variable 'unary' of type 'CFunction<int, int>'", 2, 14),
        id="r07-signature-mismatch",
    ),
    pytest.param(
        "int (*f)(int), g(int);\nint main() { return 0; }",
        ("Function 'g' must be declared on its own, not beside other declarators", 1, 16),
        id="r07-function-beside-function-pointer",
    ),
    pytest.param(
        "int main() { int? (*f)(int), g; return 0; }",
        ("A nullable declaration declares one variable: write one declaration per nullable variable", 1, 28),
        id="r07-nullable-result-in-declarator-list",
    ),
    pytest.param(
        "typedef int (*Table[2])(int);\nint main() { return 0; }",
        (FUNCTION_POINTER_ARRAY_TYPEDEF, 1, 20),
        id="r07-typedef-of-function-pointer-array",
    ),
    pytest.param(
        "typedef int Count, (*Table[2])(int);\nint main() { return 0; }",
        (FUNCTION_POINTER_ARRAY_TYPEDEF, 1, 27),
        id="r07-later-typedef-of-function-pointer-array",
    ),
    pytest.param(
        "int a, (*)(int);\nint main() { return 0; }",
        ("Expected IDENT, got RPAREN ')'", 1, 10),
        id="r07-unnamed-later-declarator",
    ),
    pytest.param(
        "struct S { int (*)(int); };\nint main() { return 0; }",
        ("Expected IDENT, got RPAREN ')'", 1, 18),
        id="r07-unnamed-field",
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
]


UNION_PLAIN = "; a union cannot tell which member is live, so its members must be plain C values"
MAIN_LINE = "\nint main() { return 0; }"

# Row 9 (docs/design/c-compatibility.md "Refusals", records and tags). The
# struct messages were made identical first; each union message derives from
# its struct twin. A tag of another kind is refused in every type position.
RECORD_REFUSALS = [
    pytest.param(
        "struct S { int a; };\nstruct S { int a; };" + MAIN_LINE,
        ("Duplicate definition of struct 'S'", 2, 1),
        id="r09-struct-duplicate-definition",
    ),
    pytest.param(
        "struct S { };" + MAIN_LINE,
        ("Struct 'S' cannot have an empty body under strict C11", 1, 1),
        id="r09-struct-empty-body",
    ),
    pytest.param(
        "struct { int a; };" + MAIN_LINE,
        ("anonymous struct at top level must be named", 1, 1),
        id="r09-struct-anonymous",
    ),
    pytest.param(
        "struct S { int a; };\nint main() { S s; s.z = 1; return 0; }",
        ("Struct 'S' has no field 'z'", 2, 19),
        id="r09-struct-unknown-member",
    ),
    pytest.param(
        "union U { int a; int a; };" + MAIN_LINE,
        ("Duplicate field 'a' in union 'U'", 1, 22),
        id="r09-union-duplicate-member",
    ),
    pytest.param(
        "union U { int a; };\nunion U { int a; };" + MAIN_LINE,
        ("Duplicate definition of union 'U'", 2, 1),
        id="r09-union-duplicate-definition",
    ),
    pytest.param(
        "union U { };" + MAIN_LINE,
        ("Union 'U' cannot have an empty body under strict C11", 1, 1),
        id="r09-union-empty-body",
    ),
    pytest.param(
        "union { int a; };" + MAIN_LINE,
        ("anonymous union at top level must be named", 1, 1),
        id="r09-union-anonymous",
    ),
    pytest.param(
        "struct U { int a; };\nunion U;" + MAIN_LINE,
        ("Top-level name 'U' is declared as both struct and union", 2, 7),
        id="r09-struct-and-union",
    ),
    pytest.param(
        "union U { int a; };\nint main() { union U u; u.z = 1; return 0; }",
        ("Union 'U' has no field 'z'", 2, 25),
        id="r09-union-unknown-member",
    ),
    pytest.param(
        "struct P { int a; };\nint main() { union P p; return 0; }",
        ("'union P' does not name a union: 'P' is a struct", 2, 14),
        id="r09-wrong-keyword-struct",
    ),
    pytest.param(
        "enum Color { RED };\nint main() { struct Color c; return 0; }",
        ("'struct Color' does not name a struct: 'Color' is an enum", 2, 14),
        id="r09-wrong-keyword-enum",
    ),
    pytest.param(
        "class Box { public int v; }\nint main() { union Box* b = null; return 0; }",
        ("'union Box' does not name a union: 'Box' is a class", 2, 14),
        id="r09-wrong-keyword-class",
    ),
    pytest.param(
        "typedef int Id;\nint main() { int s = sizeof(struct Id); return s; }",
        ("'struct Id' does not name a struct: 'Id' is a typedef", 2, 29),
        id="r09-wrong-keyword-sizeof",
    ),
    pytest.param(
        "union U { int a; };\nint main() { void* p = null; return (struct U*)p == null ? 0 : 1; }",
        ("'struct U' does not name a struct: 'U' is a union", 2, 38),
        id="r09-wrong-keyword-cast",
    ),
    pytest.param(
        "union Holder { string text; int value; };" + MAIN_LINE,
        ("Union 'Holder' member 'text' cannot hold managed type 'string'" + UNION_PLAIN, 1, 23),
        id="r09-union-managed-member",
    ),
    pytest.param(
        "class Box { public int v; }\nunion Holder { Box box; int value; };" + MAIN_LINE,
        ("Union 'Holder' member 'box' cannot hold managed type 'Box'" + UNION_PLAIN, 2, 20),
        id="r09-union-class-member",
    ),
    pytest.param(
        "union Holder { CFunction<string, int> describe; int value; };" + MAIN_LINE,
        ("Union 'Holder' member 'describe' cannot hold managed type 'CFunction<string, int>'" + UNION_PLAIN, 1, 39),
        id="r09-union-managed-callback-member",
    ),
    pytest.param(
        "struct Pair { string name; int n; };\nunion Holder { struct Pair pair; int value; };" + MAIN_LINE,
        ("Union 'Holder' member 'pair' cannot hold 'Pair', which contains managed field 'name'" + UNION_PLAIN, 2, 28),
        id="r09-union-nested-managed-member",
    ),
    pytest.param(
        "union U { Atomic<int> counter; int a; };" + MAIN_LINE,
        (
            "Union field 'U.counter' cannot embed an Atomic<T> owner in shallow copyable storage; "
            "keep Atomic<T> as a direct class field or local owner",
            1,
            11,
        ),
        id="r09-union-atomic-member",
    ),
    pytest.param(
        "union U { RealtimeFunction callback; int a; };" + MAIN_LINE,
        (
            "Union 'U' member 'callback' cannot hold a RealtimeFunction; "
            "a union could reinterpret it without its realtime proof",
            1,
            28,
        ),
        id="r09-union-realtime-function",
    ),
    pytest.param(
        "union U { int n; int data[]; };" + MAIN_LINE,
        ("Union member 'U.data' cannot be a flexible array member", 1, 22),
        id="r09-union-flexible-array",
    ),
    pytest.param(
        "union U { int n; int[] data; };" + MAIN_LINE,
        ("Union field 'data' cannot use the 'T[] name' spelling; declare a pointer as 'T* data'", 1, 24),
        id="r09-union-array-spelling",
    ),
    pytest.param(
        "typedef union { int n; int data[]; } Holder;" + MAIN_LINE,
        ("Union member 'Holder.data' cannot be a flexible array member", 1, 28),
        id="r09-typedef-union-flexible-array",
    ),
    pytest.param(
        "typedef union { int n; } *Handle;" + MAIN_LINE,
        (
            "An untagged union in a typedef needs a plain declarator to name it; "
            "add a tag (typedef union Name { ... } *Alias;)",
            1,
            9,
        ),
        id="r09-typedef-union-unnamed",
    ),
    pytest.param(
        "union U { int i; float f; };\nint main() { U u = {1, 2}; return 0; }",
        (
            "Union 'U' initializer has 2 elements; a positional union initializer sets only the first member "
            "(use a designator such as {.f = ...})",
            2,
            20,
        ),
        id="r09-union-two-positional-elements",
    ),
    pytest.param(
        "union U { int i; float f; };\n@gpu void k(U u) { }" + MAIN_LINE,
        ("@gpu function 'k': type 'U' not allowed in parameter 'u' (use int, float, or bool)", 2, 6),
        id="r09-union-gpu",
    ),
    pytest.param(
        "struct P { int a; };\nint apply(CFunction<int, union P> f) { return 0; }" + MAIN_LINE,
        ("'union P' does not name a union: 'P' is a struct", 2, 26),
        id="r09-wrong-keyword-generic-argument",
    ),
    pytest.param(
        "struct P { int a; };\nstruct Q { union P inner; };" + MAIN_LINE,
        ("'union P' does not name a union: 'P' is a struct", 2, 12),
        id="r09-wrong-keyword-field",
    ),
    pytest.param(
        "interface Shape { int area(); }\nint main() { struct Shape* s = null; return 0; }",
        ("'struct Shape' does not name a struct: 'Shape' is an interface", 2, 14),
        id="r09-wrong-keyword-interface",
    ),
    pytest.param(
        "struct S { int a; int a; };" + MAIN_LINE,
        ("Duplicate field 'a' in struct 'S'", 1, 23),
        id="r09-struct-duplicate-member",
    ),
    pytest.param(
        "union U { int i; };\nint main() { U a = {1}; print(a); return 0; }",
        (
            "Union 'U' cannot be printed or formatted; a union cannot tell which member is live, "
            "so print one of its members",
            2,
            31,
        ),
        id="r09-union-print",
    ),
    pytest.param(
        'union U { int i; };\nint main() { U a = {1}; string s = f"{a}"; return 0; }',
        (
            "Union 'U' cannot be printed or formatted; a union cannot tell which member is live, "
            "so print one of its members",
            2,
            39,
        ),
        id="r09-union-f-string",
    ),
    pytest.param(
        "union U { int i; };\nint main() { U* p = new U(); return 0; }",
        ("new requires a class type, got 'U'", 2, 21),
        id="r09-union-new",
    ),
]


@pytest.mark.parametrize(
    ("source", "expected"),
    REFUSALS
    + C_REFUSALS
    + DECLARATOR_REFUSALS
    + ADJACENT_STRING_REFUSALS
    + CHAR_ARRAY_REFUSALS
    + VLA_REFUSALS
    + FUNCTION_POINTER_REFUSALS
    + RECORD_REFUSALS,
)
def test_refusal_is_identical_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    expected: tuple[str, int, int],
) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)

    assert selfhost.returncode != 0 and reference.returncode != 0
    assert diagnostic_identity(selfhost.stderr) == expected
    assert diagnostic_identity(reference.stderr) == expected


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
    for artifact in compile_snippet_pair(semantic_btrcc, tmp_path, source, name):
        strict_c11_matrix(artifact, tmp_path)


# Only expressions concatenate: an import path stays one literal, so a second
# literal after it is refused. The two import parsers already reported this
# differently before row 5 landed (btrcc has no same-line import check); the
# pair is pinned so a change to either side is deliberate.
# The two compilers word a duplicate class member differently for single
# declarations too; several declarators reach the same check, so the
# divergence is pinned, not new.
DECLARATOR_DIVERGENT_REFUSALS = [
    pytest.param(
        "class C { public int a, a; }\nint main() { return 0; }",
        ("Duplicate field 'a' in class 'C'", 1, 25),
        ("Duplicate member 'C.a'", 1, 25),
        id="r03-duplicate-class-field",
    ),
]

# Row 9: the compilers word `==` and the ownership operations on any record
# differently (a struct does too); a union meets the same refusals.
RECORD_DIVERGENT_REFUSALS = [
    pytest.param(
        "union U { int i; };\nint main() { U a = {1}; U b = {2}; bool same = a == b; return 0; }",
        ("operator '==' is not defined for aggregate operands 'U' and 'U'", 2, 48),
        ("Operator '==' is not defined for 'U' and 'U'", 2, 48),
        id="r09-union-equality",
    ),
    pytest.param(
        "union U { int i; };\nint main() { U a = {1}; keep a; return 0; }",
        ("Ownership operation is not valid for 'U'", 2, 25),
        ("keep is not valid for type 'U'", 2, 25),
        id="r09-union-keep",
    ),
    pytest.param(
        "union U { int i; };\nint main() { U a = {1}; release a; return 0; }",
        ("Ownership operation is not valid for 'U'", 2, 25),
        ("release is not valid for type 'U'", 2, 25),
        id="r09-union-release",
    ),
    pytest.param(
        "union U { int i; };\nint main() { U a = {1}; delete a; return 0; }",
        ("Ownership operation is not valid for 'U'", 2, 25),
        ("delete is not valid for type 'U'", 2, 25),
        id="r09-union-delete",
    ),
]

# Row 19: each parser words a missing expression its own way.
COMMA_DIVERGENT_REFUSALS = [
    # A missing operand is each parser's ordinary expression error.
    pytest.param(
        "int main() { int i; for (i = 0, ; i < 2; i++) {} return 0; }",
        ("Unexpected token ';' in expression", 1, 33),
        ("Expected expression, got SEMICOLON ';'", 1, 33),
        id="r19-missing-comma-operand",
    ),
]

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
    ("source", "reference_expected", "selfhost_expected"),
    VLA_DIVERGENT_REFUSALS
    + DECLARATOR_DIVERGENT_REFUSALS
    + COMMA_DIVERGENT_REFUSALS
    + IMPORT_PATH_REFUSALS
    + RECORD_DIVERGENT_REFUSALS,
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
    assert diagnostic_identity(reference.stderr) == reference_expected
    assert diagnostic_identity(selfhost.stderr) == selfhost_expected


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
    assert diagnostic_identity(selfhost.stderr) == (message, 1, 61)


# PLAN.md Stage 16's C1 exit requires byte-identical negative diagnostics for
# every C1 refusal. Each family below names the parametrization that pins it in
# test_refusal_is_identical_in_both_compilers, with the message it must carry,
# so a family cannot move to the divergent list or lose its pin unnoticed.
C1_REFUSAL_FAMILIES = {
    "r01-named-void": VOID_LIST,
    "r01-unnamed-definition": UNNAMED,
    "r02-declaration-if-body": DECLARATION_BODY,
    "r03-missing-declarator": "Expected declarator name, got SEMICOLON ';'",
    "r04-exact-fit": EXACT_FIT.format(3, 4),
    "r04-overflow": OVERFLOW.format(4, 2),
    "r05-fstring-then-literal": ADJACENT_FSTRING,
    "r06-file-scope-semicolon": "Unexpected token ';' at top level",
    "r07-signature-mismatch": "Cannot assign 'CFunction<int, int, int>' to variable 'unary' of type 'CFunction<int, int>'",
    "r19-comma-operator": "Cannot assign 'Tuple<int, int>' to variable 'value' of type 'int'" + TUPLE_HINT,
}


def test_every_c1_refusal_family_is_pinned_identically() -> None:
    identical = {
        param.id: param.values[1]
        for param in REFUSALS
        + C_REFUSALS
        + DECLARATOR_REFUSALS
        + ADJACENT_STRING_REFUSALS
        + CHAR_ARRAY_REFUSALS
        + FUNCTION_POINTER_REFUSALS
    }
    for family, message in C1_REFUSAL_FAMILIES.items():
        assert family in identical, family
        assert identical[family][0] == message, family


# Row 18 (C4, docs/known-language-gaps.md): btrc evaluates #if, but C compiles
# the program, so whatever #if cannot see is refused, never guessed
# (c-preprocessor-conditionals.md, "Refusals"). Each is pinned identically in
# both compilers, positions file-local; the host target conditions them, so
# every outcome here is target-independent.
NOT_A_TARGET_MACRO = (
    "Identifier '{0}' in #if is not a macro defined earlier in this file or a target macro; test it with defined({0})"
)
RESERVED_IN_IF = "'{}' is reserved for the C implementation and is not a btrc target macro; #if cannot test it"
FOREIGN_IN_IF = (
    "'{}' is defined by C headers or C compiler flags, not by btrc; #if is evaluated before C compilation "
    "and cannot test it"
)
UNDEFD_IN_CODE = "Source macro '{}' cannot be used in code because it is #undef'd; " + (
    "btrc emits every #define and #undef before the program"
)
MAIN = "\nint main() { return 0; }"

PREPROCESSOR_REFUSALS = [
    pytest.param("#if UNKNOWN_FLAG\n#endif" + MAIN, (NOT_A_TARGET_MACRO.format("UNKNOWN_FLAG"), 1, 5), id="r18-i1"),
    pytest.param("#if __LINE__ > 0\n#endif" + MAIN, (RESERVED_IN_IF.format("__LINE__"), 1, 5), id="r18-i2-line"),
    pytest.param("#ifdef __GNUC__\n#endif" + MAIN, (RESERVED_IN_IF.format("__GNUC__"), 1, 8), id="r18-i2-gnuc"),
    pytest.param("#ifdef PATH_MAX\n#endif" + MAIN, (FOREIGN_IN_IF.format("PATH_MAX"), 1, 8), id="r18-i3"),
    pytest.param(
        "#define VERSION(x) x\n#if VERSION(1)\n#endif" + MAIN,
        ("Function-like macro 'VERSION' cannot be used in #if; btrc expands only object-like macros there", 2, 5),
        id="r18-i4",
    ),
    pytest.param("#define X X\n#if X\n#endif" + MAIN, ("Macro 'X' expands to itself in #if", 2, 5), id="r18-i6"),
    pytest.param(
        "#define P a ## b\n#if P\n#endif" + MAIN,
        ("Macro 'P' uses '##', which #if does not evaluate", 2, 5),
        id="r18-i8",
    ),
    pytest.param(
        "#if 0 && (1, 2)\n#endif" + MAIN, ("',' is not allowed in a #if expression", 1, 12), id="r18-e7-comma"
    ),
    pytest.param(
        "#if '\\xff'\n#endif" + MAIN,
        ("Character constant '\\xff' in #if has a target-dependent value; write its integer value", 1, 5),
        id="r18-e10",
    ),
    pytest.param(
        "#if L'a'\n#endif" + MAIN,
        ("Wide character constant L'a' in #if; write its integer value", 1, 5),
        id="r18-e15",
    ),
    pytest.param("#if -1 << 1\n#endif" + MAIN, ("Left shift of negative value in #if expression", 1, 8), id="r18-a4"),
    pytest.param(
        "#if -1 < 0u\n#endif" + MAIN,
        ("#if expression converts negative value -1 to unsigned for '<'", 1, 8),
        id="r18-a5",
    ),
    pytest.param(
        "#undef max" + MAIN,
        ("#undef of 'max' is not allowed; btrc undefines only macros that its own sources #define", 1, 1),
        id="r18-m2",
    ),
    pytest.param(
        "#define WRAP 1\n#undef WRAP\nint main() { return WRAP; }",
        (UNDEFD_IN_CODE.format("WRAP"), 3, 21),
        id="r18-u1",
    ),
    pytest.param(
        "#define WRAP 1\n#define A WRAP\n#undef WRAP\nint main() { return A; }",
        (
            "Source macro 'A' cannot be used in code because it expands to #undef'd macro 'WRAP'; "
            "btrc emits every #define and #undef before the program",
            4,
            21,
        ),
        id="r18-u2",
    ),
    pytest.param(
        "#if 0\n#elifdef X\n#endif" + MAIN,
        ("'#elifdef' is C23; write '#elif defined(NAME)'", 2, 1),
        id="r18-d9-dead",
    ),
    pytest.param(
        "#if 0\n#define X \\\n1\n#endif" + MAIN,
        ("multi-line preprocessor directives are unsupported", 2, 11),
        id="r18-d10-dead",
    ),
    pytest.param(
        "%:if 1\n%:endif" + MAIN, ("'%:' is not supported as a spelling of '#'; write '#'", 1, 1), id="r18-d14"
    ),
    pytest.param(
        "#if 0\n#/**/define X 1\n#endif" + MAIN,
        ("a comment between '#' and the directive name is unsupported", 2, 2),
        id="r18-d16-dead",
    ),
    pytest.param(
        "#if 0\n#if\f1\n#endif\n#endif" + MAIN,
        ("only spaces and tabs may separate tokens in a preprocessor directive (C11 6.10p5)", 2, 4),
        id="r18-d17-dead",
    ),
    pytest.param(
        "#if 0\nint x = 08;\n#endif" + MAIN, ("Invalid digit '8' in octal literal", 2, 9), id="r18-dead-group-lexes"
    ),
]


@pytest.mark.parametrize(("source", "expected"), PREPROCESSOR_REFUSALS)
def test_preprocessor_refusal_is_identical_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    expected: tuple[str, int, int],
) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode != 0 and reference.returncode != 0
    assert diagnostic_identity(selfhost.stderr) == expected
    assert diagnostic_identity(reference.stderr) == expected


def test_null_directive_is_refused_in_both_compilers(semantic_btrcc: Path, tmp_path: Path) -> None:
    """The null directive `#` keeps lowering's unpositioned refusal."""

    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, "#" + MAIN):
        assert result.returncode != 0
        assert "malformed preprocessor directive" in result.stderr


PROGRAM_CHECK_IDS = ("P1", "P3-quoted-include", "P3-c-import", "P4")


def test_program_check_refusals_are_pinned_in_both_compilers() -> None:
    """P1-P4 need several files; the C4 suite pins each, through both
    compilers, in test_preprocessor_conditionals.DIAGNOSTIC_CASES."""

    from src.tests.btrc.test_preprocessor_conditionals import DIAGNOSTIC_CASES

    pinned = {case.name for case in DIAGNOSTIC_CASES}
    assert set(PROGRAM_CHECK_IDS) <= pinned
