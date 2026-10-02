"""Path-sensitive nullable-access diagnostics."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser

PRELUDE = """
class Box {
    public int value;
    public Box? next;
    public Box(int value) { self.value = value; self.next = null; }
}
"""


def _nullable_warnings(body: str) -> list[str]:
    program = Parser(Lexer(PRELUDE + body, "<nullable-flow>").tokenize()).parse()
    result = SemanticAnalyzer().analyze(program)
    assert result.errors == []
    return [warning for warning in result.warnings if "Non-optional access" in warning]


def test_short_circuit_guards_refine_only_the_reachable_rhs():
    warnings = _nullable_warnings("""
        bool guardedAnd(Box? box) {
            return box != null && box.value > 0;
        }
        bool guardedOr(Box? box) {
            return box == null || box.value > 0;
        }
        bool reversedAnd(Box? box) {
            return null != box && box.value > 0;
        }
        bool reversedOr(Box? box) {
            return null == box || box.value > 0;
        }
    """)

    assert warnings == []


def test_if_branches_and_terminating_null_guard_refine_the_safe_path():
    warnings = _nullable_warnings("""
        int guardedThen(Box? box) {
            if (box != null) { return box.value; }
            return 0;
        }
        int guardedElse(Box? box) {
            if (box == null) { return 0; }
            else { return box.value; }
        }
        int guardedContinuation(Box? box) {
            if (box == null) { return 0; }
            return box.value;
        }
        int guardedContinue(Box? box) {
            int result = 0;
            for (int index = 0; index < 1; index++) {
                if (box == null) { continue; }
                result = box.value;
            }
            return result;
        }
    """)

    assert warnings == []


def test_nested_member_guard_refines_the_same_stable_access_path():
    warnings = _nullable_warnings("""
        bool hasPositiveNext(Box box) {
            return box.next != null && box.next.value > 0;
        }
        int nextValue(Box box) {
            if (box.next == null) { return 0; }
            return box.next.value;
        }
    """)

    assert warnings == []


def test_unguarded_and_null_branch_accesses_still_warn():
    warnings = _nullable_warnings("""
        int unguarded(Box? box) { return box.value; }
        int wrongThen(Box? box) {
            if (box == null) { return box.value; }
            return 0;
        }
        bool wrongAnd(Box? box) {
            return box == null && box.value > 0;
        }
        bool wrongOr(Box? box) {
            return box != null || box.value > 0;
        }
    """)

    assert len(warnings) == 4


def test_refinement_does_not_leak_or_survive_assignment():
    warnings = _nullable_warnings("""
        int branchEnds(Box? box) {
            if (box != null) { int observed = box.value; }
            return box.value;
        }
        int reassigned(Box? box) {
            if (box == null) { return 0; }
            box = null;
            return box.value;
        }
        int branchReassigned(Box? box, bool clear) {
            if (box == null) { return 0; }
            if (clear) { box = null; }
            return box.value;
        }
        int loopGuardDoesNotEscape(Box? box) {
            for (int index = 0; index < 1; index++) {
                if (box == null) { continue; }
                int observed = box.value;
            }
            return box.value;
        }
        int switchGuardDoesNotEscape(Box? box, int branch) {
            switch (branch) {
                case 0:
                    if (box == null) { break; }
                    int observed = box.value;
                    break;
                default:
                    break;
            }
            return box.value;
        }
        int tryGuardDoesNotReachCatch(Box? box) {
            try {
                if (box == null) { return 0; }
            } catch (string message) {
                return box.value;
            }
            return 0;
        }
    """)

    assert len(warnings) == 6


def test_call_invalidates_refined_member_paths_that_callee_can_mutate():
    warnings = _nullable_warnings("""
        class Holder {
            public Box? item;
            public Holder(Box? item) { self.item = item; }
            public void clear() { self.item = null; }
        }
        int read(Holder holder) {
            if (holder.item != null) {
                holder.clear();
                return holder.item.value;
            }
            return 0;
        }
    """)

    assert len(warnings) == 1


def test_member_assignment_invalidates_facts_learned_through_an_alias():
    warnings = _nullable_warnings("""
        class Holder {
            public Box? item;
            public Holder(Box? item) { self.item = item; }
        }
        int read(Holder holder) {
            Holder alias = holder;
            if (holder.item != null) {
                alias.item = null;
                return holder.item.value;
            }
            return 0;
        }
    """)

    assert len(warnings) == 1


def test_call_invalidates_local_fact_after_its_address_has_escaped():
    warnings = _nullable_warnings("""
        extern void mutate(void* slot);
        int read(Box? box) {
            var slot = &box;
            if (box != null) {
                mutate(slot);
                return box.value;
            }
            return 0;
        }
    """)

    assert len(warnings) == 1


def test_c_for_body_and_update_share_the_true_condition_refinement():
    warnings = _nullable_warnings("""
        int visit(Box? box) {
            int total = 0;
            for (; box != null; box = box.next) {
                total += box.value;
            }
            return total;
        }
    """)

    assert warnings == []


def test_storing_a_value_known_to_be_non_null_refines_the_target():
    warnings = _nullable_warnings("""
        class Holder {
            public Box? item;
            public Holder() { self.item = null; }
        }
        class Memo {
            class Map<string, string>? memo = null;
            class string lookup(string key) {
                Map<string, string>? memo = Memo.memo;
                if (memo == null) { memo = {}; Memo.memo = memo; }
                if (memo.has(key)) { return memo.get(key); }
                memo.put(key, key);
                return key;
            }
        }
        int constructed(bool flag) {
            Box? box = null;
            if (flag) { box = Box(1); return box.value; }
            return 0;
        }
        int copiedFromGuardedField(Holder holder) {
            if (holder.item == null) { return 0; }
            var item = holder.item;
            return item.value;
        }
        int storedField(Holder holder) {
            holder.item = Box(2);
            return holder.item.value;
        }
        int bothBranches(bool flag) {
            Box? box = flag ? Box(1) : Box(2);
            return box.value;
        }
    """)

    assert warnings == []


def test_a_nullable_or_possibly_null_store_does_not_refine_the_target():
    warnings = _nullable_warnings("""
        class Holder {
            public Box? item;
            public Holder() { self.item = null; }
        }
        Box? find(int key) { return null; }
        int ternaryWithNull(bool flag) {
            Box? box = flag ? Box(1) : null;
            return box.value;
        }
        int reassignedNull() {
            Box? box = Box(1);
            box = null;
            return box.value;
        }
        int copiedNullable(Holder holder) {
            var item = holder.item;
            return item.value;
        }
        int nullableResult() {
            Box? box = find(1);
            return box.value;
        }
        int optionalChain(Holder holder) {
            Box? next = holder.item?.next;
            return next.value;
        }
        int callForgetsStoredField(Holder holder) {
            holder.item = Box(2);
            find(0);
            return holder.item.value;
        }
    """)

    assert len(warnings) == 6


def test_for_header_comma_operands_update_flow_like_single_expressions():
    # C row 19: each comma operand records and invalidates facts exactly as
    # the same assignment alone in the header does.
    warnings = _nullable_warnings("""
        int cleared(Box? box) {
            int index;
            if (box != null) {
                for (index = 0, box = null; index < 1; index++) {}
                return box.value;
            }
            return 0;
        }
        int filled() {
            int index;
            Box? box = null;
            for (index = 0, box = new Box(4); index < 1; index++) {}
            return box.value;
        }
    """)

    # Only `cleared` warns: its operand nulled the guarded path, and
    # `filled`'s operand stored a fresh object.
    assert len(warnings) == 1
    prelude_lines = PRELUDE.count("\n")
    assert f"{prelude_lines + 6}:" in warnings[0]


def test_a_call_inside_a_stored_value_invalidates_member_facts_first():
    warnings = _nullable_warnings("""
        class Holder {
            public Box? item;
            public Holder() { self.item = null; }
        }
        Box clearAndMake(Holder holder) { holder.item = null; return Box(3); }
        int callInStoredValue(Holder holder) {
            holder.item = Box(1);
            Box? other = null;
            other = clearAndMake(holder);
            return holder.item.value + other.value;
        }
        int callInCondition(Holder holder) {
            holder.item = Box(1);
            if (clearAndMake(holder).value > 0) { return holder.item.value; }
            return 0;
        }
    """)

    assert warnings == [
        "Non-optional access '.value' on nullable type 'Box?' — use '?.value' or check for null at 17:20",
        "Non-optional access '.value' on nullable type 'Box?' — use '?.value' or check for null at 21:58",
    ]


def test_a_loop_body_cannot_rely_on_facts_its_back_edge_kills():
    warnings = _nullable_warnings("""
        int whileWalk(Box head) {
            int total = 0;
            Box? node = head;
            while (total < 10) {
                total += node.value;
                node = node.next;
            }
            return total;
        }
        int forWalk(Box head) {
            int total = 0;
            for (Box? node = head; total < 10; node = node.next) {
                total += node.value;
            }
            return total;
        }
        int doWalk(Box head) {
            int total = 0;
            Box? node = head;
            do {
                total += node.value;
            } while ((node = node.next) != null || total < 10);
            return total;
        }
    """)

    assert len(warnings) == 6
    assert all(warning.startswith("Non-optional access") for warning in warnings)


def test_a_loop_guard_still_refines_every_iteration():
    warnings = _nullable_warnings("""
        int whileWalk(Box? head) {
            int total = 0;
            Box? node = head;
            while (node != null) {
                total += node.value;
                node = node.next;
            }
            return total;
        }
        int forWalk(Box? head) {
            int total = 0;
            for (Box? node = head; node != null; node = node.next) {
                total += node.value;
            }
            return total;
        }
        int untouched(Box head, int count) {
            Box? stable = head;
            int total = 0;
            for (int index = 0; index < count; index++) {
                Box? local = null;
                local = Box(index);
                total += stable.value + local.value;
            }
            return total;
        }
    """)

    assert warnings == []
