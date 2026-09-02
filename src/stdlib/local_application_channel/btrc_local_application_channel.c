#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include "btrc_local_application_channel.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)

static void btrc_local_application_channel_error(int* output, int value) {
    if (output != NULL) {
        *output = value;
    }
}

int std_local_application_channel_server_open(
    const char* path,
    int maximum_clients,
    int maximum_message_bytes,
    int idle_timeout_milliseconds,
    int work_bytes_per_poll,
    void** server_out,
    int* native_error_out) {
    (void)path;
    (void)maximum_clients;
    (void)maximum_message_bytes;
    (void)idle_timeout_milliseconds;
    (void)work_bytes_per_poll;
    if (server_out != NULL) {
        *server_out = NULL;
    }
    btrc_local_application_channel_error(native_error_out, 0);
    return BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_UNSUPPORTED;
}

int std_local_application_channel_server_poll(
    void* server,
    unsigned char* request_buffer,
    int request_capacity,
    uint64_t* request_identity_out,
    int* request_length_out,
    int* native_error_out) {
    (void)server;
    (void)request_buffer;
    (void)request_capacity;
    if (request_identity_out != NULL) {
        *request_identity_out = 0;
    }
    if (request_length_out != NULL) {
        *request_length_out = 0;
    }
    btrc_local_application_channel_error(native_error_out, 0);
    return BTRC_LOCAL_APPLICATION_CHANNEL_POLL_CLOSED;
}

int std_local_application_channel_server_respond(
    void* server,
    uint64_t request_identity,
    const unsigned char* response,
    int response_length,
    int* native_error_out) {
    (void)server;
    (void)request_identity;
    (void)response;
    (void)response_length;
    btrc_local_application_channel_error(native_error_out, 0);
    return BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_CLOSED;
}

int std_local_application_channel_server_close(void** server) {
    if (server != NULL) {
        *server = NULL;
    }
    return 0;
}

int std_local_application_channel_request(
    const char* path,
    const unsigned char* request,
    int request_length,
    unsigned char* response_buffer,
    int response_capacity,
    int timeout_milliseconds,
    int* response_length_out,
    int* native_error_out) {
    (void)path;
    (void)request;
    (void)request_length;
    (void)response_buffer;
    (void)response_capacity;
    (void)timeout_milliseconds;
    if (response_length_out != NULL) {
        *response_length_out = 0;
    }
    btrc_local_application_channel_error(native_error_out, 0);
    return BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_UNSUPPORTED;
}

#else

#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

enum {
    BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_UNUSED = 0,
    BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READING_HEADER = 1,
    BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READING_BODY = 2,
    BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READY = 3,
    BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_DELIVERED = 4,
    BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_WRITING = 5,
};

typedef struct BtrcLocalApplicationChannelClient {
    int descriptor;
    int state;
    uint64_t request_identity;
    uint64_t last_activity_milliseconds;
    unsigned char header[4];
    size_t header_length;
    unsigned char* request;
    size_t request_length;
    size_t request_received;
    unsigned char* response;
    size_t response_length;
    size_t response_sent;
} BtrcLocalApplicationChannelClient;

typedef struct BtrcLocalApplicationChannelServer {
    int listener;
    int maximum_clients;
    int maximum_message_bytes;
    int idle_timeout_milliseconds;
    int work_bytes_per_poll;
    uid_t owner_user;
    uint64_t next_request_identity;
    char* path;
    dev_t endpoint_device;
    ino_t endpoint_inode;
    BtrcLocalApplicationChannelClient* clients;
} BtrcLocalApplicationChannelServer;

static void btrc_local_application_channel_error(int* output, int value) {
    if (output != NULL) {
        *output = value;
    }
}

static uint64_t btrc_local_application_channel_now_milliseconds(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0 || now.tv_sec < (time_t)0 || now.tv_nsec < 0L || now.tv_nsec >= 1000000000L) {
        return UINT64_MAX;
    }
    if ((uint64_t)now.tv_sec > UINT64_MAX / UINT64_C(1000)) {
        return UINT64_MAX;
    }
    uint64_t seconds = (uint64_t)now.tv_sec * UINT64_C(1000);
    uint64_t fraction = (uint64_t)now.tv_nsec / UINT64_C(1000000);
    return seconds > UINT64_MAX - fraction ? UINT64_MAX : seconds + fraction;
}

