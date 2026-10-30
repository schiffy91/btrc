/* Executes the unchanged BTRC supervisor policy against a deterministic
 * process/file seam. This is policy evidence, not Windows API evidence. */
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "windows_os.h"
#include "windows_daemon_protocol.h"

#define REQUIRE(value) do { if (!(value)) { fprintf(stderr, "scenario=%d line=%d: %s\n", scenario, __LINE__, #value); abort(); } } while (0)
struct __btrc_windows_supervisor_owner { int phase; };
struct file { char name[160], text[160]; size_t size; unsigned id; int exists, flushed; };
struct __btrc_windows_daemon_file_owner { int live, index; uint32_t access; };
static struct __btrc_windows_supervisor_owner supervisor;
static struct __btrc_windows_daemon_file_owner owners[8];
static struct file files[160];
static int scenario, file_count, cursor, pending = -1, spawns, polls, closes, record_removals, answered;
static unsigned next_id;
static const char token[] = "000102030405060708090a0b0c0d0e0f\n";
static const char stop_name[] = "control.000102030405060708090a0b0c0d0e0f.stop";
static const char probe_name[] = "control.000102030405060708090a0b0c0d0e0f.probe.11111111111111111111111111111111";

static void clear(__btrc_windows_launch_error_t *error) { memset(error, 0, sizeof(*error)); }
static int fail(__btrc_windows_launch_error_t *error, uint32_t code, uint32_t owned) {
    clear(error); error->stage = 17; error->domain = 2; error->native_code = code; error->ownership_state = owned; return -1;
}
static int find(const char *name) {
    for (int i = 0; i < file_count; i++) if (files[i].exists && !strcmp(files[i].name, name)) return i;
    return -1;
}
static int add(const char *name, const char *text) {
    REQUIRE(file_count < 160 && find(name) < 0);
    int i = file_count++;
    REQUIRE(strlen(name) < sizeof(files[i].name) && strlen(text) < sizeof(files[i].text));
    strcpy(files[i].name, name); strcpy(files[i].text, text); files[i].size = strlen(text);
    files[i].exists = 1; files[i].flushed = 1; files[i].id = ++next_id; return i;
}
static __btrc_windows_daemon_file_owner *acquire(int index, uint32_t access) {
    for (size_t i = 0; i < sizeof(owners) / sizeof(owners[0]); i++) if (!owners[i].live) {
        owners[i].live = 1; owners[i].index = index; owners[i].access = access; return &owners[i];
    }
    abort();
}
static void snapshot(int index, __btrc_windows_daemon_directory_entry *identity) {
    memset(identity, 0, sizeof(*identity)); identity->present = 1; identity->volume = UINT64_C(0x123456789abcdef0);
    memcpy(identity->file_id + 12, &files[index].id, sizeof(files[index].id));
}
static void owner_check(__btrc_windows_daemon_file_owner *owner) { REQUIRE(owner && owner->live); }

