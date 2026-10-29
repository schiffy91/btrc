/* Portable protocol-state checks; native pipe exchange is tested separately. */
#include <stdio.h>
#include <string.h>
#include "windows_daemon_handshake.h"

#define CHECK(expression) do { if (!(expression)) { \
    fprintf(stderr, "handshake check failed at line %d: %s\n", __LINE__, #expression); return 1; \
} } while (0)

static const unsigned char token[16] = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 };

static btrc_daemon_frame frame(uint16_t kind) {
    btrc_daemon_frame value;
    memset(&value, 0, sizeof(value));
    value.type = kind;
    value.supervisor_pid = 42;
    value.lifetime = 1;
    memcpy(value.token, token, sizeof(token));
    return value;
}

static int exchange(btrc_daemon_handshake *launcher, btrc_daemon_handshake *supervisor, uint16_t kind) {
    btrc_daemon_frame value = frame(kind);
    int from_launcher = kind == BTRC_DAEMON_INIT || kind == BTRC_DAEMON_COMMIT;
    int first = btrc_daemon_handshake_message(from_launcher ? launcher : supervisor, &value, 1);
    int second = btrc_daemon_handshake_message(from_launcher ? supervisor : launcher, &value, 0);
    return first == 0 && second == 0 ? 0 : -1;
}

static int ready(btrc_daemon_handshake *launcher, btrc_daemon_handshake *supervisor) {
    CHECK(btrc_daemon_handshake_start(launcher, BTRC_DAEMON_LAUNCHER, 42, 1, token) == 0);
    CHECK(btrc_daemon_handshake_start(supervisor, BTRC_DAEMON_SUPERVISOR, 42, 0, NULL) == 0);
    CHECK(exchange(launcher, supervisor, BTRC_DAEMON_INIT) == 0);
    CHECK(btrc_daemon_handshake_prepared(supervisor) == 0);
    CHECK(exchange(launcher, supervisor, BTRC_DAEMON_READY) == 0);
    return 0;
}

static int happy(void) {
    btrc_daemon_handshake launcher, supervisor;
    CHECK(ready(&launcher, &supervisor) == 0);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    CHECK(btrc_daemon_handshake_result(&launcher) == 1);
    CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_COMMIT) == 0);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    CHECK(btrc_daemon_handshake_result(&launcher) == 2);
    CHECK(btrc_daemon_handshake_record_verified(&supervisor) == 0);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_ACK) == 0);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    CHECK(btrc_daemon_handshake_bootstrap_closed(&supervisor) == 0);
    CHECK(btrc_daemon_handshake_can_run(&supervisor));
    CHECK(btrc_daemon_handshake_result(&launcher) == 2);
    CHECK(btrc_daemon_handshake_record_verified(&launcher) == 0);
    CHECK(btrc_daemon_handshake_result(&launcher) == 0);
    btrc_daemon_handshake_clear(&launcher);
    btrc_daemon_handshake_clear(&supervisor);
    const unsigned char *bytes = (const unsigned char *)&supervisor;
    for (size_t index = 0; index < sizeof(supervisor); index++) CHECK(bytes[index] == 0);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    return 0;
}

static int identity(void) {
    for (int index = 0; index < 16; index++) {
        btrc_daemon_handshake launcher, supervisor;
        CHECK(ready(&launcher, &supervisor) == 0);
        btrc_daemon_frame wrong = frame(BTRC_DAEMON_COMMIT);
        wrong.token[index] ^= 0x80;
        CHECK(btrc_daemon_handshake_message(&supervisor, &wrong, 0) == -1);
        CHECK(!supervisor.commit_accepted && !btrc_daemon_handshake_can_run(&supervisor));
        CHECK(btrc_daemon_handshake_message(&launcher, &wrong, 1) == -1);
        CHECK(btrc_daemon_handshake_result(&launcher) == 1);
        CHECK(ready(&launcher, &supervisor) == 0);
        CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_COMMIT) == 0);
        wrong.type = BTRC_DAEMON_ACK;
        CHECK(btrc_daemon_handshake_message(&launcher, &wrong, 0) == -1);
        CHECK(!launcher.ack_received && btrc_daemon_handshake_result(&launcher) == 2);
    }
    for (int mismatch = 0; mismatch < 2; mismatch++) {
        for (int ack = 0; ack < 2; ack++) {
            btrc_daemon_handshake launcher, supervisor;
            CHECK(ready(&launcher, &supervisor) == 0);
            btrc_daemon_frame wrong = frame(ack ? BTRC_DAEMON_ACK : BTRC_DAEMON_READY);
            if (ack) CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_COMMIT) == 0);
            else launcher.last_type = BTRC_DAEMON_INIT;
            if (mismatch) wrong.lifetime = 0;
            else wrong.supervisor_pid++;
            CHECK(btrc_daemon_handshake_message(&launcher, &wrong, 0) == -1);
            CHECK(btrc_daemon_handshake_result(&launcher) == (ack ? 2u : 1u));
        }
    }
    return 0;
}

