#ifndef BTRC_FILESYSTEM_LINUX_FILE_WATCHER_H
#define BTRC_FILESYSTEM_LINUX_FILE_WATCHER_H

#include <stddef.h>
#include <stdint.h>

typedef struct BtrcLinuxFileWatcher BtrcLinuxFileWatcher;

BtrcLinuxFileWatcher *btrcLinuxWatcherOpen(const char *rootPath);
void btrcLinuxWatcherClose(BtrcLinuxFileWatcher *watcher);
int btrcLinuxWatcherWaitCount(BtrcLinuxFileWatcher *watcher, int timeoutMs);
int btrcLinuxWatcherPop(BtrcLinuxFileWatcher *watcher, int *outKind, int *outIsDir, char *pathBuf, size_t pathBufCap, size_t *outLen);

#endif
