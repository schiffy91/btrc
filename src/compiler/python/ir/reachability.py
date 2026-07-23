"""Reachability owners for top-level structured IR declarations."""

from __future__ import annotations

from typing import Protocol

from .expr_nodes import IRCall, IRFunctionRef, IRStmtExpr, IRUnaryOp, IRVar
from .module import IRModule
from .optimizer_walk import IdentifierReferences, IRTree
from .top_nodes import IREnumDef, IRGlobalDecl, IRHelperDecl, IRTaggedUnionDef

DeclarationKey = tuple[str, int]

_ENTRY_POINTS = frozenset({"main", "btrc_main"})
_MUTATING_UNARY_OPERATORS = frozenset({"++", "--"})


class _NamedDeclaration(Protocol):
    name: str | None


class ProgramReachability:
    """Prune the unified function/global graph of one translation unit."""

    def __init__(self, module: IRModule):
        self._module = module
        self._functions = {function.name: function for function in module.function_defs}
        self._globals_by_name: dict[str, list[IRGlobalDecl]] = {}
        for declaration in module.global_decls:
            self._globals_by_name.setdefault(declaration.name, []).append(declaration)
        self._function_names = set(self._functions)
        self._global_names = set(self._globals_by_name)

    def prune(self) -> None:
        live_functions = self._function_names & _ENTRY_POINTS
        live_globals = {
            name
            for name, declarations in self._globals_by_name.items()
            if any(self._is_global_root(declaration) for declaration in declarations)
        }
        IdentifierReferences(self._function_names).scan_macro_replacements(
            self._module.preprocessor_decls,
            live_functions,
        )
        IdentifierReferences(self._global_names).scan_macro_replacements(
            self._module.preprocessor_decls,
            live_globals,
        )

        worklist = [("function", name) for name in live_functions]
        worklist.extend(("global", name) for name in live_globals)
        while worklist:
            kind, name = worklist.pop()
            function_references: set[str] = set()
            global_references: set[str] = set()
            if kind == "function":
                self._collect_references(
                    self._functions[name].body,
                    function_references,
                    global_references,
                )
            else:
                for declaration in self._globals_by_name[name]:
                    self._collect_references(
                        declaration,
                        function_references,
                        global_references,
                    )
            self._extend_worklist(
                worklist,
                "function",
                function_references,
                live_functions,
            )
            self._extend_worklist(
                worklist,
                "global",
                global_references,
                live_globals,
            )

        removed_functions = self._function_names - live_functions
        self._module.function_defs = [
            function for function in self._module.function_defs if function.name in live_functions
        ]
        self._module.global_decls = [
            declaration for declaration in self._module.global_decls if declaration.name in live_globals
        ]
        if removed_functions:
            self._module.function_decls = [
                declaration for declaration in self._module.function_decls if declaration.name not in removed_functions
            ]

    def _collect_references(
        self,
        value: object,
        function_references: set[str],
        global_references: set[str],
    ) -> None:
        tree = IRTree(value)
        tree.collect_callable_references(
            self._function_names,
            function_references,
        )
        tree.collect_value_references(
            self._global_names,
            global_references,
        )
        for node in tree:
            if isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee in self._global_names:
                global_references.add(node.callee)

    @classmethod
    def _is_global_root(cls, declaration: IRGlobalDecl) -> bool:
        # Volatile affects accesses, not an unreachable internal object's
        # observability. External linkage and effects are the actual roots.
        return bool(
            not declaration.is_static
            or declaration.is_extern
            or cls._initializer_has_side_effects(declaration.init)
            or cls._initializer_has_side_effects(declaration.array_size)
        )

    @staticmethod
    def _initializer_has_side_effects(value: object) -> bool:
        for node in IRTree(value):
            if isinstance(node, (IRCall, IRStmtExpr)):
                return True
            if isinstance(node, IRUnaryOp) and node.op in _MUTATING_UNARY_OPERATORS:
                return True
        return False

    @staticmethod
    def _extend_worklist(
        worklist: list[tuple[str, str]],
        kind: str,
        references: set[str],
        live: set[str],
    ) -> None:
        for reference in references - live:
            live.add(reference)
            worklist.append((kind, reference))


