"""Opaque ``Mutex<T>`` runtime with typed-box and ownership callbacks."""

from __future__ import annotations

from .core import HelperDef

MUTEXES = {
    "__btrc_mutex_val_create": HelperDef(
        c_source=(
            "typedef void (*__btrc_mutex_value_callback)(\n"
            "    void*, void*);\n"
            "typedef struct {\n"
            "    pthread_mutex_t lock;\n"
            "    void* value;\n"
            "    size_t size;\n"
            "    void* context;\n"
            "    __btrc_mutex_value_callback retain;\n"
            "    __btrc_mutex_value_callback release;\n"
            "} __btrc_mutex_val_t;\n"
            "\n"
            "static __btrc_mutex_val_t* __btrc_mutex_val_create(\n"
            "        void* initial, size_t size,\n"
            "        const void* context, size_t context_size,\n"
            "        __btrc_mutex_value_callback retain,\n"
            "        __btrc_mutex_value_callback release) {\n"
            '    if (!initial || size == 0) { fprintf(stderr, "btrc: Mutex requires an initial value\\n"); exit(1); }\n'
            '    if ((!retain) != (!release)) { fprintf(stderr, "btrc: invalid Mutex ownership callbacks\\n"); free(initial); exit(1); }\n'
            '    if ((!context) != (context_size == 0)) { fprintf(stderr, "btrc: invalid Mutex ownership context\\n"); free(initial); exit(1); }\n'
            "    __btrc_mutex_val_t* m = (__btrc_mutex_val_t*)__btrc_safe_realloc(\n"
            "        NULL, sizeof(__btrc_mutex_val_t));\n"
            "    int err = pthread_mutex_init(&m->lock, NULL);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: mutex init failed (%d)\\n", err); free(initial); free(m); exit(1); }\n'
            "    m->value = initial;\n"
            "    m->size = size;\n"
            "    m->context = NULL;\n"
            "    if (context_size != 0) {\n"
            "        m->context = __btrc_safe_realloc(NULL, context_size);\n"
            "        memcpy(m->context, context, context_size);\n"
            "    }\n"
            "    m->retain = retain;\n"
            "    m->release = release;\n"
            "    if (m->retain) m->retain(*(void**)m->value, m->context);\n"
            "    return m;\n"
            "}"
        ),
        depends_on=["__btrc_safe_realloc"],
        required_headers=["pthread.h", "string.h"],
    ),
    "__btrc_mutex_arc_retain": HelperDef(
        c_source=(
            "static void __btrc_mutex_arc_retain(\n"
            "        void* value, void* context) {\n"
            "    (void)context;\n"
            "    (void)__btrc_arc_retain(value);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_create", "__btrc_arc_retain"],
    ),
    "__btrc_mutex_arc_release": HelperDef(
        c_source=(
            "static void __btrc_mutex_arc_release(\n"
            "        void* value, void* context) {\n"
            "    __btrc_arc_release(value, (const __btrc_arc_type*)context);\n"
            "    __btrc_poll_cycles();\n"
            "}"
        ),
        depends_on=[
            "__btrc_mutex_val_create",
            "__btrc_arc_release",
            "__btrc_poll_cycles",
        ],
    ),
    "__btrc_mutex_string_retain": HelperDef(
        c_source=(
            "static void __btrc_mutex_string_retain(\n"
            "        void* value, void* context) {\n"
            "    (void)context;\n"
            "    (void)__btrc_string_retain((char*)value);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_create", "__btrc_string_retain"],
    ),
    "__btrc_mutex_string_release": HelperDef(
        c_source=(
            "static void __btrc_mutex_string_release(\n"
            "        void* value, void* context) {\n"
            "    (void)context;\n"
            "    __btrc_string_release((char*)value);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_create", "__btrc_string_release"],
    ),
    "__btrc_mutex_val_get": HelperDef(
        c_source=(
            "static void* __btrc_mutex_val_get(__btrc_mutex_val_t* m) {\n"
            '    if (!m) { fprintf(stderr, "btrc: cannot get a null Mutex\\n"); exit(1); }\n'
            "    void* copy = __btrc_safe_realloc(NULL, m->size);\n"
            "    int err = pthread_mutex_lock(&m->lock);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: mutex lock failed (%d)\\n", err); exit(1); }\n'
            "    memcpy(copy, m->value, m->size);\n"
            "    if (m->retain) m->retain(*(void**)copy, m->context);\n"
            "    err = pthread_mutex_unlock(&m->lock);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: mutex unlock failed (%d)\\n", err); exit(1); }\n'
            "    return copy;\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_create"],
    ),
    "__btrc_mutex_val_set": HelperDef(
        c_source=(
            "static void __btrc_mutex_val_set(__btrc_mutex_val_t* m, void* val) {\n"
            '    if (!m || !val) { fprintf(stderr, "btrc: cannot set a null Mutex\\n"); free(val); exit(1); }\n'
            "    if (m->retain) m->retain(*(void**)val, m->context);\n"
            "    int err = pthread_mutex_lock(&m->lock);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: mutex lock failed (%d)\\n", err); exit(1); }\n'
            "    void* old = m->value;\n"
            "    m->value = val;\n"
            "    err = pthread_mutex_unlock(&m->lock);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: mutex unlock failed (%d)\\n", err); exit(1); }\n'
            "    if (m->release) m->release(*(void**)old, m->context);\n"
            "    free(old);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_create"],
    ),
    "__btrc_mutex_val_destroy": HelperDef(
        c_source=(
            "static void __btrc_mutex_val_destroy(__btrc_mutex_val_t* m) {\n"
            "    if (!m) return;\n"
            "    int err = pthread_mutex_lock(&m->lock);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: mutex lock failed (%d)\\n", err); exit(1); }\n'
            "    void* old = m->value;\n"
            "    m->value = NULL;\n"
            "    err = pthread_mutex_unlock(&m->lock);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: mutex unlock failed (%d)\\n", err); exit(1); }\n'
            "    err = pthread_mutex_destroy(&m->lock);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: mutex destroy failed (%d)\\n", err); exit(1); }\n'
            "    if (m->release) m->release(*(void**)old, m->context);\n"
            "    free(old);\n"
            "    free(m->context);\n"
            "    free(m);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_create"],
    ),
}


__all__ = ["MUTEXES"]
