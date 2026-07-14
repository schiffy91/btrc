"""ARC release, replacement, and suspect-removal atoms."""

from .core import HelperDef

ARC_RELEASE_HELPERS = {
    "__btrc_forget_suspect": HelperDef(
        c_source=r"""static void __btrc_forget_suspect(void* obj) {
    if (!obj || __btrc_suspect_key_cap == 0) return;
    size_t mask = (size_t)__btrc_suspect_key_cap - 1;
    size_t hole = __btrc_ptr_hash(obj) & mask;
    while (__btrc_suspect_keys[hole]
            && __btrc_suspect_keys[hole] != obj)
        hole = (hole + 1) & mask;
    if (!__btrc_suspect_keys[hole]) return;
    __btrc_suspect_keys[hole] = NULL;
    size_t scan = (hole + 1) & mask;
    while (__btrc_suspect_keys[scan]) {
        void* displaced = __btrc_suspect_keys[scan];
        __btrc_suspect_keys[scan] = NULL;
        size_t target = __btrc_ptr_hash(displaced) & mask;
        while (__btrc_suspect_keys[target])
            target = (target + 1) & mask;
        __btrc_suspect_keys[target] = displaced;
        scan = (scan + 1) & mask;
    }
    for (int i = 0; i < __btrc_suspect_count; i++) {
        if (__btrc_suspects[i] != obj) continue;
        int last = --__btrc_suspect_count;
        if (i != last) {
            __btrc_suspects[i] = __btrc_suspects[last];
            __btrc_visit_table[i] = __btrc_visit_table[last];
            __btrc_destroy_table[i] = __btrc_destroy_table[last];
        }
        return;
    }
}""",
        depends_on=["__btrc_suspect_state", "__btrc_ptr_hash"],
    ),
    "__btrc_arc_release_impl": HelperDef(
        c_source=r"""static inline int __btrc_arc_release_impl(
        void* object, const __btrc_arc_type* fallback,
        int edge, void* replacement) {
    if (!object) return 0;
    __btrc_arc_validate(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    if (!type || !type->destroy) { fprintf(stderr, "btrc: untyped managed release\n"); exit(1); }
    if (header->state != __BTRC_ARC_LIVE) {
        fprintf(stderr, "btrc: release of non-live managed object\n");
        exit(1);
    }
    if (header->rc <= 0 || (edge && header->edge_rc <= 0)) { fprintf(stderr, "btrc: reference count underflow\n"); exit(1); }
    if (edge) {
        /* The slot-specific unlink atom invalidated only the removed owner. */
        (void)replacement;
        header->edge_rc--;
    }
    header->rc--;
    if (header->rc == 0) {
        if (header->edge_rc != 0 || header->incoming != NULL) {
            fprintf(stderr, "btrc: terminal object retained an incoming edge\n");
            exit(1);
        }
        __btrc_forget_suspect(object);
        __btrc_arc_enqueue_locked(object);
        return 0;
    }
    __btrc_arc_validate(object);
    if (type->visit && header->rc == header->edge_rc
            && !__btrc_arc_reverse_proves_live(object))
        __btrc_suspect_locked(object, type->visit, type->destroy);
    return 0;
}""",
        depends_on=[
            "__btrc_suspect_locked",
            "__btrc_arc_reverse_proves_live",
            "__btrc_forget_suspect",
            "__btrc_arc_deferred_state",
        ],
    ),
    "__btrc_arc_replace_edge": HelperDef(
        c_source=r"""static inline int __btrc_arc_replace_edge(
        volatile void* slot_storage, __btrc_arc_slot_access_fn access,
        void* replacement, void* owner,
        const __btrc_arc_type* fallback, int adopt) {
    if (!slot_storage || !access || !owner) {
        fprintf(stderr, "btrc: managed edge replacement requires a slot and owner\n");
        exit(1);
    }
    __btrc_arc_lock_mutation();
    void* object = access(slot_storage, NULL, NULL, 0);
    __btrc_arc_validate(owner);
    __btrc_arc_header* owner_header = __btrc_arc_header_of(owner);
    const __btrc_arc_type* error_type = owner_header->type;
    int invalid_publication = replacement
        && owner_header->state != __BTRC_ARC_LIVE;
    if (replacement) {
        __btrc_arc_validate(replacement);
        if (__btrc_arc_header_of(replacement)->state
                != __BTRC_ARC_LIVE) {
            invalid_publication = 1;
            error_type = __btrc_arc_header_of(replacement)->type;
        }
    }
    if (invalid_publication) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
        return -1;
    }
    if (!replacement && owner_header->state != __BTRC_ARC_LIVE
            && owner_header->state != __BTRC_ARC_DESTROYING) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
        return -1;
    }
    if (object == replacement) {
        if (replacement && adopt)
            __btrc_arc_release_impl(replacement, fallback, 0, NULL);
        __btrc_arc_unlock_mutation();
        __btrc_arc_drain_deferred(0);
        return 0;
    }
    if (access(slot_storage, object, replacement, 1) != object) {
        __btrc_arc_unlock_mutation();
        fprintf(stderr, "btrc: managed edge changed during transaction\n");
        exit(1);
    }
    if (object) {
        __btrc_arc_validate(object);
        __btrc_arc_unregister_incoming(object, owner);
    }
    if (replacement) {
        __btrc_arc_header* next = __btrc_arc_header_of(replacement);
        if (adopt) {
            if (next->edge_rc == INT_MAX || next->edge_rc >= next->rc) {
                fprintf(stderr, "btrc: invalid owned-edge adoption\n");
                exit(1);
            }
            __btrc_arc_register_incoming(replacement, owner);
            next->edge_rc++;
        } else {
            if (next->rc == INT_MAX || next->edge_rc == INT_MAX) {
                fprintf(stderr, "btrc: reference count overflow\n");
                exit(1);
            }
            __btrc_arc_register_incoming(replacement, owner);
            next->rc++;
            next->edge_rc++;
        }
        __btrc_arc_validate(replacement);
    }
    if (object)
        __btrc_arc_release_impl(object, fallback, 1, replacement);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}""",
        depends_on=[
            "__btrc_arc_release_impl",
            "__btrc_arc_register_incoming",
            "__btrc_arc_unregister_incoming",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_drain",
        ],
    ),
    "__btrc_arc_release": HelperDef(
        c_source=r"""static inline int __btrc_arc_release(
        void* object, const __btrc_arc_type* type) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_release_impl(object, type, 0, NULL);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}""",
        depends_on=[
            "__btrc_arc_release_impl",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_drain",
        ],
    ),
    "__btrc_arc_release_edge": HelperDef(
        c_source=r"""static inline int __btrc_arc_release_edge(
        void* object, const __btrc_arc_type* type, void* replacement) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_release_impl(object, type, 1, replacement);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}""",
        depends_on=[
            "__btrc_arc_release_impl",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_drain",
        ],
    ),
    "__btrc_arc_release_acyclic": HelperDef(
        c_source=r"""static inline int __btrc_arc_release_acyclic(
        void* object, const __btrc_arc_type* type) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* runtime_type = __btrc_arc_type_of(object, type);
    if (!runtime_type || !runtime_type->destroy) { fprintf(stderr, "btrc: untyped managed release\n"); exit(1); }
    if (header->state != __BTRC_ARC_LIVE || header->rc <= 0) { fprintf(stderr, "btrc: reference count underflow\n"); exit(1); }
    header->rc--;
    if (header->rc == 0) {
        if (header->edge_rc != 0 || header->incoming != NULL) {
            fprintf(stderr, "btrc: terminal object retained an incoming edge\n");
            exit(1);
        }
        __btrc_arc_enqueue_locked(object);
    } else {
        __btrc_arc_validate(object);
    }
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}""",
        depends_on=[
            "__btrc_arc_type_of",
            "__btrc_arc_validate",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_drain",
        ],
    ),
    "__btrc_arc_invalidate": HelperDef(
        c_source=r"""static inline int __btrc_arc_invalidate(void* object) {
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    __btrc_arc_unlock_mutation();
    return 0;
}""",
        depends_on=["__btrc_arc_validate", "__btrc_arc_mutation_lock"],
    ),
}

__all__ = ["ARC_RELEASE_HELPERS"]
