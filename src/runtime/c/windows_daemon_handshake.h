/* Private protocol ordering and authorization state. Native lifecycle owners
 * mark preparation and record verification only after checking their resources;
 * these flags never substitute for image, path, ACL or record verification. */
#ifndef BTRC_WINDOWS_DAEMON_HANDSHAKE_H
#define BTRC_WINDOWS_DAEMON_HANDSHAKE_H

#include "windows_daemon_protocol.h"

enum { BTRC_DAEMON_LAUNCHER = 1, BTRC_DAEMON_SUPERVISOR = 2 };

typedef struct {
    uint32_t role, supervisor_pid, lifetime;
    uint16_t last_type;
    unsigned char token[16];
    int prepared, record_verified, commit_attempted, commit_accepted, ack_received, bootstrap_closed, failed;
} btrc_daemon_handshake;

static inline void btrc_daemon_handshake_clear(btrc_daemon_handshake *state) {
    volatile unsigned char *bytes = (volatile unsigned char *)state;
    for (size_t index = 0; index < sizeof(*state); index++) bytes[index] = 0;
}

static inline int btrc_daemon_handshake_fail(btrc_daemon_handshake *state) {
    state->failed = 1;
    return -1;
}

static inline int btrc_daemon_handshake_start(btrc_daemon_handshake *state,
        uint32_t role, uint32_t supervisor_pid, uint32_t lifetime, const unsigned char *token) {
    memset(state, 0, sizeof(*state));
    if ((role != BTRC_DAEMON_LAUNCHER && role != BTRC_DAEMON_SUPERVISOR)
            || supervisor_pid < 2 || supervisor_pid > INT_MAX || lifetime > 1
            || (role == BTRC_DAEMON_LAUNCHER && token == NULL))
        return btrc_daemon_handshake_fail(state);
    state->role = role;
    state->supervisor_pid = supervisor_pid;
    state->lifetime = lifetime;
    if (token != NULL) memcpy(state->token, token, sizeof(state->token));
    return 0;
}

static inline int btrc_daemon_token_matches(const unsigned char first[16], const unsigned char second[16]) {
    unsigned int difference = 0;
    for (size_t index = 0; index < 16; index++) difference |= first[index] ^ second[index];
    return difference == 0;
}

/* sending is true immediately before a write is attempted, not after it
 * succeeds. Every frame must first pass the wire codec's complete validation.
 * Receive calls occur only after the full frame has been decoded.
 * Return 1 for an authenticated channel's pre-COMMIT ERROR, -1 for a protocol
 * violation, and 0 for a permitted outgoing or incoming message. */
static inline int btrc_daemon_handshake_message(btrc_daemon_handshake *state,
        const btrc_daemon_frame *frame, int sending) {
    if (state->failed || frame == NULL
            || (state->role != BTRC_DAEMON_LAUNCHER && state->role != BTRC_DAEMON_SUPERVISOR))
        return btrc_daemon_handshake_fail(state);
    uint16_t kind = frame->type;
    if (kind == BTRC_DAEMON_ERROR) {
        if (state->last_type >= BTRC_DAEMON_COMMIT) return btrc_daemon_handshake_fail(state);
        state->failed = 1;
        return sending ? 0 : 1;
    }
    int launcher_sends = kind == BTRC_DAEMON_INIT || kind == BTRC_DAEMON_COMMIT;
    if (kind != state->last_type + 1 || kind > BTRC_DAEMON_ACK
            || sending != ((state->role == BTRC_DAEMON_LAUNCHER) == launcher_sends))
        return btrc_daemon_handshake_fail(state);
    if (kind == BTRC_DAEMON_INIT) {
        if (state->role == BTRC_DAEMON_LAUNCHER) {
            if (frame->lifetime != state->lifetime || !btrc_daemon_token_matches(frame->token, state->token))
                return btrc_daemon_handshake_fail(state);
        } else {
            state->lifetime = frame->lifetime;
            memcpy(state->token, frame->token, sizeof(state->token));
        }
    }
    if (kind == BTRC_DAEMON_READY || kind == BTRC_DAEMON_ACK) {
        if (frame->supervisor_pid != state->supervisor_pid || frame->lifetime != state->lifetime)
            return btrc_daemon_handshake_fail(state);
    }
    if (kind == BTRC_DAEMON_READY && sending && !state->prepared)
        return btrc_daemon_handshake_fail(state);
    if (kind == BTRC_DAEMON_COMMIT || kind == BTRC_DAEMON_ACK) {
        if (!btrc_daemon_token_matches(frame->token, state->token))
            return btrc_daemon_handshake_fail(state);
    }
    if (kind == BTRC_DAEMON_ACK && sending && !state->record_verified)
        return btrc_daemon_handshake_fail(state);
    state->last_type = kind;
    if (kind == BTRC_DAEMON_COMMIT) {
        if (sending) state->commit_attempted = 1;
        else state->commit_accepted = 1;
    }
    if (kind == BTRC_DAEMON_ACK && !sending) state->ack_received = 1;
    return 0;
}

static inline int btrc_daemon_handshake_prepared(btrc_daemon_handshake *state) {
    if (state->failed || state->role != BTRC_DAEMON_SUPERVISOR || state->last_type != BTRC_DAEMON_INIT)
        return btrc_daemon_handshake_fail(state);
    state->prepared = 1;
    return 0;
}

static inline int btrc_daemon_handshake_record_verified(btrc_daemon_handshake *state) {
    if (state->failed || (state->role == BTRC_DAEMON_SUPERVISOR
            ? !state->commit_accepted : !state->ack_received))
        return btrc_daemon_handshake_fail(state);
    state->record_verified = 1;
    return 0;
}

/* The lifecycle owner calls this only after both endpoints have drained and
 * closed successfully. An ordinary ACK delivery failure does not prevent that
 * cleanup; an uncertain native close never earns this grant. */
static inline int btrc_daemon_handshake_bootstrap_closed(btrc_daemon_handshake *state) {
    if (state->role != BTRC_DAEMON_SUPERVISOR || !state->commit_accepted || !state->record_verified)
        return btrc_daemon_handshake_fail(state);
    state->bootstrap_closed = 1;
    return 0;
}

/* Complete COMMIT, verified publication and completed bootstrap cleanup permit
 * execution even when ACK delivery failed. The lifecycle owner still checks
 * its managed-job and log ownership before spawning. */
static inline int btrc_daemon_handshake_can_run(const btrc_daemon_handshake *state) {
    return state->role == BTRC_DAEMON_SUPERVISOR && state->commit_accepted
        && state->record_verified && state->bootstrap_closed;
}

/* Launcher transfer result: a record alone never confirms success. A lost ACK
 * stays indeterminate here; the public controller's token-bound liveness probe
 * may separately reconcile it without claiming that ACK was received. */
static inline uint32_t btrc_daemon_handshake_result(const btrc_daemon_handshake *state) {
    if (!state->commit_attempted) return 1;
    return state->ack_received && state->record_verified ? 0 : 2;
}

#endif
