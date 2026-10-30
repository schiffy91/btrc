/* Deterministic controller protocol and ownership checks; no Windows execution claim. */
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "windows_os.h"
#include "windows_daemon_image.h"
#define REQUIRE(value) do { if (!(value)) { fprintf(stderr, "scenario=%d line=%d: %s\n", scenario, __LINE__, #value); abort(); } } while (0)
struct file { char name[160], text[160]; size_t size; unsigned id; int exists, flushed; };
struct __btrc_windows_daemon_file_owner { int live, index; uint32_t access; };
struct __btrc_windows_image_owner { int live; };
static struct __btrc_windows_image_owner image;
static struct __btrc_windows_daemon_file_owner owners[16];
static struct file files[160];
static int scenario, file_count, transfers, verifications, image_closes, file_closes, probes, directories;
static unsigned next_id;
static char token_line[34], record[80];
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

void controllerPolicySetup(int value) {
    scenario = value;
    strcpy(token_line, "000102030405060708090a0b0c0d0e0f\n");
    snprintf(record, sizeof(record), "btrc-daemon-v1\n%s123\n", token_line);
    if (scenario == 10 || scenario == 14 || (scenario >= 18 && scenario <= 21))
        add("control", scenario == 10 || scenario == 21 ? "foreign\n" : record);
}
int __btrc_windows_daemon_directory_open(const unsigned char *path, size_t size, uint32_t create,
        __btrc_windows_daemon_file_owner **out, __btrc_windows_launch_error_t *error) {
    REQUIRE(size == 8 && !memcmp(path, "C:\\state", 8) && create == 0);
    clear(error); *out = NULL; directories++;
    if (scenario == 24) return fail(error, 5, 0);
    *out = acquire(-1, 0); return 0;
}
int __btrc_windows_daemon_directory_path(__btrc_windows_daemon_file_owner *owner,
        unsigned char *buffer, size_t capacity, size_t *required, __btrc_windows_launch_error_t *error) {
    owner_check(owner); REQUIRE(owner->index == -1); clear(error); *required = 9;
    if (buffer) { REQUIRE(capacity >= 9); memcpy(buffer, "C:\\state", 9); }
    else REQUIRE(capacity == 0);
    return 0;
}
int __btrc_windows_daemon_control_open_at(__btrc_windows_daemon_file_owner *directory,
        const unsigned char *bytes, size_t size, uint32_t access,
        const __btrc_windows_daemon_directory_entry *expected,
        __btrc_windows_daemon_file_owner **out, __btrc_windows_launch_error_t *error) {
    owner_check(directory); REQUIRE(directory->index == -1 && size < 160);
    char name[160]; memcpy(name, bytes, size); name[size] = 0;
    int index = find(name); clear(error); *out = NULL;
    if (scenario == 25) return fail(error, 5, 0);
    if (scenario == 19 && strstr(name, ".stop") && access == 0) {
        files[find("control")].exists = 0; return fail(error, 5, 0);
    }
    if (access == 1) {
        REQUIRE(expected == NULL);
        if (scenario == 18 && strstr(name, ".stop")) {
            files[find("control")].exists = 0; return fail(error, 5, 0);
        }
        if (index >= 0) return fail(error, 80, 0);
        index = add(name, ""); files[index].flushed = 0;
    } else if (index < 0) return fail(error, 2, 0);
    if (expected) {
        __btrc_windows_daemon_directory_entry actual; snapshot(index, &actual);
        if (expected->present != 1 || expected->kind != 0 || expected->volume != actual.volume
                || memcmp(expected->file_id, actual.file_id, 16)) return fail(error, 1234, 0);
    }
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
    struct file *file = &files[owner->index]; file->flushed = 1;
    if (strstr(file->name, ".probe.")) {
        REQUIRE(!strcmp(file->text, token_line)); probes++;
        if (scenario != 7) {
            char ack[180]; snprintf(ack, sizeof(ack), "%s.ack", file->name);
            add(ack, scenario == 26 ? "wrong\n" : token_line);
        }
        if (scenario == 15) files[find("control")].id++;
    } else if (strstr(file->name, ".stop")) {
        REQUIRE(!strcmp(file->text, token_line));
        if (scenario == 20) files[find("control")].id++;
        else if (scenario != 14) files[find("control")].exists = 0;
    } else abort();
    return 0;
}
int __btrc_windows_daemon_file_dispose(__btrc_windows_daemon_file_owner *owner, uint32_t *state,
        __btrc_windows_launch_error_t *error) {
    owner_check(owner); REQUIRE(owner->index >= 0 && (owner->access == 1 || owner->access == 2));
    REQUIRE(strcmp(files[owner->index].name, "control")); clear(error);
    files[owner->index].exists = 0; *state = 1; return 0;
}
int __btrc_windows_daemon_file_close(__btrc_windows_daemon_file_owner **slot, __btrc_windows_launch_error_t *error) {
    clear(error); if (!slot || !*slot) return 0;
    owner_check(*slot); file_closes++;
    if (scenario == 17 && (*slot)->index >= 0 && probes) return fail(error, 717, 2);
    if (scenario == 27 && (*slot)->index == -1 && transfers) return fail(error, 727, 2);
    (*slot)->live = 0; *slot = NULL; return 0;
}
int __btrc_windows_daemon_log_open(const unsigned char *path, size_t size,
        __btrc_windows_daemon_file_owner **out, __btrc_windows_launch_error_t *error) {
    REQUIRE(size == 12 && !memcmp(path, "C:\\state\\log", 12)); clear(error); *out = NULL;
    if (scenario == 12) return fail(error, 5, 0);
    *out = acquire(-2, 0); return 0;
}
int __btrc_windows_supervisor_image_verify(__btrc_windows_image_owner **out, __btrc_windows_launch_error_t *error) {
    REQUIRE(verifications++ == 0); clear(error); *out = NULL;
    if (scenario == 9) return fail(error, 709, 0);
    image.live = 1; *out = &image; return 0;
}
int __btrc_windows_supervisor_image_close(__btrc_windows_image_owner **slot, __btrc_windows_launch_error_t *error) {
    clear(error); if (!*slot) return 0;
    REQUIRE(*slot == &image && image.live); image_closes++;
    if (scenario == 16) { REQUIRE(image_closes == 1); return fail(error, 716, 2); }
    if (scenario == 23 && image_closes == 1) return fail(error, 723, 1);
    image.live = 0; *slot = NULL; return 0;
}
int __btrc_windows_supervisor_transfer(const __btrc_windows_image_owner *owner,
        const __btrc_windows_daemon_startup *startup, const unsigned char token[16], uint64_t timeout,
        __btrc_windows_transfer_result *result, __btrc_windows_launch_error_t *error) {
    REQUIRE(owner == &image && image.live && transfers++ == 0 && timeout == 3000);
    REQUIRE(!strcmp(startup->name_utf8, "worker"));
    REQUIRE(!strcmp(startup->control_path_utf8, "C:\\state\\control") && !strcmp(startup->log_path_utf8, "C:\\state\\log"));
    REQUIRE(!strcmp(startup->command.executable_utf8, "tool.exe") && startup->command.argc == 3);
    REQUIRE(!strcmp(startup->command.argv_utf8[0], "tool.exe") && !strcmp(startup->command.argv_utf8[1], "a b"));
    REQUIRE(!strcmp(startup->command.argv_utf8[2], "") && startup->command.argv_utf8[3] == NULL);
    REQUIRE(!strcmp(startup->command.cwd_utf8, "C:\\work") && startup->auto_restart == 1);
    REQUIRE(startup->command.override_count == 0 && startup->command.unset_count == 0);
    clear(error); memset(result, 0, sizeof(*result)); result->supervisor_pid = 123;
    if (scenario == 8) { result->state = 1; return fail(error, 708, 1); }
    for (int i = 0; i < 16; i++) snprintf(token_line + i * 2, 3, "%02x", token[i]);
    token_line[32] = '\n'; token_line[33] = 0;
    snprintf(record, sizeof(record), "btrc-daemon-v1\n%s%d\n", token_line, scenario == 5 ? 456 : 123);
    if (scenario == 4) record[14] = record[14] == '0' ? '1' : '0';
    if (scenario != 3 && scenario != 6) add("control", record);
    if ((scenario >= 2 && scenario <= 5) || scenario == 26) { result->state = 2; return fail(error, 702, 1); }
    return 0;
}
int controllerPolicyCleanupCalls(void) { return image_closes + file_closes; }

void controllerPolicyVerify(void) {
    int no_transfer = scenario == 9 || scenario == 10 || scenario == 11 || scenario == 12 || scenario == 13
        || scenario == 14 || (scenario >= 18 && scenario <= 21) || scenario == 24 || scenario == 25;
    REQUIRE(transfers == !no_transfer);
    REQUIRE(verifications == (no_transfer && scenario != 9 ? 0 : 1));
    if (scenario == 11) REQUIRE(directories == 0);
    if (scenario == 16) REQUIRE(image_closes == 1 && image.live);
    else REQUIRE(!image.live);
    if (scenario != 17 && scenario != 27)
        for (size_t i = 0; i < sizeof(owners) / sizeof(owners[0]); i++) REQUIRE(!owners[i].live);
    if (scenario == 1 || scenario == 2 || scenario == 18 || scenario == 19 || scenario == 23) REQUIRE(find("control") < 0);
    if (scenario == 10) REQUIRE(!strcmp(files[find("control")].text, "foreign\n"));
    if (scenario == 26) { REQUIRE(probes == 1); REQUIRE(file_count == 3 && files[2].exists); }
}
