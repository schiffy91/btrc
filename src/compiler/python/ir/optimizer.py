"""Owned optimization, reachability, ordering, and boundary passes for structured IR."""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable
from dataclasses import replace

from ..abi.freestanding import FreestandingRuntime
from ..runtime.catalog import RuntimeHelperCatalog
from .nodes import (
    CType,
    IRBlock,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRCxxNew,
    IRDoWhile,
    IREnumDef,
    IRExprStmt,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionPointerTypedef,
    IRFunctionRef,
    IRGlobalDecl,
    IRHelperDecl,
    IRIf,
    IRInclude,
    IRLiteral,
    IRMacroDef,
    IRModule,
    IRNode,
    IRObjectiveCBlock,
    IRObjectiveCMessage,
    IRParam,
    IRReturn,
    IRStatementSequence,
    IRStmtExpr,
    IRStructDef,
    IRSwitch,
    IRTaggedUnionDef,
    IRTypedefDef,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)

PUBLIC_COLLECTION_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})
_PROGRAM_ENTRIES = frozenset({"btrc_main", "main"})
_ENTRY_POINTS = frozenset({"main", "btrc_main"})
_CYCLABLE_RELEASE_HELPERS = frozenset({"__btrc_arc_release", "__btrc_arc_release_edge", "__btrc_arc_replace_edge"})
_MUTATING_UNARY_OPERATORS = frozenset({"++", "--"})
_ASSIGNMENT_OPERATORS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="})
_MUTATING_CALL_SLOT = {
    "__btrc_arc_replace_edge": 0,
    "__btrc_safe_realloc": 0,
    "free": 0,
    "memcpy": 0,
    "memmove": 0,
    "memset": 0,
    "qsort": 0,
    "realloc": 0,
}
_GPU_RUNTIME_FEATURE = "BTRC_RT_NEEDS_GPU"
_GPU_RUNTIME_HEADER = "btrc_gpu_compute_internal.h"
_SETJMP_RUNTIME_HEADER = "setjmp.h"
# Generated file-scope adapter families, each numbered from 1 by its owner.
_ADAPTER_FAMILIES = (
    "__btrc_arc_slot_access_",
    "__btrc_mutex_value_access_",
    "__btrc_store_",
    "__btrc_cleanup_take_",
)
_DECLARATION_GROUPS = (
    ("enum", "enum_defs"),
    ("forward", "struct_forwards"),
    ("fnptr", "function_pointer_typedefs"),
    ("typedef", "typedef_defs"),
    ("tagged", "tagged_union_defs"),
    ("struct", "struct_defs"),
)
_AGGREGATE_TYPES = (IRStructDef, IRTaggedUnionDef)
_COMPLETE_TYPE_CONTEXTS = (*_AGGREGATE_TYPES, IREnumDef)
TypeDeclaration = IREnumDef | IRFunctionPointerTypedef | IRTypedefDef | IRTaggedUnionDef | IRStructDef
DeclarationKey = tuple[str, int]


