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


def test_a_guard_ending_in_a_hosted_noreturn_call_refines_the_continuation():
    warnings = _nullable_warnings("""
        int afterExit(Box? box) {
            if (box == null) { exit(1); }
            return box.value;
        }
        int afterAbort(Box? box) {
            if (box == null) { fprintf(stderr, "missing\\n"); abort(); }
            return box.value;
        }
        int afterElseExit(Box? box) {
            if (box != null) { } else { exit(2); }
            return box.value;
        }
    """)

    assert warnings == []


def test_a_callable_whose_every_path_diverges_never_returns():
    warnings = _nullable_warnings("""
        void die(string message) {
            fprintf(stderr, "%s\\n", message);
            exit(1);
        }
        void dieTwice(string message) { die(message); }
        void raise(string message) { throw message; }
        void either(bool quiet) {
            if (quiet) { exit(0); } else { die("loud"); }
        }
        int viaFunction(Box? box) {
            if (box == null) { dieTwice("missing"); }
            return box.value;
        }
        int viaThrow(Box? box) {
            if (box == null) { raise("missing"); }
            return box.value;
        }
        int viaBranches(Box? box) {
            if (box == null) { either(true); }
            return box.value;
        }
    """)

    assert warnings == []


def test_a_callable_that_can_return_or_only_recurses_still_returns():
    warnings = _nullable_warnings("""
        void maybe(bool stop) {
            if (stop) { return; }
            exit(1);
        }
        void ping(int depth) { pong(depth); }
        void pong(int depth) { ping(depth); }
        int afterMaybe(Box? box) {
            if (box == null) { maybe(true); }
            return box.value;
        }
        int afterRecursion(Box? box) {
            if (box == null) { ping(0); }
            return box.value;
        }
    """)

    assert warnings == [
        "Non-optional access '.value' on nullable type 'Box?' — use '?.value' or check for null at 16:20",
        "Non-optional access '.value' on nullable type 'Box?' — use '?.value' or check for null at 20:20",
    ]


def test_static_and_self_methods_that_never_return_refine_their_callers():
    warnings = _nullable_warnings("""
        class Checks {
            class void fail(string message) {
                fprintf(stderr, "%s\\n", message);
                exit(1);
            }
            private void stop(string message) { throw message; }
            public int viaSelf(Box? box) {
                if (box == null) { self.stop("missing"); }
                return box.value;
            }
        }
        int viaStatic(Box? box) {
            if (box == null) { Checks.fail("missing"); }
            return box.value;
        }
    """)

    assert warnings == []


def test_a_self_call_an_override_can_return_from_is_not_proof():
    warnings = _nullable_warnings("""
        class Base {
            public void stop(string message) { throw message; }
            public int read(Box? box) {
                if (box == null) { self.stop("missing"); }
                return box.value;
            }
        }
        class Lenient extends Base {
            public void stop(string message) { }
        }
    """)

    assert warnings == [
        "Non-optional access '.value' on nullable type 'Box?' — use '?.value' or check for null at 12:24",
    ]


def test_code_after_a_call_that_never_returns_is_unreachable():
    warnings = _nullable_warnings("""
        int afterExit(Box? box) {
            exit(1);
            return box.value;
        }
        int afterDivergingBranches(Box? box, bool flag) {
            if (flag) { exit(1); } else { throw "no"; }
            return box.value;
        }
        int afterDivergingTry(Box? box) {
            try { throw "no"; } catch (string error) { abort(); }
            return box.value;
        }
        int reachedAgain(Box? box) {
            int total = 0;
            for (int index = 0; index < 2; index++) {
                if (index > 5) { exit(1); }
                total += box.value;
            }
            return total;
        }
    """)

    assert warnings == [
        "Non-optional access '.value' on nullable type 'Box?' — use '?.value' or check for null at 24:26",
    ]


def _store_warnings(body: str) -> list[str]:
    program = Parser(Lexer(PRELUDE + body, "<nullable-flow>").tokenize()).parse()
    result = SemanticAnalyzer().analyze(program)
    assert result.errors == []
    return [warning for warning in result.warnings if warning.startswith("Possibly-null value stored")]


def _store(context: str, type_name: str, line: int, col: int) -> str:
    return (
        f"Possibly-null value stored in non-nullable {context} of type '{type_name}' — check for null first"
        f" at {line}:{col}"
    )


def test_a_possibly_null_value_stored_into_a_non_nullable_reference_warns():
    warnings = _store_warnings("""
        Box? maybe(int value) { if (value > 0) { return Box(value); } return null; }
        void take(Box box) { }
        class Holder {
            public Box item = Box(0);
            public void put(Box box) { self.item = box; }
        }
        Box stores(Holder holder, Box? box) {
            Box local = maybe(1);
            holder.item = box;
            take(box);
            holder.put(null);
            Box chosen = local.value > 0 ? local : box;
            Box fallback = box ?? maybe(2);
            return box;
        }
    """)

    assert warnings == [
        _store("variable 'local'", "Box", 15, 25),
        _store("assignment target", "Box", 16, 27),
        _store("argument 1 of 'take'", "Box", 17, 18),
        _store("argument 1 of 'put'", "Box", 18, 24),
        _store("variable 'chosen'", "Box", 19, 26),
        _store("variable 'fallback'", "Box", 20, 28),
        _store("return value", "Box", 21, 20),
    ]


def test_a_store_the_flow_proves_or_that_targets_a_nullable_reference_is_silent():
    warnings = _store_warnings("""
        Box? maybe(int value) { if (value > 0) { return Box(value); } return null; }
        void fail(string message) { fprintf(stderr, "%s\\n", message); exit(1); }
        Box guarded(Box? box) {
            if (box == null) { fail("missing"); }
            Box local = box;
            Box? optional = maybe(1);
            Box chosen = optional != null ? optional : local;
            Box fallback = maybe(2) ?? local;
            Box fresh = Box(3);
            optional = fresh;
            Box again = optional;
            return local;
        }
        Box exited(int value) {
            Box? box = maybe(value);
            if (box == null) { exit(1); }
            return box;
        }
    """)

    assert warnings == []


def test_static_field_paths_carry_facts_until_a_call():
    warnings = _store_warnings("""
        class Shared {
            class Box? cached = null;
            class Box current() {
                if (Shared.cached == null) { Box fresh = Box(1); Shared.cached = fresh; return fresh; }
                return Shared.cached;
            }
            class Box afterCall() {
                if (Shared.cached == null) { return Box(2); }
                fprintf(stderr, "call\\n");
                return Shared.cached;
            }
        }
    """)

    assert warnings == [_store("return value", "Box", 17, 24)]


def test_a_failure_method_on_a_field_of_self_never_returns():
    warnings = _nullable_warnings("""
        class Reporter {
            public void fail(string message) { fprintf(stderr, "%s\\n", message); exit(1); }
        }
        class User {
            private Reporter reporter = Reporter();
            public int read(Box? box) {
                if (box == null) { self.reporter.fail("missing"); }
                return box.value;
            }
        }
    """)

    assert warnings == []
