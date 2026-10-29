/* Consumer-only supervisor image capability. The build supplies one strong,
 * immutable metadata definition after hashing the final supervisor bytes.
 * This declaration has no dependency on the Windows SDK. */
#ifndef BTRC_WINDOWS_DAEMON_IMAGE_H
#define BTRC_WINDOWS_DAEMON_IMAGE_H

#include <stddef.h>
#include <stdint.h>
#include "windows_os.h"

typedef struct __btrc_windows_image_owner __btrc_windows_image_owner;
typedef struct {
    unsigned char sha256[32];
    uint32_t protocol;
    const char *abi_utf8;
    const char *basename_utf8;
} __btrc_windows_daemon_metadata_t;
extern const __btrc_windows_daemon_metadata_t __btrc_windows_daemon_metadata;

typedef struct {
    __btrc_windows_launch_options_t command;
    const char *name_utf8, *control_path_utf8, *log_path_utf8;
    uint32_t auto_restart;
} __btrc_windows_daemon_startup;
typedef struct {
    uint32_t state; /* 0 confirmed, 1 failed before COMMIT, 2 indeterminate */
    uint32_t supervisor_pid, lifetime; /* lifetime: 0 independent, 1 contained */
} __btrc_windows_transfer_result;

/* Strings/token are copied for this call. Daemon policy fixes stdio: command
 * input/output options do not create extra mappings. One positive finite
 * budget covers snapshot, launch, handshake, record verification and cleanup.
 * State 2 never authorizes an automatic retry; the controller reconciles the
 * token-bound record and liveness separately. Pending cleanup stays reachable
 * through image; image_close never terminates after COMMIT was attempted. */
int __btrc_windows_supervisor_transfer(const __btrc_windows_image_owner *image,
    const __btrc_windows_daemon_startup *startup, const unsigned char token[16],
    uint64_t startup_timeout_ms, __btrc_windows_transfer_result *result,
    __btrc_windows_launch_error_t *error);


/* out initializes to null. Failure retains an owner only if cleanup is
 * uncertain; ownership_state=2 forbids retry and leaves release to process
 * teardown. Successful admission holds the image and every ancestor against
 * replacement until close. After transfer, pending cleanup retains a live
 * owner (ownership_state=1); image_close polls cleanup without adding a wait
 * budget and may be retried. Uncertain release poisons it (state=2). Calls on
 * one owner, including transfer and close, must not overlap. */
int __btrc_windows_supervisor_image_verify(__btrc_windows_image_owner **out,
    __btrc_windows_launch_error_t *error);
int __btrc_windows_supervisor_image_close(__btrc_windows_image_owner **image,
    __btrc_windows_launch_error_t *error);

#endif
