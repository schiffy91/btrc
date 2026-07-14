"""Cast disambiguation (generic-type and nested-paren casts) and ARC cleanup for
generic-typed fields and classes exposing a free() method."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.cycle_symbols import cycle_visitor_symbol
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def test_cast_to_generic_type():
    c = emit_c(
        "class Box<T> { public T v; public Box(T v) { self.v = v; } }\n"
        "int main() { Box<int> b = new Box<int>(5); Box<int> c = (Box<int>)b; return c.v; }"
    )
    assert "Box_int" in c


def test_cast_with_nested_parens():
    c = emit_c("int main() { int a = 5; int b = (int)(a + 1); return b; }")
    assert "(int)" in c


def test_pointer_and_nullable_casts():
    c = emit_c(
        "class N { public int v; public N() { self.v = 0; } }\nint main() { N n = new N(); N m = (N)n; return m.v; }"
    )
    assert "(N" in c or "N*" in c


def test_arc_cleanup_generic_collection_field():
    c = emit_c(
        "class Holder {\n"
        "    public Vector<int> items;\n"
        "    public Holder() { self.items = new Vector<int>(); self.items.add(1); }\n"
        "}\n"
        "int main() { Holder h = new Holder(); return 0; }"
    )
    assert "Holder" in c


def test_arc_class_with_free_method():
    c = emit_c(
        "class Pool<T> {\n"
        "    public T item;\n"
        "    public Pool(T x) { self.item = x; }\n"
        "    public void free() { }\n"
        "}\n"
        "int main() { Pool<int> p = new Pool<int>(5); return 0; }"
    )
    assert "Pool_int" in c


def test_arc_class_field_with_generic_collection_release():
    # An owning class holds another class that itself owns a collection — the
    # destructor chain releases through both, exercising the generic-typed
    # field destroy-name resolution.
    c = emit_c(
        "class Bag { public Vector<int> data; public Bag() { self.data = new Vector<int>(); } }\n"
        "class Owner { public Bag bag; public Owner() { self.bag = new Bag(); } }\n"
        "int main() { Owner o = new Owner(); return 0; }"
    )
    assert "Owner" in c and "Bag" in c


def test_unused_cycle_visitor_is_structured_and_dead_eliminated():
    c = emit_c("""
        class Link {
            public Link next;
            public Link() { self.next = null; }
        }
        int main() { return 0; }
    """)

    assert cycle_visitor_symbol("Link") not in c


@pytest.mark.skipif(not COMPILERS or sys.platform == "win32", reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_managed_field_assignment_is_warning_clean_in_both_contexts(tmp_path: Path, c_compiler: str):
    c = emit_c("""
        int calls = 0;
        class Node {
            public int value;
            public Node next;
            public Node(int value) { self.value = value; self.next = null; }
        }
        Node makeNode(int value) { calls++; return new Node(value); }
        void exercise() {
            Node head = new Node(1);
            bool skipped = false && (head.next = makeNode(2)) != null;
            assert(!skipped);
            assert(calls == 0);
            Node chosen = true ? head : (head.next = makeNode(3));
            assert(chosen == head);
            assert(calls == 0);
            head.next = makeNode(7);
            assert(calls == 1);
            Node assigned = (head.next = head.next);
            assert(assigned.value == 7);
        }
        int main() { exercise(); return 0; }
    """)
    assert "(void)(((__btrc_field_obj_" in c
    assert "Node* assigned = ((__btrc_field_obj_" in c

    source = tmp_path / "managed_field_assignment.c"
    binary = tmp_path / "managed_field_assignment"
    source.write_text(c)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([binary], check=True, timeout=15)
