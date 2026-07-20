"""Exact ABI contracts for the shipped GPU native surface."""

from .hosted_abi_model import (
    CHAR_PTR,
    CONSUME,
    FLOAT,
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
VOID_PTR_PTR = abi_type("void", 2)


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


HOSTED_NATIVE_GPU_FUNCTIONS: dict[str, HostedFunction] = {
    "btrc_gpu_available": function(BOOL),
    "btrc_gpu_window_create": _owned(
        "btrc_gpu_window_destroy",
        CHAR_PTR,
        INT,
        INT,
        effects=(READ, VALUE, VALUE),
    ),
    "btrc_gpu_window_is_open": function(BOOL, VOID_PTR, effects=(READ,)),
    "btrc_gpu_window_poll": function(VOID, VOID_PTR, effects=(MUTATE,)),
    "btrc_gpu_window_width": function(INT, VOID_PTR, effects=(MUTATE,)),
    "btrc_gpu_window_height": function(INT, VOID_PTR, effects=(MUTATE,)),
    "btrc_gpu_window_key_pressed": function(
        BOOL,
        VOID_PTR,
        INT,
        effects=(READ, VALUE),
    ),
    "btrc_gpu_window_destroy": _destroy("btrc_gpu_window_destroy"),
    "btrc_gpu_init": _owned(
        "btrc_gpu_destroy",
        VOID_PTR,
        effects=(UNKNOWN,),
    ),
    "btrc_gpu_destroy": _destroy("btrc_gpu_destroy"),
    "btrc_gpu_create_shader": _owned(
        "btrc_gpu_shader_destroy",
        VOID_PTR,
        CHAR_PTR,
        effects=(MUTATE, READ),
    ),
    "btrc_gpu_shader_destroy": _destroy("btrc_gpu_shader_destroy"),
    "btrc_gpu_create_render_pipeline": _owned(
        "btrc_gpu_pipeline_destroy",
        VOID_PTR,
        VOID_PTR,
        CHAR_PTR,
        CHAR_PTR,
        effects=(MUTATE, READ, READ, READ),
    ),
    "btrc_gpu_pipeline_destroy": _destroy("btrc_gpu_pipeline_destroy"),
    "btrc_gpu_begin_frame": function(
        BOOL,
        VOID_PTR,
        FLOAT,
        FLOAT,
        FLOAT,
        FLOAT,
        effects=(MUTATE, VALUE, VALUE, VALUE, VALUE),
    ),
    "btrc_gpu_draw": function(
        VOID,
        VOID_PTR,
        VOID_PTR,
        INT,
        effects=(MUTATE, READ, VALUE),
    ),
    "btrc_gpu_end_frame": function(VOID, VOID_PTR, effects=(MUTATE,)),
    "btrc_gpu_get_time": function(FLOAT),
    "btrc_gpu_create_uniform": _owned(
        "btrc_gpu_uniform_destroy",
        VOID_PTR,
        INT,
        effects=(MUTATE, VALUE),
    ),
    "btrc_gpu_set_uniform": function(
        VOID,
        VOID_PTR,
        INT,
        FLOAT,
        effects=(MUTATE, VALUE, VALUE),
    ),
    "btrc_gpu_upload_uniform": function(
        VOID,
        VOID_PTR,
        VOID_PTR,
        effects=(MUTATE, MUTATE),
    ),
    "btrc_gpu_draw_uniform": function(
        VOID,
        VOID_PTR,
        VOID_PTR,
        INT,
        VOID_PTR,
        effects=(MUTATE, READ, VALUE, MUTATE),
    ),
    "btrc_gpu_uniform_destroy": _destroy("btrc_gpu_uniform_destroy"),
    "btrc_gpu_init_compute": _owned("btrc_gpu_destroy", effects=()),
    # Process singleton: independent of arguments, but deliberately has no
    # deallocator because callers do not own this shared handle.
    "btrc_gpu_acquire_compute": function(
        VOID_PTR,
        return_effect=RETURN_INDEPENDENT,
    ),
    "btrc_gpu_create_buffer": _owned(
        "btrc_gpu_buffer_destroy",
        VOID_PTR,
        INT,
        INT,
        effects=(MUTATE, VALUE, VALUE),
    ),
    "btrc_gpu_write_buffer": function(
        VOID,
        VOID_PTR,
        VOID_PTR,
        VOID_PTR,
        INT,
        effects=(MUTATE, MUTATE, READ, VALUE),
    ),
    "btrc_gpu_read_buffer_checked": function(
        BOOL,
        VOID_PTR,
        VOID_PTR,
        VOID_PTR,
        INT,
        effects=(MUTATE, READ, MUTATE, VALUE),
    ),
    "btrc_gpu_read_buffer": function(
        VOID,
        VOID_PTR,
        VOID_PTR,
        VOID_PTR,
        INT,
        effects=(MUTATE, READ, MUTATE, VALUE),
    ),
    "btrc_gpu_buffer_destroy": _destroy("btrc_gpu_buffer_destroy"),
    "btrc_gpu_create_compute_pipeline": _owned(
        "btrc_gpu_compute_pipeline_destroy",
        VOID_PTR,
        VOID_PTR,
        CHAR_PTR,
        effects=(MUTATE, READ, READ),
    ),
    "btrc_gpu_compute_pipeline_destroy": _destroy("btrc_gpu_compute_pipeline_destroy"),
    "btrc_gpu_create_bind_group": _owned(
        "btrc_gpu_bind_group_destroy",
        VOID_PTR,
        VOID_PTR,
        VOID_PTR_PTR,
        INT,
        effects=(MUTATE, READ, UNKNOWN, VALUE),
    ),
    "btrc_gpu_bind_group_destroy": _destroy("btrc_gpu_bind_group_destroy"),
    "btrc_gpu_dispatch": function(
        BOOL,
        VOID_PTR,
        VOID_PTR,
        VOID_PTR,
        INT,
        effects=(MUTATE, READ, MUTATE, VALUE),
    ),
}

__all__ = ["HOSTED_NATIVE_GPU_FUNCTIONS"]
