"""Strict left-to-right expression sequencing contracts."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import IRCommaExpr, IRStmtExpr
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.btrc.dual_frontend_harness import compile_ownership_reference
from src.tests.btrc.runtime_ownership_harness import require_sanitizers, sanitized_build_and_run
from src.tests.btrc.selfhost_snippet_harness import compile_source, strict_build_and_run


def _compile_both(semantic_btrcc: Path, tmp_path: Path, source: str):
    selfhost, selfhost_c = compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = compile_ownership_reference(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_c, reference_c


def _walk(value):
    yield value
    if is_dataclass(value):
        for field in fields(value):
            yield from _walk(getattr(value, field.name))
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)


def test_eager_operands_are_structurally_sequenced() -> None:
    source = """
        int pair(int first, int second) { return first * 10 + second; }
        int main() {
            int value = 0;
            return pair(value++, value++) + (value++ + value++);
        }
    """
    program = Parser(Lexer(source, "sequencing.btrc").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    module = IRLowerer(analyzed).lower()
    nodes = list(_walk(module))
    assert sum(isinstance(node, IRStmtExpr) for node in nodes) >= 2
    assert sum(isinstance(node, IRCommaExpr) for node in nodes) >= 2

    integration = Path("src/compiler/btrc/ir/lowering/Expressions.btrc").read_text()
    boundary = Path("src/compiler/btrc/ir/lowering/ownership/Calls.btrc").read_text()
    assert "boundary.addLoweredOperand(" in integration
    assert "return boundary.finish(" in integration
    assert "IRNode.commaExpression(sequence)" in boundary


def test_calls_binary_constructors_and_generic_bodies_run_left_to_right(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int trace = 0;
        int mark(int expected) {
            assert(trace == expected);
            trace++;
            return expected;
        }
        int pair(int first, int second) {
            assert(first == 0 && second == 1);
            return first * 10 + second;
        }

        class Ordered {
            public int first;
            public int second;
            public Ordered(int first, int second) {
                self.first = first;
                self.second = second;
            }
            static int pair(int first, int second) {
                return first * 10 + second;
            }
        }

        class GenericRunner<T> {
            public int run() {
                int local = 0;
                int called = pair(local++, local++);
                int added = local++ + local++;
                return called * 100 + added;
            }
        }

        int main() {
            trace = 0;
            assert(pair(trace++, trace++) == 1);
            assert(trace == 2);

            trace = 0;
            assert(trace++ + trace++ == 1);
            assert(trace == 2);

            trace = 0;
            Ordered ordered = new Ordered(mark(0), mark(1));
            assert(ordered.first == 0 && ordered.second == 1);

            trace = 0;
            assert(Ordered.pair(mark(0), mark(1)) == 1);

            GenericRunner<int> runner = new GenericRunner<int>();
            assert(runner.run() == 105);
            return 0;
        }
    """
    for index, generated in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        emitted = generated.read_text()
        assert "__btrc_call_operand" in emitted or "__btrc_operand" in emitted
        strict_build_and_run(generated, tmp_path / f"sequencing-{index}")


