"""Dual-frontend generated-symbol reference and lifecycle boundaries."""

from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import (
    compile_diagnostic_pair,
    compile_no_dce_pair,
)
from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_mutex_value_contract import _compile_pair, _strict_matrix

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)
REPO = Path(__file__).resolve().parents[3]


def test_name_validator_owns_closed_generated_symbol_policy() -> None:
    names = (REPO / "src/compiler/btrc/analyzer/validation/names.btrc").read_text()
    calls = (REPO / "src/compiler/btrc/analyzer/validation/calls.btrc").read_text()
    expressions = (REPO / "src/compiler/btrc/analyzer/validation/expressions.btrc").read_text()
    identity = (REPO / "src/compiler/btrc/syntax/identity.btrc").read_text()
    analyzer = (REPO / "src/compiler/btrc/analyzer/analyzer.btrc").read_text()
    validator = (REPO / "src/compiler/btrc/analyzer/validation/validator.btrc").read_text()

    claim_start = names.index("    public void claimGeneratedSymbol(")
    claim_end = names.index("\n    public void claimGpuSymbols(", claim_start)
    claim = names[claim_start:claim_end]
    assert claim.index("self.hostedAbi.ownedName(symbol)") < claim.index("self.claimSymbol(")
    assert claim.index("self.claimSymbol(") < claim.index("self.state.generatedSymbols.put(")

    for method in (
        "claimGpuSymbols",
        "claimGenericMethodSymbols",
        "deferGeneratedSymbolCall",
        "deferGeneratedSymbolReference",
        "validateCompletedGeneratedSymbols",
    ):
        assert f" {method}(" in names
        assert f" {method}(" not in calls
    assert "import ../generics.btrc;" in names
    assert "import ../generics.btrc;" not in calls
    assert "self.names.deferGeneratedSymbolCall(expression, vars);" in expressions
    assert "self.names.deferGeneratedSymbolReference(\n                expression, vars, known);" in expressions
    assert "private bool couldBeLateGeneratedSymbol(string symbol)" in names
    assert "private bool genericMethodStemMatches(string symbol," in names
    assert "private bool genericTemplateSymbolMatches(" in names
    assert "TypeIdentity.possibleGenericInstanceSymbol(" in names
    assert "TypeIdentity.possibleMethodInstanceSymbol(" in names
    assert "class bool possibleMangledGenericType(" in identity
    assert "class bool possibleGenericInstanceSymbol(" in identity
    assert "class bool possibleMethodInstanceSymbol(" in identity
    assert "self.state.analyzed.isEnumValue(symbol)" in names
    call_defer = names.index("    public void deferGeneratedSymbolCall(")
    value_defer = names.index("    public void deferGeneratedSymbolReference(")
    assert names.index("if (self.state.generatedSymbols.has(symbol))", call_defer) < names.index(
        "self.generatedReferences.push(", call_defer
    )
    exact_claim = names.index("if (self.state.generatedSymbols.has(symbol))", value_defer)
    late_shape = names.index("self.couldBeLateGeneratedSymbol(symbol)", exact_claim)
    compiler_owned = names.index("self.sourceRuntimeSymbols.compilerOwnedUnresolved(symbol)", late_shape)
    assert exact_claim < late_shape < compiler_owned
    pre_body_claim = validator.index("self.names.publishKnownGeneratedSymbols(self.program);")
    body_validation = validator.index("self.declarations.validateCallableBody(")
    assert pre_body_claim < body_validation
    publish_start = names.index("    public void publishKnownGeneratedSymbols(")
    publish_end = names.index("\n    public void validateEmittedSymbols(", publish_start)
    assert "validatePreprocessorSymbolReferences" not in names[publish_start:publish_end]
    assert "self.validatePreprocessorSymbolReferences(program);" in names[publish_end:]
    assert "self.names.validateCompletedGeneratedSymbols(self.program);" in validator
    assert analyzer.index("self.generics.closeExpressionGraph(program);") < analyzer.index(
        "validator.validateCompletedGeneratedSymbols();"
    )


