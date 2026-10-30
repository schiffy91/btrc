/* Deterministic file-seam failures for the BTRC policy, not Windows evidence. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include "windows_os.h"

struct __btrc_windows_daemon_file_owner { int directory, live; uint32_t access; };
static struct __btrc_windows_daemon_file_owner owners[8];
static int exists, failure, closes, disposals, writes, reads;
static size_t length;
static unsigned char content[200], identity_bytes[16];
static int enumeration_pending, enumeration_done;

void daemonPolicyFailure(int point) { failure = point; }
int daemonPolicyExists(void) { return exists; }
int daemonPolicyCloses(void) { return closes; }
int daemonPolicyDisposals(void) { return disposals; }
int daemonPolicyWrites(void) { return writes; }
int daemonPolicyReads(void) { return reads; }
void daemonPolicyReplace(void) { identity_bytes[15]++; }
void daemonPolicyContent(int mode) {
    length = mode == 1 ? 3 : 129;
    memset(content, 'x', length);
    if (mode == 1) content[1] = 0;
}

static int fail(__btrc_windows_launch_error_t *error, uint32_t code, uint32_t ownership) {
    memset(error, 0, sizeof(*error));
    error->stage = 17; error->domain = 2; error->native_code = code; error->ownership_state = ownership;
    return -1;
}
static void clear(__btrc_windows_launch_error_t *error) { memset(error, 0, sizeof(*error)); }
static __btrc_windows_daemon_file_owner *acquire(int directory, uint32_t access) {
    for (size_t i = 0; i < sizeof(owners) / sizeof(owners[0]); i++) {
        if (!owners[i].live) {
            owners[i].directory = directory; owners[i].access = access; owners[i].live = 1;
            return &owners[i];
        }
    }
    abort();
}
static void snapshot(__btrc_windows_daemon_directory_entry *entry) {
    memset(entry, 0, sizeof(*entry)); entry->present = 1; entry->volume = UINT64_C(0xfedcba9876543210);
    memcpy(entry->file_id, identity_bytes, 16);
}

int __btrc_windows_daemon_directory_open(const unsigned char *path, size_t size, uint32_t create,
        __btrc_windows_daemon_file_owner **out, __btrc_windows_launch_error_t *error) {
    (void)create;
    if (size != 6 || memcmp(path, "/state", 6) != 0) abort();
    clear(error); *out = acquire(1, 0); return 0;
}
int __btrc_windows_daemon_control_open_at(__btrc_windows_daemon_file_owner *directory,
        const unsigned char *name, size_t size, uint32_t access,
        const __btrc_windows_daemon_directory_entry *expected,
        __btrc_windows_daemon_file_owner **out, __btrc_windows_launch_error_t *error) {
    if (!directory || !directory->live || !directory->directory || size != 7 || memcmp(name, "control", 7)) abort();
    clear(error); *out = NULL;
    if (failure == 11) return fail(error, 5, 0);
    if (access == 1) {
        if (expected) abort();
        if (exists) { fail(error, UINT32_C(0xc0000035), 0); error->domain = 3; return -1; }
        exists = 1; length = 0; identity_bytes[15]++;
    } else if (!exists) {
        fail(error, UINT32_C(0xc0000034), 0); error->domain = 3; return -1;
    }
    if (expected && (expected->present != 1 || expected->kind != 0
            || expected->volume != UINT64_C(0xfedcba9876543210)
            || memcmp(expected->file_id, identity_bytes, 16))) return fail(error, 1234, 0);
    *out = acquire(0, access); return 0;
}
int __btrc_windows_daemon_file_identity(__btrc_windows_daemon_file_owner *owner,
        __btrc_windows_daemon_directory_entry *entry, __btrc_windows_launch_error_t *error) {
    if (!owner || !owner->live || owner->directory) abort();
    memset(entry, 0, sizeof(*entry)); clear(error);
    if (failure == 13) return fail(error, 713, 1);
    snapshot(entry); return 0;
}
int __btrc_windows_daemon_file_write(__btrc_windows_daemon_file_owner *owner, uint64_t offset,
        const unsigned char *bytes, size_t size, size_t *transferred, __btrc_windows_launch_error_t *error) {
    if (!owner || !owner->live || owner->access != 1 || offset != length || size > sizeof(content) - length) abort();
    clear(error); *transferred = 0; writes++;
    if (failure == 2 && offset != 0) return fail(error, 702, 1);
    size_t count = size > 2 ? 2 : size;
    memcpy(content + length, bytes, count); length += count; *transferred = count; return 0;
}
int __btrc_windows_daemon_file_read(__btrc_windows_daemon_file_owner *owner, uint64_t offset,
        unsigned char *bytes, size_t size, size_t *transferred, __btrc_windows_launch_error_t *error) {
    if (!owner || !owner->live || owner->directory || offset > length) abort();
    clear(error); reads++;
    size_t count = length - (size_t)offset;
    if (count > size) count = size;
    if (count > 3) count = 3;
    memcpy(bytes, content + (size_t)offset, count); *transferred = count; return 0;
}
int __btrc_windows_daemon_file_flush(__btrc_windows_daemon_file_owner *owner,
        __btrc_windows_launch_error_t *error) {
    if (!owner || !owner->live || owner->access != 1) abort();
    clear(error); return failure == 3 ? fail(error, 703, 1) : 0;
}
int __btrc_windows_daemon_file_dispose(__btrc_windows_daemon_file_owner *owner, uint32_t *state,
        __btrc_windows_launch_error_t *error) {
    if (!owner || !owner->live || owner->directory || (owner->access != 1 && owner->access != 2)) abort();
    clear(error); disposals++; *state = 0;
    if (failure == 14) return fail(error, 714, 1);
    exists = 0; *state = 1; return 0;
}
int __btrc_windows_daemon_file_close(__btrc_windows_daemon_file_owner **slot,
        __btrc_windows_launch_error_t *error) {
    clear(error);
    if (!slot || !*slot) return 0;
    __btrc_windows_daemon_file_owner *owner = *slot;
    if (!owner->live) abort();
    closes++;
    if ((failure == 4 || failure == 12) && !owner->directory) return fail(error, 700 + (uint32_t)failure, 2);
    if (failure == 15 && owner->directory) return fail(error, 715, 2);
    owner->live = 0; *slot = NULL; return 0;
}
int __btrc_windows_daemon_directory_next(__btrc_windows_daemon_file_owner *directory, uint32_t restart,
        unsigned char *buffer, size_t capacity, size_t *required,
        __btrc_windows_daemon_directory_entry *entry, __btrc_windows_launch_error_t *error) {
    if (!directory || !directory->live || !directory->directory) abort();
    clear(error); *required = 0; memset(entry, 0, sizeof(*entry));
    if (restart) enumeration_done = enumeration_pending = 0;
    if (!exists || enumeration_done) return 0;
    *required = 8; snapshot(entry);
    if (!buffer) { if (capacity != 0) abort(); enumeration_pending = 1; return 0; }
    if (!enumeration_pending || capacity < 8) abort();
    memcpy(buffer, "control", 8); enumeration_pending = 0; enumeration_done = 1; return 0;
}

int __btrc_windows_daemon_directory_path(__btrc_windows_daemon_file_owner *owner,
        unsigned char *buffer, size_t capacity, size_t *required, __btrc_windows_launch_error_t *error) {
    if (!owner || !owner->live || !owner->directory) abort();
    clear(error); *required = 7;
    if (buffer) {
        if (capacity != 7) abort();
        if (failure == 17) return fail(error, 717, 1);
        memcpy(buffer, "/state", 7);
        if (failure == 18) buffer[2] = 0;
        if (failure == 19) *required = 6;
    } else if (capacity != 0) abort();
    return 0;
}