class RuntimeSupportReachability:
    """Prune helper implementations and generated GPU constants as one pass."""

    def __init__(self, module: IRModule):
        self._module = module

    def prune(self) -> None:
        self._prune_gpu_kernels()
        self._prune_helpers()

    def _prune_gpu_kernels(self) -> None:
        if not self._module.gpu_kernels:
            return
        kernels_by_symbol = {f"{kernel.name}_wgsl": kernel for kernel in self._module.gpu_kernels}
        live_symbols = {
            node.name
            for function in self._module.function_defs
            for node in IRTree(function.body)
            if isinstance(node, IRVar) and node.name in kernels_by_symbol
        }
        self._module.gpu_kernels = [
            kernel for kernel in self._module.gpu_kernels if f"{kernel.name}_wgsl" in live_symbols
        ]

    def _prune_helpers(self) -> None:
        if not self._module.helper_decls:
            return

        helpers_by_name = {helper.name: helper for helper in self._module.helper_decls}
        names = set(helpers_by_name)
        identifiers = IdentifierReferences(names)
        # Structured declarations can depend on a helper-owned ABI without a
        # call node. Lowering records those explicit roots on the module.
        used = set(self._module.runtime_roots) & names
        for root in (*self._module.function_defs, *self._module.global_decls):
            self._collect_helper_references(root, names, used)
        identifiers.scan_macro_replacements(
            self._module.preprocessor_decls,
            used,
        )

        keep = self._helper_dependency_closure(
            used,
            helpers_by_name,
            identifiers,
        )
        self._module.helper_decls = [helper for helper in self._module.helper_decls if helper.name in keep]

    @staticmethod
    def _collect_helper_references(
        root: object,
        names: set[str],
        used: set[str],
    ) -> None:
        for node in IRTree(root):
            if isinstance(node, IRCall):
                if node.helper_ref in names:
                    used.add(node.helper_ref)
                if isinstance(node.callee, str) and node.callee in names:
                    used.add(node.callee)
            elif isinstance(node, IRFunctionRef) and node.name in names:
                # Cleanup and Mutex callbacks use helpers as values.
                used.add(node.name)

    @staticmethod
    def _helper_dependency_closure(
        roots: set[str],
        helpers_by_name: dict[str, IRHelperDecl],
        identifiers: IdentifierReferences,
    ) -> set[str]:
        keep = set(roots)
        worklist = list(roots)
        while worklist:
            helper = helpers_by_name[worklist.pop()]
            dependencies = {dependency for dependency in helper.depends_on if dependency in helpers_by_name}
            identifiers.scan(helper.c_source, dependencies)
            for dependency in dependencies - keep:
                keep.add(dependency)
                worklist.append(dependency)
        return keep


