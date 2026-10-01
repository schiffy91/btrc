"""Symbol resolution across inheritance and generic/builtin members — the
shared core behind definition, hover, references, and completion."""

from src.tests.lsp.lsphelp import (
    analyze,
    get_completions,
    get_definition,
    get_hover_info,
    get_references,
    hover_text,
    pos_of,
)

SRC = """\
import Library.Vector;

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


# ---- inherited members accessed through a subclass variable ----------------

INH = """\
class Animal {
    public string name;
    public Animal(string n) { self.name = n; }
    public string speak() { return self.name; }
}

class Dog extends Animal {
    public Dog(string n) { self.name = n; }
}

int main() {
    Dog d = Dog("rex");
    string s = d.speak();
    string nm = d.name;
    return 0;
}
"""


def test_references_inherited_method_access_classifies_via_parent():
    # click the *access* d.speak(); speak is inherited (Dog doesn't override it).
    # Non-empty result means it classified as a member via the parent chain
    # (a misclassification as a plain variable would drop the dotted access).
    refs = get_references(analyze(INH), pos_of(INH, "d.speak", offset=2))
    assert refs


def test_references_inherited_field_access_classifies_via_parent():
    refs = get_references(analyze(INH), pos_of(INH, "d.name", offset=2))
    assert refs


def test_hover_inherited_member_access():
    from src.tests.lsp.lsphelp import hover_text

    t = hover_text(get_hover_info(analyze(INH), pos_of(INH, "d.speak", offset=2)))
    assert "speak" in t


def test_inherited_method_references_via_variable():
    # describe() is inherited by Gen (not overridden); references on the
    # declaration span the inherited call site through a Gen variable.
    src = (
        "class Base { public int b; public Base() { self.b = 0; }\n"
        "             public int describe() { return self.b; } }\n"
        "class Sub extends Base { public Sub() { self.b = 1; } }\n"
        "int main() { Sub s = Sub(); return s.describe(); }\n"
    )
    refs = get_references(analyze(src), pos_of(src, "public int describe", occurrence=1, offset=11))
    lines = {r.range.start.line for r in refs}
    assert 3 in lines  # the s.describe() call


# ---- generics + inheritance + property -------------------------------------

GEN = """\
struct RawPt { int x; int y; };

class Base {
    public int b;
    public Base() { self.b = 0; }
    public int describe() { return self.b; }
    public int doubled { get { return self.b * 2; } }
}

class Gen<T> extends Base {
    public T val;
    public Gen(T v) { self.val = v; }
    public T unwrap() { return self.val; }
}

int useGen(Gen<int> g) {
    return g.unwrap();
}

int main() {
    Gen<int> gi = Gen(5);
    int r = useGen(gi);
    return r;
}
"""


def test_hover_generic_class_shows_params_and_parent():
    t = hover_text(get_hover_info(analyze(GEN), pos_of(GEN, "Gen<int> gi", offset=0)))
    assert "Gen" in t and ("T" in t or "Base" in t)


def test_hover_parameter_of_class_type():
    t = hover_text(get_hover_info(analyze(GEN), pos_of(GEN, "g.unwrap", offset=0)))
    assert "g" in t or "Gen" in t


def test_completion_lists_class_names_with_detail():
    # general (non-dot) completion builds class-name items incl. Gen's <T>/extends detail
    names = {i.label for i in get_completions(analyze(GEN), pos_of(GEN, "int r =", offset=0))}
    assert "Gen" in names and "Base" in names


def test_completion_inherited_member_on_param():
    names = {i.label for i in get_completions(analyze(GEN), pos_of(GEN, "g.unwrap", offset=2))}
    assert {"unwrap", "describe", "val"} <= names
