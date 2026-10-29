/* Supervisor runtime entry points, shared with its native harness. Include
 * windows_os.h first. The BTRC runtime catalog will expose this seam together
 * with managed-process ownership. No SDK type crosses
 * this boundary. The caller serializes every operation on one owner. */
#ifndef BTRC_WINDOWS_SUPERVISOR_H
#define BTRC_WINDOWS_SUPERVISOR_H

typedef struct __btrc_windows_supervisor_owner __btrc_windows_supervisor_owner;

/* Admit the inherited bootstrap handles and receive one complete INIT within
 * a positive finite budget. Failure releases acquired resources, or retains
 * *out and reports live/poisoned ownership when cleanup cannot finish. */
int __btrc_windows_supervisor_accept(uint64_t startup_timeout_ms,
    __btrc_windows_supervisor_owner **out, __btrc_windows_launch_error_t *error);

/* Query/copy the canonical INIT payload, without its 16-byte frame header.
 * Includes the token; the caller must scrub its copy. Insufficient capacity
 * reports the required byte count and makes no partial copy. */
int __btrc_windows_supervisor_copy_startup(__btrc_windows_supervisor_owner *owner,
    unsigned char *buffer, size_t capacity, size_t *required_bytes,
    __btrc_windows_launch_error_t *error);

/* Validate and retain the command/environment snapshot, create an unnamed
 * kill-on-close job, hold the private append log, and redirect CRT/native
 * diagnostics to it. No managed command runs during preparation. */
int __btrc_windows_supervisor_prepare(__btrc_windows_supervisor_owner *owner,
    __btrc_windows_launch_error_t *error);

/* READY and the complete authenticated COMMIT share accept's deadline. A
 * failed exchange aborts preparation; no managed command has started. */
int __btrc_windows_supervisor_ready_wait_commit(__btrc_windows_supervisor_owner *owner,
    __btrc_windows_launch_error_t *error);

/* Verify the protected record before ACK. After verification, ordinary ACK
 * loss succeeds with delivered=0. Failed cleanup poisons the retained owner.
 * Success scrubs startup storage, so copy_startup must precede this call. */
int __btrc_windows_supervisor_ack(__btrc_windows_supervisor_owner *owner,
    uint32_t *ack_delivered, __btrc_windows_launch_error_t *error);

/* Cancel/drain bootstrap operations and scrub startup storage. Only complete
 * release nulls *owner; live native I/O is never freed on timeout. A retained
 * poisoned owner must be left to process teardown, not retried. */
int __btrc_windows_supervisor_close(__btrc_windows_supervisor_owner **owner,
    uint64_t timeout_ms, __btrc_windows_launch_error_t *error);

#endif