static int btrc_local_application_channel_configure_descriptor(int descriptor) {
    int descriptor_flags = fcntl(descriptor, F_GETFD, 0);
    if (descriptor_flags < 0 || fcntl(descriptor, F_SETFD, descriptor_flags | FD_CLOEXEC) < 0) {
        return -1;
    }
    int status_flags = fcntl(descriptor, F_GETFL, 0);
    if (status_flags < 0 || fcntl(descriptor, F_SETFL, status_flags | O_NONBLOCK) < 0) {
        return -1;
    }
    return 0;
}

static int btrc_local_application_channel_wait(
    int descriptor,
    short events,
    uint64_t deadline_milliseconds) {
    for (;;) {
        uint64_t now = btrc_local_application_channel_now_milliseconds();
        if (now == UINT64_MAX || now >= deadline_milliseconds) {
            errno = ETIMEDOUT;
            return 0;
        }
        uint64_t remaining = deadline_milliseconds - now;
        int timeout = remaining > (uint64_t)INT_MAX ? INT_MAX : (int)remaining;
        struct pollfd pending;
        pending.fd = descriptor;
        pending.events = events;
        pending.revents = 0;
        int result = poll(&pending, (nfds_t)1, timeout);
        if (result < 0 && errno == EINTR) {
            continue;
        }
        if (result <= 0) {
            if (result == 0) {
                errno = ETIMEDOUT;
            }
            return result;
        }
        if ((pending.revents & (POLLERR | POLLHUP | POLLNVAL)) != 0 && (pending.revents & events) == 0) {
            errno = EIO;
            return -1;
        }
        return (pending.revents & events) != 0 ? 1 : -1;
    }
}

static int btrc_local_application_channel_parent(
    const char* path,
    char* parent,
    size_t parent_capacity) {
    if (path == NULL || path[0] != '/' || parent == NULL || parent_capacity < 2) {
        errno = EINVAL;
        return 0;
    }
    size_t length = strlen(path);
    if (length < 2 || length >= sizeof(((struct sockaddr_un*)0)->sun_path)) {
        errno = ENAMETOOLONG;
        return 0;
    }
    const char* separator = strrchr(path, '/');
    if (separator == NULL || separator[1] == '\0') {
        errno = EINVAL;
        return 0;
    }
    size_t parent_length = separator == path ? 1 : (size_t)(separator - path);
    if (parent_length >= parent_capacity) {
        errno = ENAMETOOLONG;
        return 0;
    }
    memcpy(parent, path, parent_length);
    parent[parent_length] = '\0';
    return 1;
}

static int btrc_local_application_channel_private_parent(const char* path) {
    char parent[sizeof(((struct sockaddr_un*)0)->sun_path)];
    if (!btrc_local_application_channel_parent(path, parent, sizeof(parent))) {
        return 0;
    }
    struct stat status;
    if (lstat(parent, &status) != 0) {
        return 0;
    }
    if (!S_ISDIR(status.st_mode) || status.st_uid != geteuid() || (status.st_mode & (mode_t)0077) != (mode_t)0) {
        errno = EACCES;
        return 0;
    }
    return 1;
}

static int btrc_local_application_channel_secure_endpoint(
    const char* path,
    struct stat* status_out) {
    struct stat status;
    if (path == NULL || lstat(path, &status) != 0) {
        return 0;
    }
    if (!S_ISSOCK(status.st_mode) || status.st_uid != geteuid() || (status.st_mode & (mode_t)0077) != (mode_t)0) {
        errno = EACCES;
        return 0;
    }
    if (status_out != NULL) {
        *status_out = status;
    }
    return 1;
}

static int btrc_local_application_channel_peer_is_owner(int descriptor, uid_t owner) {
#if defined(__APPLE__)
    uid_t peer_user = (uid_t)-1;
    gid_t peer_group = (gid_t)-1;
    return getpeereid(descriptor, &peer_user, &peer_group) == 0 && peer_user == owner;
#elif defined(__linux__)
    struct ucred credentials;
    socklen_t length = (socklen_t)sizeof(credentials);
    memset(&credentials, 0, sizeof(credentials));
    return getsockopt(descriptor, SOL_SOCKET, SO_PEERCRED, &credentials, &length) == 0 && length == (socklen_t)sizeof(credentials) && credentials.uid == owner;
#else
    (void)descriptor;
    (void)owner;
    errno = ENOTSUP;
    return 0;
#endif
}