int __btrc_windows_daemon_directory_open(const unsigned char *path, size_t size, uint32_t create,
        __btrc_windows_daemon_file_owner **out, __btrc_windows_launch_error_t *error) {
    REQUIRE(size == 6 && !memcmp(path, "/state", 6) && create == 0 && supervisor.phase == 2);
    clear(error); *out = NULL;
    if (scenario == 14) return fail(error, 5, 0);
    *out = acquire(-1, 0); return 0;
}
int __btrc_windows_daemon_control_open_at(__btrc_windows_daemon_file_owner *directory,
        const unsigned char *bytes, size_t size, uint32_t access,
        const __btrc_windows_daemon_directory_entry *expected,
        __btrc_windows_daemon_file_owner **out, __btrc_windows_launch_error_t *error) {
    owner_check(directory); REQUIRE(directory->index == -1 && size < 160);
    char name[160]; memcpy(name, bytes, size); name[size] = 0;
    int index = find(name); clear(error); *out = NULL;
    if (access == 1) {
        REQUIRE(expected == NULL && supervisor.phase >= 3);
        if (index >= 0) return fail(error, 80, 0);
        index = add(name, ""); files[index].flushed = 0;
    } else if (index < 0) return fail(error, 2, 0);
    if (expected) {
        __btrc_windows_daemon_directory_entry actual; snapshot(index, &actual);
        if (expected->present != 1 || expected->kind != 0 || expected->volume != actual.volume
                || memcmp(expected->file_id, actual.file_id, 16)) return fail(error, 1234, 0);
    }
    if (access == 2 && !strcmp(name, "control")) REQUIRE(supervisor.phase == 5);
    *out = acquire(index, access); return 0;
}
int __btrc_windows_daemon_file_identity(__btrc_windows_daemon_file_owner *owner,
        __btrc_windows_daemon_directory_entry *identity, __btrc_windows_launch_error_t *error) {
    owner_check(owner); REQUIRE(owner->index >= 0); clear(error); snapshot(owner->index, identity); return 0;
}
int __btrc_windows_daemon_file_write(__btrc_windows_daemon_file_owner *owner, uint64_t offset,
        const unsigned char *bytes, size_t size, size_t *transferred, __btrc_windows_launch_error_t *error) {
    owner_check(owner); REQUIRE(owner->index >= 0 && owner->access == 1);
    struct file *file = &files[owner->index]; REQUIRE(offset == file->size && size < sizeof(file->text) - file->size);
    clear(error); size_t count = size > 7 ? 7 : size;
    memcpy(file->text + file->size, bytes, count); file->size += count; file->text[file->size] = 0; *transferred = count; return 0;
}
int __btrc_windows_daemon_file_read(__btrc_windows_daemon_file_owner *owner, uint64_t offset,
        unsigned char *bytes, size_t size, size_t *transferred, __btrc_windows_launch_error_t *error) {
    owner_check(owner); REQUIRE(owner->index >= 0);
    struct file *file = &files[owner->index]; REQUIRE(offset <= file->size);
    clear(error); size_t count = file->size - (size_t)offset;
    if (count > size) count = size;
    if (count > 11) count = 11;
    memcpy(bytes, file->text + (size_t)offset, count); *transferred = count; return 0;
}
int __btrc_windows_daemon_file_flush(__btrc_windows_daemon_file_owner *owner, __btrc_windows_launch_error_t *error) {
    owner_check(owner); REQUIRE(owner->index >= 0 && owner->access == 1); clear(error);
    if (scenario == 15) return fail(error, 715, 1);
    files[owner->index].flushed = 1; return 0;
}
int __btrc_windows_daemon_file_dispose(__btrc_windows_daemon_file_owner *owner, uint32_t *state,
        __btrc_windows_launch_error_t *error) {
    owner_check(owner); REQUIRE(owner->index >= 0 && (owner->access == 1 || owner->access == 2));
    struct file *file = &files[owner->index]; clear(error);
    if (!strcmp(file->name, "control")) { REQUIRE(supervisor.phase == 5 || scenario == 15); record_removals++; }
    if (!strcmp(file->name, probe_name)) {
        char ack[160]; snprintf(ack, sizeof(ack), "%s.ack", probe_name);
        int index = find(ack); REQUIRE(index >= 0 && files[index].flushed && !strcmp(files[index].text, token)); answered++;
    }
    file->exists = 0; *state = 1; return 0;
}
int __btrc_windows_daemon_file_close(__btrc_windows_daemon_file_owner **slot, __btrc_windows_launch_error_t *error) {
    clear(error); if (!slot || !*slot) return 0;
    owner_check(*slot);
    if (scenario == 19 && (*slot)->index >= 0) return fail(error, 719, 2);
    (*slot)->live = 0; *slot = NULL; return 0;
}
int __btrc_windows_daemon_directory_next(__btrc_windows_daemon_file_owner *directory, uint32_t restart,
        unsigned char *buffer, size_t capacity, size_t *required,
        __btrc_windows_daemon_directory_entry *identity, __btrc_windows_launch_error_t *error) {
    owner_check(directory); REQUIRE(directory->index == -1); clear(error);
    if (restart) { cursor = 0; pending = -1; }
    memset(identity, 0, sizeof(*identity)); *required = 0;
    if (pending < 0) {
        while (cursor < file_count && !files[cursor].exists) cursor++;
        if (cursor == file_count) return 0;
        pending = cursor;
    }
    snapshot(pending, identity); *required = strlen(files[pending].name) + 1;
    if (!buffer) { REQUIRE(capacity == 0); return 0; }
    REQUIRE(capacity >= *required); memcpy(buffer, files[pending].name, *required);
    cursor = pending + 1; pending = -1; return 0;
}

