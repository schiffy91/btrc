"""Flexible array members (C row 13) have one meaning in both compilers (PLAN.md Stage 17, r13).

A struct member ``T name[]`` that is last, follows a named member and sits
directly in a named struct's body is a C11 flexible array member (6.7.2.1p18):
array storage of unknown size, emitted as ``T name[];``, in a struct that
exists only behind a pointer (docs/design/c-compatibility.md, "r13 flexible
array members"). Every refusal in that section's wording table is pinned here
to one diagnostic -- message, line and column -- that both compilers report.
The C11-valid forms btrc refuses on purpose (objects, ``extern``, the partial
copy, P1's spelling) are pinned in ``test_c_compatibility_refusals.py``.

The predicate itself has one owner per compiler, the record-member owner
(Python ``TypeSystem.is_flexible_array_member``, btrc
``SemanticTypeSystem.flexibleArrayMember``), and storage, lowering and
validation read it rather than re-deriving the shape.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.diagnostic_harness import diagnostic_identity
from src.tests.btrc.dual_frontend_harness import compile_snippet_pair, strict_c11_matrix
from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair

REPO = Path(__file__).resolve().parents[3]
PYTHON = REPO / "src/compiler/python"
BTRC = REPO / "src/compiler/btrc"

BUFFER = "struct Buffer { int count; int data[]; };\n"
BY_VALUE = "{} uses struct 'Buffer' with a flexible array member by value; use a pointer"
SHADOW = "Type parameter '{0}' of '{1}' is named like struct '{0}', which has a flexible array member; rename the type parameter"

REFUSALS = [
    pytest.param(
        "struct Buffer { int data[]; int count; };\nint main() { return 0; }",
        ("Flexible array member 'Buffer.data' must be the last field of struct 'Buffer'", 1, 21),
        id="not-last",
    ),
    pytest.param(
        "struct Buffer { int data[]; };\nint main() { return 0; }",
        ("Flexible array member 'Buffer.data' needs a named field before it", 1, 21),
        id="no-named-member-before",
    ),
    pytest.param(
        "struct Buffer { int count; string items[]; };\nint main() { return 0; }",
        ("Flexible array member 'Buffer.items' cannot hold managed type 'string'", 1, 35),
        id="managed-element",
    ),
    pytest.param(
        "class Box { public int v; }\nstruct Buffer { int count; Box items[]; };\nint main() { return 0; }",
        ("Flexible array member 'Buffer.items' cannot hold managed type 'Box'", 2, 32),
        id="class-element",
    ),
    pytest.param(
        BUFFER + "int apply(CFunction<int, struct Buffer> f) { return 0; }\nint main() { return 0; }",
        (BY_VALUE.format("Generic argument 2 of Parameter 'apply.f'"), 2, 11),
        id="generic-argument-of-parameter",
    ),
    pytest.param(
        BUFFER + "struct Holder { int n; CFunction<int, struct Buffer> f; };\nint main() { return 0; }",
        (BY_VALUE.format("Generic argument 2 of Struct field 'Holder.f'"), 2, 54),
        id="generic-argument-of-field",
    ),
    pytest.param(
        BUFFER + "class Box<T> { public T v; }\nint main() { Box<struct Buffer>? b = null; return 0; }",
        (BY_VALUE.format("Generic argument 1 of Variable 'b'"), 3, 14),
        id="generic-class-argument-behind-a-reference",
    ),
    pytest.param(
        BUFFER + "class Box<T> { public T v; }\nclass K { public Box<struct Buffer>? b; }\nint main() { return 0; }",
        (BY_VALUE.format("Generic argument 1 of Field 'K.b'"), 3, 11),
        id="generic-class-argument-of-field",
    ),
    pytest.param(
        BUFFER + "extern int f(struct Buffer b);\nint main() { return 0; }",
        (BY_VALUE.format("Parameter 'f.b'"), 2, 14),
        id="prototype-parameter",
    ),
    pytest.param(
        BUFFER + "struct Buffer make();\nint main() { return 0; }",
        (BY_VALUE.format("Return type of 'make'"), 2, 1),
        id="prototype-return",
    ),
    pytest.param(
        BUFFER + "interface I { int f(struct Buffer b); }\nint main() { return 0; }",
        (BY_VALUE.format("Parameter 'I.f.b'"), 2, 21),
        id="interface-parameter",
    ),
    pytest.param(
        BUFFER + "abstract class A { public abstract int f(struct Buffer b); }\nint main() { return 0; }",
        (BY_VALUE.format("Parameter 'A.f.b'"), 2, 42),
        id="abstract-method-parameter",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; int c = (() => *p)().count; return c; }",
        (BY_VALUE.format("Lambda return type"), 2, 48),
        id="lambda-inferred-return",
    ),
    pytest.param(
        BUFFER + "int main() { var f = (struct Buffer b) => b.count; return 0; }",
        (BY_VALUE.format("Lambda parameter 'b'"), 2, 23),
        id="lambda-parameter",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; var t = spawn(() => *p); return 0; }",
        (BY_VALUE.format("Lambda return type"), 2, 53),
        id="spawn-result",
    ),
    pytest.param(
        "class Box { public int v; }\nstruct S { int n; Box? items[]; };\nint main() { return 0; }",
        ("Flexible array member 'S.items' cannot hold managed type 'Box'", 2, 24),
        id="nullable-class-element",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; int c = (*p, 1)._0.count; return c; }",
        (BY_VALUE.format("Generic argument 1 of Tuple literal"), 2, 47),
        id="tuple-literal",
    ),
    pytest.param(
        BUFFER
        + "class K { public T id<T>(T x) { return x; } }\n"
        + "int main() { K k = new K(); struct Buffer* p = null; int c = k.id(*p).count; return c; }",
        (BY_VALUE.format("Generic argument 1 for 'K.id'"), 3, 62),
        id="inferred-generic-instance",
    ),
    pytest.param(
        BUFFER + '#include <stdio.h>\nint main() { struct Buffer* p = null; printf("%d", *p); return 0; }',
        (BY_VALUE.format("Call argument"), 3, 52),
        id="variadic-argument",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer b = {1}; return 0; }",
        (BY_VALUE.format("Variable 'b'"), 2, 14),
        id="brace-initialization",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; int v = (p->count > 0 ? *p : *p).data[0]; return v; }",
        (BY_VALUE.format("Conditional expression"), 2, 48),
        id="conditional-copy",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; int v = (p->count > 0 ? p[0] : p[0]).count; return v; }",
        (BY_VALUE.format("Conditional expression"), 2, 48),
        id="conditional-indexed-copy",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; int n = [*p].len; return n; }",
        (BY_VALUE.format("List literal element"), 2, 48),
        id="list-literal-element",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; int s = 0; for x in [*p] { s = s + x.data[0]; } return s; }",
        (BY_VALUE.format("List literal element"), 2, 60),
        id="list-literal-iteration",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; var m = {1: *p}; return 0; }",
        (BY_VALUE.format("Map literal value"), 2, 51),
        id="map-literal-value",
    ),
    pytest.param(
        BUFFER + "class G<T> { public T v; }\nint main() { new G<struct Buffer>(); return 0; }",
        (BY_VALUE.format("Generic argument 1 of new expression"), 3, 14),
        id="new-generic-instance",
    ),
    pytest.param(
        BUFFER + "int main() { size_t n = sizeof((struct Buffer, int)); return (int)n; }",
        (BY_VALUE.format("Generic argument 1 of sizeof"), 2, 32),
        id="sizeof-tuple",
    ),
    pytest.param(
        BUFFER + "int main() { size_t n = sizeof((int, struct Buffer)); return (int)n; }",
        (BY_VALUE.format("Generic argument 2 of sizeof"), 2, 32),
        id="sizeof-tuple-second",
    ),
    pytest.param(
        BUFFER + "class Box<T> { public T v; }\nint main() { size_t n = sizeof(Box<struct Buffer>); return (int)n; }",
        (BY_VALUE.format("Generic argument 1 of sizeof"), 3, 32),
        id="sizeof-generic-instance",
    ),
    pytest.param(
        BUFFER + "int main() { size_t n = sizeof(CFunction<struct Buffer, int>); return (int)n; }",
        (BY_VALUE.format("Generic argument 1 of sizeof"), 2, 32),
        id="sizeof-function-pointer",
    ),
    pytest.param(
        BUFFER + 'int main() { struct Buffer* p = null; print(f"{*p}"); return 0; }',
        (BY_VALUE.format("Formatted value"), 2, 48),
        id="f-string-value",
    ),
    pytest.param(
        BUFFER
        + "class Reader { public T get<T>(T* value) { return *value; } }\n"
        + "int main() { Reader r = new Reader(); struct Buffer* p = null; int n = r.get(p).data[3]; return n; }",
        (BY_VALUE.format("Generic argument 1 for 'Reader.get'"), 3, 72),
        id="inferred-method-argument-return",
    ),
    pytest.param(
        BUFFER
        + "class Reader { public int get<T>(T* value) { T copy = *value; return 0; } }\n"
        + "int main() { Reader r = new Reader(); struct Buffer* p = null; int n = r.get(p); return n; }",
        (BY_VALUE.format("Generic argument 1 for 'Reader.get'"), 3, 72),
        id="inferred-method-argument-local-copy",
    ),
    pytest.param(
        BUFFER
        + "Buffer* gp = null;\nclass Holder<Buffer> { public Buffer value; "
        + "public Holder(Buffer value) { self.value = value; } "
        + "public int peek(bool c) { return (c ? *gp : *gp).data[3]; } }\nint main() { return 0; }",
        (SHADOW.format("Buffer", "Holder"), 3, 1),
        id="class-type-parameter-shadows-struct",
    ),
    pytest.param(
        "struct Packet { int length; int items[]; };\nPacket* source = null;\n"
        + "class P { public int pick<Packet>(Packet unused, bool flag) { return (flag ? *source : *source).items[2]; } }\n"
        + "int main() { return 0; }",
        (SHADOW.format("Packet", "P.pick"), 3, 11),
        id="method-type-parameter-shadows-struct",
    ),
    pytest.param(
        BUFFER + "interface Getter<Buffer> { Buffer get(); }\nint main() { return 0; }",
        (SHADOW.format("Buffer", "Getter"), 2, 1),
        id="interface-type-parameter-shadows-struct",
    ),
    pytest.param(
        BUFFER + "int f(int x) { return x; }\nint main() { struct Buffer* p = null; return f(*p); }",
        (BY_VALUE.format("Call argument"), 3, 48),
        id="call-argument-of-another-type",
    ),
    pytest.param(
        BUFFER + "int f(int x) { return x; }\nint main() { struct Buffer* p = null; return f(1, *p); }",
        (BY_VALUE.format("Call argument"), 3, 51),
        id="call-argument-beyond-arity",
    ),
    pytest.param(
        BUFFER
        + "class C { public int m(int x) { return x; } }\n"
        + "int main() { C c = new C(); struct Buffer* p = null; return c.m(1, *p); }",
        (BY_VALUE.format("Call argument"), 3, 68),
        id="method-argument-beyond-arity",
    ),
    pytest.param(
        BUFFER
        + "class Reader { public int second<T>((T, int) pair) { return pair._1; } }\n"
        + "int main() { Reader r = new Reader(); struct Buffer* p = null; return r.second((*p, 1)); }",
        (BY_VALUE.format("Generic argument 1 of Tuple literal"), 3, 80),
        id="generic-call-tuple-argument",
    ),
    pytest.param(
        BUFFER
        + "class Holder { public int transform<T>(CFunction<T, struct Buffer*> f) { return 0; } }\n"
        + "int main() { Holder h = new Holder(); return h.transform((struct Buffer* q) => *q); }",
        (BY_VALUE.format("Lambda return type"), 3, 58),
        id="generic-call-lambda-argument",
    ),
    pytest.param(
        BUFFER
        + "class Reader { public int take<T>(T v) { return 0; } }\n"
        + "int main() { Reader r = new Reader(); struct Buffer* p = null; return r.take(p->count > 0 ? *p : *p); }",
        (BY_VALUE.format("Conditional expression"), 3, 78),
        id="generic-call-conditional-argument",
    ),
    pytest.param(
        BUFFER + "int f(struct Buffer b) { return b.count; }\nint main() { return 0; }",
        (BY_VALUE.format("Parameter 'f.b'"), 2, 7),
        id="by-value-parameter",
    ),
    pytest.param(
        BUFFER + "struct Buffer f(struct Buffer* p) { return *p; }\nint main() { return 0; }",
        (BY_VALUE.format("Return type of 'f'"), 2, 1),
        id="by-value-return",
    ),
    pytest.param(
        BUFFER + "struct Outer { int n; struct Buffer inner; };\nint main() { return 0; }",
        (BY_VALUE.format("Struct field 'Outer.inner'"), 2, 37),
        id="struct-field",
    ),
    pytest.param(
        BUFFER + "struct Outer { int n; struct Buffer inner[2]; };\nint main() { return 0; }",
        (BY_VALUE.format("Struct field 'Outer.inner'"), 2, 37),
        id="array-of-structs-field",
    ),
    pytest.param(
        BUFFER + "struct Outer { int n; struct Buffer inner[]; };\nint main() { return 0; }",
        (BY_VALUE.format("Struct field 'Outer.inner'"), 2, 37),
        id="flexible-array-of-flexible-structs",
    ),
    pytest.param(
        BUFFER + "class Box { public struct Buffer b; }\nint main() { return 0; }",
        (BY_VALUE.format("Field 'Box.b'"), 2, 13),
        id="class-field",
    ),
    pytest.param(
        BUFFER + "enum class E { V(struct Buffer p), W }\nint main() { return 0; }",
        (BY_VALUE.format("Rich-enum payload 'E.V.p'"), 2, 18),
        id="rich-enum-payload",
    ),
    pytest.param(
        BUFFER + "int main() { (struct Buffer, int) pair; return 0; }",
        (BY_VALUE.format("Generic argument 1 of Variable 'pair'"), 2, 14),
        id="tuple-element",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer items[2]; return 0; }",
        (BY_VALUE.format("Variable 'items'"), 2, 14),
        id="array-of-structs",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; var b = *p; return 0; }",
        (BY_VALUE.format("Variable 'b'"), 2, 39),
        id="var-copy",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; int n = ((struct Buffer)*p).count; return n; }",
        (BY_VALUE.format("Cast target"), 2, 48),
        id="cast",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; size_t n = sizeof(p->data); return (int)n; }",
        ("sizeof cannot be applied to flexible array member 'Buffer.data'", 2, 50),
        id="sizeof-member",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; int* q = &p->data; return 0; }",
        (
            "Cannot take the address of flexible array member 'Buffer.data'; "
            "use the member itself or an element's address",
            2,
            48,
        ),
        id="address-of-member",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; int x[2] = {1, 2}; p->data = x; return 0; }",
        ("Array object 'int[]' is not assignable", 2, 58),
        id="assign-member",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* p = null; for x in p->data { print(x); } return 0; }",
        ("Array for-in iterable has no provable element capacity", 2, 39),
        id="for-in-member",
    ),
    pytest.param(
        BUFFER + "int main() { struct Buffer* b = new Buffer(); return 0; }",
        ("new requires a class type, got 'Buffer'", 2, 33),
        id="new",
    ),
]


@pytest.mark.parametrize(("source", "expected"), REFUSALS)
def test_refusal_is_identical_in_both_compilers(
    semantic_btrcc: Path, tmp_path: Path, source: str, expected: tuple[str, int, int]
) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)

    assert selfhost.returncode != 0 and reference.returncode != 0
    assert diagnostic_identity(selfhost.stderr) == expected
    assert diagnostic_identity(reference.stderr) == expected


def test_member_assignment_from_a_pointer_is_refused_in_both_compilers(semantic_btrcc: Path, tmp_path: Path) -> None:
    """Both refuse it, worded as for a fixed array member: the reference
    reports the array object first, btrcc the pointer conversion."""
    source = BUFFER + "int main() { struct Buffer* p = null; int* q = null; p->data = q; return 0; }"
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)

    assert diagnostic_identity(reference.stderr) == ("Array object 'int[]' is not assignable", 2, 54)
    assert diagnostic_identity(selfhost.stderr) == ("Cannot assign 'int*' to 'int[]'", 2, 54)


CACHE_LIBRARY = """
{imports}class Cache<Entry> {{
	public Entry value;
	public Cache(Entry value) {{ self.value = value; }}
	public Entry get() {{ return self.value; }}
}}
"""

ENTRY_PROGRAM = """import ./modlib/CacheLib.btrc;
{imports}#include <stdlib.h>
{declaration}int main() {{
	struct Entry* e = (struct Entry*)calloc((size_t)1, sizeof(struct Entry) + (size_t)4);
	if (e == null) {{ return 1; }}
	e->length = 5;
	Cache<int> cache = new Cache<int>(e->length);
	int n = cache.get();
	delete cache;
	free(e);
	print(f"PASS {{n}}");
	return 0;
}}
"""

ENTRY = "struct Entry { int length; char text[]; };\n"


def _compile_library_program(btrcc: Path, root: Path, *, library_sees_entry: bool):
    """A program and an imported user library whose generic's type parameter
    is named like the program's flexible-array struct. Only a library that can
    name the struct (it imports the struct's module) may not shadow it."""
    (root / "modlib").mkdir(parents=True)
    if library_sees_entry:
        (root / "modlib" / "Entries.btrc").write_text(ENTRY)
        library_imports, program_imports, declaration = (
            "import ./Entries.btrc;\n",
            "import ./modlib/Entries.btrc;\n",
            "",
        )
    else:
        library_imports, program_imports, declaration = "", "", ENTRY
    (root / "modlib" / "CacheLib.btrc").write_text(CACHE_LIBRARY.format(imports=library_imports))
    program = root / "UsesEntry.btrc"
    program.write_text(ENTRY_PROGRAM.format(imports=program_imports, declaration=declaration))
    reference_c = root / "reference.c"
    reference = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(program), "--no-cache", "-o", str(reference_c)],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(root / "reference-cache")},
        capture_output=True,
        text=True,
        timeout=300,
    )
    selfhost = subprocess.run([str(btrcc), str(program)], cwd=REPO, capture_output=True, text=True, timeout=300)
    selfhost_c = root / "selfhost.c"
    if selfhost.returncode == 0:
        selfhost_c.write_text(selfhost.stdout)
    return (reference, reference_c), (selfhost, selfhost_c)


