"""C function-pointer declarators are ``CFunction`` spelled the C way (C row 7).

docs/design/c-compatibility.md ("Stage 16 r07"): ``T (*name)(params)``, its
array form ``T (*name[n])(params)`` and the abstract ``T (*)(params)`` build
the same ``__fn_ptr`` ``TypeExpr`` as ``CFunction<T, params...>``, so the
analyzer and lowering need no change. Each declarator program here lowers to
the same raw IR (``--emit-ir``) and the same C, with and without ``--debug``,
as its ``CFunction`` twin, through both compilers (btrcc has no
``--emit-ir``, so its C carries the comparison). The canonical AST of every
r07 corpus program, positions included, matches between the two parsers, and
a statement whose head is not a type stays an expression in both (D20).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.dual_frontend_harness import compile_snippet_pair, strict_c11_matrix
from src.tests.btrc.test_c_compatibility_bodies import _reference, _relative, _selfhost, _write

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "src/tests/c_compat"
PARSE_TOOL = REPO / "src/compiler/btrc/tools/ParseMain.btrc"

# Each pair is (C declarator, CFunction); every declaration keeps its line, so
# the #line markers of the two spellings are identical.
TWINS = [
    pytest.param(
        """
        int add(int a, int b) { return a + b; }
        int (*globalOperation)(int, int) = add;
        static int (*hidden)(int, int) = add;
        int main() {
            int (*operation)(int, int) = add;
            char* (*skipper)(char*);
            return operation(1, 2) + globalOperation(0, 0) + hidden(0, 0) - 3;
        }
        """,
        """
        int add(int a, int b) { return a + b; }
        CFunction<int, int, int> globalOperation = add;
        static CFunction<int, int, int> hidden = add;
        int main() {
            CFunction<int, int, int> operation = add;
            CFunction<char*, char*> skipper;
            return operation(1, 2) + globalOperation(0, 0) + hidden(0, 0) - 3;
        }
        """,
        id="locals-and-globals",
    ),
    pytest.param(
        """
        typedef void (*DestroyFn)(void*);
        typedef int (*Compare)(const void* left, const void* right);
        void dispose(void* value) {}
        int main() { DestroyFn destroy = dispose; destroy(null); return 0; }
        """,
        """
        typedef CFunction<void, void*> DestroyFn;
        typedef CFunction<int, const void*, const void*> Compare;
        void dispose(void* value) {}
        int main() { DestroyFn destroy = dispose; destroy(null); return 0; }
        """,
        id="typedefs",
    ),
    pytest.param(
        """
        int add(int a, int b) { return a + b; }
        int (*table[2])(int, int) = {add, add};
        int main() { int (*local[])(int, int) = {add}; return table[1](1, 1) + local[0](0, 0) - 2; }
        """,
        """
        int add(int a, int b) { return a + b; }
        CFunction<int, int, int> table[2] = {add, add};
        int main() { CFunction<int, int, int> local[] = {add}; return table[1](1, 1) + local[0](0, 0) - 2; }
        """,
        id="arrays",
    ),
    pytest.param(
        """
        #include <stdlib.h>
        int ascending(const void* left, const void* right) { return *(const int*)left - *(const int*)right; }
        void sortInts(int* values, size_t count, int (*compare)(const void* left, const void* right)) { qsort(values, count, sizeof(int), compare); }
        int run(int (*)(int), int);
        int run(int (*entry)(int), int value) { return entry(value); }
        void each(void (*visit)(int), void (*)(void (*)(int)));
        int same(int value) { return value; }
        int main() { int values[2] = {2, 1}; sortInts(values, 2, ascending); return run(same, values[0]) - 1; }
        """,
        """
        #include <stdlib.h>
        int ascending(const void* left, const void* right) { return *(const int*)left - *(const int*)right; }
        void sortInts(int* values, size_t count, CFunction<int, const void*, const void*> compare) { qsort(values, count, sizeof(int), compare); }
        int run(CFunction<int, int>, int);
        int run(CFunction<int, int> entry, int value) { return entry(value); }
        void each(CFunction<void, int> visit, CFunction<void, CFunction<void, int>>);
        int same(int value) { return value; }
        int main() { int values[2] = {2, 1}; sortInts(values, 2, ascending); return run(same, values[0]) - 1; }
        """,
        id="parameters",
    ),
    pytest.param(
        """
        void tick(void) {}
        struct Codec { int (*encode)(const char* text, int length); void (*reset)(void); };
        class Dispatcher { public void (*handler)(void) = tick; }
        int main() { Dispatcher dispatcher = new Dispatcher(); dispatcher.handler(); return 0; }
        """,
        """
        void tick(void) {}
        struct Codec { CFunction<int, const char*, int> encode; CFunction<void> reset; };
        class Dispatcher { public CFunction<void> handler = tick; }
        int main() { Dispatcher dispatcher = new Dispatcher(); dispatcher.handler(); return 0; }
        """,
        id="fields",
    ),
    pytest.param(
        """
        int compareInts(const int* left, const int* right) { return *left - *right; }
        int main() {
            int (*generic)(const void*, const void*) = (int (*)(const void*, const void*))compareInts;
            return (int)sizeof(int (*)(int)) - (int)sizeof(generic);
        }
        """,
        """
        int compareInts(const int* left, const int* right) { return *left - *right; }
        int main() {
            CFunction<int, const void*, const void*> generic = (CFunction<int, const void*, const void*>)compareInts;
            return (int)sizeof(CFunction<int, int>) - (int)sizeof(generic);
        }
        """,
        id="casts-and-sizeof",
    ),
    pytest.param(
        """
        int twice(int value) { return value * 2; }
        int apply(int (*outer)(int (*inner)(int), int), int value) { return value; }
        int call(int (*f)(int), int value) { return f(value); }
        int takesArray(int (*f)(int values[4]));
        int main() { return apply(call, 0); }
        """,
        """
        int twice(int value) { return value * 2; }
        int apply(CFunction<int, CFunction<int, int>, int> outer, int value) { return value; }
        int call(CFunction<int, int> f, int value) { return f(value); }
        int takesArray(CFunction<int, int*> f);
        int main() { return apply(call, 0); }
        """,
        id="nested-and-array-parameters",
    ),
    pytest.param(
        """
        int add(int a, int b) { return a + b; }
        static int (*plus)(int, int) = add, (*minus)(int, int) = add;
        typedef int (*BinaryOp)(int, int), *Counter;
        struct Ops { int (*first)(int, int), count, (*second)(void); };
        int main() { int (*f)(int, int) = add, v = 1, *p = &v, (*g)(int, int) = f; return g(v, *p) - 2; }
        """,
        """
        int add(int a, int b) { return a + b; }
        static CFunction<int, int, int> plus = add; static CFunction<int, int, int> minus = add;
        typedef CFunction<int, int, int> BinaryOp; typedef int* Counter;
        struct Ops { CFunction<int, int, int> first; int count; CFunction<int> second; };
        int main() { CFunction<int, int, int> f = add; int v = 1; int* p = &v; CFunction<int, int, int> g = f; return g(v, *p) - 2; }
        """,
        id="declarator-lists",
    ),
]


@pytest.mark.parametrize(("declarator", "cfunction"), TWINS)
def test_declarator_lowers_exactly_like_its_cfunction_twin(
    semantic_btrcc: Path,
    tmp_path: Path,
    declarator: str,
    cfunction: str,
) -> None:
    left = _write(tmp_path / "declarator", declarator)
    right = _write(tmp_path / "cfunction", cfunction)

    for flags in (("--emit-ir",), (), ("--debug",)):
        assert _relative(_reference(left, *flags), left) == _relative(_reference(right, *flags), right), flags
    for flags in ((), ("--debug",)):
        assert _relative(_selfhost(semantic_btrcc, left, *flags), left) == _relative(
            _selfhost(semantic_btrcc, right, *flags), right
        ), flags


@pytest.fixture(scope="module")
def parse_tool(selfhost_driver) -> Path:
    return selfhost_driver(PARSE_TOOL, compile_flags=("-pedantic-errors",))


@pytest.mark.parametrize(
    "corpus",
    [
        "FunctionPointerArray.btrc",
        "FunctionPointerCast.btrc",
        "FunctionPointerDeclaratorLists.btrc",
        "FunctionPointerField.btrc",
        "FunctionPointerLocal.btrc",
        "FunctionPointerParameter.btrc",
        "FunctionPointerTypedef.btrc",
    ],
)
def test_canonical_ast_and_positions_match_the_reference(parse_tool: Path, corpus: str) -> None:
    program = CORPUS / corpus
    parsed = subprocess.run([str(parse_tool), str(program)], capture_output=True, text=True, timeout=30)
    reference = subprocess.run(
        [sys.executable, "-m", "tools.compiler_codegen.main", "dump-ast", str(program)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert parsed.returncode == 0, parsed.stderr
    assert reference.returncode == 0, reference.stderr
    assert parsed.stdout == reference.stdout


# D20: `T (*name)(...)` declares only when T names a type. The parser's rule
# is syntactic: a head that is not a bare identifier, or a list only a
# parameter-type list can spell, declares; an initializer always does,
# because a call result is never assignable.
DISAMBIGUATION = [
    pytest.param(
        """
        #include <assert.h>
        int twice(int value) { return value * 2; }
        CFunction<int, int> pick(int key) { return twice; }
        int main() {
            int key = 0;
            int* pointer = &key;
            pick (*pointer)(4);
            assert(pick(*pointer)(4) == 8);
            return 0;
        }
        """,
        id="call-of-a-dereference-stays-an-expression",
    ),
    pytest.param(
        """
        #include <assert.h>
        typedef int Count;
        struct Pair { int left; int right; };
        Count twice(Count value) { return value * 2; }
        int sum(struct Pair pair) { return pair.left + pair.right; }
        size_t one(const char* text) { return (size_t)1; }
        int main() {
            size_t (*measure)(const char*);
            measure = one;
            assert(measure("x") == (size_t)1);
            Count (*scale)(Count) = twice;
            Count (*named)(Count value) = twice;
            int (*total)(struct Pair);
            total = sum;
            struct Pair pair = {1, 2};
            assert(scale(2) == 4 && named(3) == 6 && total(pair) == 3);
            return 0;
        }
        """,
        id="parameter-type-lists-and-initializers",
    ),
]


@pytest.mark.parametrize("source", DISAMBIGUATION)
def test_disambiguation_runs_strictly_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    source: str,
) -> None:
    name = request.node.callspec.id
    for artifact in compile_snippet_pair(semantic_btrcc, tmp_path, source, name):
        strict_c11_matrix(artifact, tmp_path)
