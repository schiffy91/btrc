"""Strict behavioral contracts for the zero-libc reference runtime."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.freestanding import RUNTIME_HEADER

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

HARNESS = r"""
#define BTRC_FREESTANDING
#define BTRC_FREESTANDING_IMPL
#include <stddef.h>
static char captured[2048];
static size_t captured_length = 0U;
static void capture_output(const char *text, size_t length) {
    if (length > sizeof captured) length = sizeof captured;
    for (size_t i = 0; i < length; ++i) captured[i] = text[i];
    captured_length = length;
}
#define BTRC_RT_PUTS capture_output
#include "btrc_rt.h"

static int same(const char *actual, const char *expected) {
    return strcmp(actual, expected) == 0;
}

int main(void) {
    char text[128];
    if (snprintf(text, sizeof text, "%ld", -2147483647L) < 0
            || !same(text, "-2147483647")) return 1;
    if (snprintf(text, sizeof text, "%lld", (-9223372036854775807LL - 1LL)) < 0
            || !same(text, "-9223372036854775808")) return 2;
    if (snprintf(text, sizeof text, "%lu", 4000000000UL) < 0
            || !same(text, "4000000000")) return 3;
    if (snprintf(text, sizeof text, "%llu", 18446744073709551615ULL) < 0
            || !same(text, "18446744073709551615")) return 4;
    if (snprintf(text, sizeof text, "%zu", (size_t)123456789U) < 0
            || !same(text, "123456789")) return 5;
    if (snprintf(text, sizeof text, "%05d", -7) < 0
            || !same(text, "-0007")) return 6;
    if (snprintf(text, sizeof text, "%g", 3.5) < 0
            || !same(text, "3.5")) return 7;
    if (snprintf(text, sizeof text, "%g", 1000000.0) < 0
            || !same(text, "1e+06")) return 8;
    if (snprintf(text, sizeof text, "%Lg", 12.5L) < 0
            || !same(text, "12.5")) return 9;
    if (snprintf(text, sizeof text, "%g", 0.0) < 0
            || !same(text, "0")) return 23;
    if (snprintf(text, sizeof text, "%.2f", 3.14159) < 0
            || !same(text, "3.14")) return 10;
    if (snprintf(text, sizeof text, "%.0f", 2.7) < 0
            || !same(text, "3")) return 11;
    if (snprintf(text, 4U, "%s", "abcdef") != 6
            || !same(text, "abc")) return 12;
    if (snprintf((char *)0, 0U, "%llu", 12345ULL) != 5) return 13;

    char *end = (char *)0;
    const char *number = "  -12.5e2tail";
    double parsed = strtod(number, &end);
    if (parsed != -1250.0 || !same(end, "tail")) return 14;
    const char *invalid = "  nope";
    if (strtof(invalid, &end) != 0.0F || end != invalid) return 15;

    unsigned char *small = malloc(4U);
    if (!small) return 16;
    small[0] = 1U; small[1] = 2U; small[2] = 3U; small[3] = 4U;
    unsigned char *large = realloc(small, 64U);
    if (!large || large[0] != 1U || large[3] != 4U) return 17;
    if ((uintptr_t)large % (uintptr_t)_Alignof(max_align_t) != 0U) return 18;
    if (malloc(SIZE_MAX) != (void *)0) return 19;
    if (malloc((size_t)BTRC_RT_ARENA_BYTES + 1U) != (void *)0) return 24;
    if (calloc(SIZE_MAX, 2U) != (void *)0) return 20;

    char bounded[3] = {'x', 'x', 'Q'};
    strncpy(bounded, "", 2U);
    if (bounded[0] != '\0' || bounded[1] != '\0' || bounded[2] != 'Q') return 21;
    char overlap[7] = "abcdef";
    memmove(overlap + 1, overlap, 5U);
    if (!same(overlap, "aabcde")) return 22;
    char long_text[1501];
    for (size_t i = 0; i < 1500U; ++i) long_text[i] = (char)('a' + i % 26U);
    long_text[1500] = '\0';
    if (printf("%s", long_text) != 1500 || captured_length != 1500U) return 25;
    if (memcmp(captured, long_text, 1500U) != 0) return 26;
    return 0;
}
"""


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("ubsan", (False, True), ids=("plain", "ubsan"))
def test_reference_runtime_is_strict_and_width_correct(
    tmp_path: Path,
    c_compiler: str,
    ubsan: bool,
):
    (tmp_path / "btrc_rt.h").write_text(RUNTIME_HEADER)
    source = tmp_path / "reference_runtime.c"
    binary = tmp_path / ("reference_runtime_ubsan" if ubsan else "reference_runtime")
    source.write_text(HARNESS)
    sanitizer_flags = ["-fsanitize=undefined", "-fno-sanitize-recover=all"] if ubsan else []
    compiled = subprocess.run(
        [
            c_compiler,
            *sanitizer_flags,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-ffreestanding",
            "-fno-builtin",
            f"-I{tmp_path}",
            str(source),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
    )
    if (
        compiled.returncode != 0
        and ubsan
        and "ubsan" in compiled.stderr.lower()
        and "not found" in compiled.stderr.lower()
    ):
        pytest.skip("compiler wrapper does not provide its UBSan runtime")
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, f"reference runtime check {result.returncode} failed"
