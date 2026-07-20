"""ABI specs for compiler helpers intentionally callable from source."""

from .hosted_abi_model import (
    ALIAS_EXACT,
    CHAR_PTR,
    CHAR_PTR_PTR,
    CONST_CHAR_PTR,
    CONSUME,
    DEALLOC_FREE,
    INT,
    MUTATE,
    READ,
    RETURN_ALIAS,
    RETURN_FRESH,
    RETURN_INDEPENDENT,
    SIZE,
    VALUE,
    VOID_PTR,
    HostedFunction,
    abi_type,
    function,
)

SOURCE_RUNTIME_FUNCTIONS: dict[str, HostedFunction] = {
    "__btrc_safe_calloc": function(
        VOID_PTR,
        SIZE,
        SIZE,
        return_effect=RETURN_FRESH,
        return_deallocator=DEALLOC_FREE,
    ),
    "__btrc_safe_realloc": function(
        VOID_PTR,
        VOID_PTR,
        SIZE,
        effects=(CONSUME, VALUE),
        return_effect=RETURN_FRESH,
        raw_lifetime=True,
        return_deallocator=DEALLOC_FREE,
        consume_deallocator=DEALLOC_FREE,
    ),
    "__btrc_str_track": function(
        CHAR_PTR,
        CHAR_PTR,
        effects=(CONSUME,),
        semantic_result=abi_type("string"),
        return_effect=RETURN_FRESH,
    ),
    "__btrc_strdup": function(
        CHAR_PTR,
        CONST_CHAR_PTR,
        effects=(READ,),
        return_effect=RETURN_FRESH,
        return_deallocator=DEALLOC_FREE,
    ),
    "__btrc_string_adopt": function(
        CHAR_PTR,
        CHAR_PTR,
        effects=(CONSUME,),
        semantic_result=abi_type("string"),
        return_effect=RETURN_FRESH,
    ),
    "__btrc_string_alloc": function(
        CHAR_PTR,
        INT,
        semantic_result=abi_type("string"),
        return_effect=RETURN_FRESH,
    ),
    "__btrc_string_length": function(INT, CONST_CHAR_PTR, effects=(READ,)),
    "__btrc_string_live_count": function(SIZE),
    "__btrc_string_or_empty": function(
        CONST_CHAR_PTR,
        CONST_CHAR_PTR,
        effects=(READ,),
        return_effect=RETURN_ALIAS,
        return_alias_parameter=0,
        return_alias_null_effect=RETURN_INDEPENDENT,
        return_alias_shape=ALIAS_EXACT,
    ),
    "__btrc_descriptor_close_bound": function(INT),
    "__btrc_close_descriptors_from": function(INT, INT),
    "__btrc_move_descriptor_outside_stdio": function(
        INT,
        abi_type("int", 1),
        effects=(MUTATE,),
    ),
    "__btrc_posix_spawn_cloexec": function(
        abi_type("pid_t"),
        CONST_CHAR_PTR,
        CHAR_PTR_PTR,
        CHAR_PTR_PTR,
        CONST_CHAR_PTR,
        INT,
        INT,
        INT,
        INT,
        INT,
        INT,
        INT,
        effects=(READ, READ, READ, READ, VALUE, VALUE, VALUE, VALUE, VALUE, VALUE, VALUE),
    ),
}

SOURCE_RUNTIME_HELPERS = frozenset(SOURCE_RUNTIME_FUNCTIONS)
SOURCE_RUNTIME_ADOPTING_HELPERS = frozenset(
    name
    for name, spec in SOURCE_RUNTIME_FUNCTIONS.items()
    if not spec.raw_lifetime
    and spec.semantic_result is not None
    and spec.semantic_result.base == "string"
    and spec.effects
    and spec.effects[0] == CONSUME
)

__all__ = [
    "SOURCE_RUNTIME_ADOPTING_HELPERS",
    "SOURCE_RUNTIME_FUNCTIONS",
    "SOURCE_RUNTIME_HELPERS",
]
