"""Shared recognition of proven class-backed index protocols."""

from dataclasses import dataclass

from .type_identity import is_semantic_scalar_void


def _valid_getter(method) -> bool:
    return bool(
        method
        and method.access != "class"
        and not method.generic_params
        and len(method.params) == 1
        and not method.params[0].keep
        and method.return_type is not None
        and not is_semantic_scalar_void(method.return_type)
    )


def _valid_setter(method) -> bool:
    return bool(
        method
        and method.access != "class"
        and not method.generic_params
        and len(method.params) == 2
        and not method.params[0].keep
        and is_semantic_scalar_void(method.return_type)
    )


@dataclass(frozen=True)
class IndexedProtocol:
    """Declared protocol names plus the signatures proven safe to lower."""

    class_info: object
    declared_getter: object | None
    declared_setter: object | None
    getter: object | None
    setter: object | None

    def substitutions(self, object_type) -> dict:
        return dict(zip(self.class_info.generic_params, object_type.generic_args))


def indexed_protocol(type_expr, class_table, *, active_type_params=None) -> IndexedProtocol | None:
    """Describe a direct class value that declares ``get`` or ``set``."""
    if type_expr is None or type_expr.is_array:
        return None
    if active_type_params and type_expr.base in active_type_params:
        return None
    info = class_table.get(type_expr.base)
    if info is None:
        return None
    # Python analysis normalizes both ordinary and generic class values to one
    # implicit pointer level. A second level is explicit raw pointer storage.
    raw_pointer = type_expr.pointer_depth > 1
    if raw_pointer:
        return None
    getter = info.methods.get("get")
    setter = info.methods.get("set")
    if getter is None and setter is None:
        return None
    return IndexedProtocol(
        class_info=info,
        declared_getter=getter,
        declared_setter=setter,
        getter=getter if _valid_getter(getter) else None,
        setter=setter if _valid_setter(setter) else None,
    )


def indexed_protocol_info(type_expr, class_table, *, method: str | None = None):
    """Compatibility facade returning the owning class for a proven method."""
    protocol = indexed_protocol(type_expr, class_table)
    if protocol is None:
        return None
    if method is None:
        return protocol.class_info
    if method not in {"get", "set"} or getattr(protocol, method + "ter") is None:
        return None
    return protocol.class_info


__all__ = ["IndexedProtocol", "indexed_protocol", "indexed_protocol_info"]
