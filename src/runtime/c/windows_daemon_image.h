/* Consumer-only supervisor image capability. The build supplies one strong,
 * immutable metadata definition after hashing the final supervisor bytes.
 * This declaration has no dependency on the Windows SDK. */
#ifndef BTRC_WINDOWS_DAEMON_IMAGE_H
#define BTRC_WINDOWS_DAEMON_IMAGE_H

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

/* out initializes to null. Failure retains an owner only if cleanup is
 * uncertain; ownership_state=2 forbids retry and leaves release to process
 * teardown. Successful admission holds the image and every ancestor against
 * replacement until close. Calls on one owner must not overlap. */
int __btrc_windows_supervisor_image_verify(__btrc_windows_image_owner **out,
    __btrc_windows_launch_error_t *error);
int __btrc_windows_supervisor_image_close(__btrc_windows_image_owner **image,
    __btrc_windows_launch_error_t *error);

#endif
