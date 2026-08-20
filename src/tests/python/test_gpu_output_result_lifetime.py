"""Typed result contracts for direct GPU output assignments."""

import re
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c
from src.tests.python.test_gpu_dispatch_failures import COMPILERS, _compile_with_gpu_stubs

OWNED_PROPERTY_SOURCE = r"""
#include <assert.h>

int drops = 0;
int getterCalls = 0;
int raw[1] = {0};

class Vector<T> {
    public T* data;
    public int len;
    public Vector(T* data, int len) { self.data = data; self.len = len; }
    public void __del__() { drops++; }
}

class Holder {
    public Vector<int> output {
        get {
            getterCalls++;
            return new Vector<int>(raw, 1);
        }
    }
}

@gpu int[] copy(int[] input) {
    int i = gpu_id();
    return input[i];
}

int main() {
    int[] input = {7};
    Holder holder = new Holder();
    holder.output = copy(input);
    assert(raw[0] == 7);
    assert(getterCalls == 1);
    assert(drops == 1);
    delete holder;
    return 0;
}
"""

BORROWED_FIELD_SOURCE = r"""
#include <assert.h>

int drops = 0;
int raw[1] = {0};

class Vector<T> {
    public T* data;
    public int len;
    public Vector(T* data, int len) { self.data = data; self.len = len; }
    public void __del__() { drops++; }
}

class Holder {
    public Vector<int> output;
    public Holder() { self.output = new Vector<int>(raw, 1); }
}

@gpu int[] copy(int[] input) {
    int i = gpu_id();
    return input[i];
}

int main() {
    int[] input = {7};
    Holder holder = new Holder();
    holder.output = copy(input);
    assert(raw[0] == 7);
    assert(drops == 0);
    delete holder;
    assert(drops == 1);
    return 0;
}
"""

FIXED_ARRAY_SOURCE = r"""
#include <assert.h>

@gpu int[] copy(int[] input) {
    int i = gpu_id();
    return input[i];
}

int main() {
    int[] input = {7};
    int output[1] = {0};
    output = copy(input);
    assert(output[0] == 7);
    return 0;
}
"""

OWNED_FIXED_ARRAY_EXCEPTION_SOURCE = r"""
#include <assert.h>

int drops = 0;

class Holder {
    public int values[1];
    public Holder() { self.values[0] = 0; }
    public void __del__() { drops++; }
}

Holder makeHolder() { return new Holder(); }
int explode() { throw "stop"; }

@gpu int[] copy(int[] input, int ignored) {
    int i = gpu_id();
    return input[i] + ignored * 0;
}

int main() {
    int[] input = {7};
    try {
        makeHolder().values = copy(input, explode());
        return 1;
    } catch (string error) {
        assert(error == "stop");
    }
    assert(drops == 1);
    return 0;
}
"""


def _main_body(source: str) -> str:
    generated = emit_c(source)
    start = generated.index("int main(void) {")
    return generated[start:]


def test_owned_property_output_hands_result_to_the_existing_discard_boundary() -> None:
    body = _main_body(OWNED_PROPERTY_SOURCE)
    target_match = re.search(r"btrc_Vector_int\* (__gpu_output_target_\d+);", body)
    result_match = re.search(r"btrc_Vector_int\* (__gpu_output_result_\d+);", body)
    discarded_match = re.search(r"btrc_Vector_int\* (__btrc_discarded_\d+) =", body)
    assert target_match is not None and result_match is not None and discarded_match is not None
    target = target_match.group(1)
    result = result_match.group(1)
    discarded = discarded_match.group(1)

    getter = body.index("Holder_get_output(")
    data = body.index(f"{target}->data", getter)
    dispatch = body.index("__gpu_dispatch_", data)
    handoff = body.index(f"{result} = {target}", dispatch)
    clear = body.index(f"{target} = NULL", handoff)
    yielded = body.index(f"{result});", clear)
    release = body.index(f"__btrc_arc_release_acyclic({discarded}", yielded)

    assert body.count("Holder_get_output(") == 1
    assert dispatch < handoff < clear < yielded < release


def test_borrowed_field_output_returns_the_retained_assignment_result_once() -> None:
    body = _main_body(BORROWED_FIELD_SOURCE)
    target_match = re.search(r"btrc_Vector_int\* (__gpu_output_target_\d+);", body)
    result_match = re.search(r"btrc_Vector_int\* (__gpu_output_result_\d+);", body)
    discarded_match = re.search(r"btrc_Vector_int\* (__btrc_discarded_\d+) =", body)
    assert target_match is not None and result_match is not None and discarded_match is not None
    target = target_match.group(1)
    result = result_match.group(1)
    discarded = discarded_match.group(1)

    assignment = body.index(f"{target} = holder->output")
    retain = body.index(f"__btrc_arc_retain({target})", assignment)
    dispatch = body.index("__gpu_dispatch_", retain)
    handoff = body.index(f"{result} = {target}", dispatch)
    clear = body.index(f"{target} = NULL", handoff)
    yielded = body.index(f"{result});", clear)
    release = body.index(f"__btrc_arc_release_acyclic({discarded}", yielded)

    assert body.count("holder->output") == 1
    assert assignment < retain < dispatch < handoff < clear < yielded < release


def test_fixed_array_output_assignment_ends_in_its_typed_target() -> None:
    body = _main_body(FIXED_ARRAY_SOURCE)
    dispatch = body.index("__gpu_dispatch_")
    yielded = body.index("output));", dispatch)
    assertion = body.index("output[0]", yielded)
    assert dispatch < yielded < assertion
    assert "__btrc_discarded" not in body


def test_owned_fixed_array_output_receiver_is_cleanup_protected_before_throwing_rhs() -> None:
    body = _main_body(OWNED_FIXED_ARRAY_EXCEPTION_SOURCE)
    producer = re.search(r"\(([A-Za-z_][A-Za-z0-9_]*) = makeHolder\(\)\)", body)
    assert producer is not None
    receiver = producer.group(1)
    registration = body.index("__btrc_register_cleanup", producer.start())
    projection = body.index(f"{receiver}->values", registration)
    throwing_rhs = body.index("explode()", projection)
    dispatch = body.index("_run(", throwing_rhs)
    clear = body.index(f"{receiver} = NULL", dispatch)
    release = body.index("__btrc_arc_release", clear)

    assert body.count("makeHolder()") == 1
    assert body.count("explode()") == 1
    assert producer.start() < registration < projection < throwing_rhs < dispatch < clear < release


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    "source",
    (OWNED_PROPERTY_SOURCE, BORROWED_FIELD_SOURCE, FIXED_ARRAY_SOURCE, OWNED_FIXED_ARRAY_EXCEPTION_SOURCE),
    ids=("owned-property", "borrowed-field", "fixed-array", "owned-fixed-array-exception"),
)
def test_gpu_output_assignment_results_hold_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
    source: str,
) -> None:
    executable = _compile_with_gpu_stubs(
        tmp_path,
        source,
        available=False,
        fail_second_buffer=False,
        compiler=c_compiler,
    )
    executed = subprocess.run([executable], capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr
