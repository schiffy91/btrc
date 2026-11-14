#pragma once

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/syscall.h>
#include <sys/xattr.h>
#include <time.h>
#include <unistd.h>

/* What a filesystem that forwards to a real directory needs beyond the
 * portable calls: operations on a node it holds only as a path descriptor
 * (which cannot be read, written or given attributes directly, so each one
 * goes through the descriptor's /proc name), and calls glibc exposes only
 * under Linux-specific names or constants. */

/* Every node the kernel remembers costs this process one descriptor, so let
 * it have as many as it is allowed. The new limit. */
static inline unsigned long btrcBackingDescriptorLimit(void) {
	struct rlimit limit;
	if (getrlimit(RLIMIT_NOFILE, &limit) != 0) { return 0; }
	if (limit.rlim_cur < limit.rlim_max) {
		limit.rlim_cur = limit.rlim_max;
		setrlimit(RLIMIT_NOFILE, &limit);
		getrlimit(RLIMIT_NOFILE, &limit);
	}
	return (unsigned long)limit.rlim_cur;
}

static inline int btrcBackingName(char* out, unsigned long capacity, int descriptor) {
	int written = snprintf(out, capacity, "/proc/self/fd/%d", descriptor);
	return written > 0 && (unsigned long)written < capacity ? 0 : -1;
}

/* Open the node a path descriptor names, for real: a new descriptor, or -1
 * with errno. */
static inline int btrcBackingOpen(int descriptor, int flags) {
	char name[40];
	if (btrcBackingName(name, sizeof(name), descriptor) != 0) {
		errno = EINVAL;
		return -1;
	}
	return open(name, (flags & ~O_NOFOLLOW) | O_CLOEXEC);
}

/* What `fstat` reports about a descriptor, as plain numbers. */
struct BtrcBackingStatus {
	unsigned long device;
	unsigned long number;
	unsigned long size;
	unsigned long blocks;
	unsigned long special;
	long accessed;
	long modified;
	long changed;
	long accessedNanoseconds;
	long modifiedNanoseconds;
	long changedNanoseconds;
	unsigned int mode;
	unsigned int links;
	unsigned int user;
	unsigned int group;
	unsigned int blockSize;
};

/* 0, or -1 with errno. */
static inline int btrcBackingInspect(int descriptor, struct BtrcBackingStatus* out) {
	struct stat status;
	if (fstat(descriptor, &status) != 0) { return -1; }
	out->device = (unsigned long)status.st_dev;
	out->number = (unsigned long)status.st_ino;
	out->size = (unsigned long)status.st_size;
	out->blocks = (unsigned long)status.st_blocks;
	out->special = (unsigned long)status.st_rdev;
	out->accessed = (long)status.st_atim.tv_sec;
	out->modified = (long)status.st_mtim.tv_sec;
	out->changed = (long)status.st_ctim.tv_sec;
	out->accessedNanoseconds = status.st_atim.tv_nsec;
	out->modifiedNanoseconds = status.st_mtim.tv_nsec;
	out->changedNanoseconds = status.st_ctim.tv_nsec;
	out->mode = status.st_mode;
	out->links = (unsigned int)status.st_nlink;
	out->user = status.st_uid;
	out->group = status.st_gid;
	out->blockSize = (unsigned int)status.st_blksize;
	return 0;
}

/* Read and write at an offset: the count, or a negative errno. */
static inline long btrcBackingRead(int descriptor, unsigned char* buffer, unsigned long size, long offset) {
	ssize_t length = pread(descriptor, buffer, size, (off_t)offset);
	return length < 0 ? -(long)errno : (long)length;
}

static inline long btrcBackingWrite(int descriptor, const unsigned char* data, unsigned long size, long offset) {
	ssize_t length = pwrite(descriptor, data, size, (off_t)offset);
	return length < 0 ? -(long)errno : (long)length;
}

static inline int btrcBackingResize(int descriptor, long size) { return ftruncate(descriptor, (off_t)size); }

static inline int btrcBackingSynchronize(int descriptor, int dataOnly) { return dataOnly ? fdatasync(descriptor) : fsync(descriptor); }

/* Where a symbolic link points, into `target`: its length, or a negative errno. */
static inline long btrcBackingTarget(int descriptor, unsigned char* target, unsigned long capacity) {
	ssize_t length = readlinkat(descriptor, "", (char*)target, capacity);
	return length < 0 ? -(long)errno : (long)length;
}

/* A directory's entries from `offset` on, packed into `buffer` as the kernel
 * hands them over: the bytes filled, 0 at the end, or a negative errno.
 * `offset` is 0 or the position of an entry already read. */
static inline long btrcBackingList(int descriptor, long offset, unsigned char* buffer, unsigned long capacity) {
	long length;
	if (lseek(descriptor, (off_t)offset, SEEK_SET) < 0) { return -(long)errno; }
	length = syscall(SYS_getdents64, descriptor, buffer, capacity);
	return length < 0 ? -(long)errno : length;
}

/* One packed entry, `at` bytes into the buffer: the kernel's layout is an
 * inode number, the position after the entry, the entry's length, its kind
 * and its name. */
static inline unsigned long btrcBackingListedNumber(const unsigned char* buffer, unsigned long at) {
	uint64_t value;
	memcpy(&value, buffer + at, sizeof(value));
	return (unsigned long)value;
}

static inline long btrcBackingListedPosition(const unsigned char* buffer, unsigned long at) {
	int64_t value;
	memcpy(&value, buffer + at + 8, sizeof(value));
	return (long)value;
}

