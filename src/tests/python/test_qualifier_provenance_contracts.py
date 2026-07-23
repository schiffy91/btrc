"""Declarator-aware qualifier provenance and strict-C boundaries."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.qualifier_provenance import (
    effective_outer_volatile,
    volatile_qualifier_depths,
)

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _analyze(source):
    program = Parser(Lexer(source, "<qualifier-contract>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _emit(source):
    analyzed = _analyze(source)
    assert analyzed.errors == []
    module = IRLowerer(analyzed).lower()
    return module, CEmitter().emit(optimize(module))


def test_effective_storage_and_decay_provenance_are_distinct():
    typedefs = {"V": TypeExpr(base="int", is_volatile=True)}
    scalar = TypeExpr(base="V")
    pointer = TypeExpr(base="V", pointer_depth=1)
    array = TypeExpr(base="V", is_array=True)

    assert effective_outer_volatile(scalar, typedefs)
    assert not effective_outer_volatile(pointer, typedefs)
    assert effective_outer_volatile(array, typedefs)
    assert volatile_qualifier_depths(pointer, typedefs) == frozenset({1})
    assert volatile_qualifier_depths(array, typedefs) == frozenset({1})


@pytest.mark.parametrize(
    "source",
    [
        "volatile int value = 0; int* alias = &value; int main(){ return 0; }",
        "struct S { volatile int value; }; int main(){ S s = {0}; int* p = &s.value; return 0; }",
        "void take(int* p){} int main(){ volatile int values[1]={0}; take(values); return 0; }",
        """
            typedef volatile int V;
            typedef V* P;
            int main() {
                V value = 0;
                P pointer = &value;
                int* bad = &pointer[0];
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            int main() {
                V value = 0;
                P pointer = &value;
                int* bad = &*pointer;
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            int main() {
                V value = 0;
                Vector<P> pointers = [&value];
                int* bad = pointers[0];
                return 0;
            }
        """,
        """
            typedef volatile int V;
            class Box<T> {
                public T value;
                public Box(T value) { self.value = value; }
            }
            int main() {
                Box<V> box = new Box<V>(0);
                int* bad = &box.value;
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            class Source<T> {
                public Source() {}
                public T get() { return (T)null; }
            }
            int main() {
                Source<P> source = new Source<P>();
                int* bad = source.get();
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            class Source<T> {
                public Source() {}
                public T __neg__() { return (T)null; }
            }
            int main() {
                Source<P> source = new Source<P>();
                int* bad = -source;
                return 0;
            }
        """,
        """
            typedef volatile int V;
            typedef V* P;
            class Source<T> {
                public Source() {}
                public T get(int index) { return (T)null; }
            }
            int main() {
                Source<P> source = new Source<P>();
                int* bad = source[0];
                return 0;
            }
        """,
    ],
)
def test_nested_volatile_loss_is_rejected_before_ir(source):
    errors = _analyze(source).errors
    assert any("would discard volatile storage qualification" in error for error in errors)
    assert any("unsupported layered pointer qualifiers" in error for error in errors)


@pytest.mark.parametrize(
    "source, subject",
    [
        ("const int f(){ return 1; } int main(){ return 0; }", "function 'f'"),
        (
            "class C { public volatile int* f(){ return null; } } int main(){ return 0; }",
            "method 'C.f'",
        ),
        ("__fn_ptr<const int> callback; int main(){ return 0; }", "Global 'callback'"),
        (
            "int main(){ var callback = const int function(){ return 1; }; return 0; }",
            "Lambda return type",
        ),
    ],
)
def test_callable_outer_cv_results_are_rejected(source, subject):
    errors = _analyze(source).errors
    assert any(subject in error and "C discards qualifiers" in error for error in errors)


def test_const_rich_enum_payload_is_rejected_but_const_pointee_is_valid():
    rejected = _analyze("enum class Payload { Some(const int value), None } int main(){ return 0; }")
    assert any("cannot use const storage" in error for error in rejected.errors)

    accepted = _analyze("enum class Payload { Some(const int* value), None } int main(){ return 0; }")
    assert accepted.errors == []


def test_effective_metadata_does_not_duplicate_physical_qualifiers():
    module, emitted = _emit(
        """
        typedef volatile int V;
        struct Probe { V value; V* pointer; volatile int values[2]; };
        V global = 0;
        int read(V value) { V local = value; return local; }
        int main(){ Probe probe = {0}; return read(global) + probe.value; }
        """
    )
    probe = next(item for item in module.struct_defs if item.name == "Probe")
    fields = {field.name: field for field in probe.fields}
    assert (fields["value"].is_volatile, fields["value"].effective_is_volatile) == (False, True)
    assert (fields["pointer"].is_volatile, fields["pointer"].effective_is_volatile) == (False, False)
    assert (fields["values"].is_volatile, fields["values"].effective_is_volatile) == (True, True)
    global_value = next(item for item in module.global_decls if item.name == "global")
    assert (global_value.is_volatile, global_value.effective_is_volatile) == (False, True)
    read = next(item for item in module.function_defs if item.name.endswith("read"))
    assert (read.params[0].is_volatile, read.params[0].effective_is_volatile) == (False, True)
    local = next(item for item in read.body.stmts if getattr(item, "name", None) == "local")
    assert (local.is_volatile, local.effective_is_volatile) == (False, True)
    assert "volatile V" not in emitted


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_typedef_preserved_volatile_aliases_compile_as_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    _, emitted = _emit(
        """
        typedef volatile int V;
        typedef V* P;
        struct Probe { V value; };
        void writeValue(V* value) { *value = 7; }
        int main() {
            V value = 0;
            V values[1] = {0};
            P pointer = &value;
            long distance = pointer - pointer;
            bool absent = !pointer;
            struct Probe probe = {0};
            writeValue(&value);
            writeValue(values);
            writeValue(&pointer[0]);
            writeValue(&*pointer);
            writeValue(&probe.value);
            return value == 7 && values[0] == 7 && probe.value == 7
                && distance == 0 && !absent ? 0 : 1;
        }
        """
    )
    source = tmp_path / "qualifiers.c"
    binary = tmp_path / "qualifiers"
    source.write_text(emitted)
    built = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr
