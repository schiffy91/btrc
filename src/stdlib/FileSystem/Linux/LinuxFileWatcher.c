#include "LinuxFileWatcher.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct BtrcInotifyWatch {
	int wd;
	char *dirPath;
} BtrcInotifyWatch;

typedef struct BtrcLinuxWatchItem {
	int kind;
	int isDir;
	char *path;
} BtrcLinuxWatchItem;

struct BtrcLinuxFileWatcher {
	int fd;
	char *rootPath;
	BtrcInotifyWatch *watches;
	size_t watchCount;
	size_t watchCap;
	BtrcLinuxWatchItem *items;
	size_t head;
	size_t count;
	size_t capacity;
};

static char *btrcLinuxStrdup(const char *s) {
	if (!s) { return NULL; }
	size_t n = strlen(s) + 1u;
	char *out = (char *)malloc(n);
	if (out) { memcpy(out, s, n); }
	return out;
}

static char *btrcJoinPath(const char *dir, const char *name) {
	size_t dl = strlen(dir);
	size_t nl = strlen(name);
	int needSlash = (dl > 0u && dir[dl - 1u] != '/') ? 1 : 0;
	char *out = (char *)malloc(dl + (size_t)needSlash + nl + 1u);
	if (!out) { return NULL; }
	memcpy(out, dir, dl);
	if (needSlash) { out[dl] = '/'; }
	memcpy(out + dl + (size_t)needSlash, name, nl);
	out[dl + (size_t)needSlash + nl] = '\0';
	return out;
}

static void btrcLinuxPush(BtrcLinuxFileWatcher *w, int kind, int isDir, const char *path) {
	char *copy = btrcLinuxStrdup(path);
	if (!copy) { return; }
	if (w->count == w->capacity) {
		size_t newCap = w->capacity == 0 ? 64u : w->capacity * 2u;
		BtrcLinuxWatchItem *grown = (BtrcLinuxWatchItem *)calloc(newCap, sizeof(BtrcLinuxWatchItem));
		if (!grown) {
			free(copy);
			return;
		}
		for (size_t i = 0; i < w->count; i++) {
			grown[i] = w->items[(w->head + i) % w->capacity];
		}
		free(w->items);
		w->items = grown;
		w->head = 0;
		w->capacity = newCap;
	}
	size_t tail = (w->head + w->count) % w->capacity;
	w->items[tail].kind = kind;
	w->items[tail].isDir = isDir;
	w->items[tail].path = copy;
	w->count++;
}

static void btrcAddWatchRecursive(BtrcLinuxFileWatcher *w, const char *dirPath) {
	uint32_t mask = IN_CREATE | IN_MODIFY | IN_CLOSE_WRITE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO | IN_DELETE_SELF;
	int wd = inotify_add_watch(w->fd, dirPath, mask);
	if (wd < 0) { return; }
	if (w->watchCount == w->watchCap) {
		size_t next = w->watchCap == 0 ? 32u : w->watchCap * 2u;
		BtrcInotifyWatch *grown = (BtrcInotifyWatch *)realloc(w->watches, next * sizeof(BtrcInotifyWatch));
		if (!grown) { return; }
		w->watches = grown;
		w->watchCap = next;
	}
	w->watches[w->watchCount].wd = wd;
	w->watches[w->watchCount].dirPath = btrcLinuxStrdup(dirPath);
	w->watchCount++;

	DIR *d = opendir(dirPath);
	if (!d) { return; }
	struct dirent *ent = NULL;
	while ((ent = readdir(d)) != NULL) {
		if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0) { continue; }
		char *child = btrcJoinPath(dirPath, ent->d_name);
		if (!child) { continue; }
		struct stat st;
		if (lstat(child, &st) == 0 && S_ISDIR(st.st_mode)) {
			btrcAddWatchRecursive(w, child);
		}
		free(child);
	}
	closedir(d);
}

static const char *btrcFindWatchDir(const BtrcLinuxFileWatcher *w, int wd) {
	for (size_t i = 0; i < w->watchCount; i++) {
		if (w->watches[i].wd == wd) { return w->watches[i].dirPath; }
	}
	return w->rootPath;
}

