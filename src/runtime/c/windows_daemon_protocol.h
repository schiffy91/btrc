/* Private wire codec shared by the launcher and supervisor runtime owners.
 * Views borrow the complete frame buffer. No frame or view owns a HANDLE.
 * Transport ordering, deadlines, authentication and path policy are separate
 * from byte validation; a decoded COMMIT alone never authorizes execution. */
#ifndef BTRC_WINDOWS_DAEMON_PROTOCOL_H
#define BTRC_WINDOWS_DAEMON_PROTOCOL_H

#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "windows_utf.h"

enum {
    BTRC_DAEMON_HEADER_BYTES = 16,
    BTRC_DAEMON_MAX_PAYLOAD = 1048576,
    BTRC_DAEMON_MAX_TEXT = 65536,
    BTRC_DAEMON_MAX_ITEMS = 4096,
    BTRC_DAEMON_INIT = 1,
    BTRC_DAEMON_READY = 2,
    BTRC_DAEMON_COMMIT = 3,
    BTRC_DAEMON_ACK = 4,
    BTRC_DAEMON_ERROR = 5
};

typedef struct {
    const unsigned char *data;
    size_t size;
} btrc_daemon_text;

/* Encoded string elements, without the count prefix. Iterate with a reader. */
typedef struct {
    btrc_daemon_text encoded;
    uint32_t count;
} btrc_daemon_vector;

typedef struct {
    const unsigned char *next;
    size_t remaining;
    int valid;
} btrc_daemon_reader;

typedef struct {
    uint16_t type;
    unsigned char token[16];
    uint64_t remaining_startup_ms;
    uint32_t lifetime, auto_restart, supervisor_pid;
    btrc_daemon_text name, control_path, log_path, cwd, executable;
    btrc_daemon_vector arguments, environment;
    uint32_t stage, domain, native_code, ownership_state;
} btrc_daemon_frame;

/* Encoder inputs use byte lengths, so embedded NUL cannot be silently cut. */
typedef struct {
    unsigned char token[16];
    uint64_t remaining_startup_ms;
    uint32_t lifetime, auto_restart;
    btrc_daemon_text name, control_path, log_path, cwd, executable;
    const btrc_daemon_text *arguments, *environment;
    size_t argument_count, environment_count;
} btrc_daemon_init;

static inline int btrc_daemon_text_valid(btrc_daemon_text text) {
    if (text.size > BTRC_DAEMON_MAX_TEXT || (text.data == NULL && text.size != 0)) return 0;
    for (size_t offset = 0; offset < text.size;) {
        uint32_t scalar = 0;
        size_t count = btrc_windows_utf8_next(text.data + offset, text.size - offset, &scalar);
        if (count == 0 || scalar == 0) return 0;
        offset += count;
    }
    return 1;
}

static inline const unsigned char *btrc_daemon_read(btrc_daemon_reader *reader, size_t size) {
    if (!reader->valid || size > reader->remaining) {
        reader->valid = 0;
        return NULL;
    }
    const unsigned char *data = reader->next;
    if (size != 0) reader->next += size;
    reader->remaining -= size;
    return data;
}

static inline uint64_t btrc_daemon_read_integer(btrc_daemon_reader *reader, size_t size) {
    const unsigned char *data = btrc_daemon_read(reader, size);
    uint64_t value = 0;
    if (data != NULL) {
        for (size_t index = 0; index < size; index++) value |= (uint64_t)data[index] << (index * 8);
    }
    return value;
}

static inline btrc_daemon_text btrc_daemon_read_text(btrc_daemon_reader *reader) {
    size_t size = (size_t)btrc_daemon_read_integer(reader, 4);
    btrc_daemon_text text = { btrc_daemon_read(reader, size), size };
    if (!btrc_daemon_text_valid(text)) reader->valid = 0;
    return text;
}

static inline btrc_daemon_vector btrc_daemon_read_vector(btrc_daemon_reader *reader) {
    uint32_t count = (uint32_t)btrc_daemon_read_integer(reader, 4);
    btrc_daemon_vector vector = { { reader->next, 0 }, count };
    size_t before = reader->remaining;
    if (count > BTRC_DAEMON_MAX_ITEMS || count > reader->remaining / 4) reader->valid = 0;
    for (uint32_t index = 0; reader->valid && index < count; index++) {
        (void)btrc_daemon_read_text(reader);
    }
    vector.encoded.size = before - reader->remaining;
    return vector;
}

