"""Owned declaration indexes and pass-one semantic registration."""

from __future__ import annotations

import sys

from ...ast_nodes import (
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    InterfaceDecl,
    MethodDecl,
    Program,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
    TypeExpr,
    VarDeclStmt,
)
from ...class_storage import instance_storage_name
from ..analysis_context import AnalysisContext
from ..core_models import AnalyzedProgram, ClassInfo, InterfaceInfo, Scope
from .inheritance import InheritanceResolver
from .policy import DeclarationPolicy
from .top_level import TopLevelRegistrar


class DeclarationRegistry:
    """Own declaration tables and the complete pass-one registration cascade."""

    def __init__(
        self,
        context: AnalysisContext,
        global_scope: Scope,
        *,
        seed: AnalyzedProgram | None = None,
    ) -> None:
        self.context = context
        self.global_scope = global_scope
        self.class_table: dict[str, ClassInfo] = {}
        self.function_table: dict[str, FunctionDecl] = {}
        self.typedef_table: dict[str, TypeExpr] = {}
        self.struct_table: dict[str, StructDecl] = {}
        self.enum_table: dict[str, list[str]] = {}
        self.interface_table: dict[str, InterfaceInfo] = {}
        self.rich_enum_table: dict[str, RichEnumDecl] = {}
        self.declared_type_names: set[str] = set()
        self.top_level_kinds: dict[str, str] = {}
        self.source_macro_names: set[str] = set()
        self.source_macro_definitions: dict[str, object] = {}
        self.enum_member_owners: dict[str, set[str]] = {}
        self.enum_constant_values: dict[tuple[str, str], int | None] = {}
        self.global_declarations: dict[str, object] = {}
        self.global_definitions: dict[str, object] = {}
        self.struct_definitions: dict[str, object] = {}
        self.policy = DeclarationPolicy(context, self)
        self.top_level = TopLevelRegistrar(self)
        self.inheritance = InheritanceResolver(self)
        if seed is not None:
            self.seed(seed)

    def seed(self, analyzed: AnalyzedProgram) -> None:
        self.class_table = dict(analyzed.class_table)
        self.function_table = dict(analyzed.function_table)
        self.typedef_table = dict(analyzed.typedef_table)
        self.struct_table = dict(analyzed.struct_table)
        self.enum_table = {name: list(values) for name, values in analyzed.enum_table.items()}
        self.interface_table = dict(analyzed.interface_table)
        self.rich_enum_table = dict(analyzed.rich_enum_table)

    def register(self, program: Program) -> None:
        if sys.getrecursionlimit() < 40000:
            sys.setrecursionlimit(40000)
        pre_resolved_classes = {id(info) for info in self.class_table.values()}
        self.top_level.initialize(program)
        for declaration in self.context.declarations(program):
            if isinstance(declaration, InterfaceDecl):
                self._register_interface(declaration)
        self.declared_type_names = set()
        for declaration in self.context.declarations(program):
            if isinstance(declaration, ClassDecl):
                self._register_class(declaration)
            elif isinstance(declaration, FunctionDecl):
                self.top_level.register_function(declaration)
            elif isinstance(declaration, StructDecl):
                self.top_level.register_struct(declaration)
            elif isinstance(declaration, EnumDecl):
                self.top_level.enums.register_simple(declaration)
            elif isinstance(declaration, RichEnumDecl):
                self.top_level.enums.register_rich(declaration)
            elif isinstance(declaration, TypedefDecl):
                self.top_level.claim_name(
                    declaration.alias,
                    "typedef",
                    declaration.name_line or declaration.line,
                    declaration.name_col or declaration.col,
                )
                self.declared_type_names.add(declaration.alias)
                self.typedef_table[declaration.alias] = declaration.original
            elif isinstance(declaration, VarDeclStmt):
                self.top_level.register_global(declaration)
        self.inheritance.resolve(pre_resolved_classes)

    def resolve_interface_parents(self, program: Program) -> None:
        declarations = {
            declaration.name: declaration
            for declaration in self.context.declarations(program)
            if isinstance(declaration, InterfaceDecl)
        }
        visiting: set[str] = set()
        done: set[str] = set()

        def resolve(name: str) -> None:
            if name in done:
                return
            declaration = declarations[name]
            if name in visiting:
                self.context.error(
                    f"Circular interface inheritance involving '{name}'",
                    declaration.line,
                    declaration.col,
                )
                return
            visiting.add(name)
            info = self.interface_table[name]
            if info.parent:
                if info.parent not in self.interface_table:
                    self.context.error(
                        f"Parent interface '{info.parent}' not found",
                        declaration.line,
                        declaration.col,
                    )
                else:
                    resolve(info.parent)
                    inherited = dict(self.interface_table[info.parent].methods)
                    inherited.update(info.methods)
                    info.methods = inherited
            visiting.remove(name)
            done.add(name)

        for name in declarations:
            resolve(name)

    def _register_interface(self, declaration: InterfaceDecl) -> None:
        policy = self.policy
        self.top_level.claim_name(
            declaration.name,
            "interface",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
        )
        policy.validate_generic_parameter_names(
            declaration.generic_params,
            f"interface '{declaration.name}'",
            declaration.line,
            declaration.col,
        )
        info = InterfaceInfo(
            name=declaration.name,
            parent=declaration.parent,
            generic_params=declaration.generic_params,
        )
        for method in declaration.methods:
            policy.validate_name(
                method.name,
                "Interface method",
                method.name_line or method.line,
                method.name_col or method.col,
                allow_magic=True,
                c_name_generated=True,
            )
            policy.validate_parameter_names(
                method.params,
                f"interface method '{declaration.name}.{method.name}'",
            )
            policy.callables.validate_array_return(method, declaration.name)
            if method.name in info.methods:
                self.context.error(
                    f"Duplicate method '{method.name}' in interface '{declaration.name}'",
                    method.line,
                    method.col,
                )
            info.methods[method.name] = method
        self.interface_table[declaration.name] = info

    def _register_class(self, declaration: ClassDecl) -> None:
        policy = self.policy
        self.top_level.claim_name(
            declaration.name,
            "class",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
        )
        policy.validate_generic_parameter_names(
            declaration.generic_params,
            f"class '{declaration.name}'",
            declaration.line,
            declaration.col,
        )
        info = ClassInfo(
            name=declaration.name,
            generic_params=declaration.generic_params,
            parent=declaration.parent,
            interfaces=declaration.interfaces,
            is_abstract=declaration.is_abstract,
        )
        fields: set[str] = set()
        methods: set[str] = set()
        properties: set[str] = set()
        members: dict[str, str] = {}
        storage_names = {"__arc", "__rc", "__cycle_safe_rc"}
        for member in declaration.members:
            if isinstance(member, FieldDecl):
                policy.validate_name(
                    member.name,
                    "Field",
                    member.name_line or member.line,
                    member.name_col or member.col,
                )
                if member.name in fields:
                    self.context.error(
                        f"Duplicate field '{member.name}' in class '{declaration.name}'",
                        member.line,
                        member.col,
                    )
                fields.add(member.name)
                self.inheritance.claim_member_name(declaration, member, "field", members)
                target = info.static_fields if member.access == "class" else info.fields
                target[member.name] = member
                info.field_owners[member.name] = declaration.name
            elif isinstance(member, MethodDecl):
                policy.validate_name(
                    member.name,
                    "Method",
                    member.name_line or member.line,
                    member.name_col or member.col,
                    allow_magic=True,
                    c_name_generated=True,
                )
                policy.validate_generic_parameter_names(
                    member.generic_params,
                    f"method '{declaration.name}.{member.name}'",
                    member.line,
                    member.col,
                )
                policy.validate_parameter_names(
                    member.params,
                    f"method '{declaration.name}.{member.name}'",
                )
                if member.name in methods:
                    self.context.error(
                        f"Duplicate method '{member.name}' in class '{declaration.name}'",
                        member.line,
                        member.col,
                    )
                methods.add(member.name)
                self.inheritance.claim_member_name(declaration, member, "method", members)
                if member.is_constructor:
                    info.constructor = member
                info.methods[member.name] = member
                info.method_owners[member.name] = declaration.name
            elif isinstance(member, PropertyDecl):
                policy.validate_name(
                    member.name,
                    "Property",
                    member.name_line or member.line,
                    member.name_col or member.col,
                    c_name_generated=True,
                )
                if member.name in properties:
                    self.context.error(
                        f"Duplicate property '{member.name}' in class '{declaration.name}'",
                        member.line,
                        member.col,
                    )
                properties.add(member.name)
                self.inheritance.claim_member_name(declaration, member, "property", members)
                info.properties[member.name] = member
                info.property_owners[member.name] = declaration.name
            storage_name = instance_storage_name(member)
            if storage_name is not None:
                if storage_name in storage_names:
                    self.context.error(
                        f"Instance storage name '{storage_name}' collides with another member in class '{declaration.name}'",
                        member.line,
                        member.col,
                    )
                else:
                    storage_names.add(storage_name)
                    info.instance_storage.append((storage_name, member))
        self.class_table[declaration.name] = info


__all__ = ["DeclarationRegistry"]
