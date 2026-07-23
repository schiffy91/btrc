"""Strict runtime contracts for assignable-expression lowering."""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

RUNTIME_SOURCE = r"""
#include <assert.h>

int receiver_calls = 0;
int index_calls = 0;
int rhs_calls = 0;
int getter_calls = 0;
int setter_calls = 0;
int add_calls = 0;
int string_rhs_calls = 0;
int divisor_calls = 0;
int raw_values[3];

int* raw_receiver() { receiver_calls++; return &raw_values[0]; }
int index_probe() { index_calls++; return 1; }
int rhs_probe() { rhs_calls++; return 4; }
string string_rhs() { string_rhs_calls++; return "b"; }
int divisor_probe() { divisor_calls++; return 2; }

class Vector<T> {
    public T* data;
    public int len;
    public int cap;
    public Vector() {
        self.len = 0;
        self.cap = 16;
        self.data = (T*)calloc(16, sizeof(T));
    }
    public T get(int index) { return self.data[index]; }
    public void set(int index, T value) { self.data[index] = value; }
    public void push(T value) { self.data[self.len] = value; self.len++; }
}

class Gauge {
    private int stored;
    public Gauge(int initial) { self.stored = initial; }
    public int value {
        get { getter_calls++; return self.stored; }
        set { setter_calls++; self.stored = value; }
    }
}

class Counter {
    public int value;
    public Counter(int value) { self.value = value; }
    public Counter __add__(Counter other) {
        add_calls++;
        return Counter(self.value + other.value);
    }
}

class Holder {
    private Vector<int> stored;
    public Holder(Vector<int> stored) { self.stored = stored; }
    public Vector<int> items {
        get { return self.stored; }
        set { self.stored = value; }
    }
}

class Slots<T> {
    private T stored;
    public Slots(T initial) { self.stored = initial; }
    public T get(int index) { (void)index; return self.stored; }
    public void set(int index, T value) { (void)index; self.stored = value; }
}

class Worker<T> {
    public T update(Vector<T> values, int index, T delta) {
        return values[index] += delta;
    }
    public int updateGauge(Gauge target, int delta) {
        return target.value += delta;
    }
    public void reset(Holder target) { target.items = []; }
    public void resetAt(Slots<Vector<int>> rows, int index) {
        rows[index] = [];
    }
}

Gauge gauge;
Vector<int> vector;
Gauge gauge_probe() { receiver_calls++; return gauge; }
Vector<int> vector_probe() { receiver_calls++; return vector; }
Counter counter_rhs() { rhs_calls++; return Counter(2); }

int main() {
    raw_values[1] = 10;
    raw_receiver()[index_probe()] += rhs_probe();
    assert(raw_values[1] == 14);
    assert(receiver_calls == 1 && index_calls == 1 && rhs_calls == 1);
    receiver_calls = 0; index_calls = 0;
    int raw_old = raw_receiver()[index_probe()]++;
    int raw_new = ++raw_receiver()[index_probe()];
    assert(raw_old == 14 && raw_new == 16);
    assert(receiver_calls == 2 && index_calls == 2);

    gauge = new Gauge(10);
    receiver_calls = 0; rhs_calls = 0;
    int property_result = gauge_probe().value += rhs_probe();
    assert(property_result == 14 && gauge.value == 14);
    assert(receiver_calls == 1 && rhs_calls == 1);
    assert(getter_calls == 2 && setter_calls == 1);
    getter_calls = 0; setter_calls = 0; receiver_calls = 0;
    int property_old = gauge_probe().value++;
    int property_new = ++gauge_probe().value;
    assert(property_old == 14 && property_new == 16 && gauge.value == 16);
    assert(receiver_calls == 2 && getter_calls == 3 && setter_calls == 2);

    vector = [10, 20];
    receiver_calls = 0; index_calls = 0; rhs_calls = 0;
    int vector_result = vector_probe()[index_probe()] += rhs_probe();
    assert(vector_result == 24 && vector[1] == 24);
    assert(receiver_calls == 1 && index_calls == 1 && rhs_calls == 1);
    receiver_calls = 0; index_calls = 0;
    int vector_old = vector_probe()[index_probe()]++;
    int vector_new = ++vector_probe()[index_probe()];
    assert(vector_old == 24 && vector_new == 26 && vector[1] == 26);
    assert(receiver_calls == 2 && index_calls == 2);

    volatile int scalar = 1;
    scalar += 2;
    volatile string text = "a";
    text += string_rhs();
    assert(scalar == 3 && text == "ab" && string_rhs_calls == 1);

    Counter counter = Counter(40);
    rhs_calls = 0;
    counter += counter_rhs();
    assert(counter.value == 42 && rhs_calls == 1 && add_calls == 1);

    long long wide = 8589934592LL;
    wide /= divisor_probe();
    wide %= 3LL;
    assert(wide == 1LL && divisor_calls == 1);

    Worker<int> worker = new Worker<int>();
    assert(worker.update(vector, 1, 4) == 30 && vector[1] == 30);
    getter_calls = 0; setter_calls = 0;
    assert(worker.updateGauge(gauge, 4) == 20);
    assert(getter_calls == 1 && setter_calls == 1 && gauge.value == 20);

    Holder holder = new Holder([1, 2]);
    worker.reset(holder);
    assert(holder.items.len == 0);
    Vector<int> row = [7];
    Slots<Vector<int>> rows = new Slots<Vector<int>>(row);
    worker.resetAt(rows, 0);
    assert(rows[0].len == 0);
    return 0;
}
"""


