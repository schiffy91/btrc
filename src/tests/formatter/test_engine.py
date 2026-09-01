from __future__ import annotations

from pathlib import Path

import pytest

from src.devex.formatter import BtrcFormatter, FormatError, StyleConfig


def formatted(source: str, **overrides: object) -> str:
    return BtrcFormatter(StyleConfig(**overrides)).format(source, "fixture.btrc")


def test_default_style_covers_members_constructs_and_trivial_methods() -> None:
    source = """\
class Demo {

    public int first;

    public int second;

    public int getNumber(
        int ignored
    ) {
        return 0;
    }


    public bool choose(
        int value
    ) {
        if (
            value > 0 &&
            value < 10
        ) {
            value++;
            return true;
        }
        return false;
    }

}
"""

    result = formatted(source)

    assert "class Demo {\n\tpublic int first;\n\tpublic int second;" in result
    assert "\tpublic int getNumber(int ignored) { return 0; }" in result
    assert "\tpublic bool choose(int value) {" in result
    assert "\t\tif (value > 0 && value < 10) {" in result
    assert "\n\n\tpublic bool choose" in result
    assert result.endswith("\t}\n}\n")


def test_unlimited_default_collapses_a_long_signature() -> None:
    long_name = "aParameterNameThatWouldNormallyExceedAConventionalFormattingWidth"
    source = f"""\
class Demo {{
    public int combine(
        int {long_name},
        int anotherLongParameterName
    ) {{
        print("work");
        return 0;
    }}
}}
"""

    result = formatted(source)

    assert f"public int combine(int {long_name}, int anotherLongParameterName) {{" in result


def test_signature_and_condition_collapsing_are_independently_optional() -> None:
    source = """\
class Demo {
    public bool choose(
        int value
    ) {
        if (
            value > 0 &&
            value < 10
        ) {
            value++;
            return true;
        }
        return false;
    }
}
"""

    signature_multiline = formatted(source, single_line_signatures=False, compact_trivial_functions=False)
    condition_multiline = formatted(source, single_line_conditions=False, compact_trivial_functions=False)

    assert "\tpublic bool choose(\n\t\tint value\n\t)" in signature_multiline
    assert "\t\tif (value > 0 && value < 10)" in signature_multiline
    assert "\tpublic bool choose(int value)" in condition_multiline
    assert "\t\tif (\n\t\t\tvalue > 0\n\t\t\t&& value < 10\n\t\t)" in condition_multiline


def test_paren_placement_and_multiline_close_are_configurable() -> None:
    source = """\
class Demo {
    public int add(
        int left,
        int right
    ) {
        print("work");
        return left + right;
    }
}
"""

    result = formatted(
        source,
        single_line_signatures=False,
        opening_paren="next-line",
        multiline_closing_paren="same-line",
        compact_trivial_functions=False,
    )

    assert "\tpublic int add\n\t(\n\t\tint left,\n\t\tint right) {" in result


def test_line_width_wraps_at_signature_commas() -> None:
    source = """\
class Demo {
    public int combine(int firstLongParameter, int secondLongParameter) {
        print("work");
        return 0;
    }
}
"""

    result = formatted(source, line_width=38, compact_trivial_functions=False)

    assert "\tpublic int combine(\n\t\tint firstLongParameter,\n\t\tint secondLongParameter\n\t) {" in result


def test_unlimited_default_collapses_calls_assignments_returns_and_boolean_chains() -> None:
    source = """\
class Demo {
    public bool evaluate(bool first, bool second) {
        bool localHeader =
            first
            && second;
        assert(
            localHeader
            && second
        );
        Demo copy = new Demo(
            first,
            second
        );
        string label = combine(
            "left",
            "right"
        );
        return decide(
            localHeader,
            copy != null
        );
    }
}
"""

    result = formatted(source)

    assert "\t\tbool localHeader = first && second;" in result
    assert "\t\tassert(localHeader && second);" in result
    assert "\t\tDemo copy = new Demo(first, second);" in result
    assert '\t\tstring label = combine("left", "right");' in result
    assert "\t\treturn decide(localHeader, copy != null);" in result


