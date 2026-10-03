"""Canonical hosted-ABI model, provenance, and namespace contracts."""

import copy
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from src.compiler.python.abi import generated as generated_abi
from src.compiler.python.abi.declarations import (
    CONSUME,
    DEALLOC_FREE,
    MUTATE,
    READ,
    RETURN_ALIAS,
    RETURN_FRESH,
    UNKNOWN,
    VALUE,
    AbiType,
    HostedFunction,
)
from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.types import CIntegerWidths
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.packages import PackageTarget
from src.compiler.python.frontend.sources import CompilerStdlibSource, StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog
from src.compiler.python.syntax.ast.generated import FunctionDecl, TypedefDecl
from src.tests.c_toolchains import host_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TRANSPILE_TIMEOUT
from tools.compiler_codegen.hosted_abi import (
    HostedAbiCatalogGenerator,
    HostedAbiManifest,
    HostedAbiManifestError,
    TargetManifest,
    TargetUnion,
)
from tools.compiler_codegen.runtime import RuntimeManifest

SOURCE_ROOT = Path(__file__).parents[2]
REPOSITORY_ROOT = SOURCE_ROOT.parent
INT = AbiType("int")
VOID_PTR = AbiType("void", 1)
HOSTED_FUNCTIONS = HOSTED_ABI.functions
HOSTED_TYPE_NAMES = HOSTED_ABI.types
HOSTED_TYPEDEF_NAMES = HOSTED_ABI.typedefs
HOSTED_NATIVE_FUNCTIONS = {name: HOSTED_ABI.functions[name] for name in HOSTED_ABI.native_names}
HOSTED_NATIVE_INTERNAL_NAMES = HOSTED_ABI.native_internal_names
SOURCE_RUNTIME_HELPERS = RuntimeHelperCatalog().source_visible_names
hosted_function = HOSTED_ABI.function
hosted_macro_reference_requires_semantic_call = HOSTED_ABI.macro_reference_requires_semantic_call
hosted_return_alias_parameter = HOSTED_ABI.return_alias_parameter
hosted_return_deallocator = HOSTED_ABI.return_deallocator
hosted_return_effect = HOSTED_ABI.return_effect
hosted_source_helper_adopts_raw_string = HOSTED_ABI.source_helper_adopts_raw_string
abi_type = AbiType


