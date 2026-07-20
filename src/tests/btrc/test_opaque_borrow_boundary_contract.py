"""Managed-to-raw representations are ephemeral, read-only borrows."""

from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import (
    compile_diagnostic_pair,
    run_strict_pair,
)
from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.string_coercion_harness import compile_pair

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")

INVALID_CASES = (
    pytest.param(
        "class Box {} int main() { Box owner = new Box(); void* raw = (void*)owner; return raw == null; }",
        "cannot persist a managed value as a raw representation",
        id="direct-local",
    ),
    pytest.param(
        "bool matchesAt(string text) { char* raw = (char*)text; return raw[0] == 'x'; } "
        'int main() { return matchesAt("x") ? 0 : 1; }',
        "cannot persist a managed value as a raw representation",
        id="string-cast-local",
    ),
    pytest.param(
        'int main() { string owner = "first"; char* aliases[1]; '
        'aliases[0] = (char*)owner; owner = "second"; '
        "return aliases[0][0]; }",
        "cannot persist a managed value as a raw representation",
        id="array-rebind-before-use",
    ),
    pytest.param(
        '#include <string.h>\nint main() { string owner = "abc"; '
        'char* found = strstr(owner, "b"); return found == NULL; }',
        "cannot persist a managed value as a raw representation",
        id="hosted-return-alias",
    ),
    pytest.param(
        "class Box {} int main() { Box owner = new Box(); void* raw = *(void**)&owner; (void)raw; return 0; }",
        "cannot persist a managed value as a raw representation",
        id="pointer-dereference",
    ),
    pytest.param(
        "class Box {} int main() { Box owner = new Box(); void* raw = ((void**)&owner)[0]; (void)raw; return 0; }",
        "cannot persist a managed value as a raw representation",
        id="pointer-index",
    ),
    pytest.param(
        "struct View { void* slot; }; class Box {} int main() { "
        "Box owner = new Box(); void* raw = ((View*)&owner).slot; "
        "(void)raw; return 0; }",
        "cannot persist a managed value as a raw representation",
        id="cast-struct-field",
    ),
    pytest.param(
        "void* unwrap(void** value) { return *value; } class Box {} "
        "int main() { Box owner = new Box(); "
        "void* raw = unwrap((void**)&owner); (void)raw; return 0; }",
        "parameter is not proven borrow-only",
        id="source-dereference-return",
    ),
    pytest.param(
        "#include <string.h>\nvoid wipe(void* value) { memset(value, 0, 8); } "
        "class Box {} int main() { Box owner = new Box(); "
        "wipe((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="mutating-memset-wrapper",
    ),
    pytest.param(
        "#include <string.h>\nvoid overwrite(void* value) { char byte[1]; "
        "byte[0] = 0; memcpy(value, byte, 1); } class Box {} "
        "int main() { Box owner = new Box(); overwrite((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="mutating-memcpy-wrapper",
    ),
    pytest.param(
        "void mutate(void* value) { *(int*)value = 1; } class Box {} "
        "int main() { Box owner = new Box(); mutate((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="direct-dereference-write-wrapper",
    ),
    pytest.param(
        "void mutate(void* value) { ((int*)value)[0]++; } class Box {} "
        "int main() { Box owner = new Box(); mutate((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="indexed-update-wrapper",
    ),
    pytest.param(
        "struct View { void* slot; }; void mutate(void* value) { "
        "((View*)value).slot = null; } class Box {} int main() { "
        "Box owner = new Box(); mutate((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="field-write-wrapper",
    ),
    pytest.param(
        "void mutate(void* value) { int* alias = (int*)value; "
        "alias[0] += 1; } class Box {} int main() { Box owner = new Box(); "
        "mutate((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="derived-alias-write-wrapper",
    ),
    pytest.param(
        "void retain(void* value) { var check = () => value != null; } "
        "class Box {} "
        "int main() { Box owner = new Box(); retain((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="lambda-capture-wrapper",
    ),
    pytest.param(
        "class Holder { public void* value; public Holder(void* value) { "
        "self.value = value; } } void forward(void* value) { "
        "new Holder(value); } class Box {} int main() { Box owner = new Box(); "
        "forward((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="constructor-forward-wrapper",
    ),
    pytest.param(
        "extern void retain(void* value); class Box {} int main() { "
        "Box owner = new Box(); retain((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="unknown-extern-forward",
    ),
    pytest.param(
        "void forward(void* value, __fn_ptr<void, void*> strlen) { "
        "strlen(value); } void retain(void* value) { (void)value; } "
        "class Box {} int main() { Box owner = new Box(); "
        "forward((void*)owner, retain); return 0; }",
        "parameter is not proven borrow-only",
        id="hosted-name-local-callable-forward",
    ),
    pytest.param(
        "void invoke(void* value) { ((__fn_ptr<void>)value)(); } "
        "class Box {} int main() { Box owner = new Box(); "
        "invoke((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="borrow-used-as-callable",
    ),
    pytest.param(
        "void relay(void* value) { throw value; } class Box {} "
        "int main() { Box owner = new Box(); relay((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="borrow-thrown-from-wrapper",
    ),
    pytest.param(
        "void launch(void* value) { var worker = spawn(() => "
        "value != null ? 1 : 0); worker.join(); } class Box {} "
        "int main() { Box owner = new Box(); launch((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="borrow-captured-by-spawn",
    ),
    pytest.param(
        "#include <string.h>\nclass Base { public void inspect(void* value) { "
        "memset(value, 0, 1); } public void wrap(void* value) { "
        "self.inspect(value); } } class Child extends Base { public void inspect("
        "void* value) { (void)value; } } class Box {} int main() { "
        "Child child = new Child(); Box owner = new Box(); "
        "child.wrap((void*)owner); return 0; }",
        "parameter is not proven borrow-only",
        id="inherited-wrapper-uses-lexical-mutating-method",
    ),
    pytest.param(
        "#include <string.h>\nclass Box {} int main() { Box owner = new Box(); memset((void*)owner, 0, 8); return 0; }",
        "parameter is not proven borrow-only",
        id="direct-mutating-hosted-call",
    ),
    pytest.param(
        "#include <unistd.h>\nclass Box {} int main() { Box owner = new Box(); read(0, (void*)owner, 1); return 0; }",
        "parameter is not proven borrow-only",
        id="direct-hosted-output-buffer",
    ),
    pytest.param(
        '#include <string.h>\nint main() { string owner = "abc"; free(strstr(owner, "b")); return 0; }',
        "free() cannot consume managed value",
        id="consume-hosted-return-alias",
    ),
    pytest.param(
        'int main() { free("literal"); return 0; }',
        "cannot consume static string storage",
        id="consume-static-literal",
    ),
    pytest.param(
        'int main() { realloc((void*)"literal", 16); return 0; }',
        "cannot consume static string storage",
        id="resize-static-literal-cast",
    ),
)


