"""Deferred generic operand lowering with earlier values installed."""


def deferred_generic_operand(emitter, node):
    """Lower one operand after preceding boundary overrides are visible."""

    def lower(overrides):
        previous = {key: emitter._arc_overrides.get(key) for key in overrides}
        emitter._arc_overrides.update(overrides)
        try:
            return emitter.lower_expression(node)
        finally:
            for key, value in previous.items():
                if value is None:
                    emitter._arc_overrides.pop(key, None)
                else:
                    emitter._arc_overrides[key] = value

    return lower


__all__ = ["deferred_generic_operand"]