static int ordering(void) {
    btrc_daemon_handshake launcher, supervisor;
    CHECK(ready(&launcher, &supervisor) == 0);
    CHECK(btrc_daemon_handshake_bootstrap_closed(&supervisor) == -1);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    CHECK(ready(&launcher, &supervisor) == 0);
    CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_COMMIT) == 0);
    CHECK(btrc_daemon_handshake_bootstrap_closed(&supervisor) == -1);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    CHECK(btrc_daemon_handshake_start(&supervisor, BTRC_DAEMON_SUPERVISOR, 42, 0, NULL) == 0);
    CHECK(btrc_daemon_handshake_prepared(&supervisor) == -1);
    CHECK(btrc_daemon_handshake_start(&launcher, BTRC_DAEMON_LAUNCHER, 42, 1, token) == 0);
    CHECK(btrc_daemon_handshake_start(&supervisor, BTRC_DAEMON_SUPERVISOR, 42, 0, NULL) == 0);
    CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_INIT) == 0);
    btrc_daemon_frame value = frame(BTRC_DAEMON_READY);
    CHECK(btrc_daemon_handshake_message(&supervisor, &value, 1) == -1);
    CHECK(ready(&launcher, &supervisor) == 0);
    CHECK(btrc_daemon_handshake_record_verified(&supervisor) == -1);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    CHECK(ready(&launcher, &supervisor) == 0);
    CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_COMMIT) == 0);
    CHECK(btrc_daemon_handshake_record_verified(&launcher) == -1);
    CHECK(btrc_daemon_handshake_result(&launcher) == 2);
    value = frame(BTRC_DAEMON_ACK);
    CHECK(btrc_daemon_handshake_message(&supervisor, &value, 1) == -1);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    for (int kind = BTRC_DAEMON_INIT; kind <= BTRC_DAEMON_ACK; kind++) {
        CHECK(ready(&launcher, &supervisor) == 0);
        if (kind >= BTRC_DAEMON_COMMIT) CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_COMMIT) == 0);
        if (kind == BTRC_DAEMON_ACK) {
            CHECK(btrc_daemon_handshake_record_verified(&supervisor) == 0);
            CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_ACK) == 0);
        }
        value = frame((uint16_t)kind);
        CHECK(btrc_daemon_handshake_message(&launcher, &value, 0) == -1);
        CHECK(btrc_daemon_handshake_message(&supervisor, &value, 1) == -1);
    }
    return 0;
}

static int failure(void) {
    btrc_daemon_handshake launcher, supervisor;
    btrc_daemon_frame error = frame(BTRC_DAEMON_ERROR);
    CHECK(ready(&launcher, &supervisor) == 0);
    CHECK(btrc_daemon_handshake_message(&launcher, &error, 0) == 1);
    CHECK(btrc_daemon_handshake_result(&launcher) == 1);
    CHECK(ready(&launcher, &supervisor) == 0);
    btrc_daemon_frame commit = frame(BTRC_DAEMON_COMMIT);
    CHECK(btrc_daemon_handshake_message(&launcher, &commit, 1) == 0);
    CHECK(btrc_daemon_handshake_fail(&launcher) == -1);
    CHECK(btrc_daemon_handshake_result(&launcher) == 2);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    CHECK(ready(&launcher, &supervisor) == 0);
    CHECK(exchange(&launcher, &supervisor, BTRC_DAEMON_COMMIT) == 0);
    CHECK(btrc_daemon_handshake_message(&launcher, &error, 0) == -1);
    CHECK(btrc_daemon_handshake_result(&launcher) == 2);
    CHECK(btrc_daemon_handshake_record_verified(&supervisor) == 0);
    btrc_daemon_frame ack = frame(BTRC_DAEMON_ACK);
    CHECK(btrc_daemon_handshake_message(&supervisor, &ack, 1) == 0);
    CHECK(btrc_daemon_handshake_fail(&supervisor) == -1);
    CHECK(!btrc_daemon_handshake_can_run(&supervisor));
    CHECK(btrc_daemon_handshake_bootstrap_closed(&supervisor) == 0);
    CHECK(btrc_daemon_handshake_can_run(&supervisor));
    CHECK(btrc_daemon_handshake_result(&launcher) == 2);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    int status = strcmp(argv[1], "happy") == 0 ? happy()
        : strcmp(argv[1], "identity") == 0 ? identity()
        : strcmp(argv[1], "ordering") == 0 ? ordering()
        : strcmp(argv[1], "failure") == 0 ? failure() : 2;
    if (status == 0) printf("windows-daemon-handshake %s PASS\n", argv[1]);
    return status;
}
