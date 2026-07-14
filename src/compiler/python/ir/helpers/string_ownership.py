"""Process-wide ownership registry for heap-backed ``char*`` strings."""

from .core import HelperDef

_REGISTRY_SOURCE = r"""
typedef struct __btrc_string_entry {
    char* value;
    size_t references;
    struct __btrc_string_entry* next;
} __btrc_string_entry;

static atomic_flag __btrc_string_lock = ATOMIC_FLAG_INIT;
static __btrc_string_entry* __btrc_string_inline_buckets[64] = {0};
static __btrc_string_entry** __btrc_string_buckets =
    __btrc_string_inline_buckets;
static size_t __btrc_string_bucket_count = 64;
static size_t __btrc_string_entry_count = 0;

static inline void __btrc_string_registry_lock(void) {
    unsigned int delay = 1;
    while (atomic_flag_test_and_set_explicit(
            &__btrc_string_lock, memory_order_acquire)) {
        for (unsigned int spin = 0; spin < delay; spin++) {
            atomic_signal_fence(memory_order_seq_cst);
        }
        if (delay < 1024) delay *= 2;
    }
}

static inline void __btrc_string_registry_unlock(void) {
    atomic_flag_clear_explicit(&__btrc_string_lock, memory_order_release);
}

static inline size_t __btrc_string_hash(char* value, size_t buckets) {
    uintptr_t bits = (uintptr_t)(void*)value;
    bits ^= bits >> 17;
    bits *= (uintptr_t)0xed5ad4bbU;
    bits ^= bits >> 11;
    return (size_t)(bits % (uintptr_t)buckets);
}

static inline __btrc_string_entry** __btrc_string_slot(char* value) {
    size_t index = __btrc_string_hash(value, __btrc_string_bucket_count);
    __btrc_string_entry** slot = &__btrc_string_buckets[index];
    while (*slot && (*slot)->value != value) slot = &(*slot)->next;
    return slot;
}
""".strip()

_REGISTRY_RESIZE_SOURCE = r"""
static inline void __btrc_string_registry_resize(size_t capacity) {
    __btrc_string_entry** old_buckets = __btrc_string_buckets;
    size_t old_capacity = __btrc_string_bucket_count;
    __btrc_string_entry** buckets = (__btrc_string_entry**)
        __btrc_safe_calloc(capacity, sizeof(__btrc_string_entry*));
    for (size_t index = 0; index < old_capacity; index++) {
        __btrc_string_entry* entry = old_buckets[index];
        while (entry) {
            __btrc_string_entry* next = entry->next;
            size_t target = __btrc_string_hash(entry->value, capacity);
            entry->next = buckets[target];
            buckets[target] = entry;
            entry = next;
        }
    }
    if (old_buckets == __btrc_string_inline_buckets) {
        memset(__btrc_string_inline_buckets, 0,
            sizeof(__btrc_string_inline_buckets));
    } else {
        free(old_buckets);
    }
    __btrc_string_buckets = buckets;
    __btrc_string_bucket_count = capacity;
}
""".strip()

_LIVE_COUNT_SOURCE = r"""
static inline size_t __btrc_string_live_count(void) {
    __btrc_string_registry_lock();
    size_t result = __btrc_string_entry_count;
    __btrc_string_registry_unlock();
    return result;
}
""".strip()


STRING_OWNERSHIP = {
    "__btrc_string_registry": HelperDef(
        c_source=_REGISTRY_SOURCE,
        required_headers=["stdatomic.h"],
    ),
    "__btrc_string_registry_resize": HelperDef(
        c_source=_REGISTRY_RESIZE_SOURCE,
        depends_on=["__btrc_string_registry", "__btrc_safe_calloc"],
    ),
    "__btrc_string_adopt": HelperDef(
        depends_on=[
            "__btrc_string_registry_resize",
            "__btrc_safe_realloc",
        ],
        c_source=r"""
static inline char* __btrc_string_adopt(char* value) {
    if (!value) return NULL;
    __btrc_string_entry* candidate = (__btrc_string_entry*)
        __btrc_safe_realloc(NULL, sizeof(__btrc_string_entry));
    candidate->value = value;
    candidate->references = 1;
    candidate->next = NULL;

    __btrc_string_registry_lock();
    __btrc_string_entry** slot = __btrc_string_slot(value);
    if (*slot) {
        __btrc_string_registry_unlock();
        free(candidate);
        return value;
    }
    if (__btrc_string_entry_count >= __btrc_string_bucket_count
            - __btrc_string_bucket_count / 4) {
        if (__btrc_string_bucket_count > SIZE_MAX / 2) {
            __btrc_string_registry_unlock();
            fprintf(stderr, "btrc: string registry overflow\n");
            exit(1);
        }
        __btrc_string_registry_resize(__btrc_string_bucket_count * 2);
        slot = __btrc_string_slot(value);
    }
    candidate->next = *slot;
    *slot = candidate;
    __btrc_string_entry_count++;
    __btrc_string_registry_unlock();
    return value;
}
""".strip(),
    ),
    "__btrc_string_retain": HelperDef(
        depends_on=["__btrc_string_registry"],
        c_source=r"""
static inline char* __btrc_string_retain(char* value) {
    if (!value) return NULL;
    __btrc_string_registry_lock();
    if (__btrc_string_bucket_count != 0) {
        __btrc_string_entry* entry = *__btrc_string_slot(value);
        if (entry) {
            if (entry->references == SIZE_MAX) {
                __btrc_string_registry_unlock();
                fprintf(stderr, "btrc: string reference overflow\n");
                exit(1);
            }
            entry->references++;
        }
    }
    __btrc_string_registry_unlock();
    return value;
}
""".strip(),
    ),
    "__btrc_string_release": HelperDef(
        depends_on=["__btrc_string_registry"],
        c_source=r"""
static inline void __btrc_string_release(char* value) {
    if (!value) return;
    __btrc_string_entry* removed = NULL;
    __btrc_string_entry** retired_buckets = NULL;
    __btrc_string_registry_lock();
    __btrc_string_entry** slot = __btrc_string_slot(value);
    __btrc_string_entry* entry = *slot;
    if (entry && entry->references > 1) {
        entry->references--;
    } else if (entry) {
        *slot = entry->next;
        removed = entry;
        __btrc_string_entry_count--;
        if (__btrc_string_entry_count == 0
                && __btrc_string_buckets != __btrc_string_inline_buckets) {
            retired_buckets = __btrc_string_buckets;
            __btrc_string_buckets = __btrc_string_inline_buckets;
            __btrc_string_bucket_count = 64;
            memset(__btrc_string_inline_buckets, 0,
                sizeof(__btrc_string_inline_buckets));
        }
    }
    __btrc_string_registry_unlock();
    if (removed) {
        free(removed->value);
        free(removed);
    }
    free(retired_buckets);
}
""".strip(),
    ),
    "__btrc_string_release_cleanup": HelperDef(
        depends_on=["__btrc_string_release"],
        c_source=(
            "static inline void __btrc_string_release_cleanup(void* value) {\n"
            "    __btrc_string_release((char*)value);\n"
            "}"
        ),
    ),
    "__btrc_string_live_count": HelperDef(
        depends_on=["__btrc_string_registry"],
        c_source=_LIVE_COUNT_SOURCE,
    ),
}


__all__ = ["STRING_OWNERSHIP"]