def _analyze(source: str):
    program = Parser(Lexer(source, "<hosted-abi>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


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


def test_qsort_and_bsearch_have_exact_nonescaping_callback_abis() -> None:
    callback = abi_type(
        "CFunction",
        generic_args=(
            abi_type("int"),
            abi_type("void", 1, True),
            abi_type("void", 1, True),
        ),
    )
    qsort = hosted_function("qsort")
    bsearch = hosted_function("bsearch")

    assert qsort is not None
    assert qsort.parameters == (VOID_PTR, abi_type("size_t"), abi_type("size_t"), callback)
    assert qsort.effects == (MUTATE, VALUE, VALUE, VALUE)
    assert qsort.callback_lifetimes == (None, None, None, "during_call")

    assert bsearch is not None
    assert bsearch.parameters == (
        abi_type("void", 1, True),
        abi_type("void", 1, True),
        abi_type("size_t"),
        abi_type("size_t"),
        callback,
    )
    assert bsearch.callback_lifetimes[-1] == "during_call"
    assert hosted_return_alias_parameter("bsearch") == 1


def test_stored_callback_lifetime_is_explicit_and_cannot_be_marked_realtime_safe() -> None:
    runtime = RuntimeManifest.load(SOURCE_ROOT / "runtime/c/manifest.toml")
    manifest = HostedAbiManifest.load(SOURCE_ROOT / "language/hosted_abi.toml", runtime)
    qsort = next(function for function in manifest.functions if function.name == "qsort")
    callback_index = len(qsort.parameters) - 1
    stored_parameters = tuple(
        replace(parameter, callback_lifetime="stored_until_unregister") if index == callback_index else parameter
        for index, parameter in enumerate(qsort.parameters)
    )

    HostedAbiManifest._validate_function(replace(qsort, parameters=stored_parameters))
    with pytest.raises(HostedAbiManifestError, match="unknown callback lifetime"):
        invalid_parameters = tuple(
            replace(parameter, callback_lifetime="until_magic") if index == callback_index else parameter
            for index, parameter in enumerate(qsort.parameters)
        )
        HostedAbiManifest._validate_function(replace(qsort, parameters=invalid_parameters))
    with pytest.raises(HostedAbiManifestError, match="callback call-graph proof is unavailable"):
        HostedAbiManifest._validate_function(replace(qsort, realtime_effect="safe"))


def test_cfunction_is_public_syntax_for_one_word_noncapturing_callback() -> None:
    source = """
        int compare(const void* left, const void* right) { return 0; }
        int main() {
            CFunction<int, const void*, const void*> callback = compare;
            return 0;
        }
    """
    program = Parser(Lexer(source, "<cfunction>").tokenize()).parse()
    callback = program.declarations[1].body.statements[0]
    assert callback.type.base == "__fn_ptr"
    assert not _analyze(source).errors


@pytest.mark.parametrize(
    "declaration",
    (
        "int compare(const void* value) { return 0; }",
        "void compare(const void* left, const void* right) {}",
        "int compare(void* left, void* right) { return 0; }",
    ),
)
def test_qsort_rejects_wrong_callback_arity_result_and_qualifiers(declaration: str) -> None:
    source = f"""
        {declaration}
        int main() {{
            int values[2] = {{2, 1}};
            qsort(values, 2, sizeof(int), compare);
            return 0;
        }}
    """
    errors = _analyze(source).errors
    assert any("Argument 4 to hosted function 'qsort()' expects" in error and "CFunction" in error for error in errors)


def test_qsort_rejects_capturing_lambda_callback() -> None:
    errors = _analyze("""
        int main() {
            int values[2] = {2, 1};
            int direction = 1;
            qsort(values, 2, sizeof(int),
                (const void* left, const void* right) => direction);
            return 0;
        }
    """).errors
    assert any("capturing lambda" in error.lower() for error in errors)


def test_qsort_exact_bodyless_declaration_uses_cfunction_spelling() -> None:
    good = """
        extern void qsort(void* base, size_t count, size_t size,
            CFunction<int, const void*, const void*> compare);
        int main() { return 0; }
    """
    bad = good.replace("const void*, const void*", "void*, void*")
    assert not _analyze(good).errors
    assert any("does not match compiler-owned C ABI" in error for error in _analyze(bad).errors)


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
    typedefs = {}
    for path in (SOURCE_ROOT / "stdlib").rglob("*.btrc"):
        program = Parser(Lexer(path.read_text(), str(path)).tokenize()).parse()
        for declaration in program.declarations:
            if isinstance(declaration, TypedefDecl):
                typedefs[declaration.alias] = declaration.original
            if (
                isinstance(declaration, FunctionDecl)
                and declaration.body is None
                and declaration.name.startswith(("btrc_", "std_"))
            ):
                declarations.setdefault(declaration.name, []).append(declaration)
    assert declarations.keys() == HOSTED_NATIVE_FUNCTIONS.keys()
    analyzer = SemanticAnalyzer()
    analyzer.index.typedef_table.update(typedefs)
    for name, variants in declarations.items():
        spec = HOSTED_NATIVE_FUNCTIONS[name]
        assert spec.parameters is not None
        assert spec.return_effect != "opaque" or spec.result.pointer_depth == 0
        for declaration in variants:
            assert analyzer.declarations.hosted_abi_type(declaration.return_type) == spec.result
            assert (
                tuple(analyzer.declarations.hosted_abi_type(parameter.type) for parameter in declaration.params)
                == spec.parameters
            )
        if name.startswith("btrc_") and name.endswith("_destroy"):
            assert spec.raw_lifetime
            assert spec.consume_deallocator == name
        if name.startswith("std_"):
            assert not spec.raw_lifetime


def test_native_headers_are_exact_or_an_explicit_internal_seam() -> None:
    names = set()
    pattern = re.compile(r"\b((?:btrc|std)_[A-Za-z0-9_]+)\s*\(")
    stdlib = SOURCE_ROOT / "stdlib"
    headers = [path for path in stdlib.rglob("*.h") if path.relative_to(stdlib).parts[0] != "Windows"]
    headers += sorted((SOURCE_ROOT / "runtime" / "gpu").glob("*.h"))
    for path in headers:
        names.update(pattern.findall(path.read_text()))
    assert names == set(HOSTED_NATIVE_FUNCTIONS) | set(HOSTED_NATIVE_INTERNAL_NAMES)


def test_native_thread_boundary_is_exact() -> None:
    invoke = hosted_function("__btrc_native_thread_invoke")
    assert hosted_function("std_background_jobs_submit") is None
    assert invoke is not None and invoke.parameters is not None
    assert invoke.parameters[0] == abi_type("CFunction", generic_args=(INT, VOID_PTR))
    assert invoke.callback_lifetimes == ("during_call", None, None)


def test_local_application_channel_effects_are_exact() -> None:
    request = hosted_function("std_local_application_channel_request")
    poll = hosted_function("std_local_application_channel_server_poll")
    close = hosted_function("std_local_application_channel_server_close")

    assert request is None
    assert poll is None
    assert close is None


def test_gpu_compute_abi_is_private() -> None:
    assert hosted_function("btrc_gpu_init") is None
    assert "btrc_gpu_acquire_compute" not in HOSTED_NATIVE_FUNCTIONS
    assert "btrc_gpu_acquire_compute" in HOSTED_NATIVE_INTERNAL_NAMES


def test_gpu_bind_group_retained_buffer_handles_fail_closed() -> None:
    create_bind_group = hosted_function("btrc_gpu_create_bind_group")
    assert create_bind_group is not None
    assert create_bind_group.effects == (MUTATE, READ, UNKNOWN, VALUE)


def test_source_string_adopters_are_derived_from_the_canonical_registry() -> None:
    assert hosted_source_helper_adopts_raw_string("__btrc_string_adopt", 0)
    assert not hosted_source_helper_adopts_raw_string("__btrc_string_alloc", 0)
    assert not hosted_source_helper_adopts_raw_string("__btrc_string_adopt", 1)
    assert not hosted_source_helper_adopts_raw_string("__btrc_str_track", 0)


def test_generated_registry_is_current_and_has_one_domain_owner() -> None:
    runtime = RuntimeManifest.load(SOURCE_ROOT / "runtime/c/manifest.toml")
    manifest = HostedAbiManifest.load(SOURCE_ROOT / "language/hosted_abi.toml", runtime)
    targets = TargetManifest.load(SOURCE_ROOT / "language/targets.toml", manifest)
    artifacts = HostedAbiCatalogGenerator(manifest, targets).artifacts()
    artifact = next(item for item in artifacts if item.path.suffix == ".btrc")
    path = REPOSITORY_ROOT.joinpath(*artifact.path.parts)
    expected = artifact.content.decode()
    assert path.name == "Tables.btrc"
    assert path.read_text() == expected
    assert "class GeneratedHostedAbiData" in expected
    assert '#include "' not in expected


def test_source_runtime_helper_roots_are_generated_from_the_registry() -> None:
    runtime = RuntimeManifest.load(SOURCE_ROOT / "runtime/c/manifest.toml")
    manifest = HostedAbiManifest.load(SOURCE_ROOT / "language/hosted_abi.toml", runtime)
    generated_names = {function.name for function in manifest.functions if function.origin == "runtime"}
    assert generated_names == SOURCE_RUNTIME_HELPERS

    source_runtime = (SOURCE_ROOT / "compiler/btrc/analyzer/HostedAbi.btrc").read_text()
    assert "class SourceRuntimeSymbols" in source_runtime
    assert not any(name in source_runtime for name in SOURCE_RUNTIME_HELPERS)


def test_root_path_cannot_spoof_compiler_stdlib_provenance(tmp_path: Path) -> None:
    # Exercise the actual configured stdlib root without publishing a package
    # lock into the checkout (or an immutable installed compiler directory).
    library = tmp_path / "stdlib"
    shutil.copytree(SOURCE_ROOT / "stdlib", library, ignore=shutil.ignore_patterns("btrc.lock"))
    stdlib_path = library / "Process.btrc"
    source = '#include "Process.btrc"\nextern char** environ;\nint main() { return 0; }'
    pipeline = CompilationPipeline(frontend=FrontendStage(StdlibRepository(directory=str(library))))
    options = CompilerOptions(include_stdlib=False, use_ast_cache=False)
    resolved = pipeline.resolve(
        source,
        str(stdlib_path),
        options,
    )
    parsed = pipeline.parse(resolved, "Process.btrc", options)
    declaration = next(item for item in parsed.program.declarations if getattr(item, "name", "") == "environ")
    assert not CompilerStdlibSource.authenticated(declaration.source_file)
    errors = SemanticAnalyzer().analyze(parsed.program).errors
    assert any("environ" in error and "hosted C symbol" in error for error in errors)


def test_resolved_stdlib_import_receives_authenticated_provenance(tmp_path: Path) -> None:
    root = tmp_path / "Main.btrc"
    source = "import Library.Process;\nint main() { return 0; }"
    pipeline = CompilationPipeline()
    options = CompilerOptions(include_stdlib=False, use_ast_cache=False)
    resolved = pipeline.resolve(source, str(root), options)
    parsed = pipeline.parse(resolved, root.name, options)
    declaration = next(item for item in parsed.program.declarations if getattr(item, "name", "") == "environ")
    assert CompilerStdlibSource.authenticated(declaration.source_file)


def test_exact_public_native_abi_has_one_authoritative_diagnostic() -> None:
    errors = _analyze("extern int btrc_gpu_available(); int main() { return 0; }").errors
    matching = [error for error in errors if "btrc_gpu_available" in error]
    assert len(matching) == 1
    assert "does not match compiler-owned C ABI" in matching[0]
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
    stdlib_wrapper.source_file = CompilerStdlibSource()
    errors = SemanticAnalyzer().analyze(program).errors
    assert any("Hosted lifetime function 'free' must be called directly" in error for error in errors)


def test_stdlib_source_owner_stamps_nested_declaration_provenance() -> None:
    source = "class Wrapper { public void inspect(void* value) { (void)value; } }"
    program = Parser(Lexer(source, "<archive-provenance>").tokenize()).parse()
    for declaration in program.declarations:
        declaration.source_file = CompilerStdlibSource()
        CompilerStdlibSource.stamp_nested(declaration)
    declaration = program.declarations[0]
    assert CompilerStdlibSource.authenticated(declaration.source_file)
    assert CompilerStdlibSource.authenticated(declaration.members[0].source_file)


def test_generated_enum_names_are_safe_but_anonymous_values_are_raw() -> None:
    assert not _analyze("enum Error { EINVAL = 1 }; int main() { return EINVAL; }").errors
    errors = _analyze("enum { EINVAL = 1 }; int main() { return EINVAL; }").errors
    assert any("EINVAL" in error and "hosted C symbol" in error for error in errors)


# The compilation-target spec (src/language/targets.toml, PLAN.md D21) and its
# generated rows: docs/design/c-preprocessor-conditionals.md, "Shared owners".

TARGET_SPEC = SOURCE_ROOT / "language/targets.toml"


def _target_document() -> dict:
    return tomllib.loads(TARGET_SPEC.read_text())


def _hosted_manifest() -> HostedAbiManifest:
    runtime = RuntimeManifest.load(SOURCE_ROOT / "runtime/c/manifest.toml")
    return HostedAbiManifest.load(SOURCE_ROOT / "language/hosted_abi.toml", runtime)


def _macro(document: dict, name: str) -> dict:
    return next(row for row in document["predefined_macros"] if row["name"] == name)


def _duplicate_target(document: dict) -> None:
    document["targets"].append(dict(document["targets"][0]))


def _overlapping_rows(document: dict) -> None:
    document["predefined_macros"].append({"name": "__linux__", "value": 2, "architectures": ["aarch64"]})


TARGET_RULE_VIOLATIONS = {
    "schema": (lambda document: document.update(schema_version=2), "unsupported target spec schema version"),
    "unknown-key": (lambda document: document.update(environments=[]), "unknown target spec keys: environments"),
    "duplicate-target": (_duplicate_target, "target 'linux-x86_64' appears more than once"),
    "unknown-os": (
        lambda document: _macro(document, "__linux__").update(operating_systems=["ios"]),
        "'__linux__' selects unknown operating systems",
    ),
    "unknown-architecture": (
        lambda document: _macro(document, "__aarch64__").update(architectures=["riscv64"]),
        "'__aarch64__' selects unknown architectures",
    ),
    "environments": (
        lambda document: _macro(document, "_WIN32").update(environments=["gnu"]),
        "'_WIN32' selects environments",
    ),
    "unreserved-name": (
        lambda document: _macro(document, "__linux__").update(name="linux"),
        "'linux' is not a reserved name",
    ),
    "lowercase-underscore-name": (
        lambda document: _macro(document, "__linux__").update(name="_linux"),
        "'_linux' is not a reserved name",
    ),
    "negative-value": (
        lambda document: _macro(document, "__STDC__").update(value=-1),
        "outside \\[0, 2\\*\\*63 - 1\\]",
    ),
    "wide-value": (
        lambda document: _macro(document, "__STDC__").update(value=2**63),
        "outside \\[0, 2\\*\\*63 - 1\\]",
    ),
    "overlapping-rows": (_overlapping_rows, "'__linux__' has rows that both select 'linux-aarch64'"),
    "unreserved-undefined": (
        lambda document: document["conditionals"].update(undefined_macro_names=["ANDROID"]),
        "undefined macro name 'ANDROID' is not a reserved name",
    ),
    "undefined-in-table": (
        lambda document: document["conditionals"].update(undefined_macro_names=["__cplusplus", "__linux__"]),
        "undefined macro name '__linux__' is also a predefined macro",
    ),
    "reserved-foreign": (
        lambda document: document["conditionals"].update(foreign_macro_names=["__FOREIGN"]),
        "foreign macro name '__FOREIGN' is a reserved name",
    ),
    "hosted-foreign": (
        lambda document: document["conditionals"].update(foreign_macro_names=["printf"]),
        "foreign macro name 'printf' is already a hosted-ABI name",
    ),
    "unsorted": (
        lambda document: document["conditionals"].update(foreign_macro_names=["bool", "NDEBUG"]),
        "foreign_macro_names must be sorted and unique",
    ),
    "repeated": (
        lambda document: document["conditionals"].update(foreign_macro_names=["NDEBUG", "NDEBUG"]),
        "foreign_macro_names must be sorted and unique",
    ),
    "unsorted-selector": (
        lambda document: _macro(document, "__linux__").update(operating_systems=["macos", "linux"]),
        "operating_systems must be sorted and unique",
    ),
}


def test_target_spec_loads_and_satisfies_the_generator_rules() -> None:
    targets = TargetManifest.load(TARGET_SPEC, _hosted_manifest())
    assert targets.labels == (
        "linux-x86_64",
        "linux-aarch64",
        "macos-x86_64",
        "macos-aarch64",
        "windows-x86_64",
        "windows-aarch64",
    )
    assert {"__CHAR_BIT__", "__STDC_VERSION__", "__BYTE_ORDER__"} <= {macro.name for macro in targets.predefined_macros}


@pytest.mark.parametrize("violation", tuple(TARGET_RULE_VIOLATIONS))
def test_target_spec_generator_rules_fail_closed(violation: str) -> None:
    mutate, message = TARGET_RULE_VIOLATIONS[violation]
    hosted = _hosted_manifest()
    document = copy.deepcopy(_target_document())
    TargetManifest.from_document(copy.deepcopy(document), hosted)
    mutate(document)
    with pytest.raises(HostedAbiManifestError, match=message):
        TargetManifest.from_document(document, hosted)


def test_generated_target_rows_equal_the_spec() -> None:
    targets = TargetManifest.load(TARGET_SPEC, _hosted_manifest())
    assert [tuple(row) for row in generated_abi.TARGET_ROWS] == [
        (target.operating_system, target.architecture) for target in targets.targets
    ]
    assert [tuple(row) for row in generated_abi.TARGET_PREDEFINED_MACRO_ROWS] == [
        (macro.name, macro.value, macro.operating_systems, macro.architectures, macro.environments)
        for macro in targets.predefined_macros
    ]
    assert targets.undefined_macro_names == generated_abi.TARGET_UNDEFINED_MACRO_NAMES
    assert targets.foreign_macro_names == generated_abi.TARGET_FOREIGN_MACRO_NAMES
    assert targets.fingerprint == generated_abi.TARGET_SPEC_FINGERPRINT
    tables = (SOURCE_ROOT / "compiler/btrc/generated/hosted_abi/Tables.btrc").read_text()
    assert f'self.targetSpecFingerprint = "{targets.fingerprint}";' in tables
    for target in targets.targets:
        assert f'built.push(GeneratedTargetRow("{target.operating_system}", "{target.architecture}"));' in tables


def test_target_union_merges_targets_and_names_a_disagreement() -> None:
    union = TargetUnion(TargetManifest.load(TARGET_SPEC, _hosted_manifest()))
    first, *rest = union.labels
    owners = union.owners(
        {label: {"Vector": {"Vector.btrc"}} for label in union.labels} | {first: {"Map": {"Map.btrc"}}}
    )
    assert owners == {"Map": {"Map.btrc"}, "Vector": {"Vector.btrc"}}
    merged = union.merge("Vector.btrc", {label: {"Vector": 1} for label in union.labels} | {first: {"Only": 2}})
    assert merged == {"Only": 2, "Vector": 1}
    disagreeing = {label: {"Vector": 1} for label in union.labels} | {rest[-1]: {"Vector": 2}}
    with pytest.raises(
        HostedAbiManifestError, match=f"Vector.btrc: 'Vector' differs between targets '{first}' and '{rest[-1]}'"
    ):
        union.merge("Vector.btrc", disagreeing)
    with pytest.raises(HostedAbiManifestError, match="must cover exactly the spec targets"):
        union.merge("Vector.btrc", {first: {}})


# Every OS-ARCH pair either compiler might be asked for: the spec's rows and
# near misses on each axis.
_CANDIDATE_OPERATING_SYSTEMS = ("linux", "macos", "windows", "ios", "android")
_CANDIDATE_ARCHITECTURES = ("x86_64", "aarch64", "riscv64")


def _spec_labels() -> set[str]:
    return {f"{row.operating_system}-{row.architecture}" for row in generated_abi.TARGET_ROWS}


def test_target_rows_equal_the_reference_package_targets() -> None:
    accepted = set()
    for operating_system in _CANDIDATE_OPERATING_SYSTEMS:
        for architecture in _CANDIDATE_ARCHITECTURES:
            label = f"{operating_system}-{architecture}"
            try:
                target = PackageTarget.parse(label)
            except ValueError:
                continue
            accepted.add(f"{target.operating_system}-{target.architecture}")
    assert accepted == _spec_labels()


def test_target_rows_equal_the_self_hosted_package_targets(tmp_path: Path, immutable_btrcc: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    (project / "btrc.toml").write_text('manifest-version = 1\n\n[package]\nname = "targets"\n')
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_HOME": str(SOURCE_ROOT)}
    accepted = set()
    for operating_system in _CANDIDATE_OPERATING_SYSTEMS[:4]:
        for architecture in _CANDIDATE_ARCHITECTURES:
            label = f"{operating_system}-{architecture}"
            result = subprocess.run(
                [str(immutable_btrcc), "--strict-imports", "--target", label, str(source)],
                cwd=REPOSITORY_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=TRANSPILE_TIMEOUT,
            )
            if result.returncode == 0:
                accepted.add(label)
            else:
                assert f"unsupported package target '{label}'" in result.stderr, result.stderr
    assert accepted == _spec_labels()


def _selected_value(label: str, name: str) -> int:
    operating_system, architecture = label.split("-", 1)
    values = [
        row.value
        for row in generated_abi.TARGET_PREDEFINED_MACRO_ROWS
        if row.name == name
        and (not row.operating_systems or operating_system in row.operating_systems)
        and (not row.architectures or architecture in row.architectures)
    ]
    assert len(values) == 1, f"{name} on {label}"
    return values[0]


def _table_widths(label: str) -> tuple[int, int, int, int]:
    char_bit = _selected_value(label, "__CHAR_BIT__")
    return (
        char_bit,
        char_bit * _selected_value(label, "__SIZEOF_SHORT__"),
        char_bit * _selected_value(label, "__SIZEOF_INT__"),
        char_bit * _selected_value(label, "__SIZEOF_LONG_LONG__"),
    )


def test_reference_analyzer_widths_equal_every_target_row() -> None:
    widths = CIntegerWidths.native()
    for label in sorted(_spec_labels()):
        assert _table_widths(label) == (widths.char, widths.short, widths.int_, widths.long_long), label


def test_self_hosted_analyzer_widths_equal_every_target_row(tmp_path: Path) -> None:
    # The self-hosted analyzer takes these ranks' ranges from <limits.h> of the
    # C compiler that builds btrcc (ConstantValidator.builtinCastRange).
    constants = (SOURCE_ROOT / "compiler/btrc/analyzer/validation/Constants.btrc").read_text()
    for base, limit in (("signed char", "SCHAR"), ("short", "SHRT"), ("int", "INT"), ("long long", "LLONG")):
        pattern = rf'base == "{base}"[^{{]*\{{\s*return self\.signedCastRange\({limit}_MIN, {limit}_MAX\);'
        assert re.search(pattern, constants), base
    compiler = host_c_compiler()
    if compiler is None:
        pytest.skip("requires the configured C compiler")
    probe = tmp_path / "limits.c"
    executable = tmp_path / "limits"
    probe.write_text(
        "#include <limits.h>\n#include <stdio.h>\n"
        'int main(void) { printf("%d %d %d %d %lld\\n", CHAR_BIT, SCHAR_MAX, SHRT_MAX, INT_MAX, LLONG_MAX); '
        "return 0; }\n"
    )
    subprocess.run(
        [*compiler, "-std=c11", str(probe), "-o", str(executable)],
        check=True,
        capture_output=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, check=True, timeout=RUN_TIMEOUT)
    char_bit, schar_max, short_max, int_max, long_long_max = map(int, result.stdout.split())
    limits = (char_bit, (schar_max + 1).bit_length(), (short_max + 1).bit_length(), (int_max + 1).bit_length())
    for label in sorted(_spec_labels()):
        char, short, int_, long_long = _table_widths(label)
        assert limits == (char, char, short, int_), label
        assert (long_long_max + 1).bit_length() == long_long, label
