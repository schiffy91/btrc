"""Deterministic transitive closure for generic class specializations."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from ..ast_nodes import TypeExpr
from ..type_identity import generic_instance_key, type_shape_key


def close_generic_instance_graph(analyzer) -> None:
    """Discover concrete generic types used by instantiated templates.

    Initial semantic analysis records source-level specializations.  This pass
    then walks each concrete class and generic-method instance under its type
    substitution map.  Newly found instances extend the work queue; structural
    keys make recursive/self-referential templates terminate deterministically.
    """
    processed_classes: set[tuple] = set()
    processed_methods: set[tuple] = set()
    saved_class = analyzer.current_class
    saved_method = analyzer.current_method
    analyzer.current_class = None
    analyzer.current_method = None
    try:
        while True:
            class_work = _pending_classes(analyzer, processed_classes)
            method_work = _pending_methods(analyzer, processed_methods)
            if not class_work and not method_work:
                return
            for base, args, key in class_work:
                processed_classes.add(key)
                _scan_class_instance(analyzer, base, args)
            for owner, name, class_args, method_args, key in method_work:
                processed_methods.add(key)
                _scan_method_instance(
                    analyzer,
                    owner,
                    name,
                    class_args,
                    method_args,
                )
    finally:
        analyzer.current_class = saved_class
        analyzer.current_method = saved_method


def _pending_classes(analyzer, processed):
    work = []
    for base, instances in analyzer.generic_instances.items():
        for args in instances:
            key = generic_instance_key(base, args)
            if key not in processed:
                work.append((base, tuple(args), key))
    return work


def _pending_methods(analyzer, processed):
    work = []
    for (owner, name), instances in analyzer.generic_method_instances.items():
        for class_args, method_args in instances:
            key = (
                owner,
                name,
                tuple(type_shape_key(arg) for arg in class_args),
                tuple(type_shape_key(arg) for arg in method_args),
            )
            if key not in processed:
                work.append(
                    (
                        owner,
                        name,
                        tuple(class_args),
                        tuple(method_args),
                        key,
                    )
                )
    return work


def _scan_class_instance(analyzer, base, args) -> None:
    cls = analyzer.class_table.get(base)
    if cls is None or not cls.generic_params:
        return
    substitutions = dict(zip(cls.generic_params, args))
    scanned: set[int] = set()

    # Canonical storage includes inherited fields and backed properties.  Owner
    # maps prevent a child's T from rewriting an inherited declaration whose
    # source class happens to use the same spelling as a concrete type name.
    for _storage_name, member in cls.instance_storage:
        member_subs = _member_substitutions(cls, base, member, substitutions)
        _scan_value(analyzer, member, member_subs, ())
        scanned.add(id(member))
    for name, field in cls.fields.items():
        if id(field) not in scanned:
            owner = cls.field_owners.get(name, base)
            _scan_value(
                analyzer,
                field,
                substitutions if owner == base else {},
                (),
            )
    for name, field in cls.static_fields.items():
        owner = cls.field_owners.get(name, base)
        _scan_value(
            analyzer,
            field,
            substitutions if owner == base else {},
            (),
        )
    for name, prop in cls.properties.items():
        owner = cls.property_owners.get(name, base)
        _scan_value(
            analyzer,
            prop,
            substitutions if owner == base else {},
            (),
        )
    if cls.constructor is not None:
        _scan_value(analyzer, cls.constructor, substitutions, ())
    for name, method in cls.methods.items():
        if method.is_constructor:
            continue
        owner = cls.method_owners.get(name, base)
        _scan_value(
            analyzer,
            method,
            substitutions if owner == base else {},
            tuple(method.generic_params),
        )


def _member_substitutions(cls, base, member, substitutions):
    name = getattr(member, "name", "")
    if name in cls.field_owners:
        owner = cls.field_owners[name]
    else:
        owner = cls.property_owners.get(name, base)
    return substitutions if owner == base else {}


def _scan_method_instance(
    analyzer,
    owner,
    name,
    class_args,
    method_args,
) -> None:
    cls = analyzer.class_table.get(owner)
    if cls is None:
        return
    method = cls.methods.get(name)
    if method is None:
        return
    substitutions = dict(zip(cls.generic_params, class_args))
    substitutions.update(zip(method.generic_params, method_args))
    _scan_value(analyzer, method, substitutions, ())


def _scan_value(analyzer, value, substitutions, unresolved) -> None:
    if value is None:
        return
    if isinstance(value, TypeExpr):
        resolved = analyzer._substitute_type(value, substitutions)
        if resolved is not None and resolved.generic_args:
            analyzer._collect_generic_instances(resolved, unresolved)
        _scan_value(analyzer, value.array_size, substitutions, unresolved)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _scan_value(analyzer, item, substitutions, unresolved)
        return
    if isinstance(value, dict):
        for item in value.values():
            _scan_value(analyzer, item, substitutions, unresolved)
        return
    if not is_dataclass(value):
        return
    inferred = analyzer.node_types.get(id(value))
    if inferred is not None:
        resolved = analyzer._substitute_type(inferred, substitutions)
        if resolved is not None and resolved.generic_args:
            analyzer._collect_generic_instances(resolved, unresolved)
    for field in fields(value):
        _scan_value(
            analyzer,
            getattr(value, field.name),
            substitutions,
            unresolved,
        )


__all__ = ["close_generic_instance_graph"]
