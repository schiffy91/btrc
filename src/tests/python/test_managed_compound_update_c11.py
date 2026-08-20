"""Strict-C regression coverage for managed compound-update temporaries."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.btrc.runtime_ownership_harness import require_sanitizers, sanitized_build_and_run
from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import _tracked_strict_matrix
from src.tests.python.test_codegen import emit_c

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src/tests/classes/test_class_compound_assignment.btrc"
COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

CONVERTED_RHS_SOURCE = r"""
#include <assert.h>

extern void arc_test_allocation_checkpoint();
extern long arc_test_allocation_delta();

int makeCalls = 0;
int conversionCalls = 0;
int liveLabels = 0;
int liveBoxes = 0;
int targetCalls = 0;
int orderStep = 0;

typedef string SuffixAlias;

class Label {
    public Label() { liveLabels++; }
    public string toString() {
        conversionCalls++;
        return "!";
    }
    public void __del__() { liveLabels--; }
}

class GenericLabel<T> {
    public GenericLabel() { liveLabels++; }
    public string toString() {
        conversionCalls++;
        return "!";
    }
    public void __del__() { liveLabels--; }
}

class TextBox {
    public string text;
    public TextBox(string text) {
        self.text = text;
        liveBoxes++;
    }
    public TextBox __add__(SuffixAlias suffix) {
        return new TextBox(self.text + suffix);
    }
    public void __del__() { liveBoxes--; }
}

class GenericText<T> {
    public string text;
    public GenericText(string text) {
        self.text = text;
        liveBoxes++;
    }
    public GenericText<T> __add__(SuffixAlias suffix) {
        return new GenericText<T>(self.text + suffix);
    }
    public void __del__() { liveBoxes--; }
}

class BaseValue {
    public BaseValue() {}
}

class ChildValue extends BaseValue {
    public ChildValue() {}
}

class BaseBox {
    public BaseBox() { liveBoxes++; }
    public BaseBox __add__(BaseValue replacement) {
        return new BaseBox();
    }
    public void __del__() { liveBoxes--; }
}

class Owner {
    public TextBox text;
    public Owner(TextBox text) { self.text = text; }
}

typedef TextBox TextBoxAlias;

Owner activeOwner = null;

Label makeLabel() {
    makeCalls++;
    return new Label();
}

GenericLabel<int> makeGenericLabel() {
    makeCalls++;
    return new GenericLabel<int>();
}

Owner targetOwner() {
    targetCalls++;
    assert(orderStep == 0);
    orderStep = 1;
    return activeOwner;
}

Label makeOrderedLabel() {
    assert(orderStep == 1);
    orderStep = 2;
    return makeLabel();
}

void ordinaryUpdate() {
    TextBox text = new TextBox("ordinary");
    text += makeLabel();
    assert(text.text == "ordinary!");
    assert(liveLabels == 0 && liveBoxes == 1);
    text = null;
}

void genericUpdate() {
    GenericText<int> text = new GenericText<int>("generic");
    text += makeGenericLabel();
    assert(text.text == "generic!");
    assert(liveLabels == 0 && liveBoxes == 1);
    text = null;
}

void baseUpdate() {
    BaseBox box = new BaseBox();
    box += new ChildValue();
    assert(liveBoxes == 1);
    box = null;
}

void effectUpdate() {
    int initialTargetCalls = targetCalls;
    activeOwner = new Owner(new TextBox("effect"));
    orderStep = 0;
    targetOwner().text += makeOrderedLabel();
    assert(orderStep == 2 && targetCalls == initialTargetCalls + 1);
    assert(activeOwner.text.text == "effect!");
    assert(liveLabels == 0 && liveBoxes == 1);
    activeOwner = null;
}

void aliasUpdate() {
    TextBoxAlias text = new TextBox("alias");
    text += makeLabel();
    assert(text.text == "alias!");
    assert(liveLabels == 0 && liveBoxes == 1);
    text = null;
}

int main() {
    ordinaryUpdate();
    genericUpdate();
    aliasUpdate();
    baseUpdate();
    effectUpdate();
    assert(makeCalls == 4 && conversionCalls == 4);
    assert(liveLabels == 0 && liveBoxes == 0);

    arc_test_allocation_checkpoint();
    ordinaryUpdate();
    assert(arc_test_allocation_delta() == 0);
    genericUpdate();
    assert(arc_test_allocation_delta() == 0);
    aliasUpdate();
    assert(arc_test_allocation_delta() == 0);
    baseUpdate();
    assert(arc_test_allocation_delta() == 0);
    effectUpdate();
    assert(arc_test_allocation_delta() == 0);
    assert(makeCalls == 8 && conversionCalls == 8);
    assert(liveLabels == 0 && liveBoxes == 0);
    return 0;
}
"""

SANITIZED_CONVERTED_RHS_SOURCE = (
    CONVERTED_RHS_SOURCE.replace(
        "extern void arc_test_allocation_checkpoint();\nextern long arc_test_allocation_delta();\n\n",
        "",
    )
    .replace("    arc_test_allocation_checkpoint();\n", "")
    .replace("    assert(arc_test_allocation_delta() == 0);\n", "")
)

GENERIC_TEMPLATE_CONVERSION_SOURCE = r"""
#include <assert.h>

