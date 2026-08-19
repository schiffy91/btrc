"""Assignment target lifetime and source-order regressions."""

import re
from pathlib import Path

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_assignment_boundary_uses_the_expression_owner_and_typed_plan() -> None:
    repository = Path(__file__).resolve().parents[3]
    lowering = repository / "src/compiler/btrc/ir/lowering"
    expressions = (lowering / "expressions.btrc").read_text()
    assignments = (lowering / "assignments.btrc").read_text()
    start = expressions.index("private IRNode? lowerOwnedAssignment(")
    end = expressions.index("public IRNode? lowerOwnedUnaryUpdate(", start)
    boundary = expressions[start:end]
    core_start = expressions.index("private IRNode materializeAssignmentCore(")
    core = expressions[core_start:]

    assert "class AssignmentPlan {" in assignments
    assert "class AssignmentLowerer {" in assignments
    assert "public AssignmentPlan plan(" in assignments
    assert "public IRNode materializePlain(" in assignments
    assert "self.materializeAssignmentCore(" in boundary
    assert "self.lowerExpr(" not in boundary
    assert "return self.assignments.materializePlain(plan, target, value);" in core
    assert "generator." not in assignments + boundary


def test_nested_managed_field_assignment_has_one_result_boundary(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        int live_nodes = 0;

        class Node {
            public Node direct;
            public Node() { live_nodes++; self.direct = null; }
            public void __del__() { live_nodes--; }
        }

        Node makeChain() {
            Node root = new Node();
            root.direct = new Node();
            return root;
        }

        void closeCycle(Node root) {
            root.direct.direct = root;
        }

        int main() {
            {
                Node root = makeChain();
                closeCycle(root);
            }
            assert(live_nodes == 0);
            return 0;
        }
    """
    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    selfhost_body = selfhost_c.read_text().rsplit("void closeCycle(", 1)[1].split("\nint main(void)", 1)[0]
    boundary_pattern = r"\b__btrc_boundary_result_\d+\b"
    assert len(set(re.findall(boundary_pattern, selfhost_body))) == 1

    _strict_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-nested-field-assignment",
    )
    _strict_build_and_run(
        reference_c,
        tmp_path / "reference-nested-field-assignment",
    )


def test_assignment_targets_survive_destructive_rhs(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        class Item {
            public int id;
            public Item(int id) { self.id = id; }
            public Item __add__(int delta) {
                return new Item(self.id + delta);
            }
        }

        class Holder {
            public Item item;
            public int scalar;
            public int value { get; set; }
            public Holder(int id) {
                self.item = new Item(id);
                self.scalar = id;
                self.value = id;
            }
        }

        class Bag {
            public int value;
            public Bag(int value) { self.value = value; }
            public int get(int index) { return self.value + index; }
            public void set(int index, int value) {
                self.value = value - index;
            }
            public int index() { return 0; }
        }

        int main() {
            Holder scalarHolder = new Holder(1);
            int scalarResult = (
                scalarHolder.scalar =
                    (scalarHolder = new Holder(2)).scalar
            );
            assert(scalarResult == 2);
            assert(scalarHolder.scalar == 2);

            Holder fieldHolder = new Holder(1);
            Item fieldResult = (
                fieldHolder.item =
                    (fieldHolder = new Holder(2)).item
            );
            assert(fieldResult.id == 2);

            Holder compoundHolder = new Holder(1);
            Item compoundResult = (
                compoundHolder.item +=
                    (compoundHolder = new Holder(2)).scalar
            );
            assert(compoundResult.id == 3);

            Item local = new Item(1);
            local += (local = new Item(2)).id;
            assert(local.id == 3);

            Holder propertyHolder = new Holder(1);
            int propertyResult = (
                propertyHolder.value =
                    (propertyHolder = new Holder(2)).value
            );
            assert(propertyResult == 2);

            Bag bag = new Bag(1);
            int indexedResult = (
                bag[0] = (bag = new Bag(2))[0]
            );
            assert(indexedResult == 2);
            assert(bag[0] == 2);

            Bag indexedTarget = new Bag(1);
            indexedTarget[(indexedTarget = new Bag(2)).index()] = 7;
            assert(indexedTarget[0] == 2);
            return 0;
        }
    """
    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-assignment-lifetime",
        toolchain,
    )
    sanitized_build_and_run(
        reference_c,
        tmp_path / "reference-assignment-lifetime",
        toolchain,
    )


def test_compound_update_loads_before_mutating_rhs(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = "int main() { int value = 1; value += value++; return value == 2 ? 0 : 1; }"
    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-compound-order",
        toolchain,
    )
    sanitized_build_and_run(
        reference_c,
        tmp_path / "reference-compound-order",
        toolchain,
    )