def test_statement_collapse_spaces_binary_groups_but_preserves_unary_and_casts() -> None:
    source = """\
class Demo {
    public bool grouped(bool enabled, bool loopEnabled, int* pointer) {
        bool valid =
            enabled
            || (
                loopEnabled
                && (pointer != null)
            );
        bool negated =
            !(
                enabled || loopEnabled
            );
        int value =
            *(
                (int*)pointer
            );
        int scaled =
            value
            * (value + 1);
        return valid
            && (
                scaled > 0
            )
            && !negated;
    }
}
"""

    result = formatted(source)

    assert "bool valid = enabled || (loopEnabled && (pointer != null));" in result
    assert "bool negated = !(enabled || loopEnabled);" in result
    assert "int value = *((int*)pointer);" in result
    assert "int scaled = value * (value + 1);" in result
    assert "return valid && (scaled > 0) && !negated;" in result
    assert "||(" not in result
    assert "&&(" not in result
    assert formatted(result) == result


def test_statement_collapsing_can_be_disabled_and_continuations_remain_indented() -> None:
    source = """\
class Demo {
    public bool evaluate(bool first, bool second) {
        bool localHeader =
            first
            && second;
        return localHeader;
    }
}
"""

    result = formatted(source, single_line_statements=False, compact_trivial_functions=False)

    assert "\t\tbool localHeader =\n\t\t\tfirst\n\t\t\t&& second;" in result


def test_statement_line_comments_prevent_unsafe_joining() -> None:
    source = """\
class Demo {
    public int evaluate(int first, int second) {
        int result = combine(
            first, // argument ownership stays visible
            second
        );
        return result;
    }
}
"""

    result = formatted(source)

    assert "combine(\n\t\t\tfirst, // argument ownership stays visible\n\t\t\tsecond\n\t\t);" in result
    assert "// argument ownership stays visible" in result


def test_multiline_structural_data_is_preserved_unless_explicitly_enabled() -> None:
    source = """\
class Demo {
    public int firstValue() {
        int values[] = {
            1,
            2
        };
        return values[0];
    }
}
"""

    preserved = formatted(source)
    flattened = formatted(source, single_line_data=True)

    assert "int values[] = {\n\t\t\t1,\n\t\t\t2\n\t\t};" in preserved
    assert "int values[] = { 1, 2 };" in flattened


def test_statement_width_wraps_call_arguments_and_boolean_chains() -> None:
    source = """\
class Demo {
    public bool evaluate(bool firstCondition, bool secondCondition) {
        bool result = firstCondition && secondCondition;
        return combine(firstCondition, secondCondition);
    }
}
"""

    result = formatted(source, line_width=38, compact_trivial_functions=False)

    assert "\t\tbool result = firstCondition\n\t\t\t&& secondCondition;" in result
    assert "\t\treturn combine(\n\t\t\tfirstCondition,\n\t\t\tsecondCondition\n\t\t);" in result


def test_trivial_compaction_can_be_disabled() -> None:
    source = """\
class Demo {
    public int getNumber() {
        return 0;
    }
}
"""

    assert "public int getNumber() { return 0; }" in formatted(source)
    assert "public int getNumber() {\n\t\treturn 0;\n\t}" in formatted(
        source,
        compact_trivial_functions=False,
    )


def test_all_member_and_class_blank_counts_are_configurable() -> None:
    source = """\
class Demo {
    public int first;
    public int second;
    public int one() {
        print("one");
        return 1;
    }
    public int two() {
        print("two");
        return 2;
    }
}
"""

    result = formatted(
        source,
        compact_trivial_functions=False,
        blank_lines_between_functions=2,
        blank_lines_between_fields=1,
        blank_lines_after_class_opening=1,
        blank_lines_before_class_closing=2,
    )

    assert "class Demo {\n\n\tpublic int first;\n\n\tpublic int second;" in result
    assert "\t}\n\n\n\tpublic int two()" in result
    assert result.endswith("\t}\n\n\n}\n")


