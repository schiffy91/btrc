/* Private held log/control-file capabilities. Include windows_os.h first.
 * Paths are complete UTF-8 byte strings, never borrowed after the call. The
 * runtime retains every verified ancestor without delete sharing, opens the
 * leaf relative to its parent, and checks the current-user protected ACL.
 * Failure may retain an owner only when native cleanup is uncertain. */
#ifndef BTRC_WINDOWS_DAEMON_FILES_H
#define BTRC_WINDOWS_DAEMON_FILES_H

typedef struct btrc_wos_daemon_file btrc_wos_daemon_file;

int btrc_wos_daemon_log_open(const unsigned char *path, size_t size,
    btrc_wos_daemon_file **out, __btrc_windows_launch_error_t *error);
int btrc_wos_daemon_record_open(const unsigned char *path, size_t size,
    const unsigned char token[16], uint32_t supervisor_pid,
    btrc_wos_daemon_file **out, __btrc_windows_launch_error_t *error);
int btrc_wos_daemon_file_close(btrc_wos_daemon_file **file,
    __btrc_windows_launch_error_t *error);

#endif
