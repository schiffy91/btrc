/* Exercise the production wire codec without a Windows SDK or handles. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif

#include "windows_daemon_protocol.h"

/* Assertions must execute even when the Windows toolchain defines NDEBUG. */
#define CHECK(expression) do { if (!(expression)) { \
    fprintf(stderr, "check failed at %d: %s\n", __LINE__, #expression); abort(); \
} } while (0)

static btrc_daemon_text text(const char *value) {
    btrc_daemon_text result = { (const unsigned char *)value, strlen(value) };
    return result;
}

static void check_bounds(void) {
    btrc_daemon_text arguments[] = { text("tool.exe"), text("argument") };
    btrc_daemon_init init = {0};
    init.remaining_startup_ms = 3000;
    init.name = text("worker");
    init.control_path = text("C:\\state\\worker.control");
    init.log_path = text("C:\\state\\worker.log");
    init.cwd = text("C:\\work");
    init.executable = arguments[0];
    init.arguments = arguments;
    init.argument_count = 2;
    size_t required = 0;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &required) == 0);
    unsigned char *bytes = malloc(required + 1);
    CHECK(bytes != NULL);
    for (size_t capacity = 0; capacity < required; capacity++) {
        memset(bytes, 0xA5, required + 1);
        size_t written = 123;
        CHECK(btrc_daemon_encode_init(&init, bytes, capacity, &written) != 0);
        CHECK(written == 0);
        for (size_t index = capacity; index <= required; index++) CHECK(bytes[index] == 0xA5);
    }
    size_t written = 0;
    CHECK(btrc_daemon_encode_init(&init, bytes, required, &written) == 0 && written == required);
    btrc_daemon_frame frame;
    for (size_t size = 0; size < required; size++) {
        memset(&frame, 0xA5, sizeof(frame));
        CHECK(btrc_daemon_decode(bytes, size, &frame) != 0);
        btrc_daemon_frame empty;
        memset(&empty, 0, sizeof(empty));
        CHECK(memcmp(&frame, &empty, sizeof(frame)) == 0);
    }
    CHECK(btrc_daemon_decode(bytes, required, &frame) == 0);
    CHECK(frame.arguments.count == 2 && frame.environment.count == 0);
    free(bytes);

    init.remaining_startup_ms = 0;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0 && written == 0);
    init.remaining_startup_ms = 3000;
    init.argument_count = 0;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    init.argument_count = SIZE_MAX;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    init.argument_count = 1;
    init.arguments = NULL;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    init.arguments = arguments;
    init.name.size = SIZE_MAX;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    init.name.data = NULL;
    init.name.size = 1;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    init.name = text("worker");
    init.lifetime = 2;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    init.lifetime = 0;
    init.auto_restart = 2;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    init.auto_restart = 0;
    init.environment_count = 1;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);

    init.environment_count = 0;
    unsigned char *large = malloc(BTRC_DAEMON_MAX_TEXT + 1);
    CHECK(large != NULL);
    memset(large, 'x', BTRC_DAEMON_MAX_TEXT + 1);
    btrc_daemon_text many[16];
    for (size_t index = 0; index < 16; index++) {
        many[index].data = large;
        many[index].size = BTRC_DAEMON_MAX_TEXT;
    }
    init.arguments = many;
    init.argument_count = 16;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0 && written == 0);
    init.arguments = arguments;
    init.argument_count = 1;
    init.name.data = large;
    init.name.size = BTRC_DAEMON_MAX_TEXT + 1;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    init.name.size = BTRC_DAEMON_MAX_TEXT;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) == 0);
    large[0] = 0;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    large[0] = 0xF0;
    init.name.size = 1;
    CHECK(btrc_daemon_encode_init(&init, NULL, 0, &written) != 0);
    free(large);

    btrc_daemon_frame signal = {0};
    for (uint16_t type = BTRC_DAEMON_READY; type <= BTRC_DAEMON_ERROR; type++) {
        signal.type = type;
        signal.supervisor_pid = 42;
        signal.lifetime = 1;
        CHECK(btrc_daemon_encode_signal(&signal, NULL, 0, &required) == 0);
        unsigned char buffer[64];
        for (size_t capacity = 0; capacity < required; capacity++) {
            memset(buffer, 0xA5, sizeof(buffer));
            CHECK(btrc_daemon_encode_signal(&signal, buffer, capacity, &written) != 0 && written == 0);
            for (size_t index = capacity; index < sizeof(buffer); index++) CHECK(buffer[index] == 0xA5);
        }
        CHECK(btrc_daemon_encode_signal(&signal, buffer, required, &written) == 0);
        CHECK(btrc_daemon_decode(buffer, written, &frame) == 0);
    }
    signal.type = BTRC_DAEMON_INIT;
    CHECK(btrc_daemon_encode_signal(&signal, NULL, 0, &written) != 0);
    signal.type = BTRC_DAEMON_ACK;
    signal.supervisor_pid = 1;
    CHECK(btrc_daemon_encode_signal(&signal, NULL, 0, &written) != 0);
    signal.supervisor_pid = UINT32_MAX;
    CHECK(btrc_daemon_encode_signal(&signal, NULL, 0, &written) != 0);
    signal.supervisor_pid = 42;
    signal.lifetime = 2;
    CHECK(btrc_daemon_encode_signal(&signal, NULL, 0, &written) != 0);
    signal.type = BTRC_DAEMON_ERROR;
    signal.ownership_state = 3;
    CHECK(btrc_daemon_encode_signal(&signal, NULL, 0, &written) != 0);
    puts("daemon-protocol bounds PASS");
}