def test_imported_library_cannot_hide_a_struct_it_cannot_name(semantic_btrcc: Path, tmp_path: Path) -> None:
    for name, (result, generated) in zip(
        ("reference", "selfhost"), _compile_library_program(semantic_btrcc, tmp_path, library_sees_entry=False)
    ):
        assert result.returncode == 0, result.stderr
        strict_c11_matrix((name, generated), tmp_path)


def test_imported_library_may_not_hide_a_struct_it_imports(semantic_btrcc: Path, tmp_path: Path) -> None:
    message = SHADOW.format("Entry", "Cache")
    for result, _ in _compile_library_program(semantic_btrcc, tmp_path, library_sees_entry=True):
        assert result.returncode != 0
        assert f"error: {message}" in result.stderr, result.stderr


ACCEPTED = [
    pytest.param(
        """
        #include <assert.h>
        #include <stdlib.h>
        struct Buffer { int count; int data[]; };
        int total(int* values, int count) {
            int sum = 0;
            for (int i = 0; i < count; i++) { sum += values[i]; }
            return sum;
        }
        int main() {
            struct Buffer* b = (struct Buffer*)calloc((size_t)1, sizeof(struct Buffer) + (size_t)3 * sizeof(int));
            if (b == null) { return 1; }
            b->count = 3;
            for (int i = 0; i < b->count; i++) { b->data[i] = i + 1; }
            int* second = &b->data[1];
            *second = 5;
            assert(total(b->data, b->count) == 9 && sizeof(*b) == sizeof(struct Buffer));
            free(b);
            return 0;
        }
        """,
        id="allocate-index-decay",
    ),
    pytest.param(
        """
        #include <assert.h>
        typedef int[] Values;
        struct Slice { int length; Values values; };
        int main() {
            int storage[2] = {3, 4};
            struct Slice slice = {2, storage};
            int other[1] = {9};
            slice.values = other;
            assert(slice.values[0] == 9);
            return 0;
        }
        """,
        id="typedef-array-field-stays-a-pointer",
    ),
    pytest.param(
        """
        #include <assert.h>
        #include <stdlib.h>
        struct Slots { int count; int? values[]; };
        int main() {
            int seven = 7;
            struct Slots* slots = (struct Slots*)calloc((size_t)1, sizeof(struct Slots) + sizeof(int*));
            if (slots == null) { return 1; }
            slots->values[0] = &seven;
            int? value = slots->values[0];
            assert(value != null && *value == 7);
            free(slots);
            return 0;
        }
        """,
        id="nullable-pointer-elements",
    ),
    pytest.param(
        """
        #include <assert.h>
        #include <stdint.h>
        #include <stddef.h>
        #include <stdlib.h>
        #include <time.h>
        #include <wchar.h>
        enum Color { RED, GREEN };
        struct Bytes { size_t length; uint8_t data[]; };
        struct Wide { int count; int64_t a[]; };
        struct Sizes { int count; size_t a[]; };
        struct Offsets { int count; ptrdiff_t a[]; };
        struct Addresses { int count; uintptr_t a[]; };
        struct Characters { int count; wchar_t a[]; };
        struct Times { int count; time_t a[]; };
        struct Colors { int count; Color a[]; };
        int main() {
            struct Bytes* bytes = (struct Bytes*)calloc((size_t)1, sizeof(struct Bytes) + (size_t)2);
            struct Colors* colors = (struct Colors*)calloc((size_t)1, sizeof(struct Colors) + sizeof(Color));
            if (bytes == null || colors == null) { return 1; }
            bytes->length = (size_t)2;
            bytes->data[1] = (uint8_t)200;
            colors->a[0] = GREEN;
            assert(bytes->data[1] == (uint8_t)200 && colors->a[0] == GREEN);
            assert(sizeof(struct Wide) + sizeof(struct Sizes) + sizeof(struct Offsets) > (size_t)0);
            assert(sizeof(struct Addresses) + sizeof(struct Characters) + sizeof(struct Times) > (size_t)0);
            free(bytes);
            free(colors);
            return 0;
        }
        """,
        id="hosted-abi-and-enum-elements",
    ),
]


