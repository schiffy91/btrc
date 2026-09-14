#include <stdlib.h>

static int remaining = -1;

void guiFailAllocation(int countdown) { remaining = countdown; }

void* guiSurfaceCalloc(size_t count, size_t size) {
    if (remaining == 0) {
        remaining = -1;
        return NULL;
    }
    if (remaining > 0) { remaining--; }
    return calloc(count, size);
}