int __btrc_windows_supervisor_accept(uint64_t timeout, __btrc_windows_supervisor_owner **out,
        __btrc_windows_launch_error_t *error) {
    REQUIRE(timeout > 0 && supervisor.phase == 0); clear(error); *out = NULL;
    if (scenario == 2) return fail(error, 702, 0);
    supervisor.phase = 1; *out = &supervisor; return 0;
}
int __btrc_windows_supervisor_copy_startup(__btrc_windows_supervisor_owner *owner,
        unsigned char *buffer, size_t capacity, size_t *required, __btrc_windows_launch_error_t *error) {
    REQUIRE(owner == &supervisor && supervisor.phase == 1); clear(error);
    btrc_daemon_init init = {0};
    for (int i = 0; i < 16; i++) init.token[i] = (unsigned char)i;
    init.remaining_startup_ms = 1000;
    init.auto_restart = scenario == 11;
    init.name = (btrc_daemon_text){(const unsigned char *)"worker-long-name", 16};
    init.control_path = (btrc_daemon_text){(const unsigned char *)"/state/control", 14};
    init.log_path = (btrc_daemon_text){(const unsigned char *)"/state/log", 10};
    init.cwd = (btrc_daemon_text){(const unsigned char *)"/state", 6};
    init.executable = (btrc_daemon_text){(const unsigned char *)"app", 3};
    init.arguments = &init.executable; init.argument_count = 1;
    unsigned char frame[512]; size_t written = 0;
    REQUIRE(btrc_daemon_encode_init(&init, frame, sizeof(frame), &written) == 0 && written > 16);
    *required = scenario == 16 ? 39 : written - 16;
    if (buffer) { REQUIRE(capacity >= *required); memcpy(buffer, frame + 16, *required); }
    else REQUIRE(capacity == 0);
    return 0;
}
int __btrc_windows_supervisor_prepare(__btrc_windows_supervisor_owner *owner, __btrc_windows_launch_error_t *error) {
    REQUIRE(owner == &supervisor && supervisor.phase == 1); clear(error); supervisor.phase = 2; return 0;
}
int __btrc_windows_supervisor_ready_wait_commit(__btrc_windows_supervisor_owner *owner, __btrc_windows_launch_error_t *error) {
    REQUIRE(owner == &supervisor && supervisor.phase == 2); clear(error);
    if (scenario == 3) return fail(error, 703, 1);
    supervisor.phase = 3; return 0;
}
int __btrc_windows_supervisor_ack(__btrc_windows_supervisor_owner *owner, uint32_t *delivered,
        __btrc_windows_launch_error_t *error) {
    REQUIRE(owner == &supervisor && supervisor.phase == 3);
    int index = find("control"); REQUIRE(index >= 0 && files[index].flushed);
    REQUIRE(!strncmp(files[index].text, "btrc-daemon-v1\n000102030405060708090a0b0c0d0e0f\n", 48));
    for (size_t i = 0; i < sizeof(owners) / sizeof(owners[0]); i++) REQUIRE(!owners[i].live || owners[i].index != index);
    clear(error); *delivered = 0;
    if (scenario == 6 || scenario == 7) return fail(error, 706, scenario == 7 ? 2 : 1);
    supervisor.phase = 4; *delivered = scenario != 5;
    if (scenario == 10) add(stop_name, token);
    if (scenario == 18) add(stop_name, "ffffffffffffffffffffffffffffffff\n");
    if (scenario == 17) {
        for (int i = 0; i < 140; i++) { char name[32]; snprintf(name, sizeof(name), "unrelated-%d", i); add(name, "foreign\n"); }
        add(probe_name, token);
    }
    return 0;
}
int __btrc_windows_supervisor_spawn_managed(__btrc_windows_supervisor_owner *owner, __btrc_windows_launch_error_t *error) {
    REQUIRE(owner == &supervisor && supervisor.phase == 4); clear(error); spawns++;
    if (scenario == 13) return fail(error, 713, 1);
    if (scenario == 11 && spawns == 2) { REQUIRE(answered == 1); add(stop_name, token); }
    return 0;
}
int __btrc_windows_supervisor_poll_managed(__btrc_windows_supervisor_owner *owner, uint32_t *running,
        uint32_t *code, __btrc_windows_launch_error_t *error) {
    REQUIRE(owner == &supervisor && supervisor.phase == 4 && spawns > 0); clear(error); polls++;
    REQUIRE(polls < 100);
    if (scenario == 12) return fail(error, 712, 1);
    if (scenario == 11 && polls == 1) add(probe_name, token);
    *running = scenario == 17 && !answered; *code = 37; return 0;
}
int __btrc_windows_supervisor_close(__btrc_windows_supervisor_owner **slot, uint64_t timeout,
        __btrc_windows_launch_error_t *error) {
    REQUIRE(timeout > 0 && closes++ == 0); clear(error);
    if (!*slot) return 0;
    REQUIRE(*slot == &supervisor);
    if (scenario == 8) return fail(error, 708, 2);
    supervisor.phase = 5; *slot = NULL;
    if (scenario == 9) { int index = find("control"); REQUIRE(index >= 0); files[index].id++; }
    return 0;
}

