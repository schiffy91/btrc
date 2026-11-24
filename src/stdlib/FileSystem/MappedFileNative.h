#ifndef BTRC_FILESYSTEM_MAPPED_FILE_NATIVE_H
#define BTRC_FILESYSTEM_MAPPED_FILE_NATIVE_H

#include <stddef.h>
#include <stdint.h>

typedef struct BtrcMappedRegion BtrcMappedRegion;

/* Open a read-only memory-mapped view of `path` (handles 0-byte files cleanly). */
BtrcMappedRegion *btrcMappedFileOpen(const char *path);
void btrcMappedFileClose(BtrcMappedRegion *region);
long long btrcMappedFileSize(const BtrcMappedRegion *region);
const unsigned char *btrcMappedFileData(const BtrcMappedRegion *region);
int btrcMappedFileCopy(const BtrcMappedRegion *region, long long offset, void *dst, size_t byteCount);
long long btrcMappedFileFindPair(const BtrcMappedRegion *region, long long start, long long end, int b0, int b1);
int btrcMappedFileMatches(const BtrcMappedRegion *region, long long offset, const char *text, size_t len);

#endif
