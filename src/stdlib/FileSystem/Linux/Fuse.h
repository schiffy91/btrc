#pragma once

#include <errno.h>
#include <fcntl.h>
#include <linux/fuse.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <unistd.h>

/* The kernel's FUSE protocol: a mounted directory whose every operation
 * arrives as a message on /dev/fuse and waits for the answer written back.
 * Messages are kernel structures packed into one buffer, their requests are
 * ioctl numbers built from structure sizes, and names follow fixed parts at
 * offsets only the structures know, so each field read and each answer is one
 * adapter here. Nothing in this file decides anything. */

/* The largest write the kernel may send, and the buffer that holds it with
 * its headers. */
#define BTRC_FUSE_MAX_WRITE (1024u * 1024u)
#define BTRC_FUSE_BUFFER (BTRC_FUSE_MAX_WRITE + 8192u)

static inline unsigned long btrcFuseBufferSize(void) { return BTRC_FUSE_BUFFER; }

static inline int btrcFuseOpenDevice(void) { return open("/dev/fuse", O_RDWR | O_CLOEXEC); }

/* Mount the device at `directory`; 0, or -1 with errno. Needs CAP_SYS_ADMIN. */
static inline int btrcFuseMount(int device, const char* directory, const char* name, unsigned int rootMode, unsigned int user, unsigned int group, int allowOthers, int kernelPermissions) {
	char options[256];
	char type[96];
	int written = snprintf(options, sizeof(options), "fd=%d,rootmode=%o,user_id=%u,group_id=%u%s%s", device, rootMode & (unsigned int)S_IFMT, user, group, allowOthers ? ",allow_other" : "", kernelPermissions ? ",default_permissions" : "");
	if (written < 0 || (size_t)written >= sizeof(options)) {
		errno = EINVAL;
		return -1;
	}
	written = snprintf(type, sizeof(type), "fuse.%s", name);
	if (written < 0 || (size_t)written >= sizeof(type)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	return mount(name, directory, type, MS_NOSUID | MS_NODEV, options);
}

static inline int btrcFuseUnmount(const char* directory) { return umount2(directory, MNT_DETACH); }

/* The next request into `buffer`: its length, 0 when the caller should wait
 * and ask again, or a negative errno (-ENODEV once the mount is gone). */
static inline long btrcFuseReceive(int device, unsigned char* buffer, unsigned long capacity) {
	ssize_t length = read(device, buffer, capacity);
	if (length >= 0) { return (long)length; }
	if (errno == EINTR || errno == EAGAIN || errno == ENOENT) { return 0; }
	return -(long)errno;
}

static inline const struct fuse_in_header* btrcFuseHeader(const unsigned char* request) { return (const struct fuse_in_header*)(const void*)request; }

static inline const unsigned char* btrcFuseBody(const unsigned char* request) { return request + sizeof(struct fuse_in_header); }

static inline unsigned int btrcFuseOpcode(const unsigned char* request) { return btrcFuseHeader(request)->opcode; }

static inline unsigned long btrcFuseUnique(const unsigned char* request) { return (unsigned long)btrcFuseHeader(request)->unique; }

static inline unsigned long btrcFuseNode(const unsigned char* request) { return (unsigned long)btrcFuseHeader(request)->nodeid; }

static inline unsigned int btrcFuseUser(const unsigned char* request) { return btrcFuseHeader(request)->uid; }

static inline unsigned int btrcFuseGroup(const unsigned char* request) { return btrcFuseHeader(request)->gid; }

static inline unsigned int btrcFuseProcess(const unsigned char* request) { return btrcFuseHeader(request)->pid; }

/* The name that starts `skip` bytes into the body, or NULL when it does not
 * end inside the request. */
static inline const char* btrcFuseName(const unsigned char* request, unsigned long skip) {
	unsigned long bodyLength = (unsigned long)btrcFuseHeader(request)->len - sizeof(struct fuse_in_header);
	const unsigned char* start = btrcFuseBody(request) + skip;
	if (skip >= bodyLength || memchr(start, 0, bodyLength - skip) == NULL) { return NULL; }
	return (const char*)start;
}

/* Where the name after the one at `skip` starts. */
static inline unsigned long btrcFuseNameAfter(const unsigned char* request, unsigned long skip) {
	const char* name = btrcFuseName(request, skip);
	return name == NULL ? skip : skip + strlen(name) + 1;
}

/* The bytes after the fixed part: a write's data, or an attribute's value. */
static inline const unsigned char* btrcFusePayload(const unsigned char* request, unsigned long skip) { return btrcFuseBody(request) + skip; }

static inline unsigned long btrcFusePayloadLength(const unsigned char* request, unsigned long skip) {
	unsigned long bodyLength = (unsigned long)btrcFuseHeader(request)->len - sizeof(struct fuse_in_header);
	return skip >= bodyLength ? 0 : bodyLength - skip;
}

/* The fixed parts' sizes, which is where a request's names start. */
static inline unsigned long btrcFuseSizeMakeDirectory(void) { return sizeof(struct fuse_mkdir_in); }

static inline unsigned long btrcFuseSizeMakeNode(void) { return sizeof(struct fuse_mknod_in); }

static inline unsigned long btrcFuseSizeCreate(void) { return sizeof(struct fuse_create_in); }

static inline unsigned long btrcFuseSizeRename(void) { return sizeof(struct fuse_rename_in); }

static inline unsigned long btrcFuseSizeRenameFlags(void) { return sizeof(struct fuse_rename2_in); }

static inline unsigned long btrcFuseSizeLink(void) { return sizeof(struct fuse_link_in); }

static inline unsigned long btrcFuseSizeWrite(void) { return sizeof(struct fuse_write_in); }

/* Kernels that did not agree to the longer form send only the first two
 * fields. */
static inline unsigned long btrcFuseSizeSetAttribute(int extended) { return extended ? sizeof(struct fuse_setxattr_in) : FUSE_COMPAT_SETXATTR_IN_SIZE; }

static inline unsigned long btrcFuseSizeGetAttribute(void) { return sizeof(struct fuse_getxattr_in); }

/* Field readers. `which` names a field of the request's fixed part; each
 * request kind has its own small set, listed beside the structure it reads. */
static inline unsigned long btrcFuseField(const unsigned char* request, int which) {
	const void* body = btrcFuseBody(request);
	switch (btrcFuseOpcode(request)) {
	case FUSE_FORGET: return (unsigned long)((const struct fuse_forget_in*)body)->nlookup;
	case FUSE_GETATTR: {
		const struct fuse_getattr_in* in = body;
		return which == 0 ? in->getattr_flags : (unsigned long)in->fh;
	}
	case FUSE_SETATTR: {
		const struct fuse_setattr_in* in = body;
		switch (which) {
		case 0: return in->valid;
		case 1: return (unsigned long)in->fh;
		case 2: return (unsigned long)in->size;
		case 3: return (unsigned long)in->atime;
		case 4: return in->atimensec;
		case 5: return (unsigned long)in->mtime;
		case 6: return in->mtimensec;
		case 7: return in->mode;
		case 8: return in->uid;
		case 9: return in->gid;
		default: return 0;
		}
	}
	case FUSE_MKDIR: return ((const struct fuse_mkdir_in*)body)->mode;
	case FUSE_MKNOD: {
		const struct fuse_mknod_in* in = body;
		return which == 0 ? in->mode : in->rdev;
	}
	case FUSE_RENAME: return (unsigned long)((const struct fuse_rename_in*)body)->newdir;
	case FUSE_RENAME2: {
		const struct fuse_rename2_in* in = body;
		return which == 0 ? (unsigned long)in->newdir : in->flags;
	}
	case FUSE_LINK: return (unsigned long)((const struct fuse_link_in*)body)->oldnodeid;
	case FUSE_OPEN:
	case FUSE_OPENDIR: return ((const struct fuse_open_in*)body)->flags;
	case FUSE_CREATE: {
		const struct fuse_create_in* in = body;
		return which == 0 ? in->flags : in->mode;
	}
	case FUSE_READ:
	case FUSE_READDIR:
	case FUSE_READDIRPLUS: {
		const struct fuse_read_in* in = body;
		return which == 0 ? (unsigned long)in->fh : which == 1 ? (unsigned long)in->offset : in->size;
	}
	case FUSE_WRITE: {
		const struct fuse_write_in* in = body;
		return which == 0 ? (unsigned long)in->fh : which == 1 ? (unsigned long)in->offset : in->size;
	}
	case FUSE_RELEASE:
	case FUSE_RELEASEDIR: {
		const struct fuse_release_in* in = body;
		return which == 0 ? (unsigned long)in->fh : in->flags;
	}
	case FUSE_FLUSH: return (unsigned long)((const struct fuse_flush_in*)body)->fh;
	case FUSE_FSYNC:
	case FUSE_FSYNCDIR: {
		const struct fuse_fsync_in* in = body;
		return which == 0 ? (unsigned long)in->fh : in->fsync_flags;
	}
	case FUSE_SETXATTR: {
		const struct fuse_setxattr_in* in = body;
		return which == 0 ? in->size : in->flags;
	}
	case FUSE_GETXATTR:
	case FUSE_LISTXATTR: return ((const struct fuse_getxattr_in*)body)->size;
	case FUSE_ACCESS: return ((const struct fuse_access_in*)body)->mask;
	case FUSE_FALLOCATE: {
		const struct fuse_fallocate_in* in = body;
		return which == 0 ? (unsigned long)in->fh : which == 1 ? (unsigned long)in->offset : which == 2 ? (unsigned long)in->length : in->mode;
	}
	case FUSE_LSEEK: {
		const struct fuse_lseek_in* in = body;
		return which == 0 ? (unsigned long)in->fh : which == 1 ? (unsigned long)in->offset : in->whence;
	}
	case FUSE_INTERRUPT: return (unsigned long)((const struct fuse_interrupt_in*)body)->unique;
	case FUSE_BATCH_FORGET: return ((const struct fuse_batch_forget_in*)body)->count;
	default: return 0;
	}
}

/* What a seek looks for: 1 the next hole, 0 the next data, -1 neither. */
static inline int btrcFuseSeekTarget(unsigned long whence) { return whence == (unsigned long)SEEK_HOLE ? 1 : whence == (unsigned long)SEEK_DATA ? 0 : -1; }

/* One node of a batched forget: its id, and how many lookups it gives back. */
static inline unsigned long btrcFuseForgetNode(const unsigned char* request, unsigned long index) {
	const struct fuse_forget_one* list = (const struct fuse_forget_one*)(const void*)(btrcFuseBody(request) + sizeof(struct fuse_batch_forget_in));
	return (unsigned long)list[index].nodeid;
}

static inline unsigned long btrcFuseForgetCount(const unsigned char* request, unsigned long index) {
	const struct fuse_forget_one* list = (const struct fuse_forget_one*)(const void*)(btrcFuseBody(request) + sizeof(struct fuse_batch_forget_in));
	return (unsigned long)list[index].nlookup;
}

/* Write one answer: the header, then `length` bytes of `body`. 0, or a
 * negative errno (-ENOENT when the caller stopped waiting, which is fine). */
static inline int btrcFuseAnswer(int device, unsigned long unique, int error, const void* body, unsigned long length) {
	struct fuse_out_header header;
	struct iovec parts[2];
	header.len = (uint32_t)(sizeof(header) + length);
	header.error = -error;
	header.unique = unique;
	parts[0].iov_base = &header;
	parts[0].iov_len = sizeof(header);
	parts[1].iov_base = (void*)(uintptr_t)body;
	parts[1].iov_len = length;
	return writev(device, parts, length > 0 ? 2 : 1) < 0 ? -errno : 0;
}

static inline int btrcFuseAnswerError(int device, unsigned long unique, int error) { return btrcFuseAnswer(device, unique, error, NULL, 0); }

static inline int btrcFuseAnswerData(int device, unsigned long unique, const unsigned char* data, unsigned long length) { return btrcFuseAnswer(device, unique, 0, data, length); }

/* Answer the handshake. Returns a negative errno, or the features both
 * sides agreed: bit 0 passthrough, bit 1 the longer set-attribute request. */
static inline int btrcFuseAnswerHandshake(int device, const unsigned char* request, int passthrough) {
	const struct fuse_init_in* in = (const struct fuse_init_in*)(const void*)btrcFuseBody(request);
	struct fuse_init_out out;
	uint64_t offered = in->flags;
	uint64_t wanted = FUSE_INIT_EXT | FUSE_ASYNC_READ | FUSE_BIG_WRITES | FUSE_ATOMIC_O_TRUNC | FUSE_AUTO_INVAL_DATA | FUSE_PARALLEL_DIROPS | FUSE_MAX_PAGES | FUSE_CACHE_SYMLINKS | FUSE_DO_READDIRPLUS | FUSE_READDIRPLUS_AUTO | FUSE_SETXATTR_EXT;
	uint64_t agreed;
	int answered;
	memset(&out, 0, sizeof(out));
	out.major = FUSE_KERNEL_VERSION;
	out.minor = FUSE_KERNEL_MINOR_VERSION;
	if (in->major < 7 || (in->major == 7 && in->minor < 36)) { return btrcFuseAnswerError(device, btrcFuseUnique(request), EPROTO) < 0 ? -errno : -EPROTO; }
	if (in->major > 7) {
		answered = btrcFuseAnswer(device, btrcFuseUnique(request), 0, &out, sizeof(out));
		return answered < 0 ? answered : -EAGAIN;
	}
	if (in->minor < out.minor) { out.minor = in->minor; }
	if (in->flags & FUSE_INIT_EXT) { offered |= (uint64_t)in->flags2 << 32; }
	if (passthrough) { wanted |= FUSE_PASSTHROUGH; }
	agreed = offered & wanted;
	out.max_readahead = in->max_readahead;
	out.flags = (uint32_t)agreed;
	out.flags2 = (uint32_t)(agreed >> 32);
	out.max_background = 64;
	out.congestion_threshold = 48;
	out.max_write = BTRC_FUSE_MAX_WRITE;
	out.time_gran = 1;
	out.max_pages = (uint16_t)(BTRC_FUSE_MAX_WRITE / 4096u);
	if (agreed & FUSE_PASSTHROUGH) { out.max_stack_depth = 1; }
	answered = btrcFuseAnswer(device, btrcFuseUnique(request), 0, &out, sizeof(out));
	if (answered < 0) { return answered; }
	return ((agreed & FUSE_PASSTHROUGH) ? 1 : 0) | ((agreed & FUSE_SETXATTR_EXT) ? 2 : 0);
}

/* What `stat` reports, as plain numbers the filesystem fills in. */
struct BtrcFuseAttributes {
	unsigned long number;
	unsigned long size;
	unsigned long blocks;
	unsigned long accessed;
	unsigned long modified;
	unsigned long changed;
	unsigned int accessedNanoseconds;
	unsigned int modifiedNanoseconds;
	unsigned int changedNanoseconds;
	unsigned int mode;
	unsigned int links;
	unsigned int user;
	unsigned int group;
	unsigned int device;
	unsigned int blockSize;
};

static inline void btrcFuseAttributes(struct fuse_attr* out, const struct BtrcFuseAttributes* from) {
	memset(out, 0, sizeof(*out));
	out->ino = from->number;
	out->size = from->size;
	out->blocks = from->blocks;
	out->atime = from->accessed;
	out->mtime = from->modified;
	out->ctime = from->changed;
	out->atimensec = from->accessedNanoseconds;
	out->mtimensec = from->modifiedNanoseconds;
	out->ctimensec = from->changedNanoseconds;
	out->mode = from->mode;
	out->nlink = from->links;
	out->uid = from->user;
	out->gid = from->group;
	out->rdev = from->device;
	out->blksize = from->blockSize;
}

static inline void btrcFuseEntry(struct fuse_entry_out* out, unsigned long node, unsigned long generation, unsigned long entryNanoseconds, unsigned long attributeNanoseconds, const struct BtrcFuseAttributes* attributes) {
	memset(out, 0, sizeof(*out));
	out->nodeid = node;
	out->generation = generation;
	out->entry_valid = entryNanoseconds / 1000000000ul;
	out->entry_valid_nsec = (uint32_t)(entryNanoseconds % 1000000000ul);
	out->attr_valid = attributeNanoseconds / 1000000000ul;
	out->attr_valid_nsec = (uint32_t)(attributeNanoseconds % 1000000000ul);
	if (attributes != NULL) { btrcFuseAttributes(&out->attr, attributes); }
}

/* A name's answer. Node 0 with a lifetime says "no such name, and remember
 * that"; `attributes` is then NULL. */
static inline int btrcFuseAnswerEntry(int device, unsigned long unique, unsigned long node, unsigned long generation, unsigned long entryNanoseconds, unsigned long attributeNanoseconds, const struct BtrcFuseAttributes* attributes) {
	struct fuse_entry_out out;
	btrcFuseEntry(&out, node, generation, entryNanoseconds, attributeNanoseconds, attributes);
	return btrcFuseAnswer(device, unique, 0, &out, sizeof(out));
}

static inline int btrcFuseAnswerAttributes(int device, unsigned long unique, unsigned long nanoseconds, const struct BtrcFuseAttributes* attributes) {
	struct fuse_attr_out out;
	memset(&out, 0, sizeof(out));
	out.attr_valid = nanoseconds / 1000000000ul;
	out.attr_valid_nsec = (uint32_t)(nanoseconds % 1000000000ul);
	btrcFuseAttributes(&out.attr, attributes);
	return btrcFuseAnswer(device, unique, 0, &out, sizeof(out));
}

/* An open's answer. `backing` above 0 hands the file to the kernel. */
static inline int btrcFuseAnswerOpen(int device, unsigned long unique, unsigned long handle, int keepCache, int backing) {
	struct fuse_open_out out;
	memset(&out, 0, sizeof(out));
	out.fh = handle;
	out.open_flags = (keepCache ? FOPEN_KEEP_CACHE : 0u) | (backing > 0 ? FOPEN_PASSTHROUGH : 0u);
	out.backing_id = backing > 0 ? backing : 0;
	return btrcFuseAnswer(device, unique, 0, &out, sizeof(out));
}

/* A create's answer: the new name's entry, then its open. */
static inline int btrcFuseAnswerCreate(int device, unsigned long unique, unsigned long node, unsigned long generation, unsigned long entryNanoseconds, unsigned long attributeNanoseconds, const struct BtrcFuseAttributes* attributes, unsigned long handle, int backing) {
	struct {
		struct fuse_entry_out entry;
		struct fuse_open_out opened;
	} out;
	memset(&out, 0, sizeof(out));
	btrcFuseEntry(&out.entry, node, generation, entryNanoseconds, attributeNanoseconds, attributes);
	out.opened.fh = handle;
	out.opened.open_flags = backing > 0 ? FOPEN_PASSTHROUGH : 0u;
	out.opened.backing_id = backing > 0 ? backing : 0;
	return btrcFuseAnswer(device, unique, 0, &out, sizeof(out));
}

static inline int btrcFuseAnswerWritten(int device, unsigned long unique, unsigned long count) {
	struct fuse_write_out out;
	memset(&out, 0, sizeof(out));
	out.size = (uint32_t)count;
	return btrcFuseAnswer(device, unique, 0, &out, sizeof(out));
}

static inline int btrcFuseAnswerStatistics(int device, unsigned long unique, unsigned long blockSize, unsigned long blocks, unsigned long blocksFree, unsigned long blocksAvailable, unsigned long nodes, unsigned long nodesFree, unsigned long longestName) {
	struct fuse_statfs_out out;
	memset(&out, 0, sizeof(out));
	out.st.blocks = blocks;
	out.st.bfree = blocksFree;
	out.st.bavail = blocksAvailable;
	out.st.files = nodes;
	out.st.ffree = nodesFree;
	out.st.bsize = (uint32_t)blockSize;
	out.st.namelen = (uint32_t)longestName;
	out.st.frsize = (uint32_t)blockSize;
	return btrcFuseAnswer(device, unique, 0, &out, sizeof(out));
}

/* How large an attribute's value or a list of names is, for a caller that
 * asked with no room. */
static inline int btrcFuseAnswerSize(int device, unsigned long unique, unsigned long size) {
	struct fuse_getxattr_out out;
	memset(&out, 0, sizeof(out));
	out.size = (uint32_t)size;
	return btrcFuseAnswer(device, unique, 0, &out, sizeof(out));
}

static inline int btrcFuseAnswerOffset(int device, unsigned long unique, unsigned long offset) {
	struct fuse_lseek_out out;
	memset(&out, 0, sizeof(out));
	out.offset = offset;
	return btrcFuseAnswer(device, unique, 0, &out, sizeof(out));
}

/* Add one name to a listing being built in `buffer`. Returns the bytes used
 * after it, or 0 when it does not fit. `next` is what the kernel passes back
 * to continue after this name. */
static inline unsigned long btrcFuseListAdd(unsigned char* buffer, unsigned long capacity, unsigned long used, const char* name, unsigned long node, unsigned int kind, unsigned long next) {
	size_t length = strlen(name);
	size_t padded = FUSE_DIRENT_ALIGN(FUSE_NAME_OFFSET + length);
	struct fuse_dirent* entry = (struct fuse_dirent*)(void*)(buffer + used);
	if (used + padded > capacity) { return 0; }
	memset(entry, 0, padded);
	entry->ino = node;
	entry->off = next;
	entry->namelen = (uint32_t)length;
	entry->type = kind;
	memcpy(entry->name, name, length);
	return used + padded;
}

/* The same, with the name's entry so the kernel need not look it up. A node
 * of 0 lists the name without one. */
static inline unsigned long btrcFuseListAddEntry(unsigned char* buffer, unsigned long capacity, unsigned long used, const char* name, unsigned long node, unsigned long generation, unsigned long entryNanoseconds, unsigned long attributeNanoseconds, const struct BtrcFuseAttributes* attributes, unsigned long next) {
	size_t length = strlen(name);
	size_t padded = FUSE_DIRENT_ALIGN(FUSE_NAME_OFFSET_DIRENTPLUS + length);
	struct fuse_direntplus* entry = (struct fuse_direntplus*)(void*)(buffer + used);
	if (used + padded > capacity) { return 0; }
	memset(entry, 0, padded);
	btrcFuseEntry(&entry->entry_out, node, generation, entryNanoseconds, attributeNanoseconds, attributes);
	entry->dirent.ino = attributes->number;
	entry->dirent.off = next;
	entry->dirent.namelen = (uint32_t)length;
	entry->dirent.type = (attributes->mode & (unsigned int)S_IFMT) >> 12;
	memcpy(entry->dirent.name, name, length);
	return used + padded;
}

/* Tell the kernel to drop what it remembers. These are messages without a
 * request; 0, or a negative errno (-ENOENT when it remembered nothing). */
static inline int btrcFuseForgetName(int device, unsigned long parent, const char* name) {
	struct fuse_out_header header;
	struct fuse_notify_inval_entry_out out;
	struct iovec parts[3];
	size_t length = strlen(name);
	memset(&out, 0, sizeof(out));
	out.parent = parent;
	out.namelen = (uint32_t)length;
	header.len = (uint32_t)(sizeof(header) + sizeof(out) + length + 1);
	header.error = FUSE_NOTIFY_INVAL_ENTRY;
	header.unique = 0;
	parts[0].iov_base = &header;
	parts[0].iov_len = sizeof(header);
	parts[1].iov_base = &out;
	parts[1].iov_len = sizeof(out);
	parts[2].iov_base = (void*)(uintptr_t)name;
	parts[2].iov_len = length + 1;
	return writev(device, parts, 3) < 0 ? -errno : 0;
}

/* `length` 0 drops everything from `offset`; `offset` below 0 drops only the
 * attributes. */
static inline int btrcFuseForgetContents(int device, unsigned long node, long offset, long length) {
	struct fuse_out_header header;
	struct fuse_notify_inval_inode_out out;
	struct iovec parts[2];
	memset(&out, 0, sizeof(out));
	out.ino = node;
	out.off = offset;
	out.len = length;
	header.len = (uint32_t)(sizeof(header) + sizeof(out));
	header.error = FUSE_NOTIFY_INVAL_INODE;
	header.unique = 0;
	parts[0].iov_base = &header;
	parts[0].iov_len = sizeof(header);
	parts[1].iov_base = &out;
	parts[1].iov_len = sizeof(out);
	return writev(device, parts, 2) < 0 ? -errno : 0;
}

/* Register an open file the kernel may read and write directly. Returns its
 * id, above 0, or a negative errno. */
static inline int btrcFuseBackingOpen(int device, int descriptor) {
	struct fuse_backing_map map;
	int id;
	memset(&map, 0, sizeof(map));
	map.fd = descriptor;
	id = ioctl(device, FUSE_DEV_IOC_BACKING_OPEN, &map);
	return id > 0 ? id : id == 0 ? -EIO : -errno;
}

static inline int btrcFuseBackingClose(int device, int id) {
	uint32_t value = (uint32_t)id;
	return ioctl(device, FUSE_DEV_IOC_BACKING_CLOSE, &value) < 0 ? -errno : 0;
}
