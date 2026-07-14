"""Transactional managed deletion and partial-construction teardown."""

from .core import HelperDef

ARC_LIFECYCLE_HELPERS = {
    "__btrc_arc_destroy_slot": HelperDef(
        c_source=r"""static inline int __btrc_arc_destroy_slot(
        volatile void* slot_storage, __btrc_arc_slot_access_fn access,
        const __btrc_arc_type* fallback) {
    if (!slot_storage || !access) return 0;
    __btrc_arc_lock_mutation();
    void* object = access(slot_storage, NULL, NULL, 0);
    if (!object) {
        __btrc_arc_unlock_mutation();
        return 0;
    }
    __btrc_arc_validate(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    if (!type || !type->destroy) { fprintf(stderr, "btrc: untyped managed destroy\n"); exit(1); }
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    if (header->state != __BTRC_ARC_LIVE || header->rc != 1
            || header->edge_rc != 0 || header->incoming != NULL) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            type, "cannot delete shared managed object");
    }
    if (access(slot_storage, object, NULL, 1) != object) {
        __btrc_arc_unlock_mutation();
        fprintf(stderr, "btrc: managed delete slot changed during transaction\n");
        exit(1);
    }
    header->rc = 0;
    header->live_witness = NULL;
    __btrc_forget_suspect(object);
    __btrc_arc_enqueue_locked(object);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}""",
        depends_on=[
            "__btrc_forget_suspect",
            "__btrc_arc_type_of",
            "__btrc_arc_validate",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_deferred_state",
            "__btrc_arc_drain",
        ],
    ),
    "__btrc_arc_destroy_edge": HelperDef(
        c_source=r"""static inline int __btrc_arc_destroy_edge(
        volatile void* slot_storage, __btrc_arc_slot_access_fn access, void* owner,
        const __btrc_arc_type* fallback) {
    if (!slot_storage || !access || !owner) return 0;
    __btrc_arc_lock_mutation();
    void* object = access(slot_storage, NULL, NULL, 0);
    if (!object) {
        __btrc_arc_unlock_mutation();
        return 0;
    }
    __btrc_arc_validate(owner);
    __btrc_arc_validate(object);
    const __btrc_arc_type* type = __btrc_arc_type_of(object, fallback);
    __btrc_arc_header* owner_header = __btrc_arc_header_of(owner);
    __btrc_arc_header* header = __btrc_arc_header_of(object);
    int owner_valid = owner_header->state == __BTRC_ARC_LIVE
        || owner_header->state == __BTRC_ARC_DESTROYING;
    int unique = header->state == __BTRC_ARC_LIVE
        && header->rc == 1 && header->edge_rc == 1
        && header->incoming && header->incoming->owner == owner
        && header->incoming->next == NULL;
    if (!owner_valid || !unique) {
        __btrc_arc_unlock_mutation();
        __btrc_arc_raise_unlocked(
            type, "cannot delete shared managed object");
    }
    if (access(slot_storage, object, NULL, 1) != object) {
        __btrc_arc_unlock_mutation();
        fprintf(stderr, "btrc: managed delete slot changed during transaction\n");
        exit(1);
    }
    __btrc_arc_unregister_incoming(object, owner);
    header->rc = 0;
    header->edge_rc = 0;
    header->live_witness = NULL;
    __btrc_forget_suspect(object);
    __btrc_arc_enqueue_locked(object);
    __btrc_arc_unlock_mutation();
    __btrc_arc_drain_deferred(0);
    return 0;
}""",
        depends_on=[
            "__btrc_forget_suspect",
            "__btrc_arc_unregister_incoming",
            "__btrc_arc_type_of",
            "__btrc_arc_validate",
            "__btrc_arc_mutation_lock",
            "__btrc_arc_deferred_state",
            "__btrc_arc_drain",
        ],
    ),
}

__all__ = ["ARC_LIFECYCLE_HELPERS"]
