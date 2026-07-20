"""Exact ABI contracts for shipped GUI, font, and window runtimes."""

from .hosted_abi_model import (
    CHAR_PTR,
    CONSUME,
    INT,
    MUTATE,
    READ,
    RETURN_INDEPENDENT,
    UNKNOWN,
    VALUE,
    VOID,
    VOID_PTR,
    HostedFunction,
    abi_type,
    function,
)

BOOL = abi_type("bool")
UINT = abi_type("unsigned int")


def _owned(deallocator, *parameters, effects) -> HostedFunction:
    return function(
        VOID_PTR,
        *parameters,
        effects=effects,
        return_effect=RETURN_INDEPENDENT,
        return_deallocator=deallocator,
    )


def _destroy(name) -> HostedFunction:
    return function(
        VOID,
        VOID_PTR,
        effects=(CONSUME,),
        raw_lifetime=True,
        consume_deallocator=name,
    )


HOSTED_NATIVE_GUI_FUNCTIONS: dict[str, HostedFunction] = {
    "btrc_gui_surface_create": _owned(
        "btrc_gui_surface_destroy",
        INT,
        INT,
        effects=(VALUE, VALUE),
    ),
    "btrc_gui_surface_destroy": _destroy("btrc_gui_surface_destroy"),
    "btrc_gui_surface_width": function(INT, VOID_PTR, effects=(READ,)),
    "btrc_gui_surface_height": function(INT, VOID_PTR, effects=(READ,)),
    "btrc_gui_surface_resize": function(
        VOID,
        VOID_PTR,
        INT,
        INT,
        effects=(MUTATE, VALUE, VALUE),
    ),
    "btrc_gui_clear": function(
        VOID,
        VOID_PTR,
        UINT,
        effects=(MUTATE, VALUE),
    ),
    "btrc_gui_fill_rect": function(
        VOID,
        VOID_PTR,
        INT,
        INT,
        INT,
        INT,
        UINT,
        effects=(MUTATE, VALUE, VALUE, VALUE, VALUE, VALUE),
    ),
    "btrc_gui_blend_rect": function(
        VOID,
        VOID_PTR,
        INT,
        INT,
        INT,
        INT,
        UINT,
        effects=(MUTATE, VALUE, VALUE, VALUE, VALUE, VALUE),
    ),
    "btrc_gui_draw_text": function(
        VOID,
        VOID_PTR,
        INT,
        INT,
        CHAR_PTR,
        UINT,
        INT,
        effects=(MUTATE, VALUE, VALUE, READ, VALUE, VALUE),
    ),
    "btrc_gui_text_width": function(
        INT,
        CHAR_PTR,
        INT,
        effects=(READ, VALUE),
    ),
    "btrc_gui_text_height": function(INT, INT, effects=(VALUE,)),
    "btrc_gui_get_pixel": function(
        UINT,
        VOID_PTR,
        INT,
        INT,
        effects=(READ, VALUE, VALUE),
    ),
    "btrc_gui_save_ppm": function(
        BOOL,
        VOID_PTR,
        CHAR_PTR,
        effects=(READ, READ),
    ),
    "btrc_gui_font_load": _owned(
        "btrc_gui_font_destroy",
        CHAR_PTR,
        INT,
        effects=(READ, VALUE),
    ),
    "btrc_gui_font_destroy": _destroy("btrc_gui_font_destroy"),
    # The font handle escapes into process-global state.
    "btrc_gui_set_font": function(VOID, VOID_PTR, effects=(UNKNOWN,)),
    "btrc_gui_window_open": _owned(
        "btrc_gui_window_close",
        CHAR_PTR,
        INT,
        INT,
        effects=(READ, VALUE, VALUE),
    ),
    "btrc_gui_window_should_close": function(BOOL, VOID_PTR, effects=(READ,)),
    "btrc_gui_window_poll": function(VOID, VOID_PTR, effects=(MUTATE,)),
    "btrc_gui_window_mouse_x": function(INT, VOID_PTR, effects=(READ,)),
    "btrc_gui_window_mouse_y": function(INT, VOID_PTR, effects=(READ,)),
    "btrc_gui_window_mouse_down": function(BOOL, VOID_PTR, effects=(READ,)),
    "btrc_gui_window_fb_width": function(INT, VOID_PTR, effects=(READ,)),
    "btrc_gui_window_fb_height": function(INT, VOID_PTR, effects=(READ,)),
    "btrc_gui_window_present": function(
        VOID,
        VOID_PTR,
        VOID_PTR,
        effects=(MUTATE, READ),
    ),
    "btrc_gui_window_close": _destroy("btrc_gui_window_close"),
}

__all__ = ["HOSTED_NATIVE_GUI_FUNCTIONS"]
