/* Private runtime-to-runtime bootstrap transport. Include windows_os.h first.
 * Only windows_os.c owns the handles, events and pending buffers. These entries
 * are not part of the generated BTRC ABI. All deadlines are absolute values on
 * the GetTickCount64 clock, shared by every operation in one transfer. Each
 * endpoint has one caller at a time, including during close. */
#ifndef BTRC_WINDOWS_BOOTSTRAP_H
#define BTRC_WINDOWS_BOOTSTRAP_H

#include "windows_daemon_handshake.h"

typedef struct btrc_wos_bootstrap_pipe btrc_wos_bootstrap_pipe;

/* Exact reserved UTF-16 invocation, without its NUL. image_units describes the
 * quoted executable starting at command[1]. No handles are acquired here. */
int btrc_wos_bootstrap_invocation(const uint16_t *command, size_t units,
    size_t *image_units, uintptr_t *request, uintptr_t *reply);

/* Supervisor-only admission from GetCommandLineW. Check the five inherited
 * handles and clear inheritance before adopting the two pipe ends. The CRT
 * retains its three standard handles. Failed cleanup retains opaque owners. */
int btrc_wos_bootstrap_admit(btrc_wos_bootstrap_pipe **request,
    btrc_wos_bootstrap_pipe **reply, __btrc_windows_launch_error_t *error);

typedef struct {
    unsigned char *bytes;
    size_t size;
    btrc_daemon_frame frame;
} btrc_wos_bootstrap_message;

/* Framed exchange enforces ordering before sending and after fully receiving.
 * Incoming views borrow message->bytes until release. Receive requires an empty
 * message; release it before reuse. Lifecycle callers mark
 * prepared/record_verified only after performing their native checks. */
int btrc_wos_bootstrap_send_init(btrc_wos_bootstrap_pipe *pipe,
    btrc_daemon_handshake *state, const btrc_daemon_init *startup,
    uint64_t deadline, __btrc_windows_launch_error_t *error);
int btrc_wos_bootstrap_send_signal(btrc_wos_bootstrap_pipe *pipe,
    btrc_daemon_handshake *state, const btrc_daemon_frame *frame,
    uint64_t deadline, __btrc_windows_launch_error_t *error);
int btrc_wos_bootstrap_receive(btrc_wos_bootstrap_pipe *pipe,
    btrc_daemon_handshake *state, btrc_wos_bootstrap_message *message,
    uint64_t deadline, __btrc_windows_launch_error_t *error);
void btrc_wos_bootstrap_message_release(btrc_wos_bootstrap_message *message);

/* The image owner supplies fresh cryptographic randomness for each pipe name,
 * never the control token.
 * Both endpoints are overlapped, non-inheritable and private to the current
 * user. A failed cleanup retains its owner in the corresponding output. */
int btrc_wos_bootstrap_pair(const unsigned char nonce[16],
    btrc_wos_bootstrap_pipe **reader, btrc_wos_bootstrap_pipe **writer,
    __btrc_windows_launch_error_t *error);

/* Copy caller data into runtime-owned storage before issuing I/O. A read copies
 * nothing to its caller until the entire request completes. On any failure the
 * endpoint admits only close; pending storage survives a timeout. A partial
 * write is never reported as a complete transfer. */
int btrc_wos_bootstrap_read(btrc_wos_bootstrap_pipe *pipe, unsigned char *buffer,
    size_t size, uint64_t deadline, __btrc_windows_launch_error_t *error);
int btrc_wos_bootstrap_write(btrc_wos_bootstrap_pipe *pipe, const unsigned char *buffer,
    size_t size, uint64_t deadline, __btrc_windows_launch_error_t *error);

/* Cancel and drain within the deadline, then release. A timeout keeps the
 * owner live for another close; an uncertain native close poisons it and must
 * not be retried. Success nulls the pointer; closing NULL is idempotent. */
int btrc_wos_bootstrap_close(btrc_wos_bootstrap_pipe **pipe, uint64_t deadline,
    __btrc_windows_launch_error_t *error);

#endif
