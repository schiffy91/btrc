#include <stddef.h>

struct MirrorEnvelope {
    char tag;
    union {
        struct {
            int count;
            short values[3];
        };
        double real;
    };
    char tail;
};

struct MirrorAlignedEnvelope {
    char prefix;
    struct MirrorEnvelope value;
};

size_t anonymousEnvelopeSize(void) { return sizeof(struct MirrorEnvelope); }
size_t anonymousEnvelopeAlignment(void) { return _Alignof(struct MirrorEnvelope); }
size_t anonymousEnvelopeCountOffset(void) { return offsetof(struct MirrorEnvelope, count); }
size_t anonymousEnvelopeValuesOffset(void) { return offsetof(struct MirrorEnvelope, values); }
size_t anonymousEnvelopeRealOffset(void) { return offsetof(struct MirrorEnvelope, real); }
size_t anonymousEnvelopeTailOffset(void) { return offsetof(struct MirrorEnvelope, tail); }
size_t anonymousAlignedEnvelopeOffset(void) { return offsetof(struct MirrorAlignedEnvelope, value); }
