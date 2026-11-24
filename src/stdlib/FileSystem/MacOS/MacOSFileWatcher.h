#ifndef BTRC_FILESYSTEM_MACOS_FILE_WATCHER_H
#define BTRC_FILESYSTEM_MACOS_FILE_WATCHER_H

#include <stddef.h>
#include <stdint.h>

typedef struct BtrcMacOSFileWatcher BtrcMacOSFileWatcher;

BtrcMacOSFileWatcher *btrcMacOSWatcherOpen(const char *rootPath, int latencyMs);
void btrcMacOSWatcherClose(BtrcMacOSFileWatcher *watcher);

/* Wait up to timeoutMs for at least one event; returns queued event count. */
int btrcMacOSWatcherWaitCount(BtrcMacOSFileWatcher *watcher, int timeoutMs);

/* Pop the next event into caller buffers; returns 1 if popped, 0 if empty.
 * kind: 0=created, 1=modified, 2=removed, 3=renamed, 4=rescan. */
int btrcMacOSWatcherPop(BtrcMacOSFileWatcher *watcher, int *outKind, int *outIsDir, char *pathBuf, size_t pathBufCap, size_t *outLen);

#endif
