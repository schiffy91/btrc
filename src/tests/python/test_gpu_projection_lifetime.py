"""GPU argument lifetime contracts for fixed-array owner projections."""

import re
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c
from src.tests.python.test_gpu_dispatch_failures import COMPILERS, _compile_with_gpu_stubs

BORROWED_SOURCE = r"""
#include <assert.h>

int drops = 0;
int effects = 0;

class Owner {
    public int values[1];
    public Owner(int value) { self.values[0] = value; }
    public void __del__() { drops++; }
}

class Holder {
    public Owner owner;
    public Holder() { self.owner = new Owner(7); }
    public int replace() {
        effects++;
        self.owner = new Owner(9);
        return 0;
    }
    public int run() {
        int[] result = copy(self.owner.values, self.replace());
        return result[0];
    }
}

@gpu int[] copy(int[] values, int ignored) {
    int i = gpu_id();
    return values[i];
}

int main() {
    Holder holder = new Holder();
    assert(holder.run() == 7);
    assert(effects == 1);
    assert(drops == 1);
    delete holder;
    assert(drops == 2);
    return 0;
}
"""

OWNED_SOURCE = r"""
#include <assert.h>

int drops = 0;
int makes = 0;
int effects = 0;

class Owner {
    public int values[1];
    public Owner(int value) { self.values[0] = value; }
    public void __del__() { drops++; }
}

Owner makeOwner() {
    makes++;
    return new Owner(7);
}

int laterEffect() {
    effects++;
    return 0;
}

@gpu int[] copy(int[] values, int ignored) {
    int i = gpu_id();
    return values[i];
}

int main() {
    int[] result = copy(makeOwner().values, laterEffect());
    assert(result[0] == 7);
    assert(makes == 1);
    assert(effects == 1);
    assert(drops == 1);
    return 0;
}
"""

EXCEPTION_SOURCE = r"""
#include <assert.h>

int drops = 0;
int makes = 0;
int effects = 0;

class Owner {
    public int values[1];
    public Owner(int value) { self.values[0] = value; }
    public void __del__() { drops++; }
}

Owner makeOwner() {
    makes++;
    return new Owner(7);
}

int explode() {
    effects++;
    throw "stop";
}

@gpu int[] copy(int[] values, int ignored) {
    int i = gpu_id();
    return values[i];
}

int main() {
    try {
        int[] result = copy(makeOwner().values, explode());
        return result[0] + 1;
    } catch (string error) {
        assert(error == "stop");
    }
    assert(makes == 1);
    assert(effects == 1);
    assert(drops == 1);
    return 0;
}
"""

CALLABLE_FLOW_SOURCE = r"""
#include <assert.h>

int drops = 0;

class Owner {
    public int values[1];
    public Owner(int value) { self.values[0] = value; }
    public void __del__() { drops++; }
}

Owner makeOwner() { return new Owner(7); }

@gpu int[] copy(bool ignored, int[] values) {
    int i = gpu_id();
    return values[i] + (ignored ? 0 : 0);
}

int main() {
    __fn_ptr<Owner> callback = (__fn_ptr<Owner>)null;
    int[] result = copy(
        (callback = makeOwner) != null,
        callback().values
    );
    assert(result[0] == 7);
    assert(drops == 1);
    return 0;
}
"""

CALLABLE_HEAP_SOURCE = r"""
#include <assert.h>

int raw[1] = {7};
int drops = 0;

class Vector<T> {
    public T* data;
    public int len;
    public Vector(T* data, int len) { self.data = data; self.len = len; }
    public void __del__() { drops++; }
}

Vector<int> makeVector() { return new Vector<int>(raw, 1); }

@gpu void touch(int[] values, bool ignored) {
    int i = gpu_id();
    values[i] += ignored ? 0 : 0;
}

int run() {
    __fn_ptr<Vector<int>> callback = makeVector;
    touch(
        callback(),
        (callback = (__fn_ptr<Vector<int>>)null) != null
    );
    return drops;
}

int main() {
    assert(run() == 1);
    return 0;
}
"""


def _function_body(generated: str, signature: str) -> str:
    start = generated.index(signature)
    depth = 0
    for index in range(generated.index("{", start), len(generated)):
        if generated[index] == "{":
            depth += 1
        elif generated[index] == "}":
            depth -= 1
            if depth == 0:
                return generated[start : index + 1]
    raise AssertionError(f"unterminated generated function: {signature}")