class DeclarationReachability:
    """Prune unused external functions and typed C declarations."""

    _GROUPS = (
        ("enum", "enum_defs"),
        ("forward", "struct_forwards"),
        ("fnptr", "function_pointer_typedefs"),
        ("typedef", "typedef_defs"),
        ("tagged", "tagged_union_defs"),
        ("struct", "struct_defs"),
    )

    def __init__(self, module: IRModule):
        self._module = module

    def prune(self) -> None:
        self._prune_externs()
        self._prune_types()

    def _prune_externs(self) -> None:
        defined = {function.name for function in self._module.function_defs}
        declarations_by_name = {
            declaration.name: declaration
            for declaration in self._module.function_decls
            if declaration.name not in defined
        }
        if not declarations_by_name:
            return

        names = set(declarations_by_name)
        identifiers = IdentifierReferences(names)
        referenced: set[str] = set()
        for root in (*self._module.function_defs, *self._module.global_decls):
            IRTree(root).collect_callable_references(names, referenced)
        identifiers.scan_macro_replacements(
            self._module.preprocessor_decls,
            referenced,
        )
        for helper in self._module.helper_decls:
            identifiers.scan(helper.c_source, referenced)

        dead = names - referenced
        self._module.function_decls = [
            declaration for declaration in self._module.function_decls if declaration.name not in dead
        ]

    def _prune_types(self) -> None:
        declarations = self._type_declarations()
        if not declarations:
            return

        type_providers: dict[str, set[DeclarationKey]] = {}
        value_providers: dict[str, set[DeclarationKey]] = {}
        for key, declaration in declarations.items():
            for name in self._provided_type_names(declaration):
                type_providers.setdefault(name, set()).add(key)
            for name in self._provided_value_names(declaration):
                value_providers.setdefault(name, set()).add(key)

        type_names = set(type_providers)
        value_names = set(value_providers)
        type_identifiers = IdentifierReferences(type_names)
        value_identifiers = IdentifierReferences(value_names)
        referenced_types: set[str] = set()
        referenced_values: set[str] = set()
        for root in (
            *self._module.function_defs,
            *self._module.global_decls,
            *self._module.function_decls,
        ):
            tree = IRTree(root)
            tree.collect_c_type_references(
                type_identifiers,
                referenced_types,
            )
            tree.collect_value_references(
                value_names,
                referenced_values,
            )
        for helper in self._module.helper_decls:
            type_identifiers.scan(helper.c_source, referenced_types)
            value_identifiers.scan(helper.c_source, referenced_values)
        type_identifiers.scan_macro_replacements(
            self._module.preprocessor_decls,
            referenced_types,
        )
        value_identifiers.scan_macro_replacements(
            self._module.preprocessor_decls,
            referenced_values,
        )

        keep = self._provider_keys(
            referenced_types,
            type_providers,
        )
        keep.update(
            self._provider_keys(
                referenced_values,
                value_providers,
            )
        )
        worklist = list(keep)
        while worklist:
            declaration = declarations[worklist.pop()]
            dependencies: set[str] = set()
            value_dependencies: set[str] = set()
            tree = IRTree(declaration)
            tree.collect_c_type_references(
                type_identifiers,
                dependencies,
            )
            tree.collect_value_references(
                value_names,
                value_dependencies,
            )
            required = self._provider_keys(
                dependencies,
                type_providers,
            )
            required.update(
                self._provider_keys(
                    value_dependencies,
                    value_providers,
                )
            )
            for key in required - keep:
                keep.add(key)
                worklist.append(key)

        for kind, field_name in self._GROUPS:
            declarations_in_group = getattr(self._module, field_name)
            setattr(
                self._module,
                field_name,
                [declaration for index, declaration in enumerate(declarations_in_group) if (kind, index) in keep],
            )

    def _type_declarations(self) -> dict[DeclarationKey, _NamedDeclaration]:
        return {
            (kind, index): declaration
            for kind, field_name in self._GROUPS
            for index, declaration in enumerate(getattr(self._module, field_name))
        }

    @staticmethod
    def _provided_type_names(
        declaration: _NamedDeclaration,
    ) -> set[str]:
        names = {declaration.name} if declaration.name is not None else set()
        if isinstance(declaration, IRTaggedUnionDef):
            names.update(
                f"{declaration.name}_{variant.name}_Data" for variant in declaration.variants if variant.fields
            )
        return names

    @staticmethod
    def _provided_value_names(
        declaration: _NamedDeclaration,
    ) -> set[str]:
        if not isinstance(declaration, IREnumDef):
            return set()
        return {value.name for value in declaration.values}

    @staticmethod
    def _provider_keys(
        names: set[str],
        providers: dict[str, set[DeclarationKey]],
    ) -> set[DeclarationKey]:
        return {key for name in names for key in providers.get(name, ())}


__all__ = [
    "DeclarationReachability",
    "ProgramReachability",
    "RuntimeSupportReachability",
]
