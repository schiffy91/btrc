"""Pass 1: Register declarations and validate inheritance/interfaces."""

from ..ast_nodes import (
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    InterfaceDecl,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
    VarDeclStmt,
)
from ..class_storage import instance_storage_name
from .core import ClassInfo, InterfaceInfo


class RegistrationMixin:
    def _register_declarations(self, program):
        # Deep left-leaning expression chains (a+a+...+a) recurse one Python
        # frame per term in _analyze_expr/_infer_type. The default limit
        # (1000) rejects real programs; CPython 3.12+ heap-allocates pure
        # Python frames, so a higher limit is safe here.
        import sys

        if sys.getrecursionlimit() < 40000:
            sys.setrecursionlimit(40000)
        # The LSP seeds fresh analyzers with an already-resolved stdlib symbol
        # table.  Preserve the identity of those ClassInfo objects so parent
        # metadata is not merged (or shadow-validated) a second time below.
        pre_resolved_classes = {id(info) for info in self.class_table.values()}
        self._initialize_registration_state(program)
        for decl in self._decls_with_file(program):
            if isinstance(decl, InterfaceDecl):
                self._register_interface(decl)
        # Struct/enum/typedef names, available before pass 2 runs (cast
        # validation needs them regardless of declaration order).
        self.declared_type_names: set[str] = set()
        for decl in self._decls_with_file(program):
            if isinstance(decl, ClassDecl):
                self._register_class(decl)
            elif isinstance(decl, FunctionDecl):
                self._register_function(decl)
            elif isinstance(decl, StructDecl):
                self._register_struct(decl)
            elif isinstance(decl, EnumDecl):
                self._register_simple_enum(decl)
            elif isinstance(decl, RichEnumDecl):
                self._register_rich_enum(decl)
            elif isinstance(decl, TypedefDecl):
                self._claim_top_level_name(
                    decl.alias,
                    "typedef",
                    decl.name_line or decl.line,
                    decl.name_col or decl.col,
                )
                self.declared_type_names.add(decl.alias)
                self.typedef_table[decl.alias] = decl.original
            elif isinstance(decl, VarDeclStmt):
                self._register_global(decl)
        self._resolve_class_parents(pre_resolved_classes)

    def _register_interface(self, decl):
        self._claim_top_level_name(
            decl.name,
            "interface",
            decl.name_line or decl.line,
            decl.name_col or decl.col,
        )
        self._validate_generic_parameter_names(
            decl.generic_params,
            f"interface '{decl.name}'",
            decl.line,
            decl.col,
        )
        info = InterfaceInfo(name=decl.name, parent=decl.parent, generic_params=decl.generic_params)
        for method in decl.methods:
            self._validate_declared_name(
                method.name,
                "Interface method",
                method.name_line or method.line,
                method.name_col or method.col,
                allow_magic=True,
                c_name_generated=True,
            )
            self._validate_parameter_names(
                method.params,
                f"interface method '{decl.name}.{method.name}'",
            )
            self._validate_array_return_declaration(method, decl.name)
            if method.name in info.methods:
                self._error(
                    f"Duplicate method '{method.name}' in interface '{decl.name}'",
                    method.line,
                    method.col,
                )
            info.methods[method.name] = method
        self.interface_table[decl.name] = info

    def _resolve_interface_parents(self, program):
        """Resolve inherited methods in dependency order and reject cycles."""
        declarations = {decl.name: decl for decl in self._decls_with_file(program) if isinstance(decl, InterfaceDecl)}
        visiting: set[str] = set()
        done: set[str] = set()

        def resolve(name: str):
            if name in done:
                return
            declaration = declarations[name]
            if name in visiting:
                self._error(f"Circular interface inheritance involving '{name}'", declaration.line, declaration.col)
                return
            visiting.add(name)
            info = self.interface_table[name]
            if info.parent:
                if info.parent not in self.interface_table:
                    self._error(f"Parent interface '{info.parent}' not found", declaration.line, declaration.col)
                else:
                    resolve(info.parent)
                    parent = self.interface_table[info.parent]
                    inherited = dict(parent.methods)
                    inherited.update(info.methods)
                    info.methods = inherited
            visiting.remove(name)
            done.add(name)

        for name in declarations:
            resolve(name)

    def _register_class(self, decl):
        self._claim_top_level_name(
            decl.name,
            "class",
            decl.name_line or decl.line,
            decl.name_col or decl.col,
        )
        self._validate_generic_parameter_names(
            decl.generic_params,
            f"class '{decl.name}'",
            decl.line,
            decl.col,
        )
        info = ClassInfo(
            name=decl.name,
            generic_params=decl.generic_params,
            parent=decl.parent,
            interfaces=decl.interfaces,
            is_abstract=decl.is_abstract,
        )
        declared_fields: set[str] = set()
        declared_methods: set[str] = set()
        declared_properties: set[str] = set()
        declared_members: dict[str, str] = {}
        storage_names = {"__arc", "__rc", "__cycle_safe_rc"}
        for member in decl.members:
            if isinstance(member, FieldDecl):
                self._validate_declared_name(
                    member.name,
                    "Field",
                    member.name_line or member.line,
                    member.name_col or member.col,
                )
                if member.name in declared_fields:
                    self._error(f"Duplicate field '{member.name}' in class '{decl.name}'", member.line, member.col)
                declared_fields.add(member.name)
                self._claim_member_name(decl, member, "field", declared_members)
                target = info.static_fields if member.access == "class" else info.fields
                target[member.name] = member
                info.field_owners[member.name] = decl.name
            elif isinstance(member, MethodDecl):
                self._validate_declared_name(
                    member.name,
                    "Method",
                    member.name_line or member.line,
                    member.name_col or member.col,
                    allow_magic=True,
                    c_name_generated=True,
                )
                self._validate_generic_parameter_names(
                    member.generic_params,
                    f"method '{decl.name}.{member.name}'",
                    member.line,
                    member.col,
                )
                self._validate_parameter_names(
                    member.params,
                    f"method '{decl.name}.{member.name}'",
                )
                if member.name in declared_methods:
                    self._error(f"Duplicate method '{member.name}' in class '{decl.name}'", member.line, member.col)
                declared_methods.add(member.name)
                self._claim_member_name(decl, member, "method", declared_members)
                if member.is_constructor:
                    info.constructor = member
                info.methods[member.name] = member
                info.method_owners[member.name] = decl.name
            elif isinstance(member, PropertyDecl):
                self._validate_declared_name(
                    member.name,
                    "Property",
                    member.name_line or member.line,
                    member.name_col or member.col,
                    c_name_generated=True,
                )
                if member.name in declared_properties:
                    self._error(
                        f"Duplicate property '{member.name}' in class '{decl.name}'",
                        member.line,
                        member.col,
                    )
                declared_properties.add(member.name)
                self._claim_member_name(decl, member, "property", declared_members)
                info.properties[member.name] = member
                info.property_owners[member.name] = decl.name
            storage_name = instance_storage_name(member)
            if storage_name is not None:
                if storage_name in storage_names:
                    self._error(
                        f"Instance storage name '{storage_name}' collides with another member in class '{decl.name}'",
                        member.line,
                        member.col,
                    )
                else:
                    storage_names.add(storage_name)
                    info.instance_storage.append((storage_name, member))
        self.class_table[decl.name] = info
