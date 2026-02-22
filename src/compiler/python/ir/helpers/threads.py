"""Threading runtime helpers -- pthread wrappers for spawn/join."""

from .core import HelperDef

THREADS = {
    "__btrc_thread_spawn": HelperDef(
        c_source=(
            "typedef struct {\n"
            "    void* (*fn)(void*);\n"
            "    void* arg;\n"
            "    void* result;\n"
            "    pthread_t handle;\n"
            "} __btrc_thread_t;\n"
            "\n"
            "static void* __btrc_thread_wrapper(void* raw) {\n"
            "    __btrc_thread_t* t = (__btrc_thread_t*)raw;\n"
            "    t->result = t->fn(t->arg);\n"
            "    return NULL;\n"
            "}\n"
            "\n"
            "static __btrc_thread_t* __btrc_thread_spawn(void* (*fn)(void*), void* arg) {\n"
            "    __btrc_thread_t* t = (__btrc_thread_t*)malloc(sizeof(__btrc_thread_t));\n"
            '    if (!t) { fprintf(stderr, "btrc: thread alloc failed\\n"); exit(1); }\n'
            "    t->fn = fn;\n"
            "    t->arg = arg;\n"
            "    t->result = NULL;\n"
            "    int err = pthread_create(&t->handle, NULL, __btrc_thread_wrapper, t);\n"
            '    if (err != 0) { fprintf(stderr, "btrc: pthread_create failed\\n"); free(t); exit(1); }\n'
            "    return t;\n"
            "}"
        ),
    ),
    "__btrc_thread_join": HelperDef(
        c_source=(
            "static void* __btrc_thread_join(__btrc_thread_t* t) {\n"
            "    pthread_join(t->handle, NULL);\n"
            "    return t->result;\n"
            "}"
        ),
        depends_on=["__btrc_thread_spawn"],
    ),
    "__btrc_thread_free": HelperDef(
        c_source=(
            "static void __btrc_thread_free(__btrc_thread_t* t) {\n"
            "    free(t);\n"
            "}"
        ),
        depends_on=["__btrc_thread_spawn"],
    ),
    "__btrc_mutex_val_create": HelperDef(
        c_source=(
            "typedef struct {\n"
            "    pthread_mutex_t lock;\n"
            "    void* value;\n"
            "} __btrc_mutex_val_t;\n"
            "\n"
            "static __btrc_mutex_val_t* __btrc_mutex_val_create(void* initial) {\n"
            "    __btrc_mutex_val_t* m = (__btrc_mutex_val_t*)malloc(sizeof(__btrc_mutex_val_t));\n"
            '    if (!m) { fprintf(stderr, "btrc: mutex alloc failed\\n"); exit(1); }\n'
            '    if (pthread_mutex_init(&m->lock, NULL) != 0) { fprintf(stderr, "btrc: mutex init failed\\n"); free(m); exit(1); }\n'
            "    m->value = initial;\n"
            "    return m;\n"
            "}"
        ),
    ),
    "__btrc_mutex_val_get": HelperDef(
        c_source=(
            "static void* __btrc_mutex_val_get(__btrc_mutex_val_t* m) {\n"
            "    pthread_mutex_lock(&m->lock);\n"
            "    void* v = m->value;\n"
            "    pthread_mutex_unlock(&m->lock);\n"
            "    return v;\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_create"],
    ),
    "__btrc_mutex_val_set": HelperDef(
        c_source=(
            "static void __btrc_mutex_val_set(__btrc_mutex_val_t* m, void* val) {\n"
            "    pthread_mutex_lock(&m->lock);\n"
            "    m->value = val;\n"
            "    pthread_mutex_unlock(&m->lock);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_create"],
    ),
    "__btrc_mutex_val_destroy": HelperDef(
        c_source=(
            "static void __btrc_mutex_val_destroy(__btrc_mutex_val_t* m) {\n"
            "    pthread_mutex_destroy(&m->lock);\n"
            "    free(m);\n"
            "}"
        ),
        depends_on=["__btrc_mutex_val_create"],
    ),
}
