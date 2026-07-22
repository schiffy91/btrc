"""Data models shared by semantic analysis and downstream consumers."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ast_nodes import (
    FieldDecl,
    FunctionDecl,
    MethodDecl,
    MethodSig,
    Program,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypeExpr,
)


class AnalyzerError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


@dataclass
class Diag:
    """One semantic diagnostic with optional source-file provenance."""

    message: str
    line: int
    col: int
    severity: str = "error"
    file: str | None = None


@dataclass
class ClassInfo:
    name: str
    generic_params: list[str] = field(default_factory=list)
    fields: dict[str, FieldDecl] = field(default_factory=dict)
    static_fields: dict[str, FieldDecl] = field(default_factory=dict)
    methods: dict[str, MethodDecl] = field(default_factory=dict)
    properties: dict[str, PropertyDecl] = field(default_factory=dict)
    field_owners: dict[str, str] = field(default_factory=dict)
    method_owners: dict[str, str] = field(default_factory=dict)
    property_owners: dict[str, str] = field(default_factory=dict)
    instance_storage: list[tuple[str, FieldDecl | PropertyDecl]] = field(default_factory=list)
    constructor: MethodDecl = None
    parent: str = None
    interfaces: list[str] = field(default_factory=list)
    is_abstract: bool = False
    is_cyclable: bool = False


@dataclass
class SymbolInfo:
    name: str
    type: TypeExpr
    kind: str = "variable"
    decl_line: int = 0
    decl_col: int = 0
    decl_file: str | None = None
    captures_environment: bool = False
    owned_storage: bool = False


@dataclass
class Occurrence:
    """An identifier use resolved to its recorded definition site."""

    kind: str
    name: str
    def_file: str | None = None
    def_line: int = 0
    def_col: int = 0


@dataclass
class Scope:
    symbols: dict[str, SymbolInfo] = field(default_factory=dict)
    parent: Scope = None

    def lookup(self, name: str) -> SymbolInfo | None:
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def define(self, name: str, info: SymbolInfo):
        self.symbols[name] = info


@dataclass
class InterfaceInfo:
    name: str
    methods: dict[str, MethodSig] = field(default_factory=dict)
    parent: str = None
    generic_params: list[str] = field(default_factory=list)


@dataclass
class AnalyzedProgram:
    program: Program
    generic_instances: dict[str, list[tuple[TypeExpr, ...]]]
    class_table: dict[str, ClassInfo]
    generic_method_instances: dict[tuple[str, str], list[tuple[tuple, tuple]]] = field(default_factory=dict)
    generic_method_call_args: dict[int, tuple] = field(default_factory=dict)
    function_table: dict[str, FunctionDecl] = field(default_factory=dict)
    global_var_types: dict[str, TypeExpr] = field(default_factory=dict)
    hosted_call_ids: set[int] = field(default_factory=set)
    typedef_table: dict[str, TypeExpr] = field(default_factory=dict)
    struct_table: dict[str, StructDecl] = field(default_factory=dict)
    node_types: dict[int, TypeExpr] = field(default_factory=dict)
    enum_table: dict[str, list[str]] = field(default_factory=dict)
    interface_table: dict[str, InterfaceInfo] = field(default_factory=dict)
    rich_enum_table: dict[str, RichEnumDecl] = field(default_factory=dict)
    rich_enum_unsafe_default_ids: set[int] = field(default_factory=set)
    array_iteration_capacity_ids: set[int] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diags: list[Diag] = field(default_factory=list)
    occurrences: dict[int, Occurrence] = field(default_factory=dict)


__all__ = [
    "AnalyzedProgram",
    "AnalyzerError",
    "ClassInfo",
    "Diag",
    "InterfaceInfo",
    "Occurrence",
    "Scope",
    "SymbolInfo",
]