@pytest.mark.parametrize(
    ("source", "symbol"),
    (
        ("class Box {} int main() { Box_init(null); return 0; }", "Box_init"),
        ("class Box {} int main() { Box_new(); return 0; }", "Box_new"),
        ("class Box {} int main() { Box_destroy(null); return 0; }", "Box_destroy"),
        (
            "@gpu void kernel(int[] values) { int i = gpu_id(); values[i] += 1; } "
            "int main() { kernel__gpuitem(); return 0; }",
            "kernel__gpuitem",
        ),
        (
            "@gpu void kernel(int[] values) { int i = gpu_id(); values[i] += 1; } "
            "int main() { kernel__gpucpu(); return 0; }",
            "kernel__gpucpu",
        ),
        (
            "class Vault { private int secret() { return 42; } } "
            "int main() { Vault value = new Vault(); return Vault_secret(value); }",
            "Vault_secret",
        ),
        (
            "class Vault { private int secret { get { return 42; } } } "
            "int main() { Vault value = new Vault(); return Vault_get_secret(value); }",
            "Vault_get_secret",
        ),
        (
            "class Box { class int total = 0; } int main() { return Box_total(); }",
            "Box_total",
        ),
        (
            "class Box { public void __del__() {} } int main() { __btrc_Box_destructor_hook(null); return 0; }",
            "__btrc_Box_destructor_hook",
        ),
        (
            "class Box<T> {} int main() { Box<int> stored = new Box<int>(); btrc_Box_int_destroy(stored); return 0; }",
            "btrc_Box_int_destroy",
        ),
        (
            "class Box { public U identity<U>(U value) { return value; } } "
            "int main() { Box box = new Box(); int value = box.identity(42); "
            "return Box_identity_int(box, value); }",
            "Box_identity_int",
        ),
    ),
)
def test_generated_c_calls_are_rejected_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    symbol: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert f"compiler-generated C symbol '{symbol}'" in result.stderr


@pytest.mark.parametrize(
    "source",
    (
        "class Box {} int main() { var value = Box_new(); return 0; }",
        "@gpu void kernel(int[] values) { int i = gpu_id(); values[i] += 1; } "
        "int main() { var value = kernel__gpuitem(); return 0; }",
    ),
    ids=("class-allocator", "gpu-worker"),
)
def test_current_generated_calls_fail_before_var_inference(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode != 0
    assert "compiler-generated C symbol" in selfhost.stderr
    assert "Cannot infer type" not in selfhost.stderr
    assert reference.returncode != 0
    assert "compiler-generated C symbol" in reference.stderr


@pytest.mark.parametrize(
    "symbol",
    (
        "__btrc_lambda_1",
        "__btrc_spawn_wrapper_1",
        "__btrc_spawn_env_dispose_1",
        "__btrc_cleanup_take_1",
        "__gpu_dispatch_1_run",
    ),
)
def test_dynamic_compiler_owned_names_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    symbol: str,
) -> None:
    source = f"int main() {{ {symbol}(); return 0; }}"
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert f"compiler-owned C symbol '{symbol}'" in result.stderr


@pytest.mark.parametrize(
    ("statement", "symbol"),
    (
        ("__fn_ptr<void, void*> hook = __btrc_Box_destructor_hook; hook(null);", "__btrc_Box_destructor_hook"),
        ("void* hook = (void*)&__btrc_Box_destructor_hook;", "__btrc_Box_destructor_hook"),
        ("((__fn_ptr<void, void*>)__btrc_Box_destructor_hook)(null);", "__btrc_Box_destructor_hook"),
        ("void* hook = (void*)&Vault_secret;", "Vault_secret"),
    ),
)
def test_generated_symbol_value_reference_fails_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    statement: str,
    symbol: str,
) -> None:
    source = (
        "class Box { public void __del__() {} } class Vault { private int secret() { return 42; } } int main() { "
        + statement
        + " return 0; }"
    )
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert f"compiler-generated C symbol '{symbol}'" in result.stderr


