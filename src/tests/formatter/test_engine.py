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


def test_pointer_declarations_dereferences_and_multiplication_use_operator_context() -> None:
    fixture = Path(__file__).with_name("fixtures") / "PointerExpressions.btrc"
    source = fixture.read_text(encoding="utf-8")

    result = BtrcFormatter().format(source, str(fixture))

    assert "static void addScaled(int* value, int scale)" in result
    assert "\n\t// A dereference begins a statement; multiplication remains binary.\n\t*value += scale;" in result
    assert "\n\t*value = *value * 2;" in result
    assert "\n\tint* pointer = &value;" in result
    assert "\n\tint product = *pointer * value;" in result
    assert result == source
    assert BtrcFormatter().format(result, str(fixture)) == result


def test_function_pointer_declarators_keep_their_space_and_calls_stay_tight() -> None:
    source = (
        "void sortInts(int* values, size_t count, int (*compare)(const void* left, const void* right)) {}\n"
        "\n"
        "void* run(void* (*)(void*), void*);\n"
        "\n"
        "int main() {\n"
        "\tint (*operation)(int, int) = add;\n"
        "\treturn pick(*pointer)(4);\n"
        "}\n"
    )

    result = BtrcFormatter().format(source, "FunctionPointers.btrc")

    assert result == source
    assert BtrcFormatter().format(result, "FunctionPointers.btrc") == result


def test_braceless_bodies_indent_one_level_past_their_header() -> None:
    fixture = Path(__file__).with_name("fixtures") / "BracelessBodies.btrc"
    source = fixture.read_text(encoding="utf-8")
    flattened = "\n".join(line.lstrip("\t") for line in source.split("\n"))

    result = BtrcFormatter().format(flattened, str(fixture))

    # Each unbraced body sits one level past its header and stays on its own
    # line; a dangling else aligns with the nearest if, and a closing brace
    # with the header line that opened it.
    assert "\n\tif (a)\n\t\tif (b)\n\t\t\tresult = 1;\n\t\telse\n\t\t\tresult = 2;\n\telse if (b)\n" in result
    assert "\n\tdo\n\t\ttotal--;\n\twhile (total > 4);\n" in result
    assert "\n\t\tfor (int i = 0; i < 2; i++) {\n\t\t\ttotal += i;\n\t\t}\n\telse\n" in result
    assert result == source
    assert BtrcFormatter().format(source, str(fixture)) == source


def test_unary_dereference_and_binary_multiplication_keep_distinct_multiline_indentation() -> None:
    source = """\
void update(int* value, int left, int right) {
    *value = left;
    int product =
        left
        * right;
    *value += product;
}
"""

    result = formatted(source, single_line_statements=False, compact_trivial_functions=False)

    assert "\n\t*value = left;" in result
    assert "\n\tint product =\n\t\tleft\n\t\t* right;" in result
    assert "\n\t*value += product;" in result
    assert formatted(result, single_line_statements=False, compact_trivial_functions=False) == result


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


def test_statement_call_parentheses_follow_placement_overrides() -> None:
    source = """\
class Demo {
    public bool evaluate(bool firstCondition, bool secondCondition) {
        return combine(firstCondition, secondCondition);
    }
}
"""

    result = formatted(
        source,
        line_width=38,
        opening_paren="next-line",
        multiline_closing_paren="same-line",
        compact_trivial_functions=False,
    )

    assert "\t\treturn combine\n\t\t(\n\t\t\tfirstCondition,\n\t\t\tsecondCondition);" in result
    assert (
        formatted(
            result,
            line_width=38,
            opening_paren="next-line",
            multiline_closing_paren="same-line",
            compact_trivial_functions=False,
        )
        == result
    )


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

import Library.Map;

import user.alpha;
import Library.Vector;

#include <second.btrc>

