"""Declaration registration, policy, hierarchy, and body ownership."""

from __future__ import annotations

import sys
from dataclasses import replace

from src.compiler.python.abi.declarations import AbiType
from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.program import (
    AnalysisContext,
    AnalysisSession,
    AnalyzedProgram,
    ClassInfo,
    DeclarationIndex,
    InterfaceInfo,
    SourceMacroNamespace,
    SymbolInfo,
)
from src.compiler.python.analyzer.types import TypeIdentity, TypeShapeError, TypeSystem
from src.compiler.python.frontend.sources import CompilerStdlibSource
from src.compiler.python.syntax.ast.generated import (
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    InterfaceDecl,
    MethodDecl,
    PreprocessorDirective,
    Program,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
    TypeExpr,
    VarDeclStmt,
)
from src.compiler.python.syntax.tokens import SourceSymbolDirective


class EnumRegistrar:
    def __init__(
        self,
        registry: DeclarationRegistry,
        names: TopLevelRegistrar,
        context: AnalysisContext,
        index: DeclarationIndex,
    ) -> None:
        self.registry = registry
        self.names = names
        self.context = context
        self.index = index

    def register_simple(self, declaration) -> None:
        registry = self.registry
        context = self.context
        policy = registry
        if not declaration.values:
            context.error(
                f"Enum '{declaration.name or '<anonymous>'}' requires at least one value",
                declaration.line,
                declaration.col,
            )
        if declaration.name:
            self.names.claim_name(
                declaration.name,
                "enum",
                declaration.name_line or declaration.line,
                declaration.name_col or declaration.col,
            )
            self.index.declared_type_names.add(declaration.name)
        values = []
        seen = set()
        for value in declaration.values:
            valid_name = policy.validate_name(
                value.name, "Enum value", value.line, value.col, c_name_generated=bool(declaration.name)
            )
            if valid_name and (not declaration.name) and HOSTED_ABI.owned_name(value.name):
                context.error(
                    f"Enum value name '{value.name}' collides with a compiler-owned hosted C symbol",
                    value.line,
                    value.col,
                )
            if value.name in seen:
                context.error(
                    f"Duplicate enum value '{value.name}' in enum '{declaration.name}'", value.line, value.col
                )
            seen.add(value.name)
            values.append(value.name)
            self.index.enum_member_owners.setdefault(value.name, set()).add(declaration.name)
            if not declaration.name:
                self.names.claim_name(value.name, "anonymous enum value", value.line, value.col)
        key = declaration.name or ""
        if key in self.index.enum_table and declaration.name:
            return
        if declaration.name:
            self.index.enum_table[key] = values
        else:
            self.index.enum_table.setdefault("", []).extend(values)

    def register_rich(self, declaration) -> None:
        registry = self.registry
        context = self.context
        policy = registry
        if not declaration.variants:
            context.error(
                f"Rich enum '{declaration.name}' requires at least one variant", declaration.line, declaration.col
            )
        self.names.claim_name(
            declaration.name, "enum", declaration.name_line or declaration.line, declaration.name_col or declaration.col
        )
        self.index.declared_type_names.add(declaration.name)
        variants = set()
        for variant in declaration.variants:
            policy.validate_name(variant.name, "Rich-enum variant", variant.line, variant.col, c_name_generated=True)
            if variant.name in variants:
                context.error(
                    f"Duplicate variant '{variant.name}' in rich enum '{declaration.name}'", variant.line, variant.col
                )
            variants.add(variant.name)
            policy.validate_parameter_names(variant.params, f"rich-enum variant '{declaration.name}.{variant.name}'")
        self.index.rich_enum_table[declaration.name] = declaration


class InheritanceResolver:
    def __init__(
        self,
        registry: DeclarationRegistry,
        context: AnalysisContext,
        index: DeclarationIndex,
    ) -> None:
        self.registry = registry
        self.context = context
        self.index = index

    def resolve(self, pre_resolved_classes=frozenset()) -> None:
        order: list[str] = []
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(name: str) -> None:
            if name in done or name in visiting:
                return
            visiting.add(name)
            info = self.index.class_table.get(name)
            if info and info.parent and (info.parent in self.index.class_table):
                visit(info.parent)
            visiting.discard(name)
            done.add(name)
            order.append(name)

        for name in self.index.class_table:
            visit(name)
        for name in order:
            info = self.index.class_table[name]
            if id(info) not in pre_resolved_classes:
                self._merge_parent(info)

    def claim_member_name(self, declaration, member, kind, declared) -> None:
        existing = declared.get(member.name)
        if existing and existing != kind and ("property" in (existing, kind)):
            self.context.error(
                f"Member '{member.name}' in class '{declaration.name}' is declared as both {existing} and {kind}",
                member.line,
                member.col,
            )
        declared[member.name] = kind

    def _merge_parent(self, info) -> None:
        registry = self.registry
        if not info.parent or info.parent not in self.index.class_table:
            return
        parent = self.index.class_table[info.parent]
        registry.validate_inherited_member_names(info, parent)
        own_fields = {name: field for name, field in info.fields.items() if name not in parent.fields}
        info.fields = {**parent.fields, **own_fields}
        own_field_owners = {name: owner for name, owner in info.field_owners.items() if name not in parent.fields}
        info.field_owners = {**parent.field_owners, **own_field_owners}
        inherited_methods = {name: method for name, method in parent.methods.items() if not method.is_constructor}
        inherited_method_owners = {
            name: owner for name, owner in parent.method_owners.items() if not parent.methods[name].is_constructor
        }
        info.methods = {**inherited_methods, **info.methods}
        info.method_owners = {**inherited_method_owners, **info.method_owners}
        info.properties = {**parent.properties, **info.properties}
        info.property_owners = {**parent.property_owners, **info.property_owners}
        parent_storage_names = {name for name, _member in parent.instance_storage}
        info.instance_storage = [
            *parent.instance_storage,
            *(entry for entry in info.instance_storage if entry[0] not in parent_storage_names),
        ]