@pytest.mark.parametrize(
    ("source", "symbol"),
    (
        (
            "@gpu void kernel(int[] values) { int i = gpu_id(); values[i] += 1; } "
            "int main() { void* worker = (void*)&kernel__gpuitem; return 0; }",
            "kernel__gpuitem",
        ),
        (
            "class Box { public U identity<U>(U value) { return value; } } "
            "int main() { Box box = new Box(); int value = box.identity(42); "
            "void* specialized = (void*)&Box_identity_int; return value; }",
            "Box_identity_int",
        ),
    ),
)
def test_call_owned_generated_symbol_values_are_rejected_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    symbol: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert f"compiler-generated C symbol '{symbol}'" in result.stderr


@pytest.mark.parametrize(
    ("source", "symbol"),
    (
        (
            "#define CALL(value) kernel__gpuitem(value)\n"
            "@gpu void kernel(int[] values) { int i = gpu_id(); values[i] += 1; } "
            "int main() { return 0; }",
            "kernel__gpuitem",
        ),
        (
            "#define CALL(receiver, value) Box_identity_int(receiver, value)\n"
            "class Box { public U identity<U>(U value) { return value; } } "
            "int main() { Box box = new Box(); return box.identity(42); }",
            "Box_identity_int",
        ),
    ),
)
def test_call_owned_generated_symbol_macros_are_rejected_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    symbol: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert f"compiler-generated C symbol '{symbol}'" in result.stderr


