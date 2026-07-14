"""Mutex type, guarded callback, and construction runtime helpers."""

from .core import HelperDef

MUTEX_CORE = {
    "__btrc_mutex_val_types": HelperDef(
        c_source=(
            "typedef void* (*__btrc_mutex_value_access)(const void*);\n"
            "typedef void (*__btrc_mutex_value_callback)(\n"
            "    const void*, __btrc_mutex_value_access, void*, void*);\n"
            "typedef void (*__btrc_mutex_finalize_callback)(void*);\n"
            "typedef struct {\n"
            "    pthread_mutex_t lock;\n"
            "    void* value;\n"
            "    size_t size;\n"
            "    __btrc_mutex_value_access access;\n"
            "    __btrc_arc_slot_access_fn slot_access;\n"
            "    void* context;\n"
            "    void* owner;\n"
            "    __btrc_mutex_value_callback retain;\n"
            "    __btrc_mutex_value_callback release;\n"
            "    __btrc_mutex_finalize_callback finalize;\n"
            "    __btrc_raise_fn raise;\n"
            "} __btrc_mutex_val_t;"
        ),
        depends_on=["__btrc_arc_callback_types"],
        required_headers=["pthread.h"],
    ),
    "__btrc_mutex_value_callback_guard": HelperDef(
        c_source=(
            "typedef struct {\n"
            "    __btrc_mutex_value_callback callback;\n"
            "    const void* storage;\n"
            "    __btrc_mutex_value_access access;\n"
            "    void* context;\n"
            "    void* owner;\n"
            "} __btrc_mutex_value_call;\n"
            "static void __btrc_mutex_value_callback_thunk(void* raw) {\n"
            "    __btrc_mutex_value_call* call =\n"
            "        (__btrc_mutex_value_call*)raw;\n"
            "    call->callback(\n"
            "        call->storage, call->access, call->context, call->owner);\n"
            "}\n"
            "static int __btrc_mutex_value_callback_guard(\n"
            "        __btrc_mutex_value_callback callback,\n"
            "        const void* storage, __btrc_mutex_value_access access,\n"
            "        void* context, void* owner,\n"
            "        char* error, size_t error_capacity) {\n"
            "    __btrc_mutex_value_call call = {\n"
            "        callback, storage, access, context, owner};\n"
            "    return __btrc_arc_guard_hook(\n"
            "        __btrc_mutex_value_callback_thunk,\n"
            "        &call, error, error_capacity);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_types", "__btrc_arc_guard_hook"],
    ),
    "__btrc_mutex_finalize_callback_guard": HelperDef(
        c_source=(
            "typedef struct {\n"
            "    __btrc_mutex_finalize_callback callback;\n"
            "    void* context;\n"
            "} __btrc_mutex_finalize_call;\n"
            "static void __btrc_mutex_finalize_callback_thunk(void* raw) {\n"
            "    __btrc_mutex_finalize_call* call =\n"
            "        (__btrc_mutex_finalize_call*)raw;\n"
            "    call->callback(call->context);\n"
            "}\n"
            "static int __btrc_mutex_finalize_callback_guard(\n"
            "        __btrc_mutex_finalize_callback callback, void* context,\n"
            "        char* error, size_t error_capacity) {\n"
            "    __btrc_mutex_finalize_call call = {callback, context};\n"
            "    return __btrc_arc_guard_hook(\n"
            "        __btrc_mutex_finalize_callback_thunk,\n"
            "        &call, error, error_capacity);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_types", "__btrc_arc_guard_hook"],
    ),
    "__btrc_mutex_val_create": HelperDef(
        c_source=(
            "static __btrc_mutex_val_t* __btrc_mutex_val_create(\n"
            "        void* initial, size_t size,\n"
            "        __btrc_mutex_value_access access,\n"
            "        __btrc_arc_slot_access_fn slot_access,\n"
            "        const void* context, size_t context_size,\n"
            "        __btrc_mutex_value_callback retain,\n"
            "        __btrc_mutex_value_callback release,\n"
            "        __btrc_mutex_finalize_callback finalize,\n"
            "        __btrc_raise_fn raise) {\n"
            '    if (!initial || size == 0) { fprintf(stderr, "btrc: Mutex requires an initial value\\n"); exit(1); }\n'
            '    if ((!retain) != (!release)) { fprintf(stderr, "btrc: invalid Mutex ownership callbacks\\n"); free(initial); exit(1); }\n'
            '    if ((!access) != (!retain)) { fprintf(stderr, "btrc: invalid Mutex value adapter\\n"); free(initial); exit(1); }\n'
            '    if (slot_access && !retain) { fprintf(stderr, "btrc: invalid Mutex graph adapter\\n"); free(initial); exit(1); }\n'
            '    if (finalize && !release) { fprintf(stderr, "btrc: invalid Mutex finalizer callback\\n"); free(initial); exit(1); }\n'
            '    if (raise && !release) { fprintf(stderr, "btrc: invalid Mutex raise callback\\n"); free(initial); exit(1); }\n'
            '    if ((!context) != (context_size == 0)) { fprintf(stderr, "btrc: invalid Mutex ownership context\\n"); free(initial); exit(1); }\n'
            "    __btrc_mutex_val_t* m = (__btrc_mutex_val_t*)__btrc_safe_realloc(\n"
            "        NULL, sizeof(__btrc_mutex_val_t));\n"
            "    int err = pthread_mutex_init(&m->lock, NULL);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: mutex init failed (%d)\\n", err); free(initial); free(m); exit(1); }\n'
            "    m->value = initial;\n"
            "    m->size = size;\n"
            "    m->access = access;\n"
            "    m->slot_access = slot_access;\n"
            "    m->context = NULL;\n"
            "    m->owner = NULL;\n"
            "    if (context_size != 0) {\n"
            "        m->context = __btrc_safe_realloc(NULL, context_size);\n"
            "        memcpy(m->context, context, context_size);\n"
            "    }\n"
            "    m->retain = retain;\n"
            "    m->release = release;\n"
            "    m->finalize = finalize;\n"
            "    m->raise = raise;\n"
            "    if (m->retain) {\n"
            '        char error[1024] = "";\n'
            "        if (__btrc_mutex_value_callback_guard(\n"
            "                m->retain, m->value, m->access, m->context,\n"
            "                NULL, error, sizeof error)) {\n"
            "            __btrc_raise_fn saved_raise = m->raise;\n"
            "            (void)pthread_mutex_destroy(&m->lock);\n"
            "            free(m->context);\n"
            "            free(initial);\n"
            "            free(m);\n"
            "            __btrc_raise_captured(saved_raise, error);\n"
            "        }\n"
            "    }\n"
            "    return m;\n"
            "}"
        ),
        depends_on=[
            "__btrc_mutex_val_types",
            "__btrc_mutex_value_callback_guard",
            "__btrc_raise_captured",
            "__btrc_safe_realloc",
        ],
        required_headers=["string.h"],
    ),
}

__all__ = ["MUTEX_CORE"]
