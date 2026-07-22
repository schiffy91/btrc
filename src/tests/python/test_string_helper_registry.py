"""Contracts for the split string-operation helper registry."""

import ast
import re
from pathlib import Path

from src.compiler.python.ir.helpers.alloc import ALLOC
from src.compiler.python.ir.helpers.string_ownership import STRING_OWNERSHIP
from src.compiler.python.ir.helpers.string_pool import STRING_POOL
from src.compiler.python.ir.helpers.strings import STRING
from src.compiler.python.ir.helpers.strings_common import STRING_COMMON
from src.compiler.python.ir.helpers.strings_composition import STRING_COMPOSITION
from src.compiler.python.ir.helpers.strings_layout import STRING_LAYOUT
from src.compiler.python.ir.helpers.strings_ops import STRING_OPS
from src.compiler.python.ir.helpers.strings_transform import STRING_TRANSFORM

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

_BRANCH_START_PATTERN = re.compile(
    r"^[ \t]+(?:\} )?(?:else )?if \((.*?)\) \{",
    re.MULTILINE | re.DOTALL,
)


def _named_branch_values(source: str, value_pattern: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    matches = list(_BRANCH_START_PATTERN.finditer(source))
    for index, match in enumerate(matches):
        condition = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        body = source[match.end() : end]
        names = re.findall(r'name == "([^"]+)"', condition)
        branch_values = re.findall(value_pattern, body)
        for name in names:
            values[name] = branch_values
    return values


def test_split_registry_preserves_public_names_and_emission_order():
    grouped_names = (
        *STRING_TRANSFORM,
        *STRING_LAYOUT,
        *STRING_COMPOSITION,
    )

    assert tuple(STRING_OPS) == EXPECTED_OPERATION_HELPERS
    assert grouped_names == EXPECTED_OPERATION_HELPERS
    for name in EXPECTED_OPERATION_HELPERS:
        assert STRING_OPS[name] is (STRING_TRANSFORM | STRING_LAYOUT | STRING_COMPOSITION)[name]


def test_substring_clamps_without_adding_signed_integers():
    source = STRING_OPS["__btrc_substring"].c_source

    assert "if (len > slen - start) len = slen - start;" in source
    assert "start + len" not in source


def test_string_helpers_only_use_checked_allocation_and_known_dependencies():
    all_helpers = ALLOC | STRING_OWNERSHIP | STRING_POOL | STRING

    for helper in (
        *STRING_OWNERSHIP.values(),
        *STRING_POOL.values(),
        *STRING.values(),
    ):
        assert "(char*)malloc(" not in helper.c_source
        assert "(char**)realloc(" not in helper.c_source
        assert set(helper.depends_on) <= set(all_helpers)


def test_common_helpers_precede_public_string_operations():
    assert tuple(STRING)[: len(STRING_COMMON)] == tuple(STRING_COMMON)
    assert STRING_COMMON["__btrc_string_alloc"].depends_on == [
        "__btrc_safe_realloc",
        "__btrc_string_adopt",
    ]


def test_self_hosted_string_helper_source_exactly_matches_python_registry():
    ir_source = Path("src/compiler/btrc/ir_nodes.btrc").read_text()
    core_catalog = Path("src/compiler/btrc/ir/runtime/core_catalog.btrc").read_text()
    ownership_runtime = Path("src/compiler/btrc/string_runtime_helpers.btrc").read_text()
    ownership_source = ownership_runtime.split("Vector<string> stringOwnershipRuntimeHelperDependencies", 1)[0]
    blocks: dict[str, str] = {}
    pattern = re.compile(
        r'^([ \t]+)if \(name == "([^"]+)"\) \{\n(.*?)^\1\}',
        re.MULTILINE | re.DOTALL,
    )
    for source in (core_catalog, ownership_source):
        for match in pattern.finditer(source):
            literals = re.findall(r'"(?:\\.|[^"\\])*"', match.group(3))
            blocks[match.group(2)] = "".join(ast.literal_eval(item) for item in literals)

    for name, helper in (STRING_OWNERSHIP | STRING_POOL | STRING).items():
        assert blocks.get(name) == helper.c_source, name

    ownership_dependencies = ownership_runtime.split("Vector<string> stringOwnershipRuntimeHelperDependencies", 1)[
        1
    ].split("Vector<string> stringOwnershipRuntimeHelperHeaders", 1)[0]
    dependency_map = _named_branch_values(ownership_dependencies, r'out\.push\("([^"]+)"\)')
    ownership_helpers = STRING_OWNERSHIP | STRING_POOL
    ownership_runtime_helpers = ownership_helpers | {
        name: STRING[name] for name in ("__btrc_string_or_empty", "__btrc_string_alloc")
    }
    for name, helper in ownership_runtime_helpers.items():
        assert dependency_map.get(name, []) == helper.depends_on, name

    ownership_headers = ownership_runtime.split("Vector<string> stringOwnershipRuntimeHelperHeaders", 1)[1].split(
        "void appendStringOwnershipRuntimeHelperOrder", 1
    )[0]
    header_map = _named_branch_values(ownership_headers, r'out\.push\("([^"]+)"\)')
    for name, helper in ownership_runtime_helpers.items():
        assert header_map.get(name, []) == helper.required_headers, name

    helper_dependencies = core_catalog.split("public Vector<string> dependencies", 1)[1]
    helper_dependency_map = _named_branch_values(helper_dependencies, r'out\.push\("([^"]+)"\)')
    for name, helper in STRING.items():
        if name not in {"__btrc_string_or_empty", "__btrc_string_alloc"}:
            assert helper_dependency_map.get(name, []) == helper.depends_on, name

    ownership_order = ownership_runtime.split("void appendStringOwnershipRuntimeHelperOrder", 1)[1]
    assert re.findall(r'order\.push\("([^"]+)"\)', ownership_order) == [*ownership_helpers]
    string_order = ir_source.split("/* string — STRING_COMMON */", 1)[1].split("/* math */", 1)[0]
    assert re.findall(r'order\.push\("([^"]+)"\)', string_order) == [*STRING]
