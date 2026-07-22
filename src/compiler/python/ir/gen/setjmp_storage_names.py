"""Storage-name classification shared by setjmp safety passes."""


def compiler_storage_name(name: str) -> bool:
    """Whether a C binding is compiler-authored rather than source-renamed."""

    return name.startswith("__btrc_") and not name.startswith("__btrc_source_")


__all__ = ["compiler_storage_name"]
