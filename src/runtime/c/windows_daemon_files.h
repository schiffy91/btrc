/* Private held log/control-file capabilities. Include windows_os.h first.
 * Paths are complete UTF-8 byte strings, never borrowed after the call. The
 * runtime retains every verified ancestor without delete sharing, opens the
 * leaf relative to its parent, and checks the current-user protected ACL.
 * Failure may retain an owner only when native cleanup is uncertain. */
#ifndef BTRC_WINDOWS_DAEMON_FILES_H
#define BTRC_WINDOWS_DAEMON_FILES_H

typedef struct btrc_wos_daemon_file btrc_wos_daemon_file;

/* Open a protected directory, optionally creating only its final component.
 * Existing parents need not have the private-leaf ACL, but every ancestor is
 * retained and checked. An existing leaf must already satisfy that ACL; its
 * permissions are never rewritten. Close through daemon_file_close. */
int btrc_wos_daemon_directory_open(const unsigned char *path, size_t size,
    uint32_t create, btrc_wos_daemon_file **out, __btrc_windows_launch_error_t *error);
/* Copy the canonical path obtained from this held directory. required_bytes
 * includes the NUL. A null/zero query succeeds; a short buffer is untouched.
 * The owner retains one immutable path snapshot for query/copy consistency. */
int btrc_wos_daemon_directory_path(btrc_wos_daemon_file *directory,
    unsigned char *buffer, size_t capacity, size_t *required_bytes,
    __btrc_windows_launch_error_t *error);

/* Control files use the same held ancestry and private ACL as verified
 * records. Creation is exclusive and never truncates an existing name.
 * REMOVE grants read plus handle-based disposition, so policy can compare
 * the record while replacements and writers remain excluded. */
enum {
    BTRC_WOS_CONTROL_READ = 0,
    BTRC_WOS_CONTROL_CREATE = 1,
    BTRC_WOS_CONTROL_REMOVE = 2
};
int btrc_wos_daemon_control_open(const unsigned char *path, size_t size,
    uint32_t access, btrc_wos_daemon_file **out, __btrc_windows_launch_error_t *error);
/* Synchronous, offset-based caller-buffer I/O, at most INT_MAX bytes per
 * call. A failed call still reports any bytes transferred. Zero capacity
 * permits a null buffer. Only a newly created control owner permits writes.
 * Flush is explicit; successful write alone does not establish durability. */
int btrc_wos_daemon_file_read(btrc_wos_daemon_file *file, uint64_t offset,
    unsigned char *buffer, size_t capacity, size_t *transferred,
    __btrc_windows_launch_error_t *error);
int btrc_wos_daemon_file_write(btrc_wos_daemon_file *file, uint64_t offset,
    const unsigned char *buffer, size_t size, size_t *transferred,
    __btrc_windows_launch_error_t *error);
int btrc_wos_daemon_file_flush(btrc_wos_daemon_file *file,
    __btrc_windows_launch_error_t *error);
/* Commit POSIX disposition through the held handle; closing this owner
 * removes the name even while other readers hold the old file. No pathname
 * or legacy disposition fallback. state: 0 not committed, 1 committed,
 * 2 indeterminate. Success commits disposition, not release of ownership.
 * A committed/indeterminate owner permits only close; never retry a mutation
 * whose outcome is uncertain. Failure retains ownership for explicit close. */
int btrc_wos_daemon_file_dispose(btrc_wos_daemon_file *file, uint32_t *state,
    __btrc_windows_launch_error_t *error);

int btrc_wos_daemon_log_open(const unsigned char *path, size_t size,
    btrc_wos_daemon_file **out, __btrc_windows_launch_error_t *error);
int btrc_wos_daemon_record_open(const unsigned char *path, size_t size,
    const unsigned char token[16], uint32_t supervisor_pid,
    btrc_wos_daemon_file **out, __btrc_windows_launch_error_t *error);
int btrc_wos_daemon_file_close(btrc_wos_daemon_file **file,
    __btrc_windows_launch_error_t *error);

#endif
