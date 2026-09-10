"""btrc source spells the names it owns in camelCase.

btrc's convention is camelCase members, parameters and locals over PascalCase
types. The Python reference compiler keeps Python's snake_case; neither
language borrows the other's spelling. Every `.btrc` file in the repository is
held to this, not just the self-hosted compiler.

The exceptions are all foreign names, which must keep the spelling C gave
them, and each has a source rather than a hand-written list that would drift:
the hosted-ABI repository covers `size_t` and its neighbours, the
repository's own C and Objective-C sources cover the stdlib shims, native
fixtures and example packages that btrc links against, and a small tuple below
covers system-header struct members, which have no declaration site to consult
because btrc passes `entry->d_name` straight through to C.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from src.compiler.python.abi.hosted import HostedAbiRepository
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.syntax.tokens import TokenKind

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"

_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")

# Members of structures the system headers declare. btrc has no declaration
# for these -- a member access on a foreign pointer is emitted verbatim -- so
# unlike every other foreign name there is nothing in the tree to read them
# from. Each is grouped by the structure that owns it.
_PLATFORM_STRUCT_MEMBERS = frozenset(
    {
        "d_name",  # struct dirent
        "decimal_point",  # struct lconv
        "c_lflag",  # struct termios
        "it_interval",
        "it_value",  # struct itimerval
        "pw_dir",
        "pw_name",
        "pw_uid",  # struct passwd
        "rlim_cur",  # struct rlimit
        "rm_eo",
        "rm_so",  # regmatch_t
        "s_addr",  # struct in_addr
        "sin_addr",
        "sin_family",
        "sin_port",  # struct sockaddr_in
        "st_nlink",
        "st_size",  # struct stat
        "tm_hour",
        "tm_mday",
        "tm_min",
        "tm_mon",
        "tm_sec",
        "tm_year",  # struct tm
    }
)

_C_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])([A-Z])")


def _tracked(pattern: str) -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", pattern], capture_output=True, check=True, cwd=REPO, text=True
    ).stdout.split()
    assert listing, f"no tracked files match {pattern}"
    return listing


def _snake_case_of(name: str) -> str:
    return _CAMEL_BOUNDARY.sub(r"_\1", name).lower()


def _foreign_names() -> frozenset[str]:
    """Every C name the hosted ABI lets btrc source spell verbatim."""

    abi = HostedAbiRepository()
    return frozenset(
        abi.function_names
        | abi.macros
        | abi.objects
        | abi.types
        | abi.typedefs
        | abi.owned_names
        | abi.native_names
        | abi.native_internal_names
        | abi.platform_function_names
        | abi.platform_macro_names
        | abi.platform_object_names
        | abi.platform_type_names
        | abi.platform_typedef_names
    )


_FSTRING = re.compile(r'f"(?:[^"\\\n]|\\.)*"')
_INTERPOLATION = re.compile(r"\{[^{}]*\}")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _interpolated_names(text: str) -> set[str]:
    """Identifiers an f-string interpolates.

    The lexer hands back one token for the whole f-string, so a field named
    inside {...} never appears as an IDENT even though the analyzer resolves
    it like any other member access.
    """

    names: set[str] = set()
    for literal in _FSTRING.findall(text):
        for span in _INTERPOLATION.findall(literal):
            names.update(_WORD.findall(span))
    return names


def test_self_hosted_compiler_owns_only_camel_case_names() -> None:
    """The compiler is held to the narrowest allowlist.

    It links against no fixture and no example package, so the hosted ABI is
    the only foreign spelling it may borrow.
    """

    foreign = _foreign_names()
    sources = sorted(SELFHOST.rglob("*.btrc"))
    assert sources, "no self-hosted compiler sources found"
    offenders: dict[str, set[str]] = {}
    for source in sources:
        owned = _owned_snake_case_names(source, foreign)
        if owned:
            offenders[str(source.relative_to(REPO))] = owned

    assert not offenders, "btrc sources must spell owned names in camelCase: " + _report(offenders)


def _repository_c_names() -> frozenset[str]:
    """Identifiers the repository's own C and Objective-C sources spell.

    A stdlib shim, a native test fixture and an example package all expose C
    functions that btrc reaches by their C name, and C names them in
    snake_case. Respelling only the btrc side leaves the C definition behind
    and the program fails to link, so those spellings are read from the C
    sources rather than assumed.
    """

    names: set[str] = set()
    for pattern in ("*.c", "*.h", "*.m", "*.mm"):
        for relative in _tracked(pattern):
            source = _C_COMMENT.sub(" ", (REPO / relative).read_text(errors="ignore"))
            names.update(_WORD.findall(source))
    return frozenset(names)


def _owned_snake_case_names(source: Path, foreign: frozenset[str]) -> set[str]:
    """Snake_case identifiers a btrc source spells that no foreign name explains."""

    text = source.read_text()
    spelled = {
        token.value for token in Lexer(text, str(source)).tokenize() if token.type is TokenKind.IDENT
    } | _interpolated_names(text)
    return {name for name in spelled if _SNAKE_CASE.match(name) and name not in foreign}


def _report(offenders: dict[str, set[str]]) -> str:
    return "; ".join(f"{path}: {', '.join(sorted(names))}" for path, names in sorted(offenders.items()))


def test_every_btrc_source_owns_only_camel_case_names() -> None:
    """The convention covers the stdlib, the corpus and the examples too."""

    foreign = _foreign_names() | _repository_c_names() | _PLATFORM_STRUCT_MEMBERS
    offenders: dict[str, set[str]] = {}
    for relative in _tracked("*.btrc"):
        owned = _owned_snake_case_names(REPO / relative, foreign)
        if owned:
            offenders[relative] = owned

    assert not offenders, "btrc sources must spell owned names in camelCase: " + _report(offenders)


def test_no_extern_was_respelled_away_from_its_c_definition() -> None:
    """An `extern` names a C symbol, so respelling it strands the definition.

    This is the failure mode the camelCase migration hit: an example package's
    btrc started declaring `leafValue` while its header still defined
    `leaf_value`, and the link failed with an undefined symbol. Rather than
    keep a list of the symbols C owns -- libc's are declared in headers this
    repository cannot read -- the check looks for the fingerprint of a
    half-finished rename: an extern the C sources do not spell, whose
    snake_case form they do.
    """

    declaration = re.compile(r"^\s*extern\b[^;{]*?\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    native = _repository_c_names()
    offenders: dict[str, set[str]] = {}
    for relative in _tracked("*.btrc"):
        for line in (REPO / relative).read_text(errors="ignore").splitlines():
            match = declaration.match(line)
            if not match:
                continue
            name = match.group(1)
            if name not in native and _snake_case_of(name) in native:
                offenders.setdefault(relative, set()).add(name)

    assert not offenders, "externs respelled away from the C definition beside them: " + _report(offenders)


def test_every_btrc_file_is_named_in_pascal_case() -> None:
    """A btrc file is named for what it declares, so the name is PascalCase.

    No underscore and no leading lowercase letter, anywhere in the tree. The
    corpus runner keys golden output to the stem and the stdlib resolves
    `import Library.X` to `X.btrc`, so a name is API, not decoration.
    """

    offenders = sorted(
        relative
        for relative in _tracked("*.btrc")
        if "_" in Path(relative).stem or not Path(relative).stem[:1].isupper()
    )

    assert not offenders, "btrc file names must be PascalCase: " + ", ".join(offenders)


def test_every_golden_belongs_to_a_corpus_source() -> None:
    """`expected/<Stem>.stdout` and `<Stem>.btrc` are renamed together."""

    orphans: list[str] = []
    for relative in _tracked("*.stdout"):
        golden = Path(relative)
        if golden.parent.name != "expected":
            continue
        if not (REPO / golden.parent.parent / (golden.stem + ".btrc")).is_file():
            orphans.append(relative)

    assert not orphans, "golden output with no source: " + ", ".join(sorted(orphans))