static void btrc_local_application_channel_close_descriptor(int descriptor) {
    if (descriptor < 0) {
        return;
    }
    shutdown(descriptor, SHUT_RDWR);
    close(descriptor);
}

static void btrc_local_application_channel_reset_client(
    BtrcLocalApplicationChannelClient* client) {
    if (client == NULL) {
        return;
    }
    btrc_local_application_channel_close_descriptor(client->descriptor);
    free(client->request);
    free(client->response);
    memset(client, 0, sizeof(*client));
    client->descriptor = -1;
    client->state = BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_UNUSED;
}

static uint32_t btrc_local_application_channel_decode_length(const unsigned char header[4]) {
    return ((uint32_t)header[0] << 24) |
        ((uint32_t)header[1] << 16) |
        ((uint32_t)header[2] << 8) |
        (uint32_t)header[3];
}

static void btrc_local_application_channel_encode_length(
    unsigned char header[4],
    uint32_t length) {
    header[0] = (unsigned char)((length >> 24) & UINT32_C(0xff));
    header[1] = (unsigned char)((length >> 16) & UINT32_C(0xff));
    header[2] = (unsigned char)((length >> 8) & UINT32_C(0xff));
    header[3] = (unsigned char)(length & UINT32_C(0xff));
}

static int btrc_local_application_channel_probe_existing(const char* path) {
    int descriptor = socket(AF_UNIX, SOCK_STREAM, 0);
    if (descriptor < 0) {
        return -1;
    }
    if (btrc_local_application_channel_configure_descriptor(descriptor) != 0) {
        int saved_error = errno;
        close(descriptor);
        errno = saved_error;
        return -1;
    }
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    memcpy(address.sun_path, path, strlen(path) + 1);
    int result = connect(descriptor, (struct sockaddr*)&address, sizeof(address));
    int saved_error = errno;
    close(descriptor);
    errno = saved_error;
    if (result == 0 || saved_error == EINPROGRESS || saved_error == EAGAIN || saved_error == EWOULDBLOCK) {
        return 1;
    }
    if (saved_error == ECONNREFUSED || saved_error == ENOENT) {
        return 0;
    }
    return -1;
}

static int btrc_local_application_channel_remove_stale(
    const char* path,
    int* open_kind_out) {
    struct stat first;
    if (lstat(path, &first) != 0) {
        if (errno == ENOENT) {
            return 1;
        }
        *open_kind_out = BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_PATH_CONFLICT;
        return 0;
    }
    if (!S_ISSOCK(first.st_mode) || first.st_uid != geteuid()) {
        errno = EEXIST;
        *open_kind_out = BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_PATH_CONFLICT;
        return 0;
    }
    int active = btrc_local_application_channel_probe_existing(path);
    if (active != 0) {
        *open_kind_out = active > 0 ? BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_ALREADY_RUNNING : BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_PATH_CONFLICT;
        return 0;
    }
    struct stat second;
    if (lstat(path, &second) != 0 || second.st_dev != first.st_dev || second.st_ino != first.st_ino || !S_ISSOCK(second.st_mode) || second.st_uid != geteuid()) {
        errno = EAGAIN;
        *open_kind_out = BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_PATH_CONFLICT;
        return 0;
    }
    if (unlink(path) != 0) {
        *open_kind_out = BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_PATH_CONFLICT;
        return 0;
    }
    return 1;
}

