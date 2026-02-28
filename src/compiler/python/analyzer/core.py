"""Analyzer core: data structures, scope management, and orchestration."""

from __future__ import annotations
from dataclasses import dataclass, field

from ..ast_nodes import (
    ClassDecl, FieldDecl, FunctionDecl, InterfaceDecl, MethodDecl,
    MethodSig, Program, PropertyDecl, RichEnumDecl, TypeExpr,
)


class AnalyzerError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


@dataclass
class ClassInfo:
    name: str
    generic_params: list[str] = field(default_factory=list)
    fields: dict[str, FieldDecl] = field(default_factory=dict)
    methods: dict[str, MethodDecl] = field(default_factory=dict)
    properties: dict[str, PropertyDecl] = field(default_factory=dict)
    constructor: MethodDecl = None
    parent: str = None
    interfaces: list[str] = field(default_factory=list)
    is_abstract: bool = False
    # ARC: true if this class can participate in reference cycles
    # (has class-type fields that could transitively reference self)
    is_cyclable: bool = False


@dataclass
class SymbolInfo:
    name: str
    type: TypeExpr
    kind: str = "variable"  # "variable" | "function" | "param"


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
    function_table: dict[str, FunctionDecl] = field(default_factory=dict)
    node_types: dict[int, TypeExpr] = field(default_factory=dict)
    enum_table: dict[str, list[str]] = field(default_factory=dict)
    interface_table: dict[str, InterfaceInfo] = field(default_factory=dict)
    rich_enum_table: dict[str, RichEnumDecl] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class AnalyzerBase:
    def __init__(self):
        self.class_table: dict[str, ClassInfo] = {}
        self.function_table: dict[str, FunctionDecl] = {}
        self.generic_instances: dict[str, list[tuple[TypeExpr, ...]]] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.scope: Scope = Scope()
        self.global_scope: Scope = self.scope
        self.current_class: ClassInfo | None = None
        self.current_method: MethodDecl | None = None
        self.current_return_type: TypeExpr | None = None
        self.in_gpu_function: bool = False
        self.node_types: dict[int, TypeExpr] = {}
        self.loop_depth: int = 0
        self.break_depth: int = 0
        self.enum_table: dict[str, list[str]] = {}
        self.interface_table: dict[str, InterfaceInfo] = {}
        self.rich_enum_table: dict[str, RichEnumDecl] = {}

    def analyze(self, program: Program) -> AnalyzedProgram:
        self._register_declarations(program)
        self._resolve_interface_parents(program)
        self._validate_inheritance(program)
        self._validate_interfaces(program)
        self._validate_overrides(program)
        self._compute_cyclable_flags()
        for decl in program.declarations:
            self._analyze_decl(decl)
        return AnalyzedProgram(
            program=program,
            generic_instances=self.generic_instances,
            class_table=self.class_table,
            function_table=self.function_table,
            node_types=self.node_types,
            enum_table=self.enum_table,
            interface_table=self.interface_table,
            rich_enum_table=self.rich_enum_table,
            errors=self.errors,
            warnings=self.warnings,
        )

    def _compute_cyclable_flags(self):
        """Mark classes that can participate in reference cycles.

        A class is cyclable if it has class-type fields that could
        transitively reference the class itself. This is computed via a
        fixed-point algorithm: start with classes that directly reference
        themselves, then propagate to classes that reference cyclable classes.
        """
        # Build adjacency: class → set of class types referenced in its fields
        refs: dict[str, set[str]] = {}
        for name, ci in self.class_table.items():
            field_types: set[str] = set()
            for _fn, fd in ci.fields.items():
                if fd.type and fd.type.base in self.class_table:
                    field_types.add(fd.type.base)
                # Generic type parameter could be anything — can't know statically
                if fd.type and fd.type.generic_args:
                    for ga in fd.type.generic_args:
                        if ga.base in self.class_table:
                            field_types.add(ga.base)
            refs[name] = field_types

        # Fixed-point: mark classes that can reach themselves
        cyclable: set[str] = set()
        changed = True
        while changed:
            changed = False
            for name in refs:
                if name in cyclable:
                    continue
                # Can this class reach itself through field references?
                visited: set[str] = set()
                stack = list(refs.get(name, set()))
                while stack:
                    cur = stack.pop()
                    if cur in visited:
                        continue
                    visited.add(cur)
                    if cur == name:
                        cyclable.add(name)
                        changed = True
                        break
                    stack.extend(refs.get(cur, set()))

        for name in cyclable:
            self.class_table[name].is_cyclable = True

    def _error(self, msg: str, line: int = 0, col: int = 0):
        self.errors.append(f"{msg} at {line}:{col}")

    def _warning(self, msg: str, line: int = 0, col: int = 0):
        self.warnings.append(f"{msg} at {line}:{col}")

    def _push_scope(self):
        self.scope = Scope(parent=self.scope)

    def _pop_scope(self):
        self.scope = self.scope.parent