class SignatureTypePolicy:
    """Own canonical equality and substitution for callable signatures."""

    def __init__(self, context: AnalysisContext, index: DeclarationIndex, type_identity: TypeIdentity) -> None:
        self.context = context
        self.index = index
        self._type_identity = type_identity
        self._reported_shape_errors: set[tuple[str, int, int]] = set()

    def equal(self, left: TypeExpr | None, right: TypeExpr | None) -> bool:
        """Compare signature types after typedef and reference normalization."""
        if left is None or right is None:
            return left is right
        left = self.canonical(left)
        right = self.canonical(right)
        if (
            left.base != right.base
            or self.semantic_pointer_depth(left) != self.semantic_pointer_depth(right)
            or left.is_array != right.is_array
            or (left.is_nullable != right.is_nullable)
            or (left.is_const != right.is_const)
            or (left.is_volatile != right.is_volatile)
        ):
            return False
        left_args = left.generic_args or []
        right_args = right.generic_args or []
        return len(left_args) == len(right_args) and all(
            (self.equal(first, second) for first, second in zip(left_args, right_args))
        )

    def substitute(self, type_expr: TypeExpr | None, substitutions: dict[str, TypeExpr]) -> TypeExpr | None:
        """Substitute signature parameters and report unrepresentable shapes."""
        try:
            return self._type_identity.substitute(type_expr, substitutions, reference_resolver=self.canonical)
        except TypeShapeError as error:
            bad_type = error.type_expr or type_expr
            line = getattr(bad_type, "line", 0) or getattr(type_expr, "line", 0)
            col = getattr(bad_type, "col", 0) or getattr(type_expr, "col", 0)
            marker = (str(error), line, col)
            if marker not in self._reported_shape_errors:
                self._reported_shape_errors.add(marker)
                self.context.error(str(error), line, col)
            return type_expr

    def canonical(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        return TypeSystem.canonical_declaration_type(type_expr, self.index.typedef_table)

    @staticmethod
    def semantic_pointer_depth(type_expr: TypeExpr) -> int:
        depth = type_expr.pointer_depth
        intrinsic_base = type_expr.base in {"string", "Thread", "Mutex", "__fn_ptr"}
        if TypeSystem.nullable_collapses_reference_layer(type_expr, base_is_reference=intrinsic_base):
            depth -= 1
        if intrinsic_base:
            depth += 1
        elif type_expr.base in {"Vector", "List", "Map", "Set", "Array"} and type_expr.generic_args and (depth == 0):
            depth = 1
        return depth


class SourceMacroDeclarations:
    """Build the analyzer's immutable macro namespace from source order."""

    def __init__(self, context: AnalysisContext) -> None:
        self.context = context

    def collect(self, declarations) -> SourceMacroNamespace:
        names: set[str] = set()
        definitions: dict[str, SourceSymbolDirective] = {}
        for declaration in declarations:
            if not isinstance(declaration, PreprocessorDirective):
                continue
            directive = SourceSymbolDirective.parse(declaration.text)
            if directive is None:
                continue
            name = directive.name
            if directive.operation == "define":
                names.add(name)
                definitions[name] = directive
                self._validate_mutation(declaration, name, define=True)
            else:
                definitions.pop(name, None)
                self._validate_mutation(declaration, name, define=False)
        return SourceMacroNamespace(names, definitions)

    def _validate_mutation(self, declaration, name: str, *, define: bool) -> None:
        prefix = DeclarationRegistry.compiler_reserved_prefix(name)
        if prefix is not None:
            message = (
                f"Macro name '{name}' uses the compiler-reserved '{prefix}' prefix"
                if define
                else f"Source #undef of compiler-owned C symbol '{name}' is not allowed"
            )
        elif DeclarationRegistry.c_file_scope_reserved_identifier(name):
            subject = "Macro name" if define else "Source #undef name"
            message = f"{subject} '{name}' is reserved by C11 at file scope"
        elif HOSTED_ABI.owned_name(name):
            action = "Macro name" if define else "Source #undef of"
            message = f"{action} compiler-owned hosted C symbol '{name}' is not allowed"
        else:
            return
        self.context.error(message, declaration.line, declaration.col)


class TopLevelRegistrar:
    def __init__(
        self,
        registry: DeclarationRegistry,
        session: AnalysisSession,
        index: DeclarationIndex,
    ) -> None:
        self.registry = registry
        self.session = session
        self.index = index

    def register_struct(self, declaration) -> None:
        registry = self.registry
        if not declaration.name:
            self.session.error("anonymous struct at top level must be named", declaration.line, declaration.col)
            return
        self.claim_name(
            declaration.name,
            "struct",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_hosted=registry.hosted_type_declaration_allowed(declaration),
        )
        self.index.declared_type_names.add(declaration.name)
        if not declaration.is_forward:
            if not declaration.fields:
                self.session.error(
                    f"Struct '{declaration.name}' cannot have an empty body under strict C11",
                    declaration.line,
                    declaration.col,
                )
            seen = set()
            for field in declaration.fields:
                registry.validate_name(field.name, "Struct field", field.line, field.col)
                if field.name in seen:
                    self.session.error(
                        f"Duplicate field '{field.name}' in struct '{declaration.name}'", field.line, field.col
                    )
                seen.add(field.name)
            if declaration.name in self.index.struct_definitions:
                self.session.error(
                    f"Duplicate definition of struct '{declaration.name}'", declaration.line, declaration.col
                )
            else:
                self.index.struct_definitions[declaration.name] = declaration
                self.index.struct_table[declaration.name] = declaration
        elif declaration.name not in self.index.struct_table:
            self.index.struct_table[declaration.name] = declaration

    def register_function(self, declaration) -> None:
        registry = self.registry
        self.claim_name(
            declaration.name,
            "function",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_prototype=declaration.body is None,
            c_name_generated=declaration.body is not None,
        )
        registry.validate_parameter_names(declaration.params, f"function '{declaration.name}'")
        existing = self.index.function_table.get(declaration.name)
        if existing is None:
            self.index.function_table[declaration.name] = declaration
            return
        if not registry.declarations_compatible(existing, declaration):
            self.session.error(
                f"Conflicting declarations for function '{declaration.name}'", declaration.line, declaration.col
            )
        if existing.body is not None and declaration.body is not None:
            self.session.error(
                f"Duplicate function name '{declaration.name}': duplicate definition", declaration.line, declaration.col
            )
            return
        if declaration.body is not None:
            registry.merge_defaults(declaration, existing)
            self.index.function_table[declaration.name] = declaration
        else:
            registry.merge_defaults(existing, declaration)

    def register_global(self, declaration) -> None:
        registry = self.registry
        self.claim_name(
            declaration.name,
            "global",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_hosted=registry.hosted_object_declaration_allowed(declaration),
        )
        previous = self.index.global_declarations.get(declaration.name)
        if previous is not None and (not registry.global_types_compatible(previous.type, declaration.type)):
            self.session.error(f"Conflicting types for global '{declaration.name}'", declaration.line, declaration.col)
        is_extern = bool(declaration.type and declaration.type.is_extern and (declaration.initializer is None))
        if not is_extern:
            if declaration.name in self.index.global_definitions:
                self.session.error(
                    f"Duplicate definition of global '{declaration.name}'", declaration.line, declaration.col
                )
            else:
                self.index.global_definitions[declaration.name] = declaration
        chosen = self.index.global_definitions.get(declaration.name, previous or declaration)
        self.index.global_declarations[declaration.name] = chosen
        symbol_type = chosen.type if chosen is not None else declaration.type
        self.session.global_scope.define(
            declaration.name,
            SymbolInfo(
                declaration.name,
                symbol_type,
                "global",
                decl_line=declaration.name_line or declaration.line,
                decl_col=declaration.name_col or declaration.col,
                decl_file=self.session.current_source_file,
            ),
        )

    def claim_name(
        self,
        name,
        kind,
        line,
        col,
        *,
        allow_same=False,
        trusted_prototype=False,
        trusted_hosted=False,
        c_name_generated=False,
    ) -> None:
        registry = self.registry
        if kind != "function" and (not trusted_hosted) and HOSTED_ABI.owned_name(name):
            self.session.error(
                f"{kind.capitalize()} name '{name}' collides with a compiler-owned hosted C symbol", line, col
            )
        registry.validate_name(
            name,
            kind.capitalize(),
            line,
            col,
            file_scope=True,
            trusted_prototype=trusted_prototype,
            trusted_hosted=trusted_hosted,
            c_name_generated=c_name_generated,
        )
        existing = self.index.top_level_kinds.get(name)
        if existing is None:
            self.index.top_level_kinds[name] = kind
        elif existing == kind:
            if not allow_same:
                self.session.error(f"Duplicate {kind} name '{name}'", line, col)
        else:
            self.session.error(f"Top-level name '{name}' is declared as both {existing} and {kind}", line, col)


class HierarchyValidator:
    """Validate registered hierarchy contracts without analyzer inheritance."""

    def __init__(self, context: AnalysisContext, index: DeclarationIndex, signature_types: SignatureTypePolicy) -> None:
        self.context = context
        self.index = index
        self._signature_types = signature_types

    def validate(self, program: Program) -> None:
        self._validate_inheritance(program)
        self._validate_interfaces(program)
        self._validate_overrides(program)

    def _validate_inheritance(self, program: Program) -> None:
        for declaration in self.context.declarations(program):
            if not isinstance(declaration, ClassDecl) or not declaration.parent:
                continue
            if declaration.parent not in self.index.class_table:
                self.context.error(f"Parent class '{declaration.parent}' not found", declaration.line, declaration.col)
                continue
            parent_info = self.index.class_table[declaration.parent]
            if declaration.generic_params or parent_info.generic_params:
                self.context.error(
                    f"Generic class inheritance is not supported: class '{declaration.name}' extends '{declaration.parent}'",
                    declaration.line,
                    declaration.col,
                )
                continue
            seen = {declaration.name}
            parent = declaration.parent
            while parent and parent in self.index.class_table:
                if parent in seen:
                    self.context.error(
                        f"Circular inheritance detected: '{declaration.name}' -> '{parent}'",
                        declaration.line,
                        declaration.col,
                    )
                    break
                seen.add(parent)
                parent = self.index.class_table[parent].parent

    def _validate_interfaces(self, program: Program) -> None:
        self._validate_interface_redeclarations(program)
        for declaration in self.context.declarations(program):
            if not isinstance(declaration, ClassDecl):
                continue
            class_info = self.index.class_table.get(declaration.name)
            if class_info is None:
                continue
            for interface_name in class_info.interfaces:
                self._validate_interface(declaration, class_info, interface_name)
            self._validate_abstract_parent(declaration, class_info)

    def _validate_interface_redeclarations(self, program: Program) -> None:
        for declaration in self.context.declarations(program):
            if not isinstance(declaration, InterfaceDecl) or not declaration.parent:
                continue
            parent = self.index.interface_table.get(declaration.parent)
            if parent is None:
                continue
            for method in declaration.methods:
                inherited = parent.methods.get(method.name)
                if inherited is not None:
                    self._validate_signature(
                        declaration.name, method, inherited, f"parent interface '{declaration.parent}'"
                    )

    def _validate_interface(self, declaration, class_info, interface_name) -> None:
        if interface_name not in self.index.interface_table:
            self.context.error(f"Interface '{interface_name}' not found", declaration.line, declaration.col)
            return
        interface = self.index.interface_table[interface_name]
        substitutions = {
            parameter: TypeExpr(base=class_info.generic_params[index])
            for index, parameter in enumerate(interface.generic_params)
            if index < len(class_info.generic_params)
        }
        for method_name, signature in interface.methods.items():
            if method_name not in class_info.methods:
                self.context.error(
                    f"Class '{declaration.name}' does not implement interface method '{method_name}' from '{interface_name}'",
                    declaration.line,
                    declaration.col,
                )
                continue
            self._validate_signature(
                declaration.name,
                class_info.methods[method_name],
                signature,
                f"interface '{interface_name}'",
                substitutions,
            )

    def _validate_abstract_parent(self, declaration, class_info) -> None:
        if not class_info.parent or class_info.parent not in self.index.class_table or class_info.is_abstract:
            return
        parent = self.index.class_table[class_info.parent]
        if not parent.is_abstract:
            return
        own_methods = {member.name for member in declaration.members if isinstance(member, MethodDecl)}
        for method_name, method in parent.methods.items():
            if method.is_abstract and method_name not in own_methods:
                self.context.error(
                    f"Class '{declaration.name}' must implement abstract method '{method_name}' from '{class_info.parent}'",
                    declaration.line,
                    declaration.col,
                )

    def _validate_overrides(self, program: Program) -> None:
        for declaration in self.context.declarations(program):
            if not isinstance(declaration, ClassDecl) or not declaration.parent:
                continue
            parent = self.index.class_table.get(declaration.parent)
            if parent is None:
                continue
            for member in declaration.members:
                if not isinstance(member, MethodDecl) or member.is_constructor:
                    continue
                parent_method = parent.methods.get(member.name)
                if parent_method is not None:
                    self._validate_signature(
                        declaration.name, member, parent_method, f"parent class '{declaration.parent}'"
                    )

    def _validate_signature(self, class_name, implementation, expected, source, substitutions=None) -> None:
        name = implementation.name
        line = getattr(implementation, "line", 0)
        col = getattr(implementation, "col", 0)
        substitutions = dict(substitutions or {})
        actual_generics = list(getattr(implementation, "generic_params", ()))
        expected_generics = list(getattr(expected, "generic_params", ()))
        if len(actual_generics) != len(expected_generics):
            self.context.error(
                f"Override '{name}' in '{class_name}' has {len(actual_generics)} generic parameter(s) (expected {len(expected_generics)} from {source})",
                line,
                col,
            )
        elif expected_generics:
            substitutions.update(
                {
                    expected_name: TypeExpr(base=actual_name)
                    for expected_name, actual_name in zip(expected_generics, actual_generics)
                }
            )
        actual_static = getattr(implementation, "access", "") == "class"
        expected_static = getattr(expected, "access", "") == "class"
        if actual_static != expected_static:
            self.context.error(
                f"Override '{name}' in '{class_name}' changes the static/instance calling convention (expected {('static' if expected_static else 'instance')} from {source})",
                line,
                col,
            )
        if bool(getattr(implementation, "keep_return", False)) != bool(getattr(expected, "keep_return", False)):
            self.context.error(
                f"Override '{name}' in '{class_name}' has incompatible keep-return ownership from {source}", line, col
            )
        if bool(getattr(implementation, "is_gpu", False)) != bool(getattr(expected, "is_gpu", False)):
            self.context.error(f"Override '{name}' in '{class_name}' changes @gpu execution from {source}", line, col)
        expected_return = getattr(expected, "return_type", None)
        if substitutions:
            expected_return = self._signature_types.substitute(expected_return, substitutions)
        actual_return = getattr(implementation, "return_type", None)
        if expected_return and actual_return and (not self._signature_types.equal(expected_return, actual_return)):
            self.context.error(
                f"Override '{name}' in '{class_name}' has incompatible return type '{actual_return.base}' (expected '{expected_return.base}' from {source})",
                line,
                col,
            )
        self._validate_parameters(class_name, implementation, expected, source, substitutions)

    def _validate_parameters(self, class_name, implementation, expected, source, substitutions) -> None:
        actual_parameters = getattr(implementation, "params", [])
        expected_parameters = getattr(expected, "params", [])
        if len(actual_parameters) != len(expected_parameters):
            self.context.error(
                f"Override '{implementation.name}' in '{class_name}' has {len(actual_parameters)} parameter(s) (expected {len(expected_parameters)} from {source})",
                getattr(implementation, "line", 0),
                getattr(implementation, "col", 0),
            )
            return
        pairs = enumerate(zip(expected_parameters, actual_parameters), 1)
        for index, (expected_parameter, actual_parameter) in pairs:
            expected_type = expected_parameter.type
            if substitutions:
                expected_type = self._signature_types.substitute(expected_type, substitutions)
            if not self._signature_types.equal(expected_type, actual_parameter.type):
                self.context.error(
                    f"Override '{implementation.name}' param {index} in '{class_name}' has incompatible type '{actual_parameter.type.base}' (expected '{expected_type.base}' from {source})",
                    getattr(implementation, "line", 0),
                    getattr(implementation, "col", 0),
                )
            if bool(getattr(expected_parameter, "keep", False)) != bool(getattr(actual_parameter, "keep", False)):
                self.context.error(
                    f"Override '{implementation.name}' param {index} in '{class_name}' has incompatible keep ownership from {source}",
                    getattr(implementation, "line", 0),
                    getattr(implementation, "col", 0),
                )


C11_RESERVED_NAMES = frozenset(
    {
        "auto",
        "break",
        "case",
        "char",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extern",
        "float",
        "for",
        "goto",
        "if",
        "inline",
        "int",
        "long",
        "register",
        "restrict",
        "return",
        "short",
        "signed",
        "sizeof",
        "static",
        "struct",
        "switch",
        "typedef",
        "union",
        "unsigned",
        "void",
        "volatile",
        "while",
        "_Alignas",
        "_Alignof",
        "_Atomic",
        "_Bool",
        "_Complex",
        "_Generic",
        "_Imaginary",
        "_Noreturn",
        "_Static_assert",
        "_Thread_local",
    }
)
_PUBLIC_NATIVE_BINDINGS = frozenset({"btrc_gpu_available", "btrc_gui_surface_width", "btrc_tray_show"})
_COMPILER_RESERVED_PREFIXES = ("__btrc_", "__BTRC_", "__gpu_", "btrc_")
MAGIC_METHOD_SIGNATURES = {
    "__add__": (1, None),
    "__sub__": (1, None),
    "__mul__": (1, None),
    "__div__": (1, None),
    "__mod__": (1, None),
    "__eq__": (1, "bool"),
    "__ne__": (1, "bool"),
    "__lt__": (1, "bool"),
    "__gt__": (1, "bool"),
    "__le__": (1, "bool"),
    "__ge__": (1, "bool"),
    "__neg__": (0, None),
    "toString": (0, "string"),
    "__del__": (0, "void"),
}
_C_BASES = {
    "byte": "unsigned char",
    "long int": "long",
    "long long int": "long long",
    "short int": "short",
    "signed": "int",
    "signed int": "int",
    "string": "char",
    "unsigned": "unsigned int",
    "uint": "unsigned int",
    "unsigned long int": "unsigned long",
    "unsigned long long int": "unsigned long long",
    "unsigned short int": "unsigned short",
}
_KNOWN_C_GLOBALS = frozenset({"stdin", "stdout", "stderr", "errno", "__func__"})


class DeclarationRegistry:
    """Own the pass-one declaration-registration cascade."""

    def __init__(
        self,
        session: AnalysisSession,
        index: DeclarationIndex,
        type_identity: TypeIdentity,
        *,
        seed: AnalyzedProgram | None = None,
    ) -> None:
        self.session = session
        self.index = index
        self._type_identity = type_identity
        self._source_macro_declarations = SourceMacroDeclarations(session)
        if seed is not None:
            self.seed(seed)

    @staticmethod
    def compiler_reserved_prefix(name: str) -> str | None:
        return next((prefix for prefix in _COMPILER_RESERVED_PREFIXES if name.startswith(prefix)), None)

    @staticmethod
    def c_reserved_identifier(name: str) -> bool:
        return name.startswith("__") or (len(name) > 1 and name[0] == "_" and ("A" <= name[1] <= "Z"))

    @staticmethod
    def c_file_scope_reserved_identifier(name: str) -> bool:
        return name.startswith("_")

    @staticmethod
    def trusted_native_binding(name: str, source_file: str | None) -> bool:
        return name in _PUBLIC_NATIVE_BINDINGS or CompilerStdlibSource.authenticated(source_file)

    @staticmethod
    def known_c_global(name: str) -> bool:
        return name in _KNOWN_C_GLOBALS

    def global_types_compatible(self, left, right) -> bool:
        """Compare source global declarations after removing linkage storage."""
        if left is None or right is None:
            return left is right
        return self._type_identity.shape_key(replace(left, is_extern=False)) == self._type_identity.shape_key(
            replace(right, is_extern=False)
        )

    def validate_name(
        self,
        name,
        subject,
        line=0,
        col=0,
        *,
        allow_magic=False,
        file_scope=False,
        trusted_prototype=False,
        trusted_hosted=False,
        c_name_generated=False,
    ) -> bool:
        """Validate one source spelling against language and C namespaces."""
        if not name:
            return True
        if self.index.source_macros.declared(name):
            self.session.error(f"{subject} name '{name}' collides with source macro '{name}'", line, col)
            return False
        if name in HOSTED_ABI.macros and (not (c_name_generated or trusted_hosted)):
            self.session.error(f"{subject} name '{name}' collides with an automatically included C macro", line, col)
            return False
        if name in C11_RESERVED_NAMES:
            self.session.error(f"{subject} name '{name}' is reserved by C11", line, col)
            return False
        reserved_prefix = self.compiler_reserved_prefix(name)
        if reserved_prefix:
            if trusted_prototype and self.trusted_native_binding(name, self.session.current_source_file):
                return True
            self.session.error(
                f"{subject} name '{name}' uses the compiler-reserved '{reserved_prefix}' prefix", line, col
            )
            return False
        if self.c_reserved_identifier(name) and (not (allow_magic and self.is_magic_method_name(name))):
            self.session.error(f"{subject} name '{name}' is reserved by C11", line, col)
            return False
        if file_scope and self.c_file_scope_reserved_identifier(name):
            self.session.error(f"{subject} name '{name}' is reserved by C11 at file scope", line, col)
            return False
        return True

    def validate_parameter_names(self, parameters, owner) -> None:
        seen = set()
        for parameter in parameters:
            line = parameter.name_line or parameter.line
            col = parameter.name_col or parameter.col
            self.validate_name(parameter.name, "Parameter", line, col, c_name_generated=True)
            if parameter.name in seen:
                self.session.error(f"Duplicate parameter name '{parameter.name}' in {owner}", line, col)
            seen.add(parameter.name)

    def validate_generic_parameter_names(self, names, owner, line=0, col=0) -> None:
        seen = set()
        for name in names:
            self.validate_name(name, "Generic parameter", line, col)
            if name in seen:
                self.session.error(f"Duplicate generic parameter name '{name}' in {owner}", line, col)
            seen.add(name)

    def validate_default_parameters(self, parameters, line, col) -> None:
        seen_default = False
        for parameter in parameters:
            if parameter.default is not None:
                seen_default = True
            elif seen_default:
                self.session.error(
                    f"Non-default parameter '{parameter.name}' follows default parameter",
                    parameter.line or line,
                    parameter.col or col,
                )
                break

    def validate_inherited_member_names(self, child, parent) -> None:
        own_fields = {name for name, owner in child.field_owners.items() if owner == child.name}
        own_methods = {
            name for name, owner in child.method_owners.items() if owner == child.name and name != child.name
        }
        own_properties = {name for name, owner in child.property_owners.items() if owner == child.name}
        conflicts = (
            own_fields & parent.properties.keys()
            | own_methods & parent.properties.keys()
            | own_properties & (parent.fields.keys() | parent.methods.keys())
        )
        for name in sorted(conflicts):
            member = child.fields.get(name) or child.methods.get(name) or child.properties.get(name)
            self.session.error(
                f"Member '{name}' in class '{child.name}' conflicts with an inherited member of a different kind",
                getattr(member, "line", 0),
                getattr(member, "col", 0),
            )
        parent_storage = {name for name, _member in parent.instance_storage}
        for storage_name, member in child.instance_storage:
            if storage_name in parent_storage:
                self.session.error(
                    f"Instance storage '{storage_name}' in class '{child.name}' conflicts with inherited storage",
                    getattr(member, "line", 0),
                    getattr(member, "col", 0),
                )

    @staticmethod
    def is_magic_method_name(name: str) -> bool:
        return name in MAGIC_METHOD_SIGNATURES

    def validate_array_return(self, declaration, owner=None) -> None:
        return_type = declaration.return_type
        if not return_type or not return_type.is_array or getattr(declaration, "is_gpu", False):
            return
        subject = f"Method '{owner}.{declaration.name}'" if owner else f"Function '{declaration.name}'"
        self.session.error(f"{subject} cannot return an array outside @gpu", declaration.line, declaration.col)

    def validate_class_shape(self, class_decl, method) -> None:
        owner = f"method '{class_decl.name}.{method.name}'"
        if class_decl.generic_params and method.access == "class":
            self.session.error(
                f"Static {owner} has no specialization target and is not supported on a generic class",
                method.line,
                method.col,
            )
        if method.is_constructor:
            self._validate_constructor_shape(class_decl, method)
            return
        if method.name == class_decl.name:
            message = (
                f"Constructor '{class_decl.name}' cannot have return type '{method.return_type.base}'"
                if method.return_type.base != class_decl.name
                else f"Method '{class_decl.name}.{method.name}' uses explicit-return constructor syntax"
            )
            self.session.error(message, method.line, method.col)
        if method.is_abstract:
            if not class_decl.is_abstract:
                self.session.error(f"Abstract {owner} requires an abstract class", method.line, method.col)
            if method.body is not None:
                self.session.error(f"Abstract {owner} cannot have a body", method.line, method.col)
        elif method.body is None:
            self.session.error(f"Concrete {owner} requires a body", method.line, method.col)
        signature = MAGIC_METHOD_SIGNATURES.get(method.name)
        if signature is None:
            return
        arity, return_base = signature
        if method.access == "class":
            self.session.error(f"Magic {owner} must be an instance method", method.line, method.col)
        if method.is_abstract or method.body is None:
            self.session.error(f"Magic {owner} requires a concrete body", method.line, method.col)
        if method.generic_params:
            self.session.error(f"Magic {owner} cannot be generic", method.line, method.col)
        if len(method.params) != arity:
            self.session.error(
                f"Magic {owner} expects {arity} explicit parameter(s) but got {len(method.params)}",
                method.line,
                method.col,
            )
        canonical_return = TypeSystem.canonical_declaration_type(method.return_type, self.index.typedef_table)
        if return_base and (
            canonical_return is None
            or canonical_return.base != return_base
            or canonical_return.pointer_depth
            or canonical_return.is_array
            or canonical_return.generic_args
        ):
            self.session.error(f"Magic {owner} must return '{return_base}'", method.line, method.col)

    def declarations_compatible(self, left, right) -> bool:
        if (
            self._function_linkage(left) != self._function_linkage(right)
            or self._function_type_key(left.return_type) != self._function_type_key(right.return_type)
            or left.is_gpu != right.is_gpu
            or (left.keep_return != right.keep_return)
            or (len(left.params) != len(right.params))
        ):
            return False
        return all(
            first.name == second.name
            and first.keep == second.keep
            and self._type_identity.shape_key(first.type) == self._type_identity.shape_key(second.type)
            and self._compatible_defaults(first.default, second.default)
            for first, second in zip(left.params, right.params)
        )

    @staticmethod
    def merge_defaults(definition, declaration) -> None:
        for target, source in zip(definition.params, declaration.params):
            if target.default is None and source.default is not None:
                target.default = source.default

    def validate_main_signature(self, function) -> None:
        if function.name != "main":
            return
        result = TypeSystem.canonical_declaration_type(function.return_type, self.index.typedef_table)
        valid_result = bool(
            result
            and result.base in {"int", "void"}
            and (result.pointer_depth == 0)
            and (not result.is_array)
            and (not result.generic_args)
        )
        valid_params = not function.params
        if result and result.base == "int" and (len(function.params) == 2):
            argc = TypeSystem.canonical_declaration_type(function.params[0].type, self.index.typedef_table)
            argv = TypeSystem.canonical_declaration_type(function.params[1].type, self.index.typedef_table)
            argv_depth = argv.pointer_depth + int(argv.is_array) if argv else -1
            valid_params = bool(
                argc
                and argc.base == "int"
                and (argc.pointer_depth == 0)
                and (not argc.is_array)
                and argv
                and (argv.base == "char")
                and (argv_depth == 2)
            )
        if not valid_result or not valid_params or function.is_gpu:
            self.session.error(
                "main must be 'int main()', 'int main(int, char**)', or 'void main()'", function.line, function.col
            )

    def _validate_constructor_shape(self, class_decl, method) -> None:
        owner = f"Constructor '{class_decl.name}'"
        checks = (
            (method.access == "class", f"{owner} cannot be class/static"),
            (method.is_abstract, f"{owner} cannot be abstract"),
            (method.is_gpu, f"{owner} cannot be @gpu"),
            (method.keep_return, f"{owner} cannot use keep-return"),
            (method.body is None, f"{owner} requires a concrete body"),
            (bool(method.generic_params), f"{owner} cannot be generic"),
        )
        for invalid, message in checks:
            if invalid:
                self.session.error(message, method.line, method.col)

    @staticmethod
    def _compatible_defaults(left, right) -> bool:
        return (
            left is None
            or right is None
            or AnalysisSession.semantic_ast_key(left) == AnalysisSession.semantic_ast_key(right)
        )

    @staticmethod
    def _function_linkage(declaration) -> str:
        return "internal" if declaration.return_type.is_static else "external"

    def _function_type_key(self, type_expr):
        return self._type_identity.shape_key(TypeSystem.function_signature_component(type_expr))

    def hosted_type_declaration_allowed(self, declaration) -> bool:
        return bool(
            CompilerStdlibSource.authenticated(self.session.current_source_file)
            and declaration.name == "winsize"
            and declaration.is_forward
            and (not declaration.fields)
        )

    def hosted_object_declaration_allowed(self, declaration) -> bool:
        type_expr = declaration.type
        canonical = TypeSystem.canonical_declaration_type(type_expr, self.index.typedef_table)
        return bool(
            CompilerStdlibSource.authenticated(self.session.current_source_file)
            and declaration.name == "environ"
            and (declaration.initializer is None)
            and (type_expr is not None)
            and type_expr.is_extern
            and (canonical is not None)
            and (canonical.base == "char")
            and (canonical.pointer_depth == 2)
            and (not canonical.is_array)
            and (not canonical.generic_args)
        )

    def validate_hosted_function(self, declaration) -> None:
        if declaration.body is not None:
            return
        name = declaration.name
        if name in HOSTED_ABI.macros:
            self.session.error(
                f"Hosted macro '{name}' cannot be redeclared as a function", declaration.line, declaration.col
            )
            return
        spec = HOSTED_ABI.function(name)
        if (
            spec is None
            and self.trusted_native_binding(name, self.session.current_source_file)
            and CompilerStdlibSource.authenticated(self.session.current_source_file)
        ):
            return
        if spec is None:
            if HOSTED_ABI.owned_name(name):
                self.session.error(
                    f"Hosted symbol '{name}' has no source-representable prototype; include its standard header and call it directly",
                    declaration.line,
                    declaration.col,
                )
            return
        if spec.parameters is None or spec.variadic:
            self.session.error(
                f"Hosted function '{name}' has an ABI that btrc prototypes cannot represent; include its standard header and call it directly",
                declaration.line,
                declaration.col,
            )
            return
        actual_result = self.hosted_abi_type(declaration.return_type)
        actual_parameters = tuple(self.hosted_abi_type(parameter.type) for parameter in declaration.params)
        modifiers_valid = bool(
            not declaration.return_type.is_static
            and (not declaration.return_type.is_volatile)
            and (not declaration.is_gpu)
            and (not declaration.keep_return)
            and all(
                not parameter.keep
                and parameter.default is None
                and (not parameter.type.is_static)
                and (not parameter.type.is_extern)
                and (not parameter.type.is_volatile)
                for parameter in declaration.params
            )
        )
        if not modifiers_valid or actual_result != spec.result or actual_parameters != spec.parameters:
            self.session.error(
                f"Hosted function declaration '{name}' does not match compiler-owned C ABI '{self._format_hosted_abi(spec)}'",
                declaration.line,
                declaration.col,
            )

    def hosted_abi_type(self, type_expr) -> AbiType | None:
        canonical = TypeSystem.canonical_declaration_type(type_expr, self.index.typedef_table)
        if canonical is None or canonical.generic_args:
            return None
        base = _C_BASES.get(canonical.base, canonical.base)
        depth = canonical.pointer_depth + int(canonical.is_array)
        if canonical.base == "string":
            depth += 1
        if TypeSystem.nullable_collapses_reference_layer(canonical, base_is_reference=canonical.base == "string"):
            depth -= 1
        return AbiType(base, depth, bool(canonical.is_const))

    @staticmethod
    def _format_hosted_abi(spec) -> str:
        def render(type_shape: AbiType) -> str:
            qualifier = "const " if type_shape.is_const else ""
            return qualifier + type_shape.base + "*" * type_shape.pointer_depth

        parameters = ", ".join(render(item) for item in spec.parameters or ())
        if spec.variadic:
            parameters = f"{parameters}, ..." if parameters else "..."
        return f"{render(spec.result)} ({parameters or 'void'})"

    def seed(self, analyzed: AnalyzedProgram) -> None:
        self.index.class_table = dict(analyzed.class_table)
        self.index.function_table = dict(analyzed.function_table)
        self.index.typedef_table = dict(analyzed.typedef_table)
        self.index.struct_table = dict(analyzed.struct_table)
        self.index.enum_table = {name: list(values) for name, values in analyzed.enum_table.items()}
        self.index.interface_table = dict(analyzed.interface_table)
        self.index.rich_enum_table = dict(analyzed.rich_enum_table)

    def register(self, program: Program) -> None:
        if sys.getrecursionlimit() < 40000:
            sys.setrecursionlimit(40000)
        top_level = TopLevelRegistrar(self, self.session, self.index)
        enum_registrar = EnumRegistrar(self, top_level, self.session, self.index)
        inheritance = InheritanceResolver(self, self.session, self.index)
        pre_resolved_classes = {id(info) for info in self.index.class_table.values()}
        self.index.definition_index = self._build_definition_index(program)
        self.index.top_level_kinds = {}
        self.index.source_macros = self._source_macro_declarations.collect(self.session.declarations(program))
        self.index.enum_member_owners = {}
        self.index.enum_constant_values = {}
        self.index.global_declarations = {}
        self.index.global_definitions = {}
        self.index.struct_definitions = {}
        for declaration in self.session.declarations(program):
            if isinstance(declaration, InterfaceDecl):
                self._register_interface(declaration, top_level)
        self.index.declared_type_names = set()
        for declaration in self.session.declarations(program):
            if isinstance(declaration, ClassDecl):
                self._register_class(declaration, top_level, inheritance)
            elif isinstance(declaration, FunctionDecl):
                top_level.register_function(declaration)
            elif isinstance(declaration, StructDecl):
                top_level.register_struct(declaration)
            elif isinstance(declaration, EnumDecl):
                enum_registrar.register_simple(declaration)
            elif isinstance(declaration, RichEnumDecl):
                enum_registrar.register_rich(declaration)
            elif isinstance(declaration, TypedefDecl):
                top_level.claim_name(
                    declaration.alias,
                    "typedef",
                    declaration.name_line or declaration.line,
                    declaration.name_col or declaration.col,
                )
                self.index.declared_type_names.add(declaration.alias)
                self.index.typedef_table[declaration.alias] = declaration.original
            elif isinstance(declaration, VarDeclStmt):
                top_level.register_global(declaration)
        inheritance.resolve(pre_resolved_classes)

    @staticmethod
    def _build_definition_index(program: Program) -> dict[str, tuple[object, str]]:
        index: dict[str, tuple[object, str]] = {}
        for declaration in program.declarations:
            if isinstance(declaration, ClassDecl):
                index.setdefault(declaration.name, (declaration, "class"))
            elif isinstance(declaration, FunctionDecl):
                index.setdefault(declaration.name, (declaration, "function"))
            elif isinstance(declaration, EnumDecl):
                index.setdefault(declaration.name, (declaration, "enum"))
                for value in declaration.values:
                    index.setdefault(value.name, (value, "enum"))
            elif isinstance(declaration, RichEnumDecl):
                index.setdefault(declaration.name, (declaration, "enum"))
                for variant in declaration.variants:
                    index.setdefault(variant.name, (variant, "enum"))
        return index

    def definition(self, name: str) -> tuple[object | None, str]:
        """Return the registered definition site and semantic kind for a name."""
        return self.index.definition_index.get(name, (None, ""))

    def resolve_interface_parents(self, program: Program) -> None:
        declarations = {
            declaration.name: declaration
            for declaration in self.session.declarations(program)
            if isinstance(declaration, InterfaceDecl)
        }
        visiting: set[str] = set()
        done: set[str] = set()

        def resolve(name: str) -> None:
            if name in done:
                return
            declaration = declarations[name]
            if name in visiting:
                self.session.error(
                    f"Circular interface inheritance involving '{name}'", declaration.line, declaration.col
                )
                return
            visiting.add(name)
            info = self.index.interface_table[name]
            if info.parent:
                if info.parent not in self.index.interface_table:
                    self.session.error(f"Parent interface '{info.parent}' not found", declaration.line, declaration.col)
                else:
                    resolve(info.parent)
                    inherited = dict(self.index.interface_table[info.parent].methods)
                    inherited.update(info.methods)
                    info.methods = inherited
            visiting.remove(name)
            done.add(name)

        for name in declarations:
            resolve(name)

    def _register_interface(self, declaration: InterfaceDecl, top_level: TopLevelRegistrar) -> None:
        policy = self
        top_level.claim_name(
            declaration.name,
            "interface",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
        )
        policy.validate_generic_parameter_names(
            declaration.generic_params, f"interface '{declaration.name}'", declaration.line, declaration.col
        )
        info = InterfaceInfo(
            name=declaration.name, parent=declaration.parent, generic_params=declaration.generic_params
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
            policy.validate_parameter_names(method.params, f"interface method '{declaration.name}.{method.name}'")
            policy.validate_array_return(method, declaration.name)
            if method.name in info.methods:
                self.session.error(
                    f"Duplicate method '{method.name}' in interface '{declaration.name}'", method.line, method.col
                )
            info.methods[method.name] = method
        self.index.interface_table[declaration.name] = info

    def _register_class(
        self,
        declaration: ClassDecl,
        top_level: TopLevelRegistrar,
        inheritance: InheritanceResolver,
    ) -> None:
        policy = self
        top_level.claim_name(
            declaration.name,
            "class",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
        )
        policy.validate_generic_parameter_names(
            declaration.generic_params, f"class '{declaration.name}'", declaration.line, declaration.col
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
                    member.name, "Field", member.name_line or member.line, member.name_col or member.col
                )
                if member.name in fields:
                    self.session.error(
                        f"Duplicate field '{member.name}' in class '{declaration.name}'", member.line, member.col
                    )
                fields.add(member.name)
                inheritance.claim_member_name(declaration, member, "field", members)
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
                    member.generic_params, f"method '{declaration.name}.{member.name}'", member.line, member.col
                )
                policy.validate_parameter_names(member.params, f"method '{declaration.name}.{member.name}'")
                if member.name in methods:
                    self.session.error(
                        f"Duplicate method '{member.name}' in class '{declaration.name}'", member.line, member.col
                    )
                methods.add(member.name)
                inheritance.claim_member_name(declaration, member, "method", members)
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
                    self.session.error(
                        f"Duplicate property '{member.name}' in class '{declaration.name}'", member.line, member.col
                    )
                properties.add(member.name)
                inheritance.claim_member_name(declaration, member, "property", members)
                info.properties[member.name] = member
                info.property_owners[member.name] = declaration.name
            storage_name = None
            if isinstance(member, FieldDecl) and member.access != "class":
                storage_name = member.name
            elif (
                isinstance(member, PropertyDecl)
                and member.access != "class"
                and (
                    (member.has_getter and member.getter_body is None)
                    or (member.has_setter and member.setter_body is None)
                )
            ):
                storage_name = f"_prop_{member.name}"
            if storage_name is not None:
                if storage_name in storage_names:
                    self.session.error(
                        f"Instance storage name '{storage_name}' collides with another member in class '{declaration.name}'",
                        member.line,
                        member.col,
                    )
                else:
                    storage_names.add(storage_name)
                    info.instance_storage.append((storage_name, member))
        self.index.class_table[declaration.name] = info


__all__ = [
    "DeclarationRegistry",
    "EnumRegistrar",
    "HierarchyValidator",
    "InheritanceResolver",
    "SignatureTypePolicy",
    "SourceMacroDeclarations",
    "TopLevelRegistrar",
]