/* Decode only the fixed header before transport allocates the payload. */
static inline int btrc_daemon_header(const unsigned char *data, size_t size,
        uint16_t *type, uint32_t *payload_size) {
    *type = 0;
    *payload_size = 0;
    if (data == NULL || size != BTRC_DAEMON_HEADER_BYTES || memcmp(data, "BTRCDM1\0", 8) != 0) return -1;
    btrc_daemon_reader reader = { data + 8, 8, 1 };
    uint16_t version = (uint16_t)btrc_daemon_read_integer(&reader, 2);
    uint16_t kind = (uint16_t)btrc_daemon_read_integer(&reader, 2);
    uint32_t length = (uint32_t)btrc_daemon_read_integer(&reader, 4);
    if (version != 1 || kind < BTRC_DAEMON_INIT || kind > BTRC_DAEMON_ERROR
            || length > BTRC_DAEMON_MAX_PAYLOAD) return -1;
    *type = kind;
    *payload_size = length;
    return 0;
}

/* All failures clear the result; callers cannot consume partially read data. */
static inline int btrc_daemon_decode(const unsigned char *data, size_t size, btrc_daemon_frame *frame) {
    memset(frame, 0, sizeof(*frame));
    uint16_t type = 0;
    uint32_t length = 0;
    if (size < BTRC_DAEMON_HEADER_BYTES
            || btrc_daemon_header(data, BTRC_DAEMON_HEADER_BYTES, &type, &length) != 0
            || size - BTRC_DAEMON_HEADER_BYTES != length) return -1;
    btrc_daemon_reader reader = { data + BTRC_DAEMON_HEADER_BYTES, length, 1 };
    frame->type = type;
    if (type == BTRC_DAEMON_INIT || type == BTRC_DAEMON_COMMIT || type == BTRC_DAEMON_ACK) {
        const unsigned char *token = btrc_daemon_read(&reader, 16);
        if (token != NULL) memcpy(frame->token, token, 16);
    }
    if (type == BTRC_DAEMON_INIT) {
        frame->remaining_startup_ms = btrc_daemon_read_integer(&reader, 8);
        frame->lifetime = (uint32_t)btrc_daemon_read_integer(&reader, 4);
        frame->auto_restart = (uint32_t)btrc_daemon_read_integer(&reader, 4);
        frame->name = btrc_daemon_read_text(&reader);
        frame->control_path = btrc_daemon_read_text(&reader);
        frame->log_path = btrc_daemon_read_text(&reader);
        frame->cwd = btrc_daemon_read_text(&reader);
        frame->executable = btrc_daemon_read_text(&reader);
        frame->arguments = btrc_daemon_read_vector(&reader);
        frame->environment = btrc_daemon_read_vector(&reader);
        if (frame->remaining_startup_ms == 0 || frame->auto_restart > 1 || frame->lifetime > 1
                || frame->arguments.count == 0) reader.valid = 0;
    } else if (type == BTRC_DAEMON_READY || type == BTRC_DAEMON_ACK) {
        frame->supervisor_pid = (uint32_t)btrc_daemon_read_integer(&reader, 4);
        frame->lifetime = (uint32_t)btrc_daemon_read_integer(&reader, 4);
        if (frame->supervisor_pid < 2 || frame->supervisor_pid > INT_MAX || frame->lifetime > 1) reader.valid = 0;
    } else if (type == BTRC_DAEMON_ERROR) {
        frame->stage = (uint32_t)btrc_daemon_read_integer(&reader, 4);
        frame->domain = (uint32_t)btrc_daemon_read_integer(&reader, 4);
        frame->native_code = (uint32_t)btrc_daemon_read_integer(&reader, 4);
        frame->ownership_state = (uint32_t)btrc_daemon_read_integer(&reader, 4);
        if (frame->ownership_state > 2) reader.valid = 0;
    }
    if (!reader.valid || reader.remaining != 0) {
        memset(frame, 0, sizeof(*frame));
        return -1;
    }
    return 0;
}

typedef struct {
    unsigned char *data;
    size_t capacity, size;
    int valid;
} btrc_daemon_writer;

static inline void btrc_daemon_write(btrc_daemon_writer *writer, const void *data, size_t size) {
    if (!writer->valid) return;
    size_t maximum = BTRC_DAEMON_HEADER_BYTES + BTRC_DAEMON_MAX_PAYLOAD;
    if (size > maximum - writer->size || (size != 0 && data == NULL)
            || (writer->data != NULL && size > writer->capacity - writer->size)) {
        writer->valid = 0;
        return;
    }
    if (size != 0 && writer->data != NULL) memcpy(writer->data + writer->size, data, size);
    writer->size += size;
}

static inline void btrc_daemon_write_integer(btrc_daemon_writer *writer, uint64_t value, size_t size) {
    unsigned char bytes[8];
    for (size_t index = 0; index < size; index++) bytes[index] = (unsigned char)(value >> (index * 8));
    btrc_daemon_write(writer, bytes, size);
}