def test_imports_are_stably_partitioned_into_exactly_two_groups() -> None:
    source = """\
#include "first.btrc"

import std.map;

import user.alpha;
import std.vector;

#include <second.btrc>

class Demo {}
"""

    result = formatted(source)

    assert result.startswith(
        'import std.map;\nimport std.vector;\n\n#include "first.btrc"\nimport user.alpha;\n#include <second.btrc>\n'
    )
    assert formatted(result) == result


def test_real_include_stdlib_and_user_import_fixture_uses_the_documented_normalization() -> None:
    fixture = Path(__file__).with_name("fixtures") / "ImportGroups.btrc"

    result = BtrcFormatter().format(fixture.read_text(encoding="utf-8"), str(fixture))

    assert result.startswith(
        'import std.vector;\nimport std.map;\n\n#include <assert.h>\nimport ./Support.btrc;\n#include "Legacy.btrc"\n'
    )
    assert BtrcFormatter().format(result, str(fixture)) == result


def test_preprocessor_directive_is_a_hard_boundary_before_top_level_function() -> None:
    source = """\
#include <assert.h>
Bytes encryptedZip(
    Bytes encoded
) {
    assert(encoded.len() > 0);
    return encoded;
}
"""

    result = formatted(source)

    assert result.startswith("#include <assert.h>\nBytes encryptedZip(Bytes encoded) {")
    assert "#include <assert.h> Bytes" not in result


def test_trivial_compaction_preserves_fstring_prefix_adjacency() -> None:
    source = """\
class Demo {
    public string identity(string name) {
        return f"album {name}" + f" / {name}";
    }
}
"""

    result = formatted(source)

    assert 'return f"album {name}" + f" / {name}";' in result
    assert 'f "' not in result
    assert formatted(result) == result


def test_import_group_spacing_is_configurable() -> None:
    source = """\
import std.map;


import std.vector;
import user.alpha;

#include <second.btrc>
class Demo {}
"""

    result = formatted(
        source,
        blank_lines_within_import_groups=1,
        blank_lines_between_import_groups=2,
    )

    assert result.startswith(
        "import std.map;\n\nimport std.vector;\n\n\nimport user.alpha;\n\n#include <second.btrc>\n"
    )


def test_spaces_and_indent_width_override_tabs() -> None:
    source = "class Demo {\npublic int value;\n}\n"

    assert "\n      public int value;\n" in formatted(source, indent_style="spaces", indent_width=6)


def test_comments_strings_and_preprocessor_contents_are_never_treated_as_code() -> None:
    source = """\
/* import std.fake;
   if (notCode) { } */
#define TEXT "import std.fake; if (value)"
class Demo {
    public string text() {
        string value = "if (x) { import std.fake; }";
        print(value);
        return value;
    }

    public int sum(
        int left, // keep this parameter comment
        int right
    ) {
        return left + right;
    }
}
"""

    result = formatted(source)

    assert "/* import std.fake;\n   if (notCode) { } */" in result
    assert '#define TEXT "import std.fake; if (value)"' in result
    assert '"if (x) { import std.fake; }"' in result
    assert "// keep this parameter comment" in result
    assert "sum(\n\t\tint left, // keep this parameter comment" in result
    assert formatted(result) == result


def test_invalid_source_reports_the_compiler_location() -> None:
    with pytest.raises(FormatError) as failure:
        formatted("class Demo { public int value;\n")

    assert failure.value.line >= 1
    assert "Expected" in str(failure.value)


@pytest.mark.parametrize(
    "values",
    [
        {"indent_style": "invalid"},
        {"indent_width": 0},
        {"line_width": -1},
        {"opening_paren": "floating"},
        {"multiline_closing_paren": "floating"},
        {"blank_lines_between_functions": -1},
    ],
)
def test_style_config_rejects_invalid_values(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        StyleConfig(**values)
