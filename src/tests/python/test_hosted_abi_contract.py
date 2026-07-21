"""Canonical hosted-ABI model, provenance, and namespace contracts."""

import re
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ast_nodes import FunctionDecl
from src.compiler.python.cli_archive import _stamp_stdlib_declarations
from src.compiler.python.frontend import (
    lex_parse_frontend_source,
    resolve_frontend_source,
)
from src.compiler.python.gen_hosted_abi_btrc import render_files
from src.compiler.python.hosted_abi import (
    HOSTED_FUNCTIONS,
    HOSTED_TYPE_NAMES,
    HOSTED_TYPEDEF_NAMES,
    MUTATE,
    READ,
    hosted_function,
    hosted_macro_reference_requires_semantic_call,
    hosted_return_alias_parameter,
    hosted_return_deallocator,
    hosted_return_effect,
    hosted_source_helper_adopts_raw_string,
)
from src.compiler.python.hosted_abi_model import (
    CONSUME,
    DEALLOC_FREE,
    INT,
    RETURN_ALIAS,
    RETURN_FRESH,
    UNKNOWN,
    VALUE,
    VOID_PTR,
    HostedFunction,
    abi_type,
)
from src.compiler.python.hosted_abi_native import (
    HOSTED_NATIVE_FUNCTIONS,
    HOSTED_NATIVE_INTERNAL_NAMES,
)
from src.compiler.python.hosted_abi_runtime import SOURCE_RUNTIME_HELPERS
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.source_provenance import (
    compiler_stdlib_source,
    is_compiler_stdlib_source,
)

SOURCE_ROOT = Path(__file__).parents[2]


def _analyze(source: str):
    program = Parser(Lexer(source, "<hosted-abi>").tokenize()).parse()
    return Analyzer().analyze(program)


def test_registry_model_rejects_incoherent_effects() -> None:
    with pytest.raises(ValueError, match="effects must match"):
        HostedFunction(INT, (INT,), ())
    with pytest.raises(ValueError, match="unknown parameter effect"):
        HostedFunction(INT, (INT,), ("invented",))
    with pytest.raises(ValueError, match="requires exactly one alias"):
        HostedFunction(VOID_PTR, (VOID_PTR,), (READ,), return_effect=RETURN_ALIAS)
    with pytest.raises(ValueError, match="pointer parameter"):
        HostedFunction(
            VOID_PTR,
            (INT,),
            (READ,),
            return_effect=RETURN_ALIAS,
            return_alias_parameter=0,
        )
    with pytest.raises(ValueError, match="cannot consume a scalar"):
        HostedFunction(INT, (INT,), (CONSUME,), raw_lifetime=True)
    with pytest.raises(ValueError, match="requires a pointer result"):
        HostedFunction(INT, (), (), return_effect=RETURN_FRESH)


def test_registry_entries_obey_model_invariants() -> None:
    assert HOSTED_FUNCTIONS
    for spec in HOSTED_FUNCTIONS.values():
        if spec.parameters is not None:
            assert len(spec.parameters) == len(spec.effects)
        if spec.return_effect == RETURN_ALIAS:
            assert spec.return_alias_parameter is not None
        if spec.raw_lifetime:
            assert spec.effects.count(CONSUME) == 1


def test_exact_posix_effects_and_aliases_are_not_opaque() -> None:
    fchmod = hosted_function("fchmod")
    getcwd = hosted_function("getcwd")
    read = hosted_function("read")
    realpath = hosted_function("realpath")
    assert fchmod is not None and fchmod.result == INT
    assert fchmod.parameters == (INT, abi_type("mode_t"))
    assert fchmod.effects == (VALUE, VALUE)
    assert getcwd is not None and getcwd.effects == (MUTATE, VALUE)
    assert hosted_return_alias_parameter("getcwd") == 0
    assert hosted_return_effect("getcwd", alias_argument_is_null=True) == RETURN_FRESH
    assert hosted_return_deallocator("getcwd", alias_argument_is_null=True) == DEALLOC_FREE
    assert read is not None and read.effects == (VALUE, MUTATE, VALUE)
    assert realpath is not None and realpath.effects == (READ, MUTATE)
    assert hosted_return_alias_parameter("realpath") == 1


def test_freopen_models_path_borrows_stream_mutation_and_alias_result() -> None:
    freopen = hosted_function("freopen")
    assert freopen is not None
    assert freopen.effects == (READ, READ, MUTATE)
    assert hosted_return_alias_parameter("freopen") == 2
    assert hosted_return_effect("freopen") == RETURN_ALIAS


