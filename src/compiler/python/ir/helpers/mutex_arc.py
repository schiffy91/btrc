"""ARC identity, payload edges, and terminal cleanup for Mutex nodes."""

from .core import HelperDef

MUTEX_ARC = {
    "__btrc_mutex_arc_retain": HelperDef(
        c_source=r"""static void __btrc_mutex_arc_retain(
        const void* storage, __btrc_mutex_value_access access,
        void* context, void* owner) {
    (void)context;
    if (owner)
        (void)__btrc_arc_retain_edge(access(storage), owner);
    else
        (void)__btrc_arc_retain(access(storage));
}""",
        depends_on=[
            "__btrc_mutex_val_types",
            "__btrc_arc_retain",
            "__btrc_arc_retain_edge",
        ],
    ),
    "__btrc_mutex_arc_release": HelperDef(
        c_source=r"""static void __btrc_mutex_arc_release(
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
}""",
        depends_on=[
            "__btrc_mutex_val_types",
            "__btrc_arc_release",
            "__btrc_arc_release_edge",
            "__btrc_arc_unlink_edge",
        ],
    ),
    "__btrc_mutex_arc_finalize": HelperDef(
        c_source=r"""static void __btrc_mutex_arc_finalize(void* context) {
    (void)context;
    (void)__btrc_flush_cycles();
}""",
        depends_on=["__btrc_mutex_val_types", "__btrc_flush_cycles"],
    ),
    "__btrc_mutex_string_retain": HelperDef(
        c_source=r"""static void __btrc_mutex_string_retain(
        const void* storage, __btrc_mutex_value_access access,
        void* context, void* owner) {
    (void)context;
    (void)owner;
    (void)__btrc_string_retain((const char*)access(storage));
}""",
        depends_on=["__btrc_mutex_val_types", "__btrc_string_retain"],
    ),
    "__btrc_mutex_string_release": HelperDef(
        c_source=r"""static void __btrc_mutex_string_release(
        const void* storage, __btrc_mutex_value_access access,
        void* context, void* owner) {
    (void)context;
    (void)owner;
    __btrc_string_release((const char*)access(storage));
}""",
        depends_on=["__btrc_mutex_val_types", "__btrc_string_release"],
    ),
    "__btrc_mutex_arc_type": HelperDef(
        c_source=r"""static void __btrc_mutex_arc_visit(
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
};""",
        depends_on=[
            "__btrc_mutex_val_types",
            "__btrc_arc_topology_begin",
            "__btrc_arc_topology_leave",
            "__btrc_mark_destroyed",
            "__btrc_throw",
        ],
        required_headers=["stdio.h", "stdlib.h"],
    ),
}

__all__ = ["MUTEX_ARC"]
