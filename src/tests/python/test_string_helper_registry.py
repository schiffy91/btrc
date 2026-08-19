"""Contracts for the string families in the shared runtime catalog."""

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog
from src.compiler.python.runtime.generated import RUNTIME_HELPER_ROWS

EXPECTED_OPERATION_HELPERS = (
    "__btrc_substring",
    "__btrc_trim",
    "__btrc_toUpper",
    "__btrc_toLower",
    "__btrc_replace",
    "__btrc_split",
    "__btrc_repeat",
    "__btrc_reverse",
    "__btrc_removePrefix",
    "__btrc_removeSuffix",
    "__btrc_capitalize",
    "__btrc_title",
    "__btrc_swapCase",
    "__btrc_padLeft",
    "__btrc_padRight",
    "__btrc_center",
    "__btrc_lstrip",
    "__btrc_rstrip",
    "__btrc_zfill",
    "__btrc_strcat",
    "__btrc_join",
)


def test_operation_helpers_keep_their_public_names_and_order() -> None:
    names = [row.name for row in RUNTIME_HELPER_ROWS if row.category == "string"]
    start = names.index(EXPECTED_OPERATION_HELPERS[0])

    assert tuple(names[start : start + len(EXPECTED_OPERATION_HELPERS)]) == EXPECTED_OPERATION_HELPERS


def test_substring_clamps_without_adding_signed_integers() -> None:
    rows = {row.name: row for row in RUNTIME_HELPER_ROWS}
    source = rows["__btrc_substring"].c_source

    assert "if (len > slen - start) len = slen - start;" in source
    assert "start + len" not in source


def test_string_helpers_only_use_checked_allocation_and_known_dependencies() -> None:
    rows = {row.name: row for row in RUNTIME_HELPER_ROWS}
    string_rows = tuple(
        row for row in RUNTIME_HELPER_ROWS if row.category in {"string_ownership", "string_pool", "string"}
    )

    for row in string_rows:
        assert "(char*)malloc(" not in row.c_source
        assert "(char**)realloc(" not in row.c_source
        assert set(row.depends_on) <= rows.keys()


def test_common_helpers_precede_public_string_operations() -> None:
    rows = [row for row in RUNTIME_HELPER_ROWS if row.category == "string"]
    names = [row.name for row in rows]
    string_alloc = next(row for row in rows if row.name == "__btrc_string_alloc")

    assert names[:6] == [
        "__btrc_string_or_empty",
        "__btrc_string_length",
        "__btrc_string_alloc",
        "__btrc_ascii_upper",
        "__btrc_ascii_lower",
        "__btrc_ascii_space",
    ]
    assert string_alloc.depends_on == (
        "__btrc_safe_realloc",
        "__btrc_string_adopt",
    )


def test_string_families_are_generated_once_for_both_compilers() -> None:
    rows = {row.name: row for row in RUNTIME_HELPER_ROWS}
    catalog = RuntimeHelperCatalog()
    selected = {row.name: row for row in catalog.definitions_for({"__btrc_join"})}

    assert selected["__btrc_join"] is rows["__btrc_join"]
    assert "__btrc_string_alloc" in selected
    assert "__btrc_string_adopt" in selected
    assert "__btrc_safe_realloc" in selected


def test_string_family_categories_are_complete_and_disjoint() -> None:
    grouped = {
        category: {row.name for row in RUNTIME_HELPER_ROWS if row.category == category}
        for category in ("string_ownership", "string_pool", "string")
    }

    assert all(grouped.values())
    assert grouped["string_ownership"].isdisjoint(grouped["string_pool"])
    assert grouped["string_ownership"].isdisjoint(grouped["string"])
    assert grouped["string_pool"].isdisjoint(grouped["string"])
    assert set(EXPECTED_OPERATION_HELPERS) <= grouped["string"]
