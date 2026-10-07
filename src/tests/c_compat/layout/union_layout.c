/* C mirror for UnionLayout.btrc (C row 9). The btrc program declares the
   same members; these report the C compiler's layout of the mirror as size_t,
   so the two agree only if btrc emits the union exactly as written. */
#include <stddef.h>

union MirrorValue {
    int integer;
    double real;
    char bytes[12];
};

struct MirrorTagged {
    char tag;
    union MirrorValue value;
    short flag;
};

union MirrorSmall {
    char letter;
    short half;
};

size_t unionLayoutValueSize(void) { return sizeof(union MirrorValue); }
size_t unionLayoutValueAlignment(void) { return _Alignof(union MirrorValue); }
size_t unionLayoutTaggedSize(void) { return sizeof(struct MirrorTagged); }
size_t unionLayoutValueOffset(void) { return offsetof(struct MirrorTagged, value); }
size_t unionLayoutFlagOffset(void) { return offsetof(struct MirrorTagged, flag); }
size_t unionLayoutSmallSize(void) { return sizeof(union MirrorSmall); }
