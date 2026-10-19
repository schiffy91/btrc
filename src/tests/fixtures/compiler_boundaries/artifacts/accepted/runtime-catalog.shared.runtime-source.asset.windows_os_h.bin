/* SDK-free declarations of the separately compiled Windows runtime object
 * windows_os.c (docs/design/windows-os-services.md, "Requests to Claude").
 *
 * Each section below is pasted into an emitted unit like any runtime helper,
 * and windows_os.c includes this file, so both sides compile the same text.
 * Nothing here names an SDK type or macro: emitted user C never sees
 * windows.h. The manifest's [[external_objects]] row binds these sections to
 * windows_os.c, which every build driver compiles and links whole when an
 * emitted unit retains one of them. */
/* btrc-runtime-helper:begin __btrc_windows_launch_types */
/* The launch seam's records. Strings are NUL-terminated UTF-8 borrowed for
 * the call; the runtime copies everything it keeps before __btrc_windows_launch
 * returns and never writes through these pointers.
 *
 * stdin_mode: 0 = the NUL device, 1 = the parent's stdin; nonempty stdin_bytes
 * is a separate source and cannot combine with 1. stdout_mode/stderr_mode:
 * 0 = collect, 1 = stream to the parent's stream, 2 = combine into stdout
 * (stderr only, with stdout collected), 3 = suppress. These equal the public
 * ChildStdin and CommandOutput values.
 *
 * Result state: 0 running, 1 exited, 2 timed out, 3 capture limit, 4 capture
 * I/O failed; launch_failed stays 0, since a launch that fails returns no
 * owner to wait on. Error stage: 0 none, 1 validation, 2 UTF
 * conversion, 3 allocation, 4 executable not found, 5 executable refused (not
 * a launchable PE image), 6 stdio setup, 7 attribute list, 8 job setup,
 * 9 CreateProcessW, 10 job assignment, 11 resume, 12 pipe I/O, 13 wait,
 * 14 termination, 15 unsupported host, 16 environment, 17 working directory,
 * 18 buffer capacity. Error domain: 0 none, 1 validation, 2 Win32
 * (native_code is the GetLastError value), 4 runtime refusal. Ownership
 * state: 0 none or released, 1 a live owner is retained, 2 poisoned. */
typedef struct __btrc_windows_launch_owner_t __btrc_windows_launch_owner_t;
typedef struct {
    char *executable_utf8;
    char **argv_utf8;
    size_t argc;
    char *cwd_utf8;
    char **environment_overrides_utf8;
    size_t override_count;
    char **environment_unsets_utf8;
    size_t unset_count;
    unsigned char *stdin_bytes;
    size_t stdin_size;
    uint32_t stdin_mode;
    uint32_t stdout_mode;
    uint32_t stderr_mode;
    size_t stdout_limit;
    size_t stderr_limit;
} __btrc_windows_launch_options_t;
typedef struct {
    uint32_t stage;
    uint32_t domain;
    uint32_t native_code;
    uint32_t ownership_state;
} __btrc_windows_launch_error_t;
typedef struct {
    uint32_t state;
    uint32_t native_exit_code;
    uint32_t has_exit_code;
    uint32_t launch_failed;
    uint32_t timed_out;
    uint32_t capture_exceeded;
    uint32_t capture_failed;
    uint64_t stdout_bytes_seen;
    uint64_t stderr_bytes_seen;
    size_t stdout_bytes_retained;
    size_t stderr_bytes_retained;
} __btrc_windows_launch_result_t;
/* btrc-runtime-helper:end __btrc_windows_launch_types */
/* btrc-runtime-helper:begin __btrc_windows_launch */
/* Resolve, validate and start one child, suspended inside a new
 * kill-on-close job, then resume it. Returns 0 with *out set, or nonzero with
 * *out NULL and *error describing the first failure. */
int __btrc_windows_launch(const __btrc_windows_launch_options_t *options,
    __btrc_windows_launch_owner_t **out, __btrc_windows_launch_error_t *error);
/* btrc-runtime-helper:end __btrc_windows_launch */
/* btrc-runtime-helper:begin __btrc_windows_launch_wait */
/* wait_mode 0 polls, 1 waits until the child completes or timeout_ms
 * (positive) expires, killing the whole job at expiry, 2 waits without a
 * deadline. Returns 0 when *result describes the launch. */
int __btrc_windows_launch_wait(__btrc_windows_launch_owner_t *launch,
    uint32_t wait_mode, uint64_t timeout_ms,
    __btrc_windows_launch_result_t *result,
    __btrc_windows_launch_error_t *error);
/* btrc-runtime-helper:end __btrc_windows_launch_wait */
/* btrc-runtime-helper:begin __btrc_windows_launch_copy_output */
/* Copy a completed launch's retained bytes of stream 1 (stdout) or 2
 * (stderr). *written reports the retained size; a NULL buffer with zero
 * capacity only queries it, and a smaller buffer copies nothing and fails. */
int __btrc_windows_launch_copy_output(__btrc_windows_launch_owner_t *launch,
    uint32_t stream, unsigned char *buffer, size_t capacity, size_t *written);
/* btrc-runtime-helper:end __btrc_windows_launch_copy_output */
/* btrc-runtime-helper:begin __btrc_windows_launch_terminate */
/* Terminate the launch's whole job with exit_code. Idempotent. */
int __btrc_windows_launch_terminate(__btrc_windows_launch_owner_t *launch,
    uint32_t exit_code, __btrc_windows_launch_error_t *error);
/* btrc-runtime-helper:end __btrc_windows_launch_terminate */
/* btrc-runtime-helper:begin __btrc_windows_launch_close */
/* Release a launch. An active launch's job is terminated and its I/O
 * cancelled and drained within timeout_ms. Returns 0 and sets *launch NULL
 * only after everything is released; a NULL owner is success. */
int __btrc_windows_launch_close(__btrc_windows_launch_owner_t **launch,
    uint64_t timeout_ms, __btrc_windows_launch_error_t *error);
/* btrc-runtime-helper:end __btrc_windows_launch_close */
/* btrc-runtime-helper:begin __btrc_windows_quote_argv_utf8 */
/* Render argv as the CommandLineToArgvW-compatible command line that
 * __btrc_windows_launch passes to CreateProcessW: argv[0] always quoted and
 * free of '"', every other argument quoted only when empty or when it holds
 * whitespace or '"', with backslashes doubled before a quote. *required_units
 * counts the UTF-16 units including the terminating NUL; a NULL buffer with
 * zero capacity only queries it, and a smaller buffer writes nothing. Never
 * invokes a shell. */
int __btrc_windows_quote_argv_utf8(char **argv, size_t argc,
    uint16_t *buffer, size_t capacity_units, size_t *required_units,
    __btrc_windows_launch_error_t *error);
/* btrc-runtime-helper:end __btrc_windows_quote_argv_utf8 */