class Demo {}
"""

    result = formatted(source)

    assert result.startswith(
        'import Library.Map;\nimport Library.Vector;\n\n#include "first.btrc"\nimport user.alpha;\n#include <second.btrc>\n'
    )
    assert formatted(result) == result


def test_real_include_stdlib_and_user_import_fixture_uses_the_documented_normalization() -> None:
    fixture = Path(__file__).with_name("fixtures") / "ImportGroups.btrc"

    result = BtrcFormatter().format(fixture.read_text(encoding="utf-8"), str(fixture))

    assert result.startswith(
        'import Library.Vector;\nimport Library.Map;\n\n#include <assert.h>\nimport ./Support.btrc;\n#include "Legacy.btrc"\n'
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
import Library.Map;


import Library.Vector;
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
        "import Library.Map;\n\nimport Library.Vector;\n\n\nimport user.alpha;\n\n#include <second.btrc>\n"
    )


def test_import_partitioning_can_be_disabled() -> None:
    source = """\
import user.alpha;
import Library.Vector;

class Demo {}
"""

    result = formatted(source, group_imports=False)

    assert result.startswith("import user.alpha;\n\nimport Library.Vector;\n")


def test_spaces_and_indent_width_override_tabs() -> None:
    source = "class Demo {\npublic int value;\n}\n"

    assert "\n      public int value;\n" in formatted(source, indent_style="spaces", indent_width=6)


def test_comments_strings_and_preprocessor_contents_are_never_treated_as_code() -> None:
    source = """\
/* import Library.fake;
   if (notCode) { } */