static int btrc_local_application_channel_accept(
    BtrcLocalApplicationChannelServer* server,
    int* native_error_out) {
    BtrcLocalApplicationChannelClient* slot = NULL;
    for (int index = 0; index < server->maximum_clients; index++) {
        if (server->clients[index].state == BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_UNUSED) {
            slot = &server->clients[index];
            break;
        }
    }
    if (slot == NULL) {
        return 0;
    }
    int descriptor = accept(server->listener, NULL, NULL);
    if (descriptor < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
            return 0;
        }
        btrc_local_application_channel_error(native_error_out, errno);
        return -1;
    }
    if (btrc_local_application_channel_configure_descriptor(descriptor) != 0 || !btrc_local_application_channel_peer_is_owner(descriptor, server->owner_user)) {
        btrc_local_application_channel_close_descriptor(descriptor);
        return 1;
    }
    memset(slot, 0, sizeof(*slot));
    slot->descriptor = descriptor;
    slot->state = BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READING_HEADER;
    slot->last_activity_milliseconds = btrc_local_application_channel_now_milliseconds();
    return 1;
}

static int btrc_local_application_channel_client_expired(
    const BtrcLocalApplicationChannelServer* server,
    const BtrcLocalApplicationChannelClient* client,
    uint64_t now) {
    if (now == UINT64_MAX || client->last_activity_milliseconds == UINT64_MAX) {
        return 1;
    }
    uint64_t elapsed = now >= client->last_activity_milliseconds ? now - client->last_activity_milliseconds : UINT64_MAX;
    return elapsed >= (uint64_t)server->idle_timeout_milliseconds;
}

static int btrc_local_application_channel_read_client(
    BtrcLocalApplicationChannelServer* server,
    BtrcLocalApplicationChannelClient* client,
    int* work_remaining) {
    while (*work_remaining > 0) {
        if (client->state == BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READING_HEADER) {
            size_t needed = sizeof(client->header) - client->header_length;
            size_t permitted = needed < (size_t)*work_remaining ? needed : (size_t)*work_remaining;
            ssize_t count = recv(client->descriptor, client->header + client->header_length, permitted, 0);
            if (count > (ssize_t)0) {
                client->header_length += (size_t)count;
                *work_remaining -= (int)count;
                client->last_activity_milliseconds = btrc_local_application_channel_now_milliseconds();
                if (client->header_length < sizeof(client->header)) {
                    continue;
                }
                uint32_t length = btrc_local_application_channel_decode_length(client->header);
                if (length > (uint32_t)server->maximum_message_bytes) {
                    return -1;
                }
                client->request_length = (size_t)length;
                if (length == 0) {
                    client->state = BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READY;
                    return 1;
                }
                client->request = (unsigned char*)malloc((size_t)length);
                if (client->request == NULL) {
                    return -1;
                }
                client->state = BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READING_BODY;
            } else if (count < (ssize_t)0 && errno == EINTR) {
                continue;
            } else if (count < (ssize_t)0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
                return 0;
            } else {
                return -1;
            }
        } else if (client->state == BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READING_BODY) {
            size_t needed = client->request_length - client->request_received;
            size_t permitted = needed < (size_t)*work_remaining ? needed : (size_t)*work_remaining;
            ssize_t count = recv(client->descriptor, client->request + client->request_received, permitted, 0);
            if (count > (ssize_t)0) {
                client->request_received += (size_t)count;
                *work_remaining -= (int)count;
                client->last_activity_milliseconds = btrc_local_application_channel_now_milliseconds();
                if (client->request_received == client->request_length) {
                    client->state = BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READY;
                    return 1;
                }
            } else if (count < (ssize_t)0 && errno == EINTR) {
                continue;
            } else if (count < (ssize_t)0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
                return 0;
            } else {
                return -1;
            }
        } else {
            return 0;
        }
    }
    return 0;
}

static int btrc_local_application_channel_write_client(
    BtrcLocalApplicationChannelClient* client,
    int* work_remaining) {
    while (*work_remaining > 0 && client->response_sent < client->response_length) {
        size_t needed = client->response_length - client->response_sent;
        size_t permitted = needed < (size_t)*work_remaining ? needed : (size_t)*work_remaining;
        ssize_t count = send(client->descriptor, client->response + client->response_sent, permitted, MSG_NOSIGNAL);
        if (count > (ssize_t)0) {
            client->response_sent += (size_t)count;
            *work_remaining -= (int)count;
            client->last_activity_milliseconds = btrc_local_application_channel_now_milliseconds();
        } else if (count < (ssize_t)0 && errno == EINTR) {
            continue;
        } else if (count < (ssize_t)0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            return 0;
        } else {
            return -1;
        }
    }
    return client->response_sent == client->response_length ? 1 : 0;
}

