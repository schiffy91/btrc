#include "MappedFileNative.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#if !defined(_WIN32)
#include <sys/mman.h>
#endif

struct BtrcMappedRegion {
	unsigned char *data;
	long long size;
	int mapped;
};

BtrcMappedRegion *btrcMappedFileOpen(const char *path) {
	if (!path || path[0] == '\0') { return NULL; }
#if !defined(_WIN32)
	int fd = open(path, O_RDONLY);
	if (fd < 0) { return NULL; }
	struct stat st;
	if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode)) {
		close(fd);
		return NULL;
	}
	long long len = (long long)st.st_size;
	BtrcMappedRegion *region = (BtrcMappedRegion *)calloc(1, sizeof(BtrcMappedRegion));
	if (!region) {
		close(fd);
		return NULL;
	}
	if (len <= 0LL) {
		close(fd);
		region->data = NULL;
		region->size = 0LL;
		region->mapped = 0;
		return region;
	}
	void *ptr = mmap(NULL, (size_t)len, PROT_READ, MAP_PRIVATE, fd, 0);
	close(fd);
	if (ptr == MAP_FAILED) {
		free(region);
		return NULL;
	}
	region->data = (unsigned char *)ptr;
	region->size = len;
	region->mapped = 1;
	return region;
#else
	FILE *f = fopen(path, "rb");
	if (!f) { return NULL; }
	if (fseek(f, 0, SEEK_END) != 0) {
		fclose(f);
		return NULL;
	}
	long lenLong = ftell(f);
	if (lenLong < 0) {
		fclose(f);
		return NULL;
	}
	BtrcMappedRegion *region = (BtrcMappedRegion *)calloc(1, sizeof(BtrcMappedRegion));
	if (!region) {
		fclose(f);
		return NULL;
	}
	if (lenLong == 0) {
		fclose(f);
		return region;
	}
	rewind(f);
	unsigned char *buf = (unsigned char *)malloc((size_t)lenLong);
	if (!buf) {
		fclose(f);
		free(region);
		return NULL;
	}
	size_t got = fread(buf, 1, (size_t)lenLong, f);
	fclose(f);
	if (got != (size_t)lenLong) {
		free(buf);
		free(region);
		return NULL;
	}
	region->data = buf;
	region->size = (long long)lenLong;
	region->mapped = 0;
	return region;
#endif
}

void btrcMappedFileClose(BtrcMappedRegion *region) {
	if (!region) { return; }
	if (region->data && region->size > 0LL) {
#if !defined(_WIN32)
		if (region->mapped) {
			munmap((void *)region->data, (size_t)region->size);
		} else {
			free(region->data);
		}
#else
		free(region->data);
#endif
	}
	region->data = NULL;
	region->size = 0LL;
	free(region);
}

long long btrcMappedFileSize(const BtrcMappedRegion *region) { return region ? region->size : 0LL; }

const unsigned char *btrcMappedFileData(const BtrcMappedRegion *region) { return region ? region->data : NULL; }

int btrcMappedFileCopy(const BtrcMappedRegion *region, long long offset, void *dst, size_t byteCount) {
	if (!region || !dst || offset < 0LL) { return 0; }
	if (byteCount == 0u) { return 1; }
	if (!region->data || offset > region->size || (long long)byteCount > region->size - offset) { return 0; }
	memcpy(dst, region->data + offset, byteCount);
	return 1;
}

long long btrcMappedFileFindPair(const BtrcMappedRegion *region, long long start, long long end, int b0, int b1) {
	if (!region || !region->data || region->size < 2LL) { return -1LL; }
	if (start < 0LL) { start = 0LL; }
	if (end > region->size) { end = region->size; }
	if (end - start < 2LL) { return -1LL; }
	unsigned char c0 = (unsigned char)(b0 & 255);
	unsigned char c1 = (unsigned char)(b1 & 255);
	long long limit = end - 1LL;
	for (long long i = start; i < limit; i++) {
		if (region->data[i] == c0 && region->data[i + 1LL] == c1) { return i; }
	}
	return -1LL;
}

int btrcMappedFileMatches(const BtrcMappedRegion *region, long long offset, const char *text, size_t len) {
	if (!region || !text || offset < 0LL) { return 0; }
	if (len == 0u) { return 1; }
	if (!region->data || offset > region->size || (long long)len > region->size - offset) { return 0; }
	return memcmp(region->data + offset, text, len) == 0 ? 1 : 0;
}
