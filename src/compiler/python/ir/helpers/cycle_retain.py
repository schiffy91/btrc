"""Live-object retain and incoming-edge ARC atoms."""

from .core import HelperDef

ARC_RETAIN_HELPERS = {
    "__btrc_arc_retain": HelperDef(
        c_source=r"""static inline int __btrc_arc_retain(void* object) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* type = header->type;
    if (header->state != __BTRC_ARC_LIVE) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            type, "cannot retain destroying managed object");
    }
    if (header->rc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
    if (header->live_witness == object) header->live_witness = NULL;
    header->rc++;
    __btrc_arc_validate(object);
    __btrc_arc_unlock_mutation();
    return 0;
}""",
        depends_on=[
            "__btrc_arc_validate",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_deferred_state",
        ],
    ),
    "__btrc_arc_retain_edge": HelperDef(
        c_source=r"""static inline int __btrc_arc_retain_edge(
        void* object, void* owner) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    if (owner) __btrc_arc_validate(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* error_type = header->type;
    if (header->state != __BTRC_ARC_LIVE
            || (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE)) {
        if (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE)
            error_type = __btrc_arc_header_of(owner)->type;
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
    }
    if (header->rc == INT_MAX || header->edge_rc == INT_MAX) { fprintf(stderr, "btrc: reference count overflow\n"); exit(1); }
    __btrc_arc_register_incoming(object, owner);
    header->rc++;
    header->edge_rc++;
    __btrc_arc_validate(object);
    __btrc_arc_unlock_mutation();
    return 0;
}""",
        depends_on=[
            "__btrc_arc_register_incoming",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_deferred_state",
        ],
    ),
    "__btrc_arc_adopt_edge": HelperDef(
        c_source=r"""static inline int __btrc_arc_adopt_edge(
        void* object, void* owner) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    if (owner) __btrc_arc_validate(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    const __btrc_arc_type* error_type = header->type;
    if (header->state != __BTRC_ARC_LIVE
            || (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE)) {
        if (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE)
            error_type = __btrc_arc_header_of(owner)->type;
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            error_type, "cannot retain destroying managed object");
    }
    if (header->edge_rc == INT_MAX || header->edge_rc >= header->rc) { fprintf(stderr, "btrc: invalid owned-edge adoption\n"); exit(1); }
    __btrc_arc_register_incoming(object, owner);
    header->edge_rc++;
    __btrc_arc_validate(object);
    __btrc_arc_unlock_mutation();
    return 0;
}""",
        depends_on=[
            "__btrc_arc_register_incoming",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_deferred_state",
        ],
    ),
    "__btrc_arc_unlink_edge": HelperDef(
        c_source=r"""static inline int __btrc_arc_unlink_edge(
        void* object, void* owner) {
    if (!object) return 0;
    __btrc_arc_lock_mutation();
    __btrc_arc_validate(object);
    if (owner) __btrc_arc_validate(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->state != __BTRC_ARC_LIVE
            || (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE
                && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_DESTROYING)) {
        const __btrc_arc_type* type = header->type;
        if (owner && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_LIVE
                && __btrc_arc_header_of(owner)->state
                != __BTRC_ARC_DESTROYING)
            type = __btrc_arc_header_of(owner)->type;
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            type, "cannot retain destroying managed object");
    }
    __btrc_arc_unregister_incoming(object, owner);
    __btrc_arc_unlock_mutation();
    return 0;
}""",
        depends_on=[
            "__btrc_arc_unregister_incoming",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_deferred_state",
        ],
    ),
}

__all__ = ["ARC_RETAIN_HELPERS"]
