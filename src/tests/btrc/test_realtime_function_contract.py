"""Proof-carrying RealtimeFunction frontend and C-ABI parity."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).with_name("fixtures") / "RealtimeFunction.btrc"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _reference(source: Path, output: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(source), "--no-stdlib", "--no-cache", "-o", str(output)],
        cwd=REPOSITORY,
        env={**os.environ, "BTRC_CACHE_DIR": str(cache)},
        capture_output=True,
        text=True,
        timeout=120,
    )


def _selfhost(compiler: Path, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    compiled = subprocess.run(
        [str(compiler), "--no-stdlib", str(source)],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if compiled.returncode == 0:
        output.write_text(compiled.stdout)
    return compiled


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
def test_realtime_function_preserves_proof_through_typed_storage_and_one_way_downgrade(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    generated = {
        "reference": tmp_path / "RealtimeFunctionReference.c",
        "selfhost": tmp_path / "RealtimeFunctionSelfhost.c",
    }
    reference = _reference(FIXTURE, generated["reference"], tmp_path / "reference-cache")
    selfhost = _selfhost(semantic_btrcc, FIXTURE, generated["selfhost"])
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    for emitted in (generated["reference"].read_text(), generated["selfhost"].read_text()):
        assert "__realtime_fn_ptr" not in emitted
        assert "typedef RealtimeFunction" not in emitted
        assert "typedef int (*__btrc_fn_int_int)(int);" in emitted
        assert "typedef __btrc_fn_int_int ProvenTransform;" in emitted
    for frontend, source in generated.items():
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"RealtimeFunction-{frontend}-{Path(compiler).name}"
            built = subprocess.run(
                [compiler, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2", str(source), "-o", str(executable)],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert built.returncode == 0, built.stderr
            run = subprocess.run([str(executable)], cwd=REPOSITORY, capture_output=True, text=True, timeout=30)
            assert run.returncode == 0, run.stderr
            assert run.stdout == "PASS RealtimeFunction\n"
            assert run.stderr == ""


@pytest.mark.parametrize(
    ("declarations", "statement", "expected"),
    (
        (
            "int ordinary(int value) { return value; }",
            "ProvenTransform proof = ordinary;",
            "RealtimeFunction value must be a direct named @realtime function or an exact RealtimeFunction copy",
        ),
        (
            "@realtime int safe(int value) { return value; }",
            "CFunction<int, int> ordinary = safe; ProvenTransform proof = ordinary;",
            "RealtimeFunction value must be a direct named @realtime function or an exact RealtimeFunction copy",
        ),
        (
            "@realtime int safe(int value) { return value; }",
            "ProvenTransform proof = (ProvenTransform)safe;",
            "RealtimeFunction cannot be created by a cast",
        ),
        (
            "",
            "ProvenTransform proof = (int value) => value;",
            "RealtimeFunction value must be a direct named @realtime function or an exact RealtimeFunction copy",
        ),
        (
            "@realtime int safe(int value) { return value; }\nstruct Slot { ProvenTransform proof; };",
            "CFunction<int, int> ordinary = safe; struct Slot slot = {ordinary};",
            "RealtimeFunction value must be a direct named @realtime function or an exact RealtimeFunction copy",
        ),
        (
            "ProvenTransform nativeFactory();",
            "",
            "Native function declaration 'nativeFactory' cannot expose RealtimeFunction",
        ),
        (
            "@realtime int unsafeTransform(int value) { printf(\"%d\", value); return value; }",
            "ProvenTransform proof = unsafeTransform;",
            "forbidden strings operation 'string value'",
        ),
        (
            "",
            "ProvenTransform proof = null;",
            "RealtimeFunction value must be a direct named @realtime function or an exact RealtimeFunction copy",
        ),
        (
            "@realtime int safe(int value) { return value; }",
            "ProvenTransform proofs[1] = {safe};",
            "RealtimeFunction must be one direct, unqualified proof-carrying function pointer",
        ),
        (
            "@realtime int safe(int value) { return value; }\nstruct Slot { ProvenTransform proof; };",
            "struct Slot slot = {safe}; CFunction<int, int> ordinary = safe; slot.proof = ordinary;",
            "RealtimeFunction value must be a direct named @realtime function or an exact RealtimeFunction copy",
        ),
        (
            "ProvenTransform nativeTransform(ProvenTransform input);",
            "",
            "Native function declaration 'nativeTransform' cannot expose RealtimeFunction",
        ),
        (
            "abstract class Foreign { static abstract ProvenTransform make(); }",
            "",
            "Bodyless method 'Foreign.make' cannot expose RealtimeFunction",
        ),
        (
            "interface ForeignFactory { ProvenTransform make(); }",
            "",
            "Interface method 'ForeignFactory.make' cannot expose RealtimeFunction",
        ),
        (
            "class Fabricator<T> { public T fabricate(CFunction<int, int> value) { return value; } }",
            "Fabricator<ProvenTransform> fabricator = new Fabricator<ProvenTransform>(); "
            "CFunction<int, int> ordinary = null; ProvenTransform proof = fabricator.fabricate(ordinary);",
            "Return type mismatch: expected 'T' but got 'CFunction<int, int>'",
        ),
    ),
    ids=(
        "ordinary-root",
        "upgrade",
        "cast",
        "lambda",
        "aggregate-field",
        "native-return",
        "unsafe-root",
        "null",
        "array",
        "field-upgrade",
        "native-parameter",
        "bodyless-method",
        "interface-method",
        "generic-laundering",
    ),
)
def test_realtime_function_rejects_every_unproven_construction_path(
    semantic_btrcc: Path,
    tmp_path: Path,
    declarations: str,
    statement: str,
    expected: str,
) -> None:
    source = tmp_path / "UnprovenRealtimeFunction.btrc"
    source.write_text(
        f"typedef RealtimeFunction<int, int> ProvenTransform;\n{declarations}\n"
        f"int main() {{ {statement} return 0; }}\n"
    )
    reference = _reference(source, tmp_path / "reference.c", tmp_path / "reference-cache")
    selfhost = _selfhost(semantic_btrcc, source, tmp_path / "selfhost.c")
    assert reference.returncode == 1
    assert selfhost.returncode == 1
    assert expected in reference.stderr
    assert expected in selfhost.stderr


def test_realtime_function_allows_only_inert_zero_initialization(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "EmptyRealtimeFunctionSlot.btrc"
    source.write_text(
        "typedef RealtimeFunction<int, int> ProvenTransform;\n"
        "struct Slot { ProvenTransform proof; bool occupied; };\n"
        "int main() { struct Slot slot = {}; return slot.occupied ? 1 : 0; }\n"
    )
    reference = _reference(source, tmp_path / "reference.c", tmp_path / "reference-cache")
    selfhost = _selfhost(semantic_btrcc, source, tmp_path / "selfhost.c")
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
def test_realtime_function_vector_storage_preserves_proof_and_cannot_upgrade(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "RealtimeFunctionVector.btrc"
    source.write_text(
        "import std.vector;\n"
        "typedef RealtimeFunction<int, int> ProvenTransform;\n"
        "@realtime int increment(int value) { return value + 1; }\n"
        "@realtime int invoke(ProvenTransform transform, int value) { return transform(value); }\n"
        "int main() {\n"
        "\tVector<ProvenTransform> routes = new Vector<ProvenTransform>();\n"
        "\troutes.push(increment);\n"
        "\tProvenTransform recovered = routes.get(0);\n"
        "\treturn invoke(recovered, 6) == 7 ? 0 : 1;\n"
        "}\n"
    )
    generated = (tmp_path / "vector-reference.c", tmp_path / "vector-selfhost.c")
    reference = _reference(source, generated[0], tmp_path / "reference-cache")
    selfhost = _selfhost(semantic_btrcc, source, generated[1])
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    for frontend, emitted in (("reference", generated[0]), ("selfhost", generated[1])):
        executable = tmp_path / f"vector-{frontend}"
        built = subprocess.run(
            [STRICT_COMPILERS[0], "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2", str(emitted), "-o", str(executable)],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert built.returncode == 0, built.stderr
        run = subprocess.run([str(executable)], cwd=REPOSITORY, capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stderr

    rejected = tmp_path / "RealtimeFunctionVectorUpgrade.btrc"
    rejected.write_text(
        "import std.vector;\n"
        "typedef RealtimeFunction<int, int> ProvenTransform;\n"
        "@realtime int increment(int value) { return value + 1; }\n"
        "int main() {\n"
        "\tVector<CFunction<int, int>> routes = new Vector<CFunction<int, int>>();\n"
        "\troutes.push(increment);\n"
        "\tProvenTransform upgraded = routes.get(0);\n"
        "\treturn 0;\n"
        "}\n"
    )
    expected = "RealtimeFunction value must be a direct named @realtime function or an exact RealtimeFunction copy"
    reference_rejected = _reference(rejected, tmp_path / "rejected-reference.c", tmp_path / "rejected-cache")
    selfhost_rejected = _selfhost(semantic_btrcc, rejected, tmp_path / "rejected-selfhost.c")
    assert reference_rejected.returncode == 1
    assert selfhost_rejected.returncode == 1
    assert expected in reference_rejected.stderr
    assert expected in selfhost_rejected.stderr
