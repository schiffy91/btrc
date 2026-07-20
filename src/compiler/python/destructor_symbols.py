"""Canonical compiler-reserved source-destructor symbol names."""


def destructor_hook_symbol(owner_name: str) -> str:
    return f"__btrc_{owner_name}_destructor_hook"


__all__ = ["destructor_hook_symbol"]
