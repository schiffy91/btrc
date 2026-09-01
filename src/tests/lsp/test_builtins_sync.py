"""The checked-in LSP catalog must match the canonical compiler generator."""

from pathlib import Path, PureWindowsPath

from src.devex.lsp.catalog.builtins import BuiltinCatalog
from tools.compiler_codegen.builtins import BuiltinCatalogGenerator, BuiltinStdlibScanner

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKED_IN = REPO_ROOT / "src" / "devex" / "lsp" / "catalog" / "generated.py"


def test_builtin_source_order_is_independent_of_host_path_flavor():
    windows_paths = (
        PureWindowsPath("stdlib/array.btrc"),
        PureWindowsPath("stdlib/BitPattern.btrc"),
        PureWindowsPath("stdlib/background_jobs.btrc"),
    )

    ordered = sorted(windows_paths, key=BuiltinStdlibScanner._source_order_key)

    assert [path.name for path in ordered] == [
        "BitPattern.btrc",
        "array.btrc",
        "background_jobs.btrc",
    ]


def test_checked_in_builtins_matches_generator_output():
    artifact = BuiltinCatalogGenerator(REPO_ROOT).artifacts()[0]

    assert REPO_ROOT.joinpath(*artifact.path.parts) == CHECKED_IN
    assert artifact.content == CHECKED_IN.read_bytes(), (
        "src/devex/lsp/catalog/generated.py is stale — regenerate it with `make compiler-codegen-generate`"
    )


def test_realtime_primitive_surfaces_are_in_the_builtin_catalog():
    catalog = BuiltinCatalog()

    assert {member.name for member in catalog.members("Atomic<uint>")} == {
        "init",
        "load",
        "store",
        "exchange",
        "fetchAdd",
        "fetchSub",
        "fetchAnd",
        "fetchOr",
        "fetchXor",
        "compareExchangeStrong",
    }
    assert {member.name for member in catalog.members("Span<int>")} == {
        "length",
        "isEmpty",
        "isValid",
        "tryGet",
        "trySet",
    }
    assert {member.name for member in catalog.members("SpscQueue<int>")} == {
        "tryPush",
        "tryPop",
        "close",
    }
