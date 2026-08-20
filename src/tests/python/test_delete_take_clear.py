"""Structured IR contracts for terminal deletion."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import IRAddressOf, IRCall, IRFieldAccess, IRNode, IRVar
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

EFFECTFUL_EDGE_OWNER_SOURCE = r"""
#include <assert.h>

int ownerCalls = 0;
bool alternateOwner() {
    ownerCalls++;
    return (ownerCalls % 2) == 1;
}

class Item {
    public Item() {}
}

class Holder {
    public Item child;
    public Holder() { self.child = new Item(); }
}

void exerciseOrdinary(Holder left, Holder right) {
    release (alternateOwner() ? left : right).child;
    assert(ownerCalls == 1);
    assert(left.child == null && right.child != null);
    delete (alternateOwner() ? left : right).child;
    assert(ownerCalls == 2);
    assert(right.child == null);
}

class Exercise<T> {
    public void run(Holder left, Holder right) {
        release (alternateOwner() ? left : right).child;
        assert(ownerCalls == 1);
        assert(left.child == null && right.child != null);
        delete (alternateOwner() ? left : right).child;
        assert(ownerCalls == 2);
        assert(right.child == null);
    }
}

int main() {
    Item original = new Item();
    Item alias = original;
    release original;
    assert(original == null && alias != null);
    delete alias;

    Holder left = new Holder();
    Holder right = new Holder();
    exerciseOrdinary(left, right);
    delete left;
    delete right;

    ownerCalls = 0;
    left = new Holder();
    right = new Holder();
    Exercise<int> exercise = new Exercise<int>();
    exercise.run(left, right);
    delete exercise;
    delete left;
    delete right;
    return 0;
}
"""


def _lower(source: str):
    program = Parser(Lexer(source, "<physical-slot>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    return IRLowerer(analyzed).lower()


def _strict_build_and_run(tmp_path: Path, c_compiler: str, stem: str, generated: str) -> None:
    c_path = tmp_path / f"{stem}.c"
    binary = tmp_path / stem
    c_path.write_text(generated)
    build = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(c_path),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [str(binary)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr


def test_delete_clears_saved_class_slot_before_destroy() -> None:
    generated = emit_c("class Item {} int main() { Item value = new Item(); delete value; return 0; }")
    main = generated[generated.rindex("int main(") :]
    slot = main.index("Item* volatile* __btrc_delete_slot")
    destroy = main.index("__btrc_arc_destroy_slot(", slot)
    assert slot < destroy
    assert "__btrc_arc_slot_access_" in main[destroy : destroy + 300]
    assert "Item* volatile* typed_slot" in generated
    assert "(*typed_slot) = ((Item*)replacement);" in generated


def test_generic_class_and_raw_delete_use_the_shared_boundary() -> None:
    generated = emit_c(
        "class Item {} "
        "class Drop<T> { "
        "  public void dropNull() { Item value = (Item)null; delete value; } "
        "} "
        "int main() { "
        "  int* raw = null; delete raw; "
        "  Drop<string> drop = new Drop<string>(); drop.dropNull(); "
        "  return 0; "
        "}"
    )
    assert generated.count("__btrc_delete_slot") >= 2
    assert "__btrc_arc_destroy_slot(((volatile void*)__btrc_delete_slot" in generated
    assert "__btrc_arc_slot_access_" in generated
    assert "free(__btrc_delete_value" in generated
    assert "__btrc_arc_destroy(" not in generated


def test_effectful_edge_owner_is_one_shared_ir_value_in_ordinary_and_generic_bodies() -> None:
    module = _lower(EFFECTFUL_EDGE_OWNER_SOURCE)
    bodies = [
        function.body
        for function in module.function_defs
        if function.name in {"exerciseOrdinary", "btrc_Exercise_int_run"}
    ]
    assert len(bodies) == 2

    for body in bodies:
        nodes = list(IRNode.walk_value(body))
        owner_calls = [node for node in nodes if isinstance(node, IRCall) and node.callee == "alternateOwner"]
        addressed_owners = [
            node.expr.obj.name
            for node in nodes
            if (
                isinstance(node, IRAddressOf)
                and isinstance(node.expr, IRFieldAccess)
                and node.expr.field == "child"
                and isinstance(node.expr.obj, IRVar)
            )
        ]
        edge_owners = []
        for node in nodes:
            if not isinstance(node, IRCall):
                continue
            if node.callee == "__btrc_arc_replace_edge":
                edge_owners.append(node.args[3].name)
            elif node.callee == "__btrc_arc_destroy_edge":
                edge_owners.append(node.args[2].name)

        assert len(owner_calls) == 2
        assert len(addressed_owners) == 2
        assert addressed_owners == edge_owners
        assert all(name.startswith("__btrc_storage_receiver_") for name in edge_owners)


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_effectful_edge_owner_release_and_delete_run_once_in_ordinary_and_generic_bodies(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    _strict_build_and_run(
        tmp_path,
        c_compiler,
        "effectful-edge-owner",
        emit_c(EFFECTFUL_EDGE_OWNER_SOURCE),
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_indexed_delete_and_release_preserve_physical_slots(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    generated = emit_c(
        """
        #include <assert.h>
        #include <stdlib.h>

        int indexCalls = 0;
        int nextIndex() { indexCalls++; return 0; }
        class Item {}

        void releaseOnce() {
            Item item = new Item();
            Item slots[1] = {null};
            keep item;
            slots[0] = item;
            release slots[nextIndex()];
            assert(indexCalls == 1);
            assert(slots[0] == null);
        }

        class Drop<T> {
            public void deleteOnce() {
                void* slots[1] = {malloc(4)};
                delete slots[nextIndex()];
                assert(indexCalls == 2);
                assert(slots[0] == null);
            }
            public void releaseOnce() {
                Item item = new Item();
                Item slots[1] = {null};
                keep item;
                slots[0] = item;
                release slots[nextIndex()];
                assert(indexCalls == 3);
                assert(slots[0] == null);
            }
        }

        int main() {
            releaseOnce();
            Drop<int> drop = new Drop<int>();
            drop.deleteOnce();
            drop.releaseOnce();
            delete drop;
            return 0;
        }
        """
    )
    _strict_build_and_run(tmp_path, c_compiler, "physical-slots", generated)


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_shared_delete_rejection_preserves_root_and_edge_slots(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    fixture = Path(__file__).parents[1] / "btrc/fixtures/lifecycle_shared_delete_runtime.btrc"
    _strict_build_and_run(
        tmp_path,
        c_compiler,
        "shared-delete",
        emit_c(fixture.read_text()),
    )
