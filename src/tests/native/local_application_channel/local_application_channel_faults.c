#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include "btrc_local_application_channel.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

static void encode_length(unsigned char output[4], uint32_t length) {
    output[0] = (unsigned char)(length >> 24);
    output[1] = (unsigned char)(length >> 16);
    output[2] = (unsigned char)(length >> 8);
    output[3] = (unsigned char)length;
}

static uint32_t decode_length(const unsigned char input[4]) {
    return ((uint32_t)input[0] << 24) | ((uint32_t)input[1] << 16) | ((uint32_t)input[2] << 8) | (uint32_t)input[3];
}

static void sleep_milliseconds(int milliseconds) {
    struct timespec duration;
    duration.tv_sec = milliseconds / 1000;
    duration.tv_nsec = (long)(milliseconds % 1000) * 1000000L;
    while (nanosleep(&duration, &duration) != 0 && errno == EINTR) {
    }
}

static int connect_peer(const char* path) {
    int descriptor = socket(AF_UNIX, SOCK_STREAM, 0);
    assert(descriptor >= 0);
    struct timeval timeout;
    timeout.tv_sec = 2;
    timeout.tv_usec = 0;
    assert(setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    memcpy(address.sun_path, path, strlen(path) + 1);
    assert(connect(descriptor, (struct sockaddr*)&address, sizeof(address)) == 0);
    return descriptor;
}

static void send_all(int descriptor, const unsigned char* data, size_t length) {
    size_t sent = 0;
    while (sent < length) {
        ssize_t count = send(descriptor, data + sent, length - sent, 0);
        if (count > 0) {
            sent += (size_t)count;
        } else if (count < 0 && errno == EINTR) {
            continue;
        } else {
            assert(0 && "raw peer send failed");
        }
    }
}

static void send_frame(int descriptor, const char* text) {
    size_t length = strlen(text);
    unsigned char header[4];
    encode_length(header, (uint32_t)length);
    send_all(descriptor, header, sizeof(header));
    send_all(descriptor, (const unsigned char*)text, length);
}

static void receive_all(int descriptor, unsigned char* data, size_t length) {
    size_t received = 0;
    while (received < length) {
        ssize_t count = recv(descriptor, data + received, length - received, 0);
        if (count > 0) {
            received += (size_t)count;
        } else if (count < 0 && errno == EINTR) {
            continue;
        } else {
            assert(0 && "raw peer receive failed");
        }
    }
}

static void receive_frame(int descriptor, const char* expected) {
    unsigned char header[4];
    receive_all(descriptor, header, sizeof(header));
    uint32_t length = decode_length(header);
    assert(length == strlen(expected));
    unsigned char data[128];
    assert(length < sizeof(data));
    receive_all(descriptor, data, length);
    assert(memcmp(data, expected, length) == 0);
}

static uint64_t poll_request(void* server, unsigned char* data, int capacity, int* length_out) {
    for (int attempt = 0; attempt < 5000; attempt++) {
        uint64_t identity = 0;
        int native_error = 0;
        int kind = std_local_application_channel_server_poll(server, data, capacity, &identity, length_out, &native_error);
        if (kind == BTRC_LOCAL_APPLICATION_CHANNEL_POLL_REQUEST) {
            assert(identity != 0);
            return identity;
        }
        assert(kind == BTRC_LOCAL_APPLICATION_CHANNEL_POLL_IDLE || kind == BTRC_LOCAL_APPLICATION_CHANNEL_POLL_WORK_REMAINS);
        sleep_milliseconds(1);
    }
    assert(0 && "server request did not arrive");
    return 0;
}

static void flush_server(void* server, unsigned char* data, int capacity) {
    for (int attempt = 0; attempt < 5000; attempt++) {
        uint64_t identity = 0;
        int length = 0;
        int native_error = 0;
        int kind = std_local_application_channel_server_poll(server, data, capacity, &identity, &length, &native_error);
        assert(kind == BTRC_LOCAL_APPLICATION_CHANNEL_POLL_IDLE || kind == BTRC_LOCAL_APPLICATION_CHANNEL_POLL_WORK_REMAINS);
        if (kind == BTRC_LOCAL_APPLICATION_CHANNEL_POLL_IDLE) {
            return;
        }
    }
    assert(0 && "server response did not flush");
}

static void write_regular_file(const char* path) {
    FILE* file = fopen(path, "wb");
    assert(file != NULL);
    assert(fputs("sentinel", file) >= 0);
    assert(fclose(file) == 0);
}

int main(void) {
    char directory_template[] = "/tmp/btrc-local-channel-faults-XXXXXX";
    char* directory = mkdtemp(directory_template);
    assert(directory != NULL);
    char endpoint[512];
    assert(snprintf(endpoint, sizeof(endpoint), "%s/application.sock", directory) > 0);

    void* server = NULL;
    int native_error = 0;
    assert(chmod(directory, (mode_t)0755) == 0);
    assert(std_local_application_channel_server_open(endpoint, 4, 64, 100, 4, &server, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_INSECURE_PARENT);
    assert(server == NULL);
    assert(chmod(directory, (mode_t)0700) == 0);

    write_regular_file(endpoint);
    assert(std_local_application_channel_server_open(endpoint, 4, 64, 100, 4, &server, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_PATH_CONFLICT);
    assert(unlink(endpoint) == 0);
    assert(symlink("missing-target", endpoint) == 0);
    assert(std_local_application_channel_server_open(endpoint, 4, 64, 100, 4, &server, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_PATH_CONFLICT);
    assert(unlink(endpoint) == 0);
    unsigned char missing_response[64];
    int missing_response_length = 0;
    assert(std_local_application_channel_request(endpoint, (const unsigned char*)"missing", 7, missing_response, sizeof(missing_response), 100, &missing_response_length, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_UNAVAILABLE);

    assert(std_local_application_channel_server_open(endpoint, 4, 64, 100, 4, &server, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_OPENED);
    assert(server != NULL);
    unsigned char request_buffer[64];

    int partial = connect_peer(endpoint);
    unsigned char partial_header[4];
    encode_length(partial_header, 7);
    send_all(partial, partial_header, 2);
    uint64_t unused_identity = 0;
    int unused_length = 0;
    assert(std_local_application_channel_server_poll(server, request_buffer, sizeof(request_buffer), &unused_identity, &unused_length, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_POLL_IDLE);
    send_all(partial, partial_header + 2, 2);
    send_all(partial, (const unsigned char*)"partial", 7);
    int partial_length = 0;
    uint64_t partial_identity = poll_request(server, request_buffer, sizeof(request_buffer), &partial_length);
    assert(partial_length == 7 && memcmp(request_buffer, "partial", 7) == 0);
    unsigned char oversized_response[65];
    memset(oversized_response, 'x', sizeof(oversized_response));
    assert(std_local_application_channel_server_respond(server, partial_identity, oversized_response, sizeof(oversized_response), &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_TOO_LARGE);
    assert(std_local_application_channel_server_respond(server, partial_identity, (const unsigned char*)"ok", 2, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_QUEUED);
    flush_server(server, request_buffer, sizeof(request_buffer));
    receive_frame(partial, "ok");
    close(partial);
    assert(std_local_application_channel_server_respond(server, partial_identity, (const unsigned char*)"again", 5, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_STALE);

    int oversized = connect_peer(endpoint);
    unsigned char oversized_header[4];
    encode_length(oversized_header, 65);
    send_all(oversized, oversized_header, sizeof(oversized_header));
    for (int attempt = 0; attempt < 100; attempt++) {
        assert(std_local_application_channel_server_poll(server, request_buffer, sizeof(request_buffer), &unused_identity, &unused_length, &native_error) != BTRC_LOCAL_APPLICATION_CHANNEL_POLL_FAILED);
    }
    assert(recv(oversized, request_buffer, 1, 0) <= 0);
    close(oversized);

    int idle = connect_peer(endpoint);
    send_all(idle, partial_header, 1);
    assert(std_local_application_channel_server_poll(server, request_buffer, sizeof(request_buffer), &unused_identity, &unused_length, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_POLL_IDLE);
    sleep_milliseconds(150);
    assert(std_local_application_channel_server_poll(server, request_buffer, sizeof(request_buffer), &unused_identity, &unused_length, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_POLL_IDLE);
    assert(recv(idle, request_buffer, 1, 0) <= 0);
    close(idle);

    int first = connect_peer(endpoint);
    int second = connect_peer(endpoint);
    send_frame(first, "one");
    send_frame(second, "two");
    int first_length = 0;
    uint64_t first_identity = poll_request(server, request_buffer, sizeof(request_buffer), &first_length);
    assert(first_length == 3);
    char first_request[4];
    memcpy(first_request, request_buffer, 3);
    first_request[3] = '\0';
    int second_length = 0;
    uint64_t second_identity = poll_request(server, request_buffer, sizeof(request_buffer), &second_length);
    assert(second_length == 3);
    char second_request[4];
    memcpy(second_request, request_buffer, 3);
    second_request[3] = '\0';
    assert(strcmp(first_request, second_request) != 0);
    assert((strcmp(first_request, "one") == 0 || strcmp(first_request, "two") == 0) && (strcmp(second_request, "one") == 0 || strcmp(second_request, "two") == 0));
    assert(std_local_application_channel_server_respond(server, first_identity, (const unsigned char*)first_request, 3, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_QUEUED);
    assert(std_local_application_channel_server_respond(server, second_identity, (const unsigned char*)second_request, 3, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_QUEUED);
    flush_server(server, request_buffer, sizeof(request_buffer));
    receive_frame(first, "one");
    receive_frame(second, "two");
    close(first);
    close(second);

    assert(chmod(endpoint, (mode_t)0666) == 0);
    int response_length = 0;
    unsigned char response_buffer[64];
    assert(std_local_application_channel_request(endpoint, (const unsigned char*)"x", 1, response_buffer, sizeof(response_buffer), 100, &response_length, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_SECURITY_REJECTED);
    assert(chmod(endpoint, (mode_t)0600) == 0);
    assert(std_local_application_channel_request(endpoint, (const unsigned char*)"timeout", 7, response_buffer, sizeof(response_buffer), 100, &response_length, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_TIMED_OUT);
    int timed_out_length = 0;
    uint64_t timed_out_identity = poll_request(server, request_buffer, sizeof(request_buffer), &timed_out_length);
    assert(timed_out_length == 7);
    assert(std_local_application_channel_server_respond(server, timed_out_identity, (const unsigned char*)"late", 4, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_QUEUED);
    flush_server(server, request_buffer, sizeof(request_buffer));

    assert(std_local_application_channel_server_close(&server) == 0);
    assert(server == NULL && access(endpoint, F_OK) != 0);

    int stale = socket(AF_UNIX, SOCK_STREAM, 0);
    assert(stale >= 0);
    struct sockaddr_un stale_address;
    memset(&stale_address, 0, sizeof(stale_address));
    stale_address.sun_family = AF_UNIX;
    memcpy(stale_address.sun_path, endpoint, strlen(endpoint) + 1);
    assert(bind(stale, (struct sockaddr*)&stale_address, sizeof(stale_address)) == 0);
    assert(chmod(endpoint, (mode_t)0600) == 0);
    close(stale);
    assert(std_local_application_channel_server_open(endpoint, 4, 64, 100, 4, &server, &native_error) == BTRC_LOCAL_APPLICATION_CHANNEL_OPENED);
    assert(unlink(endpoint) == 0);
    write_regular_file(endpoint);
    assert(std_local_application_channel_server_close(&server) == 0);
    struct stat replacement;
    assert(lstat(endpoint, &replacement) == 0 && S_ISREG(replacement.st_mode));
    assert(unlink(endpoint) == 0);
    assert(rmdir(directory) == 0);

    puts("PASS: local application channel faults");
    return 0;
}
