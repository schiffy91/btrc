"""Assignment target lifetime and source-order regressions."""

import re
from pathlib import Path

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _tracked_strict_matrix,
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


def test_managed_identifier_assignments_cannot_bypass_the_typed_slot_owner() -> None:
    repository = Path(__file__).resolve().parents[3]
    lowering = repository / "src/compiler/btrc/ir/lowering"
    expressions = (lowering / "expressions.btrc").read_text()
    managed_types = (lowering / "ownership/managed_types.btrc").read_text()
    core = expressions[expressions.index("private IRNode materializeAssignmentCore(") :]
    identifier_plan = managed_types[
        managed_types.index("private ManagedIdentifierStorePlan? identifierStorePlan(") : managed_types.index(
            "/* Commit one already-owned replacement", managed_types.index("private ManagedIdentifierStorePlan?")
        )
    ]
    strong_store = managed_types[
        managed_types.index("private void appendStrongSlotCommit(") : managed_types.index(
            "public IRNode materializeStaticFieldStore("
        )
    ]

    assert core.index("self.managedTypes.planIdentifierStore(") < core.index("self.assignments.materializePlain(")
    assert "self.managedTypes.materializeIdentifierStore(" in core
    assert "self.lifetime.managedLocalValueType(storageName)" in identifier_plan
    assert "self.lifetime.managedLocalStorageCType(storageName)" in identifier_plan
    assert identifier_plan.index("registeredType != null") < identifier_plan.index("targetType == null")
    assert "!self.context.sourceCNameActive(storageName)" in identifier_plan
    assert "self.analyzed.globalHasDefinition.has(sourceName)" in identifier_plan
    assert "self.lifetime.cleanupRegistration(" in strong_store
    assert strong_store.index('value, "=", IRNode.literal("NULL")') < strong_store.index("self.lifetime.releaseValue(")


def test_managed_compound_updates_have_one_physical_storage_transaction() -> None:
    repository = Path(__file__).resolve().parents[3]
    lowering = repository / "src/compiler/btrc/ir/lowering"
    expressions = (lowering / "expressions.btrc").read_text()
    managed_types = (lowering / "ownership/managed_types.btrc").read_text()
    lifetime = (lowering / "ownership/lifetime.btrc").read_text()
    validation = repository / "src/compiler/btrc/analyzer/validation"
    storage_validation = (validation / "storage.btrc").read_text()
    type_validation = (validation / "types.btrc").read_text()
    core = expressions[expressions.index("private IRNode materializeAssignmentCore(") :]
    transaction = managed_types[
        managed_types.index("private void appendArcFieldPublication(") : managed_types.index(
            "public IRNode releaseField("
        )
    ]
    arc_publication = managed_types[
        managed_types.index("private void appendArcFieldPublication(") : managed_types.index(
            "/* Stabilize the physical target", managed_types.index("private void appendArcFieldPublication(")
        )
    ]
    plan = managed_types[
        managed_types.index("public ManagedCompoundStorePlan? planCompoundStore(") : managed_types.index(
            "/* Evaluate receiver and replacement once", managed_types.index("public ManagedCompoundStorePlan?")
        )
    ]

    assert core.index("self.managedTypes.planCompoundStore(") < core.index("self.lowerDirectCompound(")
    assert core.index("self.managedTypes.requiresManagedCompoundStore(") < core.index("self.lowerDirectCompound(")
    assert core.count("self.managedTypes.materializeCompoundStore(") == 1
    assert "enum ManagedCompoundStoreKind" in managed_types
    assert "MANAGED_COMPOUND_OWNED_SLOT" in plan
    assert "MANAGED_COMPOUND_STATIC_FIELD" in plan
    assert "MANAGED_COMPOUND_INSTANCE_FIELD" in plan
    assert "NK_PROPERTY_DECL" not in plan
    assert "NK_INDEX_EXPR" not in plan
    assert transaction.index('update.oldValue, "=", update.slot') < transaction.index(
        'update.rightValue, "=", loweredRight'
    )
    assert transaction.index("self.lifetime.retainValue(") < transaction.index('update.rightValue, "=", loweredRight')
    assert "self.appendCleanupProtection(" in transaction
    assert "self.lifetime.cleanupRegistration(" in managed_types
    assert "self.lifetime.replaceTypedEdge(" in arc_publication
    assert arc_publication.index("self.appendCleanupProtection(") < arc_publication.index(
        "self.lifetime.replaceTypedEdge("
    )
    assert arc_publication.index("self.lifetime.replaceTypedEdge(") < arc_publication.index(
        "self.appendReleaseAndClear("
    )
    assert "owner, false" in arc_publication
    assert "self.appendStrongSlotCommit(" in transaction
    assert "self.appendReleaseAndClear(" in transaction
    assert "public string storageCType;" in managed_types
    assert "private Node canonicalStorageType(Node typeExpr)" in managed_types
    assert "public Node? managedLocalValueType(string cName)" in lifetime
    assert "public string managedLocalStorageCType(string cName)" in lifetime
    assert "valueType, storageCType" in lifetime
    assert "public Node? binaryOverloadMethod(" in type_validation
    assert "public Node resolvedBinaryOverloadType(" in type_validation
    validator = storage_validation[storage_validation.index("public void validateAssignment(") :]
    assert "self.types.binaryOverloadMethod(target, op)" in validator
    assert "self.types.assignmentCompatible(target, result)" in validator
    assert validator.index("self.types.assignmentCompatible(target, result)") < validator.index(
        "return;", validator.index("self.types.assignmentCompatible(target, result)")
    )
    assert "self.compoundOverloadResultCompatible(" in core
    assert "self.compoundOverloadArgumentCompatible(" in core
    assert core.index("self.compoundOverloadResultCompatible(") < core.index("self.prepareTargetValue(")
    assert core.index("self.compoundOverloadArgumentCompatible(") < core.index("self.prepareTargetValue(")
    assert "concreteComputed = self.strings.upcastClassPointer(" in core
    assert core.index("concreteComputed = self.strings.upcastClassPointer(") < core.index(
        "self.managedTypes.materializeCompoundStore("
    )