static inline void btrc_daemon_write_text(btrc_daemon_writer *writer, btrc_daemon_text text) {
    if (!btrc_daemon_text_valid(text)) { writer->valid = 0; return; }
    btrc_daemon_write_integer(writer, text.size, 4);
    btrc_daemon_write(writer, text.data, text.size);
}

static inline void btrc_daemon_write_vector(btrc_daemon_writer *writer,
        const btrc_daemon_text *items, size_t count) {
    if (count > BTRC_DAEMON_MAX_ITEMS || (items == NULL && count != 0)) { writer->valid = 0; return; }
    btrc_daemon_write_integer(writer, count, 4);
    for (size_t index = 0; writer->valid && index < count; index++) btrc_daemon_write_text(writer, items[index]);
}

static inline btrc_daemon_writer btrc_daemon_begin(unsigned char *data, size_t capacity, uint16_t type) {
    btrc_daemon_writer writer = { data, capacity, 0, 1 };
    btrc_daemon_write(&writer, "BTRCDM1\0", 8);
    btrc_daemon_write_integer(&writer, 1, 2);
    btrc_daemon_write_integer(&writer, type, 2);
    btrc_daemon_write_integer(&writer, 0, 4);
    return writer;
}

static inline int btrc_daemon_finish(btrc_daemon_writer *writer, size_t *size) {
    *size = 0;
    if (!writer->valid) return -1;
    uint32_t payload = (uint32_t)(writer->size - BTRC_DAEMON_HEADER_BYTES);
    if (writer->data != NULL) {
        for (size_t index = 0; index < 4; index++) writer->data[12 + index] = (unsigned char)(payload >> (index * 8));
    }
    *size = writer->size;
    return 0;
}

/* NULL output with zero capacity queries the required size. A failure may
 * write a prefix, but reports zero bytes: transport sends only on success. */
static inline int btrc_daemon_encode_init(const btrc_daemon_init *init,
        unsigned char *data, size_t capacity, size_t *size) {
    *size = 0;
    if (init == NULL || (data == NULL && capacity != 0) || init->remaining_startup_ms == 0
            || init->lifetime > 1 || init->auto_restart > 1 || init->argument_count == 0) return -1;
    btrc_daemon_writer writer = btrc_daemon_begin(data, capacity, BTRC_DAEMON_INIT);
    btrc_daemon_write(&writer, init->token, 16);
    btrc_daemon_write_integer(&writer, init->remaining_startup_ms, 8);
    btrc_daemon_write_integer(&writer, init->lifetime, 4);
    btrc_daemon_write_integer(&writer, init->auto_restart, 4);
    btrc_daemon_write_text(&writer, init->name);
    btrc_daemon_write_text(&writer, init->control_path);
    btrc_daemon_write_text(&writer, init->log_path);
    btrc_daemon_write_text(&writer, init->cwd);
    btrc_daemon_write_text(&writer, init->executable);
    btrc_daemon_write_vector(&writer, init->arguments, init->argument_count);
    btrc_daemon_write_vector(&writer, init->environment, init->environment_count);
    return btrc_daemon_finish(&writer, size);
}

static inline int btrc_daemon_encode_signal(const btrc_daemon_frame *frame,
        unsigned char *data, size_t capacity, size_t *size) {
    *size = 0;
    if (frame == NULL || (data == NULL && capacity != 0)
            || frame->type < BTRC_DAEMON_READY || frame->type > BTRC_DAEMON_ERROR) return -1;
    btrc_daemon_writer writer = btrc_daemon_begin(data, capacity, frame->type);
    if (frame->type == BTRC_DAEMON_COMMIT || frame->type == BTRC_DAEMON_ACK) btrc_daemon_write(&writer, frame->token, 16);
    if (frame->type == BTRC_DAEMON_READY || frame->type == BTRC_DAEMON_ACK) {
        if (frame->supervisor_pid < 2 || frame->supervisor_pid > INT_MAX || frame->lifetime > 1) writer.valid = 0;
        btrc_daemon_write_integer(&writer, frame->supervisor_pid, 4);
        btrc_daemon_write_integer(&writer, frame->lifetime, 4);
    } else if (frame->type == BTRC_DAEMON_ERROR) {
        if (frame->ownership_state > 2) writer.valid = 0;
        btrc_daemon_write_integer(&writer, frame->stage, 4);
        btrc_daemon_write_integer(&writer, frame->domain, 4);
        btrc_daemon_write_integer(&writer, frame->native_code, 4);
        btrc_daemon_write_integer(&writer, frame->ownership_state, 4);
    }
    return btrc_daemon_finish(&writer, size);
}

#endif