@pytest.mark.parametrize(("source", "diagnostic"), INVALID_CASES)
def test_opaque_borrow_escapes_fail_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert diagnostic in result.stderr


READ_ONLY_SOURCE = (FIXTURES / "opaque_borrow_read_only_runtime.btrc").read_text()

COMPARISON_CAST_SOURCE = r"""
int main() {
    string owner = "x";
    int matches = (int)(owner == "x");
    return matches == 1 ? 0 : 1;
}
"""


def test_read_only_wrappers_scalar_reads_and_static_aliases_remain_valid(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        READ_ONLY_SOURCE,
        "opaque-read-only-boundary",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


def test_comparison_result_cast_severs_managed_borrow_provenance(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        COMPARISON_CAST_SOURCE,
        "opaque-comparison-cast",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


OWNED_COPY_SOURCE = (FIXTURES / "opaque_borrow_owned_copy_runtime.btrc").read_text()

STDLIB_HOSTED_SHADOW_SOURCE = r"""
void* retained_memcpy_source;

void* memcpy(void* destination, const void* source, size_t count) {
    (void)count;
    retained_memcpy_source = (void*)source;
    return destination;
}

int main() {
    Bytes bytes = Bytes();
    string owner = "abc";
    bytes.appendRaw((char*)owner, 3);
    return bytes.length() == 3 && bytes.get(1) == 98 ? 0 : 1;
}
"""


def test_stdlib_borrow_proof_uses_stdlib_hosted_call_provenance(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        STDLIB_HOSTED_SHADOW_SOURCE,
        "opaque-stdlib-hosted-shadow",
        include_stdlib=True,
    )
    run_strict_pair(compiled, tmp_path)


def test_owned_raw_copy_survives_managed_rebind_under_sanitizers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        OWNED_COPY_SOURCE,
        "opaque-owned-copy-rebind",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)
    toolchain = require_sanitizers(tmp_path)
    for frontend, generated in compiled:
        sanitized_build_and_run(
            generated,
            tmp_path / f"{frontend}-opaque-owned-copy-san",
            toolchain,
        )
