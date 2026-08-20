/* btrc-runtime-helper:begin __btrc_mutex_val_types */
typedef void* (*__btrc_mutex_value_access)(const void*);
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
} __btrc_mutex_val_t;
/* btrc-runtime-helper:end __btrc_mutex_val_types */
/* btrc-runtime-helper:begin __btrc_mutex_value_callback_guard */
typedef struct {
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
}
/* btrc-runtime-helper:end __btrc_mutex_value_callback_guard */
/* btrc-runtime-helper:begin __btrc_mutex_finalize_callback_guard */
typedef struct {
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
}
/* btrc-runtime-helper:end __btrc_mutex_finalize_callback_guard */
/* btrc-runtime-helper:begin __btrc_mutex_val_create */
static __btrc_mutex_val_t* __btrc_mutex_val_create(
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
}
/* btrc-runtime-helper:end __btrc_mutex_val_create */
/* btrc-runtime-helper:begin __btrc_mutex_arc_retain */
static void __btrc_mutex_arc_retain(
        const void* storage, __btrc_mutex_value_access access,
        void* context, void* owner) {
    (void)context;
    if (owner)
        (void)__btrc_arc_retain_edge(access(storage), owner);
    else
        (void)__btrc_arc_retain(access(storage));
}
/* btrc-runtime-helper:end __btrc_mutex_arc_retain */
/* btrc-runtime-helper:begin __btrc_mutex_arc_release */
static void __btrc_mutex_arc_release(
        const void* storage, __btrc_mutex_value_access access,
        void* context, void* owner) {
    void* object = access(storage);
    if (owner) {
        (void)__btrc_arc_unlink_edge(object, owner);
        (void)__btrc_arc_release_edge(
            object, (const __btrc_arc_type*)context, NULL);
    } else {
        (void)__btrc_arc_release(
            object, (const __btrc_arc_type*)context);
    }
}
/* btrc-runtime-helper:end __btrc_mutex_arc_release */
/* btrc-runtime-helper:begin __btrc_mutex_arc_finalize */
static void __btrc_mutex_arc_finalize(void* context) {
    (void)context;
    (void)__btrc_flush_cycles();
}
/* btrc-runtime-helper:end __btrc_mutex_arc_finalize */
/* btrc-runtime-helper:begin __btrc_mutex_string_retain */
static void __btrc_mutex_string_retain(
        const void* storage, __btrc_mutex_value_access access,
        void* context, void* owner) {
    (void)context;
    (void)owner;
    (void)__btrc_string_retain((const char*)access(storage));
}
/* btrc-runtime-helper:end __btrc_mutex_string_retain */
/* btrc-runtime-helper:begin __btrc_mutex_string_release */
static void __btrc_mutex_string_release(
        const void* storage, __btrc_mutex_value_access access,
        void* context, void* owner) {
    (void)context;
    (void)owner;
    __btrc_string_release((const char*)access(storage));
}
/* btrc-runtime-helper:end __btrc_mutex_string_release */
/* btrc-runtime-helper:begin __btrc_mutex_arc_type */
static void __btrc_mutex_arc_visit(
        void* object, __btrc_field_visit_fn fn, void* context) {
    __btrc_mutex_val_t* m = (__btrc_mutex_val_t*)object;
    if (!m || !fn) return;
    int err = pthread_mutex_lock(&m->lock);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex lock failed (%d)\n", err);
        exit(1);
    }
    if (m->value && m->slot_access)
        fn((volatile void*)m->value, m->slot_access,
            (const __btrc_arc_type*)m->context, context);
    err = pthread_mutex_unlock(&m->lock);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex unlock failed (%d)\n", err);
        exit(1);
    }
}
static void __btrc_mutex_arc_destroy(void* object) {
    __btrc_mutex_val_t* m = (__btrc_mutex_val_t*)object;
    if (!m) return;
    void* topology = m->slot_access
        ? __btrc_arc_topology_begin() : NULL;
    int err = pthread_mutex_lock(&m->lock);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex lock failed (%d)\n", err);
        exit(1);
    }
    void* old = m->value;
    m->value = NULL;
    err = pthread_mutex_unlock(&m->lock);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex unlock failed (%d)\n", err);
        exit(1);
    }
    err = pthread_mutex_destroy(&m->lock);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex destroy failed (%d)\n", err);
        exit(1);
    }
    if (m->release && old)
        m->release(old, m->access, m->context, m);
    if (topology)
        (void)__btrc_arc_topology_leave(topology);
    __btrc_mark_destroyed(m);
    free(old);
    free(m->context);
    free(m);
}
static const __btrc_arc_type __btrc_mutex_arc_descriptor = {
    __btrc_mutex_arc_visit,
    __btrc_mutex_arc_destroy,
    NULL, NULL, __btrc_throw
};
/* btrc-runtime-helper:end __btrc_mutex_arc_type */
/* btrc-runtime-helper:begin __btrc_mutex_val_get */
static void* __btrc_mutex_val_get(__btrc_mutex_val_t* m) {
    if (!m) {
        fprintf(stderr, "btrc: cannot get a null Mutex\n");
        exit(1);
    }
    void* copy = __btrc_safe_realloc(NULL, m->size);
    void* topology = m->slot_access
        ? __btrc_arc_topology_begin() : NULL;
    int err = pthread_mutex_lock(&m->lock);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex lock failed (%d)\n", err);
        free(copy);
        exit(1);
    }
    memcpy(copy, m->value, m->size);
    char first_error[1024];
    first_error[0] = '\0';
    int retain_failed = m->retain
        && __btrc_mutex_value_callback_guard(
            m->retain, copy, m->access, m->context,
            NULL, first_error, sizeof first_error);
    int has_error = retain_failed;
    __btrc_raise_fn saved_raise = m->raise;
    err = pthread_mutex_unlock(&m->lock);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex unlock failed (%d)\n", err);
        free(copy);
        exit(1);
    }
    int should_flush = topology
        && __btrc_arc_topology_leave(topology);
    if (should_flush && m->finalize) {
        char finalize_error[1024];
        finalize_error[0] = '\0';
        int finalize_failed = __btrc_mutex_finalize_callback_guard(
            m->finalize, m->context,
            finalize_error, sizeof finalize_error);
        if (finalize_failed && !has_error) {
            memcpy(first_error, finalize_error, sizeof first_error);
            has_error = 1;
        }
    }
    if (has_error) {
        if (m->release && !retain_failed) {
            char rollback_error[1024];
            rollback_error[0] = '\0';
            (void)__btrc_mutex_value_callback_guard(
                m->release, copy, m->access, m->context,
                NULL, rollback_error, sizeof rollback_error);
        }
        free(copy);
        __btrc_raise_captured(saved_raise, first_error);
    }
    return copy;
}
/* btrc-runtime-helper:end __btrc_mutex_val_get */
/* btrc-runtime-helper:begin __btrc_mutex_val_set */
static void __btrc_mutex_val_set(
        __btrc_mutex_val_t* m, void* val) {
    if (!m || !val) {
        fprintf(stderr, "btrc: cannot set a null Mutex\n");
        free(val);
        exit(1);
    }
    void* topology = m->slot_access
        ? __btrc_arc_topology_begin() : NULL;
    int err = pthread_mutex_lock(&m->lock);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex lock failed (%d)\n", err);
        free(val);
        exit(1);
    }
    char first_error[1024];
    first_error[0] = '\0';
    int has_error = m->retain
        && __btrc_mutex_value_callback_guard(
            m->retain, val, m->access, m->context, m,
            first_error, sizeof first_error);
    void* old = NULL;
    if (!has_error) {
        old = m->value;
        m->value = val;
    }
    err = pthread_mutex_unlock(&m->lock);
    if (err != 0) {
        fprintf(stderr, "btrc: mutex unlock failed (%d)\n", err);
        exit(1);
    }
    if (!has_error && m->release)
        has_error = __btrc_mutex_value_callback_guard(
            m->release, old, m->access, m->context, m,
            first_error, sizeof first_error);
    int should_flush = topology
        && __btrc_arc_topology_leave(topology);
    if (should_flush && m->finalize) {
        char finalize_error[1024];
        finalize_error[0] = '\0';
        int finalize_failed = __btrc_mutex_finalize_callback_guard(
            m->finalize, m->context,
            finalize_error, sizeof finalize_error);
        if (finalize_failed && !has_error) {
            memcpy(first_error, finalize_error, sizeof first_error);
            has_error = 1;
        }
    }
    __btrc_raise_fn saved_raise = m->raise;
    free(old ? old : val);
    if (has_error)
        __btrc_raise_captured(saved_raise, first_error);
}
/* btrc-runtime-helper:end __btrc_mutex_val_set */