int std_local_application_channel_server_open(
    const char* path,
    int maximum_clients,
    int maximum_message_bytes,
    int idle_timeout_milliseconds,
    int work_bytes_per_poll,
    void** server_out,
    int* native_error_out) {
    if (server_out != NULL) {
        *server_out = NULL;
    }
    btrc_local_application_channel_error(native_error_out, 0);
    if (server_out == NULL || path == NULL || maximum_clients < 1 || maximum_clients > 32 || maximum_message_bytes < 1 || maximum_message_bytes > 1048576 || idle_timeout_milliseconds < 100 || idle_timeout_milliseconds > 300000 || work_bytes_per_poll < 1 || work_bytes_per_poll > 1048576) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_INVALID;
    }
    size_t path_length = strlen(path);
    if (path[0] != '/' || path_length < 2 || path_length >= sizeof(((struct sockaddr_un*)0)->sun_path) || path[path_length - 1] == '/') {
        return BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_INVALID;
    }
    if (!btrc_local_application_channel_private_parent(path)) {
        btrc_local_application_channel_error(native_error_out, errno);
        return BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_INSECURE_PARENT;
    }
    int open_kind = BTRC_LOCAL_APPLICATION_CHANNEL_OPENED;
    if (!btrc_local_application_channel_remove_stale(path, &open_kind)) {
        btrc_local_application_channel_error(native_error_out, errno);
        return open_kind;
    }

    BtrcLocalApplicationChannelServer* server = (BtrcLocalApplicationChannelServer*)calloc(1, sizeof(*server));
    BtrcLocalApplicationChannelClient* clients = (BtrcLocalApplicationChannelClient*)calloc((size_t)maximum_clients, sizeof(*clients));
    char* owned_path = strdup(path);
    if (server == NULL || clients == NULL || owned_path == NULL) {
        free(server);
        free(clients);
        free(owned_path);
        return BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_RESOURCE_FAILED;
    }
    for (int index = 0; index < maximum_clients; index++) {
        clients[index].descriptor = -1;
    }
    server->listener = -1;
    server->maximum_clients = maximum_clients;
    server->maximum_message_bytes = maximum_message_bytes;
    server->idle_timeout_milliseconds = idle_timeout_milliseconds;
    server->work_bytes_per_poll = work_bytes_per_poll;
    server->owner_user = geteuid();
    server->next_request_identity = UINT64_C(1);
    server->path = owned_path;
    server->clients = clients;

    int listener = socket(AF_UNIX, SOCK_STREAM, 0);
    if (listener < 0 || btrc_local_application_channel_configure_descriptor(listener) != 0) {
        int saved_error = errno;
        if (listener >= 0) {
            close(listener);
        }
        free(server->clients);
        free(server->path);
        free(server);
        btrc_local_application_channel_error(native_error_out, saved_error);
        return BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_RESOURCE_FAILED;
    }
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    memcpy(address.sun_path, path, strlen(path) + 1);
    if (bind(listener, (struct sockaddr*)&address, sizeof(address)) != 0 || chmod(path, (mode_t)0600) != 0 || listen(listener, maximum_clients) != 0) {
        int saved_error = errno;
        close(listener);
        unlink(path);
        free(server->clients);
        free(server->path);
        free(server);
        btrc_local_application_channel_error(native_error_out, saved_error);
        return BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_RESOURCE_FAILED;
    }
    struct stat endpoint_status;
    if (!btrc_local_application_channel_secure_endpoint(path, &endpoint_status)) {
        int saved_error = errno;
        close(listener);
        unlink(path);
        free(server->clients);
        free(server->path);
        free(server);
        btrc_local_application_channel_error(native_error_out, saved_error);
        return BTRC_LOCAL_APPLICATION_CHANNEL_OPEN_RESOURCE_FAILED;
    }
    server->listener = listener;
    server->endpoint_device = endpoint_status.st_dev;
    server->endpoint_inode = endpoint_status.st_ino;
    *server_out = server;
    return BTRC_LOCAL_APPLICATION_CHANNEL_OPENED;
}

