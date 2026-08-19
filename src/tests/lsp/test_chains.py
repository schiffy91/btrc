"""Multi-level member chains and `var` type inference — the resolve_chain_type /
resolve_member_type / _scan_for_var_type core shared by every feature."""

from src.tests.lsp.lsphelp import get_completions
from src.tests.lsp.lsphelp import get_definition
from src.tests.lsp.lsphelp import get_hover_info
from src.tests.lsp.lsphelp import analyze, hover_text, pos_of

SRC = """\
class Inner {
    public int value;
    public Inner(int v) { self.value = v; }
    public int get() { return self.value; }
}

class Outer {
    public Inner inner;
    public Outer() { self.inner = Inner(7); }
    public Inner getInner() { return self.inner; }
}

int main() {
    Outer o = Outer();
    var x = o.getInner();
    int a = o.inner.value;
    int b = o.getInner().get();
    int c = x.value;
    return a + b + c;
}
"""


def _def_line(needle, occurrence=1, offset=1):
    loc = get_definition(analyze(SRC), pos_of(SRC, needle, occurrence, offset))
    return loc.range.start.line if loc else None


def test_clean():
    assert analyze(SRC).diagnostics == []


def test_chain_field_then_field():
    # o.inner.value → `value` field of Inner on line 1
    assert _def_line("o.inner.value", offset=8) == 1


def test_chain_first_hop_field():
    # the `inner` hop → Inner field declared on line 7
    assert _def_line("o.inner.value", offset=2) == 7


def test_var_inferred_from_method_return():
    # `x` is `var x = o.getInner()` → inferred Inner; x.value resolves to line 1
    assert _def_line("x.value", offset=2) == 1


def test_var_hover_shows_inferred_type():
    t = hover_text(get_hover_info(analyze(SRC), pos_of(SRC, "x.value", offset=0)))
    assert "Inner" in t


def test_chain_through_method_return():
    # o.getInner().get() → `get` method of Inner on line 3
    assert _def_line("o.getInner().get", offset=13) == 3


def test_completion_after_chain():
    items = get_completions(analyze(SRC), pos_of(SRC, "o.inner.value", offset=8))
    names = {i.label for i in items}
    assert {"value", "get"} <= names


GENERIC_BUILTIN_SRC = """\
import std.map;

int main() {
    string text = "a,b";
    int splitCount = text.split(",").len;
    Map<string, int> lookup = {};
    int keyCount = lookup.keys().len;
    return splitCount + keyCount;
}
"""


def _completion_names(source, needle, offset):
    position = pos_of(source, needle, offset=offset)
    return {item.label for item in get_completions(analyze(source), position)}


def test_completion_after_string_split_call_returns_vector_members():
    names = _completion_names(
        GENERIC_BUILTIN_SRC,
        'text.split(",").len',
        len('text.split(",").'),
    )
    assert {"len", "get", "join"} <= names


def test_completion_after_map_keys_call_returns_vector_members():
    names = _completion_names(
        GENERIC_BUILTIN_SRC,
        "lookup.keys().len",
        len("lookup.keys()."),
    )
    assert {"len", "get", "join"} <= names


def test_definition_after_generic_builtin_call_maps_to_stdlib_member():
    loc = get_definition(
        analyze(GENERIC_BUILTIN_SRC),
        pos_of(GENERIC_BUILTIN_SRC, "lookup.keys().len", offset=len("lookup.keys().")),
    )

    assert loc is not None
    assert loc.uri.endswith("/src/stdlib/vector.btrc")


def test_hover_after_generic_builtin_call_uses_vector_member():
    text = hover_text(
        get_hover_info(
            analyze(GENERIC_BUILTIN_SRC),
            pos_of(
                GENERIC_BUILTIN_SRC,
                'text.split(",").len',
                offset=len('text.split(",").'),
            ),
        )
    )

    assert "int" in text and "len" in text
