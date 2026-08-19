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