int std_local_application_channel_server_poll(
    void* raw_server,
    unsigned char* request_buffer,
    int request_capacity,
    uint64_t* request_identity_out,
    int* request_length_out,
    int* native_error_out) {
    if (request_identity_out != NULL) {
        *request_identity_out = 0;
    }
    if (request_length_out != NULL) {
        *request_length_out = 0;
    }
    btrc_local_application_channel_error(native_error_out, 0);
    if (raw_server == NULL) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_POLL_CLOSED;
    }
    BtrcLocalApplicationChannelServer* server = (BtrcLocalApplicationChannelServer*)raw_server;
    if (request_buffer == NULL || request_capacity < server->maximum_message_bytes || request_identity_out == NULL || request_length_out == NULL) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_POLL_INVALID_BUFFER;
    }

    int work_remaining = server->work_bytes_per_poll;
    int accepted = btrc_local_application_channel_accept(server, native_error_out);
    if (accepted < 0) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_POLL_FAILED;
    }
    uint64_t now = btrc_local_application_channel_now_milliseconds();
    for (int index = 0; index < server->maximum_clients; index++) {
        BtrcLocalApplicationChannelClient* client = &server->clients[index];
        if (client->state == BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_UNUSED) {
            continue;
        }
        if (btrc_local_application_channel_client_expired(server, client, now)) {
            btrc_local_application_channel_reset_client(client);
            continue;
        }
        if (client->state == BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_WRITING) {
            int written = btrc_local_application_channel_write_client(client, &work_remaining);
            if (written != 0) {
                btrc_local_application_channel_reset_client(client);
            }
            continue;
        }
        if (client->state == BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READING_HEADER || client->state == BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READING_BODY) {
            int read = btrc_local_application_channel_read_client(server, client, &work_remaining);
            if (read < 0) {
                btrc_local_application_channel_reset_client(client);
                continue;
            }
        }
        if (client->state == BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_READY) {
            if (server->next_request_identity == UINT64_MAX) {
                btrc_local_application_channel_reset_client(client);
                btrc_local_application_channel_error(native_error_out, EOVERFLOW);
                return BTRC_LOCAL_APPLICATION_CHANNEL_POLL_FAILED;
            }
            uint64_t identity = server->next_request_identity++;
            client->request_identity = identity;
            if (client->request_length > 0) {
                memcpy(request_buffer, client->request, client->request_length);
            }
            *request_identity_out = identity;
            *request_length_out = (int)client->request_length;
            client->state = BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_DELIVERED;
            client->last_activity_milliseconds = btrc_local_application_channel_now_milliseconds();
            return BTRC_LOCAL_APPLICATION_CHANNEL_POLL_REQUEST;
        }
    }
    return work_remaining == 0 ? BTRC_LOCAL_APPLICATION_CHANNEL_POLL_WORK_REMAINS : BTRC_LOCAL_APPLICATION_CHANNEL_POLL_IDLE;
}

int std_local_application_channel_server_respond(
    void* raw_server,
    uint64_t request_identity,
    const unsigned char* response,
    int response_length,
    int* native_error_out) {
    btrc_local_application_channel_error(native_error_out, 0);
    if (raw_server == NULL) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_CLOSED;
    }
    BtrcLocalApplicationChannelServer* server = (BtrcLocalApplicationChannelServer*)raw_server;
    if (request_identity == 0 || response_length < 0 || (response_length > 0 && response == NULL)) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_INVALID;
    }
    if (response_length > server->maximum_message_bytes) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_TOO_LARGE;
    }
    BtrcLocalApplicationChannelClient* client = NULL;
    for (int index = 0; index < server->maximum_clients; index++) {
        if (server->clients[index].state == BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_DELIVERED && server->clients[index].request_identity == request_identity) {
            client = &server->clients[index];
            break;
        }
    }
    if (client == NULL) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_STALE;
    }
    size_t framed_length = (size_t)response_length + (size_t)4;
    unsigned char* framed = (unsigned char*)malloc(framed_length);
    if (framed == NULL) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_RESOURCE_FAILED;
    }
    btrc_local_application_channel_encode_length(framed, (uint32_t)response_length);
    if (response_length > 0) {
        memcpy(framed + 4, response, (size_t)response_length);
    }
    free(client->request);
    client->request = NULL;
    client->request_length = 0;
    client->request_received = 0;
    client->response = framed;
    client->response_length = framed_length;
    client->response_sent = 0;
    client->state = BTRC_LOCAL_APPLICATION_CHANNEL_CLIENT_WRITING;
    client->last_activity_milliseconds = btrc_local_application_channel_now_milliseconds();
    return BTRC_LOCAL_APPLICATION_CHANNEL_RESPONSE_QUEUED;
}

