"""Exact ABI contracts for the shipped system-tray runtime."""

from .hosted_abi_model import (
    ALIAS_DEPENDENT,
    CHAR_PTR,
    CONSUME,
    INT,
    MUTATE,
    READ,
    RETURN_ALIAS,
    RETURN_INDEPENDENT,
    VALUE,
    VOID,
    VOID_PTR,
    HostedFunction,
    abi_type,
    function,
)

BOOL = abi_type("bool")

HOSTED_NATIVE_TRAY_FUNCTIONS: dict[str, HostedFunction] = {
    "btrc_tray_create": function(
        VOID_PTR,
        CHAR_PTR,
        effects=(READ,),
        return_effect=RETURN_INDEPENDENT,
        return_deallocator="btrc_tray_destroy",
    ),
    "btrc_tray_set_icon": function(
        VOID,
        VOID_PTR,
        CHAR_PTR,
        effects=(MUTATE, READ),
    ),
    "btrc_tray_set_tooltip": function(
        VOID,
        VOID_PTR,
        CHAR_PTR,
        effects=(MUTATE, READ),
    ),
    "btrc_tray_add_item": function(
        INT,
        VOID_PTR,
        CHAR_PTR,
        CHAR_PTR,
        BOOL,
        effects=(MUTATE, READ, READ, VALUE),
    ),
    "btrc_tray_add_separator": function(VOID, VOID_PTR, effects=(MUTATE,)),
    "btrc_tray_set_menu": function(VOID, VOID_PTR, effects=(MUTATE,)),
    "btrc_tray_show": function(BOOL, VOID_PTR, effects=(MUTATE,)),
    "btrc_tray_run_iteration": function(
        BOOL,
        VOID_PTR,
        INT,
        effects=(MUTATE, VALUE),
    ),
    "btrc_tray_take_command": function(
        CHAR_PTR,
        VOID_PTR,
        effects=(MUTATE,),
        return_effect=RETURN_ALIAS,
        return_alias_parameter=0,
        return_alias_shape=ALIAS_DEPENDENT,
    ),
    "btrc_tray_should_quit": function(BOOL, VOID_PTR, effects=(READ,)),
    "btrc_tray_request_quit": function(VOID, VOID_PTR, effects=(MUTATE,)),
    "btrc_tray_destroy": function(
        VOID,
        VOID_PTR,
        effects=(CONSUME,),
        raw_lifetime=True,
        consume_deallocator="btrc_tray_destroy",
    ),
}

__all__ = ["HOSTED_NATIVE_TRAY_FUNCTIONS"]
