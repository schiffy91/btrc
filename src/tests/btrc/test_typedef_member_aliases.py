"""Self-host/reference parity for typedef-based member dispatch and ARC."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.dual_frontend_harness import compile_ownership_reference
from src.tests.btrc.selfhost_snippet_harness import compile_source, strict_build_and_run

FIXTURE = Path(__file__).with_name("fixtures") / "TypedefMemberAliasRuntime.btrc"


def test_alias_member_dispatch_and_scope_cleanup_have_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = FIXTURE.read_text()
    selfhost, selfhost_source = compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = compile_ownership_reference(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    reference_c = reference_source.read_text()
    assert "BoxAlias box = Box_new(10);" in reference_c
    assert "CellAlias cell = btrc_Cell_int_new(5);" in reference_c
    strict_build_and_run(selfhost_source, tmp_path / "selfhost-typedef-members")
    strict_build_and_run(reference_source, tmp_path / "reference-typedef-members")


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            "class Vault { private int secret; } typedef Vault Alias; int read(Alias value) { return value.secret; }",
            "private field 'secret'",
        ),
        (
            "class Vault { private int secret { get; set; } } typedef Vault Alias; "
            "int read(Alias value) { return value.secret; }",
            "private property 'secret'",
        ),
        (
            "class Accessors { public int readOnly { get; } } typedef Accessors Alias; "
            "void write(Alias value) { value.readOnly = 1; }",
            "has no setter",
        ),
        (
            "class Accessors { public int writeOnly { set; } } typedef Accessors Alias; "
            "int read(Alias value) { return value.writeOnly; }",
            "has no getter",
        ),
        (
            "class Accessors { public int writeOnly { set; } } typedef Accessors Alias; "
            "void update(Alias value) { value.writeOnly += 1; }",
            "has no getter",
        ),
        (
            "class Slots { public int get(string key) { return 0; } } typedef Slots Alias; "
            "int read(Alias value) { return value[1]; }",
            "string",
        ),
        (
            "class Vault { private int reveal() { return 1; } } typedef Vault Alias; "
            "int read(Alias value) { return value.reveal(); }",
            "private method 'reveal'",
        ),
    ),
)
def test_alias_member_diagnostics_have_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = compile_ownership_reference(tmp_path, source)

    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr.lower()
    assert diagnostic in reference.stderr.lower()
