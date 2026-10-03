"""Formatting #if regions (c-preprocessor-conditionals.md, "LSP, formatter and tools").

The formatter has no target. A region whose every group is balanced in
``{}``, ``()`` and ``[]`` is indented normally, each group from the depth at
its opening directive; any other region is kept verbatim. Directive lines stay
at column 0.
"""

from __future__ import annotations

import pytest

from src.devex.formatter import BtrcFormatter, FormatError, StyleConfig


def formatted(source: str) -> str:
    formatter = BtrcFormatter(StyleConfig())
    result = formatter.format(source, "fixture.btrc")
    assert formatter.format(result, "fixture.btrc") == result, "formatting must be idempotent"
    return result


def test_balanced_groups_are_indented_from_the_opening_depth() -> None:
    source = """\
int f(int x) {
#if 1
        if (x) {
return 1;
    }
#else
  return 2;
#endif
    return 0;
}
"""
    assert (
        formatted(source)
        == """\
int f(int x) {
#if 1
\tif (x) {
\t\treturn 1;
\t}
#else
\treturn 2;
#endif
\treturn 0;
}
"""
    )


def test_an_unbalanced_region_is_kept_verbatim_and_counts_its_first_group() -> None:
    source = """\
int f(int x) {
#ifdef A
  if (x) {
#else
      if (!x) {
#endif
            return 1;
    }
    return 0;
}
"""
    assert (
        formatted(source)
        == """\
int f(int x) {
#ifdef A
  if (x) {
#else
      if (!x) {
#endif
\t\treturn 1;
\t}
\treturn 0;
}
"""
    )


def test_regions_in_class_bodies_and_between_operands() -> None:
    source = """\
class C {
#if 1
public int a;
#endif
    public int b;
}
int sum() {
\treturn 1 +
#if 1
\t\t2
#else
\t\t3
#endif
\t\t+ 4;
}
"""
    assert (
        formatted(source)
        == """\
class C {
#if 1
\tpublic int a;
#endif
\tpublic int b;
}
int sum() {
\treturn 1 +
#if 1
\t\t2
#else
\t\t3
#endif
\t\t+ 4;
}
"""
    )


def test_nested_regions_keep_directives_at_column_zero() -> None:
    source = """\
int f() {
    #if 1
#ifdef A
        int a = 1;
#endif
    #endif
    return 0;
}
"""
    result = formatted(source)
    assert [line for line in result.splitlines() if line.lstrip().startswith("#")] == [
        "#if 1",
        "#ifdef A",
        "#endif",
        "#endif",
    ]
    assert "\tint a = 1;" in result.splitlines()


def test_a_source_that_does_not_condition_is_refused() -> None:
    with pytest.raises(FormatError, match="'#if' without '#endif'"):
        BtrcFormatter(StyleConfig()).format("int a;\n#if 1\nint b;\n", "fixture.btrc")
    with pytest.raises(FormatError, match="Identifier 'FOO' in #if"):
        BtrcFormatter(StyleConfig()).format("#if FOO\n#endif\n", "fixture.btrc")
