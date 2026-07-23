"""Symbol resolution across inheritance and generic/builtin members — the
shared core behind definition, hover, references, and completion."""

from src.devex.lsp.completion import get_completions
from src.devex.lsp.definition import get_definition
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.references import get_references
from src.devex.lsp.tests.lsphelp import analyze, hover_text, pos_of

SRC = """\
import std.vector;

class Animal {
    public string name;
    public Animal(string name) { self.name = name; }
    public string speak() { return "..."; }
}

class Dog extends Animal {
    public int legs;
    public Dog(string name) { self.name = name; self.legs = 4; }
    public string speak() { return "woof"; }
    public int legCount() { return self.legs; }
}

int main() {
    Dog d = Dog("rex");
    string s = d.speak();
    string n = d.name;
    int l = d.legCount();
    Vector<int> nums = [1, 2, 3];
    nums.push(4);
    int first = nums.get(0);
    return l + first;
}
"""


def _def_line(needle, occurrence=1, offset=1):
    loc = get_definition(analyze(SRC), pos_of(SRC, needle, occurrence, offset))
    return loc.range.start.line if loc else None


def test_sample_is_clean():
    # inheritance + override + generic collection must analyze without error
    assert analyze(SRC).diagnostics == []


def test_definition_own_overridden_method():
    # d.speak() → Dog's own override on line 11
    assert _def_line("d.speak", offset=2) == 11


def test_definition_inherited_field_walks_parent():
    # d.name → inherited field declared in Animal on line 3
    assert _def_line("d.name", offset=2) == 3


def test_definition_own_method():
    assert _def_line("d.legCount", offset=2) == 12


def test_hover_inherited_field():
    t = hover_text(get_hover_info(analyze(SRC), pos_of(SRC, "d.name", offset=2)))
    assert "name" in t and "string" in t


def test_references_of_field_across_class():
    # `name` field: declaration + self.name (x2) + d.name
    refs = get_references(analyze(SRC), pos_of(SRC, "public string name", offset=14), include_declaration=True)
    lines = {r.range.start.line for r in refs}
    assert {3, 4, 10, 18} <= lines


def test_member_completion_includes_inherited():
    items = get_completions(analyze(SRC), pos_of(SRC, "d.speak", offset=2))
    names = {i.label for i in items}
    assert {"speak", "name", "legCount", "legs"} <= names


def test_hover_on_generic_builtin_member():
    # hovering a Vector<int> member resolves via the built-in member catalog
    t = hover_text(get_hover_info(analyze(SRC), pos_of(SRC, "nums.push", offset=5)))
    assert "push" in t


def test_member_completion_on_generic_builtin():
    items = get_completions(analyze(SRC), pos_of(SRC, "nums.push", offset=5))
    names = {i.label for i in items}
    assert "push" in names and "get" in names