def test_compound_overload_signature_must_fit_the_concrete_slot(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    cases = {
        "argument": (
            r"""
                class A {
                    public A() {}
                    public A __add__(string value) { return new A(); }
                }
                int main() {
                    A value = new A();
                    value += 1;
                    return 0;
                }
            """,
            "operator '+' expects 'string' but got 'int'",
            "operator '+' expects 'string' but got 'int'",
        ),
        "result": (
            r"""
                class A {
                    public A() {}
                    public int __add__(int value) { return value; }
                }
                int main() {
                    A value = new A();
                    value += 1;
                    return 0;
                }
            """,
            "cannot be stored in compound target",
            "cannot be stored in compound target",
        ),
        "typedef-result": (
            r"""
                class A {
                    public A() {}
                    public int __add__(int value) { return value; }
                }
                typedef A Alias;
                int main() {
                    Alias value = new A();
                    value += 1;
                    return 0;
                }
            """,
            "cannot be stored in compound target",
            "cannot be stored in compound target",
        ),
        "specialized-field": (
            r"""
                class A {
                    public A() {}
                    public int __add__(A value) { return 1; }
                }
                class Box<T> {
                    public T value;
                    public Box(T value) { self.value = value; }
                    public void add(T value) { self.value += value; }
                }
                int main() {
                    Box<A> box = new Box<A>(new A());
                    box.add(new A());
                    return 0;
                }
            """,
            "compound overload result cannot be stored in managed target after specialization",
            "cannot be stored in compound target",
        ),
        "specialized-argument": (
            r"""
                class A {
                    public A() {}
                    public A __add__(string value) { return new A(); }
                }
                class Box<T> {
                    public T value;
                    public Box(T value) { self.value = value; }
                    public void add(T value) { self.value += value; }
                }
                int main() {
                    A value = new A();
                    Box<A> box = new Box<A>(value);
                    box.add(value);
                    return 0;
                }
            """,
            "compound overload argument cannot be converted after specialization",
            "operator '+' parameter 'char*' cannot accept concrete 'a*'",
        ),
    }

    for name, (source, selfhost_diagnostic, reference_diagnostic) in cases.items():
        case_dir = tmp_path / name
        case_dir.mkdir()
        selfhost, _selfhost_c = _compile_source(
            semantic_btrcc,
            case_dir,
            source,
        )
        reference, _reference_c = _compile_reference_source(case_dir, source)
        assert selfhost.returncode != 0, name
        assert reference.returncode != 0, name
        assert selfhost_diagnostic in (selfhost.stdout + selfhost.stderr).lower(), name
        assert reference_diagnostic in (reference.stdout + reference.stderr).lower(), name


def test_generic_compound_rhs_conversion_materializes_concrete_to_string(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        int liveValues = 0;
        int conversions = 0;
        int additions = 0;

        class Value<T> {
            public Value() { liveValues++; }
            public void __del__() { liveValues--; }
            public string toString() {
                conversions++;
                return "converted";
            }
            public Value<T> __add__(string text) {
                additions++;
                assert(text.equals("converted"));
                return new Value<T>();
            }
        }

        class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public void add(T value) { self.value += value; }
        }

        int main() {
            {
                Value<int> left = new Value<int>();
                Value<int> right = new Value<int>();
                Box<Value<int>> box = new Box<Value<int>>(left);
                box.add(right);
                assert(conversions == 1 && additions == 1);
                assert(liveValues == 3);
                box = null;
                left = null;
                right = null;
            }
            assert(liveValues == 0);
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

    _tracked_strict_matrix(
        ("selfhost-generic-compound-string-conversion", selfhost_c),
        tmp_path,
    )
    _tracked_strict_matrix(
        ("reference-generic-compound-string-conversion", reference_c),
        tmp_path,
    )


def test_managed_compound_upcasts_a_derived_overload_result(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        int additions = 0;

        class Base {
            public Base() {}
            public Child __add__(int value) {
                additions += value;
                return new Child();
            }
        }

        class Child extends Base {
            public Child() {}
        }

        int main() {
            Base value = new Base();
            value += 1;
            assert(additions == 1);
            value = null;
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

    _tracked_strict_matrix(
        ("selfhost-managed-compound-result-upcast", selfhost_c),
        tmp_path,
    )
    _tracked_strict_matrix(
        ("reference-managed-compound-result-upcast", reference_c),
        tmp_path,
    )


def test_managed_identifier_slots_replace_exactly_one_ownership_unit(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        int alive = 0;
        int drops = 0;
        int rhsCalls = 0;

        class Item {
            public int id;
            public Item(int id) { self.id = id; alive++; }
            public void __del__() { alive--; drops++; }
        }

        Item globalSlot = null;

        Item makeWhileTwoAreAlive(int id) {
            rhsCalls++;
            assert(alive == 2);
            return new Item(id);
        }

        void localMatrix() {
            Item left = new Item(1);
            Item right = new Item(2);
            left = makeWhileTwoAreAlive(3);
            assert(rhsCalls == 1 && alive == 2 && drops == 1 && left.id == 3);
            left = right;
            assert(alive == 1 && drops == 2 && left == right);
            left = left;
            assert(alive == 1 && drops == 2);
            left = null;
            assert(alive == 1 && drops == 2);
            right = null;
            assert(alive == 0 && drops == 3);
        }

        void globalMatrix() {
            globalSlot = new Item(4);
            Item borrowed = new Item(5);
            globalSlot = borrowed;
            assert(alive == 1 && drops == 4 && globalSlot == borrowed);
            globalSlot = globalSlot;
            globalSlot = null;
            assert(alive == 1 && drops == 4);
            borrowed = null;
            assert(alive == 0 && drops == 5);
        }

        void exceptionMatrix() {
            try {
                Item value = new Item(6);
                value = new Item(7);
                assert(alive == 1 && drops == 6);
                throw "managed slot unwind";
            } catch (string error) {
                assert(error.equals("managed slot unwind"));
            }
            assert(alive == 0 && drops == 7);
        }

        class GenericSlots<T> {
            public void exercise(T first, T second) {
                T local = first;
                local = second;
                local = local;
                local = null;
            }
        }

        void genericMatrix() {
            Item first = new Item(8);
            Item second = new Item(9);
            GenericSlots<Item> slots = new GenericSlots<Item>();
            slots.exercise(first, second);
            assert(alive == 2 && drops == 7);
            first = null;
            second = null;
            delete slots;
            assert(alive == 0 && drops == 9);
        }

        int main() {
            localMatrix();
            globalMatrix();
            exceptionMatrix();
            genericMatrix();
            assert(alive == 0 && drops == 9 && rhsCalls == 1);
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

    _strict_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-managed-identifier-slots",
    )
    _strict_build_and_run(
        reference_c,
        tmp_path / "reference-managed-identifier-slots",
    )
    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-managed-identifier-slots-san",
        toolchain,
    )
    sanitized_build_and_run(
        reference_c,
        tmp_path / "reference-managed-identifier-slots-san",
        toolchain,
    )


def test_registered_raw_string_slot_uses_its_semantic_managed_type(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        extern void arc_test_allocation_checkpoint();
        extern long arc_test_allocation_delta();

        int main() {
            arc_test_allocation_checkpoint();
            {
                char* raw = __btrc_string_alloc(1);
                raw[0] = 'a';
                raw = null;
            }
            assert(arc_test_allocation_delta() == 0);
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

    _tracked_strict_matrix(("selfhost-raw-string-slot", selfhost_c), tmp_path)
    _tracked_strict_matrix(("reference-raw-string-slot", reference_c), tmp_path)


def test_typedef_managed_slots_dispatch_semantically_and_store_physically(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        int liveItems = 0;
        int itemDrops = 0;

        class Item {
            public int value;
            public Item(int value) {
                self.value = value;
                liveItems++;
            }
            public Item __add__(int delta) {
                return new Item(self.value + delta);
            }
            public void __del__() {
                liveItems--;
                itemDrops++;
            }
        }

        typedef Item ItemAlias;
        typedef string TextAlias;

        ItemAlias globalItem = null;
        TextAlias globalText = "";

        class AliasRoots {
            class ItemAlias item = null;
            class TextAlias text = "";
        }

        class AliasHolder {
            public ItemAlias item;
            public TextAlias text;
            public AliasHolder(ItemAlias item, TextAlias text) {
                self.item = item;
                self.text = text;
            }
            public void bump() {
                self.item += 1;
                self.text += "!";
            }
        }

        int main() {
            globalItem = new Item(1);
            globalItem += 1;
            globalText += "g";

            AliasRoots.item = new Item(3);
            AliasRoots.item += 1;
            AliasRoots.text += "s";

            ItemAlias local = new Item(5);
            local += 1;
            TextAlias localText = "l";
            localText += "!";

            AliasHolder holder = new AliasHolder(
                new Item(7), "h"
            );
            holder.bump();

            assert(globalItem.value == 2);
            assert(globalText.equals("g"));
            assert(AliasRoots.item.value == 4);
            assert(AliasRoots.text.equals("s"));
            assert(local.value == 6);
            assert(localText.equals("l!"));
            assert(holder.item.value == 8);
            assert(holder.text.equals("h!"));
            assert(liveItems == 4);

            local = null;
            localText = null;
            holder = null;
            globalItem = null;
            globalText = null;
            AliasRoots.item = null;
            AliasRoots.text = null;
            assert(liveItems == 0 && itemDrops == 8);
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
    generated = selfhost_c.read_text()
    assert "ItemAlias volatile* typed_slot" in generated
    assert "ItemAlias __btrc_update_old" in generated

    _strict_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-typedef-managed-slots",
    )
    _strict_build_and_run(
        reference_c,
        tmp_path / "reference-typedef-managed-slots",
    )
    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-typedef-managed-slots-san",
        toolchain,
    )
    sanitized_build_and_run(
        reference_c,
        tmp_path / "reference-typedef-managed-slots-san",
        toolchain,
    )


def test_arc_field_publication_keeps_owned_replacement_armed_until_commit(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        int liveValues = 0;
        int valueDrops = 0;
        int simpleCaught = 0;
        int compoundCaught = 0;

        class Value {
            public int value;
            public Value(int value) {
                self.value = value;
                liveValues++;
            }
            public Value __add__(int delta) {
                return new Value(self.value + delta);
            }
            public void __del__() {
                liveValues--;
                valueDrops++;
            }
        }

        class Owner {
            public Value field;
            public int mode;
            public Owner(int mode) {
                self.field = new Value(mode * 10);
                self.mode = mode;
            }
            public void __del__() {
                if (self.mode == 1) {
                    try {
                        self.field = new Value(20);
                    } catch (string error) {
                        simpleCaught++;
                    }
                } else {
                    try {
                        self.field += 1;
                    } catch (string error) {
                        compoundCaught++;
                    }
                }
            }
        }

        int main() {
            Owner simple = new Owner(1);
            simple = null;
            assert(simpleCaught == 1);
            assert(liveValues == 0 && valueDrops == 2);

            Owner compound = new Owner(2);
            compound = null;
            assert(compoundCaught == 1);
            assert(liveValues == 0 && valueDrops == 4);
            return 0;
        }
    """
    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    generated = selfhost_c.read_text()
    assert "__btrc_arc_replace_edge" in generated
    assert ", 0);" in generated

    _strict_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-destroying-owner-publication",
    )
    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-destroying-owner-publication-san",
        toolchain,
    )


def test_managed_compound_nonowned_shapes_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    item = r"""
        class Item {
            public int value;
            public Item(int value) { self.value = value; }
            public Item __add__(int delta) {
                return new Item(self.value + delta);
            }
        }
    """
    cases = {
        "shallow-struct": item
        + r"""
            struct Shallow { Item item; };
            int main() {
                Item owner = new Item(1);
                struct Shallow value = {owner};
                value.item += 1;
                return 0;
            }
        """,
        "generic-property": item
        + r"""
            class Box<T> {
                private T stored;
                public Box(T value) { self.stored = value; }
                public T value {
                    get { return self.stored; }
                    set { self.stored = value; }
                }
            }
            int main() {
                Box<Item> box = new Box<Item>(new Item(1));
                box.value += 1;
                return 0;
            }
        """,
        "generic-index": item
        + r"""
            class Box<T> {
                private T stored;
                public Box(T value) { self.stored = value; }
                public T get(int index) { return self.stored; }
                public void set(int index, T value) {
                    self.stored = value;
                }
            }
            int main() {
                Box<Item> box = new Box<Item>(new Item(1));
                box[0] += 1;
                return 0;
            }
        """,
    }

    for name, source in cases.items():
        case_dir = tmp_path / name
        case_dir.mkdir()
        selfhost, _selfhost_c = _compile_source(
            semantic_btrcc,
            case_dir,
            source,
        )
        reference, _reference_c = _compile_reference_source(
            case_dir,
            source,
        )
        assert selfhost.returncode != 0, name
        assert reference.returncode != 0, name
        assert "managed compound update" in (selfhost.stdout + selfhost.stderr).lower()
        assert "managed compound update" in (reference.stdout + reference.stderr).lower()


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


def test_managed_compound_physical_slots_commit_once_and_unwind_safely(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        int liveItems = 0;
        int itemDrops = 0;
        int addCalls = 0;
        int livePairs = 0;
        int liveLabels = 0;
        int liveTextBoxes = 0;
        int liveLinks = 0;

        class Item {
            public int id;
            public bool throwOnDrop;
            public Item(int id, bool throwOnDrop) {
                self.id = id;
                self.throwOnDrop = throwOnDrop;
                liveItems++;
            }
            public Item __add__(int delta) {
                addCalls++;
                if (delta == 99) { throw "operator failed"; }
                return new Item(self.id + delta, false);
            }
            public void __del__() {
                liveItems--;
                itemDrops++;
                if (self.throwOnDrop) { throw "destructor failed"; }
            }
        }

        Item globalItem = null;

        class Roots {
            class Item item = null;
        }

        class Holder {
            public Item item;
            public int scalar;
            public Holder(int id) {
                self.item = new Item(id, false);
                self.scalar = id;
            }
        }

        int replaceCurrentWithBomb(Holder holder) {
            holder.item = new Item(500, true);
            return 1;
        }

        class GenericBox<T> {
            public Item value;
            public GenericBox(Item value) { self.value = value; }
            public Item bump(int delta) {
                self.value += delta;
                return self.value;
            }
        }

        class Pair {
            public int value;
            public Pair(int value) { self.value = value; livePairs++; }
            public Pair __add__(keep Pair other) {
                return new Pair(self.value + other.value);
            }
            public void __del__() { livePairs--; }
        }

        class Label {
            public Label() { liveLabels++; }
            public string toString() { return "!"; }
            public void __del__() { liveLabels--; }
        }

        class TextBox {
            public string text;
            public TextBox(string text) {
                self.text = text;
                liveTextBoxes++;
            }
            public TextBox __add__(string suffix) {
                return new TextBox(self.text + suffix);
            }
            public void __del__() { liveTextBoxes--; }
        }

        class Link {
            public Link next;
            public Link() { self.next = null; liveLinks++; }
            public Link __add__(Link replacement) { return replacement; }
            public void __del__() { liveLinks--; }
        }

        void rootAndLocalMatrix() {
            globalItem = new Item(1, false);
            globalItem += 2;
            assert(globalItem.id == 3 && liveItems == 1);

            Roots.item = new Item(4, false);
            Roots.item += 3;
            assert(Roots.item.id == 7 && liveItems == 2);

            Item local = new Item(10, false);
            local += (local = new Item(11, false)).id;
            assert(local.id == 21 && liveItems == 3);

            local = null;
            globalItem = null;
            Roots.item = null;
            assert(liveItems == 0);
        }

        void fieldAndGenericMatrix() {
            Holder holder = new Holder(20);
            Item result = (
                holder.item += (holder = new Holder(30)).scalar
            );
            assert(result.id == 50);
            result = null;
            holder = null;
            assert(liveItems == 0);

            GenericBox<Item> box = new GenericBox<Item>(
                new Item(40, false)
            );
            Item genericResult = box.bump(2);
            assert(genericResult.id == 42);
            genericResult = null;
            box = null;
            assert(liveItems == 0);
        }

        void rhsOwnershipMatrix() {
            Pair left = new Pair(1);
            Pair right = new Pair(2);
            left += right;
            assert(left.value == 3 && right.value == 2 && livePairs == 2);
            left = null;
            right = null;
            assert(livePairs == 0);

            TextBox text = new TextBox("start");
            text += new Label();
            assert(text.text == "start!");
            assert(liveLabels == 0 && liveTextBoxes == 1);
            text = null;
            assert(liveTextBoxes == 0);
        }

        void unwindMatrix() {
            Item local = new Item(60, false);
            bool operatorCaught = false;
            try {
                local += 99;
            } catch (string error) {
                operatorCaught = error == "operator failed";
            }
            assert(operatorCaught && local.id == 60 && liveItems == 1);
            local = null;
            assert(liveItems == 0);

            Holder holder = new Holder(70);
            bool destructorCaught = false;
            try {
                holder.item += replaceCurrentWithBomb(holder);
            } catch (string error) {
                destructorCaught = error == "destructor failed";
            }
            assert(destructorCaught);
            assert(holder.item.id == 71 && liveItems == 1);
            holder = null;
            assert(liveItems == 0);
        }

        void cycleMatrix() {
            Link root = new Link();
            Link old = new Link();
            root.next = old;
            root.next += root;
            old = null;
            root = null;
        }

        int main() {
            rootAndLocalMatrix();
            fieldAndGenericMatrix();
            rhsOwnershipMatrix();
            unwindMatrix();
            cycleMatrix();
            assert(liveItems == 0 && livePairs == 0);
            assert(liveLabels == 0 && liveTextBoxes == 0 && liveLinks == 0);
            assert(addCalls == 7);
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

    _strict_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-managed-compound-slots",
    )
    _strict_build_and_run(
        reference_c,
        tmp_path / "reference-managed-compound-slots",
    )
    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-managed-compound-slots-san",
        toolchain,
    )
    sanitized_build_and_run(
        reference_c,
        tmp_path / "reference-managed-compound-slots-san",
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
