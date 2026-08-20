"""Cohesive classes IR lowering owner."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.generated_symbols import GeneratedSymbolRegistry
from src.compiler.python.analyzer.program import AnalyzedProgram, ClassInfo
from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.analyzer.types import TypeIdentity, TypeSystem
from src.compiler.python.ir.nodes import (
    CType,
    IRAssign,
    IRBlock,
    IRCall,
    IRCast,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDecl,
    IRFunctionDef,
    IRGlobalDecl,
    IRLiteral,
    IRParam,
    IRReturn,
    IRSizeof,
    IRStructDef,
    IRStructField,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import (
    BraceInitializer,
    ClassDecl,
    FieldDecl,
    ListLiteral,
    MapLiteral,
    MethodDecl,
    PropertyDecl,
    StructDecl,
    TypeExpr,
)

from .calls import CallableProvenance, CallableSignatureLowerer
from .types import CTypeLowerer

if TYPE_CHECKING:
    from .calls import CallableStorageBoundary, CallLowerer
    from .collections import CollectionLowerer
    from .expressions import ExpressionLowerer
    from .generics import SpecializedDeclarationView
    from .ownership import (
        CycleMetadata,
        ManagedLifetimeLowerer,
        ManagedValueSemantics,
        OwnershipLowerer,
    )
    from .session import LoweringSession
    from .statements import StatementLowerer


class ClassLowerer:
    """Own classes lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        signatures: CallableSignatureLowerer,
        type_identity: TypeIdentity,
        expressions: ExpressionLowerer,
        statements: StatementLowerer,
        collections: CollectionLowerer,
        ownership: OwnershipLowerer,
        values: ManagedValueSemantics,
        lifetime: ManagedLifetimeLowerer,
        cycles: CycleMetadata,
        calls: CallLowerer,
        callable_boundaries: CallableStorageBoundary,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._signatures = signatures
        self._type_identity = type_identity
        self._expressions = expressions
        self._statements = statements
        self._collections = collections
        self._ownership = ownership
        self._values = values
        self._lifetime = lifetime
        self._cycles = cycles
        self._calls = calls
        self._callable_boundaries = callable_boundaries
        self._pack_alignments: dict[int, int | None] = {}

    def lower_declaration(self, declaration):
        return self.emit_class_decl(
            declaration,
        )

    def lower_specialization(self, view: SpecializedDeclarationView[ClassDecl]) -> None:
        self.emit_class_decl(view.declaration)

    def declare_specialization(self, view: SpecializedDeclarationView[ClassDecl]) -> None:
        """Declare every callable for one concrete class before any body lowers."""
        declaration = replace(view.declaration, name=view.symbol, generic_params=[])
        class_info = self._analyzed.class_table.get(view.base_name)
        if class_info is not None:
            self.emit_class_callable_declarations(
                declaration,
                class_info,
                view.selected_callables,
            )

    def configure_pack_alignments(self, alignments: dict[int, int]) -> None:
        """Install the translation unit's resolved pragma-pack layout."""
        self._pack_alignments = dict(alignments)

    def emit_constructor(self, decl: ClassDecl, cls_info: ClassInfo) -> None:
        """Emit ``Class_init`` and allocating ``Class_new`` functions."""
        name = decl.name
        constructor = cls_info.constructor
        init_provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        init_constructor_params = [
            init_provenance.lower_source_param(param) for param in (constructor.params if constructor else [])
        ]
        init_params = [IRParam(c_type=CType(text=f"{name}*"), name="self"), *init_constructor_params]
        init_stmts = self._ownership.arc_header_initialization(name)
        for member in decl.members:
            if isinstance(member, FieldDecl) and member.access != "class" and member.initializer:
                self._callable_boundaries.reject_persistent_escape(
                    member.type,
                    member.initializer,
                    "field storage",
                    init_provenance,
                )
                target = IRFieldAccess(obj=IRVar(name="self"), field=member.name, arrow=True)
                with self._expressions.hosted_result_request(
                    member.initializer,
                    member.type,
                    init_provenance,
                ):
                    lowered_initializer = self._lower_field_init(member, init_provenance)
                prepared = self._expressions.prepare_lowered_value(
                    member.initializer,
                    member.type,
                    lowered_initializer,
                    init_provenance,
                )
                value = prepared.value
                value = self._types.upcast_class_pointer(member.type, prepared.effective_type, value)
                if self._values.is_arc(member.type):
                    init_stmts.append(
                        IRExprStmt(
                            expr=self._lifetime.replace_edge_value(
                                target, value, member.type, IRVar(name="self"), adopt=prepared.owned
                            )
                        )
                    )
                else:
                    init_stmts.append(IRAssign(target=target, value=value))
                if self._is_managed_field(member) and (not self._values.is_arc(member.type)):
                    edge_effect = (
                        self._lifetime.adopt_edge_value(target, member.type, IRVar(name="self"))
                        if prepared.owned
                        else self._lifetime.retain_edge_value(target, member.type, IRVar(name="self"))
                    )
                    init_stmts.append(IRExprStmt(expr=edge_effect))
        if constructor and constructor.body:
            self._session.function_declarations = []
            self._session.current_return_c_type = "void"
            init_stmts.extend(
                self._statements.lower_block(
                    constructor.body,
                    init_provenance,
                    local_bindings=["self", *(parameter.name for parameter in constructor.params)],
                    callable_bindings=constructor.params,
                ).stmts
            )
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=f"{name}_init",
                return_type=CType(text="void"),
                params=init_params,
                body=IRBlock(stmts=init_stmts),
                is_static=self._specialized_linkage(),
            )
        )
        new_provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        new_constructor_params = [
            new_provenance.lower_source_param(param) for param in (constructor.params if constructor else [])
        ]
        self_declaration = IRVarDecl(
            c_type=CType(text=f"{name}*"),
            name="self",
            init=IRCast(
                target_type=CType(text=f"{name}*"),
                expr=IRCall(
                    callee="__btrc_safe_calloc",
                    args=[IRLiteral(text="1"), IRSizeof(operand=CType(text=name))],
                    helper_ref="__btrc_safe_calloc",
                ),
            ),
        )
        self._session.require_helper("__btrc_safe_calloc")
        cleanup_before, cleanup_after = self._expressions.constructor_cleanup_guard(self_declaration)
        new_stmts = [
            self_declaration,
            *cleanup_before,
            IRExprStmt(
                expr=IRCall(
                    callee=f"{name}_init",
                    args=[IRVar(name="self"), *(IRVar(name=param.name) for param in new_constructor_params)],
                )
            ),
            *cleanup_after,
            IRReturn(value=IRVar(name="self")),
        ]
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=f"{name}_new",
                return_type=CType(text=f"{name}*"),
                params=new_constructor_params,
                body=IRBlock(stmts=new_stmts),
                is_static=self._specialized_linkage(),
            )
        )

    def _lower_field_init(self, field: FieldDecl, provenance: CallableProvenance):
        initializer = field.initializer
        field_type = self._types.canonical_type(field.type)
        is_empty = (
            (isinstance(initializer, BraceInitializer) and (not initializer.elements))
            or (isinstance(initializer, ListLiteral) and (not initializer.elements))
            or (isinstance(initializer, MapLiteral) and (not initializer.entries))
        )
        if is_empty and field_type and self._types.is_generic_class_type(field_type):
            mangled = self._type_identity.specialization_symbol(field_type.base, field_type.generic_args)
            return IRCall(callee=f"{mangled}_new", args=[])
        return self._expressions.lower_expr(
            initializer,
            provenance,
        )

    def _is_managed_field(self, field: FieldDecl) -> bool:
        return self._values.is_managed(field.type)

    def emit_class_callable_declarations(
        self,
        declaration: ClassDecl,
        class_info: ClassInfo,
        selected_callables: frozenset[tuple[str, str]] | None = None,
    ) -> None:
        """Register declarations for a class's own and inherited callables."""
        functions = [
            IRFunctionDecl(
                name=f"{declaration.name}_destroy",
                return_type=CType(text="void"),
                params=[IRParam(c_type=CType(text="void*"), name="object")],
                is_static=self._specialized_linkage(),
            ),
            *self.class_callable_declarations(declaration, class_info, selected_callables),
        ]
        for function in functions:
            if function not in self._session.module.function_decls:
                self._session.module.function_decls.append(function)

    def class_callable_declarations(
        self,
        declaration: ClassDecl,
        class_info: ClassInfo,
        selected_callables: frozenset[tuple[str, str]] | None = None,
    ) -> list[IRFunctionDecl]:
        """Describe every callable prototype exposed by one concrete class."""
        name = declaration.name
        constructor_params = self._parameters(
            class_info.constructor.params if class_info.constructor else [],
            self._signatures,
        )
        declarations = [
            IRFunctionDecl(
                name=f"{name}_init",
                return_type=CType(text="void"),
                params=[IRParam(c_type=CType(text=f"{name}*"), name="self")] + constructor_params,
                is_static=self._specialized_linkage(),
            ),
            IRFunctionDecl(
                name=f"{name}_new",
                return_type=CType(text=f"{name}*"),
                params=list(constructor_params),
                is_static=self._specialized_linkage(),
            ),
        ]
        for member in declaration.members:
            if (
                isinstance(member, MethodDecl)
                and (not member.is_constructor)
                and (member.name != "__del__")
                and (not member.generic_params)
                and (selected_callables is None or ("method", member.name) in selected_callables)
            ):
                params = []
                if member.access != "class":
                    params.append(IRParam(c_type=CType(text=f"{name}*"), name="self"))
                params.extend(self._parameters(member.params, self._signatures))
                declarations.append(
                    IRFunctionDecl(
                        name=f"{name}_{member.name}",
                        return_type=CType(text=self._types.render(member.return_type)),
                        params=params,
                        is_static=self._specialized_linkage(),
                    )
                )
            elif isinstance(member, PropertyDecl):
                declarations.extend(self._property_declarations(name, member, self._signatures, selected_callables))
        declarations.extend(
            self._inherited_property_declarations(
                name,
                declaration,
                class_info,
                self._signatures,
                selected_callables,
            )
        )
        declarations.extend(
            self._inherited_method_declarations(
                name,
                declaration,
                class_info,
                self._signatures,
                selected_callables,
            )
        )
        return declarations

    @staticmethod
    def _parameters(parameters, signatures: CallableSignatureLowerer) -> list[IRParam]:
        return [signatures.lower_source_param(parameter) for parameter in parameters]

    def _property_declarations(
        self,
        class_name: str,
        declaration: PropertyDecl,
        signatures: CallableSignatureLowerer,
        selected_callables: frozenset[tuple[str, str]] | None = None,
    ) -> list[IRFunctionDecl]:
        prop_type = CType(text=self._types.render(declaration.type))
        self_param = IRParam(c_type=CType(text=f"{class_name}*"), name="self")
        result = []
        if declaration.has_getter and (selected_callables is None or ("get", declaration.name) in selected_callables):
            result.append(
                IRFunctionDecl(
                    name=f"{class_name}_get_{declaration.name}",
                    return_type=prop_type,
                    params=[self_param],
                    is_static=self._specialized_linkage(),
                )
            )
        if declaration.has_setter and (selected_callables is None or ("set", declaration.name) in selected_callables):
            result.append(
                IRFunctionDecl(
                    name=f"{class_name}_set_{declaration.name}",
                    return_type=CType(text="void"),
                    params=[
                        self_param,
                        signatures.lower_named_source_type_param(declaration.type, prop_type, "value"),
                    ],
                    is_static=self._specialized_linkage(),
                )
            )
        return result

    def _inherited_property_declarations(
        self,
        class_name: str,
        declaration: ClassDecl,
        class_info: ClassInfo,
        signatures: CallableSignatureLowerer,
        selected_callables: frozenset[tuple[str, str]] | None = None,
    ) -> list[IRFunctionDecl]:
        parent = self._analyzed.class_table.get(class_info.parent) if class_info.parent else None
        if parent is None:
            return []
        own = {member.name for member in declaration.members if isinstance(member, PropertyDecl)}
        result = []
        for name, prop in parent.properties.items():
            if name not in own:
                result.extend(self._property_declarations(class_name, prop, signatures, selected_callables))
        return result

    def _inherited_method_declarations(
        self,
        class_name: str,
        declaration: ClassDecl,
        class_info: ClassInfo,
        signatures: CallableSignatureLowerer,
        selected_callables: frozenset[tuple[str, str]] | None = None,
    ) -> list[IRFunctionDecl]:
        declarations = []
        seen = {member.name for member in declaration.members if isinstance(member, MethodDecl)}
        parent_name = class_info.parent
        while parent_name and parent_name in self._analyzed.class_table:
            parent_info = self._analyzed.class_table[parent_name]
            for method_name, method in parent_info.methods.items():
                if method_name in seen or method_name in {"__del__", parent_name} or method.generic_params:
                    continue
                seen.add(method_name)
                if selected_callables is not None and ("method", method_name) not in selected_callables:
                    continue
                params = []
                if method.access != "class":
                    params.append(IRParam(c_type=CType(text=f"{class_name}*"), name="self"))
                params.extend(self._parameters(method.params, signatures))
                declarations.append(
                    IRFunctionDecl(
                        name=f"{class_name}_{method_name}",
                        return_type=CType(text=self._types.render(method.return_type)),
                        params=params,
                        is_static=self._specialized_linkage(),
                    )
                )
            parent_name = parent_info.parent
        return declarations

    def emit_destructor(self, decl: ClassDecl, cls_info: ClassInfo) -> str | None:
        """Emit ClassName_destroy(self) which frees internal resources."""
        name = decl.name
        dtor = cls_info.methods.get("__del__")
        hook = None
        if dtor and dtor.body:
            provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
            self._session.function_declarations = []
            previous_return_type = self._session.current_return_type
            previous_return_c_type = self._session.current_return_c_type
            previous_return_owned = self._session.current_return_owned
            self._session.current_return_c_type = "void"
            self._session.current_return_type = None
            try:
                hook = ClassLowerer.build_destructor_hook(
                    name,
                    self._statements.lower_block(
                        dtor.body,
                        provenance,
                        local_bindings=["self"],
                    ),
                )
            finally:
                self._session.current_return_type = previous_return_type
                self._session.current_return_c_type = previous_return_c_type
                self._session.current_return_owned = previous_return_owned
            self._session.module.function_defs.append(hook)
        body_stmts = [
            IRVarDecl(
                c_type=CType(text=f"{name}*"),
                name="self",
                init=IRCast(target_type=CType(text=f"{name}*"), expr=IRVar(name="object")),
            )
        ]
        has_owned_field_cleanup = False
        for fname, fd in cls_info.instance_storage:
            if self._values.is_managed(fd.type):
                body_stmts.append(
                    self._emit_field_release(
                        fname,
                        fd.type,
                    )
                )
                has_owned_field_cleanup = has_owned_field_cleanup or self._values.is_arc(fd.type)
        if has_owned_field_cleanup:
            self._session.require_helper("__btrc_mark_destroyed")
            body_stmts.append(
                IRExprStmt(
                    expr=IRCall(
                        callee="__btrc_mark_destroyed", helper_ref="__btrc_mark_destroyed", args=[IRVar(name="self")]
                    )
                )
            )
        body_stmts.append(IRExprStmt(expr=IRCall(callee="free", args=[IRVar(name="self")])))
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=f"{name}_destroy",
                return_type=CType(text="void"),
                params=[IRParam(c_type=CType(text="void*"), name="object")],
                body=IRBlock(stmts=body_stmts),
                is_static=self._specialized_linkage(),
            )
        )
        return GeneratedSymbolRegistry.destructor_hook_symbol(name) if hook is not None else None

    def emit_method(self, decl: ClassDecl, method: MethodDecl):
        """Emit ClassName_methodname(self, ...) as a free function."""
        provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        name = decl.name
        is_static = method.access == "class"
        collection_instance_method = not is_static and self._collections.owns_persistent_element_edges(
            self._session.current_class_name
        )
        specialization = self._session.active_specialization
        collection_type = (
            TypeExpr(
                base=self._session.current_class_name,
                generic_args=list(specialization.type_arguments),
            )
            if collection_instance_method and specialization is not None
            else None
        )
        params = []
        if not is_static:
            params.append(IRParam(c_type=CType(text=f"{name}*"), name="self"))
        for p in method.params:
            params.append(provenance.lower_source_param(p))
        ret_type = self._types.render(method.return_type) if method.return_type else "void"
        body = IRBlock()
        if method.body:
            self._session.function_declarations = []
            previous_return_type = self._session.current_return_type
            previous_return_c_type = self._session.current_return_c_type
            previous_return_owned = self._session.current_return_owned
            self._session.current_return_c_type = ret_type
            self._session.current_return_type = method.return_type
            self._session.current_return_owned = True
            try:
                edge_owner = "self" if collection_instance_method else None
                with self._session.persistent_edge_scope(edge_owner):
                    body = self._statements.lower_block(
                        method.body,
                        provenance,
                        local_bindings=["self", *(parameter.name for parameter in method.params)],
                        callable_bindings=method.params,
                    )
            finally:
                self._session.current_return_type = previous_return_type
                self._session.current_return_c_type = previous_return_c_type
                self._session.current_return_owned = previous_return_owned
        function = IRFunctionDef(
            name=f"{name}_{method.name}",
            return_type=CType(text=ret_type),
            params=params,
            body=body,
            is_static=self._specialized_linkage(),
        )
        if collection_type is not None:
            self._collections.protect_topology_mutation(function, collection_type)
        self._session.module.function_defs.append(function)

    def emit_inherited_methods(
        self,
        decl: ClassDecl,
        cls_info: ClassInfo,
        own_methods: set[str],
        selected_callables: frozenset[tuple[str, str]] | None = None,
    ):
        """Emit wrapper functions for inherited methods not overridden."""
        parent_name = cls_info.parent
        while parent_name and parent_name in self._analyzed.class_table:
            parent_info = self._analyzed.class_table[parent_name]
            for mname, method in parent_info.methods.items():
                if mname in own_methods or mname == "__del__" or method.is_constructor or method.generic_params:
                    continue
                if selected_callables is not None and ("method", mname) not in selected_callables:
                    continue
                if method.is_abstract or method.body is None:
                    continue
                own_methods.add(mname)
                provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
                params = []
                call_args = []
                if method.access != "class":
                    params.append(IRParam(c_type=CType(text=f"{decl.name}*"), name="self"))
                    call_args.append(IRCast(target_type=CType(text=f"{parent_name}*"), expr=IRVar(name="self")))
                for p in method.params:
                    params.append(provenance.lower_source_param(p))
                    call_args.append(IRVar(name=provenance.source_binding_c_name(p.name)))
                ret_type = self._types.render(method.return_type) if method.return_type else "void"
                call = IRCall(callee=f"{parent_name}_{mname}", args=call_args)
                if ret_type == "void":
                    body = IRBlock(stmts=[IRExprStmt(expr=call)])
                else:
                    body = IRBlock(stmts=[IRReturn(value=call)])
                self._session.module.function_defs.append(
                    IRFunctionDef(
                        name=f"{decl.name}_{mname}",
                        return_type=CType(text=ret_type),
                        params=params,
                        body=body,
                        is_static=self._specialized_linkage(),
                    )
                )
            parent_name = parent_info.parent

    def _emit_field_release(self, field_name: str, field_type) -> IRBlock:
        """Release one internal field without a reentrant collector flush."""
        fa = IRFieldAccess(obj=IRVar(name="self"), field=field_name, arrow=True)
        if self._values.is_arc(field_type):
            return IRBlock(
                stmts=[
                    IRExprStmt(
                        expr=self._lifetime.replace_edge_value(
                            fa, IRLiteral(text="NULL"), field_type, IRVar(name="self"), adopt=False
                        )
                    )
                ]
            )
        old_name = self._session.fresh_temp("__btrc_destroy_field")
        return IRBlock(
            stmts=[
                IRVarDecl(c_type=CType(text=self._types.render(field_type)), name=old_name, init=fa),
                IRExprStmt(expr=self._lifetime.unlink_edge_value(IRVar(name=old_name), field_type, IRVar(name="self"))),
                IRAssign(target=fa, value=IRLiteral(text="NULL")),
                IRExprStmt(expr=self._lifetime.release_edge_value(IRVar(name=old_name), field_type)),
            ]
        )

    def emit_property(
        self,
        declaration: ClassDecl,
        prop: PropertyDecl,
        selected_callables: frozenset[tuple[str, str]] | None = None,
    ) -> None:
        """Emit getter/setter functions for one declared property."""
        name = declaration.name
        prop_type = self._types.render(prop.type) if prop.type else "int"
        backing = f"_prop_{prop.name}"
        if prop.has_getter and (selected_callables is None or ("get", prop.name) in selected_callables):
            provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
            body = self._getter_body(
                prop,
                backing,
                prop_type,
                provenance,
            )
            self._session.module.function_defs.append(
                IRFunctionDef(
                    name=f"{name}_get_{prop.name}",
                    return_type=CType(text=prop_type),
                    params=[IRParam(c_type=CType(text=f"{name}*"), name="self")],
                    body=body,
                    is_static=self._specialized_linkage(),
                )
            )
        if prop.has_setter and (selected_callables is None or ("set", prop.name) in selected_callables):
            provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
            value_name = provenance.source_binding_c_name("value")
            body = self._setter_body(
                prop,
                backing,
                value_name,
                provenance,
            )
            self._session.module.function_defs.append(
                IRFunctionDef(
                    name=f"{name}_set_{prop.name}",
                    return_type=CType(text="void"),
                    params=[
                        IRParam(c_type=CType(text=f"{name}*"), name="self"),
                        provenance.lower_named_source_type_param(prop.type, prop_type, "value"),
                    ],
                    body=body,
                    is_static=self._specialized_linkage(),
                )
            )

    def emit_inherited_properties(
        self,
        declaration: ClassDecl,
        class_info: ClassInfo,
        own_properties: set[str],
        selected_callables: frozenset[tuple[str, str]] | None = None,
    ) -> None:
        """Expose direct-parent property accessors with child-typed wrappers."""
        parent_name = class_info.parent
        parent = self._analyzed.class_table.get(parent_name) if parent_name else None
        if parent is None:
            return
        cast_self = IRCast(target_type=CType(text=f"{parent_name}*"), expr=IRVar(name="self"))
        for name, prop in parent.properties.items():
            if name in own_properties:
                continue
            prop_type = CType(text=self._types.render(prop.type))
            if prop.has_getter and (selected_callables is None or ("get", name) in selected_callables):
                self._session.module.function_defs.append(
                    IRFunctionDef(
                        name=f"{declaration.name}_get_{name}",
                        return_type=prop_type,
                        params=[IRParam(c_type=CType(text=f"{declaration.name}*"), name="self")],
                        body=IRBlock(
                            stmts=[IRReturn(value=IRCall(callee=f"{parent_name}_get_{name}", args=[cast_self]))]
                        ),
                        is_static=self._specialized_linkage(),
                    )
                )
            if prop.has_setter and (selected_callables is None or ("set", name) in selected_callables):
                provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
                value_name = provenance.source_binding_c_name("value")
                self._session.module.function_defs.append(
                    IRFunctionDef(
                        name=f"{declaration.name}_set_{name}",
                        return_type=CType(text="void"),
                        params=[
                            IRParam(c_type=CType(text=f"{declaration.name}*"), name="self"),
                            provenance.lower_named_source_type_param(prop.type, prop_type, "value"),
                        ],
                        body=IRBlock(
                            stmts=[
                                IRExprStmt(
                                    expr=IRCall(
                                        callee=f"{parent_name}_set_{name}", args=[cast_self, IRVar(name=value_name)]
                                    )
                                )
                            ]
                        ),
                        is_static=self._specialized_linkage(),
                    )
                )

    def _getter_body(
        self,
        prop,
        backing,
        prop_type,
        provenance: CallableProvenance,
    ):
        if prop.getter_body is None:
            return IRBlock(stmts=[IRReturn(value=IRFieldAccess(obj=IRVar(name="self"), field=backing, arrow=True))])
        previous_return_type = self._session.current_return_type
        previous_return_c_type = self._session.current_return_c_type
        previous_return_owned = self._session.current_return_owned
        self._session.function_declarations = []
        self._session.current_return_c_type = prop_type
        self._session.current_return_type = prop.type
        self._session.current_return_owned = True
        previous_backing = self._session.current_property_backing
        self._session.current_property_backing = prop.name if StorageModel.property_needs_backing(prop) else None
        try:
            body = self._statements.lower_block(
                prop.getter_body,
                provenance,
                local_bindings=["self"],
            )
        finally:
            self._session.current_property_backing = previous_backing
            self._session.current_return_type = previous_return_type
            self._session.current_return_c_type = previous_return_c_type
            self._session.current_return_owned = previous_return_owned
        return body

    def _setter_body(
        self,
        prop,
        backing,
        value_name,
        provenance: CallableProvenance,
    ):
        if prop.setter_body is None:
            if self._values.is_managed(prop.type):
                target = IRFieldAccess(obj=IRVar(name="self"), field=backing, arrow=True)
                if self._values.is_arc(prop.type):
                    stmts = [
                        IRExprStmt(
                            expr=self._lifetime.replace_edge_value(
                                target, IRVar(name=value_name), prop.type, IRVar(name="self"), adopt=False
                            )
                        )
                    ]
                else:
                    old_name = self._session.fresh_temp("__btrc_property_old")
                    stmts = [
                        IRVarDecl(c_type=CType(text=self._types.render(prop.type)), name=old_name, init=target),
                        IRExprStmt(
                            expr=self._lifetime.unlink_edge_value(IRVar(name=old_name), prop.type, IRVar(name="self"))
                        ),
                        IRExprStmt(
                            expr=self._lifetime.retain_edge_value(IRVar(name=value_name), prop.type, IRVar(name="self"))
                        ),
                        IRAssign(target=target, value=IRVar(name=value_name)),
                        IRExprStmt(
                            expr=self._lifetime.release_edge_value(
                                IRVar(name=old_name), prop.type, replacement=IRVar(name=value_name)
                            )
                        ),
                    ]
                flush = self._lifetime.poll_released_values(prop.type)
                if flush is not None:
                    stmts.append(IRExprStmt(expr=flush))
                return IRBlock(stmts=stmts)
            return IRBlock(
                stmts=[
                    IRAssign(
                        target=IRFieldAccess(obj=IRVar(name="self"), field=backing, arrow=True),
                        value=IRVar(name=value_name),
                    )
                ]
            )
        previous_return_type = self._session.current_return_type
        previous_return_c_type = self._session.current_return_c_type
        self._session.function_declarations = []
        self._session.current_return_c_type = "void"
        self._session.current_return_type = None
        previous_backing = self._session.current_property_backing
        self._session.current_property_backing = prop.name if StorageModel.property_needs_backing(prop) else None
        try:
            body = self._statements.lower_block(
                prop.setter_body,
                provenance,
                local_bindings=["self", "value"],
                callable_bindings=[("value", prop.type)],
            )
        finally:
            self._session.current_property_backing = previous_backing
            self._session.current_return_type = previous_return_type
            self._session.current_return_c_type = previous_return_c_type
        return body

    def emit_static_fields(self, declaration: ClassDecl) -> None:
        for field in declaration.members:
            if not isinstance(field, FieldDecl) or field.access != "class":
                continue
            provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
            field_type, array_size = self._static_field_type(
                field,
                provenance,
            )
            initializer = field.initializer
            if initializer is not None:
                self._callable_boundaries.reject_persistent_escape(
                    field.type,
                    initializer,
                    "class field storage",
                    provenance,
                )
            init = (
                self._expressions.lower_static_initializer(
                    initializer,
                    provenance,
                )
                if initializer is not None
                else None
            )
            self._session.module.global_decls.append(
                IRGlobalDecl(
                    c_type=CType(text=self._types.render(field_type)),
                    name=f"{declaration.name}_{field.name}",
                    init=init,
                    array_size=array_size,
                    is_static=True,
                    is_volatile=bool(field.type.is_volatile),
                    effective_is_volatile=StorageModel.effective_outer_volatile(
                        field.type, self._analyzed.typedef_table
                    ),
                )
            )

    def _static_field_type(self, field, provenance: CallableProvenance):
        if not field.type.is_array:
            return (field.type, None)
        from src.compiler.python.analyzer.types import TypeSystem

        field_type = TypeSystem.strip_outer_storage(field.type, array=True)
        if field.type.array_size is not None:
            return (
                field_type,
                self._expressions.lower_expr(
                    field.type.array_size,
                    provenance,
                ),
            )
        if isinstance(field.initializer, (BraceInitializer, ListLiteral)):
            return (field_type, IRLiteral(text=str(len(field.initializer.elements))))
        return (field.type, None)

    def lower_instance_storage_field(
        self,
        name,
        field_type,
        provenance: CallableProvenance,
    ) -> IRStructField:
        """Preserve a fixed source array as embedded class-instance storage."""
        if field_type is not None and field_type.is_array and (field_type.array_size is not None):
            element_type = TypeSystem.strip_outer_storage(field_type, array=True)
            return IRStructField(
                c_type=CType(text=self._types.render(element_type)),
                name=name,
                array_size=self._expressions.lower_expr(
                    field_type.array_size,
                    provenance,
                ),
                is_volatile=bool(field_type.is_volatile),
                effective_is_volatile=StorageModel.effective_outer_volatile(field_type, self._analyzed.typedef_table),
            )
        return IRStructField(
            c_type=CType(text=self._types.render(field_type)),
            name=name,
            is_volatile=bool(field_type and field_type.is_volatile),
            effective_is_volatile=StorageModel.effective_outer_volatile(field_type, self._analyzed.typedef_table),
        )

    def emit_class_visitor(
        self,
        emitted_name: str,
        concrete_type: TypeExpr,
        storage: Iterable[tuple[str, object]],
    ) -> None:
        """Emit ``NAME_visit(object, fn)`` for one cyclable representation."""
        self._cycles.register_visitor(emitted_name)
        self._collections.ensure_cycle_callback_alias()
        visitor_name = self._cycles.visitor_symbol(emitted_name)
        params = [
            IRParam(c_type=CType(text="void*"), name="object"),
            IRParam(c_type=CType(text="__btrc_field_visit_fn"), name="fn"),
            IRParam(c_type=CType(text="void*"), name="context"),
        ]
        self._session.module.function_decls.append(
            IRFunctionDecl(name=visitor_name, return_type=CType(text="void"), params=list(params), is_static=True)
        )
        body = [
            IRVarDecl(
                c_type=CType(text=f"{emitted_name}*"),
                name="self",
                init=IRCast(target_type=CType(text=f"{emitted_name}*"), expr=IRVar(name="object")),
            )
        ]
        collection_visits = self._collections.cycle_storage_visit_stmts(
            concrete_type,
            IRVar(name="self"),
        )
        visited = bool(collection_visits)
        if collection_visits is not None:
            body.extend(collection_visits)
        else:
            specialization = self._session.active_specialization
            for field_name, field_decl in storage:
                field_type = getattr(field_decl, "type", None)
                if field_type is None:
                    continue
                if specialization is not None:
                    field_type = specialization.substitution.resolve(field_type)
                if field_type is None:
                    continue
                field = IRFieldAccess(obj=IRVar(name="self"), field=field_name, arrow=True)
                field_visits = self._collections.slot_visit_stmts(
                    field_type,
                    field,
                )
                visited = visited or bool(field_visits)
                body.extend(field_visits)
        if not visited:
            body.extend(
                [
                    IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="self"))),
                    IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="fn"))),
                    IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="context"))),
                ]
            )
        self._session.module.function_defs.append(
            IRFunctionDef(
                name=visitor_name,
                return_type=CType(text="void"),
                params=params,
                body=IRBlock(stmts=body),
                is_static=True,
                archive_export=True,
            )
        )

    def emit_struct_decl(self, decl: StructDecl):
        """Emit a plain struct (not class) definition."""
        if decl.is_forward:
            return
        provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        fields = []
        for f in decl.fields:
            if f.type and f.type.is_array and f.type.array_size:
                from src.compiler.python.analyzer.types import TypeSystem

                base_type = TypeSystem.strip_outer_storage(f.type, array=True)
                fields.append(
                    IRStructField(
                        c_type=CType(text=self._types.render(base_type)),
                        name=f.name,
                        array_size=self._expressions.lower_expr(
                            f.type.array_size,
                            provenance,
                        ),
                        is_volatile=bool(f.type.is_volatile),
                        effective_is_volatile=StorageModel.effective_outer_volatile(
                            f.type, self._analyzed.typedef_table
                        ),
                    )
                )
            else:
                fields.append(
                    IRStructField(
                        c_type=CType(text=self._types.render(f.type)),
                        name=f.name,
                        is_volatile=bool(f.type and f.type.is_volatile),
                        effective_is_volatile=StorageModel.effective_outer_volatile(
                            f.type, self._analyzed.typedef_table
                        ),
                    )
                )
        self._session.module.struct_defs.append(
            IRStructDef(name=decl.name, fields=fields, pack_alignment=self._pack_alignments.get(id(decl)))
        )

    def emit_class_decl(self, decl: ClassDecl):
        """Emit a class: struct + constructor + destructor + methods."""
        source_declaration = decl
        source_name = decl.name
        cls_info = self._analyzed.class_table.get(source_name)
        if not cls_info:
            return
        specialization = self._session.active_specialization
        selected_callables = specialization.selected_callables if specialization is not None else None
        if specialization is not None and specialization.declaration is decl:
            decl = replace(decl, name=specialization.symbol, generic_params=[])
        self._session.current_class = cls_info
        self._session.current_class_name = source_name
        self._emit_class_struct(
            decl,
            cls_info,
            source_declaration,
        )
        self.emit_static_fields(
            decl,
        )
        self.emit_class_callable_declarations(
            decl,
            cls_info,
            selected_callables,
        )
        self.emit_constructor(
            decl,
            cls_info,
        )
        destructor_hook = self.emit_destructor(
            decl,
            cls_info,
        )
        visitor_name = None
        specialized_type = TypeExpr(
            base=source_name,
            generic_args=list(specialization.type_arguments) if specialization is not None else [],
        )
        if self._cycles.type_needs_visitor(specialized_type, set()):
            self.emit_class_visitor(
                decl.name,
                specialized_type,
                cls_info.instance_storage,
            )
            visitor_name = self._cycles.visitor_symbol(decl.name)
        self._ownership.emit_arc_descriptor(decl.name, visitor_name, destructor_hook)
        own_methods = set()
        own_properties = set()
        for member in decl.members:
            if isinstance(member, MethodDecl) and (not member.is_constructor) and (member.name != "__del__"):
                own_methods.add(member.name)
                if (
                    not member.generic_params
                    and (not member.is_abstract)
                    and (member.body is not None)
                    and (selected_callables is None or ("method", member.name) in selected_callables)
                ):
                    self.emit_method(
                        decl,
                        member,
                    )
            elif isinstance(member, PropertyDecl):
                self.emit_property(
                    decl,
                    member,
                    selected_callables,
                )
                own_properties.add(member.name)
        self.emit_inherited_properties(
            decl,
            cls_info,
            own_properties,
            selected_callables,
        )
        if cls_info.parent and cls_info.parent in self._analyzed.class_table:
            self.emit_inherited_methods(
                decl,
                cls_info,
                own_methods,
                selected_callables,
            )
        self._session.current_class = None
        self._session.current_class_name = ""

    def _specialized_linkage(self) -> bool:
        """Whether the active class instance has translation-unit-local linkage."""
        return self._session.active_specialization is not None

    def _emit_class_struct(
        self,
        decl: ClassDecl,
        cls_info: ClassInfo,
        source_declaration: ClassDecl,
    ) -> None:
        """Emit the struct definition for a class."""
        provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        fields: list[IRStructField] = []
        fields.append(self._ownership.arc_header_field())
        for storage_name, member in cls_info.instance_storage:
            fields.append(
                self.lower_instance_storage_field(
                    storage_name,
                    member.type,
                    provenance,
                )
            )
        self._session.module.struct_defs.append(
            IRStructDef(
                name=decl.name,
                fields=fields,
                pack_alignment=self._pack_alignments.get(id(source_declaration)),
            )
        )

    @staticmethod
    def build_destructor_hook(owner_name: str, body: IRBlock) -> IRFunctionDef:
        """Build the isolated function containing a source ``__del__`` body."""
        return IRFunctionDef(
            name=GeneratedSymbolRegistry.destructor_hook_symbol(owner_name),
            return_type=CType(text="void"),
            params=[IRParam(c_type=CType(text="void*"), name="object")],
            body=IRBlock(
                stmts=[
                    IRVarDecl(
                        c_type=CType(text=f"{owner_name}*"),
                        name="self",
                        init=IRCast(target_type=CType(text=f"{owner_name}*"), expr=IRVar(name="object")),
                    ),
                    IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="self"))),
                    *body.stmts,
                ]
            ),
            is_static=True,
            archive_export=True,
        )
