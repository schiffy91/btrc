"""Fail-closed boundary for pointer escapes not modelled field-sensitively."""

from .errors import CodegenError
from .setjmp_mutations import contains_setjmp


def reject_unmodelled_setjmp_captures(function, effects) -> None:
    if not contains_setjmp(function.body):
        return
    for storage in effects.flow.unknown_pointer_values:
        raise CodegenError(
            f"pointer storage object '{storage.name}' receives an unmodelled "
            "pointer value in a function containing try/setjmp"
        )
    escaped = effects.flow.captures | {origin for origin in effects.flow.returns if origin.depth == 0}
    for origin in escaped:
        storage = origin.storage
        if origin.depth == 0 and origin.source_exposed and storage.automatic and not storage.compiler_owned:
            raise CodegenError(
                f"automatic storage object '{storage.name}' escapes into "
                "unmodelled storage in a function containing try/setjmp"
            )


__all__ = ["reject_unmodelled_setjmp_captures"]