int daemon_policy_main(void);
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    scenario = atoi(argv[1]); REQUIRE(scenario >= 1 && scenario <= 19);
    if (scenario == 4) add("control", "foreign record\n");
    int code = daemon_policy_main();
    int normal = scenario == 1 || scenario == 5 || scenario == 17 || scenario == 18;
    REQUIRE(code == (normal ? 37 : scenario == 10 || scenario == 11 ? 0 : 125));
    int never_spawn = scenario == 2 || scenario == 3 || scenario == 4 || scenario == 6 || scenario == 7
        || scenario == 10 || scenario == 14 || scenario == 15 || scenario == 16 || scenario == 19;
    REQUIRE(spawns == (never_spawn ? 0 : scenario == 11 ? 2 : 1));
    REQUIRE(closes == (scenario == 7 ? 0 : 1));
    int retained = scenario == 4 || scenario == 7 || scenario == 8 || scenario == 9 || scenario == 19;
    REQUIRE((find("control") >= 0) == retained);
    if (scenario == 4 || scenario == 7 || scenario == 8 || scenario == 9 || scenario == 19) REQUIRE(record_removals == 0);
    if (scenario == 11 || scenario == 17) REQUIRE(answered == 1);
    if (scenario == 10 || scenario == 11) REQUIRE(find(stop_name) < 0);
    if (scenario == 18) REQUIRE(find(stop_name) >= 0);
    if (scenario == 17) for (int i = 1; i <= 140; i++) REQUIRE(files[i].exists);
    if (!retained) for (size_t i = 0; i < sizeof(owners) / sizeof(owners[0]); i++) REQUIRE(!owners[i].live);
    return 0;
}
