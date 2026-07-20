"""Mutex value transport, guarded callbacks, and construction."""

from .core import HelperDef

MUTEX_CORE = {
    "__btrc_mutex_val_types": HelperDef(
        c_source=r"""typedef void* (*__btrc_mutex_value_access)(const void*);
typedef void (*__btrc_mutex_value_callback)(
    const void*, __btrc_mutex_value_access, void*, void*);
typedef void (*__btrc_mutex_finalize_callback)(void*);
typedef struct {
    __btrc_arc_header arc;
    pthread_mutex_t lock;
    void* value;
    size_t size;
    __btrc_mutex_value_access access;
    __btrc_arc_slot_access_fn slot_access;
    void* context;
    __btrc_mutex_value_callback retain;
    __btrc_mutex_value_callback release;
    __btrc_mutex_finalize_callback finalize;
    __btrc_raise_fn raise;
} __btrc_mutex_val_t;""",
        depends_on=["__btrc_arc_callback_types"],
        required_headers=["pthread.h"],
    ),
    "__btrc_mutex_value_callback_guard": HelperDef(
        c_source=r"""typedef struct {
    __btrc_mutex_value_callback callback;
    const void* storage;
    __btrc_mutex_value_access access;
    void* context;
    void* owner;
} __btrc_mutex_value_call;
static void __btrc_mutex_value_callback_thunk(void* raw) {
    __btrc_mutex_value_call* call = (__btrc_mutex_value_call*)raw;
    call->callback(
        call->storage, call->access, call->context, call->owner);
}
static int __btrc_mutex_value_callback_guard(
        __btrc_mutex_value_callback callback,
        const void* storage, __btrc_mutex_value_access access,
        void* context, void* owner,
        char* error, size_t error_capacity) {
    __btrc_mutex_value_call call = {
        callback, storage, access, context, owner};
    return __btrc_arc_guard_hook(
        __btrc_mutex_value_callback_thunk,
        &call, error, error_capacity);
}""",
        depends_on=["__btrc_mutex_val_types", "__btrc_arc_guard_hook"],
    ),
    "__btrc_mutex_finalize_callback_guard": HelperDef(
        c_source=r"""typedef struct {
    __btrc_mutex_finalize_callback callback;
    void* context;
} __btrc_mutex_finalize_call;
static void __btrc_mutex_finalize_callback_thunk(void* raw) {
    __btrc_mutex_finalize_call* call =
        (__btrc_mutex_finalize_call*)raw;
    call->callback(call->context);
}
static int __btrc_mutex_finalize_callback_guard(
        __btrc_mutex_finalize_callback callback, void* context,
        char* error, size_t error_capacity) {
    __btrc_mutex_finalize_call call = {callback, context};
    return __btrc_arc_guard_hook(
        __btrc_mutex_finalize_callback_thunk,
        &call, error, error_capacity);
}""",
        depends_on=["__btrc_mutex_val_types", "__btrc_arc_guard_hook"],
    ),
    "__btrc_mutex_val_create": HelperDef(
        c_source=r"""static __btrc_mutex_val_t* __btrc_mutex_val_create(
        void* initial, size_t size,
        __btrc_mutex_value_access access,
        __btrc_arc_slot_access_fn slot_access,
        const void* context, size_t context_size,
        __btrc_mutex_value_callback retain,
        __btrc_mutex_value_callback release,
        __btrc_mutex_finalize_callback finalize,
        __btrc_raise_fn raise) {
    if (!initial || size == 0) {
        fprintf(stderr, "btrc: Mutex requires an initial value\n");
        exit(1);
    }
    if ((!retain) != (!release) || (!access) != (!retain)
            || (slot_access && !retain) || (finalize && !release)
            || (raise && !release)
            || ((!context) != (context_size == 0))) {
        fprintf(stderr, "btrc: invalid Mutex ownership metadata\n");
        free(initial);
        exit(1);
    }
    __btrc_mutex_val_t* m = (__btrc_mutex_val_t*)__btrc_safe_realloc(
        NULL, sizeof(__btrc_mutex_val_t));
    memset(m, 0, sizeof(*m));
    int err = pthread_mutex_init(&m->lock, NULL);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex init failed (%d)\n", err);
        free(initial);
        free(m);
        exit(1);
    }
    m->value = initial;
    m->size = size;
    m->access = access;
    m->slot_access = slot_access;
    if (context_size != 0) {
        m->context = __btrc_safe_realloc(NULL, context_size);
        memcpy(m->context, context, context_size);
    }
    m->retain = retain;
    m->release = release;
    m->finalize = finalize;
    m->raise = raise;
    m->arc.rc = 1;
    m->arc.edge_rc = 0;
    m->arc.type = &__btrc_mutex_arc_descriptor;
    m->arc.state = __BTRC_ARC_LIVE;
    if (m->retain) {
        char error[1024];
        error[0] = '\0';
        if (__btrc_mutex_value_callback_guard(
                m->retain, m->value, m->access, m->context,
                m, error, sizeof error)) {
            __btrc_raise_fn saved_raise = m->raise;
            (void)pthread_mutex_destroy(&m->lock);
            free(m->context);
            free(initial);
            free(m);
            __btrc_raise_captured(saved_raise, error);
        }
    }
    return m;
}""",
        depends_on=[
            "__btrc_mutex_arc_type",
            "__btrc_mutex_value_callback_guard",
            "__btrc_raise_captured",
            "__btrc_safe_realloc",
        ],
        required_headers=["string.h"],
    ),
}

__all__ = ["MUTEX_CORE"]