@pytest.mark.parametrize("source", ACCEPTED)
def test_accepted_program_runs_strictly_in_both_compilers(
    semantic_btrcc: Path, tmp_path: Path, request: pytest.FixtureRequest, source: str
) -> None:
    name = request.node.callspec.id
    for artifact in compile_snippet_pair(semantic_btrcc, tmp_path, source, name):
        strict_c11_matrix(artifact, tmp_path)


def _source(path: Path) -> str:
    return path.read_text()


def test_the_predicate_has_one_owner_per_compiler() -> None:
    python_definitions = [
        path for path in PYTHON.rglob("*.py") if re.search(r"def is_flexible_array_member\b", _source(path))
    ]
    btrc_definitions = [
        path for path in BTRC.rglob("*.btrc") if re.search(r"class bool flexibleArrayMember\(", _source(path))
    ]
    assert python_definitions == [PYTHON / "analyzer/types.py"]
    assert btrc_definitions == [BTRC / "analyzer/Types.btrc"]


def test_storage_lowering_and_validation_read_the_owner() -> None:
    python_readers = {
        "analyzer/aggregates.py": 4,
        "ir/lowering/classes.py": 1,
    }
    for relative, minimum in python_readers.items():
        text = _source(PYTHON / relative)
        assert text.count("TypeSystem.is_flexible_array_member(") >= minimum, relative
    btrc_readers = {
        "analyzer/validation/Storage.btrc": 2,
        "analyzer/validation/Declarations.btrc": 1,
        "ir/lowering/Declarations.btrc": 1,
    }
    for relative, minimum in btrc_readers.items():
        text = _source(BTRC / relative)
        assert text.count("SemanticTypeSystem.flexibleArrayMember(") >= minimum, relative
    # Neither emitter derives the facet: it is IR data set by struct lowering.
    assert "is_unsized_array=flexible" in _source(PYTHON / "ir/lowering/classes.py")
    assert "field.isUnsizedArray = true;" in _source(BTRC / "ir/lowering/Declarations.btrc")