class IROptimizer:
    """Own the complete ordered optimization cascade for one mutable IR module."""

    _C_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    _IDENTIFIER_TOKEN = re.compile(r"\b[A-Za-z_]\w*")
    _C_NON_CODE = re.compile(
        r"/\*.*?\*/|//(?:\\\n|[^\n])*(?:\n|$)|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
        re.DOTALL,
    )

    def __init__(
        self,
        module: IRModule,
        *,
        dce: bool = True,
        runtime_catalog: RuntimeHelperCatalog | None = None,
        freestanding_runtime: FreestandingRuntime | None = None,
        module_unit: bool = False,
        program_cyclable_release: bool | None = None,
    ) -> None:
        self._module = module
        self._dce = dce
        # A module unit's external definitions are reachable from other units,
        # and whether any unit releases a cyclable value is a program fact.
        self._module_unit = module_unit
        self._program_cyclable_release = program_cyclable_release
        self._runtime_catalog = runtime_catalog or RuntimeHelperCatalog()
        self._freestanding_runtime = freestanding_runtime or FreestandingRuntime()

    def optimize(self) -> IRModule:
        """Apply optimization mutations and return the transformed module."""

        if self._dce and self._module_unit:
            # A module unit declares the whole program; drop the prototypes
            # its own definitions never reference before any full walk.
            self._prune_externs()
        if self._dce:
            self._prune_program_reachability()
        self._install_program_cycle_boundary()
        self._rematerialize_runtime_helpers()
        if self._dce:
            self._prune_runtime_support()
            self._prune_declarations()
            # Type declarations participate in helper reachability too.  The
            # first pass preserves providers for every candidate declaration;
            # after type DCE, this pass removes providers owned only by dead
            # structs/typedefs while retaining providers used by live CTypes.
            self._prune_runtime_support()
        self._normalize_unused_parameters()
        self._order_prototypes()
        self._renumber_adapters()
        self._renumber_temporaries()
        if not self._module.freestanding:
            # Keep the standalone Stage-5 API complete; the application
            # finalizer repeats this idempotently while deriving the remaining
            # hosted/freestanding runtime state.
            self._remove_generated_preprocessor()
            self._refresh_hosted_runtime_headers()
        return self._module

    @staticmethod
    def _identifier_pattern(names: Iterable[str]) -> frozenset[str] | None:
        """The identifier names one scan looks for, or None when there are none."""
        return frozenset(names) or None

    @staticmethod
    @functools.lru_cache(maxsize=8192)
    def _code_identifiers(text: str) -> frozenset[str]:
        """Every identifier token of C code, outside comments and literals.

        A name occurs as a whole identifier exactly when it is one of these
        tokens, so scanning for a set of names is one tokenization per text.
        """
        return frozenset(IROptimizer._IDENTIFIER_TOKEN.findall(IROptimizer._C_NON_CODE.sub(" ", text)))

    @classmethod
    def identifier_tokens(cls, text: str) -> frozenset[str]:
        """Identifier tokens of C text outside comments and literals."""
        return cls._code_identifiers(text)

    @staticmethod
    def _scan_identifiers(
        names: frozenset[str] | None,
        text: str,
        out: set[str],
    ) -> None:
        if names:
            # Runtime helpers and macro replacements are C source, not bags of
            # words.  A helper name in prose or literal data is not a semantic
            # dependency and must not keep an otherwise dead helper alive.
            out.update(IROptimizer._code_identifiers(text) & names)

    @classmethod
    def _scan_macro_replacements(
        cls,
        pattern: frozenset[str] | None,
        macros,
        out: set[str],
    ) -> None:
        for declaration in macros:
            replacement = getattr(declaration, "replacement", None)
            if isinstance(replacement, str):
                cls._scan_identifiers(pattern, replacement, out)

    @staticmethod
    def _collect_value_references(root: object, names: set[str], out: set[str]) -> None:
        for node in IRNode.walk_value(root):
            if isinstance(node, IRVar) and node.name in names:
                out.add(node.name)

    @staticmethod
    def _collect_callable_references(root: object, names: set[str], out: set[str]) -> None:
        for node in IRNode.walk_value(root):
            if isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee in names:
                out.add(node.callee)
            elif isinstance(node, IRFunctionRef) and node.name in names:
                out.add(node.name)

    @classmethod
    def _collect_c_type_references(
        cls,
        root: object,
        pattern: frozenset[str] | None,
        out: set[str],
    ) -> None:
        for node in IRNode.walk_value(root):
            if isinstance(node, CType):
                cls._scan_identifiers(pattern, node.text, out)

    @classmethod
    def plan_type_declarations(cls, module: IRModule) -> list[TypeDeclaration]:
        """Return the stable strict-C dependency order for typed declarations."""

        declarations: tuple[TypeDeclaration, ...] = (
            *module.enum_defs,
            *module.function_pointer_typedefs,
            *module.typedef_defs,
            *module.tagged_union_defs,
            *module.struct_defs,
        )
        if not declarations:
            return []
        providers = cls._type_providers(declarations)
        value_providers = cls._enum_value_providers(declarations)
        pattern = cls._identifier_pattern(providers)
        alias_targets = cls._alias_complete_targets(declarations, providers, pattern)
        dependencies = [
            cls._type_dependencies(
                index,
                declaration,
                declarations,
                providers,
                value_providers,
                pattern,
                alias_targets,
            )
            for index, declaration in enumerate(declarations)
        ]
        return cls._stable_type_order(declarations, dependencies)

    @classmethod
    def refresh_type_declarations(cls, module: IRModule) -> None:
        """Refresh the module's derived strict-C declaration order."""

        planned = cls.plan_type_declarations(module)
        module.record_type_declaration_plan(planned)
        for unit in module.native_units.values():
            cls.refresh_type_declarations(unit)

    @staticmethod
    def _provided_type_names_for_order(declaration: TypeDeclaration) -> Iterable[str]:
        if isinstance(declaration, IREnumDef):
            if declaration.name is not None:
                yield declaration.name
            return
        yield declaration.name
        if isinstance(declaration, IRTaggedUnionDef):
            for variant in declaration.variants:
                if variant.fields:
                    yield f"{declaration.name}_{variant.name}_Data"

    @classmethod
    def _type_providers(cls, declarations: tuple[TypeDeclaration, ...]) -> dict[str, int]:
        providers: dict[str, int] = {}
        for index, declaration in enumerate(declarations):
            for name in cls._provided_type_names_for_order(declaration):
                previous = providers.get(name)
                if previous is not None and previous != index:
                    raise ValueError(f"duplicate typed C declaration provider '{name}'")
                providers[name] = index
        return providers

    @staticmethod
    def _enum_value_providers(declarations: tuple[TypeDeclaration, ...]) -> dict[str, int]:
        providers: dict[str, int] = {}
        for index, declaration in enumerate(declarations):
            if not isinstance(declaration, IREnumDef):
                continue
            for value in declaration.values:
                previous = providers.get(value.name)
                if previous is not None and previous != index:
                    raise ValueError(f"duplicate typed C enum-value provider '{value.name}'")
                providers[value.name] = index
        return providers

    @classmethod
    def _ctype_references(
        cls,
        c_type: CType,
        pattern: frozenset[str] | None,
    ) -> set[str]:
        references: set[str] = set()
        cls._scan_identifiers(pattern, c_type.text, references)
        return references

    @classmethod
    def _alias_complete_targets(
        cls,
        declarations: tuple[TypeDeclaration, ...],
        providers: dict[str, int],
        pattern: frozenset[str] | None,
    ) -> dict[int, set[int]]:
        memo: dict[int, set[int]] = {}
        for index in range(len(declarations)):
            cls._resolve_alias_targets(index, declarations, providers, pattern, memo, set())
        return memo

    @classmethod
    def _resolve_alias_targets(
        cls,
        index: int,
        declarations: tuple[TypeDeclaration, ...],
        providers: dict[str, int],
        pattern: frozenset[str] | None,
        memo: dict[int, set[int]],
        visiting: set[int],
    ) -> set[int]:
        if index in memo:
            return memo[index]
        if index in visiting:
            return set()
        declaration = declarations[index]
        if not isinstance(declaration, IRTypedefDef):
            return set()
        if "*" in declaration.target_type.text:
            memo[index] = set()
            return set()
        visiting.add(index)
        targets: set[int] = set()
        for name in cls._ctype_references(declaration.target_type, pattern):
            provider = providers[name]
            provided = declarations[provider]
            if isinstance(provided, _AGGREGATE_TYPES):
                targets.add(provider)
            elif isinstance(provided, IRTypedefDef):
                targets.update(
                    cls._resolve_alias_targets(
                        provider,
                        declarations,
                        providers,
                        pattern,
                        memo,
                        visiting,
                    )
                )
        visiting.remove(index)
        memo[index] = targets
        return targets

    @classmethod
    def _type_dependencies(
        cls,
        declaration_index: int,
        declaration: TypeDeclaration,
        declarations: tuple[TypeDeclaration, ...],
        providers: dict[str, int],
        value_providers: dict[str, int],
        pattern: frozenset[str] | None,
        alias_targets: dict[int, set[int]],
    ) -> set[int]:
        dependencies: set[int] = set()
        complete_type_context = isinstance(declaration, _COMPLETE_TYPE_CONTEXTS)
        for node in IRNode.walk_value(declaration):
            if not isinstance(node, CType):
                continue
            requires_complete = complete_type_context and "*" not in node.text
            for name in cls._ctype_references(node, pattern):
                provider = providers[name]
                provided = declarations[provider]
                if not isinstance(provided, _AGGREGATE_TYPES) or requires_complete:
                    dependencies.add(provider)
                if requires_complete and isinstance(provided, IRTypedefDef):
                    dependencies.update(alias_targets.get(provider, ()))
        if isinstance(declaration, IREnumDef) and value_providers:
            references: set[str] = set()
            cls._collect_value_references(declaration, set(value_providers), references)
            dependencies.update(
                value_providers[name] for name in references if value_providers[name] != declaration_index
            )
        return dependencies

    @staticmethod
    def _stable_type_order(
        declarations: tuple[TypeDeclaration, ...],
        dependencies: list[set[int]],
    ) -> list[TypeDeclaration]:
        completed: set[int] = set()
        ordered: list[TypeDeclaration] = []
        while len(ordered) < len(declarations):
            progressed = False
            for index, declaration in enumerate(declarations):
                if index in completed or not dependencies[index] <= completed:
                    continue
                completed.add(index)
                ordered.append(declaration)
                progressed = True
            if progressed:
                continue
            names = ", ".join(
                declaration.name or "<anonymous enum>"
                for index, declaration in enumerate(declarations)
                if index not in completed
            )
            raise ValueError(f"cyclic typed C declaration dependency involving {names}")
        return ordered

    def _prune_program_reachability(self) -> None:
        self._functions = {function.name: function for function in self._module.function_defs}
        self._globals_by_name: dict[str, list[IRGlobalDecl]] = {}
        for declaration in self._module.global_decls:
            self._globals_by_name.setdefault(declaration.name, []).append(declaration)
        self._function_names = set(self._functions)
        self._global_names = set(self._globals_by_name)
        live_functions = self._function_names & _ENTRY_POINTS
        if self._module_unit:
            live_functions |= {function.name for function in self._module.function_defs if not function.is_static}
        live_globals = {
            name
            for name, declarations in self._globals_by_name.items()
            if any(self._is_global_root(declaration) for declaration in declarations)
        }
        self._scan_macro_replacements(
            self._identifier_pattern(self._function_names),
            self._module.preprocessor_decls,
            live_functions,
        )
        self._scan_macro_replacements(
            self._identifier_pattern(self._global_names),
            self._module.preprocessor_decls,
            live_globals,
        )
        for declaration in self._module.objective_c_classes:
            self._collect_program_references(declaration, live_functions, live_globals)
        worklist = [("function", name) for name in live_functions]
        worklist.extend(("global", name) for name in live_globals)
        while worklist:
            kind, name = worklist.pop()
            function_references: set[str] = set()
            global_references: set[str] = set()
            roots = [self._functions[name].body] if kind == "function" else self._globals_by_name[name]
            for root in roots:
                self._collect_program_references(root, function_references, global_references)
            self._extend_worklist(worklist, "function", function_references, live_functions)
            self._extend_worklist(worklist, "global", global_references, live_globals)
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

    def _collect_program_references(
        self,
        value: object,
        function_references: set[str],
        global_references: set[str],
    ) -> None:
        self._collect_callable_references(value, self._function_names, function_references)
        self._collect_value_references(value, self._global_names, global_references)
        for node in IRNode.walk_value(value):
            if isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee in self._global_names:
                global_references.add(node.callee)

    @classmethod
    def _is_global_root(cls, declaration: IRGlobalDecl) -> bool:
        return bool(
            not declaration.is_static
            or declaration.is_extern
            or cls._initializer_has_side_effects(declaration.init)
            or cls._initializer_has_side_effects(declaration.array_size)
        )

    @staticmethod
    def _initializer_has_side_effects(value: object) -> bool:
        for node in IRNode.walk_value(value):
            if isinstance(node, (IRCall, IRStmtExpr, IRObjectiveCMessage, IRObjectiveCBlock, IRCxxNew)) or (
                isinstance(node, IRCast) and node.bridge in ("retain", "transfer")
            ):
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

    def _prune_runtime_support(self) -> None:
        self._prune_gpu_kernels()
        self._prune_helpers()

    def _prune_gpu_kernels(self) -> None:
        if not self._module.gpu_kernels:
            return
        kernels_by_symbol = {f"{kernel.name}_wgsl": kernel for kernel in self._module.gpu_kernels}
        live_symbols = {
            node.name
            for root in (*self._module.function_defs, *self._module.objective_c_classes)
            for node in IRNode.walk_value(root)
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
        pattern = self._identifier_pattern(names)
        used = set(self._module.runtime_roots) & names
        for root in (*self._module.function_defs, *self._module.global_decls, *self._module.objective_c_classes):
            self._collect_helper_references(root, names, used)
        provider_helpers: set[str] = set()
        self._collect_runtime_provider_references(self._module, provider_helpers)
        used.update(provider_helpers & names)
        self._scan_macro_replacements(pattern, self._module.preprocessor_decls, used)
        keep = self._helper_dependency_closure(used, helpers_by_name)
        self._module.helper_decls = [helper for helper in self._module.helper_decls if helper.name in keep]

    @staticmethod
    def _collect_helper_references(root: object, names: set[str], used: set[str]) -> None:
        for node in IRNode.walk_value(root):
            if isinstance(node, IRCall):
                if node.helper_ref in names:
                    used.add(node.helper_ref)
                if isinstance(node.callee, str) and node.callee in names:
                    used.add(node.callee)
            elif isinstance(node, IRFunctionRef) and node.name in names:
                used.add(node.name)

    def _collect_runtime_provider_references(self, root: object, used: set[str]) -> None:
        """Root catalog providers named by structured C declarations."""
        type_names = {
            identifier
            for node in IRNode.walk_value(root)
            if isinstance(node, CType)
            for identifier in self._C_IDENTIFIER.findall(node.text)
        }
        object_names = {node.name for node in IRNode.walk_value(root) if isinstance(node, IRVar)}
        used.update(self._runtime_catalog.helper_names_providing_types(type_names))
        used.update(self._runtime_catalog.helper_names_providing_objects(object_names))

    @staticmethod
    def _helper_dependency_closure(
        roots: set[str],
        helpers_by_name: dict[str, IRHelperDecl],
    ) -> set[str]:
        keep = set(roots)
        worklist = list(roots)
        while worklist:
            helper = helpers_by_name[worklist.pop()]
            dependencies = {dependency for dependency in helper.depends_on if dependency in helpers_by_name}
            for dependency in dependencies - keep:
                keep.add(dependency)
                worklist.append(dependency)
        return keep

    def _prune_declarations(self) -> None:
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
        pattern = self._identifier_pattern(names)
        referenced: set[str] = set()
        for root in (*self._module.function_defs, *self._module.global_decls, *self._module.objective_c_classes):
            self._collect_callable_references(root, names, referenced)
        self._scan_macro_replacements(pattern, self._module.preprocessor_decls, referenced)
        for helper in self._module.helper_decls:
            self._scan_identifiers(pattern, helper.c_source, referenced)
        dead = names - referenced
        self._module.function_decls = [
            declaration for declaration in self._module.function_decls if declaration.name not in dead
        ]

    def _prune_types(self) -> None:
        declarations = self._reachable_type_declarations()
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
        type_pattern = self._identifier_pattern(type_names)
        value_pattern = self._identifier_pattern(value_names)
        referenced_types: set[str] = set()
        referenced_values: set[str] = set()
        for root in (
            *self._module.function_defs,
            *self._module.global_decls,
            *self._module.function_decls,
            *self._module.objective_c_classes,
        ):
            self._collect_c_type_references(root, type_pattern, referenced_types)
            self._collect_value_references(root, value_names, referenced_values)
        for helper in self._module.helper_decls:
            self._scan_identifiers(type_pattern, helper.c_source, referenced_types)
            self._scan_identifiers(value_pattern, helper.c_source, referenced_values)
        self._scan_macro_replacements(type_pattern, self._module.preprocessor_decls, referenced_types)
        self._scan_macro_replacements(value_pattern, self._module.preprocessor_decls, referenced_values)
        keep = self._provider_keys(referenced_types, type_providers)
        keep.update(self._provider_keys(referenced_values, value_providers))
        keep.update(
            key
            for key, declaration in declarations.items()
            if isinstance(declaration, IREnumDef)
            and any(value.name.startswith("__btrc_atomic_lock_free_") for value in declaration.values)
        )
        worklist = list(keep)
        while worklist:
            declaration = declarations[worklist.pop()]
            dependencies: set[str] = set()
            value_dependencies: set[str] = set()
            self._collect_c_type_references(declaration, type_pattern, dependencies)
            self._collect_value_references(declaration, value_names, value_dependencies)
            required = self._provider_keys(dependencies, type_providers)
            required.update(self._provider_keys(value_dependencies, value_providers))
            for key in required - keep:
                keep.add(key)
                worklist.append(key)
        for kind, field_name in _DECLARATION_GROUPS:
            values = getattr(self._module, field_name)
            setattr(
                self._module,
                field_name,
                [value for index, value in enumerate(values) if (kind, index) in keep],
            )

    def _reachable_type_declarations(self) -> dict[DeclarationKey, object]:
        return {
            (kind, index): declaration
            for kind, field_name in _DECLARATION_GROUPS
            for index, declaration in enumerate(getattr(self._module, field_name))
        }

    @staticmethod
    def _provided_type_names(declaration: object) -> set[str]:
        names = {declaration.name} if declaration.name is not None else set()
        if isinstance(declaration, IRTaggedUnionDef):
            names.update(
                f"{declaration.name}_{variant.name}_Data" for variant in declaration.variants if variant.fields
            )
        return names

    @staticmethod
    def _provided_value_names(declaration: object) -> set[str]:
        if not isinstance(declaration, IREnumDef):
            return set()
        return {value.name for value in declaration.values}

    @staticmethod
    def _provider_keys(
        names: set[str],
        providers: dict[str, set[DeclarationKey]],
    ) -> set[DeclarationKey]:
        return {key for name in names for key in providers.get(name, ())}

    def _renumber_adapters(self) -> None:
        """Order and number each generated adapter family by first use.

        Adapters are created when lowering first needs them, so creation
        order followed the order functions were lowered in, and a family's
        names depended on adapters that only dead functions used. After
        dead-code elimination each family is ordered by the first surviving
        non-adapter function that names a member, ties keeping creation
        order, then its definitions take that order and its members are
        numbered from 1; btrcc's optimizer applies the same rule.
        """
        definitions = self._module.function_defs
        families = {
            prefix: [
                index
                for index, function in enumerate(definitions)
                if function.name.startswith(prefix) and function.name[len(prefix) :].isdigit()
            ]
            for prefix in _ADAPTER_FAMILIES
        }
        members = {definitions[index].name for indexes in families.values() for index in indexes}
        if not members:
            return
        first_use: dict[str, int] = {}
        for position, function in enumerate(definitions):
            if function.name in members:
                continue
            for node in IRNode.walk_value(function):
                for name in IROptimizer._adapter_references(node):
                    if name in members:
                        first_use.setdefault(name, position)
        placeholders: dict[str, str] = {}
        finals: dict[str, str] = {}
        reordered = list(definitions)
        for prefix, indexes in families.items():
            ordered = sorted(indexes, key=lambda index: (first_use.get(definitions[index].name, len(definitions)), index))
            for slot, (index, source) in enumerate(zip(indexes, ordered, strict=True), start=1):
                reordered[index] = definitions[source]
                placeholder = f"#{prefix}{slot}"
                placeholders[definitions[source].name] = placeholder
                finals[placeholder] = f"{prefix}{slot}"
        self._module.function_defs[:] = reordered
        if not any(name != finals[placeholder] for name, placeholder in placeholders.items()):
            return
        nodes = tuple(IRNode.walk_value(self._module))
        self._rename_symbols(nodes, placeholders)
        self._rename_symbols(nodes, finals)

    @staticmethod
    def _adapter_references(node) -> tuple[str, ...]:
        """Symbols one IR node names that could be a generated adapter."""
        names: list[str] = []
        if isinstance(node, IRFunctionRef):
            names.append(node.name)
        elif isinstance(node, IRCall) and isinstance(node.callee, str):
            names.append(node.callee)
        slot = getattr(node, "cleanup_slot", None)
        if isinstance(slot, IRCleanupSlot):
            names.append(slot.take_function)
        return tuple(names)

    @staticmethod
    def _rename_symbols(nodes: tuple[object, ...], renamed: dict[str, str]) -> None:
        renamed_slots: dict[int, IRCleanupSlot] = {}
        for node in nodes:
            if isinstance(node, (IRFunctionDef, IRFunctionDecl, IRFunctionRef)) and node.name in renamed:
                node.name = renamed[node.name]
            elif isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee in renamed:
                node.callee = renamed[node.callee]
                if node.helper_ref in renamed:
                    node.helper_ref = renamed[node.helper_ref]
            slot = getattr(node, "cleanup_slot", None)
            if isinstance(slot, IRCleanupSlot) and slot.take_function in renamed:
                if id(slot) not in renamed_slots:
                    renamed_slots[id(slot)] = replace(slot, take_function=renamed[slot.take_function])
                node.cleanup_slot = renamed_slots[id(slot)]

    def _renumber_temporaries(self) -> None:
        """Number each function's compiler temporaries from 1, in allocation order.

        Lowering draws every temporary from one counter, so a function's names
        depended on how much else was lowered before it, including functions
        dead-code elimination later removed. Renumbering per function keeps
        each prefix and the allocation order and skips any number a
        non-temporary name in the function already spells. btrcc's optimizer
        applies the same rule.
        """
        generated = self._module.temporary_names
        if not generated:
            return
        bodies = [*self._module.function_defs]
        for declaration in self._module.objective_c_classes:
            bodies.extend(declaration.methods)
        for function in bodies:
            nodes = tuple(IRNode.walk_value(function))
            temporaries: dict[str, int] = {}
            occupied: set[str] = set()
            for node in nodes:
                name = getattr(node, "name", None) if isinstance(node, (IRVar, IRVarDecl, IRParam)) else None
                if not isinstance(name, str):
                    continue
                if name in generated:
                    prefix, _, number = name.rpartition("_")
                    temporaries[name] = int(number) if number.isdigit() and prefix else 0
                else:
                    occupied.add(name)
            if not temporaries:
                continue
            # Two phases through placeholders no identifier can spell, so a
            # node the IR shares between two places is never renamed twice.
            placeholders: dict[str, str] = {}
            finals: dict[str, str] = {}
            counter = 0
            for name in sorted(temporaries, key=lambda item: temporaries[item]):
                if not temporaries[name]:
                    continue
                prefix = name.rpartition("_")[0]
                while True:
                    counter += 1
                    candidate = f"{prefix}_{counter}"
                    if candidate not in occupied:
                        break
                placeholders[name] = f"#{counter}"
                finals[f"#{counter}"] = candidate
            self._rename_temporaries(nodes, placeholders)
            self._rename_temporaries(nodes, finals)

    @staticmethod
    def _rename_temporaries(nodes: tuple[object, ...], renamed: dict[str, str]) -> None:
        renamed_slots: dict[int, IRCleanupSlot] = {}
        for node in nodes:
            if isinstance(node, (IRVar, IRVarDecl)) and node.name in renamed:
                node.name = renamed[node.name]
            slot = getattr(node, "cleanup_slot", None)
            if isinstance(slot, IRCleanupSlot) and slot.name in renamed:
                # A declaration and its registration share one slot record.
                if id(slot) not in renamed_slots:
                    renamed_slots[id(slot)] = replace(slot, name=renamed[slot.name])
                node.cleanup_slot = renamed_slots[id(slot)]
            for root_field in ("storage_root", "array_storage_root"):
                root = getattr(node, root_field, None)
                if isinstance(root, str) and root in renamed:
                    setattr(node, root_field, renamed[root])

    def _order_prototypes(self) -> None:
        """Order prototypes independently of the lowering phase that declared them.

        Prototypes with no definition in this module keep their relative order
        and come first; the rest follow their definitions' order. btrcc's
        optimizer applies the same rule, so both compilers emit one prototype
        block for one set of definitions.
        """
        positions = {function.name: index for index, function in enumerate(self._module.function_defs)}
        external = [declaration for declaration in self._module.function_decls if declaration.name not in positions]
        defined = sorted(
            (declaration for declaration in self._module.function_decls if declaration.name in positions),
            key=lambda declaration: positions[declaration.name],
        )
        self._module.function_decls = [*external, *defined]

    def _normalize_unused_parameters(self) -> None:
        for function in self._module.function_defs:
            if function.body is None or not function.params:
                continue
            nodes = tuple(IRNode.walk_value(function.body))
            references = {node.name for node in nodes if isinstance(node, IRVar)}
            declarations = {node.name for node in nodes if isinstance(node, IRVarDecl)}
            existing_discards = {
                statement.expr.name
                for statement in function.body.stmts
                if isinstance(statement, IRExprStmt) and isinstance(statement.expr, IRVar)
            }
            unused = [
                parameter.name
                for parameter in function.params
                if parameter.name not in existing_discards
                and (parameter.name not in references or parameter.name in declarations)
            ]
            function.body.stmts[0:0] = [IRExprStmt(expr=IRVar(name=name)) for name in unused]

    @classmethod
    def materialize_runtime_dependencies(
        cls,
        module: IRModule,
        runtime: FreestandingRuntime | None = None,
    ) -> None:
        """Refresh only the derived native-runtime seam for ``module``."""

        cls(module, dce=False, freestanding_runtime=runtime).refresh_runtime_dependencies()

    def refresh_runtime_dependencies(self) -> None:
        self._remove_generated_preprocessor()
        self._lower_freestanding_system_includes()
        self._module.needs_runtime = bool(
            self._module.runtime_roots or self._module.helper_decls or self._has_structured_runtime_use()
        )
        if not self._module.freestanding:
            self._refresh_hosted_runtime_headers()
            return
        generated_features: list[IRMacroDef] = []
        required_headers = {header for helper in self._module.helper_decls for header in helper.required_headers}
        required_features = self._structured_runtime_features()
        for header in required_headers:
            feature = self._freestanding_runtime.feature_for_header(header)
            if feature is not None:
                required_features.add(feature)
        for feature in sorted(required_features):
            if not any(
                isinstance(declaration, IRMacroDef) and declaration.name == feature
                for declaration in self._module.preprocessor_decls
            ):
                generated_features.append(IRMacroDef(name=feature, replacement="1"))
        has_runtime_seam = any(
            isinstance(declaration, IRInclude) and not declaration.is_system and declaration.header == "btrc_rt.h"
            for declaration in self._module.preprocessor_decls
        )
        generated: list[IRInclude | IRMacroDef] = list(generated_features)
        if has_runtime_seam:
            seam_index = next(
                index
                for index, declaration in enumerate(self._module.preprocessor_decls)
                if isinstance(declaration, IRInclude)
                and not declaration.is_system
                and declaration.header == "btrc_rt.h"
            )
            self._module.preprocessor_decls[seam_index:seam_index] = generated_features
        elif self._module.needs_runtime:
            seam = IRInclude(header="btrc_rt.h", is_system=False)
            generated.append(seam)
            self._module.preprocessor_decls.extend(generated)
        self._module.record_generated_runtime_preprocessor(generated)

    def _refresh_hosted_runtime_headers(self) -> None:
        """Rematerialize native headers from the surviving typed dependencies."""
        required_headers = {header for helper in self._module.helper_decls for header in helper.required_headers}
        required_headers.update(self._structured_runtime_headers())
        generated: list[IRInclude] = []
        for header in sorted(required_headers):
            declaration = IRInclude(header=header)
            if declaration in self._module.preprocessor_decls:
                continue
            self._module.preprocessor_decls.append(declaration)
            generated.append(declaration)
        self._module.record_generated_runtime_preprocessor(generated)

    def _structured_runtime_headers(self) -> set[str]:
        """Return hosted headers required directly by live structured IR."""
        headers = set()
        if _GPU_RUNTIME_FEATURE in self._structured_runtime_features():
            headers.add(_GPU_RUNTIME_HEADER)
        if any(isinstance(node, IRCall) and node.callee == "setjmp" for node in IRNode.walk_value(self._module)):
            headers.add(_SETJMP_RUNTIME_HEADER)
        if any(
            (isinstance(node, CType) and ("_Atomic(" in node.text or node.text == "memory_order"))
            or (isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee.startswith("atomic_"))
            or (isinstance(node, IRVar) and node.name.startswith(("memory_order_", "ATOMIC_")))
            for node in IRNode.walk_value(self._module)
        ):
            headers.add("stdatomic.h")
        return headers

    def _remove_generated_preprocessor(self) -> tuple[IRInclude | IRMacroDef, ...]:
        generated = self._module.take_generated_runtime_preprocessor()
        if not generated:
            return ()
        generated_ids = {id(declaration) for declaration in generated}
        self._module.preprocessor_decls = [
            declaration for declaration in self._module.preprocessor_decls if id(declaration) not in generated_ids
        ]
        return generated

    def _lower_freestanding_system_includes(self) -> None:
        if not self._module.needs_freestanding_system_include_lowering():
            return
        lowered = []
        emitted_seam = False
        for declaration in self._module.preprocessor_decls:
            if not isinstance(declaration, IRInclude) or not declaration.is_system:
                lowered.append(declaration)
            elif not emitted_seam:
                lowered.append(IRInclude(header="btrc_rt.h", is_system=False))
                emitted_seam = True
        self._module.preprocessor_decls = lowered
        self._module.mark_freestanding_system_includes_lowered()

    def _has_structured_runtime_use(self) -> bool:
        defined_functions = {function.name for function in self._module.function_defs}
        defined_globals = {declaration.name for declaration in self._module.global_decls}
        for node in IRNode.walk_value(self._module):
            if isinstance(node, IRCall) and isinstance(node.callee, str):
                if node.callee not in defined_functions and self._freestanding_runtime.recognizes_call(node.callee):
                    return True
            elif isinstance(node, CType):
                if any(
                    self._freestanding_runtime.recognizes_type(identifier)
                    for identifier in self._C_IDENTIFIER.findall(node.text)
                ):
                    return True
            elif isinstance(node, IRLiteral):
                if self._freestanding_runtime.recognizes_literal(node.text):
                    return True
            elif isinstance(node, IRVar):
                if node.name not in defined_globals and self._freestanding_runtime.recognizes_object(node.name):
                    return True
        return False

    def _structured_runtime_features(self) -> set[str]:
        # Typed imports carry their own header/link dependencies. Their spelling
        # must not opt into an unrelated legacy runtime header family.
        provided_functions = {
            function.name for function in self._module.function_defs
        } | self._module.native_external_names
        features: set[str] = set()
        for node in IRNode.walk_value(self._module):
            if not isinstance(node, IRCall) or not isinstance(node.callee, str) or node.callee in provided_functions:
                continue
            feature = self._freestanding_runtime.feature_for_call(node.callee)
            if feature is not None:
                features.add(feature)
        return features

    @classmethod
    def install_function_cycle_boundary(
        cls,
        function: IRFunctionDef,
        *,
        force: bool = False,
    ) -> bool:
        """Install a deterministic cycle drain on one observable function boundary."""

        body = function.body
        has_release = cls._contains_cyclable_release(body)
        if body is None or (not force and not has_release):
            return False
        state = {
            "counter": 0,
            "local_names": {parameter.name for parameter in function.params},
        }
        state["local_names"].update(node.name for node in IRNode.walk_value(body) if isinstance(node, IRVarDecl))
        cls._rewrite_cycle_block(function, body, state)
        if IRStatementSequence(body.stmts).may_fall_through() and not cls._ends_with_cycle_flush(body.stmts):
            body.stmts.append(cls._cycle_flush_statement())
        return True

    @classmethod
    def _rewrite_cycle_block(cls, function: IRFunctionDef, block: IRBlock, state: dict) -> None:
        rewritten = []
        for statement in block.stmts:
            cls._rewrite_cycle_nested(function, statement, state)
            if isinstance(statement, IRReturn):
                materialized = cls._is_materialized_flush_return(rewritten, statement)
                if statement.value is not None and not materialized:
                    result = cls._next_cycle_return_name(state)
                    rewritten.append(
                        IRVarDecl(
                            c_type=function.return_type,
                            name=result,
                            init=statement.value,
                            is_cycle_return_temp=True,
                        )
                    )
                    statement.value = IRVar(name=result)
                if not cls._ends_with_cycle_flush(rewritten):
                    rewritten.append(cls._cycle_flush_statement())
            rewritten.append(statement)
        block.stmts = rewritten

    @classmethod
    def _rewrite_cycle_nested(cls, function: IRFunctionDef, statement, state: dict) -> None:
        if isinstance(statement, IRBlock):
            cls._rewrite_cycle_block(function, statement, state)
        elif isinstance(statement, IRIf):
            cls._rewrite_cycle_block(function, statement.then_block, state)
            if statement.else_block is not None:
                cls._rewrite_cycle_block(function, statement.else_block, state)
        elif isinstance(statement, (IRWhile, IRDoWhile, IRFor)):
            cls._rewrite_cycle_block(function, statement.body, state)
        elif isinstance(statement, IRSwitch):
            for case in statement.cases:
                block = IRBlock(stmts=case.body)
                cls._rewrite_cycle_block(function, block, state)
                case.body = block.stmts

    @staticmethod
    def _next_cycle_return_name(state: dict) -> str:
        while True:
            state["counter"] += 1
            name = f"__btrc_cycle_return_{state['counter']}"
            if name not in state["local_names"]:
                state["local_names"].add(name)
                return name

    @staticmethod
    def _contains_cyclable_release(value: object) -> bool:
        return any(
            isinstance(node, IRCall)
            and (
                node.helper_ref in _CYCLABLE_RELEASE_HELPERS
                or (isinstance(node.callee, str) and node.callee in _CYCLABLE_RELEASE_HELPERS)
            )
            for node in IRNode.walk_value(value)
        )

    @classmethod
    def _is_materialized_flush_return(cls, statements, statement: IRReturn) -> bool:
        if len(statements) < 2 or not cls._ends_with_cycle_flush(statements):
            return False
        declaration = statements[-2]
        return bool(
            isinstance(declaration, IRVarDecl)
            and declaration.is_cycle_return_temp
            and isinstance(statement.value, IRVar)
            and declaration.name == statement.value.name
        )

    @staticmethod
    def _cycle_flush_statement() -> IRExprStmt:
        return IRExprStmt(
            expr=IRCall(
                callee="__btrc_flush_cycles",
                helper_ref="__btrc_flush_cycles",
                args=[],
            )
        )

    @staticmethod
    def _ends_with_cycle_flush(statements) -> bool:
        if not statements:
            return False
        statement = statements[-1]
        return bool(
            isinstance(statement, IRExprStmt)
            and isinstance(statement.expr, IRCall)
            and (statement.expr.helper_ref == "__btrc_flush_cycles" or statement.expr.callee == "__btrc_flush_cycles")
        )

    @classmethod
    def releases_cyclable_values(cls, module: IRModule) -> bool:
        """Whether any function of `module` may release a cyclable value."""
        return any(cls._contains_cyclable_release(function.body) for function in module.function_defs)

    def _install_program_cycle_boundary(self) -> bool:
        releases = self._program_cyclable_release
        if releases is None:
            releases = self.releases_cyclable_values(self._module)
        if not releases:
            return False
        installed = False
        for function in self._module.function_defs:
            if function.name in _PROGRAM_ENTRIES:
                installed = self.install_function_cycle_boundary(function, force=True) or installed
        return installed

    def _rematerialize_runtime_helpers(self) -> None:
        """Close catalog helpers over every structured live reference."""

        known_names = {definition.name for definition in self._runtime_catalog.definitions}
        roots = {helper.name for helper in self._module.helper_decls if helper.name in known_names}
        roots.update(self._module.runtime_roots & known_names)
        for root in (*self._module.function_defs, *self._module.global_decls, *self._module.objective_c_classes):
            self._collect_helper_references(root, known_names, roots)
        self._collect_runtime_provider_references(self._module, roots)
        self._scan_macro_replacements(
            self._identifier_pattern(known_names),
            self._module.preprocessor_decls,
            roots,
        )

        existing = {helper.name: helper for helper in self._module.helper_decls}
        materialized = [
            existing[definition.name] if definition.name in existing else IRHelperDecl.from_runtime(definition)
            for definition in self._runtime_catalog.definitions_for(roots)
        ]
        materialized_names = {helper.name for helper in materialized}
        self._module.helper_decls = [
            *materialized,
            *(helper for helper in self._module.helper_decls if helper.name not in materialized_names),
        ]


__all__ = ("PUBLIC_COLLECTION_BASES", "IROptimizer")