static inline unsigned long btrcBackingListedLength(const unsigned char* buffer, unsigned long at) {
	uint16_t value;
	memcpy(&value, buffer + at + 16, sizeof(value));
	return value;
}

static inline unsigned int btrcBackingListedKind(const unsigned char* buffer, unsigned long at) { return buffer[at + 18]; }

static inline const char* btrcBackingListedName(const unsigned char* buffer, unsigned long at) { return (const char*)(buffer + at + 19); }

/* Rename with the flags plain renameat lacks. 0, or -1 with errno. */
static inline int btrcBackingRename(int directory, const char* name, int newDirectory, const char* newName, int exclusive, int exchange) {
	unsigned int flags = (exclusive ? RENAME_NOREPLACE : 0u) | (exchange ? RENAME_EXCHANGE : 0u);
	return (int)syscall(SYS_renameat2, directory, name, newDirectory, newName, flags);
}

/* Change the owner of the node itself, not of what a link points to. -1
 * keeps a side as it is. */
static inline int btrcBackingOwn(int descriptor, int user, int group) { return fchownat(descriptor, "", (uid_t)user, (gid_t)group, AT_EMPTY_PATH | AT_SYMLINK_NOFOLLOW); }

static inline int btrcBackingPermit(int descriptor, int permissions) {
	char name[40];
	if (btrcBackingName(name, sizeof(name), descriptor) != 0) {
		errno = EINVAL;
		return -1;
	}
	return chmod(name, (mode_t)permissions);
}

/* Set the two times. Nanoseconds of -1 leave a time alone and -2 set it to
 * now. */
static inline int btrcBackingTimes(int descriptor, long accessed, long accessedNanoseconds, long modified, long modifiedNanoseconds) {
	char name[40];
	struct timespec times[2];
	if (btrcBackingName(name, sizeof(name), descriptor) != 0) {
		errno = EINVAL;
		return -1;
	}
	times[0].tv_sec = (time_t)accessed;
	times[0].tv_nsec = accessedNanoseconds == -1 ? UTIME_OMIT : accessedNanoseconds == -2 ? UTIME_NOW : accessedNanoseconds;
	times[1].tv_sec = (time_t)modified;
	times[1].tv_nsec = modifiedNanoseconds == -1 ? UTIME_OMIT : modifiedNanoseconds == -2 ? UTIME_NOW : modifiedNanoseconds;
	return utimensat(AT_FDCWD, name, times, 0);
}

static inline int btrcBackingSymbolicLink(const char* target, int directory, const char* name) { return symlinkat(target, directory, name); }

/* Another name for the node a path descriptor names. */
static inline int btrcBackingLink(int descriptor, int newDirectory, const char* newName) {
	char name[40];
	if (btrcBackingName(name, sizeof(name), descriptor) != 0) {
		errno = EINVAL;
		return -1;
	}
	return linkat(AT_FDCWD, name, newDirectory, newName, AT_SYMLINK_FOLLOW);
}

/* The next hole or data at or after `offset`, or a negative errno. */
static inline long btrcBackingSeek(int descriptor, long offset, int toHole) {
	off_t found = lseek(descriptor, (off_t)offset, toHole ? SEEK_HOLE : SEEK_DATA);
	return found < 0 ? -(long)errno : (long)found;
}

static inline int btrcBackingAllocate(int descriptor, int mode, long offset, long length) { return fallocate(descriptor, mode, (off_t)offset, (off_t)length); }

/* An extended attribute's value into `value`: its length, or a negative
 * errno. A `capacity` of 0 asks only for the length. */
static inline long btrcBackingAttribute(int descriptor, const char* attribute, unsigned char* value, unsigned long capacity) {
	char name[40];
	ssize_t length;
	if (btrcBackingName(name, sizeof(name), descriptor) != 0) { return -EINVAL; }
	length = getxattr(name, attribute, value, capacity);
	return length < 0 ? -(long)errno : (long)length;
}

static inline long btrcBackingAttributeNames(int descriptor, unsigned char* names, unsigned long capacity) {
	char name[40];
	ssize_t length;
	if (btrcBackingName(name, sizeof(name), descriptor) != 0) { return -EINVAL; }
	length = listxattr(name, (char*)names, capacity);
	return length < 0 ? -(long)errno : (long)length;
}

static inline int btrcBackingAttributeSet(int descriptor, const char* attribute, const unsigned char* value, unsigned long length, int flags) {
	char name[40];
	if (btrcBackingName(name, sizeof(name), descriptor) != 0) { return -EINVAL; }
	return setxattr(name, attribute, value, length, flags) != 0 ? -errno : 0;
}

static inline int btrcBackingAttributeRemove(int descriptor, const char* attribute) {
	char name[40];
	if (btrcBackingName(name, sizeof(name), descriptor) != 0) { return -EINVAL; }
	return removexattr(name, attribute) != 0 ? -errno : 0;
}

/* Room and counts of the filesystem a descriptor is on; `which` picks one:
 * 0 block size, 1 blocks, 2 free, 3 available, 4 nodes, 5 free nodes,
 * 6 longest name. 0 when the call fails. */
static inline unsigned long btrcBackingRoom(int descriptor, int which) {
	struct statvfs room;
	if (fstatvfs(descriptor, &room) != 0) { return 0; }
	switch (which) {
	case 0: return room.f_frsize;
	case 1: return room.f_blocks;
	case 2: return room.f_bfree;
	case 3: return room.f_bavail;
	case 4: return room.f_files;
	case 5: return room.f_ffree;
	default: return room.f_namemax;
	}
}
