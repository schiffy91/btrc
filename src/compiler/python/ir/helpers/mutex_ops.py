"""Locked get/set operations for ARC-managed ``Mutex<T>`` nodes."""

from .core import HelperDef

MUTEX_OPS = {
    "__btrc_mutex_val_get": HelperDef(
        c_source=r"""static void* __btrc_mutex_val_get(__btrc_mutex_val_t* m) {
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
    char first_error[1024] = "";
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
        char finalize_error[1024] = "";
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
            char rollback_error[1024] = "";
            (void)__btrc_mutex_value_callback_guard(
                m->release, copy, m->access, m->context,
                NULL, rollback_error, sizeof rollback_error);
        }
        free(copy);
        __btrc_raise_captured(saved_raise, first_error);
    }
    return copy;
}""",
        depends_on=[
            "__btrc_mutex_value_callback_guard",
            "__btrc_mutex_finalize_callback_guard",
            "__btrc_arc_topology_begin",
            "__btrc_arc_topology_leave",
            "__btrc_raise_captured",
            "__btrc_safe_realloc",
        ],
        required_headers=["string.h"],
    ),
    "__btrc_mutex_val_set": HelperDef(
        c_source=r"""static void __btrc_mutex_val_set(
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
    char first_error[1024] = "";
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
        char finalize_error[1024] = "";
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
}""",
        depends_on=[
            "__btrc_mutex_value_callback_guard",
            "__btrc_mutex_finalize_callback_guard",
            "__btrc_arc_topology_begin",
            "__btrc_arc_topology_leave",
            "__btrc_raise_captured",
        ],
        required_headers=["string.h"],
    ),
}

__all__ = ["MUTEX_OPS"]
