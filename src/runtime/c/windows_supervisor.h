/* Supervisor runtime entry points, shared with its native harness. Include
 * windows_os.h first. The BTRC runtime catalog will expose this seam together
 * with preparation, commit and managed-process ownership. No SDK type crosses
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

/* Cancel/drain bootstrap operations and scrub startup storage. Only complete
 * release nulls *owner; live native I/O is never freed on timeout. A retained
 * poisoned owner must be left to process teardown, not retried. */
int __btrc_windows_supervisor_close(__btrc_windows_supervisor_owner **owner,
    uint64_t timeout_ms, __btrc_windows_launch_error_t *error);

#endif