def test_rlimit_access_models_mutable_readback_and_read_only_update() -> None:
    getrlimit = hosted_function("getrlimit")
    setrlimit = hosted_function("setrlimit")

    assert getrlimit is not None and getrlimit.effects == (VALUE, MUTATE)
    assert setrlimit is not None and setrlimit.effects == (VALUE, READ)
    assert setrlimit.parameters is not None
    assert setrlimit.parameters[1].is_const


def test_macro_safety_predicate_fails_closed() -> None:
    assert not hosted_macro_reference_requires_semantic_call("strlen")
    assert hosted_macro_reference_requires_semantic_call("memset")
    assert hosted_macro_reference_requires_semantic_call("read")
    assert hosted_macro_reference_requires_semantic_call("printf")
    assert hosted_macro_reference_requires_semantic_call("strstr")


def test_hosted_type_namespace_contains_portable_and_platform_typedefs() -> None:
    assert {"FILE", "size_t", "pid_t"} <= HOSTED_TYPE_NAMES
    assert {"FILE", "size_t", "pid_t", "DIR"} <= HOSTED_TYPEDEF_NAMES
    assert "tm" in HOSTED_TYPE_NAMES
    assert "tm" not in HOSTED_TYPEDEF_NAMES


def test_every_shipped_native_source_prototype_has_an_exact_spec() -> None:
    declarations = {}
    for path in (SOURCE_ROOT / "stdlib").rglob("*.btrc"):
        program = Parser(Lexer(path.read_text(), str(path)).tokenize()).parse()
        for declaration in program.declarations:
            if (
                isinstance(declaration, FunctionDecl)
                and declaration.body is None
                and declaration.name.startswith("btrc_")
            ):
                declarations.setdefault(declaration.name, []).append(declaration)
    assert len(declarations) == 73
    assert declarations.keys() == HOSTED_NATIVE_FUNCTIONS.keys()
    analyzer = Analyzer()
    for name, variants in declarations.items():
        spec = HOSTED_NATIVE_FUNCTIONS[name]
        assert spec.parameters is not None
        assert spec.return_effect != "opaque" or spec.result.pointer_depth == 0
        for declaration in variants:
            assert analyzer._hosted_abi_type(declaration.return_type) == spec.result
            assert (
                tuple(analyzer._hosted_abi_type(parameter.type) for parameter in declaration.params) == spec.parameters
            )
            if name == "btrc_tray_take_command":
                assert declaration.return_type.base == "char"
                assert declaration.return_type.pointer_depth == 1
        if name.endswith("_destroy") or name == "btrc_gui_window_close":
            assert spec.raw_lifetime
            assert spec.consume_deallocator == name


def test_native_headers_are_exact_or_an_explicit_internal_seam() -> None:
    names = set()
    pattern = re.compile(r"\b(btrc_[A-Za-z0-9_]+)\s*\(")
    for directory in (
        SOURCE_ROOT / "stdlib" / "gpu",
        SOURCE_ROOT / "stdlib" / "gui",
        SOURCE_ROOT / "stdlib" / "tray",
    ):
        for path in directory.glob("*.h"):
            names.update(pattern.findall(path.read_text()))
    assert len(names) == 88
    assert names == set(HOSTED_NATIVE_FUNCTIONS) | set(HOSTED_NATIVE_INTERNAL_NAMES)
    assert len(HOSTED_NATIVE_INTERNAL_NAMES) == 15


def test_gpu_init_retained_window_effect_fails_closed() -> None:
    gpu_init = hosted_function("btrc_gpu_init")
    assert gpu_init is not None
    assert gpu_init.effects == (UNKNOWN,)


def test_gpu_bind_group_retained_buffer_handles_fail_closed() -> None:
    create_bind_group = hosted_function("btrc_gpu_create_bind_group")
    assert create_bind_group is not None
    assert create_bind_group.effects == (MUTATE, READ, UNKNOWN, VALUE)


def test_source_string_adopters_are_derived_from_the_canonical_registry() -> None:
    assert hosted_source_helper_adopts_raw_string("__btrc_str_track", 0)
    assert hosted_source_helper_adopts_raw_string("__btrc_string_adopt", 0)
    assert not hosted_source_helper_adopts_raw_string("__btrc_string_alloc", 0)
    assert not hosted_source_helper_adopts_raw_string("__btrc_str_track", 1)


