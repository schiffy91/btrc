#ifndef BTRC_LOCAL_APPLICATION_CHANNEL_H
#define BTRC_LOCAL_APPLICATION_CHANNEL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    BTRC_LOCAL_APPLICATION_CHANNEL_OPENED = 0,
    BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_INVALID = 1,
    BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_UNSUPPORTED = 2,
    BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_INSECURE_PARENT = 3,
    BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_PATH_CONFLICT = 4,
    BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_ALREADY_RUNNING = 5,
    BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_RESOURCE_FAILED = 6,
};

enum {
    BTRC_LOCAL_APPLICATION_CHANNEL_POLL_REQUEST = 0,
    BTRC_LOCAL_APPLICATION_CHANNEL_POLL_IDLE = 1,
    BTRC_LOCAL_APPLICATION_CHANNEL_POLL_WORK_REMAINS = 2,
    BTRC_LOCAL_APPLICATION_CHANNEL_POLL_CLOSED = 3,
    BTRC_LOCAL_APPLICATION_CHANNEL_POLL_INVALID_BUFFER = 4,
    BTRC_LOCAL_APPLICATION_CHANNEL_POLL_FAILED = 5,
};

enum {
    BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_QUEUED = 0,
    BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_STALE = 1,
    BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_TOO_LARGE = 2,
    BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_CLOSED = 3,
    BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_INVALID = 4,
    BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_RESOURCE_FAILED = 5,
};

enum {
    BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_COMPLETED = 0,
    BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_INVALID = 1,
    BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_UNSUPPORTED = 2,
    BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_UNAVAILABLE = 3,
    BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_TIMED_OUT = 4,
    BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_PROTOCOL_FAILED = 5,
    BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_RESPONSE_TOO_LARGE = 6,
    BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_SECURITY_REJECTED = 7,
    BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_IO_FAILED = 8,
};

int std_local_application_channel_server_open(
    const char* path,
    int maximum_clients,
    int maximum_message_bytes,
    int idle_timeout_milliseconds,
    int work_bytes_per_poll,
    void** server_out,
    int* native_error_out);

int std_local_application_channel_server_poll(
    void* server,
    unsigned char* request_buffer,
    int request_capacity,
    uint64_t* request_identity_out,
    int* request_length_out,
    int* native_error_out);

int std_local_application_channel_server_respond(
    void* server,
    uint64_t request_identity,
    const unsigned char* response,
    int response_length,
    int* native_error_out);

int std_local_application_channel_server_close(void** server);

int std_local_application_channel_request(
    const char* path,
    const unsigned char* request,
    int request_length,
    unsigned char* response_buffer,
    int response_capacity,
    int timeout_milliseconds,
    int* response_length_out,
    int* native_error_out);

#ifdef __cplusplus
}
#endif

#endif
