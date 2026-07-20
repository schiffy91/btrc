"""Top-level declarations in the structured IR."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .expr_nodes import CType, IRExpr

if TYPE_CHECKING:
    from .nodes import IRParam


def _is_c_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and bool(value)
        and (value[0].isalpha() or value[0] == "_")
        and all(char.isalnum() or char == "_" for char in value[1:])
    )


def _contains_c11_trigraph(value: str) -> bool:
    suffixes = "=/'()!<>-"
    return any(value[index : index + 2] == "??" and value[index + 2] in suffixes for index in range(len(value) - 2))


@dataclass
class IRStructForward:
    """A ``typedef struct Name Name`` declaration."""

    name: str


@dataclass
class IRFunctionPointerTypedef:
    """A named C function-pointer type."""

    name: str
    return_type: CType
    param_types: list[CType] = field(default_factory=list)


@dataclass
class IRFunctionDecl:
    """A function prototype with explicit storage metadata."""

    name: str
    return_type: CType
    params: list[IRParam] = field(default_factory=list)
    is_static: bool = False


@dataclass(frozen=True)
class IRInclude:
    """A system ``<header>`` or local ``"header"`` include."""

    header: str
    is_system: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.header, str):
            raise TypeError("IRInclude.header must be a string")
        if not isinstance(self.is_system, bool):
            raise TypeError("IRInclude.is_system must be a bool")
        has_control = any(ord(char) < 0x20 or ord(char) == 0x7F for char in self.header)
        if (
            not self.header
            or has_control
            or any(char in self.header for char in '<>"')
            or _contains_c11_trigraph(self.header)
        ):
            raise ValueError(f"invalid structured include: {self.header!r}")


@dataclass
class IRMacroDef:
    """An object-like or function-like preprocessor macro."""

    name: str
    params: list[str] | None = None
    replacement: str = ""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("IRMacroDef.name must be a string")
        if not _is_c_identifier(self.name):
            raise ValueError(f"invalid macro name: {self.name!r}")
        if self.params is not None:
            if not isinstance(self.params, list):
                raise TypeError("IRMacroDef.params must be a list or None")
            if any(
                not _is_c_identifier(param) and not (param == "..." and index == len(self.params) - 1)
                for index, param in enumerate(self.params)
            ):
                raise ValueError("invalid macro parameter")
            if len(self.params) != len(set(self.params)):
                raise ValueError("duplicate macro parameter")
        if not isinstance(self.replacement, str):
            raise TypeError("IRMacroDef.replacement must be a string")
        if any(char in self.replacement for char in "\0\r\n"):
            raise ValueError("macro replacement must fit on one source line")
        if self.replacement.endswith("\\"):
            raise ValueError("multi-line macros are unsupported")


@dataclass
class IRStructField:
    """A field in a C struct."""

    c_type: CType
    name: str
    array_size: IRExpr = None


@dataclass
class IRStructDef:
    """A C struct definition."""

    name: str
    fields: list[IRStructField] = field(default_factory=list)
    pack_alignment: int | None = None


@dataclass
class IRTypedefDef:
    """A named alias for a resolved C type."""

    target_type: CType
    name: str


@dataclass
class IRTaggedUnionVariant:
    """One payload variant in a tagged-union definition."""

    name: str
    fields: list[IRStructField] = field(default_factory=list)


@dataclass
class IRTaggedUnionDef:
    """A named struct containing a tag and optional variant payload union."""

    name: str
    tag_type: CType
    variants: list[IRTaggedUnionVariant] = field(default_factory=list)


@dataclass
class IRGlobalDecl:
    """A typed file-scope variable declaration."""

    c_type: CType
    name: str
    init: IRExpr = None
    array_size: IRExpr = None
    is_static: bool = True
    is_extern: bool = False
    is_volatile: bool = False


@dataclass
class IRHelperDecl:
    """A runtime helper with its source and dependency metadata."""

    category: str
    name: str
    c_source: str
    depends_on: list[str] = field(default_factory=list)
    required_headers: list[str] = field(default_factory=list)


@dataclass
class IREnumValue:
    """A value in a C enum."""

    name: str
    value: IRExpr | None = None


@dataclass
class IREnumDef:
    """A named C enum typedef, or an anonymous C enum declaration."""

    name: str | None
    values: list[IREnumValue] = field(default_factory=list)
