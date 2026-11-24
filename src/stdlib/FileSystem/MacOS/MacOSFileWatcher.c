#include "MacOSFileWatcher.h"

#include <CoreFoundation/CoreFoundation.h>
#include <CoreServices/CoreServices.h>
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>

typedef struct BtrcWatchItem {
	int kind;
	int isDir;
	char *path;
} BtrcWatchItem;

struct BtrcMacOSFileWatcher {
	FSEventStreamRef stream;
	dispatch_queue_t queue;
	pthread_mutex_t mu;
	pthread_cond_t cv;
	BtrcWatchItem *items;
	size_t head;
	size_t count;
	size_t capacity;
	int closed;
};

static char *btrcStrdup(const char *s) {
	if (!s) { return NULL; }
	size_t n = strlen(s) + 1u;
	char *out = (char *)malloc(n);
	if (out) { memcpy(out, s, n); }
	return out;
}

static void btrcWatcherBarrierNoop(void *ctx) { (void)ctx; }

static void btrcWatcherPush(BtrcMacOSFileWatcher *w, int kind, int isDir, const char *path) {
	if (!w || !path) { return; }
	char *copy = btrcStrdup(path);
	if (!copy) { return; }
	pthread_mutex_lock(&w->mu);
	if (w->closed) {
		pthread_mutex_unlock(&w->mu);
		free(copy);
		return;
	}
	if (w->count == w->capacity) {
		size_t newCap = w->capacity == 0 ? 64u : w->capacity * 2u;
		if (newCap > 65536u) {
			/* Ring overflow: collapse to a single rescan marker. */
			for (size_t i = 0; i < w->count; i++) {
				size_t idx = (w->head + i) % w->capacity;
				free(w->items[idx].path);
				w->items[idx].path = NULL;
			}
			w->head = 0;
			w->count = 1;
			w->items[0].kind = 4;
			w->items[0].isDir = 1;
			w->items[0].path = copy;
			pthread_cond_broadcast(&w->cv);
			pthread_mutex_unlock(&w->mu);
			return;
		}
		BtrcWatchItem *grown = (BtrcWatchItem *)calloc(newCap, sizeof(BtrcWatchItem));
		if (!grown) {
			pthread_mutex_unlock(&w->mu);
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
	pthread_cond_broadcast(&w->cv);
	pthread_mutex_unlock(&w->mu);
}

static void btrcFSEventsCallback(
	ConstFSEventStreamRef streamRef,
	void *clientCallBackInfo,
	size_t numEvents,
	void *eventPaths,
	const FSEventStreamEventFlags eventFlags[],
	const FSEventStreamEventId eventIds[]) {
	(void)streamRef;
	(void)eventIds;
	BtrcMacOSFileWatcher *w = (BtrcMacOSFileWatcher *)clientCallBackInfo;
	char **paths = (char **)eventPaths;
	for (size_t i = 0; i < numEvents; i++) {
		FSEventStreamEventFlags f = eventFlags[i];
		const char *p = paths[i];
		if (!p) { continue; }
		int isDir = (f & kFSEventStreamEventFlagItemIsDir) ? 1 : 0;
		int kind = 1; /* modified */
		if (f & (kFSEventStreamEventFlagMustScanSubDirs | kFSEventStreamEventFlagUserDropped | kFSEventStreamEventFlagKernelDropped | kFSEventStreamEventFlagRootChanged)) {
			kind = 4; /* rescan */
		} else if (f & kFSEventStreamEventFlagItemRemoved) {
			kind = 2; /* removed */
		} else if (f & kFSEventStreamEventFlagItemRenamed) {
			kind = 3; /* renamed */
		} else if (f & kFSEventStreamEventFlagItemCreated) {
			kind = 0; /* created */
		} else if (f & (kFSEventStreamEventFlagItemModified | kFSEventStreamEventFlagItemInodeMetaMod | kFSEventStreamEventFlagItemXattrMod)) {
			kind = 1; /* modified */
		} else {
			continue;
		}
		btrcWatcherPush(w, kind, isDir, p);
	}
}

BtrcMacOSFileWatcher *btrcMacOSWatcherOpen(const char *rootPath, int latencyMs) {
	if (!rootPath || rootPath[0] == '\0') { return NULL; }
	struct stat st;
	if (stat(rootPath, &st) != 0 || !S_ISDIR(st.st_mode)) { return NULL; }

	BtrcMacOSFileWatcher *w = (BtrcMacOSFileWatcher *)calloc(1, sizeof(BtrcMacOSFileWatcher));
	if (!w) { return NULL; }
	if (pthread_mutex_init(&w->mu, NULL) != 0) {
		free(w);
		return NULL;
	}
	if (pthread_cond_init(&w->cv, NULL) != 0) {
		pthread_mutex_destroy(&w->mu);
		free(w);
		return NULL;
	}

	CFStringRef cfPath = CFStringCreateWithCString(kCFAllocatorDefault, rootPath, kCFStringEncodingUTF8);
	if (!cfPath) {
		pthread_cond_destroy(&w->cv);
		pthread_mutex_destroy(&w->mu);
		free(w);
		return NULL;
	}
	CFArrayRef paths = CFArrayCreate(kCFAllocatorDefault, (const void **)&cfPath, 1, &kCFTypeArrayCallBacks);
	CFRelease(cfPath);
	if (!paths) {
		pthread_cond_destroy(&w->cv);
		pthread_mutex_destroy(&w->mu);
		free(w);
		return NULL;
	}

	FSEventStreamContext ctx;
	memset(&ctx, 0, sizeof(ctx));
	ctx.info = w;
	double latencySec = (latencyMs < 10 ? 10.0 : (double)latencyMs) / 1000.0;
	FSEventStreamCreateFlags flags = kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagNoDefer;
	w->stream = FSEventStreamCreate(
		kCFAllocatorDefault,
		btrcFSEventsCallback,
		&ctx,
		paths,
		kFSEventStreamEventIdSinceNow,
		latencySec,
		flags);
	CFRelease(paths);
	if (!w->stream) {
		pthread_cond_destroy(&w->cv);
		pthread_mutex_destroy(&w->mu);
		free(w);
		return NULL;
	}

	w->queue = dispatch_queue_create("btrc.filesystem.fsevents", DISPATCH_QUEUE_SERIAL);
	if (!w->queue) {
		FSEventStreamRelease(w->stream);
		pthread_cond_destroy(&w->cv);
		pthread_mutex_destroy(&w->mu);
		free(w);
		return NULL;
	}

	FSEventStreamSetDispatchQueue(w->stream, w->queue);
	if (!FSEventStreamStart(w->stream)) {
		FSEventStreamInvalidate(w->stream);
		FSEventStreamRelease(w->stream);
		dispatch_release(w->queue);
		pthread_cond_destroy(&w->cv);
		pthread_mutex_destroy(&w->mu);
		free(w);
		return NULL;
	}
	return w;
}

void btrcMacOSWatcherClose(BtrcMacOSFileWatcher *w) {
	if (!w) { return; }
	pthread_mutex_lock(&w->mu);
	w->closed = 1;
	pthread_cond_broadcast(&w->cv);
	pthread_mutex_unlock(&w->mu);

	if (w->stream) {
		FSEventStreamStop(w->stream);
		FSEventStreamInvalidate(w->stream);
		FSEventStreamRelease(w->stream);
		w->stream = NULL;
	}
	if (w->queue) {
		/* Barrier ensures any in-flight callback finished before freeing struct. */
		dispatch_sync_f(w->queue, NULL, btrcWatcherBarrierNoop);
		dispatch_release(w->queue);
		w->queue = NULL;
	}

	pthread_mutex_lock(&w->mu);
	for (size_t i = 0; i < w->count; i++) {
		size_t idx = (w->head + i) % w->capacity;
		free(w->items[idx].path);
	}
	free(w->items);
	w->items = NULL;
	w->count = 0;
	w->capacity = 0;
	pthread_mutex_unlock(&w->mu);

	pthread_cond_destroy(&w->cv);
	pthread_mutex_destroy(&w->mu);
	free(w);
}

int btrcMacOSWatcherWaitCount(BtrcMacOSFileWatcher *w, int timeoutMs) {
	if (!w) { return 0; }
	pthread_mutex_lock(&w->mu);
	if (w->count == 0 && !w->closed && timeoutMs > 0) {
		struct timeval tv;
		gettimeofday(&tv, NULL);
		struct timespec ts;
		long long totalUs = (long long)tv.tv_usec + (long long)timeoutMs * 1000LL;
		ts.tv_sec = tv.tv_sec + (time_t)(totalUs / 1000000LL);
		ts.tv_nsec = (long)((totalUs % 1000000LL) * 1000LL);
		while (w->count == 0 && !w->closed) {
			int rc = pthread_cond_timedwait(&w->cv, &w->mu, &ts);
			if (rc == ETIMEDOUT) { break; }
		}
	}
	int n = (int)(w->count > 2147483647u ? 2147483647u : w->count);
	pthread_mutex_unlock(&w->mu);
	return n;
}

int btrcMacOSWatcherPop(BtrcMacOSFileWatcher *w, int *outKind, int *outIsDir, char *pathBuf, size_t pathBufCap, size_t *outLen) {
	if (!w || !outKind || !outIsDir || !outLen) { return 0; }
	pthread_mutex_lock(&w->mu);
	if (w->count == 0) {
		pthread_mutex_unlock(&w->mu);
		return 0;
	}
	BtrcWatchItem item = w->items[w->head];
	w->items[w->head].path = NULL;
	w->head = (w->head + 1u) % w->capacity;
	w->count--;
	pthread_mutex_unlock(&w->mu);

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
