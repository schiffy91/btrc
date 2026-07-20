"""Raw allocation APIs cannot bypass managed lifetime protocols."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import (
    compile_fixture_pair,
    run_strict_pair,
)
from src.tests.btrc.string_coercion_harness import compile_pair
from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _compiler_environment,
)
from src.tests.btrc.test_mutex_value_contract import COMPILERS, REPO
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).parents[1] / "classes" / "test_class_dot_syntax.btrc"

INVALID_CASES = (
    pytest.param(
        "class Box {} int main() { Box value = new Box(); free(value); return 0; }",
        "free() cannot consume managed value",
        "use 'delete'",
        id="class",
    ),
    pytest.param(
        'int main() { string value = "owned"; free(value); return 0; }',
        "free() cannot consume managed value",
        "release the string",
        id="string",
    ),
    pytest.param(
        "void run(Mutex<int> value) { free(value); } int main() { return 0; }",
        "free() cannot consume managed value",
        "Mutex.destroy()",
        id="mutex",
    ),
    pytest.param(
        "int main() { Thread<int> worker = spawn(() => 1); free(worker); return 0; }",
        "free() cannot consume managed value",
        "join the Thread",
        id="thread",
    ),
    pytest.param(
        "class Owner<T> { public void drop(T value) { free(value); } } int main() { return 0; }",
        "free() cannot consume managed value",
        "pointer-typed raw buffer",
        id="generic-value",
    ),
    pytest.param(
        "class Box {} int main() { Box value = new Box(); free((void*)value); return 0; }",
        "free() cannot consume managed value",
        "use 'delete'",
        id="cast-erasure",
    ),
    pytest.param(
        "class Box {} class Holder { "
        "public Box value { get { return new Box(); } } } "
        "int main() { Holder holder = new Holder(); "
        "free((void*)holder.value); return 0; }",
        "free() cannot consume managed value",
        "bind an owned direct local",
        id="property-cast-erasure",
    ),
    pytest.param(
        "class Box {} int main() { Box value = new Box(); realloc((void*)value, 64); return 0; }",
        "realloc() cannot consume managed value",
        "raw pointer buffers",
        id="realloc-cast-erasure",
    ),
    pytest.param(
        "class Box {} int main() { Box value = new Box(); __btrc_safe_realloc(value, 64); return 0; }",
        "__btrc_safe_realloc() cannot consume managed value",
        "raw pointer buffers",
        id="safe-realloc",
    ),
    pytest.param(
        "class Box {} int main() { Box value = new Box(); reallocarray((void*)value, 2, 64); return 0; }",
        "reallocarray() cannot consume managed value",
        "raw pointer buffers",
        id="reallocarray-cast-erasure",
    ),
    pytest.param(
        "int main() { int* raw = null; Thread<int> worker = spawn(() => 1); realloc(raw, worker); return 0; }",
        "Thread handles cannot be passed as arguments",
        "join or return the unique owner",
        id="realloc-thread-size",
    ),
    pytest.param(
        "int main() { int* raw = null; "
        "Thread<int> worker = spawn(() => 1); "
        "__btrc_safe_realloc(raw, worker); return 0; }",
        "Thread handles cannot be passed as arguments",
        "join or return the unique owner",
        id="safe-realloc-thread-size",
    ),
    pytest.param(
        "int main() { int* raw = null; Thread<int> worker = spawn(() => 1); reallocarray(raw, worker, 4); return 0; }",
        "Thread handles cannot be passed as arguments",
        "join or return the unique owner",
        id="reallocarray-thread-count",
    ),
    pytest.param(
        "int main() { int local = 0; free(&local); return 0; }",
        "free() cannot consume storage",
        "'free' deallocator family",
        id="address-of-local",
    ),
    pytest.param(
        "struct Box { int value; }; int main() { Box box; free(&box.value); return 0; }",
        "free() cannot consume storage",
        "'free' deallocator family",
        id="address-of-field",
    ),
    pytest.param(
        "int main() { int values[2]; free(&values[1]); return 0; }",
        "free() cannot consume storage",
        "'free' deallocator family",
        id="address-of-index",
    ),
    pytest.param(
        '#include <stdlib.h>\nint main() { free(1 ? malloc(8) : getenv("HOME")); return 0; }',
        "free() cannot consume storage",
        "'free' deallocator family",
        id="conditional-mixed-family",
    ),
    pytest.param(
        "#include <stdlib.h>\nint main() { free((char*)malloc(8) + 1); return 0; }",
        "free() cannot consume storage",
        "'free' deallocator family",
        id="interior-pointer-arithmetic",
    ),
    pytest.param(
        "#include <stdlib.h>\nint main() { free((void*)((char*)malloc(8) + 1)); return 0; }",
        "free() cannot consume storage",
        "'free' deallocator family",
        id="cast-wrapped-interior-pointer-arithmetic",
    ),
    pytest.param(
        '#include <stdlib.h>\nint main() { free(getenv("HOME")); return 0; }',
        "free() cannot consume storage",
        "'free' deallocator family",
        id="static-environment-result",
    ),
    pytest.param(
        "#include <string.h>\nint main() { free(strerror(1)); return 0; }",
        "free() cannot consume storage",
        "'free' deallocator family",
        id="static-error-result",
    ),
    pytest.param(
        "#include <string.h>\nint main() { free(strchr(\"abc\", 'b')); return 0; }",
        "cannot consume static string storage",
        "heap memory",
        id="interior-string-result",
    ),
    pytest.param(
        '#include <stdio.h>\nint main() { free(fopen("missing", "r")); return 0; }',
        "free() cannot consume storage",
        "'free' deallocator family",
        id="file-resource-family",
    ),
    pytest.param(
        '#include <dirent.h>\nint main() { free(opendir(".")); return 0; }',
        "free() cannot consume storage",
        "'free' deallocator family",
        id="directory-resource-family",
    ),
)

RAW_POINTER_SOURCE = """
    class Buffer<T> {
        public T* data;
        public Buffer() { self.data = null; }
        public void clear() { free(self.data); self.data = null; }
    }
    int main() {
        Buffer<int> buffer = new Buffer<int>();
        buffer.clear();
        delete buffer;
        int* raw = null;
        int* candidate = realloc(raw, 64);
        if (candidate != null) { raw = candidate; }
        raw = __btrc_safe_realloc(raw, 128);
        free(raw);
        return 0;
    }
