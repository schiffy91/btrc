/* A host-side probe of windows_os.c's portable entries, driven by
 * test_windows_launch_seam.py on every host.
 *
 *     quote_probe ARG...    the UTF-16 command line for ARG... as hex units
 *     quote_probe --launch  what a launch reports off Windows
 *
 * Quoting is portable C, so its CommandLineToArgvW contract is checked here
 * without a Windows host; the launch entries report an unsupported host. */
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "windows_os.h"
#include "windows_bootstrap.h"
#include "windows_daemon_transfer.h"

static int file_unsupported(const __btrc_windows_launch_error_t *error, uint32_t ownership) {
    return error->stage == 15 && error->domain == 4 && error->native_code == 0
        && error->ownership_state == ownership;
}

static int daemon_files_off_windows(void) {
#define FILE_REQUIRE(condition) do { if (!(condition)) { fprintf(stderr, "daemon file contract failed at line %d\n", __LINE__); return 1; } } while (0)
    __btrc_windows_launch_error_t error;
    __btrc_windows_daemon_file_owner *sentinel = (__btrc_windows_daemon_file_owner *)(void *)&error;
    __btrc_windows_daemon_file_owner *owner = sentinel;
    FILE_REQUIRE(__btrc_windows_daemon_directory_open(NULL, 0, 1, &owner, &error) != 0
        && owner == NULL && file_unsupported(&error, 0));
    owner = sentinel;
    FILE_REQUIRE(__btrc_windows_daemon_control_open(NULL, 0, 0, &owner, &error) != 0
        && owner == NULL && file_unsupported(&error, 0));
    owner = sentinel;
    FILE_REQUIRE(__btrc_windows_daemon_control_open_at(sentinel, NULL, 0, 0, NULL, &owner, &error) != 0
        && owner == NULL && file_unsupported(&error, 0));
    owner = sentinel;
    FILE_REQUIRE(__btrc_windows_daemon_log_open(NULL, 0, &owner, &error) != 0
        && owner == NULL && file_unsupported(&error, 0));
    owner = sentinel;
    FILE_REQUIRE(__btrc_windows_daemon_record_open(NULL, 0, NULL, 0, &owner, &error) != 0
        && owner == NULL && file_unsupported(&error, 0));
    unsigned char buffer[4] = { 0xA5, 0xA5, 0xA5, 0xA5 };
    const unsigned char untouched[4] = { 0xA5, 0xA5, 0xA5, 0xA5 };
    size_t required = 99;
    FILE_REQUIRE(__btrc_windows_daemon_directory_path(sentinel, buffer, sizeof(buffer), &required, &error) != 0
        && required == 0 && file_unsupported(&error, 1));
    __btrc_windows_daemon_directory_entry entry, zero;
    memset(&entry, 0xA5, sizeof(entry)); memset(&zero, 0, sizeof(zero));
    FILE_REQUIRE(__btrc_windows_daemon_file_identity(sentinel, &entry, &error) != 0
        && memcmp(&entry, &zero, sizeof(entry)) == 0 && file_unsupported(&error, 1));
    memset(&entry, 0xA5, sizeof(entry));
    required = 99;
    FILE_REQUIRE(__btrc_windows_daemon_directory_next(sentinel, 0, buffer, sizeof(buffer), &required, &entry, &error) != 0
        && required == 0 && memcmp(&entry, &zero, sizeof(entry)) == 0 && file_unsupported(&error, 1));
    required = 99;
    FILE_REQUIRE(__btrc_windows_daemon_file_read(sentinel, 0, buffer, sizeof(buffer), &required, &error) != 0
        && required == 0 && file_unsupported(&error, 1));
    required = 99;
    FILE_REQUIRE(__btrc_windows_daemon_file_write(sentinel, 0, buffer, sizeof(buffer), &required, &error) != 0
        && required == 0 && file_unsupported(&error, 1));
    FILE_REQUIRE(memcmp(buffer, untouched, sizeof(buffer)) == 0);
    FILE_REQUIRE(__btrc_windows_daemon_file_flush(sentinel, &error) != 0 && file_unsupported(&error, 1));
    uint32_t state = 99;
    FILE_REQUIRE(__btrc_windows_daemon_file_dispose(sentinel, &state, &error) != 0
        && state == 0 && file_unsupported(&error, 1));
    owner = sentinel;
    FILE_REQUIRE(__btrc_windows_daemon_file_close(&owner, &error) != 0
        && owner == sentinel && file_unsupported(&error, 1));
    owner = NULL;
    FILE_REQUIRE(__btrc_windows_daemon_file_close(&owner, &error) == 0
        && owner == NULL && error.stage == 0 && error.domain == 0 && error.ownership_state == 0);
    puts("daemon files unsupported: PASS");
    return 0;
#undef FILE_REQUIRE
}

