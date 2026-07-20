"""Declaration-scope, ordering, provenance, and lifetime defaults."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import (
    compile_diagnostic_pair,
)
from src.tests.btrc.string_coercion_harness import compile_pair
from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _compiler_environment,
)
from src.tests.btrc.test_mutex_value_contract import (
    COMPILERS,
    REPO,
    _compile_pair,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")
DECLARATION_SCOPE = FIXTURES / "default_argument_declaration_scope_runtime.btrc"
BODYLESS_SCOPE = FIXTURES / "default_argument_bodyless_runtime.btrc"
BODYLESS_SHIM = FIXTURES / "default_argument_bodyless_shim.c"


def _strict_optimization_matrix(
    artifact,
    tmp_path: Path,
    *,
    optimizations=("-O0", "-O1", "-O2", "-O3"),
    extra_sources=(),
) -> None:
    frontend, generated = artifact
    for compiler in COMPILERS:
        for optimization in optimizations:
            executable = tmp_path / (f"{frontend}-{Path(compiler).name}-{optimization[1:]}")
            environment = _compiler_environment(compiler)
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    optimization,
                    str(generated),
                    *(str(source) for source in extra_sources),
                    "-pthread",
                    "-lm",
                    "-o",
                    str(executable),
                ],
                cwd=REPO,
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert build.returncode == 0, build.stderr
            run = subprocess.run(
                [str(executable)],
                cwd=REPO,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert run.returncode == 0, run.stderr


def test_defaults_use_declaration_scope_and_stable_operand_order(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        DECLARATION_SCOPE.read_text(),
        "default-argument-declaration-scope",
    )
    for artifact in compiled:
        emitted = artifact[1].read_text()
        assert "__btrc_default_" in emitted
        _strict_optimization_matrix(artifact, tmp_path)


def test_bodyless_declaration_defaults_run_in_declaration_scope(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        BODYLESS_SCOPE.read_text(),
        "default-argument-bodyless-scope",
    )
    for artifact in compiled:
        assert "__btrc_default_foreignDefault_1" in artifact[1].read_text()
        _strict_optimization_matrix(
            artifact,
            tmp_path,
            optimizations=("-O0", "-O3"),
            extra_sources=(BODYLESS_SHIM,),
        )


@pytest.mark.parametrize("keyword", ("self", "super"))
def test_constructor_defaults_reject_preallocation_receivers(
    semantic_btrcc: Path,
    tmp_path: Path,
    keyword: str,
) -> None:
    source = f"""
        class Parent {{ public int value; }}
        class Child extends Parent {{
            public Child(int value = {keyword}.value) {{ self.value = value; }}
        }}
        int main() {{ return 0; }}
    """
    for result in compile_diagnostic_pair(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode != 0
        assert f"Constructor defaults cannot reference '{keyword}' before allocation" in result.stderr


@pytest.mark.parametrize(
    "member, default",
    (
        ("public int field;", "field"),
        ("public int instanceValue() { return 1; }", "instanceValue()"),
        ("public int property { get { return 1; } }", "property"),
    ),
)
def test_constructor_defaults_reject_implicit_instance_members(
    semantic_btrcc: Path,
    tmp_path: Path,
    member: str,
    default: str,
) -> None:
    source = f"""
        class Example {{
            {member}
            public Example(int value = {default}) {{}}
        }}
        int main() {{ return 0; }}
    """
    for result in compile_diagnostic_pair(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode != 0
        assert (
            f"Constructor defaults cannot reference instance member "
            f"'{default.removesuffix('()')}' before allocation" in result.stderr
        )


@pytest.mark.parametrize(
    "source",
    (
        "class Example<T> { public T field; public Example(T value = field) {} } int main() { return 0; }",
        "class Parent { public int field; } "
        "class Example extends Parent { public Example(int value = field) {} } "
        "int main() { return 0; }",
    ),
)
def test_constructor_defaults_reject_generic_or_inherited_instance_members(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "Constructor defaults cannot reference instance member 'field' before allocation" in result.stderr


def test_context_sensitive_macro_defaults_fail_closed_transitively(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #define INNER __func__
        #define OUTER INNER
        const char* value(const char* name = OUTER) { return name; }
        int main() { return 0; }
    """
    for result in compile_diagnostic_pair(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode != 0
        assert "Source macro 'OUTER' cannot be used in a default argument" in result.stderr
        assert "context-sensitive predefined identifier" in result.stderr


def test_default_predefined_values_keep_imported_declaration_provenance(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "default_source.btrc"
    dependency.write_text(
        "const char* importedFile(const char* value = __FILE__) { return value; }\n"
        "int importedLine(int value = __LINE__) { return value; }\n"
    )
    expected_file = json.dumps(str(dependency.absolute()))
    source = f"""
        #include <assert.h>
        #include <string.h>
        #include "default_source.btrc"
        int main() {{
            assert(strcmp(importedFile(), {expected_file}) == 0);
            assert(importedLine() == 2);
            return 0;
        }}
    """
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "imported-default-provenance",
        include_stdlib=True,
    )
    for artifact in compiled:
        _strict_optimization_matrix(
            artifact,
            tmp_path,
            optimizations=("-O2",),
        )


def test_default_helper_namespace_is_unforgeable_and_targets_are_claimed(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    sources = (
        "int __btrc_default_choose_1() { return 0; } "
        "int choose(int value = 1) { return value; } int main() { return 0; }",
        "class Box { public int run(int value = 1) { return value; } } "
        "int Box_run(int value = 1) { return value; } int main() { return 0; }",
    )
    for source in sources:
        for result in compile_diagnostic_pair(
            semantic_btrcc,
            tmp_path,
            source,
        ):
            assert result.returncode != 0
            assert "__btrc_default_choose_1" in result.stderr or (
                "Box_run" in result.stderr and "collid" in result.stderr
            )
