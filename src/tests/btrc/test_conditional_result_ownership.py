"""Conditional expressions consume normalized call results exactly once."""

from pathlib import Path

import pytest

from src.tests.btrc.allocation_tracking_harness import tracked_strict_matrix
from src.tests.btrc.dual_frontend_harness import compile_snippet_pair
from src.tests.btrc.selfhost_snippet_harness import compile_reference_source, compile_source


def _conditional_source(kind: str, guarded: bool, generic: bool, *, form: str = "ternary") -> str:
    managed = kind == "class"
    field_type = "Item" if managed else "string"
    initializer = "new Item()" if managed else 'f"value={42}"'
    read = 'f"value={42}"' if kind == "owned-string" else "self.value"
    value_type = "Item?" if managed else "string"
    alternate = "null" if managed else '""'
    check = "chosen ? value != null : value == null" if managed else 'value == (chosen ? "value=42" : "")'
    leave = 'if (fail) { throw "leave"; }' if guarded else "(void)fail;"
    invoke = (
        'bool caught = false; try { exercise(chosen, fail); } catch (string error) { caught = true; assert(error == "leave"); } assert(caught == fail);'
        if guarded
        else "exercise(chosen, fail);"
    )
    receiver = "self.owner" if generic else "owner"
    selected = f"chosen ? {receiver}.same().read() : {alternate}"
    expected_reads = "(chosen ? 1 : 0)"
    nullable_method = ""
    prelude = ""
    if form == "coalesce":
        selected = f"{receiver}.same().maybe(chosen) ?? {receiver}.same().read()"
        expected_reads = "1"
        check = "value != null" if managed else 'value == "value=42"'
        nullable_method = (
            f"public {field_type}? maybe(bool chosen) {{ if (chosen) {{ return self.read(); }} return null; }}"
        )
    elif form == "both_calls":
        selected = f"chosen ? {receiver}.same().read() : {receiver}.same().read()"
        expected_reads = "1"
        check = "value != null" if managed else 'value == "value=42"'
    elif form == "cast_call":
        selected = f"chosen ? ({value_type}){receiver}.same().read() : {alternate}"
    elif form == "cast_borrowed":
        prelude = f"{field_type} borrowed = {receiver}.same().read();"
        selected = f"chosen ? ({value_type})borrowed : {alternate}"
        expected_reads = "1"
    body = f"""
        int before = reads;
        {prelude}
        {value_type} value = {selected};
        assert({check});
        assert(reads == before + {expected_reads});
        {leave}
    """
    exercise = (
        f"""
        class Choice<T> {{
            private T owner;
            public Choice(T owner) {{ self.owner = owner; }}
            public void choose(bool chosen, bool fail) {{ {body} }}
        }}
        void exercise(bool chosen, bool fail) {{
            Holder owner = new Holder();
            Choice<Holder> choice = new Choice<Holder>(owner);
            choice.choose(chosen, fail);
        }}
        """
        if generic
        else f"void exercise(bool chosen, bool fail) {{ Holder owner = new Holder(); {body} }}"
    )
    return f"""
        #include <assert.h>
        extern void arc_test_allocation_checkpoint();
        extern long arc_test_allocation_delta();
        int alive = 0;
        int reads = 0;
        class Item {{
            public Item() {{ alive++; }}
            public void __del__() {{ alive--; }}
        }}
        class Holder {{
            private {field_type} value;
            public Holder() {{ self.value = {initializer}; }}
            public Holder same() {{ return self; }}
            public {field_type} read() {{ reads++; return {read}; }}
            {nullable_method}
        }}
        {exercise}
        void visit(bool chosen, bool fail) {{
            {invoke}
            assert(alive == 0);
        }}
        int main() {{
            visit(false, false);
            visit(true, false);
            visit(false, true);
            visit(true, true);
            arc_test_allocation_checkpoint();
            for (int round = 0; round < 24; round++) {{
                bool chosen = round % 2 == 0;
                bool fail = round % 3 == 0;
                visit(chosen, fail);
            }}
            assert(arc_test_allocation_delta() == 0);
            return 0;
        }}
    """


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("kind", ["borrowed-string", "owned-string", "class"])
@pytest.mark.parametrize("guarded", [False, True], ids=["plain", "unwind"])
@pytest.mark.parametrize("generic", [False, True], ids=["ordinary", "generic"])
@pytest.mark.parametrize("form", ["ternary", "coalesce", "both_calls", "cast_call", "cast_borrowed"])
def test_conditional_call_result_is_released_once(
    semantic_btrcc: Path, tmp_path: Path, frontend: str, kind: str, guarded: bool, generic: bool, form: str
) -> None:
    source = _conditional_source(kind, guarded, generic, form=form)
    result, generated = (
        compile_reference_source(tmp_path, source)
        if frontend == "reference"
        else compile_source(semantic_btrcc, tmp_path, source)
    )
    assert result.returncode == 0, result.stderr
    tracked_strict_matrix((frontend, generated), tmp_path)


