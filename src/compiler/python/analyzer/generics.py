"""Generic inference, validation, and instance closure."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.program import (
    ClassCallableIdentity,
    ClassCallableKind,
    DeclarationIndex,
    GenericClassCallableDependency,
    GenericMethodInstanceDependency,
    GenericTemplateDependency,
)
from src.compiler.python.analyzer.types import TypeShapeError
from src.compiler.python.syntax.ast.generated import AssignExpr, Identifier, LambdaExpr, TypeExpr

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalysisSession
    from src.compiler.python.analyzer.types import TypeSystem

_UNREGISTERED_GENERIC_INSTANCE_BASES = frozenset({"Array", "List", "Map", "Mutex", "Set", "Thread", "Vector"})
_RUNTIME_GENERIC_ARITIES = {"Array": 1, "List": 1, "Map": 2, "Mutex": 1, "Set": 1, "Thread": 1, "Vector": 1}
_RUNTIME_GENERIC_MIN_ARITIES = {"Tuple": 2, "__fn_ptr": 1}


@dataclass(frozen=True)
class GenericMethodInferencePlan:
    arguments: tuple
    bindings: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class GenericSpecializationScanPlan:
    """Cached type and compound-operator facts revisited under substitutions."""

    type_uses: tuple[tuple[TypeExpr, frozenset[str]], ...]
    compound_assignments: tuple[AssignExpr, ...]


class GenericAnalyzer:
    """Generic inference, validation, and instance closure."""

    def __init__(self, session: AnalysisSession, index: DeclarationIndex, types: TypeSystem) -> None:
        self.session = session
        self.index = index
        self.types = types

    def type_of(self, expression):
        """Read a type fact produced by ExpressionAnalyzer."""
        return self.session.node_types.get(id(expression))

    def close_generic_instance_graph(self) -> None:
        """Discover concrete generic types used by instantiated templates.

        Initial semantic analysis records source-level specializations.  This pass
        then walks each concrete class and generic-method instance under its type
        substitution map.  Newly found instances extend the work queue; structural
        keys make recursive/self-referential templates terminate deterministically.
        """
        processed_classes: set[tuple] = set()
        processed_methods: set[tuple] = set()
        scan_plans: dict[int, GenericSpecializationScanPlan] = {}
        saved_class = self.session.current_class
        saved_method = self.session.current_method
        self.session.current_class = None
        self.session.current_method = None
        try:
            while True:
                class_work = self._pending_classes(processed_classes)
                method_work = self._pending_methods(processed_methods)
                if not class_work and (not method_work):
                    self._close_template_dependencies()
                    class_work = self._pending_classes(processed_classes)
                    method_work = self._pending_methods(processed_methods)
                    if not class_work and (not method_work):
                        return
                for base, args, key in class_work:
                    processed_classes.add(key)
                    self._scan_class_instance(base, args, scan_plans)
                for owner, name, class_args, method_args, key in method_work:
                    processed_methods.add(key)
                    self._scan_method_instance(owner, name, class_args, method_args, scan_plans)
        finally:
            self.session.current_class = saved_class
            self.session.current_method = saved_method

    def _pending_classes(self, processed):
        work = []
        for base, instances in self.session.generic_instances.items():
            for args in instances:
                key = self.types.generic_instance_key(base, args)
                if key not in processed:
                    work.append((base, tuple(args), key))
        return work

    def _pending_methods(self, processed):
        work = []
        for (owner, name), instances in self.session.generic_method_instances.items():
            for class_args, method_args in instances:
                key = (
                    owner,
                    name,
                    tuple(self.types.type_shape_key(arg) for arg in class_args),
                    tuple(self.types.type_shape_key(arg) for arg in method_args),
                )
                if key not in processed:
                    work.append((owner, name, tuple(class_args), tuple(method_args), key))
        return work

    def _scan_class_instance(self, base, args, scan_plans) -> None:
        cls = self.index.class_table.get(base)
        if cls is None or not cls.generic_params:
            return
        substitutions = dict(zip(cls.generic_params, args))
        scanned: set[int] = set()
        for _storage_name, member in cls.instance_storage:
            member_subs = self._member_substitutions(cls, base, member, substitutions)
            self._scan_value(member, member_subs, (), scan_plans)
            scanned.add(id(member))
        for name, field in cls.fields.items():
            if id(field) not in scanned:
                owner = cls.field_owners.get(name, base)
                self._scan_value(field, substitutions if owner == base else {}, (), scan_plans)
        for name, field in cls.static_fields.items():
            owner = cls.field_owners.get(name, base)
            self._scan_value(field, substitutions if owner == base else {}, (), scan_plans)
        for name, prop in cls.properties.items():
            owner = cls.property_owners.get(name, base)
            self._scan_value(prop, substitutions if owner == base else {}, (), scan_plans)
        if cls.constructor is not None:
            self._scan_value(cls.constructor, substitutions, (), scan_plans)
        for name, method in cls.methods.items():
            if method.is_constructor:
                continue
            owner = cls.method_owners.get(name, base)
            self._scan_value(method, substitutions if owner == base else {}, tuple(method.generic_params), scan_plans)

    @staticmethod
    def _member_substitutions(cls, base, member, substitutions):
        name = getattr(member, "name", "")
        if name in cls.field_owners:
            owner = cls.field_owners[name]
        else:
            owner = cls.property_owners.get(name, base)
        return substitutions if owner == base else {}

    def _scan_method_instance(self, owner, name, class_args, method_args, scan_plans) -> None:
        cls = self.index.class_table.get(owner)
        if cls is None:
            return
        method = cls.methods.get(name)
        if method is None:
            return
        substitutions = dict(zip(cls.generic_params, class_args))
        substitutions.update(zip(method.generic_params, method_args))
        self._scan_value(method, substitutions, (), scan_plans)

    def record_class_method_use(self, receiver_type: TypeExpr | None, method_name: str) -> None:
        """Record demand for one ordinary method on a generic class instance."""
        self.record_class_callable_use(receiver_type, "method", method_name)

    def record_class_callable_use(
        self,
        receiver_type: TypeExpr | None,
        kind: ClassCallableKind,
        callable_name: str,
    ) -> None:
        """Record one method or property-accessor demand on a generic instance."""
        receiver = self.types.canonical_type(receiver_type)
        cls = self.index.class_table.get(receiver.base) if receiver is not None else None
        if cls is None or not cls.generic_params:
            return
        callable_identity = ClassCallableIdentity(receiver.base, kind, callable_name)
        if kind == "method":
            member = cls.methods.get(callable_name)
            if member is None or member.generic_params:
                return
        elif kind == "get":
            member = cls.properties.get(callable_name)
            if member is None or not member.has_getter:
                return
        elif kind == "set":
            member = cls.properties.get(callable_name)
            if member is None or not member.has_setter:
                return
        else:
            raise ValueError(f"unknown class callable kind: {kind}")
        dependency = GenericClassCallableDependency(receiver, callable_identity)
        bucket = self._active_template_dependency_bucket()
        if bucket is not None:
            self._append_dependency(bucket, dependency)
            return
        self._select_class_callable(receiver, callable_identity)

    def _active_template_dependency_bucket(self) -> list[GenericTemplateDependency] | None:
        """Return the dependency list owned by the active generic template body."""
        current_class = self.session.current_class
        current_method = self.session.current_method
        if current_class is not None and current_method is not None and current_method.generic_params:
            return self.session.generic_method_callable_dependencies.setdefault(
                (current_class.name, current_method.name), []
            )
        if current_class is not None and current_class.generic_params:
            owner_identity = self.session.current_class_callable
            if owner_identity is None:
                return self.session.generic_class_lifecycle_dependencies.setdefault(current_class.name, [])
            return self.session.generic_class_callable_dependencies.setdefault(owner_identity, [])
        return None

    def _close_template_dependencies(self) -> None:
        """Close template bodies over concrete method and class-callable demand."""
        processed_lifecycles: set[tuple] = set()
        processed_methods: set[tuple] = set()
        processed_callables: set[tuple] = set()
        while True:
            pending: list[tuple[tuple[GenericTemplateDependency, ...], dict[str, TypeExpr]]] = []

            for owner, dependencies in tuple(self.session.generic_class_lifecycle_dependencies.items()):
                cls = self.index.class_table.get(owner)
                if cls is None:
                    continue
                for arguments in tuple(self.session.generic_instances.get(owner, ())):
                    key = (owner, tuple(self.types.type_shape_key(argument) for argument in arguments))
                    if key in processed_lifecycles:
                        continue
                    processed_lifecycles.add(key)
                    pending.append((tuple(dependencies), dict(zip(cls.generic_params, arguments))))

            for (instance_owner, method_name), instances in tuple(self.session.generic_method_instances.items()):
                cls = self.index.class_table.get(instance_owner)
                method = cls.methods.get(method_name) if cls is not None else None
                if cls is None or method is None:
                    continue
                definition_owner = cls.method_owners.get(method_name, instance_owner)
                dependencies = tuple(
                    self.session.generic_method_callable_dependencies.get((definition_owner, method_name), ())
                )
                for class_arguments, method_arguments in tuple(instances):
                    key = (
                        instance_owner,
                        method_name,
                        tuple(self.types.type_shape_key(argument) for argument in class_arguments),
                        tuple(self.types.type_shape_key(argument) for argument in method_arguments),
                    )
                    if key in processed_methods:
                        continue
                    processed_methods.add(key)
                    substitutions = dict(zip(cls.generic_params, class_arguments))
                    substitutions.update(zip(method.generic_params, method_arguments))
                    pending.append((dependencies, substitutions))

            for callable_identity, instances in tuple(self.session.generic_class_callable_instances.items()):
                cls = self.index.class_table.get(callable_identity.owner)
                if cls is None:
                    continue
                for arguments in instances:
                    key = (
                        callable_identity,
                        tuple(self.types.type_shape_key(arg) for arg in arguments),
                    )
                    if key in processed_callables:
                        continue
                    processed_callables.add(key)
                    dependencies = tuple(self.session.generic_class_callable_dependencies.get(callable_identity, ()))
                    pending.append((dependencies, dict(zip(cls.generic_params, arguments))))

            if not pending:
                return
            for dependencies, substitutions in pending:
                for dependency in dependencies:
                    self._select_resolved_dependency(dependency, substitutions)

    def _select_resolved_dependency(
        self,
        dependency: GenericTemplateDependency,
        substitutions: dict[str, TypeExpr],
    ) -> None:
        if isinstance(dependency, GenericMethodInstanceDependency):
            class_arguments = tuple(
                self.types.substitute_type(argument, substitutions) if substitutions else argument
                for argument in dependency.class_arguments
            )
            method_arguments = tuple(
                self.types.substitute_type(argument, substitutions) if substitutions else argument
                for argument in dependency.method_arguments
            )
            if any(argument is None for argument in (*class_arguments, *method_arguments)):
                return
            self._select_method_dependency(
                GenericMethodInstanceDependency(
                    owner=dependency.owner,
                    method_name=dependency.method_name,
                    class_arguments=class_arguments,
                    method_arguments=method_arguments,
                    line=dependency.line,
                    col=dependency.col,
                )
            )
            return
        resolved = (
            self.types.substitute_type(dependency.receiver, substitutions) if substitutions else dependency.receiver
        )
        if resolved is None:
            return
        callable_identity = ClassCallableIdentity(
            resolved.base,
            dependency.callable.kind,
            dependency.callable.name,
        )
        self._select_class_callable(resolved, callable_identity)

    def _select_class_callable(
        self,
        receiver: TypeExpr | None,
        callable_identity: ClassCallableIdentity,
    ) -> None:
        receiver = self.types.canonical_type(receiver)
        cls = self.index.class_table.get(receiver.base) if receiver is not None else None
        if (
            receiver is None
            or cls is None
            or not cls.generic_params
            or len(receiver.generic_args) != len(cls.generic_params)
            or callable_identity.owner != receiver.base
        ):
            return
        bucket = self.session.generic_class_callable_instances.setdefault(callable_identity, [])
        target = tuple(self.types.type_shape_key(argument) for argument in receiver.generic_args)
        if any(tuple(self.types.type_shape_key(argument) for argument in existing) == target for existing in bucket):
            return
        bucket.append(tuple(receiver.generic_args))

    def _append_dependency(
        self,
        bucket: list[GenericTemplateDependency],
        dependency: GenericTemplateDependency,
    ) -> None:
        target = self._dependency_key(dependency)
        if any(self._dependency_key(existing) == target for existing in bucket):
            return
        bucket.append(dependency)

    def _dependency_key(self, dependency: GenericTemplateDependency) -> tuple:
        if isinstance(dependency, GenericClassCallableDependency):
            return ("class_callable", self.types.type_shape_key(dependency.receiver), dependency.callable)
        return (
            "generic_method",
            dependency.owner,
            dependency.method_name,
            tuple(self.types.type_shape_key(argument) for argument in dependency.class_arguments),
            tuple(self.types.type_shape_key(argument) for argument in dependency.method_arguments),
        )

    def _scan_value(self, value, substitutions, unresolved, scan_plans) -> None:
        key = id(value)
        plan = scan_plans.get(key)
        if plan is None:
            plan = self._build_scan_plan(value)
            scan_plans[key] = plan
        substitution_names = substitutions.keys()
        for type_expr, referenced_names in plan.type_uses:
            resolved = type_expr
            if substitutions and (not referenced_names.isdisjoint(substitution_names)):
                resolved = self.types.substitute_type(type_expr, substitutions)
            if resolved is not None and resolved.generic_args:
                self.collect_type_instances(resolved, unresolved)
        self._scan_compound_operator_dependencies(plan.compound_assignments, substitutions)

    def _scan_compound_operator_dependencies(self, assignments, substitutions) -> None:
        """Select concrete operator and conversion callables hidden by template types."""
        for assignment in assignments:
            target = self._specialized_node_type(assignment.target, substitutions)
            source = self._specialized_node_type(assignment.value, substitutions)
            if target is None or source is None:
                continue
            resolved = self.types.operator_method(target, assignment.op[:-1])
            if resolved is None:
                continue
            method, method_substitutions = resolved
            self._select_class_callable(
                target,
                ClassCallableIdentity.method(target.base, method.name),
            )
            if not method.params:
                continue
            expected = method.params[0].type
            if method_substitutions:
                expected = self.types.substitute_type(expected, method_substitutions)
            if self.types.requires_string_conversion(expected, source):
                self._select_class_callable(
                    source,
                    ClassCallableIdentity.method(source.base, "toString"),
                )

    def _specialized_node_type(self, node, substitutions):
        type_expr = self.session.node_types.get(id(node))
        if type_expr is None:
            return None
        resolved = self.types.substitute_type(type_expr, substitutions) if substitutions else type_expr
        return self.types.canonical_type(resolved)

    def _build_scan_plan(self, root):
        """Index type-bearing nodes once for every reused template subtree."""
        plan: list[tuple[TypeExpr, frozenset[str]]] = []
        compound_assignments: list[AssignExpr] = []
        seen_values: set[int] = set()
        seen_types: set[int] = set()

        def add_type(type_expr):
            if type_expr is None or id(type_expr) in seen_types:
                return
            seen_types.add(id(type_expr))
            plan.append((type_expr, self._substitution_names(type_expr)))

        def visit(value):
            if value is None:
                return
            if isinstance(value, TypeExpr):
                add_type(value)
                visit(value.array_size)
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)
                return
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
                return
            if not is_dataclass(value) or id(value) in seen_values:
                return
            seen_values.add(id(value))
            if isinstance(value, AssignExpr) and value.op != "=":
                compound_assignments.append(value)
            add_type(self.session.node_types.get(id(value)))
            for field in fields(value):
                visit(getattr(value, field.name))

        visit(root)
        return GenericSpecializationScanPlan(tuple(plan), tuple(compound_assignments))

    @staticmethod
    def _substitution_names(type_expr):
        if not type_expr.generic_args:
            return frozenset((type_expr.base,))
        names: set[str] = set()
        for argument in type_expr.generic_args:
            names.update(GenericAnalyzer._substitution_names(argument))
        return frozenset(names)

    def record_method_instance(self, expr, cls, method, obj_type, plan: GenericMethodInferencePlan):
        """Record or defer the monomorphization target for a generic-method call."""
        class_subs = {}
        if cls.generic_params and obj_type.generic_args:
            class_subs = dict(zip(cls.generic_params, obj_type.generic_args))
        method_subs = self.infer_method_type_args(plan, method, class_subs)
        if method_subs is None:
            return
        method_args = tuple(method_subs[gp] for gp in method.generic_params)
        class_args = tuple(obj_type.generic_args) if obj_type.generic_args else ()
        dependency = GenericMethodInstanceDependency(
            owner=obj_type.base,
            method_name=method.name,
            class_arguments=class_args,
            method_arguments=method_args,
            line=expr.line,
            col=expr.col,
        )
        if not self._validate_method_dependency(dependency):
            return
        self.session.generic_method_call_args[id(expr)] = method_args
        bucket = self._active_template_dependency_bucket()
        if bucket is not None:
            self._append_dependency(bucket, dependency)
            return
        self._select_method_dependency(dependency, already_validated=True)

    def _validate_method_dependency(self, dependency: GenericMethodInstanceDependency) -> bool:
        cls = self.index.class_table.get(dependency.owner)
        method = cls.methods.get(dependency.method_name) if cls is not None else None
        if cls is None or method is None:
            return False
        if len(dependency.class_arguments) != len(cls.generic_params) or len(dependency.method_arguments) != len(
            method.generic_params
        ):
            return False
        owner = f"{dependency.owner}.{dependency.method_name}"
        if not self._validate_generic_arguments(
            owner,
            dependency.method_arguments,
            dependency.line,
            dependency.col,
        ):
            return False
        substitutions = dict(zip(cls.generic_params, dependency.class_arguments))
        substitutions.update(zip(method.generic_params, dependency.method_arguments))
        signature_types = [method.return_type, *(parameter.type for parameter in method.params)]
        return self._validate_substitution_shapes(
            owner,
            signature_types,
            substitutions,
            dependency.line,
            dependency.col,
        )

    def _select_method_dependency(
        self,
        dependency: GenericMethodInstanceDependency,
        *,
        already_validated: bool = False,
    ) -> None:
        if not already_validated and not self._validate_method_dependency(dependency):
            return
        cls = self.index.class_table.get(dependency.owner)
        method = cls.methods.get(dependency.method_name) if cls is not None else None
        if cls is None or method is None:
            return
        key = (dependency.owner, dependency.method_name)
        bucket = self.session.generic_method_instances.setdefault(key, [])
        entry = (dependency.class_arguments, dependency.method_arguments)
        if not self._method_instance_seen(bucket, entry):
            bucket.append(entry)
        substitutions = dict(zip(cls.generic_params, dependency.class_arguments))
        substitutions.update(zip(method.generic_params, dependency.method_arguments))
        for type_expr in [method.return_type, *(parameter.type for parameter in method.params)]:
            resolved = self.types.substitute_type(type_expr, substitutions)
            if resolved and resolved.generic_args:
                self.collect_type_instances(resolved)

    def _method_instance_seen(self, bucket, entry) -> bool:
        class_args, method_args = entry
        target = (
            tuple(self._normalize_type_key(a) for a in class_args),
            tuple(self._normalize_type_key(a) for a in method_args),
        )
        for ex_class, ex_method in bucket:
            existing = (
                tuple(self._normalize_type_key(a) for a in ex_class),
                tuple(self._normalize_type_key(a) for a in ex_method),
            )
            if existing == target:
                return True
        return False

    def infer_method_type_args(self, plan: GenericMethodInferencePlan, method, class_subs):
        """Infer concrete bindings for each method type parameter.

        Returns a dict {param_name: TypeExpr} when every parameter is resolved,
        otherwise None. Inference unifies each method parameter's declared type
        (after class-level substitution) against the corresponding argument's
        inferred type.
        """
        type_params = set(method.generic_params)
        subs: dict[str, TypeExpr] = {}
        for param_index, arg_index in plan.bindings:
            param = method.params[param_index]
            declared = self.types.substitute_type(param.type, class_subs)
            actual = self.argument_type_for_inference(plan.arguments[arg_index])
            if declared is None or actual is None:
                continue
            if not self.unify_type_parameter(declared, actual, type_params, subs):
                return None
        for gp in method.generic_params:
            if gp not in subs:
                return None
        return subs

    def argument_type_for_inference(self, arg) -> TypeExpr | None:
        """Inferred TypeExpr of a call argument, normalized for unification.

        Lambdas infer to ``__fn_ptr<ret, params...>`` already. A bare function
        reference (Identifier naming a top-level function) is reconstructed into
        the same ``__fn_ptr`` shape so it unifies the same way.
        """
        if isinstance(arg, Identifier) and arg.name in self.index.function_table:
            func = self.index.function_table[arg.name]
            return self.types.function_value_type(func)
        if isinstance(arg, LambdaExpr):
            return self.type_of(arg)
        return self.type_of(arg)

    def unify_type_parameter(self, declared, actual, type_params, subs) -> bool:
        """Structurally unify ``declared`` (may mention type params) with ``actual``.

        Records bindings for any name in ``type_params`` into ``subs``. Pointer
        depth and extra structure are ignored beyond what's needed to bind the
        type parameters.
        """
        if declared is None or actual is None:
            return True
        if declared.base in type_params and (not declared.generic_args):
            binding = self._strip_one_pointer(actual, declared)
            if binding is None:
                return False
            existing = subs.get(declared.base)
            if existing is not None:
                return self.types.types_equal(existing, binding)
            subs[declared.base] = binding
            return True
        if declared.generic_args or actual.generic_args:
            if (
                declared.base != actual.base
                or declared.pointer_depth != actual.pointer_depth
                or declared.is_array != actual.is_array
                or (len(declared.generic_args) != len(actual.generic_args))
            ):
                return False
            return all(
                (
                    self.unify_type_parameter(d, a, type_params, subs)
                    for d, a in zip(declared.generic_args, actual.generic_args)
                )
            )
        return True

    def _strip_one_pointer(self, actual, declared) -> TypeExpr | None:
        """Adjust ``actual`` for the pointer depth the declared param adds.

        When the declared parameter is ``U*`` and the actual is ``int*``, the
        bound ``U`` is ``int``. Pointer depths beyond the type-parameter slot are
        subtracted. Plain (non-pointer) parameters bind to ``actual`` as-is.
        """
        binding = actual
        if getattr(declared, "is_array", False):
            if not getattr(binding, "is_array", False):
                return None
            binding = self.types.strip_outer_storage(binding, array=True)
        extra = getattr(declared, "pointer_depth", 0)
        if extra:
            if getattr(binding, "pointer_depth", 0) < extra:
                return None
            for _ in range(extra):
                if binding.pointer_depth <= 0:
                    return None
                binding = self.types.strip_outer_storage(binding)
        return binding

    def _normalize_type_key(self, type_expr: TypeExpr) -> tuple:
        return self.types.type_shape_key(type_expr)

    def _validate_generic_arguments(self, owner, args, line=0, col=0):
        valid = True
        for index, argument in enumerate(args, 1):
            problem = self.types.generic_argument_problem(argument)
            if problem is None:
                continue
            message, bad_type = problem
            self.types.report_type_shape_error(
                f"Generic argument {index} for '{owner}' is invalid: {message}", bad_type, line, col
            )
            valid = False
        return valid

    def _validate_substitution_shapes(self, owner, declared_types, substitutions, line=0, col=0):
        valid = True
        for declared in declared_types:
            if declared is None:
                continue
            try:
                resolved = self.types.substitute_type(declared, substitutions)
            except TypeShapeError as error:
                self.types.report_type_shape_error(
                    f"Generic specialization '{owner}' is invalid: {error}", error.type_expr or declared, line, col
                )
                valid = False
                continue
            if not self._validate_nested_class_arguments(owner, resolved, line, col):
                valid = False
            self.session.generic_resolved_type_facts.append((resolved, line, col))
        return valid

    def _validate_nested_class_arguments(self, owner, type_expr, line=0, col=0):
        if type_expr is None:
            return True
        valid = True
        cls = self.index.class_table.get(type_expr.base)
        if cls is not None and cls.generic_params:
            valid = self._validate_generic_arguments(
                f"{owner} via {type_expr.base}", type_expr.generic_args or [], line, col
            )
        for argument in type_expr.generic_args or []:
            if not self._validate_nested_class_arguments(owner, argument, line, col):
                valid = False
        return valid

    def _validate_generic_specialization(self, type_expr):
        args = type_expr.generic_args or []
        cls = self.index.class_table.get(type_expr.base)
        if cls is None or not cls.generic_params:
            return True
        valid = self._validate_generic_arguments(type_expr.base, args, type_expr.line, type_expr.col)
        if len(args) != len(cls.generic_params):
            return valid
        substitutions = dict(zip(cls.generic_params, args))
        declared_types = [field.type for field in cls.fields.values()]
        declared_types.extend(prop.type for prop in cls.properties.values())
        for method in cls.methods.values():
            declared_types.append(method.return_type)
            declared_types.extend(param.type for param in method.params)
        return (
            self._validate_substitution_shapes(
                type_expr.base, declared_types, substitutions, type_expr.line, type_expr.col
            )
            and valid
        )

    def collect_type_instances(self, type_expr, unresolved_names=()):
        if type_expr is None:
            return
        active = set(unresolved_names)
        if self.session.current_class is not None:
            active.update(self.session.current_class.generic_params)
        if self.session.current_method is not None:
            active.update(self.session.current_method.generic_params)
        base_is_parameter = type_expr.base in active
        self._validate_generic_arity(type_expr, base_is_parameter)
        if type_expr.generic_args:
            self._collect_concrete_specialization(type_expr, active, base_is_parameter)
            for argument in type_expr.generic_args:
                self.collect_type_instances(argument, unresolved_names)

    def _validate_generic_arity(self, type_expr, base_is_parameter):
        if base_is_parameter:
            return
        declaration = self.index.class_table.get(type_expr.base)
        if declaration is None:
            declaration = self.index.interface_table.get(type_expr.base)
        expected = (
            len(declaration.generic_params) if declaration is not None else _RUNTIME_GENERIC_ARITIES.get(type_expr.base)
        )
        actual = len(type_expr.generic_args)
        if expected is not None and actual != expected:
            self.types.report_type_shape_error(
                f"Type '{type_expr.base}' expects {expected} generic argument(s) but got {actual}", type_expr
            )
            return
        minimum = _RUNTIME_GENERIC_MIN_ARITIES.get(type_expr.base)
        if minimum is not None and actual < minimum:
            self.types.report_type_shape_error(
                f"Type '{type_expr.base}' expects at least {minimum} generic argument(s) but got {actual}", type_expr
            )

    def _collect_concrete_specialization(self, type_expr, active, base_is_parameter):
        args = tuple(type_expr.generic_args)
        key = type_expr.base
        cls = self.index.class_table.get(key)
        registered = bool(cls and cls.generic_params and (not base_is_parameter))
        runtime = (
            cls is None and key not in self.index.interface_table and (key in _UNREGISTERED_GENERIC_INSTANCE_BASES)
        )
        unresolved = any(self.types.type_references_names(argument, active) for argument in args)
        instances = self.session.generic_instances.setdefault(key, []) if registered or runtime else []
        normalized = tuple(self._normalize_type_key(argument) for argument in args)
        if registered and (not unresolved) and (cls is not None) and (len(args) == len(cls.generic_params)):
            if any(
                tuple(self._normalize_type_key(argument) for argument in existing) == normalized
                for existing in instances
            ):
                return
        valid = self._validate_generic_specialization(type_expr) if registered else True
        if not ((registered or runtime) and valid and (not unresolved)):
            return
        if cls is not None and len(args) != len(cls.generic_params):
            return
        self.session.generic_resolved_type_facts.append((type_expr, type_expr.line, type_expr.col))
        if not any(
            tuple(self._normalize_type_key(argument) for argument in existing) == normalized for existing in instances
        ):
            instances.append(args)
        if cls and cls.generic_params:
            substitutions = dict(zip(cls.generic_params, type_expr.generic_args))
            for method in cls.methods.values():
                result = method.return_type
                if result and result.generic_args:
                    resolved = self.types.substitute_type(result, substitutions)
                    if resolved and resolved.generic_args and (resolved.base != key):
                        self.collect_type_instances(resolved, method.generic_params)


__all__ = ["GenericAnalyzer", "GenericMethodInferencePlan"]
