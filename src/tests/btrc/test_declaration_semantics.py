"""Self-hosted declaration, storage, and emitted-symbol contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        (
            "struct Item { int value; }; struct Item { int other; }; int main() { return 0; }",
            "Duplicate struct definition 'Item'",
        ),
        (
            "struct Item { Item child; }; int main() { return 0; }",
            "By-value struct dependency cycle",
        ),
        (
            "struct Item; Item value; int main() { return 0; }",
            "Incomplete struct 'Item' cannot be used by value",
        ),
        (
            "Unknown value; int main() { return 0; }",
            "unknown by-value type 'Unknown'",
        ),
        (
            "int value = run(); int run() { return 1; } int main() { return value; }",
            "requires a C constant/address initializer",
        ),
        (
            "extern int value = 1; int main() { return 0; }",
            "cannot have an initializer with extern storage",
        ),
        (
            "int values[]; int main() { return 0; }",
            "requires an array bound or initializer",
        ),
        (
            "const int value = 1; int main() { value = 2; return 0; }",
            "Cannot modify const storage",
        ),
        (
            "const int* value; int main() { value[0] = 2; return 0; }",
            "Cannot modify const storage",
        ),
        (
            "class Box {} int Box_new() { return 0; } int main() { return 0; }",
            "Emitted C symbol 'Box_new' collides",
        ),
        (
            "class Box { public int value { get { return 1; } } "
            "public int get_value() { return 2; } } "
            "int main() { return 0; }",
            "Emitted C symbol 'Box_get_value' collides",
        ),
        (
            "class Box { public int _prop_value; public int value { get; } } int main() { return 0; }",
            "Instance storage name '_prop_value' collides",
        ),
        (
            "int btrc_internal() { return 0; } int main() { return 0; }",
            "compiler-reserved 'btrc_' prefix",
        ),
        (
            "int runtime() { return 1; } enum E { A = runtime() }; int main() { return 0; }",
            "requires an integral constant expression",
        ),
        (
            "enum E { A = B, B = 1 }; int main() { return 0; }",
            "using only earlier members",
        ),
        (
            "enum class Payload { Empty } enum E { A = Payload.Empty }; int main() { return 0; }",
            "using only earlier members",
        ),
        (
            'int main() { switch ("x") { default: return 0; } }',
            "Switch subject must be integral",
        ),
        (
            "int runtime() { return 1; } int main() { switch (1) { case runtime(): return 0; default: return 1; } }",
            "Switch case requires an integral constant expression",
        ),
        (
            "int main() { switch (1) { case 1: return 0; case 1 + 0: return 1; default: return 2; } }",
            "Duplicate switch case value",
        ),
        (
            "int main() { switch (1) { default: return 0; default: return 1; } }",
            "more than one default case",
        ),
        (
            "int first = 1; int second = first; int main() { return 0; }",
            "requires a C constant/address initializer",
        ),
        (
            "int zero = 1 / 0; int main() { return 0; }",
            "requires a C constant/address initializer",
        ),
        (
            "int bound() { return 2; } int values[bound()]; int main() { return 0; }",
            "Array bound for Global 'values' must be a constant expression",
        ),
        (
            "struct Pair { int left; int right; }; int main() { Pair pair = {1, 2, 3}; return 0; }",
            "initializer elements but struct 'Pair' has 2 fields",
        ),
        (
            'struct Pair { int left; int right; }; int main() { Pair pair = {1, "bad"}; return 0; }',
            "field 'right' expects 'int' but got 'string'",
        ),
        (
            "struct Pair { int left; int right; }; int main() { Pair pair = {1, 2}; return pair.missing; }",
            "Struct 'Pair' has no field 'missing'",
        ),
        (
            'int main() { int values[2] = {1, "bad"}; return 0; }',
            "element 1 expects 'int' but got 'string'",
        ),
        (
            "int main() { int[] source = {1}; int[] copy = source; return 0; }",
            "requires an array initializer",
        ),
        (
            "import std.map;\nMap<int, int> values = {}; int main() { return 0; }",
            "requires a C constant/address initializer",
        ),
        (
            "int main() { __fn_ptr<int, int>* callback; return callback(1); }",
            "Value 'callback' is not callable",
        ),
    ],
)
def test_invalid_declaration_contracts_are_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert diagnostic in result.stderr


@pytest.mark.parametrize(
    "source",
    [
        """
            struct Left { Right right; };
            struct Right { int value; };
            int main() {
                Left left = {{42}};
                return left.right.value == 42 ? 0 : 1;
            }
        """,
        """
            struct Left;
            struct Right { Left* left; };
            struct Left { Right* right; };
            int main() {
                Left left = {NULL};
                Right right = {&left};
                left.right = &right;
                return left.right->left == &left ? 0 : 1;
            }
        """,
        """
            typedef Later Alias;
            typedef int Later;
            int main() { Alias value = 42; return value == 42 ? 0 : 1; }
        """,
        """
            extern int value;
            int value = 42;
            int main() { return value == 42 ? 0 : 1; }
        """,
        """
            const int first = 1;
            const int* current = &first;
            const int second = 2;
            int main() {
                current = &second;
                return *current == 2 ? 0 : 1;
            }
        """,
        """
            class Leaf { public int visit() { return 42; } }
            int main() {
                Leaf leaf = Leaf();
                return leaf.visit() == 42 ? 0 : 1;
            }
        """,
        """
            enum E { A = 5, B, C = A + 3, D };
            int main() {
                switch (C) {
                    case B + 2: return B == 6 && D == 9 ? 0 : 1;
                    default: return 2;
                }
            }
        """,
        """
            enum { FIRST = 5, SECOND };
            int main() { return SECOND == 6 ? 0 : 1; }
        """,
        """
            enum First { BASE = 1, NEXT = BASE + 1 };
            enum Second { BASE = 3, NEXT = BASE + 1 };
            int main() {
                return First.NEXT == 2 && Second.NEXT == 4 ? 0 : 1;
            }
        """,
        """
            enum Alias { FIRST = 1, SECOND = 1 };
            int main() {
                Alias value = SECOND;
                return strcmp(value.toString(), "FIRST");
            }
        """,
        """
            enum class Payload { First, Second }
            int selected = Payload.Second;
            int main() {
                switch (selected) {
                    case Payload.Second: return 0;
                    default: return 1;
                }
            }
        """,
        "void main() { return; }",
        """
            #include <time.h>
            int main() {
                struct timespec value;
                value.tv_sec = 0;
                return (int)value.tv_sec;
            }
        """,
        """
            int plus(int value) { return value + 1; }
            __fn_ptr<int, int> callback = plus;
            int main() { return callback(41) == 42 ? 0 : 1; }
        """,
        """
            int values[2] = {41, 42};
            int* first = values;
            int* second = &values[1];
            int main() { return *first == 41 && *second == 42 ? 0 : 1; }
        """,
        """
            int main() {
                int values[2] = {};
                return values[0] == 0 && values[1] == 0 ? 0 : 1;
            }
        """,
        """
            int main() {
                char* values[1];
                values[0] = "ok";
                return strcmp(values[0], "ok");
            }
        """,
        """
            struct Pair { int left; int right; };
            Pair makePair() { return {20, 22}; }
            int main() {
                Pair pair = {};
                pair = {20, 22};
                Pair made = makePair();
                return pair.left + pair.right == 42
                    && made.left + made.right == 42 ? 0 : 1;
            }
        """,
        """
            typedef __fn_ptr<int, int> Unary;
            int increment(int value) { return value + 1; }
            class Callbacks {
                public Unary instance;
                public Unary property { get; set; }
                public Callbacks(Unary callback) {
                    self.instance = callback;
                    self.property = callback;
                }
            }
            int main() {
                Unary local = increment;
                Callbacks callbacks = Callbacks(local);
                int first = local(39);
                int second = callbacks.instance(40);
                int third = callbacks.property(41);
                return first == 40 && second == 41 && third == 42 ? 0 : 1;
            }
        """,
    ],
)
def test_valid_declaration_contracts_compile_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    _strict_build_and_run(generated, tmp_path / "program")


def test_native_abi_allowlist_only_permits_bodyless_prototype(semantic_btrcc: Path, tmp_path: Path) -> None:
    prototype = "bool btrc_gpu_available(); int main() { return 0; }"
    accepted, _ = _compile_source(semantic_btrcc, tmp_path, prototype)
    assert accepted.returncode == 0, accepted.stderr

    definition = "bool btrc_gpu_available() { return true; } int main() { return 0; }"
    rejected, _ = _compile_source(semantic_btrcc, tmp_path, definition)
    assert rejected.returncode == 1
    assert "compiler-reserved 'btrc_' prefix" in rejected.stderr