BtrcLinuxFileWatcher *btrcLinuxWatcherOpen(const char *rootPath) {
	if (!rootPath || rootPath[0] == '\0') { return NULL; }
	struct stat st;
	if (stat(rootPath, &st) != 0 || !S_ISDIR(st.st_mode)) { return NULL; }
	int fd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
	if (fd < 0) { return NULL; }
	BtrcLinuxFileWatcher *w = (BtrcLinuxFileWatcher *)calloc(1, sizeof(BtrcLinuxFileWatcher));
	if (!w) {
		close(fd);
		return NULL;
	}
	w->fd = fd;
	w->rootPath = btrcLinuxStrdup(rootPath);
	btrcAddWatchRecursive(w, rootPath);
	return w;
}

void btrcLinuxWatcherClose(BtrcLinuxFileWatcher *w) {
	if (!w) { return; }
	if (w->fd >= 0) {
		close(w->fd);
		w->fd = -1;
	}
	for (size_t i = 0; i < w->watchCount; i++) { free(w->watches[i].dirPath); }
	free(w->watches);
	for (size_t i = 0; i < w->count; i++) {
		free(w->items[(w->head + i) % w->capacity].path);
	}
	free(w->items);
	free(w->rootPath);
	free(w);
}

int btrcLinuxWatcherWaitCount(BtrcLinuxFileWatcher *w, int timeoutMs) {
	if (!w || w->fd < 0) { return 0; }
	if (w->count == 0) {
		struct pollfd pfd;
		pfd.fd = w->fd;
		pfd.events = POLLIN;
		pfd.revents = 0;
		int rc = poll(&pfd, 1, timeoutMs < 0 ? 0 : timeoutMs);
		if (rc <= 0) { return 0; }
	}
	unsigned char buf[16384];
	for (;;) {
		ssize_t n = read(w->fd, buf, sizeof(buf));
		if (n <= 0) { break; }
		size_t off = 0;
		while (off + sizeof(struct inotify_event) <= (size_t)n) {
			struct inotify_event ev;
			memcpy(&ev, buf + off, sizeof(ev));
			const char *name = ev.len > 0 ? (const char *)(buf + off + sizeof(ev)) : "";
			const char *dir = btrcFindWatchDir(w, ev.wd);
			char *full = (name[0] != '\0') ? btrcJoinPath(dir, name) : btrcLinuxStrdup(dir);
			int isDir = (ev.mask & IN_ISDIR) ? 1 : 0;
			int kind = 1;
			if (ev.mask & IN_Q_OVERFLOW) { kind = 4; }
			else if (ev.mask & (IN_DELETE | IN_DELETE_SELF)) { kind = 2; }
			else if (ev.mask & (IN_MOVED_FROM | IN_MOVED_TO)) { kind = 3; }
			else if (ev.mask & IN_CREATE) {
				kind = 0;
				if (isDir && full) { btrcAddWatchRecursive(w, full); }
			}
			if (full) {
				btrcLinuxPush(w, kind, isDir, full);
				free(full);
			}
			off += sizeof(struct inotify_event) + ev.len;
		}
	}
	return (int)(w->count > 2147483647u ? 2147483647u : w->count);
}

int btrcLinuxWatcherPop(BtrcLinuxFileWatcher *w, int *outKind, int *outIsDir, char *pathBuf, size_t pathBufCap, size_t *outLen) {
	if (!w || !outKind || !outIsDir || !outLen || w->count == 0) { return 0; }
	BtrcLinuxWatchItem item = w->items[w->head];
	w->items[w->head].path = NULL;
	w->head = (w->head + 1u) % w->capacity;
	w->count--;
	*outKind = item.kind;
	*outIsDir = item.isDir;
	size_t len = item.path ? strlen(item.path) : 0u;
	*outLen = len;
	if (pathBuf && pathBufCap > 0u) {
		size_t copyLen = len < (pathBufCap - 1u) ? len : (pathBufCap - 1u);
		if (copyLen > 0u) { memcpy(pathBuf, item.path, copyLen); }
		pathBuf[copyLen] = '\0';
	}
	free(item.path);
	return 1;
}