def test_generic_method_generated_name_cannot_claim_hosted_abi_symbol(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        struct settype { int value; };
        class pthread {
            public U mutexattr<U>(U value) { return value; }
        }
        int main() {
            pthread api = new pthread();
            settype value = {1};
            settype result = api.mutexattr(value);
            return result.value == 1 ? 0 : 1;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "pthread_mutexattr_settype" in result.stderr
        assert "collides with compiler-owned hosted C symbol" in result.stderr


LATE_GENERIC_METHOD_PREFIX = """
    class Worker {
        public U identity<U>(U value) { return value; }
    }
    class Box<T> {
        public Worker worker;
        public Box(Worker worker) { self.worker = worker; }
        public int run() { return self.worker.identity(42); }
    }
"""


@pytest.mark.parametrize(
    "source",
    (
        LATE_GENERIC_METHOD_PREFIX
        + """
            int main() {
                Worker worker = new Worker();
                Box<int> box = new Box<int>(worker);
                int value = box.run();
                return Worker_identity_int() + value;
            }
        """,
        LATE_GENERIC_METHOD_PREFIX
        + """
            int main() {
                Worker worker = new Worker();
                Box<int> box = new Box<int>(worker);
                int value = box.run();
                void* specialized = (void*)&Worker_identity_int;
                return value;
            }
        """,
        "#define CALL(value) Worker_identity_int(value)\n"
        + LATE_GENERIC_METHOD_PREFIX
        + """
            int main() {
                Worker worker = new Worker();
                Box<int> box = new Box<int>(worker);
                return box.run();
            }
        """,
    ),
)
def test_post_closure_generic_method_references_fail_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "compiler-generated C symbol 'Worker_identity_int'" in result.stderr


def test_lowercase_post_closure_generic_method_value_uses_declared_stem(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class worker {
            public U identity<U>(U value) { return value; }
        }
        class box<T> {
            public worker value;
            public box(worker value) { self.value = value; }
            public int run() { return self.value.identity(42); }
        }
        int main() {
            worker value = new worker();
            box<int> owner = new box<int>(value);
            int result = owner.run();
            void* specialized = (void*)&worker_identity_int;
            return result;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "compiler-generated C symbol 'worker_identity_int'" in result.stderr


LATE_GENERIC_CLASS_PREFIX = """
    class Link {}
    class Holder<T> {
        public T value;
        public Link link;
        public Holder(T value) { self.value = value; }
        public T read() { return self.value; }
        public T item { get { return self.value; } }
        public U identity<U>(U value) { return value; }
    }
    class Box<T> {
        public T run(T value) {
            Holder<T> holder = new Holder<T>(value);
            int marker = holder.identity(42);
            return marker == 42 ? holder.item : holder.read();
        }
    }
"""


@pytest.mark.parametrize(
    "symbol",
    (
        "btrc_Holder_int_new",
        "btrc_Holder_int_read",
        "btrc_Holder_int_get_item",
        "btrc_Holder_int_identity_int",
        "__btrc_arc_visit_btrc_Holder_int",
    ),
    ids=("lifecycle", "method", "property", "generic-method", "cycle-visitor"),
)
def test_post_closure_generic_class_values_use_declared_type_grammar(
    semantic_btrcc: Path,
    tmp_path: Path,
    symbol: str,
) -> None:
    source = (
        LATE_GENERIC_CLASS_PREFIX
        + f"""
            int main() {{
                Box<int> box = new Box<int>();
                int result = box.run(42);
                void* generated = (void*)&{symbol};
                return result;
            }}
        """
    )
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert f"compiler-generated C symbol '{symbol}'" in result.stderr


@pytest.mark.parametrize(
    "reference",
    (
        "btrc_Holder_int_destroy(null);",
        "void* generated = (void*)&btrc_Holder_int_destroy;",
    ),
    ids=("direct", "value"),
)
def test_post_closure_generic_class_lifecycle_reference_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    reference: str,
) -> None:
    source = (
        LATE_GENERIC_CLASS_PREFIX
        + f"""
            int main() {{
                Box<int> box = new Box<int>();
                int result = box.run(42);
                {reference}
                return result;
            }}
        """
    )
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "compiler-generated C symbol 'btrc_Holder_int_destroy'" in result.stderr


def test_post_closure_generic_class_macro_is_resolved_after_claims(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        "#define DESTROY(value) btrc_Holder_int_destroy(value)\n"
        + LATE_GENERIC_CLASS_PREFIX
        + """
            int main() {
                Box<int> box = new Box<int>();
                return box.run(42);
            }
        """
    )
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "compiler-generated C symbol 'btrc_Holder_int_destroy'" in result.stderr


def test_lowercase_late_generic_class_value_uses_safe_base_grammar(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class holder<T> {
            public T value;
            public holder(T value) { self.value = value; }
            public T read() { return self.value; }
        }
        class box<T> {
            public T run(T value) {
                holder<T> item = new holder<T>(value);
                return item.read();
            }
        }
        int main() {
            box<int> owner = new box<int>();
            int result = owner.run(42);
            void* generated = (void*)&btrc_holder_int_read;
            return result;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "compiler-generated C symbol 'btrc_holder_int_read'" in result.stderr


def test_uninstantiated_generic_method_shape_is_not_labeled_generated(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    value_source = """
        class Worker {
            public U identity<U>(U value) { return value; }
        }
        int main() {
            __fn_ptr<int, int> callback = Worker_identity_int;
            return 0;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, value_source):
        assert result.returncode != 0
        assert "compiler-generated C symbol 'Worker_identity_int'" not in result.stderr
        assert "Worker_identity_int" in result.stderr

    direct_source = """
        class Worker {
            public U identity<U>(U value) { return value; }
        }
        int main() { return Worker_identity_int(42); }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, direct_source):
        assert result.returncode == 0, result.stderr


def test_unselected_late_generic_cycle_visitor_is_not_labeled_generated(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Plain<T> {
            public T value;
            public Plain(T value) { self.value = value; }
        }
        class Seed<T> {
            public T run(T value) {
                Plain<T> item = new Plain<T>(value);
                return item.value;
            }
        }
        int main() {
            Seed<int> seed = new Seed<int>();
            int result = seed.run(42);
            void* visitor = (void*)&__btrc_arc_visit_btrc_Plain_int;
            return result;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "compiler-generated C symbol '__btrc_arc_visit_btrc_Plain_int'" not in result.stderr
        assert "compiler-owned C symbol '__btrc_arc_visit_btrc_Plain_int'" in result.stderr


def test_named_enum_member_shadows_same_spelled_generated_symbol(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Box {}
        enum Result { Box_destroy = 7 };
        int main() { return Box_destroy == 7 ? 0 : 1; }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "generated-symbol-enum-member-shadow",
    ):
        _strict_matrix(artifact, tmp_path)


@pytest.mark.parametrize(
    ("source", "symbol"),
    (
        ("int main() { var value = mystery; return 0; }", "mystery"),
        ("int main() { if (mystery) { return 1; } return 0; }", "mystery"),
        ("int main() { var callback = () => mystery; return 0; }", "mystery"),
        (
            "class Worker { public U identity<U>(U value) { return value; } } "
            "int main() { var value = Worker_identity_1; return 0; }",
            "Worker_identity_1",
        ),
    ),
    ids=("var-inference", "condition", "lambda-return", "invalid-generated-shape"),
)
def test_unrelated_unknown_values_fail_before_derivative_inference(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    symbol: str,
) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode != 0
    assert f"Unknown identifier '{symbol}'" in selfhost.stderr
    assert "Cannot infer type" not in selfhost.stderr
    assert "Cannot infer lambda expression return type" not in selfhost.stderr
    assert reference.returncode != 0
    assert symbol in reference.stderr


def test_known_c_uppercase_value_still_reaches_compiler_owned_resolution(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = "int main() { int value = __BTRC_ARC_LIVE; return value; }"
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "compiler-owned C symbol '__BTRC_ARC_LIVE'" in result.stderr
        assert "Cannot infer type" not in result.stderr


def test_generic_intrinsic_values_are_not_runtime_symbols(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            __fn_ptr<bool, int, int> equal = __btrc_eq;
            return equal(1, 1) ? 0 : 1;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "compiler-owned C symbol '__btrc_eq'" in result.stderr


def test_nonclaimed_c_interop_name_is_not_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Box {}
        extern int Box_destroy_external();
        int main() { return Box_destroy_external(); }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode == 0, result.stderr


def test_lexical_callables_may_shadow_generated_global_symbols(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Box {}
        int invoke(__fn_ptr<int> Box_new) { return Box_new(); }
        int main() {
            __fn_ptr<int> Box_new = () => 20;
            return Box_new() + invoke(() => 22) == 42 ? 0 : 1;
        }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "generated-symbol-lexical-shadow",
    ):
        _strict_matrix(artifact, tmp_path)


def test_hosted_runtime_helper_values_are_rejected_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            __fn_ptr<void*, size_t, size_t> allocate = &__btrc_safe_calloc;
            return 0;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "Hosted function '__btrc_safe_calloc' cannot be stored or forwarded as a value" in result.stderr


def test_supported_runtime_helper_direct_calls_are_strict_c(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            void* storage = __btrc_safe_calloc(1, 4);
            char* copy = __btrc_strdup("ok");
            int length = __btrc_string_length(copy);
            bool equal = __btrc_eq(length, 2);
            free(copy);
            free(storage);
            return equal ? 0 : 1;
        }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "generated-symbol-runtime-helper-direct-call",
    ):
        _strict_matrix(artifact, tmp_path)


def test_unused_generic_method_is_not_emitted_unspecialized_with_no_dce(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Box {
            public U identity<U>(U value) { return value; }
        }
        int main() {
            Box box = new Box();
            delete box;
            return 0;
        }
    """
    for artifact in compile_no_dce_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "generic-method-no-dce",
    ):
        assert "Box_identity(" not in artifact[1].read_text()
        _strict_matrix(artifact, tmp_path)


LIFECYCLE_SOURCE = """
    int destroyed = 0;
    class Box {
        public int value;
        public Box(int value) { self.value = value; }
        private int secret() { return self.value; }
        public int read() { return self.secret(); }
        public void __del__() { destroyed += 1; }
    }
    int main() {
        Box box = new Box(42);
        if (box.read() != 42) { return 1; }
        delete box;
        return box == null && destroyed == 1 ? 0 : 2;
    }
"""


def test_source_lifecycle_api_is_strict_and_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        LIFECYCLE_SOURCE,
        "generated-symbol-source-lifecycle",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)
    toolchain = require_sanitizers(tmp_path)
    for frontend, generated in compiled:
        sanitized_build_and_run(
            generated,
            tmp_path / f"{frontend}-generated-symbol-lifecycle-san",
            toolchain,
        )
