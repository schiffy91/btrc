"""Strict C11 boundaries for standard predefined preprocessing identifiers."""

from pathlib import Path

from src.tests.btrc.test_mutex_value_contract import _compile_pair, _strict_matrix

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


STANDARD_PREDEFINED_MACRO_SOURCE = r"""
    #define CHECK_SUM(first, ...) ((__LINE__ > 0 && sizeof(__FILE__) > 1 && ((first) + (__VA_ARGS__)) == 42) ? 0 : 1)
    int main() {
        const char* functionName = __func__;
        return CHECK_SUM(20, 22) == 0 && functionName[0] == 'm' ? 0 : 1;
    }
"""

EXTENDED_HORIZONTAL_SPACE_SOURCE = (
    "#\fdefine\fSUM(first,\v...)\f((first) + (__VA_ARGS__))\nint main() { return SUM(20, 22) == 42 ? 0 : 1; }\n"
)

DIRECT_PREDEFINED_VALUE_SOURCE = r"""
    int main() {
        var fileName = __FILE__;
        var buildDate = __DATE__;
        var buildTime = __TIME__;
        var sourceLine = __LINE__;
        var conforming = __STDC__;
        var hosted = __STDC_HOSTED__;
        var standardVersion = __STDC_VERSION__;
        return fileName[0] != '\0'
            && buildDate[0] != '\0'
            && buildTime[0] != '\0'
            && sourceLine > 0
            && conforming == 1
            && (hosted == 0 || hosted == 1)
            && standardVersion >= 201112L
            ? 0 : 1;
    }
"""


def test_standard_predefined_tokens_work_in_variadic_source_macros(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        STANDARD_PREDEFINED_MACRO_SOURCE,
        "standard-predefined-variadic-macro",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_c_horizontal_space_is_accepted_consistently_in_source_macros(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        EXTENDED_HORIZONTAL_SPACE_SOURCE,
        "extended-horizontal-space-macro",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_guaranteed_predefined_macros_have_inferable_c11_value_types(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        DIRECT_PREDEFINED_VALUE_SOURCE,
        "direct-predefined-values",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)
