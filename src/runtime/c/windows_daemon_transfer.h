/* Private consumer-to-runtime launch ownership. Include windows_os.h first.
 * The image handle and UTF-16 path are borrowed only during open. Every
 * process/job/pipe handle belongs to windows_os.c; none reaches BTRC. */
#ifndef BTRC_WINDOWS_DAEMON_TRANSFER_H
#define BTRC_WINDOWS_DAEMON_TRANSFER_H
#include "windows_bootstrap.h"

typedef struct btrc_wos_transfer btrc_wos_transfer;
int btrc_wos_transfer_open(const uint16_t *image_path, void *verified_image,
    const unsigned char nonces[32], uint64_t deadline, btrc_wos_transfer **out,
    uint32_t *pid, uint32_t *lifetime, __btrc_windows_launch_error_t *error);
int btrc_wos_transfer_resume(btrc_wos_transfer *owner, __btrc_windows_launch_error_t *error);
btrc_wos_bootstrap_pipe *btrc_wos_transfer_request(btrc_wos_transfer *owner);
btrc_wos_bootstrap_pipe *btrc_wos_transfer_reply(btrc_wos_transfer *owner);
/* Called immediately before the COMMIT write. Clear only the temporary job's
 * kill-on-close flag, then make all subsequent cleanup non-terminating. */
int btrc_wos_transfer_begin_commit(btrc_wos_transfer *owner, uint64_t deadline,
    __btrc_windows_launch_error_t *error);
/* Before COMMIT: terminate/reap. After an attempted COMMIT: release handles
 * without terminating or waiting for the supervisor. Pending I/O is always
 * cancelled/drained. A timeout retains ownership; uncertain release poisons. */
int btrc_wos_transfer_close(btrc_wos_transfer **owner, uint64_t deadline,
    __btrc_windows_launch_error_t *error);
#endif