def test_borrowed_gpu_projection_pins_and_snapshots_before_later_effect() -> None:
    body = _function_body(emit_c(BORROWED_SOURCE), "int Holder_run(Holder* self) {")
    root_match = re.search(r"Owner\* (__btrc_call_operand_\d+);", body)
    kept_match = re.search(r"Owner\* (__btrc_kept_operand_\d+);", body)
    assert root_match is not None and kept_match is not None
    root = root_match.group(1)
    kept = kept_match.group(1)

    root_assignment = body.index(f"{root} = self->owner")
    retain = body.index(f"__btrc_arc_retain({root})", root_assignment)
    projection = body.index(f"{root}->values", retain)
    capacity = body.index(f"sizeof({root}->values)", projection)
    later_effect = body.index("Holder_replace(self)", capacity)
    dispatch = body.index("__gpu_dispatch_", later_effect)
    clear = body.index(f"{kept} = NULL", dispatch)
    release = body.index("__btrc_arc_release", clear)

    assert body.count("self->owner") == 1
    assert body.count("Holder_replace(self)") == 1
    assert root_assignment < retain < projection < capacity < later_effect < dispatch < clear < release


def test_owned_gpu_projection_is_evaluated_once_and_released_after_dispatch() -> None:
    body = _function_body(emit_c(OWNED_SOURCE), "int main(void) {")
    root_match = re.search(r"Owner\* (__btrc_call_operand_\d+);", body)
    assert root_match is not None
    root = root_match.group(1)

    make = body.index(f"{root} = makeOwner()")
    projection = body.index(f"{root}->values", make)
    capacity = body.index(f"sizeof({root}->values)", projection)
    later_effect = body.index("laterEffect()", capacity)
    dispatch = body.index("__gpu_dispatch_", later_effect)
    clear = body.index(f"{root} = NULL", dispatch)
    release = body.index("__btrc_arc_release", clear)

    assert body.count("makeOwner()") == 1
    assert body.count("laterEffect()") == 1
    assert f"__btrc_arc_retain({root})" not in body
    assert make < projection < capacity < later_effect < dispatch < clear < release


def test_owned_gpu_projection_is_registered_for_exception_cleanup() -> None:
    body = _function_body(emit_c(EXCEPTION_SOURCE), "int main(void) {")
    root_match = re.search(r"Owner\* volatile (__btrc_call_operand_\d+);", body)
    assert root_match is not None
    root = root_match.group(1)

    make = body.index(f"{root} = makeOwner()")
    registration = body.index("__btrc_register_cleanup", make)
    projection = body.index(f"{root}->values", registration)
    capacity = body.index(f"sizeof({root}->values)", projection)
    later_effect = body.index("explode()", capacity)
    dispatch = body.index("__gpu_dispatch_", later_effect)
    clear = body.index(f"{root} = NULL", dispatch)
    release = body.index("__btrc_arc_release", clear)

    assert body.count("makeOwner()") == 1
    assert body.count("explode()") == 1
    assert make < registration < projection < capacity < later_effect < dispatch < clear < release


def test_gpu_projection_ownership_uses_source_ordered_callable_flow() -> None:
    body = _function_body(emit_c(CALLABLE_FLOW_SOURCE), "int main(void) {")
    root_match = re.search(r"Owner\* (__btrc_call_operand_\d+);", body)
    assert root_match is not None
    root = root_match.group(1)

    rebind = body.index("callback = makeOwner")
    call = body.index(f"{root} = callback()", rebind)
    projection = body.index(f"{root}->values", call)
    dispatch = body.index("__gpu_dispatch_", projection)
    release = body.index("__btrc_arc_release", dispatch)

    assert f"__btrc_arc_retain({root})" not in body
    assert rebind < call < projection < dispatch < release


def test_gpu_heap_argument_keeps_pre_lowering_source_ownership_fact() -> None:
    body = _function_body(emit_c(CALLABLE_HEAP_SOURCE), "int run(void) {")
    argument_match = re.search(r"btrc_Vector_int\* (__gpu_arg_\d+);", body)
    assert argument_match is not None
    argument = argument_match.group(1)

    call = body.index(f"{argument} = callback()")
    rebind = body.index("callback = ", call)
    dispatch = body.index("__gpu_dispatch_", rebind)
    release = body.index("__btrc_arc_release", dispatch)

    assert f"__btrc_arc_retain({argument})" not in body
    assert call < rebind < dispatch < release


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    "source",
    (BORROWED_SOURCE, OWNED_SOURCE, EXCEPTION_SOURCE, CALLABLE_FLOW_SOURCE, CALLABLE_HEAP_SOURCE),
    ids=("borrowed", "owned", "exception", "callable-flow", "callable-heap"),
)
def test_gpu_projection_lifetimes_hold_under_strict_c11(
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