int std_local_application_channel_server_close(void** raw_server) {
    if (raw_server == NULL || *raw_server == NULL) {
        return 0;
    }
    BtrcLocalApplicationChannelServer* server = (BtrcLocalApplicationChannelServer*)*raw_server;
    *raw_server = NULL;
    for (int index = 0; index < server->maximum_clients; index++) {
        btrc_local_application_channel_reset_client(&server->clients[index]);
    }
    btrc_local_application_channel_close_descriptor(server->listener);
    struct stat current;
    if (server->path != NULL && lstat(server->path, &current) == 0 && S_ISSOCK(current.st_mode) && current.st_uid == server->owner_user && current.st_dev == server->endpoint_device && current.st_ino == server->endpoint_inode) {
        unlink(server->path);
    }
    free(server->clients);
    free(server->path);
    free(server);
    return 0;
}

static int btrc_local_application_channel_connect(
    const char* path,
    uint64_t deadline,
    int* native_error_out) {
    int descriptor = socket(AF_UNIX, SOCK_STREAM, 0);
    if (descriptor < 0 || btrc_local_application_channel_configure_descriptor(descriptor) != 0) {
        int saved_error = errno;
        if (descriptor >= 0) {
            close(descriptor);
        }
        btrc_local_application_channel_error(native_error_out, saved_error);
        return -1;
    }
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    memcpy(address.sun_path, path, strlen(path) + 1);
    if (connect(descriptor, (struct sockaddr*)&address, sizeof(address)) != 0) {
        if (errno != EINPROGRESS) {
            int saved_error = errno;
            close(descriptor);
            btrc_local_application_channel_error(native_error_out, saved_error);
            return -1;
        }
        int ready = btrc_local_application_channel_wait(descriptor, POLLOUT, deadline);
        if (ready <= 0) {
            int saved_error = errno;
            close(descriptor);
            btrc_local_application_channel_error(native_error_out, saved_error);
            return -1;
        }
        int socket_error = 0;
        socklen_t error_length = (socklen_t)sizeof(socket_error);
        if (getsockopt(descriptor, SOL_SOCKET, SO_ERROR, &socket_error, &error_length) != 0 || socket_error != 0) {
            int saved_error = socket_error != 0 ? socket_error : errno;
            close(descriptor);
            btrc_local_application_channel_error(native_error_out, saved_error);
            return -1;
        }
    }
    if (!btrc_local_application_channel_peer_is_owner(descriptor, geteuid())) {
        int saved_error = errno == 0 ? EACCES : errno;
        close(descriptor);
        btrc_local_application_channel_error(native_error_out, saved_error);
        errno = EACCES;
        return -2;
    }
    return descriptor;
}

static int btrc_local_application_channel_send_all(
    int descriptor,
    const unsigned char* data,
    size_t length,
    uint64_t deadline) {
    size_t sent = 0;
    while (sent < length) {
        int ready = btrc_local_application_channel_wait(descriptor, POLLOUT, deadline);
        if (ready <= 0) {
            return 0;
        }
        ssize_t count = send(descriptor, data + sent, length - sent, MSG_NOSIGNAL);
        if (count > (ssize_t)0) {
            sent += (size_t)count;
        } else if (count < (ssize_t)0 && errno == EINTR) {
            continue;
        } else if (count < (ssize_t)0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            continue;
        } else {
            return 0;
        }
    }
    return 1;
}

static int btrc_local_application_channel_receive_all(
    int descriptor,
    unsigned char* data,
    size_t length,
    uint64_t deadline) {
    size_t received = 0;
    while (received < length) {
        int ready = btrc_local_application_channel_wait(descriptor, POLLIN, deadline);
        if (ready <= 0) {
            return 0;
        }
        ssize_t count = recv(descriptor, data + received, length - received, 0);
        if (count > (ssize_t)0) {
            received += (size_t)count;
        } else if (count < (ssize_t)0 && errno == EINTR) {
            continue;
        } else if (count < (ssize_t)0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            continue;
        } else {
            errno = EPROTO;
            return 0;
        }
    }
    return 1;
}