"""

VALID_FREE_FAMILY_SOURCE = """
    #include <stdlib.h>
    #include <string.h>
    int main() {
        free(strdup("duplicate"));
        free(malloc(8));
        free(calloc(2, 8));
        free(realpath(".", (char*)NULL));
        free(strcpy((char*)malloc(8), "exact"));
        return 0;
    }
"""

SHADOW_SOURCE = """
    void free(int marker, int ignored) { (void)marker; (void)ignored; }
    int realloc(int value, int amount) { return value + amount; }
    int reallocarray(int value, int count, int size) {
        return value + count * size;
    }
    int memcpy(int value) { return value + 2; }
    int invoke(__fn_ptr<int, int> free) { return free(7); }
    int plusOne(int value) { return value + 1; }
    int main() {
        free(7, 0);
        return realloc(1, 2) == 3 && reallocarray(1, 2, 3) == 7
            && memcpy(40) == 42 && invoke(plusOne) == 8 ? 0 : 1;
    }
"""


@pytest.mark.parametrize(("source", "diagnostic", "guidance"), INVALID_CASES)
def test_managed_raw_lifetime_calls_fail_in_both_analyzers(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
    guidance: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert diagnostic in result.stderr
        assert guidance in result.stderr


def test_raw_pointer_buffers_and_source_free_shadow_remain_valid(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        RAW_POINTER_SOURCE,
        "raw-pointer-lifetime",
        include_stdlib=False,
    )
    for _frontend, generated in compiled:
        source = generated.read_text()
        assert "free(self->data)" in source
        assert "realloc(raw, 64)" in source
    run_strict_pair(compiled, tmp_path)

    shadowed = compile_pair(
        semantic_btrcc,
        tmp_path,
        SHADOW_SOURCE,
        "source-lifetime-shadow",
        include_stdlib=False,
    )
    for _frontend, generated in shadowed:
        source = generated.read_text()
        assert "__btrc_source_free" in source
        assert "__btrc_source_realloc" in source
        assert "__btrc_source_reallocarray" in source
        assert "__btrc_source_memcpy" in source
    run_strict_pair(shadowed, tmp_path)

    # Authenticated stdlib calls still bind to the canonical hosted lifetime
    # functions even when the root program defines bodyful source shadows with
    # incompatible arity.  Successful full-stdlib analysis proves those calls
    # did not borrow the source signatures; root calls remain mangled shadows.
    integrated = compile_pair(
        semantic_btrcc,
        tmp_path,
        SHADOW_SOURCE,
        "stdlib-lifetime-shadow",
        include_stdlib=True,
    )
    for _frontend, generated in integrated:
        source = generated.read_text()
        assert "__btrc_source_free" in source
        assert "__btrc_source_realloc" in source
        assert "__btrc_source_reallocarray" in source


def test_selfhost_stdlib_cannot_take_lifetime_value_through_user_shadow(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    language = data_root / "language"
    stdlib = data_root / "stdlib"
    language.mkdir(parents=True)
    stdlib.mkdir()
    shutil.copy2(REPO / "src/language/grammar.ebnf", language / "grammar.ebnf")
    for source in (REPO / "src/stdlib").glob("*.btrc"):
        shutil.copy2(source, stdlib / source.name)
    (stdlib / "probe.btrc").write_text("void probeLifetimeValue() { __fn_ptr<void, void*> sink = free; (void)sink; }\n")
    program = tmp_path / "hosted-lifetime-value-shadow.btrc"
    program.write_text("void free(void* value) { (void)value; }\nint main() { probeLifetimeValue(); return 0; }\n")
    result = subprocess.run(
        [str(semantic_btrcc), str(program)],
        cwd=REPO,
        env={**os.environ, "BTRC_HOME": str(data_root)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "Hosted lifetime function 'free' must be called directly" in result.stderr


def test_free_compatible_producers_and_exact_aliases_remain_valid(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        VALID_FREE_FAMILY_SOURCE,
        "raw-free-compatible-producers",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_class_dot_lifecycle_is_dual_frontend_strict_c11(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(semantic_btrcc, tmp_path, FIXTURE, include_stdlib=True)
    for frontend, generated in compiled:
        source = generated.read_text()
        assert "__btrc_arc_destroy_slot" in source
        assert "free(b)" not in source
        for compiler in COMPILERS:
            for optimization in ("-O0", "-O2"):
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
                assert run.stdout == "PASS: test_class_dot_syntax\n"