int conversions = 0;
int liveWords = 0;

class Word<T> {
    public int generation;
    public Word(int generation) {
        self.generation = generation;
        liveWords++;
    }
    public string toString() {
        conversions++;
        return "!";
    }
    public Word<T> __add__(string suffix) {
        assert(suffix == "!");
        return new Word<T>(self.generation + 1);
    }
    public void __del__() { liveWords--; }
}

class Box<T> {
    public T value;
    public Box(T value) { self.value = value; }
    public void add(T value) { self.value += value; }
}

int main() {
    Word<int> value = new Word<int>(1);
    Box<Word<int>> box = new Box<Word<int>>(value);
    box.add(value);
    assert(conversions == 1);
    assert(box.value.generation == 2);
    box = null;
    value = null;
    assert(liveWords == 0);
    return 0;
}
"""

ARC_FIELD_PUBLICATION_SOURCE = r"""
#include <assert.h>

int liveValues = 0;
int valueDrops = 0;
int simplePrecommitCaught = 0;
int compoundPrecommitCaught = 0;

class Value {
    public int value;
    public bool throwOnDrop;
    public Value(int value, bool throwOnDrop) {
        self.value = value;
        self.throwOnDrop = throwOnDrop;
        liveValues++;
    }
    public Value __add__(int delta) {
        return new Value(self.value + delta, false);
    }
    public void __del__() {
        liveValues--;
        valueDrops++;
        if (self.throwOnDrop) { throw "destructor failed"; }
    }
}

class Holder {
    public Value field;
    public Holder(int value, bool throwOnDrop) {
        self.field = new Value(value, throwOnDrop);
    }
}

class DestroyingOwner {
    public Value field;
    public bool compound;
    public DestroyingOwner(bool compound) {
        self.field = new Value(compound ? 20 : 10, false);
        self.compound = compound;
    }
    public void __del__() {
        if (self.compound) {
            try {
                self.field += 1;
            } catch (string error) {
                if (error != null) { compoundPrecommitCaught++; }
            }
        } else {
            try {
                self.field = new Value(11, false);
            } catch (string error) {
                if (error != null) { simplePrecommitCaught++; }
            }
        }
    }
}

int replaceWithBomb(Holder holder) {
    holder.field = new Value(500, true);
    return 1;
}

void precommitMatrix() {
    DestroyingOwner simple = new DestroyingOwner(false);
    simple = null;
    assert(simplePrecommitCaught == 1);
    assert(liveValues == 0 && valueDrops == 2);

    DestroyingOwner compound = new DestroyingOwner(true);
    compound = null;
    assert(compoundPrecommitCaught == 1);
    assert(liveValues == 0 && valueDrops == 4);
}

void simplePostcommitMatrix() {
    Holder owned = new Holder(100, true);
    bool ownedCaught = false;
    try {
        owned.field = new Value(101, false);
    } catch (string error) {
        ownedCaught = error == "destructor failed";
    }
    assert(ownedCaught && owned.field.value == 101 && liveValues == 1);
    owned = null;
    assert(liveValues == 0);

    Holder borrowedOwner = new Holder(200, true);
    Value borrowed = new Value(201, false);
    bool borrowedCaught = false;
    try {
        borrowedOwner.field = borrowed;
    } catch (string error) {
        borrowedCaught = error == "destructor failed";
    }
    assert(borrowedCaught && borrowedOwner.field == borrowed && liveValues == 1);
    borrowedOwner = null;
    assert(liveValues == 1);
    borrowed = null;
    assert(liveValues == 0);
}

void compoundPostcommitMatrix() {
    Holder holder = new Holder(300, false);
    bool caught = false;
    try {
        holder.field += replaceWithBomb(holder);
    } catch (string error) {
        caught = error == "destructor failed";
    }
    assert(caught && holder.field.value == 301 && liveValues == 1);
    holder = null;
    assert(liveValues == 0);
}

