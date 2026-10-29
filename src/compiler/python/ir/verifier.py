"""Complete invariant verification for one structured IR translation unit."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from typing import ClassVar

from .nodes import (
    CType,
    GpuDispatchNames,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRCompoundLiteral,
    IRCxxDelete,
    IRCxxExceptionBoundary,
    IRCxxNew,
    IRDeref,
    IRDesignation,
    IRDoWhile,
    IREnumDef,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionPointerTypedef,
    IRFunctionRef,
    IRGlobalDecl,
    IRGpuKernel,
    IRHelperDecl,
    IRIf,
    IRInclude,
    IRIndex,
    IRInitializerList,
    IRLiteral,
    IRMacroDef,
    IRMacroUndef,
    IRModule,
    IRNode,
    IRObjectiveCAutoreleasePool,
    IRObjectiveCBlock,
    IRObjectiveCClass,
    IRObjectiveCExceptionBoundary,
    IRObjectiveCMessage,
    IRObjectiveCMethod,
    IRObjectiveCSelector,
    IRParam,
    IRReturn,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRTaggedUnionDef,
    IRTypedefDef,
    IRVar,
    IRVarDecl,
    IRWhile,
)


@dataclass(frozen=True)
class JavaFrameState:
    """Rule 2 flow facts at one point of a JNI adapter.

    `pushed` holds while the adapter's local frame is pushed; `registered`
    names cleanup-registered slots; `pending` names owners created inside the
    frame that no cleanup slot protects yet.
    """

    pushed: bool = False
    registered: frozenset[str] = frozenset()
    pending: frozenset[str] = frozenset()


class IRVerifier:
    """Validate translation-unit schema and typed cleanup metadata."""

    # JNI calls that never leave an exception pending (native-interop-ownership.md
    # section 2.3, F1), beside every Release* slot.
    _JNI_NON_THROWING: ClassVar[frozenset[str]] = frozenset(
        {
            "ExceptionCheck",
            "ExceptionClear",
            "ExceptionOccurred",
            "ExceptionDescribe",
            "DeleteLocalRef",
            "DeleteGlobalRef",
            "DeleteWeakGlobalRef",
            "PopLocalFrame",
        }
    )
    # Critical regions, which no adapter enters: arrays copy through
    # Get/Set<X>ArrayRegion or borrow through Get<X>ArrayElements (section 2.3, "Arrays").
    _JNI_CRITICAL: ClassVar[frozenset[str]] = frozenset(
        {"GetPrimitiveArrayCritical", "ReleasePrimitiveArrayCritical", "GetStringCritical", "ReleaseStringCritical"}
    )
    # Library.Java helpers that leave a Java exception pending, checked like a JNI call.
    _JNI_HELPERS: ClassVar[frozenset[str]] = frozenset(
        {
            "btrcJavaClass",
            "btrcJavaMethod",
            "btrcJavaField",
            "btrcJavaNewString",
            "btrcJavaCopyString",
            "btrcJavaRegisterNatives",
        }
    )

    _REGISTER_ARITY: ClassVar[dict[str, int]] = {
        "__btrc_register_cleanup": 4,
        "__btrc_register_direct_cleanup": 3,
    }
    # C types strict C11 accepts for a bit-field under -pedantic-errors (C2/r12).
    _BIT_FIELD_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"_Bool", "bool", "int", "signed", "signed int", "unsigned", "unsigned int"}
    )

    def __init__(self, module: IRModule) -> None:
        self.module = module
        self._functions: dict[str, IRFunctionDef] = {}
        self._attached_cleanup_sites: dict[int, str] = {}
        # Module units: a unit proof collects the calls it cannot resolve.
        self._pending: list[tuple[str, str, tuple[str, ...]]] | None = None
        self._pending_start = ""

    @classmethod
    def prove_realtime_within(
        cls, unit: IRModule, names: Sequence[str], paths: Sequence[tuple[str, ...]]
    ) -> list[tuple[str, str, tuple[str, ...]]]:
        """Prove `names` through `unit`'s own definitions, each after its caller path.

        A call the unit neither defines nor knows to be a safe external is
        returned as (start, callee, path) for the program to resolve; every
        other rule is checked exactly as a whole-module proof checks it.
        """
        verifier = cls(unit)
        verifier._functions = {function.name: function for function in unit.function_defs}
        verifier._pending = []
        for name, path in zip(names, paths, strict=True):
            function = verifier._functions.get(name)
            if function is not None:
                verifier._pending_start = name
                verifier._validate_realtime_function(function, tuple(path), frozenset())
        return verifier._pending

    def validate(self) -> None:
        """Reject every malformed translation-unit invariant owned here."""

        self.validate_schema()
        self._functions = {function.name: function for function in self.module.function_defs}
        self._validate_register_storage()
        self._validate_cleanup_slots()
        self.validate_java_adapters()
        self.validate_type_declarations()
        for unit in self.module.native_units.values():
            IRVerifier(unit).validate()

    def _validate_register_storage(self) -> None:
        if not self._has_register_storage:
            return
        for function in self.module.function_defs:
            if any(parameter.is_register for parameter in function.params) or any(
                isinstance(node, (IRVarDecl, IRParam)) and node.is_register for node in IRNode.walk_value(function.body)
            ):
                bindings = {parameter.name: parameter.is_register for parameter in function.params}
                self._validate_register_value(function.body, bindings)

    def _validate_register_value(self, value, bindings: dict[str, bool]) -> None:
        if isinstance(value, (list, tuple)):
            for child in value:
                self._validate_register_value(child, bindings)
            return
        if not isinstance(value, IRNode):
            return
        if isinstance(value, (IRBlock, IRFor, IRObjectiveCBlock)):
            bindings = bindings.copy()
        if isinstance(value, IRParam):
            bindings[value.name] = value.is_register
        if isinstance(value, IRVarDecl):
            bindings[value.name] = value.is_register
            if value.is_register and (
                value.is_static
                or value.is_extern
                or value.array_size is not None
                or value.is_unsized_array
                or value.cleanup_slot is not None
            ):
                raise ValueError(f"register object '{value.name}' has incompatible storage or cleanup metadata")
        if isinstance(value, IRAddressOf):
            root = value.expr
            while isinstance(root, IRFieldAccess) and not root.arrow:
                root = root.obj
            if isinstance(root, IRVar) and bindings.get(root.name, False):
                raise ValueError(f"Cannot take the address of register object '{root.name}'")
        for node_field in fields(value):
            if node_field.metadata.get("ir_traverse", True):
                self._validate_register_value(getattr(value, node_field.name), bindings)

    def validate_java_adapters(self) -> None:
        """Rule 2: every generated JNI adapter checks, frames and protects as section 2.3 requires.

        A JNI adapter declares the thread's environment from btrcJavaEnvironment
        (in a natives thunk, the one Java called it with, which the thunk
        installed). In one, every throwing env call (and every Library.Java
        helper that can leave an exception pending) is immediately followed by
        its ExceptionCheck branch; every path a successful PushLocalFrame
        dominates passes PopLocalFrame, or the translation that pops; an owner
        created inside the frame is registered in a cleanup slot before the
        next throwing call; and no adapter enters a critical region.
        """
        for function in self.module.function_defs:
            environment = next(
                (
                    node.name
                    for node in IRNode.walk_value(function.body)
                    if isinstance(node, IRVarDecl)
                    and isinstance(node.init, IRCall)
                    and node.init.callee == "btrcJavaEnvironment"
                ),
                None,
            )
            if environment is None:
                continue
            state = self._java_block(function.name, environment, function.body.stmts, JavaFrameState())
            if state is not None and state.pushed:
                raise ValueError(f"Java adapter {function.name} returns with its local frame pushed")

    @staticmethod
    def _java_slot(node: object, environment: str) -> str | None:
        """The JNI function-table slot `node` calls through the adapter's environment."""
        if (
            isinstance(node, IRCall)
            and isinstance(node.callee, IRFieldAccess)
            and node.callee.arrow
            and isinstance(node.callee.obj, IRDeref)
            and isinstance(node.callee.obj.expr, IRVar)
            and node.callee.obj.expr.name == environment
        ):
            return node.callee.field
        return None

    def _java_throwing(self, node: object, environment: str) -> str | None:
        slot = self._java_slot(node, environment)
        if slot is not None:
            throwing = (
                slot not in self._JNI_NON_THROWING and slot != "PushLocalFrame" and not slot.startswith("Release")
            )
            return slot if throwing else None
        if isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee in self._JNI_HELPERS:
            return node.callee
        return None

    @staticmethod
    def _java_expressions(statement: object) -> list[object]:
        if isinstance(statement, IRVarDecl):
            return [statement.init, statement.array_size]
        if isinstance(statement, IRAssign):
            return [statement.target, statement.value]
        if isinstance(statement, (IRExprStmt, IRReturn)):
            return [statement.expr if isinstance(statement, IRExprStmt) else statement.value]
        if isinstance(statement, IRIf):
            return [statement.condition]
        return []

    def _java_exception_check(self, statement: object, environment: str) -> bool:
        return (
            isinstance(statement, IRIf)
            and self._java_slot(statement.condition, environment) == "ExceptionCheck"
            and statement.else_block is None
        )

    def _java_block(self, name, environment, statements, state):
        """Walk one statement list; the state where it falls through, or None when it never does."""
        for index, statement in enumerate(statements):
            nodes = [node for value in self._java_expressions(statement) for node in IRNode.walk_value(value)]
            throwing = [slot for node in nodes if (slot := self._java_throwing(node, environment))]
            slots = [slot for node in nodes if (slot := self._java_slot(node, environment))]
            critical = next((slot for slot in slots if slot in self._JNI_CRITICAL), None)
            if critical is not None:
                raise ValueError(
                    f"Java adapter {name}: {critical} is rejected; a critical region forbids the adapter's other JNI calls"
                )
            if len(throwing) > 1:
                raise ValueError(f"Java adapter {name}: {throwing[0]} and {throwing[1]} share one statement")
            if throwing:
                if not state.pushed:
                    raise ValueError(f"Java adapter {name}: {throwing[0]} runs outside its local frame")
                if state.pending:
                    raise ValueError(
                        f"Java adapter {name}: owner {sorted(state.pending)[0]} is not registered before {throwing[0]}"
                    )
                following = statements[index + 1] if index + 1 < len(statements) else None
                if not self._java_exception_check(following, environment):
                    raise ValueError(f"Java adapter {name}: {throwing[0]} is not followed by its ExceptionCheck branch")
            if "PushLocalFrame" in slots:
                condition = statement.condition if isinstance(statement, IRIf) else None
                if (
                    not isinstance(condition, IRBinOp)
                    or condition.op != "!="
                    or self._java_slot(condition.left, environment) != "PushLocalFrame"
                    or statement.else_block is not None
                ):
                    raise ValueError(f"Java adapter {name}: PushLocalFrame must be checked by its failure branch")
                if state.pushed:
                    raise ValueError(f"Java adapter {name}: PushLocalFrame runs inside a pushed frame")
                if self._java_block(name, environment, statement.then_block.stmts, state) is not None:
                    raise ValueError(f"Java adapter {name}: a failed PushLocalFrame continues")
                state = replace(state, pushed=True)
                continue
            for node in nodes:
                if not isinstance(node, IRCall) or not isinstance(node.callee, str):
                    if self._java_slot(node, environment) == "PopLocalFrame":
                        if not state.pushed:
                            raise ValueError(f"Java adapter {name}: PopLocalFrame pops a frame it did not push")
                        state = replace(state, pushed=False)
                    continue
                if node.callee in self._REGISTER_ARITY and node.cleanup_slot is not None:
                    slot_name = node.cleanup_slot.name
                    state = replace(
                        state, registered=state.registered | {slot_name}, pending=state.pending - {slot_name}
                    )
                if node.callee == "btrcJavaTakeException":
                    popping = len(node.args) > 1 and isinstance(node.args[1], IRLiteral) and node.args[1].text != "0"
                    if popping != state.pushed:
                        raise ValueError(
                            f"Java adapter {name}: an exception translation "
                            + ("pops a frame it did not push" if popping else "keeps its frame pushed")
                        )
                    state = replace(state, pushed=False)
            created = (
                statement.name
                if isinstance(statement, IRVarDecl)
                else statement.target.name
                if isinstance(statement, IRAssign) and isinstance(statement.target, IRVar)
                else None
            )
            value = (
                statement.init
                if isinstance(statement, IRVarDecl)
                else statement.value
                if isinstance(statement, IRAssign)
                else None
            )
            if (
                created is not None
                and state.pushed
                and isinstance(value, IRCall)
                and isinstance(value.callee, str)
                and value.callee.startswith("__btrc_unique_")
                and value.callee.endswith("_new")
                and created not in state.registered
            ):
                state = replace(state, pending=state.pending | {created})
            if isinstance(statement, IRReturn):
                if state.pushed:
                    raise ValueError(f"Java adapter {name} returns with its local frame pushed")
                return None
            if (
                isinstance(statement, IRExprStmt)
                and isinstance(statement.expr, IRCall)
                and statement.expr.never_returns
            ):
                if statement.expr.callee == "__btrc_throw" and state.pushed:
                    raise ValueError(f"Java adapter {name} throws with its local frame pushed")
                return None
            if isinstance(statement, IRBlock):
                state = self._java_block(name, environment, statement.stmts, state)
                if state is None:
                    return None
            elif isinstance(statement, IRIf):
                then_state = self._java_block(name, environment, statement.then_block.stmts, state)
                else_state = (
                    state
                    if statement.else_block is None
                    else self._java_block(name, environment, statement.else_block.stmts, state)
                )
                if then_state is None or else_state is None:
                    state = then_state or else_state
                    if state is None:
                        return None
                elif then_state.pushed != else_state.pushed:
                    raise ValueError(f"Java adapter {name}: branches leave its local frame in different states")
                else:
                    state = JavaFrameState(
                        then_state.pushed,
                        then_state.registered & else_state.registered,
                        then_state.pending | else_state.pending,
                    )
            elif not isinstance(statement, (IRVarDecl, IRAssign, IRExprStmt)):
                raise ValueError(f"Java adapter {name}: unsupported {type(statement).__name__} in a JNI adapter")
        return state

    def validate_schema(self) -> None:
        """Reject raw strings and values in the wrong declaration category."""

        self._has_register_storage = False
        if self.module.language not in ("c", "objective-c", "c++"):
            raise ValueError("unsupported IR translation-unit language")
        if not isinstance(self.module.native_units, dict):
            raise TypeError("IRModule.native_units requires named translation units")
        for name, unit in self.module.native_units.items():
            if (
                not isinstance(name, str)
                or not name.isascii()
                or not name.isidentifier()
                or not isinstance(unit, IRModule)
            ):
                raise TypeError("native adapter requires an identifier and IRModule")
            if unit.language not in ("objective-c", "c++") or unit.native_units:
                raise ValueError("native adapter must be a standalone Objective-C or C++ unit")
            IRVerifier(unit).validate_schema()
        designations: list[IRDesignation] = []
        designation_slots: set[int] = set()
        for node in self.module.walk():
            if isinstance(node, (IRVarDecl, IRParam)) and node.is_register:
                self._has_register_storage = True
            if isinstance(node, (IRAddressOf, IRDesignation, IRInitializerList, IRCompoundLiteral)):
                self._validate_initializer_or_address(node, designations, designation_slots)
            if isinstance(node, (IRFunctionDecl, IRFunctionDef)) and node.c_linkage:
                if self.module.language != "c++" or node.is_static:
                    raise ValueError("C language linkage requires a nonstatic C++ adapter function")
            if isinstance(node, (IRCxxNew, IRCxxDelete, IRCxxExceptionBoundary)):
                if self.module.language != "c++":
                    raise ValueError("C++ IR requires a C++ adapter unit")
                if isinstance(node, IRCxxNew) and (
                    not isinstance(node.value_type, CType)
                    or not isinstance(node.args, list)
                    or any(not isinstance(argument, IRExpr) for argument in node.args)
                ):
                    raise TypeError("C++ construction requires structured arguments")
                if isinstance(node, IRCxxDelete) and not isinstance(node.value, IRExpr):
                    raise TypeError("C++ deletion requires a structured value")
                if isinstance(node, IRCxxExceptionBoundary) and (
                    not isinstance(node.body, IRBlock)
                    or not isinstance(node.failure, IRBlock)
                    or (node.allocation_failure is not None and not isinstance(node.allocation_failure, IRBlock))
                ):
                    raise TypeError("C++ exception boundary requires structured body and failure blocks")
            if isinstance(node, IRCast) and node.bridge:
                if self.module.language != "objective-c" or node.bridge not in ("borrow", "retain", "transfer"):
                    raise ValueError("Objective-C bridge requires an Objective-C adapter unit and valid ownership")
            if isinstance(
                node,
                (
                    IRObjectiveCMessage,
                    IRObjectiveCSelector,
                    IRObjectiveCBlock,
                    IRObjectiveCClass,
                    IRObjectiveCMethod,
                    IRObjectiveCAutoreleasePool,
                    IRObjectiveCExceptionBoundary,
                ),
            ):
                if self.module.language != "objective-c":
                    raise ValueError("Objective-C IR requires an Objective-C adapter unit")
                if isinstance(
                    node,
                    (
                        IRObjectiveCMessage,
                        IRObjectiveCSelector,
                        IRObjectiveCBlock,
                        IRObjectiveCClass,
                        IRObjectiveCMethod,
                    ),
                ):
                    node.validate()
                elif not isinstance(node.body, IRBlock):
                    raise TypeError("Objective-C scope requires an IRBlock")
                if isinstance(node, IRObjectiveCExceptionBoundary) and not isinstance(node.failure, IRBlock):
                    raise TypeError("Objective-C exception boundary requires an IRBlock failure path")

        if any(id(designation) not in designation_slots for designation in designations):
            raise ValueError(
                "IRDesignation is legal only as an IRInitializerList element or a positional IRCompoundLiteral value"
            )

        for field_name in ("freestanding", "needs_runtime", "debug"):
            if not isinstance(getattr(self.module, field_name), bool):
                raise TypeError(f"IRModule.{field_name} requires bool")

        if not isinstance(self.module.runtime_roots, set) or any(
            not isinstance(root, str) or not root for root in self.module.runtime_roots
        ):
            raise TypeError("IRModule.runtime_roots requires a set of non-empty strings")
        if not isinstance(self.module.realtime_safe_externals, set) or any(
            not isinstance(name, str) or not name for name in self.module.realtime_safe_externals
        ):
            raise TypeError("IRModule.realtime_safe_externals requires a set of non-empty strings")
        if not isinstance(self.module.realtime_intrinsic_targets, dict) or any(
            not isinstance(callee, str) or not callee or not isinstance(provenance, str) or not provenance
            for callee, provenance in self.module.realtime_intrinsic_targets.items()
        ):
            raise TypeError("IRModule.realtime_intrinsic_targets requires non-empty string mappings")

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
            ("objective_c_classes", IRObjectiveCClass),
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

        self._validate_record_shapes()

        classes = {declaration.name for declaration in self.module.objective_c_classes}
        if len(classes) != len(self.module.objective_c_classes):
            raise ValueError("Objective-C class declarations require distinct names")
        defined = set()
        for declaration in self.module.objective_c_classes:
            if declaration.superclass in classes and declaration.superclass not in defined:
                raise ValueError("Objective-C superclass must be declared before its subclass")
            defined.add(declaration.name)

        for function in self.module.function_defs:
            if not isinstance(function.is_realtime, bool):
                raise TypeError("IRFunctionDef.is_realtime requires bool")

        if any(function.is_realtime for function in self.module.function_defs):
            self._functions = {function.name: function for function in self.module.function_defs}
            self._validate_realtime_functions()

        if not isinstance(self.module.preprocessor_decls, list):
            raise TypeError("IRModule.preprocessor_decls requires a list")
        for declaration in self.module.preprocessor_decls:
            if not isinstance(declaration, (IRInclude, IRMacroDef, IRMacroUndef)):
                raise TypeError(
                    "IRModule.preprocessor_decls requires IRInclude, IRMacroDef or IRMacroUndef, "
                    f"got {type(declaration).__name__}"
                )
            if isinstance(declaration, (IRMacroDef, IRMacroUndef)):
                declaration.validate()

    def _validate_initializer_or_address(
        self, node: IRExpr, designations: list[IRDesignation], designation_slots: set[int]
    ) -> None:
        """Check designations, their slots, and that no address reaches a bit-field."""

        if isinstance(node, IRInitializerList):
            designation_slots.update(id(element) for element in node.elements if isinstance(element, IRDesignation))
        elif isinstance(node, IRCompoundLiteral):
            designation_slots.update(
                id(value) for name, value in node.fields if name == "" and isinstance(value, IRDesignation)
            )
        elif isinstance(node, IRDesignation):
            if not isinstance(node.field, str) or (node.field == "") == (node.index is None):
                raise ValueError("IRDesignation requires exactly one of a field name and an index")
            if node.index is not None and not isinstance(node.index, IRLiteral):
                raise TypeError("IRDesignation.index requires a folded IRLiteral")
            if not isinstance(node.value, IRExpr):
                raise TypeError("IRDesignation.value requires an IRExpr")
            designations.append(node)
        elif self._bit_field_root(node.expr):
            raise ValueError("the address of a bit-field cannot be taken")

    @staticmethod
    def _bit_field_root(expr: object) -> bool:
        """Whether an lvalue path reaches a bit-field member."""

        while isinstance(expr, (IRFieldAccess, IRIndex)):
            if isinstance(expr, IRFieldAccess) and expr.bit_field:
                return True
            expr = expr.obj
        return False

    def _validate_record_shapes(self) -> None:
        """Enforce the one IRStructField shape invariant (C2 schema)."""

        for declaration in self.module.struct_forwards:
            if not isinstance(declaration.is_union, bool):
                raise TypeError("IRStructForward.is_union requires bool")
        for struct in self.module.struct_defs:
            if not isinstance(struct.is_union, bool):
                raise TypeError("IRStructDef.is_union requires bool")
            if not struct.name:
                raise ValueError("an untagged record is legal only as an anonymous member")
            self._validate_record(
                struct.fields,
                fam_allowed=not struct.is_union,
                plain=GpuDispatchNames.is_uniforms_record(struct.name),
            )
        for tagged in self.module.tagged_union_defs:
            for variant in tagged.variants:
                for value in variant.fields:
                    self._validate_plain_field(value, "tagged-union payload")
        for declaration in self.module.objective_c_classes:
            for value in declaration.fields:
                self._validate_plain_field(value, "Objective-C")

    def _validate_record(self, fields: list[IRStructField], *, fam_allowed: bool, plain: bool) -> None:
        """One record's members; a flexible array member only in a named struct."""

        named_before = False
        last = len(fields) - 1
        for index, value in enumerate(fields):
            if not isinstance(value, IRStructField):
                raise TypeError("a record's fields require IRStructField")
            if plain:
                self._validate_plain_field(value, "GPU")
            facets = (
                value.array_size is not None,
                value.is_unsized_array,
                value.bit_width is not None,
                value.record_fields is not None,
            )
            if sum(facets) > 1:
                raise ValueError(f"IRStructField '{value.name}' combines array, bit-field or record shapes")
            if value.name == "" and value.bit_width is None and value.record_fields is None:
                raise ValueError("an unnamed IRStructField must be a bit-field or an anonymous member")
            keyword = value.c_type.text if isinstance(value.c_type, CType) else ""
            if (value.record_fields is not None) != (keyword in ("struct", "union")):
                raise ValueError("an IRStructField record requires the C type 'struct' or 'union', and only it")
            if value.record_fields is not None:
                if not isinstance(value.record_fields, list) or not value.record_fields or value.name:
                    raise ValueError("an anonymous member is an unnamed field holding a non-empty record")
                self._validate_record(value.record_fields, fam_allowed=False, plain=plain)
            if value.is_unsized_array is not True and value.is_unsized_array is not False:
                raise TypeError("IRStructField.is_unsized_array requires bool")
            if value.is_unsized_array and (not fam_allowed or index != last or not named_before):
                raise ValueError(
                    "a flexible array member must be the last field of a named struct, after a named field"
                )
            if value.bit_width is not None:
                width = value.bit_width
                if isinstance(width, bool) or not isinstance(width, int) or width < 0:
                    raise TypeError("IRStructField.bit_width requires a non-negative int")
                if width == 0 and value.name:
                    raise ValueError("only an unnamed bit-field may have width 0")
                if keyword.removeprefix("const ") not in self._BIT_FIELD_TYPES:
                    raise ValueError(f"bit-field '{value.name}' requires an int or bool C type, got '{keyword}'")
            named_before = named_before or bool(value.name) or value.record_fields is not None

    @staticmethod
    def _validate_plain_field(value: IRStructField, owner: str) -> None:
        if value.record_fields is not None or value.is_unsized_array or value.bit_width is not None or not value.name:
            raise ValueError(f"{owner} fields cannot be anonymous members, flexible arrays or bit-fields")

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
        bodies = [(function.name, function.body) for function in self.module.function_defs]
        bodies.extend(
            (f"{declaration.name}::{method.selector}", method.body)
            for declaration in self.module.objective_c_classes
            for method in declaration.methods
        )
        for name, body in bodies:
            declarations: dict[int, IRCleanupSlot] = {}
            registrations: list[IRCall] = []
            for node in IRNode.walk_value(body):
                if isinstance(node, IRVarDecl) and node.cleanup_slot is not None:
                    metadata = node.cleanup_slot
                    self._validate_cleanup_declaration(node, metadata)
                    site = id(metadata)
                    if site in self._attached_cleanup_sites:
                        raise ValueError(f"cleanup metadata for {metadata.name!r} is attached more than once")
                    self._attached_cleanup_sites[site] = name
                    declarations[site] = metadata
                if isinstance(node, IRCall):
                    if isinstance(node.callee, str) and node.callee in self._REGISTER_ARITY:
                        registrations.append(node)
                    elif node.cleanup_slot is not None:
                        raise ValueError("cleanup metadata is attached to a non-registration call")
            self._validate_function_registrations(
                name,
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
            if isinstance(node, (IRCxxNew, IRCxxDelete, IRCxxExceptionBoundary)):
                raise ValueError(f"IR realtime backstop rejected C++ lifetime operation via {' -> '.join(path)}")
            if isinstance(node, IRCast) and node.bridge:
                raise ValueError(f"IR realtime backstop rejected Objective-C ownership via {' -> '.join(path)}")
            if isinstance(
                node,
                (IRObjectiveCMessage, IRObjectiveCBlock, IRObjectiveCAutoreleasePool, IRObjectiveCExceptionBoundary),
            ):
                raise ValueError(f"IR realtime backstop rejected Objective-C operation via {' -> '.join(path)}")
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
            if not isinstance(node.realtime_provenance, str):
                raise TypeError("IRCall.realtime_provenance requires str")
            if not isinstance(node.callee, str) or not node.callee:
                if node.realtime_provenance != "typed-realtime-function":
                    raise ValueError(f"IR realtime backstop rejected indirect call via {' -> '.join(path)}")
                continue
            if node.realtime_provenance == "typed-realtime-function":
                raise ValueError(
                    "IR realtime backstop rejected typed-callable provenance on direct call "
                    f"{node.callee!r} via {' -> '.join(path)}"
                )
            if node.realtime_provenance:
                expected = self.module.realtime_intrinsic_targets.get(node.callee)
                if expected != node.realtime_provenance:
                    raise ValueError(
                        "IR realtime backstop rejected invalid intrinsic provenance "
                        f"{node.realtime_provenance!r} for {node.callee!r} via {' -> '.join(path)}"
                    )
            target = self._functions.get(node.callee)
            if target is None:
                if node.callee in self.module.realtime_safe_externals or node.realtime_provenance:
                    continue
                if self._pending is not None:
                    self._pending.append((self._pending_start, node.callee, path))
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
