"""Runtime contracts for field defaults on monomorphized generic classes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(compiler for compiler in (shutil.which("gcc"), shutil.which("clang")) if compiler is not None)

SUCCESS_SOURCE = r"""
    #include <assert.h>

    int itemsAlive = 0;
    int leavesAlive = 0;
    int leavesDestroyed = 0;
    int ownersDestroyed = 0;

    struct Pair {
        int left;
        int right;
    };

    struct Buckets {
        int values[3];
    };

    class Item {
        public int id;
        public Item(int id) {
            self.id = id;
            itemsAlive++;
        }
        public void __del__() { itemsAlive--; }
    }

    Item? shared = null;

    class Leaf<T> {
        public int marker = 5;
        public T? value = null;

        public Leaf() {
            leavesAlive++;
            assert(self.marker == 5);
            assert(self.value == null);
        }

        public void __del__() {
            leavesAlive--;
            leavesDestroyed++;
        }
    }

    class Defaults<T> {
        public int scalar = 7;
        public string literal = "ok";
        public string allocated = "o" + "k";
        public Item owned = new Item(11);
        public Item? borrowed = shared;
        public T? genericValue = null;
        public Leaf<T> nested = new Leaf<T>();
        public Leaf<T> emptyNested = {};
        public Pair pair = {3, 4};
        public (int, int) tuple = {5, 6};
        public Buckets buckets = {{7, 8, 9}};

        public Defaults() {
            assert(self.scalar == 7);
            assert(self.literal.equals("ok"));
            assert(self.allocated.equals("ok"));
            assert(self.owned.id == 11);
            assert(self.borrowed == shared);
            assert(self.genericValue == null);
            assert(self.nested.marker == 5);
            assert(self.nested.value == null);
            assert(self.emptyNested.marker == 5);
            assert(self.pair.left == 3 && self.pair.right == 4);
            assert(self.tuple.0 == 5 && self.tuple.1 == 6);
            assert(self.buckets.values[0] == 7);
            assert(self.buckets.values[1] == 8);
            assert(self.buckets.values[2] == 9);
        }

        public void __del__() { ownersDestroyed++; }
    }

    int main() {
        int baselineStrings = (int)__btrc_string_live_count();
        shared = new Item(22);
        assert(itemsAlive == 1);

        Defaults<Item> value = new Defaults<Item>();
        assert(value.scalar == 7);
        assert(value.literal.equals("ok"));
        assert(value.allocated.equals("ok"));
        assert(value.owned.id == 11);
        assert(value.borrowed == shared);
        assert(value.genericValue == null);
        assert(value.nested.value == null);
        assert(value.emptyNested.value == null);
        assert(value.pair.left == 3 && value.pair.right == 4);
        assert(value.tuple.0 == 5 && value.tuple.1 == 6);
        assert(value.buckets.values[0] == 7);
        assert(value.buckets.values[1] == 8);
        assert(value.buckets.values[2] == 9);
        assert(itemsAlive == 2);
        assert(leavesAlive == 2);
        assert(leavesDestroyed == 0);
        assert((int)__btrc_string_live_count() == baselineStrings + 1);

        delete value;
        assert(ownersDestroyed == 1);
        assert(itemsAlive == 1);
        assert(leavesAlive == 0);
        assert(leavesDestroyed == 2);
        assert((int)__btrc_string_live_count() == baselineStrings);

        delete shared;
        assert(itemsAlive == 0);
        return 0;
    }
"""

FAILURE_SOURCE = r"""
    #include <assert.h>

    int nodesAlive = 0;
    int failedHooks = 0;

    class Node {
        public Node? next;
        public Node() { nodesAlive++; }
        public void __del__() { nodesAlive--; }
    }

    Node makeCycle() {
        Node node = new Node();
        node.next = node;
        return node;
    }

    int failDefault() {
        throw "field default failed";
    }

    class Failing<T> {
        public string allocated = "f" + "ail";
        public Node cycle = makeCycle();
        public int unreachable = failDefault();
        public T? genericValue = null;

        public Failing() { assert(false); }
        public void __del__() { failedHooks++; }
    }

    int main() {
        int baselineStrings = (int)__btrc_string_live_count();
        try {
            Failing<int> value = new Failing<int>();
            assert(value == null);
        } catch (string error) {
            assert(error.equals("field default failed"));
        }
        assert(nodesAlive == 0);
        assert(failedHooks == 0);
        assert((int)__btrc_string_live_count() == baselineStrings);
        return 0;
    }
"""

ARRAY_FIELD_SOURCE = r"""
    class Invalid<T> {
        public int[] values = {1, 2};
    }

    int main() {
        Invalid<int> value = new Invalid<int>();
        return value.values[0];
    }
"""

NORMAL_ARRAY_FIELD_SOURCE = r"""
    class Invalid {
        public int[] values = {1, 2};
    }

    int main() {
        Invalid value = new Invalid();
        return value.values[0];
    }
"""


def _compile_and_run(
    tmp_path: Path,
    compiler: str,
    source_text: str,
    stem: str,
) -> None:
    source = tmp_path / f"{stem}-{Path(compiler).name}.c"
    executable = source.with_suffix("")
    source.write_text(emit_c(source_text))
    subprocess.run(
        [
            compiler,
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
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_generic_defaults_initialize_and_release_every_field(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    _compile_and_run(
        tmp_path,
        c_compiler,
        SUCCESS_SOURCE,
        "generic-field-defaults",
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_throwing_generic_default_abandons_initialized_cycle(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    _compile_and_run(
        tmp_path,
        c_compiler,
        FAILURE_SOURCE,
        "generic-field-default-failure",
    )


@pytest.mark.parametrize(
    "source",
    [NORMAL_ARRAY_FIELD_SOURCE, ARRAY_FIELD_SOURCE],
    ids=["normal", "generic"],
)
def test_array_field_default_without_persistent_storage_fails_closed(source) -> None:
    program = Parser(Lexer(source, "<field-default>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)

    assert any("persistent backing storage" in error for error in analyzed.errors)