@pytest.mark.parametrize("kind", ["borrowed-string", "owned-string", "class"])
@pytest.mark.parametrize("guarded", [False, True], ids=["plain", "unwind"])
@pytest.mark.parametrize("generic", [False, True], ids=["ordinary", "generic"])
@pytest.mark.parametrize("form", ["ternary", "coalesce", "both_calls", "cast_call", "cast_borrowed"])
def test_conditional_call_result_has_identical_c(
    semantic_btrcc: Path, tmp_path: Path, kind: str, guarded: bool, generic: bool, form: str
) -> None:
    compiled = compile_snippet_pair(
        semantic_btrcc, tmp_path, _conditional_source(kind, guarded, generic, form=form), "Conditional"
    )
    assert compiled[0][1].read_bytes() == compiled[1][1].read_bytes()


def _empty_collection_source(generic: bool) -> str:
    parameters = "<T>" if generic else ""
    receiver_type = "T" if generic else "Holder"
    arguments = "<Holder>" if generic else ""
    return f"""
import Library.Vector;
extern void arc_test_allocation_checkpoint();
extern long arc_test_allocation_delta();
class Holder {{
 private Vector<int> values;
 public Holder() {{ self.values = [7]; }}
 public Holder same() {{ return self; }}
 public Vector<int> read() {{ return self.values; }}
}}
class Choice{parameters} {{
 private  {receiver_type} holder;
 public Choice( {receiver_type} holder) {{ self.holder = holder; }}
 public void exercise(bool chosen) {{
  Vector<int> values = chosen ? self.holder.same().read() : [];
  assert(values.len == (chosen ? 1 : 0));
 }}
}}
void visit(bool chosen) {{
 Holder holder = new Holder();
 Choice{arguments} choice = new Choice{arguments}(holder);
 choice.exercise(chosen);
}}
int main() {{
 visit(false); visit(true);
 arc_test_allocation_checkpoint();
 for (int i = 0; i < 24; i++) {{ visit(i % 2 == 0); }}
 assert(arc_test_allocation_delta() == 0);
 return 0;
}}
"""


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("generic", [False, True], ids=["ordinary", "generic"])
def test_empty_conditional_collection_is_released_once(semantic_btrcc, tmp_path, frontend, generic):
    source = _empty_collection_source(generic)
    result, generated = (
        compile_reference_source(tmp_path, source)
        if frontend == "reference"
        else compile_source(semantic_btrcc, tmp_path, source)
    )
    assert result.returncode == 0, result.stderr
    tracked_strict_matrix((frontend, generated), tmp_path)


@pytest.mark.parametrize("generic", [False, True], ids=["ordinary", "generic"])
def test_empty_conditional_collection_has_identical_c(semantic_btrcc, tmp_path, generic):
    compiled = compile_snippet_pair(semantic_btrcc, tmp_path, _empty_collection_source(generic), "EmptyConditional")
    assert compiled[0][1].read_bytes() == compiled[1][1].read_bytes()
