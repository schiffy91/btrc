"""Strict-C checks for minimal managed-string helper closures."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.ir.gen.helpers import helper_decls_for_roots
from src.compiler.python.ir.helpers.string_ownership import STRING_OWNERSHIP

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
NO_C11_COMPILER = not COMPILERS or sys.platform == "win32"

HEADERS = """\
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
"""

ROOT_PROGRAMS = {
    "__btrc_string_registry": """
int main(void) {
    __btrc_string_entry entry = {NULL, 0, NULL};
    bool valid = entry.value == NULL && __btrc_string_bucket_count == 64
            && __btrc_string_buckets == __btrc_string_inline_buckets;
    return valid ? 0 : 1;
}
""",
    "__btrc_string_registry_lock_state": """
int main(void) {
    bool was_set = atomic_flag_test_and_set(&__btrc_string_lock);
    atomic_flag_clear(&__btrc_string_lock);
    return was_set ? 1 : 0;
}
""",
    "__btrc_string_registry_lock": """
int main(void) { __btrc_string_registry_lock(); __btrc_string_registry_unlock(); return 0; }
""",
    "__btrc_string_registry_hash": """
int main(void) { const char value = 0; return __btrc_string_hash(&value, 64) < 64 ? 0 : 1; }
""",
    "__btrc_string_registry_slot": """
int main(void) { const char value = 0; return *__btrc_string_slot(&value) == NULL ? 0 : 1; }
""",
    "__btrc_string_registry_count": """
int main(void) { return __btrc_string_entry_count == 0 ? 0 : 1; }
""",
    "__btrc_string_registry_resize": """
int main(void) {
    __btrc_string_registry_resize(128);
    bool valid = __btrc_string_bucket_count == 128;
    free(__btrc_string_buckets);
    return valid ? 0 : 1;
}
""",
    "__btrc_string_adopt": """
int main(void) {
    char* value = (char*)__btrc_safe_realloc(NULL, 2);
    value[0] = 'x'; value[1] = '\\0';
    return __btrc_string_adopt(value) == value ? 0 : 1;
}
""",
    "__btrc_string_retain": """
int main(void) {
    const char value[] = "borrowed";
    return __btrc_string_retain(value) == value ? 0 : 1;
}
""",
    "__btrc_string_release": """
int main(void) { const char value[] = "borrowed"; __btrc_string_release(value); return 0; }
""",
    "__btrc_string_release_cleanup": """
int main(void) { char value[] = "borrowed"; __btrc_string_release_cleanup(value); return 0; }
""",
    "__btrc_string_live_count": """
int main(void) { return __btrc_string_live_count() == 0 ? 0 : 1; }
""",
    "__btrc_str_track": """
int main(void) {
    char* value = (char*)__btrc_safe_realloc(NULL, 1); value[0] = '\\0';
    return __btrc_str_track(value) == value ? 0 : 1;
}
""",
    "__btrc_str_flush": """
int main(void) { __btrc_str_flush(); return 0; }
""",
    "__btrc_string_alloc": """
int main(void) { char* value = __btrc_string_alloc(0); return value[0] == '\\0' ? 0 : 1; }
""",
    "__btrc_string_or_empty": """
int main(void) { return __btrc_string_or_empty(NULL)[0] == '\\0' ? 0 : 1; }
""",
    "__btrc_repeat": """
int main(void) {
    char* repeated = __btrc_repeat("ab", 3);
    char* empty = __btrc_repeat("", INT_MAX);
    char* null_string = __btrc_repeat(NULL, 1);
    return strcmp(repeated, "ababab") == 0 && empty[0] == '\\0'
            && null_string[0] == '\\0' ? 0 : 1;
}
""",
}


@pytest.mark.skipif(NO_C11_COMPILER, reason="requires a C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("root", ROOT_PROGRAMS)
def test_minimal_string_helper_root_is_warning_clean(tmp_path: Path, c_compiler: str, root: str):
    helpers = helper_decls_for_roots({root})
    names = {helper.name for helper in helpers}
    if root == "__btrc_string_retain":
        assert "__btrc_string_registry" in names
        assert "__btrc_string_registry_count" not in names

    runtime = "\n\n".join(helper.c_source for helper in helpers)
    source = tmp_path / f"{root.removeprefix('__btrc_')}.c"
    binary = source.with_suffix("")
    source.write_text(f"{HEADERS}\n{runtime}\n{ROOT_PROGRAMS[root]}")
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([binary], capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr


def test_every_managed_string_ownership_helper_has_a_minimal_c11_case():
    assert set(STRING_OWNERSHIP) <= ROOT_PROGRAMS.keys()
