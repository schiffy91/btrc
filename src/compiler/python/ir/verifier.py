"""Complete invariant verification for one structured IR translation unit."""

from __future__ import annotations

from typing import ClassVar

from .nodes import (
    IRAddressOf,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRDoWhile,
    IREnumDef,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionPointerTypedef,
    IRFunctionRef,
    IRGlobalDecl,
    IRGpuKernel,
    IRHelperDecl,
    IRInclude,
    IRLiteral,
    IRMacroDef,
    IRModule,
    IRNode,
    IRStructDef,
    IRStructForward,
    IRTaggedUnionDef,
    IRTypedefDef,
    IRVar,
    IRVarDecl,
    IRWhile,
)


class IRVerifier:
    """Validate translation-unit schema and typed cleanup metadata."""

    _REGISTER_ARITY: ClassVar[dict[str, int]] = {
        "__btrc_register_cleanup": 4,
        "__btrc_register_direct_cleanup": 3,
    }

    def __init__(self, module: IRModule) -> None:
        self.module = module
        self._functions: dict[str, IRFunctionDef] = {}
        self._attached_cleanup_sites: dict[int, str] = {}

    def validate(self) -> None:
        """Reject every malformed translation-unit invariant owned here."""

        self.validate_schema()
        self._functions = {function.name: function for function in self.module.function_defs}
        self._validate_cleanup_slots()
        self.validate_type_declarations()

    def validate_schema(self) -> None:
        """Reject raw strings and values in the wrong declaration category."""

        for field_name in ("freestanding", "needs_runtime", "debug"):
            if not isinstance(getattr(self.module, field_name), bool):
                raise TypeError(f"IRModule.{field_name} requires bool")

        for function in self.module.function_defs:
            if not isinstance(function.is_realtime, bool):
                raise TypeError("IRFunctionDef.is_realtime requires bool")

        if not isinstance(self.module.runtime_roots, set) or any(
            not isinstance(root, str) or not root for root in self.module.runtime_roots
        ):
            raise TypeError("IRModule.runtime_roots requires a set of non-empty strings")
        if not isinstance(self.module.realtime_safe_externals, set) or any(
            not isinstance(name, str) or not name for name in self.module.realtime_safe_externals
        ):
            raise TypeError("IRModule.realtime_safe_externals requires a set of non-empty strings")

        declaration_fields = (
            ("struct_forwards", IRStructForward),
            ("function_pointer_typedefs", IRFunctionPointerTypedef),
            ("function_decls", IRFunctionDecl),
            ("helper_decls", IRHelperDecl),
            ("enum_defs", IREnumDef),
            ("typedef_defs", IRTypedefDef),
            ("tagged_union_defs", IRTaggedUnionDef),
            ("struct_defs", IRStructDef),
            ("global_decls", IRGlobalDecl),
            ("function_defs", IRFunctionDef),
            ("gpu_kernels", IRGpuKernel),
        )
        for field_name, expected_type in declaration_fields:
            declarations = getattr(self.module, field_name)
            if not isinstance(declarations, list):
                raise TypeError(f"IRModule.{field_name} requires a list")
            for declaration in declarations:
                if not isinstance(declaration, expected_type):
                    raise TypeError(
                        f"IRModule.{field_name} requires {expected_type.__name__}, got {type(declaration).__name__}"
                    )

        if any(function.is_realtime for function in self.module.function_defs):
            self._functions = {function.name: function for function in self.module.function_defs}
            self._validate_realtime_functions()

        if not isinstance(self.module.preprocessor_decls, list):
            raise TypeError("IRModule.preprocessor_decls requires a list")
        for declaration in self.module.preprocessor_decls:
            if not isinstance(declaration, (IRInclude, IRMacroDef)):
                raise TypeError(
                    f"IRModule.preprocessor_decls requires IRInclude or IRMacroDef, got {type(declaration).__name__}"
                )
            if isinstance(declaration, IRMacroDef):
                declaration.validate()

    def validate_type_declarations(self) -> None:
        """Reject a stale optimizer-owned strict-C declaration order."""

        if not self.module.type_declaration_plan_is_current():
            self._raise_stale_type_declarations()

    @staticmethod
    def _raise_stale_type_declarations() -> None:
        raise ValueError(
            "IRModule.ordered_type_declarations is stale; "
            "call IROptimizer.refresh_type_declarations(module) after mutating "
            "type declarations"
        )

    def _validate_cleanup_slots(self) -> None:
        self._attached_cleanup_sites.clear()
        for function in self.module.function_defs:
            declarations: dict[int, IRCleanupSlot] = {}
            registrations: list[IRCall] = []
            for node in IRNode.walk_value(function.body):
                if isinstance(node, IRVarDecl) and node.cleanup_slot is not None:
                    metadata = node.cleanup_slot
                    self._validate_cleanup_declaration(node, metadata)
                    site = id(metadata)
                    if site in self._attached_cleanup_sites:
                        raise ValueError(f"cleanup metadata for {metadata.name!r} is attached more than once")
                    self._attached_cleanup_sites[site] = function.name
                    declarations[site] = metadata
                if isinstance(node, IRCall):
                    if isinstance(node.callee, str) and node.callee in self._REGISTER_ARITY:
                        registrations.append(node)
                    elif node.cleanup_slot is not None:
                        raise ValueError("cleanup metadata is attached to a non-registration call")
            self._validate_function_registrations(
                function.name,
                declarations,
                registrations,
            )

    def _validate_realtime_functions(self) -> None:
        """Backstop semantic realtime proofs against compiler-introduced IR."""

        for function in self.module.function_defs:
            if function.is_realtime:
                self._validate_realtime_function(function, (), frozenset())

    def _validate_realtime_function(self, function, path, visiting) -> None:
        if function.name in visiting:
            cycle = (*path, function.name)
            raise ValueError(f"IR realtime backstop rejected recursive call cycle via {' -> '.join(cycle)}")
        visiting = visiting | {function.name}
        path = (*path, function.name)
        for node in IRNode.walk_value(function.body):
            if isinstance(node, (IRWhile, IRDoWhile)):
                raise ValueError(f"IR realtime backstop rejected unbounded loop via {' -> '.join(path)}")
            if isinstance(node, IRFor):
                if not isinstance(node.realtime_bounded, bool):
                    raise TypeError("IRFor.realtime_bounded requires bool")
                if not node.realtime_bounded:
                    raise ValueError(f"IR realtime backstop rejected uncertified for loop via {' -> '.join(path)}")
            if isinstance(node, IRLiteral) and node.text.startswith(('"', 'L"', 'u"', 'U"', 'u8"')):
                raise ValueError(f"IR realtime backstop rejected string literal via {' -> '.join(path)}")
            if isinstance(node, IRFunctionRef):
                raise ValueError(f"IR realtime backstop rejected function value {node.name!r} via {' -> '.join(path)}")
            if not isinstance(node, IRCall):
                continue
            if not isinstance(node.callee, str) or not node.callee:
                raise ValueError(f"IR realtime backstop rejected indirect call via {' -> '.join(path)}")
            target = self._functions.get(node.callee)
            if target is None:
                if node.callee in self.module.realtime_safe_externals:
                    continue
                raise ValueError(
                    f"IR realtime backstop rejected external/runtime call {node.callee!r} via {' -> '.join(path)}"
                )
            self._validate_realtime_function(target, path, visiting)

    @staticmethod
    def _validate_cleanup_declaration(
        declaration: IRVarDecl,
        metadata: IRCleanupSlot,
    ) -> None:
        if metadata.name != declaration.name or metadata.c_type != declaration.c_type:
            raise ValueError(f"cleanup metadata does not describe slot {declaration.name!r}")
        if not declaration.is_volatile:
            raise ValueError(f"cleanup slot {declaration.name!r} is not volatile")

    def _validate_function_registrations(
        self,
        function_name: str,
        declarations: dict[int, IRCleanupSlot],
        registrations: list[IRCall],
    ) -> None:
        used_slots: set[int] = set()
        for call in registrations:
            metadata = self._validate_registration(call)
            if id(metadata) not in declarations:
                raise ValueError(
                    f"cleanup registration for {metadata.name!r} has no typed declaration in function {function_name!r}"
                )
            adapter = self._functions.get(metadata.take_function)
            if adapter is None or not adapter.is_static:
                raise ValueError(f"cleanup take adapter {metadata.take_function!r} is missing or non-static")
            used_slots.add(id(metadata))

        unused = declarations.keys() - used_slots
        if unused:
            names = ", ".join(sorted(declarations[site].name for site in unused))
            raise ValueError(f"cleanup slot metadata has no registration: {names}")

    def _validate_registration(self, call: IRCall) -> IRCleanupSlot:
        expected_arity = self._REGISTER_ARITY[call.callee]
        if call.helper_ref != call.callee or len(call.args) != expected_arity:
            raise ValueError(f"malformed {call.callee} call")
        metadata = call.cleanup_slot
        if metadata is None:
            raise ValueError(f"legacy untyped {call.callee} call")

        address = call.args[0]
        if (
            not isinstance(address, IRCast)
            or address.target_type.text != "void*"
            or not isinstance(address.expr, IRAddressOf)
            or not isinstance(address.expr.expr, IRVar)
            or address.expr.expr.name != metadata.name
        ):
            raise ValueError(f"cleanup slot {metadata.name!r} must use an opaque void* address")
        take = call.args[1]
        if not isinstance(take, IRFunctionRef) or take.name != metadata.take_function:
            raise ValueError(f"cleanup slot {metadata.name!r} has the wrong take adapter")
        return metadata


__all__ = ("IRVerifier",)
