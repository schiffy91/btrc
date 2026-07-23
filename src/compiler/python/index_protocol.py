"""Owned recognition of proven class-backed index protocols."""

from dataclasses import dataclass

from .type_identity import TypeIdentity


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


class IndexedProtocolResolver:
    """Resolve indexed access against one compiler's analyzed class universe."""

    def __init__(self, type_identity: TypeIdentity, class_table) -> None:
        self._type_identity = type_identity
        self._class_table = class_table

    def resolve(self, type_expr, *, active_type_params=None) -> IndexedProtocol | None:
        """Describe a direct class value that declares ``get`` or ``set``."""
        if type_expr is None or type_expr.is_array:
            return None
        if active_type_params and type_expr.base in active_type_params:
            return None
        info = self._class_table.get(type_expr.base)
        if info is None or type_expr.pointer_depth > 1:
            return None
        getter = info.methods.get("get")
        setter = info.methods.get("set")
        if getter is None and setter is None:
            return None
        return IndexedProtocol(
            class_info=info,
            declared_getter=getter,
            declared_setter=setter,
            getter=getter if self._valid_getter(getter) else None,
            setter=setter if self._valid_setter(setter) else None,
        )

    def class_info(
        self,
        type_expr,
        *,
        method: str | None = None,
        active_type_params=None,
    ):
        """Return the owning class for a proven indexed method."""
        protocol = self.resolve(
            type_expr,
            active_type_params=active_type_params,
        )
        if protocol is None:
            return None
        if method is None:
            return protocol.class_info
        if method not in {"get", "set"} or getattr(protocol, method + "ter") is None:
            return None
        return protocol.class_info

    def _valid_getter(self, method) -> bool:
        return bool(
            method
            and method.access != "class"
            and not method.generic_params
            and len(method.params) == 1
            and not method.params[0].keep
            and method.return_type is not None
            and not self._type_identity.is_scalar_void(method.return_type)
        )

    def _valid_setter(self, method) -> bool:
        return bool(
            method
            and method.access != "class"
            and not method.generic_params
            and len(method.params) == 2
            and not method.params[0].keep
            and self._type_identity.is_scalar_void(method.return_type)
        )


__all__ = ["IndexedProtocol", "IndexedProtocolResolver"]
