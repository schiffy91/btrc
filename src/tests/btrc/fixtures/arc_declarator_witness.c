/* ARC witness for test_c_compatibility_declarator_arc.py. The test inserts
 * one arc_witness_note call at the top of each retain, release and edge-store
 * helper in the generated C; the program reads the counts back through
 * arc_witness_count. A null operand is a no-op in the runtime, so it is not
 * counted. The witnessed programs are single-threaded. */

#include <stddef.h>

enum { WITNESS_KINDS = 5 };

static long witness_counts[WITNESS_KINDS];

void arc_witness_note(int kind, const void* object) {
    if (object == NULL || kind < 0 || kind >= WITNESS_KINDS) return;
    witness_counts[kind]++;
}

long arc_witness_count(int kind) {
    if (kind < 0 || kind >= WITNESS_KINDS) return -1;
    return witness_counts[kind];
}