int std_local_application_channel_request(
    const char* path,
    const unsigned char* request,
    int request_length,
    unsigned char* response_buffer,
    int response_capacity,
    int timeout_milliseconds,
    int* response_length_out,
    int* native_error_out) {
    if (response_length_out != NULL) {
        *response_length_out = 0;
    }
    btrc_local_application_channel_error(native_error_out, 0);
    if (path == NULL || request_length < 0 || (request_length > 0 && request == NULL) || response_buffer == NULL || response_capacity < 1 || timeout_milliseconds < 1 || timeout_milliseconds > 300000 || response_length_out == NULL || strlen(path) >= sizeof(((struct sockaddr_un*)0)->sun_path)) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_INVALID;
    }
    if (!btrc_local_application_channel_private_parent(path)) {
        int saved_error = errno;
        btrc_local_application_channel_error(native_error_out, saved_error);
        return saved_error == ENOENT ? BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_UNAVAILABLE : BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_SECURITY_REJECTED;
    }
    if (!btrc_local_application_channel_secure_endpoint(path, NULL)) {
        int saved_error = errno;
        btrc_local_application_channel_error(native_error_out, saved_error);
        return saved_error == ENOENT ? BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_UNAVAILABLE : BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_SECURITY_REJECTED;
    }
    uint64_t now = btrc_local_application_channel_now_milliseconds();
    if (now == UINT64_MAX || (uint64_t)timeout_milliseconds > UINT64_MAX - now) {
        return BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_IO_FAILED;
    }
    uint64_t deadline = now + (uint64_t)timeout_milliseconds;
    int descriptor = btrc_local_application_channel_connect(path, deadline, native_error_out);
    if (descriptor < 0) {
        int native_error = native_error_out == NULL ? errno : *native_error_out;
        if (descriptor == -2) {
            return BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_SECURITY_REJECTED;
        }
        if (native_error == ETIMEDOUT) {
            return BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_TIMED_OUT;
        }
        return native_error == ENOENT || native_error == ECONNREFUSED ? BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_UNAVAILABLE : BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_IO_FAILED;
    }
    unsigned char header[4];
    btrc_local_application_channel_encode_length(header, (uint32_t)request_length);
    if (!btrc_local_application_channel_send_all(descriptor, header, sizeof(header), deadline) || (request_length > 0 && !btrc_local_application_channel_send_all(descriptor, request, (size_t)request_length, deadline))) {
        int saved_error = errno;
        btrc_local_application_channel_close_descriptor(descriptor);
        btrc_local_application_channel_error(native_error_out, saved_error);
        return saved_error == ETIMEDOUT ? BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_TIMED_OUT : BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_IO_FAILED;
    }
    if (!btrc_local_application_channel_receive_all(descriptor, header, sizeof(header), deadline)) {
        int saved_error = errno;
        btrc_local_application_channel_close_descriptor(descriptor);
        btrc_local_application_channel_error(native_error_out, saved_error);
        return saved_error == ETIMEDOUT ? BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_TIMED_OUT : BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_PROTOCOL_FAILED;
    }
    uint32_t response_length = btrc_local_application_channel_decode_length(header);
    if (response_length > (uint32_t)response_capacity) {
        btrc_local_application_channel_close_descriptor(descriptor);
        return BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_RESPONSE_TOO_LARGE;
    }
    if (response_length > 0 && !btrc_local_application_channel_receive_all(descriptor, response_buffer, (size_t)response_length, deadline)) {
        int saved_error = errno;
        btrc_local_application_channel_close_descriptor(descriptor);
        btrc_local_application_channel_error(native_error_out, saved_error);
        return saved_error == ETIMEDOUT ? BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_TIMED_OUT : BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_PROTOCOL_FAILED;
    }
    *response_length_out = (int)response_length;
    btrc_local_application_channel_close_descriptor(descriptor);
    return BTRC_LOCAL_APPLICATION_CHANNEL_REQUEST_COMPLETED;
}

#endif