#define TEXT "import Library.fake; if (value)"
class Demo {
    public string text() {
        string value = "if (x) { import Library.fake; }";
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

    assert "/* import Library.fake;\n   if (notCode) { } */" in result
    assert '#define TEXT "import Library.fake; if (value)"' in result
    assert '"if (x) { import Library.fake; }"' in result
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


def test_adjacent_string_pieces_keep_their_lines() -> None:
    source = """\
#define TAIL "!"
int main() {
\tchar* message = "first, "
\t\t"second, "
\t\tTAIL;
\tprintf("%s=%"
\t\t"d\\n", "answer", 42);
\treturn 0;
}
"""
    assert formatted(source, indent_style="tabs") == source
    collapsed = source.replace('"first, "\n\t\t"second, "\n\t\tTAIL', '"first, " "second, " TAIL')
    assert formatted(collapsed, indent_style="tabs") == collapsed


def test_declarator_lists_keep_each_declarators_pointer() -> None:
    # `*` binds to its own declarator (C row 3, PLAN.md D20): the formatter
    # never moves it onto the type, where it would misread `int* p, v;`.
    source = (
        "struct Link { int *target, value; };\n"
        "typedef int Count, *CountPointer;\n"
        "int first = 1, *second;\n"
        "int main() {\n"
        "\tint *pointer, value = 2 * 3, *other;\n"
        "\tfor (int i = 0, *p = null; i < 2; i++) {}\n"
        "\treturn 0;\n"
        "}\n"
    )

    assert formatted(source) == source


def test_for_header_clause_opening_with_a_parenthesis_keeps_its_space() -> None:
    # Reported from BTRSmith: `;(index < 3 …` lost the space after the first `;`.
    source = (
        "int main() {\n"
        "\tint total = 0;\n"
        "\tfor (int index = 0; (index < 3 || total == 0) && total < 10; (index++)) {\n"
        "\t\ttotal += index;\n"
        "\t}\n"
        "\treturn total == 3 ? 0 : 1;\n"
        "}\n"
    )

    assert formatted(source) == source
    assert formatted(source.replace("; (", ";(")) == source


def _in_main(body: str) -> str:
    return "int main() {\n\tint a = 1;\n\tint b = 1;\n\tint x = 0;\n" + body + "\treturn x;\n}\n"


@pytest.mark.parametrize(
    "body",
    [
        "\tif (a)\n\t\tif (b) x = 1;\n\t\telse x = 2;\n",
        "\tif (a)\n\t\tif (b) { x = 1; }\n\t\telse x = 2;\n",
        "\tif (a)\n\t\tif (b) {\n\t\t\tx = 1;\n\t\t}\n\t\telse x = 2;\n",
        "\twhile (a)\n\t\tif (b) x = 1;\n\t\telse x = 2;\n",
        "\tif (a)\n\t\twhile (b)\n\t\t\tif (x) x = 1;\n\t\t\telse x = 2;\n\telse\n\t\tx = 3;\n",
        "\tif (a)\n\t\tif (b) {\n\t\t\tx = 1;\n\t\t} else {\n\t\t\tx = 2;\n\t\t}\n\telse\n\t\tx = 3;\n",
        "\tif (a)\n\t\tif (b) x = 1; else x = 2;\n\telse\n\t\tx = 3;\n",
        "\tif (a) {\n\t\tx = 1;\n\t}\n\telse if (b)\n\t\tx = 2;\n\telse\n\t\tx = 3;\n",
    ],
)
def test_dangling_else_aligns_with_an_inner_if_whose_body_shares_its_line(body: str) -> None:
    source = _in_main(body)
    assert formatted(source, indent_style="tabs") == source


@pytest.mark.parametrize(
    "body",
    [
        "\twhile (a)\n\t\tdo\n\t\t\tx++;\n\t\twhile (x < 3);\n",
        "\tif (a)\n\t\tdo\n\t\t\tx++;\n\t\twhile (x < 3);\n",
        "\tif (a)\n\t\tdo {\n\t\t\tx++;\n\t\t}\n\t\twhile (x < 6);\n",
        "\tif (a)\n\t\tdo\n\t\t{\n\t\t\tx++;\n\t\t}\n\t\twhile (x < 6);\n",
        "\tif (a)\n\t\tdo\n\t\t\tx++;\n\t\twhile (x < 3);\n\telse\n\t\tx = 2;\n",
        "\tif (a)\n\t\tdo\n\t\t\tdo x++; while (x < 2);\n\t\twhile (x < 3);\n\tx = 4;\n",
        "\tif (a)\n\t\tdo\n\t\t\twhile (x < 2)\n\t\t\t\tx++;\n\t\twhile (x < 3);\n\tx = 4;\n",
        "\tdo {\n\t\tx++;\n\t} while (x < 3);\n\twhile (x < 5)\n\t\tx++;\n",
    ],
)
def test_do_while_closing_while_aligns_with_an_unbraced_do(body: str) -> None:
    source = _in_main(body)
    assert formatted(source, indent_style="tabs") == source


@pytest.mark.parametrize(
    "body",
    [
        '\tif (x)\n\t\tprintf("%s\\n"\n\t\t\t"tail %d\\n",\n\t\t\t"head",\n\t\t\tx\n\t\t);\n',
        "\tint[] v = [1];\n\tif (x)\n\t\tv = [\n\t\t\t1,\n\t\t\t2\n\t\t];\n",
        '\tif (a)\n\t\tif (x)\n\t\t\tprintf(\n\t\t\t\t"%d\\n",\n\t\t\t\tx\n\t\t\t);\n\t\telse\n\t\t\tx = 2;\n',
    ],
)
def test_closing_bracket_line_in_an_unbraced_body_stays_with_its_statement(body: str) -> None:
    source = _in_main(body)
    assert formatted(source, indent_style="tabs", single_line_statements=False) == source


def test_wrapped_call_in_an_unbraced_body_closes_at_the_body_level() -> None:
    source = _in_main('\tif (x)\n\t\tprintf("%d %d %d\\n", alpha, beta, gamma);\n')
    result = formatted(source, indent_style="tabs", line_width=40)
    assert "\n\t\t);\n" in result
    assert "\n\t);\n" not in result
    assert formatted(result, indent_style="tabs", line_width=40) == result


@pytest.mark.parametrize(
    "source",
    [
        'import "relhelpers/QuotedMsg.btrc"\n\nint main() { return 0; }\n',
        'import "a.btrc"\nimport "b.btrc"\n\nint main() { return 0; }\n',
    ],
)
def test_line_after_a_semicolon_less_quoted_import_is_not_a_string_continuation(source: str) -> None:
    assert formatted(source, indent_style="tabs") == source


@pytest.mark.parametrize(
    "source",
    [
        'string usage() {\n\treturn "usage: tool [options]\\n"\n\t\t"  -h  help\\n"\n\t\t"  -v  verbose\\n";\n}\n',
        'class Tool {\n\tpublic string usage() {\n\t\treturn "usage: tool\\n"\n\t\t\t"  -h  help\\n";\n\t}\n}\n',
        'string usage() { return "usage: tool [options]\\n" "  -h  help\\n"; }\n',
    ],
)
def test_trivial_function_compaction_keeps_split_string_pieces(source: str) -> None:
    assert formatted(source, indent_style="tabs") == source


@pytest.mark.parametrize(
    "body",
    [
        "\tif (a)\n\t\tdo if (b) x++; while (x < 3);\n\telse\n\t\tx = 2;\n",
        "\tif (a)\n\t\tdo if (b) { x++; } while (x < 3);\n\telse\n\t\tx = 2;\n",
        "\tif (a)\n\t\tdo\n\t\t\tif (b) x++; while (x < 3);\n\telse\n\t\tx = 2;\n",
        "\tif (a)\n\t\tif (b) do\n\t\t\tif (x) x++;\n\t\twhile (x < 0);\n\t\telse x = 2;\n",
    ],
)
def test_ifs_inside_an_unbraced_do_body_close_with_its_while(body: str) -> None:
    source = _in_main(body)
    assert formatted(source, indent_style="tabs") == source


@pytest.mark.parametrize(
    "body",
    [
        "\tswitch (x) {\n\t\tcase 0:\n\t\t\tif (a)\n\t\t\t\tx = 1;\n\t\tdefault: break;\n\t}\n",
        "\tswitch (x) {\n\t\tcase 0:\n\t\t\ttry {\n\t\t\t\tx = 1;\n\t\t\t} catch (string error) {\n"
        "\t\t\t\tx = 2;\n\t\t\t}\n\t\tdefault: break;\n\t}\n",
        "\tvar f = (int y) => y;\n\tf =\n\t\t(int y) => {\n\t\t\treturn y;\n\t\t};\n",
        "\tThread<int> t = a > 0\n\t\t? spawn(() => { return 1; })\n\t\t: spawn(() => { return 2; });\n",
    ],
)
def test_a_body_opened_on_a_continuation_line_nests_past_it(body: str) -> None:
    source = _in_main(body)
    assert formatted(source, indent_style="tabs") == source


_WRAPPED_TYPE_HEADERS = [
    "class Pair<\n\tA, B> {\n\tprivate A _a;\n}\n",
    "class Pair<\n\tA, B>\n{\n\tprivate A _a;\n}\n",
    "interface I {\n\tint f();\n}\n\nclass R<A>\n\timplements I {\n\tpublic int f() { return 0; }\n}\n",
    "interface I {\n\tint f();\n}\n\nclass R\n\timplements I {\n\tpublic int f() { return 0; }\n}\n",
    "class Base {\n}\n\nclass D<A,\n\tB>\n\textends Base {\n\tprivate A _a;\n\tpublic void m() {\n"
    "\t\tif (true) {\n\t\t\treturn;\n\t\t}\n\t}\n}\n",
]


@pytest.mark.parametrize("source", _WRAPPED_TYPE_HEADERS)
def test_a_wrapped_type_header_keeps_its_body_one_level_in_from_the_keyword(source: str) -> None:
    result = formatted(source, indent_style="tabs")
    assert result == source
    assert formatted(result, indent_style="tabs") == result


@pytest.mark.parametrize("expected", _WRAPPED_TYPE_HEADERS)
def test_a_wrapped_type_header_body_is_reindented_from_any_indentation(expected: str) -> None:
    flattened = "\n".join(line.lstrip("\t") for line in expected.split("\n"))
    deepened = "\n".join("\t\t" + line if line else line for line in expected.split("\n"))
    for source in (flattened, deepened):
        result = formatted(source, indent_style="tabs")
        assert result == expected
        assert formatted(result, indent_style="tabs") == result


def test_a_struct_typed_declaration_continuation_is_not_a_type_header() -> None:
    source = "struct P {\n\tint x;\n};\n\nint main() {\n\tstruct P p =\n\t\t{1};\n\treturn 0;\n}\n"
    assert formatted(source, indent_style="tabs") == source
