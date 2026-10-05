/* C mirror of the aggregates c_compat/FlexibleArrayLayout.btrc declares.
   Imported as a raw C source, it is spliced into the same translation unit,
   so each mirror carries its own tag; the btrc program compares its own
   sizeof and member offsets with these, which the C compiler computed for
   the C spelling of the same members (C11 6.7.2.1p18). */
#include <stddef.h>

struct MirrorInts { int count; int data[]; };
struct MirrorCharDoubles { char c; double d[]; };
struct MirrorTail { double x; char c; char d[]; };
struct MirrorPair { short a; long long b; };
struct MirrorPairs { char tag; struct MirrorPair items[]; };
struct MirrorPointers { char tag; void* items[]; };

size_t mirrorIntsSize(void) { return sizeof(struct MirrorInts); }
size_t mirrorIntsOffset(void) { return offsetof(struct MirrorInts, data); }
size_t mirrorCharDoublesSize(void) { return sizeof(struct MirrorCharDoubles); }
size_t mirrorCharDoublesOffset(void) { return offsetof(struct MirrorCharDoubles, d); }
size_t mirrorTailSize(void) { return sizeof(struct MirrorTail); }
size_t mirrorTailOffset(void) { return offsetof(struct MirrorTail, d); }
size_t mirrorPairsSize(void) { return sizeof(struct MirrorPairs); }
size_t mirrorPairsOffset(void) { return offsetof(struct MirrorPairs, items); }
size_t mirrorPointersSize(void) { return sizeof(struct MirrorPointers); }
size_t mirrorPointersOffset(void) { return offsetof(struct MirrorPointers, items); }