static btrc_daemon_text *decode_vector(btrc_daemon_vector vector) {
    btrc_daemon_text *items = calloc(vector.count + 1, sizeof(*items));
    CHECK(items != NULL);
    btrc_daemon_reader reader = { vector.encoded.data, vector.encoded.size, 1 };
    for (uint32_t index = 0; index < vector.count; index++) items[index] = btrc_daemon_read_text(&reader);
    CHECK(reader.valid && reader.remaining == 0);
    return items;
}

int main(int argc, char **argv) {
#if defined(_WIN32)
    CHECK(_setmode(_fileno(stdin), _O_BINARY) != -1);
    CHECK(_setmode(_fileno(stdout), _O_BINARY) != -1);
#endif
    if (argc == 2 && strcmp(argv[1], "bounds") == 0) { check_bounds(); return 0; }
    size_t capacity = BTRC_DAEMON_HEADER_BYTES + BTRC_DAEMON_MAX_PAYLOAD + 1;
    unsigned char *input = malloc(capacity);
    unsigned char *output = malloc(capacity);
    CHECK(input != NULL && output != NULL);
    size_t size = fread(input, 1, capacity, stdin);
    CHECK(!ferror(stdin));
    /* Exact-sized storage lets ASan catch a read beyond the supplied frame. */
    unsigned char *exact = malloc(size == 0 ? 1 : size);
    CHECK(exact != NULL);
    memcpy(exact, input, size);
    free(input);
    input = exact;
    int status = 2;
    if (argc == 2 && strcmp(argv[1], "header") == 0) {
        uint16_t type = 123;
        uint32_t length = 456;
        if (btrc_daemon_header(input, size, &type, &length) == 0) {
            printf("type=%u size=%u\n", (unsigned)type, (unsigned)length);
            status = 0;
        } else {
            CHECK(type == 0 && length == 0);
        }
    } else {
        btrc_daemon_frame frame;
        if (btrc_daemon_decode(input, size, &frame) == 0) {
            size_t written = 0;
            if (frame.type == BTRC_DAEMON_INIT) {
                btrc_daemon_init init = {0};
                memcpy(init.token, frame.token, 16);
                init.remaining_startup_ms = frame.remaining_startup_ms;
                init.lifetime = frame.lifetime;
                init.auto_restart = frame.auto_restart;
                init.name = frame.name;
                init.control_path = frame.control_path;
                init.log_path = frame.log_path;
                init.cwd = frame.cwd;
                init.executable = frame.executable;
                init.arguments = decode_vector(frame.arguments);
                init.argument_count = frame.arguments.count;
                init.environment = decode_vector(frame.environment);
                init.environment_count = frame.environment.count;
                CHECK(btrc_daemon_encode_init(&init, output, capacity, &written) == 0);
                free((void *)init.arguments);
                free((void *)init.environment);
            } else {
                CHECK(btrc_daemon_encode_signal(&frame, output, capacity, &written) == 0);
            }
            CHECK(fwrite(output, 1, written, stdout) == written);
            status = 0;
        } else {
            btrc_daemon_frame empty;
            memset(&empty, 0, sizeof(empty));
            CHECK(memcmp(&frame, &empty, sizeof(frame)) == 0);
        }
    }
    free(input);
    free(output);
    return status;
}
