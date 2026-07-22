"""Self-hosted parity for canonical recursive TypeExpr identity."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _strict_build_and_run,
)

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src" / "compiler" / "btrc"
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


def _struct_body(source: str, name: str) -> str:
    start = source.index(f"struct {name} {{")
    return source[start : source.index("};", start)]


def _build_driver(source: Path, output: Path, cache: Path) -> Path:
    generated = output.with_suffix(".c")
    transpile = _run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(source),
            "--no-cache",
            "-o",
            str(generated),
        ],
        env={**os.environ, "BTRC_CACHE_DIR": str(cache)},
        timeout=300,
    )
    assert transpile.returncode == 0 and generated.exists(), transpile.stderr
    compile_result = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(output),
            "-lm",
            "-lpthread",
        ],
        timeout=300,
    )
    assert compile_result.returncode == 0 and output.exists(), compile_result.stderr
    return output


@pytest.fixture(scope="module")
def identity_driver(tmp_path_factory) -> Path:
    output = tmp_path_factory.mktemp("selfhost-type-identity")
    return _build_driver(
        REPO / "src/tests/btrc/fixtures/type_identity_driver.btrc",
        output / "identity",
        output / "cache",
    )


@pytest.fixture(scope="module")
def selfhost_compiler(tmp_path_factory) -> Path:
    output = tmp_path_factory.mktemp("selfhost-type-identity-compiler")
    return _build_driver(
        SELFHOST / "btrcc_main.btrc",
        output / "btrcc",
        output / "cache",
    )


def test_identity_contract_has_one_shared_implementation() -> None:
    lexer_stage = (SELFHOST / "lexer/stage.btrc").read_text()
    parser_stage = (SELFHOST / "parser/stage.btrc").read_text()
    analyzer_stage = (SELFHOST / "analyzer/stage.btrc").read_text()
    identity = (SELFHOST / "type_identity.btrc").read_text()
    analyzer = (SELFHOST / "analyzer.btrc").read_text()
    generator = (SELFHOST / "irgen.btrc").read_text()

    assert '#include "../type_identity.btrc"' in lexer_stage
    assert "import ../frontend/stage.btrc;" in parser_stage
    assert "import ../parser/stage.btrc;" in analyzer_stage
    assert "TypeIdentity.mangleGenericType(" in generator
    assert "mangleGenericType(" not in generator.replace(
        "TypeIdentity.mangleGenericType(",
        "",
    )
    assert "string mangleTypeName(" not in generator
    assert "class TypeIdentity {" in identity
    assert "class TypeComposition {" in identity
    for contract in (
        "class string shapeKey(",
        "class string genericInstanceKey(",
        "class bool referencesNames(",
        'return "ZQt" + TypeIdentity.encode(typeExpr);',
        'return "btrc_ZQg" + TypeIdentity.encodeNameAndTypes(base, args);',
        'return "btrc_ZQm" + payload;',
        'return "__btrc_fn_ZQf" + TypeIdentity.encodeTypes(args);',
        "class int qualifierBits(",
        "class bool resolvedReferenceShape(",
        "class int appliedSubstitutionPointerDepth(",
        "class int substitutionPointerDepth(",
        "class Node compose(",
        "class bool isSemanticScalarString(",
    ):
        assert contract in identity
    pointer = identity.index('component = component + "_p"')
    nullable = identity.index('component = component + "_n"')
    array = identity.index('component = component + "_a"')
    assert pointer < nullable < array
    assert "TypeIdentity.genericInstanceKey(base, t.generic_args)" in analyzer
    assert "TypeIdentity.methodInstanceKey(" in analyzer
    assert "TypeIdentity.referencesNames(t, unresolved)" in analyzer
    assert "isConcreteType" not in analyzer
    assert "nested array composition for type parameter" in analyzer
    assert "resolved, analyzed.typedefTable" in analyzer
    assert "genericSubstitutionReferenceShape" in analyzer
    assert "return TypeComposition.compose(t, resolved," in analyzer


def test_identity_atoms_run_under_strict_c11(identity_driver) -> None:
    result = _run([str(identity_driver)], timeout=30)

    assert result.returncode == 0
    assert result.stdout == "PASS: type_identity_driver\n"
    assert result.stderr == ""


INVALID_SPECIALIZATIONS = [
    (
        """
        class Box<T> { public T value; }
        int main() { Box<const int> invalid; return 0; }
        """,
        "cannot be const-qualified",
    ),
    (
        """
        class Box<T> { public T value; }
        int main() { Box<static int> invalid; return 0; }
        """,
        "cannot be static-qualified",
    ),
    (
        """
        class Box<T> { public T value; }
        int main() { Box<extern int> invalid; return 0; }
        """,
        "cannot be extern-qualified",
    ),
    (
        """
        class Box<T> { public T value; }
        int main() { Box<volatile int> invalid; return 0; }
        """,
        "cannot be volatile-qualified",
    ),
    (
        """
        class Buffer<T> { public T[] data; }
        int main() { Buffer<int[]> invalid; return 0; }
        """,
        "nested array composition",
    ),
    (
        """
        class Box<T> { public T value; }
        class Envelope<T> { public Box<const T> value; }
        int main() { Envelope<int> invalid; return 0; }
        """,
        "cannot be const-qualified",
    ),
    (
        """
        class Picker {
            public U identity<U>(U value) { return value; }
        }
        int main() {
            Picker picker = Picker();
            const int value = 7;
            picker.identity(value);
            return 0;
        }
        """,
        "cannot be const-qualified",
    ),
]


@pytest.mark.parametrize("source, expected", INVALID_SPECIALIZATIONS)
def test_writable_specializations_fail_closed(
    selfhost_compiler,
    tmp_path: Path,
    source: str,
    expected: str,
) -> None:
    program = tmp_path / "invalid_identity.btrc"
    program.write_text(source)
    result = _run(
        [str(selfhost_compiler), "--no-stdlib", "--no-dce", str(program)],
        timeout=30,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert expected in result.stderr.lower()


def test_structural_qualified_types_remain_allowed(
    selfhost_compiler,
    tmp_path: Path,
) -> None:
    program = tmp_path / "structural_identity.btrc"
    program.write_text("""
        void consume(__fn_ptr<void, const int> callback,
                     Tuple<const int, int> values) {}
        int main() { return 0; }
    """)
    result = _run(
        [str(selfhost_compiler), "--no-stdlib", "--no-dce", str(program)],
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "__btrc_fn_ZQf" in result.stdout
    assert "btrc_ZQg" in result.stdout


def test_declared_one_letter_class_does_not_capture_template_parameter(
    selfhost_compiler,
) -> None:
    program = REPO / "src/tests/btrc/fixtures/type_identity_declared_t.btrc"
    result = _run(
        [str(selfhost_compiler), "--no-stdlib", str(program)],
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "btrc_Inner_int" in result.stdout
    assert "btrc_Inner_T" not in result.stdout


def test_nullable_generic_substitution_has_dual_runtime_parity(
    selfhost_compiler,
    tmp_path: Path,
) -> None:
    program = REPO / "src/tests/btrc/fixtures/nullable_generic_substitution_runtime.btrc"
    source = program.read_text()
    selfhost = _run(
        [str(selfhost_compiler), "--no-stdlib", str(program)],
        timeout=30,
    )
    reference, reference_source = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    selfhost_source = tmp_path / "selfhost-nullable-substitution.c"
    selfhost_source.write_text(selfhost.stdout)
    for generated in (selfhost_source, reference_source):
        emitted = generated.read_text()
        assert "struct btrc_Maybe_Item_p1" in emitted
        assert "Item* stored;" in emitted
        assert "char* stored;" in emitted
        assert "int* stored;" in emitted
        assert ".destroy = Alias_destroy" not in emitted
        assert ".destroy = AliasChain_destroy" not in emitted
        for alias in ("Alias", "AliasChain", "TextAlias", "RawPointer", "NullableInt", "IntArray"):
            body = _struct_body(emitted, f"btrc_Empty_{alias}")
            assert f"{alias} stored;" in body
            assert f"{alias}* stored;" not in body
    _strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-nullable-substitution",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-nullable-substitution",
    )