def test_generated_registry_is_current_and_respects_file_caps() -> None:
    files = render_files()
    assert files
    for path, expected in files.items():
        assert path.read_text() == expected
        assert path.stat().st_mode & 0o777 == 0o644
        assert len(expected.splitlines()) <= 300


def test_source_runtime_helper_roots_are_generated_from_the_registry() -> None:
    files = render_files()
    generated_names = set()
    for path, source in files.items():
        if path.name.startswith("source_helper_"):
            generated_names.update(re.findall(r'name == "([^"]+)"', source))
    assert generated_names == SOURCE_RUNTIME_HELPERS

    source_runtime = (SOURCE_ROOT / "compiler" / "btrc" / "source_runtime_symbols.btrc").read_text()
    assert "hostedAbiSourceRuntimeHelperGenerated(name)" in source_runtime
    assert not any(name in source_runtime for name in SOURCE_RUNTIME_HELPERS)


def test_root_path_cannot_spoof_compiler_stdlib_provenance() -> None:
    stdlib_path = SOURCE_ROOT / "stdlib" / "process.btrc"
    source = '#include "process.btrc"\nextern char** environ;\nint main() { return 0; }'
    resolved = resolve_frontend_source(
        source,
        str(stdlib_path),
        include_stdlib=False,
    )
    parsed = lex_parse_frontend_source(resolved, "process.btrc", use_ast_cache=False)
    declaration = next(item for item in parsed.program.declarations if getattr(item, "name", "") == "environ")
    assert not is_compiler_stdlib_source(declaration.source_file)
    errors = Analyzer().analyze(parsed.program).errors
    assert any("environ" in error and "hosted C symbol" in error for error in errors)


def test_resolved_stdlib_import_receives_authenticated_provenance(tmp_path: Path) -> None:
    root = tmp_path / "main.btrc"
    source = "import std.process;\nint main() { return 0; }"
    resolved = resolve_frontend_source(source, str(root), include_stdlib=False)
    parsed = lex_parse_frontend_source(resolved, root.name, use_ast_cache=False)
    declaration = next(item for item in parsed.program.declarations if getattr(item, "name", "") == "environ")
    assert is_compiler_stdlib_source(declaration.source_file)


def test_exact_public_native_abi_has_one_authoritative_diagnostic() -> None:
    errors = _analyze("extern int btrc_gpu_available(); int main() { return 0; }").errors
    matching = [error for error in errors if "btrc_gpu_available" in error]
    assert len(matching) == 1
    assert "does not match compiler-owned C ABI 'bool (void)'" in matching[0]
    assert not _analyze("extern bool btrc_gpu_available(); int main() { return 0; }").errors


def test_hosted_function_definitions_are_mangled_source_shadows() -> None:
    source = "int memcpy(int value) { return value + 1; } int main() { return memcpy(41); }"
    analyzed = _analyze(source)
    assert not analyzed.errors
    assert analyzed.function_table["memcpy"].body is not None


def test_stdlib_cannot_take_hosted_lifetime_value_through_user_shadow() -> None:
    source = "void free(void* value) { (void)value; } void wrapper() { __fn_ptr<void, void*> sink = free; (void)sink; }"
    program = Parser(Lexer(source, "<hosted-value-shadow>").tokenize()).parse()
    source_free, stdlib_wrapper = program.declarations
    source_free.source_file = "<user>"
    stdlib_wrapper.source_file = compiler_stdlib_source()
    errors = Analyzer().analyze(program).errors
    assert any("Hosted lifetime function 'free' must be called directly" in error for error in errors)


def test_archive_stamps_nested_stdlib_declaration_provenance() -> None:
    source = "class Wrapper { public void inspect(void* value) { (void)value; } }"
    program = Parser(Lexer(source, "<archive-provenance>").tokenize()).parse()
    _stamp_stdlib_declarations(program)
    declaration = program.declarations[0]
    assert is_compiler_stdlib_source(declaration.source_file)
    assert is_compiler_stdlib_source(declaration.members[0].source_file)


def test_generated_enum_names_are_safe_but_anonymous_values_are_raw() -> None:
    assert not _analyze("enum Error { EINVAL = 1 }; int main() { return EINVAL; }").errors
    errors = _analyze("enum { EINVAL = 1 }; int main() { return EINVAL; }").errors
    assert any("EINVAL" in error and "hosted C symbol" in error for error in errors)
