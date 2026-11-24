#ifndef BTRC_GUI_FREETYPE_H
#define BTRC_GUI_FREETYPE_H

/* Declarations, ABI and the selected FT_LOAD_* macro constants all come from
 * the installed FreeType SDK; the header reader imports object-like macros. */
#include <ft2build.h>
#include FT_FREETYPE_H

/* FT_New_Memory_Face retains its buffer for the full life of the face.
 * This owner copies the call-scoped BTRC bytes. The face releases its
 * native claim before releasing the buffer. */
#include <stdlib.h>
#include <string.h>

typedef struct BtrcFreeTypeMemoryRec {
    long length;
    unsigned char bytes[];
} *BtrcFreeTypeMemory;

static inline int btrcFreeTypeCopyMemory(const unsigned char *data, long length, BtrcFreeTypeMemory *memory) {
    *memory = NULL;
    if (length < 1 || length > 16777216L) return 1;
    BtrcFreeTypeMemory copy = malloc(sizeof(*copy) + (size_t)length);
    if (!copy) return 1;
    copy->length = length;
    memcpy(copy->bytes, data, (size_t)length);
    *memory = copy;
    return 0;
}

static inline void btrcFreeTypeReleaseMemory(BtrcFreeTypeMemory memory) {
    free(memory);
}

static inline FT_Error btrcFreeTypeOpenMemoryFace(FT_Library library, BtrcFreeTypeMemory memory, FT_Face *face) {
    return FT_New_Memory_Face(library, memory->bytes, memory->length, 0, face);
}

#endif