int main() {
    precommitMatrix();
    simplePostcommitMatrix();
    compoundPostcommitMatrix();
    assert(liveValues == 0 && valueDrops == 11);
    return 0;
}
"""


@pytest.fixture(scope="module")
def compound_fixture_c(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("managed-compound") / "fixture.c"
    transpiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(FIXTURE),
            "--no-cache",
            "-o",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert transpiled.returncode == 0, transpiled.stderr
    return output


@pytest.fixture(scope="module")
def arc_field_publication_c(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("arc-field-publication") / "publication.c"
    output.write_text(emit_c(ARC_FIELD_PUBLICATION_SOURCE))
    return output


def _function_body(source: str, signature: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(signature)} \{{\n(?P<body>.*?)^\}}$",
        source,
    )
    assert match is not None, f"missing generated function: {signature}"
    return match.group("body")


def test_class_edge_update_only_captures_a_consumed_current_value(
    compound_fixture_c: Path,
) -> None:
    source = compound_fixture_c.read_text()
    regular = _function_body(
        source,
        "void ScalarCounterHolder_add(ScalarCounterHolder* self, int amount)",
    )
    generic = _function_body(
        source,
        "static void btrc_GenericScalarCounterHolder_int_add(btrc_GenericScalarCounterHolder_int* self, int amount)",
    )
    declaration = re.compile(r"ScalarCounter\* __btrc_update_current_\d+ = NULL;")

    assert declaration.findall(regular) == []
    # The generic method still needs one snapshot for its local `local += amount`.
    assert len(declaration.findall(generic)) == 1


def test_compound_overload_rhs_uses_parameter_target_conversion_once() -> None:
    source = emit_c(CONVERTED_RHS_SOURCE)
    cases = (
        ("void ordinaryUpdate(void)", "makeLabel()", "Label_toString("),
        (
            "void genericUpdate(void)",
            "makeGenericLabel()",
            "btrc_GenericLabel_int_toString(",
        ),
        ("void aliasUpdate(void)", "makeLabel()", "Label_toString("),
    )
    for signature, maker, conversion in cases:
        body = _function_body(source, signature)
        assert body.count(maker) == 1
        assert re.search(r"char\* __btrc_update_rhs_\d+ = NULL;", body)
        assert conversion in body
        assert "__btrc_arc_release_acyclic(" in body

    alias = _function_body(source, "void aliasUpdate(void)")
    assert re.search(r"TextBoxAlias __btrc_update_old_\d+ = NULL;", alias)
    assert "TextBox___add__(" in alias

    generic = _function_body(source, "void genericUpdate(void)")
    assert "btrc_GenericText_int___add__(" in generic

    base = _function_body(source, "void baseUpdate(void)")
    rhs = re.search(r"ChildValue\* (__btrc_update_rhs_\d+) = NULL;", base)
    assert rhs is not None
    assert f"((BaseValue*){rhs.group(1)})" in base
    assert f"{rhs.group(1)} = ((BaseValue*)" not in base

    effectful = _function_body(source, "void effectUpdate(void)")
    assert effectful.count("targetOwner()") == 1
    assert effectful.count("makeOrderedLabel()") == 1
    assert effectful.index("targetOwner()") < effectful.index("makeOrderedLabel()")


def test_arc_field_publication_keeps_a_protected_caller_reference(
    arc_field_publication_c: Path,
) -> None:
    source = arc_field_publication_c.read_text()
    simple = _function_body(source, "void simplePostcommitMatrix(void)")
    simple_values = re.findall(r"Value\* volatile (__btrc_store_value_\d+) = NULL;", simple)
    assert len(simple_values) == 2
    for value in simple_values:
        registration = simple.index(f"((void*)(&{value}))")
        publication = simple.index("__btrc_arc_replace_edge", registration)
        clearing = simple.index(f"({value} = NULL)", publication)
        releasing = simple.index("__btrc_arc_release_acyclic", clearing)
        call = simple[publication:clearing]
        assert value in call
        assert re.search(rf"__btrc_arc_replace_edge\(.*?{value}.*?\}}\), 0\)", call)
        assert registration < publication < clearing < releasing

    borrowed = simple_values[1]
    assert simple.index(f"__btrc_arc_retain({borrowed})") < simple.index(
        "__btrc_arc_replace_edge", simple.index(f"__btrc_arc_retain({borrowed})")
    )

    compound = _function_body(source, "void compoundPostcommitMatrix(void)")
    replacement = re.search(r"Value\* volatile (__btrc_update_new_\d+) = NULL;", compound)
    assert replacement is not None
    value = replacement.group(1)
    registration = compound.index(f"((void*)(&{value}))")
    publication = compound.index("__btrc_arc_replace_edge", registration)
    clearing = compound.index(f"({value} = NULL)", publication)
    releasing = compound.index("__btrc_arc_release_acyclic", clearing)
    call = compound[publication:clearing]
    assert value in call
    assert re.search(rf"__btrc_arc_replace_edge\(.*?{value}.*?\}}\), 0\)", call)
    assert registration < publication < clearing < releasing


@pytest.mark.skipif(not COMPILERS, reason="requires hosted C11 compilers")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_arc_field_publication_is_strict_c11_and_unwind_safe(
    tmp_path: Path,
    arc_field_publication_c: Path,
    c_compiler: str,
) -> None:
    executable = tmp_path / f"arc-field-publication-{Path(c_compiler).name}"
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(arc_field_publication_c),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([executable], capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
def test_arc_field_publication_is_sanitizer_clean(
    tmp_path: Path,
    arc_field_publication_c: Path,
) -> None:
    sanitized_build_and_run(
        arc_field_publication_c,
        tmp_path / "arc-field-publication-sanitized",
        require_sanitizers(tmp_path),
    )


def test_compound_overload_rejects_incompatible_argument_and_result() -> None:
    program = Parser(
        Lexer(
            """
            class TextBox {
                public TextBox() {}
                public TextBox __add__(string suffix) { return new TextBox(); }
            }
            class BadResult {
                public BadResult() {}
                public int __add__(int amount) { return amount; }
            }
            void run() {
                TextBox text = new TextBox();
                text += 1;
                BadResult bad = new BadResult();
                bad += 1;
            }
            """,
            "<compound-overload-contract>",
        ).tokenize()
    ).parse()
    errors = SemanticAnalyzer().analyze(program).errors

    assert any("Operator '+' expects 'string' but got 'int'" in error for error in errors)
    assert any(
        "Operator '+' returns 'int', which cannot be stored in compound target 'BadResult*'" in error
        for error in errors
    )


def test_generic_compound_overload_fails_closed_on_incompatible_concrete_result() -> None:
    with pytest.raises(
        CodegenError,
        match=r"operator '\+' returns 'int', which cannot be stored in compound target 'A\*'",
    ):
        emit_c(
            """
            class A {
                public A() {}
                public int __add__(A value) { return 1; }
            }
            class Box<T> {
                public T value;
                public Box(T value) { self.value = value; }
                public void add(T value) { self.value += value; }
            }
            int main() {
                A value = new A();
                Box<A> box = new Box<A>(value);
                box.add(value);
                return 0;
            }
            """
        )


def test_generic_compound_overload_fails_closed_on_incompatible_concrete_parameter() -> None:
    with pytest.raises(
        CodegenError,
        match=r"operator '\+' parameter 'char\*' cannot accept concrete 'A\*'",
    ):
        emit_c(
            """
            class A {
                public A() {}
                public A __add__(string value) { return new A(); }
            }
            class Box<T> {
                public T value;
                public Box(T value) { self.value = value; }
                public void add(T value) { self.value += value; }
            }
            int main() {
                A value = new A();
                Box<A> box = new Box<A>(value);
                box.add(value);
                return 0;
            }
            """
        )


@pytest.mark.skipif(not COMPILERS, reason="requires hosted C11 compilers")
def test_generic_template_compound_materializes_concrete_string_conversion(tmp_path: Path) -> None:
    generated = tmp_path / "generic-template-compound-conversion.c"
    source = emit_c(GENERIC_TEMPLATE_CONVERSION_SOURCE)
    generated.write_text(source)
    assert re.search(r"static char\* btrc_Word_int_toString\(", source)
    assert "btrc_Word_int_toString(__btrc_call_operand_" in source

    for compiler in COMPILERS:
        executable = tmp_path / f"generic-template-compound-conversion-{Path(compiler).name}"
        build = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                str(generated),
                "-lm",
                "-lpthread",
                "-o",
                str(executable),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert build.returncode == 0, build.stderr
        run = subprocess.run([executable], capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires hosted C11 compilers")
def test_compound_overload_rhs_conversion_is_tracked_and_sanitized(tmp_path: Path) -> None:
    tracked = tmp_path / "compound-converted-rhs-tracked.c"
    tracked.write_text(emit_c(CONVERTED_RHS_SOURCE))
    _tracked_strict_matrix(("python-compound-converted-rhs", tracked), tmp_path)

    sanitized = tmp_path / "compound-converted-rhs-sanitized.c"
    sanitized.write_text(emit_c(SANITIZED_CONVERTED_RHS_SOURCE))
    sanitized_build_and_run(
        sanitized,
        tmp_path / "python-compound-converted-rhs-sanitized",
        require_sanitizers(tmp_path),
    )


@pytest.mark.skipif(sys.platform == "win32", reason="requires a Unix C runtime")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_class_compound_fixture_is_strict_c11_warning_clean(
    tmp_path: Path,
    compound_fixture_c: Path,
    c_compiler: str,
) -> None:
    executable = tmp_path / "class-compound"
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(compound_fixture_c),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr

    executed = subprocess.run([executable], capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == "PASS: test_class_compound_assignment"
