/* ARC witness for test_c_compatibility_declarator_arc.py. The test inserts
 * arc_witness_note calls into the generated C's ARC and string ownership
 * helpers (its WITNESSED_HELPERS lists each one and the kind it counts); the
 * program reads the counts back through arc_witness_count. A null operand is
 * a no-op in the runtime, so it is not counted. The witnessed programs are
 * single-threaded. */

#include <stddef.h>

enum { WITNESS_KINDS = 7 };

static long witness_counts[WITNESS_KINDS];

void arc_witness_note(int kind, const void* object) {
    if (object == NULL || kind < 0 || kind >= WITNESS_KINDS) return;
    witness_counts[kind]++;
}

long arc_witness_count(int kind) {
    if (kind < 0 || kind >= WITNESS_KINDS) return -1;
    return witness_counts[kind];
}
