"""Compile and execute the emitted string runtime under Clang sanitizers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.ir.helpers.alloc import ALLOC
from src.compiler.python.ir.helpers.string_ownership import STRING_OWNERSHIP
from src.compiler.python.ir.helpers.string_pool import STRING_POOL
from src.compiler.python.ir.helpers.strings import STRING

CLANG = shutil.which("clang")
pytestmark = pytest.mark.skipif(CLANG is None, reason="needs Clang")

_HEADERS = """\
#include <ctype.h>
#include <limits.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
"""


def _runtime_source(main: str) -> str:
    helpers = "\n\n".join(
        helper.c_source for group in (ALLOC, STRING_OWNERSHIP, STRING_POOL, STRING) for helper in group.values()
    )
    return f"{_HEADERS}\n{helpers}\n\n{main}\n"


def _compile(tmp_path: Path, main: str, name: str) -> Path:
    source = tmp_path / f"{name}.c"
    binary = tmp_path / name
    source.write_text(_runtime_source(main))
    result = subprocess.run(
        [
            CLANG,
            "-std=c11",
            "-pedantic",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-unused-function",
            f"-fsanitize={os.environ.get('BTRC_STRING_SANITIZERS', 'undefined')}",
            "-fno-omit-frame-pointer",
            "-pthread",
            str(source),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return binary


def test_string_runtime_safety_and_utf8_contracts(tmp_path):
    binary = _compile(
        tmp_path,
        r"""
#define CHECK(value) do { if (!(value)) return __LINE__; } while (0)

static void free_parts(char** parts) {
    if (!parts) return;
    for (int i = 0; parts[i]; i++) __btrc_string_release(parts[i]);
    free(parts);
}

static void* exercise_pool(void* ignored) {
    (void)ignored;
    for (int i = 0; i < 600; i++) {
        char* item = __btrc_string_alloc(1);
        item[0] = 'x';
        __btrc_str_track(item);
        __btrc_string_release(item);
    }
    __btrc_str_flush();
    return NULL;
}

int main(void) {
    char* value = __btrc_substring("abc", -4, INT_MAX);
    CHECK(strcmp(value, "abc") == 0); __btrc_string_release(value);
    value = __btrc_substring(NULL, 0, 1);
    CHECK(strcmp(value, "") == 0); __btrc_string_release(value);
    value = __btrc_trim(" \tAbC\r\n");
    CHECK(strcmp(value, "AbC") == 0); __btrc_string_release(value);

    const char utf8[] = "\xC3\xA9" "aB";
    value = __btrc_toUpper(utf8);
    CHECK(memcmp(value, "\xC3\xA9" "AB", 5) == 0); __btrc_string_release(value);
    value = __btrc_swapCase(utf8);
    CHECK(memcmp(value, "\xC3\xA9" "Ab", 5) == 0); __btrc_string_release(value);

    value = __btrc_replace("aaaa", "aa", "bbb");
    CHECK(strcmp(value, "bbbbbb") == 0); __btrc_string_release(value);
    value = __btrc_replace("abcabc", "bc", "");
    CHECK(strcmp(value, "aa") == 0); __btrc_string_release(value);

    char** parts = __btrc_split("a,", ",");
    CHECK(parts[0] && parts[1] && !parts[2]);
    CHECK(strcmp(parts[0], "a") == 0 && strcmp(parts[1], "") == 0);
    free_parts(parts);
    parts = __btrc_split("", ",");
    CHECK(parts[0] && !parts[1] && strcmp(parts[0], "") == 0);
    free_parts(parts);

    value = __btrc_repeat("ab", -3);
    CHECK(strcmp(value, "") == 0); __btrc_string_release(value);
    value = __btrc_repeat("ab", 3);
    CHECK(strcmp(value, "ababab") == 0); __btrc_string_release(value);
    value = __btrc_removePrefix("abc", "abcdef");
    CHECK(strcmp(value, "abc") == 0); __btrc_string_release(value);

    char* items[] = {"a", NULL, "c"};
    value = __btrc_join(items, 3, ":");
    CHECK(strcmp(value, "a::c") == 0); __btrc_string_release(value);
    value = __btrc_join(items, -1, ":");
    CHECK(strcmp(value, "") == 0); __btrc_string_release(value);

    CHECK(__btrc_find("abc", "", 3) == 3);
    CHECK(__btrc_find("abc", "a", -8) == 0);
    CHECK(__btrc_find("abc", "", 4) == -1);
    CHECK(!__btrc_isDigitStr(NULL));
    CHECK(__btrc_isBlank(NULL));
    CHECK(!__btrc_isAlphaStr("\xC3\xA9"));

    CHECK(__btrc_charLen("\xF0\x9F\x98\x80") == 1);
    CHECK(__btrc_charLen("\xC0\xAF") == 2);
    CHECK(__btrc_charLen("\xE2\x82") == 2);
    CHECK(__btrc_charLen("\xED\xA0\x80") == 3);
    CHECK(__btrc_charLen(NULL) == 0);

    value = __btrc_longLongToString(LLONG_MIN);
    CHECK(strcmp(value, "-9223372036854775808") == 0); __btrc_string_release(value);
    CHECK(__btrc_parseInt("999999999999") == INT_MAX);
    CHECK(__btrc_parseInt("  -2147483649tail") == INT_MIN);
    CHECK(__btrc_parseLong("+12tail") == 12L);
    CHECK(__btrc_parseLong("999999999999999999999999") == LONG_MAX);
    CHECK(__btrc_parseLong("-999999999999999999999999") == LONG_MIN);
    CHECK(__btrc_parseLong(NULL) == 0L);
    CHECK(__btrc_parseBool("true"));
    CHECK(__btrc_parseBool("yes"));
    CHECK(!__btrc_parseBool("false"));
    CHECK(!__btrc_parseBool("0"));
    CHECK(!__btrc_parseBool(""));
    CHECK(!__btrc_parseBool(NULL));

    pthread_t first, second;
    CHECK(pthread_create(&first, NULL, exercise_pool, NULL) == 0);
    CHECK(pthread_create(&second, NULL, exercise_pool, NULL) == 0);
    CHECK(pthread_join(first, NULL) == 0);
    CHECK(pthread_join(second, NULL) == 0);
    CHECK(__btrc_str_track(NULL) == NULL);
    char* borrowed_literal = (char*)"literal";
    CHECK(__btrc_string_retain(borrowed_literal) == borrowed_literal);
    __btrc_string_release(borrowed_literal);
    CHECK(__btrc_string_live_count() == 0);
    return 0;
}
""",
        "string_runtime",
    )
    result = subprocess.run([binary], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "statement,error",
    [
        ('char* items[] = {"x"}; (void)__btrc_join(items, INT_MAX, "::");', "join overflow"),
        ('(void)__btrc_repeat("ab", INT_MAX);', "repeat overflow"),
        (
            "char* s = __btrc_string_alloc(1); "
            "(*__btrc_string_slot(s))->references = SIZE_MAX; "
            "(void)__btrc_string_retain(s);",
            "reference overflow",
        ),
    ],
)
def test_string_runtime_overflow_paths_fail_cleanly(tmp_path, statement, error):
    binary = _compile(
        tmp_path,
        f"int main(void) {{ {statement} return 0; }}",
        "overflow_" + error.split()[0],
    )
    result = subprocess.run([binary], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert error in result.stderr