def test_managed_receivers_survive_later_operands_and_unwind(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int alive = 0;
        class Item {
            public int id;
            public Item(int id) { self.id = id; alive++; }
            public void __del__() { alive--; }
            public int combine(int other) {
                assert(self.id == 1 || self.id == 3 || self.id == 5);
                return self.id * 10 + other;
            }
            public int ordered(int first, int second) {
                return self.id * 100 + first * 10 + second;
            }
            public int fail() { throw "boom"; }
            public Item __add__(Item other) {
                return new Item(self.id * 10 + other.id);
            }
            public bool __lt__(Item other) {
                return self.id < other.id;
            }
        }

        int trace = 0;
        int mark(int expected) {
            assert(trace == expected);
            trace++;
            return expected;
        }

        void exerciseCallReceiver() {
            Item value = new Item(1);
            Item rebound = new Item(2);
            assert(value.combine((value = rebound).id) == 12);
            assert(alive == 1);
        }

        void exerciseOperatorReceiver() {
            Item value = new Item(3);
            Item rebound = new Item(4);
            Item result = value + (value = rebound);
            assert(result.id == 34);
            assert(alive == 2);
        }

        void exerciseComparisonReceiver() {
            Item value = new Item(5);
            Item rebound = new Item(6);
            assert(value < (value = rebound));
            assert(alive == 1);
        }

        void exerciseOrderedAndOptional() {
            Item value = new Item(6);
            trace = 0;
            assert(value.ordered(mark(0), mark(1)) == 601);

            Item? optional = value;
            trace = 0;
            assert(optional?.ordered(mark(0), mark(1)) == 601);
            assert(trace == 2);
            optional = null;
            trace = 0;
            assert(optional?.ordered(mark(0), mark(1)) == 0);
            assert(trace == 0);
        }

        void exerciseUnwind() {
            Item value = new Item(1);
            Item rebound = new Item(7);
            try {
                value.combine((value = rebound).fail());
                assert(false);
            } catch (string error) {
                assert(error == "boom");
            }
            assert(alive == 1);
        }

        int main() {
            exerciseCallReceiver();
            assert(alive == 0);
            exerciseOperatorReceiver();
            assert(alive == 0);
            exerciseComparisonReceiver();
            assert(alive == 0);
            exerciseOrderedAndOptional();
            assert(alive == 0);
            exerciseUnwind();
            assert(alive == 0);
            return 0;
        }
    """
    for index, generated in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        emitted = generated.read_text()
        assert "__btrc_kept_operand" in emitted
        strict_build_and_run(generated, tmp_path / f"receiver-pin-{index}")


def test_borrowed_receiver_is_pinned_only_across_later_effects(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int alive = 0;
        class Counter {
            private Atomic<uint> value;
            public int id;

            public Counter(int id) {
                self.value.init((uint)id);
                self.id = id;
                alive++;
            }
            public uint read() {
                return self.value.load(MemoryOrder.RELAXED);
            }
            public uint combine(uint other) {
                assert(self.id == 1);
                return self.value.load(MemoryOrder.RELAXED) * 10u + other;
            }
            public void __del__() { alive--; }
        }

        uint readBorrowed(Counter counter) {
            return counter.read();
        }

        void exerciseEffectfulArgument() {
            Counter counter = new Counter(1);
            Counter replacement = new Counter(2);
            assert(counter.combine((counter = replacement).read()) == 12u);
            assert(alive == 1);
        }

        int main() {
            Counter counter = new Counter(7);
            assert(readBorrowed(counter) == 7u);
            delete counter;
            exerciseEffectfulArgument();
            assert(alive == 0);
            return 0;
        }
    """
    for index, generated in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        emitted = generated.read_text()
        direct = re.search(
            r"(?:static )?unsigned int readBorrowed\([^)]*\)\s*\{(?P<body>.*?)\n\}",
            emitted,
            re.DOTALL,
        )
        assert direct is not None
        assert "__btrc_kept_operand" not in direct.group("body")

        effectful = re.search(
            r"(?:static )?void exerciseEffectfulArgument\([^)]*\)\s*\{(?P<body>.*?)\n\}",
            emitted,
            re.DOTALL,
        )
        assert effectful is not None
        assert "__btrc_kept_operand" in effectful.group("body")
        strict_build_and_run(
            generated,
            tmp_path / f"receiver-pin-minimal-{index}",
            optimization="-O3",
        )


def test_owned_binary_result_handoff_agrees_with_and_without_unwinding(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    sanitizer = require_sanitizers(tmp_path)
    comparisons = {}
    for context in ("ordinary", "unwinding"):
        directory = tmp_path / context
        directory.mkdir()
        statement = 'assert(combined().equals("alphabetagamma"));'
        if context == "unwinding":
            statement = f"try {{ {statement} }} catch (string error) {{ print(error); return 1; }}"
        source = (
            """
            #include <assert.h>
            string combined() { return "alpha" + "beta" + "gamma"; }
            int main() {
        """
            + statement
            + "return 0; }"
        )
        generated_pair = _compile_both(semantic_btrcc, directory, source)
        for index, generated in enumerate(generated_pair):
            strict_build_and_run(generated, directory / f"strict-{index}", optimization="-O2")
            sanitized_build_and_run(generated, directory / f"sanitized-{index}", sanitizer)
        comparisons[context] = generated_pair[0].read_bytes() == generated_pair[1].read_bytes()
    assert comparisons == {"ordinary": True, "unwinding": True}


@pytest.mark.parametrize("generic", [False, True], ids=["ordinary", "generic"])
@pytest.mark.parametrize("kind", ["pointer", "callback", "managed"])
def test_staged_field_assignment_retains_declared_result_type(
    semantic_btrcc: Path, tmp_path: Path, kind: str, generic: bool
) -> None:
    sanitizer = require_sanitizers(tmp_path)
    declarations, result_check = {
        "pointer": (
            "typedef int* Value; int payload = 42; "
            "Value makeValue(int first, int second) { assert(first == 1 && second == 2); return &payload; }",
            "assert(*result == 42);",
        ),
        "callback": (
            "typedef CFunction<int, int> Value; int twice(int value) { return value * 2; } "
            "Value makeValue(int first, int second) { assert(first == 1 && second == 2); return twice; }",
            "assert(result(21) == 42);",
        ),
        "managed": (
            "class Base { public int payload; public Base() { self.payload = 42; } } "
            "typedef Base Value; "
            "Value makeValue(int first, int second) { assert(first == 1 && second == 2); return new Base(); }",
            "assert(result.payload == 42);",
        ),
    }[kind]
    source = """
        #include <assert.h>
        DECLARATIONS
        int trace = 0;
        int mark(int expected) { assert(trace == expected); trace++; return expected; }
        HOLDER_DECLARATION
        HOLDER_TYPE receiver(HOLDER_TYPE holder) { assert(trace == 0); trace++; return holder; }
        int main() {
            HOLDER_TYPE holder = new HOLDER_TYPE();
            Value result = (receiver(holder).value = makeValue(mark(1), mark(2)));
            assert(trace == 3);
            RESULT_CHECK
            return 0;
        }
    """.replace("DECLARATIONS", declarations).replace("RESULT_CHECK", result_check)
    source = source.replace(
        "HOLDER_DECLARATION",
        "class Holder<T> { public T value; }" if generic else "class Holder { public Value value; }",
    ).replace("HOLDER_TYPE", "Holder<Value>" if generic else "Holder")
    generated = _compile_both(semantic_btrcc, tmp_path, source)
    for index, path in enumerate(generated):
        strict_build_and_run(path, tmp_path / f"assignment-alias-{index}")
        sanitized_build_and_run(path, tmp_path / f"assignment-alias-sanitized-{index}", sanitizer)
    assert generated[0].read_text() == generated[1].read_text()


@pytest.mark.parametrize(
    ("declaration", "inheritance", "field"),
    [
        ("class Value { public int number; public int read() { return self.number; } }", "extends", ""),
        ("interface Value { int read(); }", "implements", "public int number;"),
    ],
    ids=["class", "interface"],
)
@pytest.mark.parametrize("ownership", ["borrowed", "owned"])
def test_prepared_call_upcasts_retain_effective_type(
    semantic_btrcc, tmp_path, declaration, inheritance, field, ownership
):
    source = (
        """
        int liveValues = 0;
        int trace = 0;
        TARGET
        class Concrete INHERITANCE Value {
            FIELD
            public Concrete(int number) { self.number = number; liveValues++; }
            public void __del__() { liveValues--; }
            public int read() { return self.number; }
        }
        Concrete makeValue() { assert(trace == 0); trace++; return Concrete(7); }
        int mark(bool fail) {
            assert(trace == PREFIX);
            trace++;
            if (fail) { throw "sibling"; }
            return 9;
        }
        int consume(Value value, int second) {
            assert(trace == PREFIX + 1);
            assert(value.read() == 7 && liveValues == 1);
            return second;
        }
        int main() {
            for (int iteration = 0; iteration < 5; iteration++) {
                {
                    SETUP
                    trace = 0;
                    assert(consume(ARGUMENT, mark(false)) == 9);
                    assert(liveValues == REMAINING);
                    trace = 0;
                    bool caught = false;
                    try { consume(ARGUMENT, mark(true)); }
                    catch (string error) { caught = error == "sibling"; }
                    assert(caught && liveValues == REMAINING);
                }
                assert(liveValues == 0);
            }
            return 0;
        }
    """.replace("TARGET", declaration)
        .replace("INHERITANCE", inheritance)
        .replace("FIELD", field)
    )
    source = source.replace("SETUP", "var existing = Concrete(7);" if ownership == "borrowed" else "")
    source = source.replace("ARGUMENT", "existing" if ownership == "borrowed" else "makeValue()")
    source = source.replace("PREFIX", "0" if ownership == "borrowed" else "1")
    source = source.replace("REMAINING", "1" if ownership == "borrowed" else "0")
    selfhost, selfhost_c = compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = compile_ownership_reference(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    sanitizer = require_sanitizers(tmp_path)
    for frontend, generated in [("selfhost", selfhost_c), ("reference", reference_c)]:
        strict_build_and_run(generated, tmp_path / frontend, optimization="-O2")
        sanitized_build_and_run(generated, tmp_path / f"{frontend}-sanitized", sanitizer)
    assert selfhost_c.read_bytes() == reference_c.read_bytes()


@pytest.mark.parametrize(("operator", "initial"), [("++", 41), ("--", 43)])
@pytest.mark.parametrize("prefix", [False, True], ids=["postfix", "prefix"])
def test_nested_field_unary_update_matches_frontends(semantic_btrcc, tmp_path, operator, initial, prefix):
    update = f"{operator}self.state.value" if prefix else f"self.state.value{operator}"
    source = (
        """
        class State {
            public long long value;
            public State(long long value) { self.value = value; }
        }
        class Counter {
            private State state;
            public Counter(long long value) { self.state = new State(value); }
            public long long read() { return self.state.value; }
            public long long advance() {
                if (self.state.value == 0) { throw "zero"; }
                return UPDATE;
            }
        }
        int main() {
            for (int iteration = 0; iteration < 20; iteration++) {
                var counter = new Counter(INITIAL);
                assert(counter.advance() == RESULT);
                assert(counter.read() == 42);
                var blocked = new Counter(0);
                bool caught = false;
                try { blocked.advance(); }
                catch (string error) { caught = error == "zero"; }
                assert(caught && blocked.read() == 0);
            }
            return 0;
        }
    """.replace("UPDATE", update)
        .replace("INITIAL", str(initial))
        .replace("RESULT", str(42 if prefix else initial))
    )
    generated = _compile_both(semantic_btrcc, tmp_path, source)
    sanitizer = require_sanitizers(tmp_path)
    for index, path in enumerate(generated):
        strict_build_and_run(path, tmp_path / f"nested-update-{index}", optimization="-O2")
        sanitized_build_and_run(path, tmp_path / f"nested-update-sanitized-{index}", sanitizer)
    assert generated[0].read_bytes() == generated[1].read_bytes()


@pytest.mark.parametrize(("operator", "initial"), [("++", 41), ("--", 43)])
@pytest.mark.parametrize("prefix", [False, True], ids=["postfix", "prefix"])
def test_unary_update_preserves_receivers_and_index_effects(semantic_btrcc, tmp_path, operator, initial, prefix):
    source = """
        int liveStates = 0;
        int factoryCalls = 0;
        int indexCalls = 0;
        int getters = 0;
        int setters = 0;
        int lastDropped = 0;
        class State {
            public int value;
            public int property { get; set; }
            public State(int value) {
                self.value = value;
                self.property = value;
                liveStates++;
            }
            public void __del__() { lastDropped = self.value; liveStates--; }
            public int get(int index) {
                assert(index == 0);
                getters++;
                return self.value;
            }
            public void set(int index, int value) {
                assert(index == 0);
                setters++;
                self.value = value;
            }
            public int index(bool fail) {
                indexCalls++;
                if (fail) { throw "index"; }
                return 0;
            }
        }
        State makeState() { factoryCalls++; return new State(INITIAL); }
        void exercise() {
            factoryCalls = 0;
            assert(TEMPORARY_UPDATE == RESULT);
            assert(factoryCalls == 1 && liveStates == 0 && lastDropped == 42);

            var propertyOwner = new State(INITIAL);
            assert(PROPERTY_UPDATE == RESULT);
            assert(propertyOwner.property == 42);

            var indexed = new State(INITIAL);
            getters = 0;
            setters = 0;
            indexCalls = 0;
            assert(INDEXED_UPDATE == RESULT);
            assert(indexed.value == 80 && lastDropped == 42);
            assert(getters == 1 && setters == 1 && indexCalls == 1);
            assert(liveStates == 2);

            var throwing = new State(INITIAL);
            bool caught = false;
            getters = 0;
            setters = 0;
            indexCalls = 0;
            try { THROWING_UPDATE; }
            catch (string error) { caught = error == "index"; }
            assert(caught && throwing.value == 80 && lastDropped == INITIAL);
            assert(getters == 0 && setters == 0 && indexCalls == 1);
            assert(liveStates == 3);

            caught = false;
            factoryCalls = 0;
            try { TEMPORARY_THROWING_UPDATE; }
            catch (string error) { caught = error == "index"; }
            assert(caught && factoryCalls == 1 && liveStates == 3);
        }
        int main() {
            for (int iteration = 0; iteration < 20; iteration++) {
                exercise();
                assert(liveStates == 0);
            }
            return 0;
        }
    """
    targets = {
        "TEMPORARY_UPDATE": "makeState().value",
        "PROPERTY_UPDATE": "propertyOwner.property",
        "INDEXED_UPDATE": "indexed[(indexed = new State(80)).index(false)]",
        "THROWING_UPDATE": "throwing[(throwing = new State(80)).index(true)]",
        "TEMPORARY_THROWING_UPDATE": "makeState()[propertyOwner.index(true)]",
    }
    for name, target in sorted(targets.items(), key=lambda pair: -len(pair[0])):
        source = source.replace(name, f"{operator}{target}" if prefix else f"{target}{operator}")
    source = source.replace("INITIAL", str(initial)).replace("RESULT", str(42 if prefix else initial))
    generated = _compile_both(semantic_btrcc, tmp_path, source)
    sanitizer = require_sanitizers(tmp_path)
    for index, path in enumerate(generated):
        strict_build_and_run(path, tmp_path / f"receiver-update-{index}", optimization="-O2")
        sanitized_build_and_run(path, tmp_path / f"receiver-update-sanitized-{index}", sanitizer)


@pytest.mark.parametrize(("operator", "initial"), [("++", 41), ("--", 43)])
@pytest.mark.parametrize("prefix", [False, True], ids=["postfix", "prefix"])
def test_unary_update_preserves_projected_receivers(semantic_btrcc, tmp_path, operator, initial, prefix):
    source = """
        int liveStates = 0;
        int liveHolders = 0;
        int getters = 0;
        int setters = 0;
        int failure = 0;
        int lastDropped = 0;
        class State {
            public int value;
            public State() { self.value = INITIAL; liveStates++; }
            public void __del__() { liveStates--; lastDropped = self.value; }
            public int property {
                get {
                    getters++;
                    if (failure == 1) { throw "getter"; }
                    return self.value;
                }
                set {
                    setters++;
                    if (failure == 2) { throw "setter"; }
                    self.value = value;
                }
            }
        }
        class Holder {
            public State state;
            public Holder() { self.state = new State(); liveHolders++; }
            public void __del__() { liveHolders--; }
        }
        Holder makeHolder() { return new Holder(); }
        int main() {
            for (int iteration = 0; iteration < 20; iteration++) {
                assert(FIELD_UPDATE == RESULT);
                assert(liveHolders == 0 && liveStates == 0 && lastDropped == 42);
                getters = 0;
                setters = 0;
                assert(PROPERTY_UPDATE == RESULT);
                assert(liveHolders == 0 && liveStates == 0 && lastDropped == 42);
                assert(getters == 1 && setters == 1);
                for (int stage = 1; stage <= 2; stage++) {
                    bool caught = false;
                    failure = stage;
                    getters = 0;
                    setters = 0;
                    try { PROPERTY_UPDATE; }
                    catch (string error) { caught = error == (stage == 1 ? "getter" : "setter"); }
                    failure = 0;
                    assert(caught && liveHolders == 0 && liveStates == 0 && lastDropped == INITIAL);
                    assert(getters == 1 && setters == stage - 1);
                }
            }
            return 0;
        }
    """
    for name, target in {
        "FIELD_UPDATE": "makeHolder().state.value",
        "PROPERTY_UPDATE": "makeHolder().state.property",
    }.items():
        source = source.replace(name, f"{operator}{target}" if prefix else f"{target}{operator}")
    source = source.replace("INITIAL", str(initial)).replace("RESULT", str(42 if prefix else initial))
    generated = _compile_both(semantic_btrcc, tmp_path, source)
    sanitizer = require_sanitizers(tmp_path)
    for index, path in enumerate(generated):
        strict_build_and_run(path, tmp_path / f"projected-update-{index}", optimization="-O2")
        sanitized_build_and_run(path, tmp_path / f"projected-update-sanitized-{index}", sanitizer)
