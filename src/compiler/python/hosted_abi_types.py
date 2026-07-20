"""Ordinary-identifier typedefs owned by automatically included headers."""

_FIXED_WIDTH_TYPES = {
    *(f"{prefix}{width}_t" for prefix in ("int", "uint") for width in (8, 16, 32, 64)),
    *(
        f"{prefix}_{family}{width}_t"
        for prefix in ("int", "uint")
        for family in ("least", "fast")
        for width in (8, 16, 32, 64)
    ),
    "intptr_t",
    "uintptr_t",
    "intmax_t",
    "uintmax_t",
}

_ATOMIC_TYPES = {
    "atomic_flag",
    "memory_order",
    *(
        f"atomic_{name}"
        for name in (
            "bool",
            "char",
            "schar",
            "uchar",
            "short",
            "ushort",
            "int",
            "uint",
            "long",
            "ulong",
            "llong",
            "ullong",
            "char16_t",
            "char32_t",
            "wchar_t",
            "intptr_t",
            "uintptr_t",
            "size_t",
            "ptrdiff_t",
            "intmax_t",
            "uintmax_t",
            *(
                f"{prefix}_{family}{width}_t"
                for prefix in ("int", "uint")
                for family in ("least", "fast")
                for width in (8, 16, 32, 64)
            ),
        )
    ),
}

_PTHREAD_TYPES = {
    "pthread_t",
    "pthread_attr_t",
    "pthread_barrier_t",
    "pthread_barrierattr_t",
    "pthread_cond_t",
    "pthread_condattr_t",
    "pthread_key_t",
    "pthread_mutex_t",
    "pthread_mutexattr_t",
    "pthread_once_t",
    "pthread_rwlock_t",
    "pthread_rwlockattr_t",
    "pthread_spinlock_t",
}

HOSTED_TYPE_NAMES = frozenset(
    {
        "FILE",
        "fpos_t",
        "size_t",
        "ptrdiff_t",
        "max_align_t",
        "wchar_t",
        "wint_t",
        "ssize_t",
        "div_t",
        "ldiv_t",
        "lldiv_t",
        "jmp_buf",
        "sigjmp_buf",
        *_FIXED_WIDTH_TYPES,
        *_ATOMIC_TYPES,
        *_PTHREAD_TYPES,
    }
)

HOSTED_OBJECT_NAMES = frozenset({"stdin", "stdout", "stderr", "errno"})

__all__ = ["HOSTED_OBJECT_NAMES", "HOSTED_TYPE_NAMES"]