def _analyze(source: str):
    program = Parser(Lexer(source, "<lvalue-update>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


@functools.lru_cache(maxsize=1)
def _emit_runtime() -> str:
    analyzed = _analyze(RUNTIME_SOURCE)
    assert not analyzed.errors
    return CEmitter().emit(IROptimizer(IRLowerer(analyzed).lower()).optimize())


def test_lvalue_runtime_uses_correct_volatile_declarators():
    generated = _emit_runtime()
    main = generated[generated.index("int main(void) {") :]
    assert re.search(r"volatile int\*\s+[A-Za-z_]\w*;", main)
    assert "char* volatile text" in generated
    assert re.search(r"int\* volatile\*\s+[A-Za-z_]\w*;", generated)
    assert "__btrc_div" in generated and "__btrc_mod" in generated


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_lvalue_runtime_is_strict_c11(tmp_path: Path, c_compiler: str):
    c_path = tmp_path / "lvalue_updates.c"
    binary = tmp_path / "lvalue_updates"
    c_path.write_text(_emit_runtime())
    subprocess.run(
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
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    subprocess.run([str(binary)], check=True, timeout=10)


def test_update_analyzer_reports_accessors_optional_target_and_zero():
    analyzed = _analyze("""
        class Accessors {
            public int readOnly { get; }
            public int writeOnly { set; }
        }
        class Vector<T> {
            private T value;
            public T get(int index) { return self.value; }
        }
        class Array<T> {
            public void set(int index, T value) {}
        }
        void run(Accessors value, Vector<int> reads,
                 Array<int> writes, Accessors? optional) {
            value.readOnly++;
            ++value.writeOnly;
            reads[0]++;
            ++writes[0];
            optional?.readOnly += 1;
            int number = 1;
            number /= 0;
            number %= 0;
        }
    """)
    messages = "\n".join(analyzed.errors).lower()
    assert "property 'readonly' has no setter" in messages
    assert "property 'writeonly' has no getter" in messages
    assert "has no indexed setter" in messages
    assert "has no indexed getter" in messages
    assert "optional-chain expression is not assignable" in messages
    assert messages.count("division by zero") >= 2


def test_nested_pointer_generic_storage_remains_raw_indexing():
    generated = emit_c("""
        class Vector<T> {
            private T* items;
            public T get(int i) { return self.items[i]; }
            public void set(int i, T value) { self.items[i] = value; }
        }
        class Slots<T> {
            private T* values;
            public Slots(T* values) { self.values = values; }
            public T read(int i) { return self.values[i]; }
            public void write(int i, T value) { self.values[i] = value; }
        }
        int main() {
            Slots<Vector<int>> slots = new Slots<Vector<int>>(null);
            Vector<int> item = slots.read(0);
            slots.write(0, item);
            return 0;
        }
    """)
    # Nested pointer storage is raw C storage, not an indexed-protocol call.
    assert len(re.findall(r"\bself->values\s*\[\s*i\s*\]", generated)) >= 2
    assert "_get(self->values" not in generated
    assert "_set(self->values" not in generated