static int snapshot_off_windows(void) {
    __btrc_windows_launch_error_t error;
    btrc_wos_startup_snapshot *owner = (btrc_wos_startup_snapshot *)(void *)&error;
    int status = btrc_wos_startup_snapshot_open(NULL, NULL, &owner, &error);
    printf("open=%d owner=%s view=%s stage=%u domain=%u\n", status != 0,
        owner == NULL ? "null" : "set", btrc_wos_startup_snapshot_get(owner) == NULL ? "null" : "set",
        (unsigned)error.stage, (unsigned)error.domain);
    btrc_wos_startup_snapshot_close(&owner);
    return 0;
}

static int transfer_off_windows(void) {
    __btrc_windows_launch_error_t error;
    btrc_wos_transfer *owner = (btrc_wos_transfer *)(void *)&error;
    uint32_t pid = 99, lifetime = 99;
    int opened = btrc_wos_transfer_open(NULL, NULL, NULL, 1000, &owner, &pid, &lifetime, &error);
    int resumed = btrc_wos_transfer_resume(owner, &error);
    int committed = btrc_wos_transfer_begin_commit(owner, 1000, &error);
    printf("open=%d owner=%s pid=%u lifetime=%u resume=%d commit=%d request=%s reply=%s stage=%u domain=%u ",
        opened != 0, owner == NULL ? "null" : "set", (unsigned)pid, (unsigned)lifetime,
        resumed != 0, committed != 0, btrc_wos_transfer_request(owner) == NULL ? "null" : "set",
        btrc_wos_transfer_reply(owner) == NULL ? "null" : "set", (unsigned)error.stage, (unsigned)error.domain);
    printf("close=%d\n", btrc_wos_transfer_close(&owner, 0, &error));
    return 0;
}

static int supervisor_off_windows(void) {
    __btrc_windows_launch_error_t error;
    __btrc_windows_supervisor_owner *owner = (__btrc_windows_supervisor_owner *)(void *)&error;
    int accepted = __btrc_windows_supervisor_accept(1000, &owner, &error);
    size_t required = 99;
    unsigned char output = 0xA5;
    int copied = __btrc_windows_supervisor_copy_startup(owner, &output, 1, &required, &error);
    int prepared = __btrc_windows_supervisor_prepare(owner, &error);
    int committed = __btrc_windows_supervisor_ready_wait_commit(owner, &error);
    uint32_t delivered = 99;
    int acknowledged = __btrc_windows_supervisor_ack(owner, &delivered, &error);
    int spawned = __btrc_windows_supervisor_spawn_managed(owner, &error);
    uint32_t running = 99, code = 99;
    int polled = __btrc_windows_supervisor_poll_managed(owner, &running, &code, &error);
    int terminated = __btrc_windows_supervisor_terminate_managed(owner, 1, &error);
    printf("accept=%d owner=%s copy=%d prepare=%d commit=%d ack=%d delivered=%u spawn=%d poll=%d running=%u code=%u terminate=%d required=%zu output=%u stage=%u domain=%u ",
        accepted != 0, owner == NULL ? "null" : "set", copied != 0, prepared != 0,
        committed != 0, acknowledged != 0, (unsigned)delivered, spawned != 0, polled != 0,
        (unsigned)running, (unsigned)code, terminated != 0, required, (unsigned)output,
        (unsigned)error.stage, (unsigned)error.domain);
    printf("close=%d\n", __btrc_windows_supervisor_close(&owner, 0, &error));
    return 0;
}

/* Read test data from stdin: the command-line limit being tested can exceed
 * the host's per-argument limit after UTF-16 hex encoding. */
static int bootstrap_invocation(void) {
    size_t units = 0, capacity = 128;
    uint16_t *command = (uint16_t *)malloc(capacity * sizeof(*command));
    if (command == NULL) return 2;
    char word[5] = { 0 };
    size_t bytes;
    while ((bytes = fread(word, 1, 4, stdin)) != 0) {
        if (bytes != 4) { free(command); return 2; }
        char *end = NULL;
        unsigned long value = strtoul(word, &end, 16);
        if (end != word + 4 || value > UINT16_MAX) { free(command); return 2; }
        if (units == capacity) {
            if (capacity > SIZE_MAX / sizeof(*command) / 2) { free(command); return 2; }
            capacity *= 2;
            uint16_t *grown = (uint16_t *)realloc(command, capacity * sizeof(*command));
            if (grown == NULL) { free(command); return 2; }
            command = grown;
        }
        command[units++] = (uint16_t)value;
    }
    if (ferror(stdin)) { free(command); return 2; }
    size_t image = 99;
    uintptr_t request = 99, reply = 99;
    int status = btrc_wos_bootstrap_invocation(command, units, &image, &request, &reply);
    printf("%d %zu %" PRIuPTR " %" PRIuPTR "\n", status, image, request, reply);
    free(command);
    return 0;
}

static int launch_off_windows(void) {
    char *arguments[] = { "probe", NULL };
    __btrc_windows_launch_options_t options;
    memset(&options, 0, sizeof(options));
    options.executable_utf8 = arguments[0];
    options.argv_utf8 = arguments;
    options.argc = 1;
    __btrc_windows_launch_owner_t *owner = (__btrc_windows_launch_owner_t *)(void *)&options;
    __btrc_windows_launch_error_t error;
    int status = __btrc_windows_launch(&options, &owner, &error);
    __btrc_windows_launch_result_t result;
    int waited = __btrc_windows_launch_wait(NULL, 2, 0, &result, &error);
    __btrc_windows_launch_error_t closing;
    int closed = __btrc_windows_launch_close(&owner, 0, &closing);
    printf("launch=%d owner=%s stage=%u domain=%u wait=%d close=%d\n", status != 0, owner == NULL ? "null" : "set",
        (unsigned)error.stage, (unsigned)error.domain, waited != 0, closed);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--daemon-files") == 0) return daemon_files_off_windows();
    if (argc == 2 && strcmp(argv[1], "--snapshot") == 0) return snapshot_off_windows();
    if (argc == 2 && strcmp(argv[1], "--transfer") == 0) return transfer_off_windows();
    if (argc == 2 && strcmp(argv[1], "--supervisor") == 0) return supervisor_off_windows();
    if (argc == 2 && strcmp(argv[1], "--bootstrap-invocation") == 0) return bootstrap_invocation();
    if (argc == 2 && strcmp(argv[1], "--launch") == 0) return launch_off_windows();
    size_t required = 0;
    __btrc_windows_launch_error_t error;
    if (__btrc_windows_quote_argv_utf8(argv + 1, (size_t)(argc - 1), NULL, 0, &required, &error) != 0) {
        printf("error stage=%u code=%u\n", (unsigned)error.stage, (unsigned)error.native_code);
        return 0;
    }
    uint16_t *buffer = (uint16_t *)calloc(required, sizeof(uint16_t));
    if (buffer == NULL) return 2;
    if (__btrc_windows_quote_argv_utf8(argv + 1, (size_t)(argc - 1), buffer, required, &required, &error) != 0) {
        printf("error stage=%u code=%u\n", (unsigned)error.stage, (unsigned)error.native_code);
        free(buffer);
        return 0;
    }
    for (size_t index = 0; index + 1 < required; index++) printf("%04x", (unsigned)buffer[index]);
    printf("\nnul=%u\n", (unsigned)buffer[required - 1]);
    free(buffer);
    return 0;
}
