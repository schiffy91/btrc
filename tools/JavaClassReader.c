/*
 * JavaClassReader reads public Java declarations from class files and prints
 * them as one btrc native ABI document: the JNI counterpart of
 * tools/NativeHeaderReader.cpp (docs/design/native-interop-ownership.md,
 * sections 2.3 and 3). It is strict C11 plus zlib, which inflates jar
 * entries; it needs no JVM and no LLVM.
 *
 *   JavaClassReader --target=<triple> --classpath=<entry>[:<entry>...]
 *                   --symbol=<symbol> [--symbol=<symbol>...]
 *
 * A classpath entry ending in .jar or .zip is a zip archive; any other entry
 * is a directory of package subdirectories. --classpath may repeat, and its
 * entries keep their order; each class resolves from the first entry that
 * holds it. A symbol names a class (java.io.File), a method
 * or constructor by its JVM descriptor (java.io.File.getPath()Ljava/lang/String;,
 * java.io.File.<init>(Ljava/lang/String;)V), or a field by its descriptor
 * (java.lang.Integer.MAX_VALUE:I). Packages are separated by dots and nested
 * classes by `$`, as in Class.getName().
 *
 * Only public classes, and their public members that are neither synthetic
 * nor bridges, are visible. Every failure (a usage error, an unknown or
 * hidden symbol, a malformed class file or jar) prints one line on stderr and
 * exits with status 1 before anything reaches stdout. Every read of a file
 * is bounds-checked, so hostile input fails the same way.
 */

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <zlib.h>

#define DOCUMENT_SCHEMA "btrc.native-declarations.v3"
#define READER_IDENTITY "btrc-class-reader/1"

/* No real class file comes near this; the bound keeps a hostile size claim
   from becoming an allocation. */
#define MAXIMUM_CLASS_BYTES ((size_t)64 * 1024 * 1024)

/* Access flags (JVMS 4.1, 4.5, 4.6). */
enum {
    ACC_PUBLIC = 0x0001,
    ACC_STATIC = 0x0008,
    ACC_FINAL = 0x0010,
    ACC_BRIDGE = 0x0040,
    ACC_NATIVE = 0x0100,
    ACC_INTERFACE = 0x0200,
    ACC_ABSTRACT = 0x0400,
    ACC_SYNTHETIC = 0x1000,
    ACC_MODULE = 0x8000
};

/* Constant pool tags (JVMS 4.4). */
enum {
    CONSTANT_UTF8 = 1,
    CONSTANT_INTEGER = 3,
    CONSTANT_FLOAT = 4,
    CONSTANT_LONG = 5,
    CONSTANT_DOUBLE = 6,
    CONSTANT_CLASS = 7,
    CONSTANT_STRING = 8,
    CONSTANT_FIELDREF = 9,
    CONSTANT_METHODREF = 10,
    CONSTANT_INTERFACE_METHODREF = 11,
    CONSTANT_NAME_AND_TYPE = 12,
    CONSTANT_METHOD_HANDLE = 15,
    CONSTANT_METHOD_TYPE = 16,
    CONSTANT_DYNAMIC = 17,
    CONSTANT_INVOKE_DYNAMIC = 18,
    CONSTANT_MODULE = 19,
    CONSTANT_PACKAGE = 20
};

static const char usageText[] =
    "usage: JavaClassReader --target=<triple> --classpath=<entry>[:<entry>...] "
    "--symbol=<symbol> [--symbol=<symbol>...]";

/* ---- Failure and memory ------------------------------------------------ */

static _Noreturn void fail(const char *format, ...) {
    va_list arguments;
    va_start(arguments, format);
    fputs("JavaClassReader: ", stderr);
    vfprintf(stderr, format, arguments);
    va_end(arguments);
    fputc('\n', stderr);
    exit(1);
}

static void *allocate(size_t size) {
    void *memory = malloc(size ? size : 1);
    if (memory == NULL) fail("out of memory");
    return memory;
}

static void *reallocate(void *memory, size_t size) {
    void *grown = realloc(memory, size ? size : 1);
    if (grown == NULL) fail("out of memory");
    return grown;
}

static char *copyText(const char *text, size_t length) {
    char *copy = allocate(length + 1);
    if (length) memcpy(copy, text, length);
    copy[length] = '\0';
    return copy;
}

/* A growable byte string, always NUL-terminated once it holds anything. */
struct Buffer {
    char *data;
    size_t length;
    size_t capacity;
};

static void appendBytes(struct Buffer *buffer, const void *bytes, size_t length) {
    if (length >= SIZE_MAX - buffer->length) fail("out of memory");
    size_t needed = buffer->length + length + 1;
    if (needed > buffer->capacity) {
        size_t capacity = buffer->capacity ? buffer->capacity : 256;
        while (capacity < needed) capacity = capacity > SIZE_MAX / 2 ? needed : capacity * 2;
        buffer->data = reallocate(buffer->data, capacity);
        buffer->capacity = capacity;
    }
    if (length) memcpy(buffer->data + buffer->length, bytes, length);
    buffer->length += length;
    buffer->data[buffer->length] = '\0';
}

static void appendText(struct Buffer *buffer, const char *text) {
    appendBytes(buffer, text, strlen(text));
}

/* ---- Text: UTF-8, modified UTF-8 and names ------------------------------ */

/* Whether text is well-formed UTF-8: no overlong forms, surrogates or code
   points past U+10FFFF. Everything the document prints passes through here
   or through decodeName, so the JSON writer never sees invalid UTF-8. */
static int isUtf8(const char *text, size_t length) {
    const unsigned char *bytes = (const unsigned char *)text;
    size_t index = 0;
    while (index < length) {
        unsigned lead = bytes[index];
        size_t extra;
        uint32_t minimum;
        uint32_t value;
        if (lead < 0x80) {
            ++index;
            continue;
        }
        if ((lead & 0xE0) == 0xC0) {
            extra = 1;
            minimum = 0x80;
            value = lead & 0x1F;
        } else if ((lead & 0xF0) == 0xE0) {
            extra = 2;
            minimum = 0x800;
            value = lead & 0x0F;
        } else if ((lead & 0xF8) == 0xF0) {
            extra = 3;
            minimum = 0x10000;
            value = lead & 0x07;
        } else {
            return 0;
        }
        if (extra > length - index - 1) return 0;
        for (size_t offset = 1; offset <= extra; ++offset) {
            unsigned next = bytes[index + offset];
            if ((next & 0xC0) != 0x80) return 0;
            value = value << 6 | (next & 0x3F);
        }
        if (value < minimum || value > 0x10FFFF || (value >= 0xD800 && value <= 0xDFFF)) return 0;
        index += extra + 1;
    }
    return 1;
}

/* Re-encodes UTF-8 as the modified UTF-8 of a class file (JVMS 4.4.7), in
   which a supplementary character is a surrogate pair of three-byte
   sequences, so a symbol compares bytewise with constant pool names. Four
   bytes become six, so the result is at most half again as long. */
static char *toModifiedUtf8(const char *text, size_t *length) {
    size_t size = strlen(text);
    const unsigned char *bytes = (const unsigned char *)text;
    char *encoded = allocate(size + size / 2 + 1);
    size_t out = 0;
    for (size_t index = 0; index < size;) {
        if ((bytes[index] & 0xF8) != 0xF0) {
            encoded[out++] = text[index++];
            continue;
        }
        uint32_t value = ((uint32_t)(bytes[index] & 0x07) << 18 | (uint32_t)(bytes[index + 1] & 0x3F) << 12
                          | (uint32_t)(bytes[index + 2] & 0x3F) << 6 | (uint32_t)(bytes[index + 3] & 0x3F))
                         - 0x10000;
        uint32_t units[2] = {0xD800 + (value >> 10), 0xDC00 + (value & 0x3FF)};
        for (int unit = 0; unit < 2; ++unit) {
            encoded[out++] = (char)(0xE0 | units[unit] >> 12);
            encoded[out++] = (char)(0x80 | (units[unit] >> 6 & 0x3F));
            encoded[out++] = (char)(0x80 | (units[unit] & 0x3F));
        }
        index += 4;
    }
    encoded[out] = '\0';
    *length = out;
    return encoded;
}

/* Whether name is a binary class name: non-empty segments split by
   separator, none holding the other separator, ';' or '[' (JVMS 4.2.1). The
   dotted form comes from symbols and the slashed form from class files. */
static int isBinaryName(const char *name, char separator) {
    char other = separator == '.' ? '/' : '.';
    size_t segment = 0;
    for (const char *character = name;; ++character) {
        if (*character == '\0' || *character == separator) {
            if (segment == 0) return 0;
            if (*character == '\0') return 1;
            segment = 0;
        } else if (*character == other || *character == ';' || *character == '[') {
            return 0;
        } else {
            ++segment;
        }
    }
}

/* Whether name is an unqualified field or method name (JVMS 4.2.2). Only
   the two initialization methods may use '<' and '>'. */
static int isMemberName(const char *name, int method) {
    if (method && (strcmp(name, "<init>") == 0 || strcmp(name, "<clinit>") == 0)) return 1;
    if (*name == '\0') return 0;
    const char *forbidden = method ? ".;[/<>" : ".;[/";
    return strpbrk(name, forbidden) == NULL;
}

static char *dottedName(const char *binaryName) {
    char *name = copyText(binaryName, strlen(binaryName));
    for (char *character = name; *character; ++character) {
        if (*character == '/') *character = '.';
    }
    return name;
}

/* ---- Descriptors (JVMS 4.3) --------------------------------------------- */

/* The position after the field descriptor that starts at text[position], or
   0 when none starts there (a descriptor is never empty, so 0 is free). */
static size_t fieldDescriptorEnd(const char *text, size_t position) {
    size_t dimensions = 0;
    while (text[position] == '[') {
        if (++dimensions > 255) return 0;
        ++position;
    }
    switch (text[position]) {
    case 'B':
    case 'C':
    case 'D':
    case 'F':
    case 'I':
    case 'J':
    case 'S':
    case 'Z':
        return position + 1;
    case 'L': {
        size_t segment = ++position;
        for (;; ++position) {
            char character = text[position];
            if (character == '\0' || character == '.' || character == '[') return 0;
            if (character == ';' || character == '/') {
                if (position == segment) return 0;
                if (character == ';') return position + 1;
                segment = position + 1;
            }
        }
    }
    default:
        return 0;
    }
}

static int isFieldDescriptor(const char *text) {
    size_t end = fieldDescriptorEnd(text, 0);
    return end != 0 && text[end] == '\0';
}

/* The position of the return type in a well-formed method descriptor. A
   class name may contain ')', so the parameters are walked, not searched. */
static size_t returnTypePosition(const char *descriptor) {
    size_t position = 1;
    while (descriptor[position] != ')') position = fieldDescriptorEnd(descriptor, position);
    return position + 1;
}

static int isMethodDescriptor(const char *text) {
    if (text[0] != '(') return 0;
    size_t position = 1;
    while (text[position] != ')') {
        position = fieldDescriptorEnd(text, position);
        if (position == 0) return 0;
    }
    ++position;
    if (text[position] == 'V') return text[position + 1] == '\0';
    return isFieldDescriptor(text + position);
}

/* ---- JSON --------------------------------------------------------------- */

/* Appends text as a JSON string. The text is valid UTF-8, so only quotes,
   backslashes and control characters need escapes; other bytes pass through. */
static void appendJsonString(struct Buffer *buffer, const char *text, size_t length) {
    static const char hex[] = "0123456789abcdef";
    appendBytes(buffer, "\"", 1);
    for (size_t index = 0; index < length; ++index) {
        unsigned byte = (unsigned char)text[index];
        const char *escape = NULL;
        switch (byte) {
        case '"': escape = "\\\""; break;
        case '\\': escape = "\\\\"; break;
        case '\b': escape = "\\b"; break;
        case '\f': escape = "\\f"; break;
        case '\n': escape = "\\n"; break;
        case '\r': escape = "\\r"; break;
        case '\t': escape = "\\t"; break;
        default: break;
        }
        if (escape != NULL) {
            appendText(buffer, escape);
        } else if (byte < 0x20) {
            char unicode[6] = {'\\', 'u', '0', '0', hex[byte >> 4], hex[byte & 0xF]};
            appendBytes(buffer, unicode, sizeof unicode);
        } else {
            appendBytes(buffer, &text[index], 1);
        }
    }
    appendBytes(buffer, "\"", 1);
}

static void appendJsonText(struct Buffer *buffer, const char *text) {
    appendJsonString(buffer, text, strlen(text));
}

static void appendJsonBool(struct Buffer *buffer, int value) {
    appendText(buffer, value ? "true" : "false");
}

/* Every type object ends with the qualifiers NativeHeaderReader reports. Java
   has none; references are nullable until the reader reads annotations. */
static void appendQualifiers(struct Buffer *buffer, const char *nullability) {
    appendText(buffer, ",\"const\":false,\"volatile\":false,\"restrict\":false,\"nullability\":\"");
    appendText(buffer, nullability);
    appendText(buffer, "\"}");
}

static void appendObjectType(struct Buffer *buffer, const char *binaryName) {
    char *name = dottedName(binaryName);
    appendText(buffer, "{\"kind\":\"java_object\",\"name\":");
    appendJsonText(buffer, name);
    appendText(buffer, ",\"binary_name\":");
    appendJsonText(buffer, binaryName);
    appendQualifiers(buffer, "nullable");
    free(name);
}

/* JNI's primitive types reuse NativeBuiltin. The floating types carry no
   "signed" key, as Clang reports them. */
static const struct Primitive {
    char code;
    const char *name;
    int bits;
    int sign; /* 1 signed, 0 unsigned, -1 floating */
} primitives[] = {
    {'Z', "jboolean", 8, 0}, {'B', "jbyte", 8, 1},  {'C', "jchar", 16, 0},  {'S', "jshort", 16, 1},
    {'I', "jint", 32, 1},    {'J', "jlong", 64, 1}, {'F', "jfloat", 32, -1}, {'D', "jdouble", 64, -1},
};

/* Appends the type of the well-formed field descriptor (or V) at
   descriptor[position], returning the position after it. */
static size_t appendDescriptorType(struct Buffer *buffer, const char *descriptor, size_t position) {
    char code = descriptor[position];
    if (code == 'V') {
        appendText(buffer, "{\"kind\":\"builtin\",\"name\":\"void\"");
        appendQualifiers(buffer, "unannotated");
        return position + 1;
    }
    if (code == '[') {
        appendText(buffer, "{\"kind\":\"java_array\",\"element\":");
        position = appendDescriptorType(buffer, descriptor, position + 1);
        appendQualifiers(buffer, "nullable");
        return position;
    }
    if (code == 'L') {
        const char *start = descriptor + position + 1;
        size_t length = (size_t)(strchr(start, ';') - start);
        char *binaryName = copyText(start, length);
        appendObjectType(buffer, binaryName);
        free(binaryName);
        return position + length + 2;
    }
    for (size_t index = 0; index < sizeof primitives / sizeof primitives[0]; ++index) {
        const struct Primitive *primitive = &primitives[index];
        if (primitive->code != code) continue;
        char numbers[64];
        snprintf(numbers, sizeof numbers, ",\"bits\":%d,\"alignment_bits\":%d", primitive->bits, primitive->bits);
        appendText(buffer, "{\"kind\":\"builtin\",\"name\":\"");
        appendText(buffer, primitive->name);
        appendText(buffer, "\"");
        appendText(buffer, numbers);
        if (primitive->sign >= 0) {
            appendText(buffer, ",\"signed\":");
            appendJsonBool(buffer, primitive->sign);
        }
        appendQualifiers(buffer, "unannotated");
        return position + 1;
    }
    fail("internal error: unchecked descriptor %s", descriptor);
}

static void appendMethodType(struct Buffer *buffer, const char *descriptor) {
    appendText(buffer, "{\"kind\":\"function\",\"return_type\":");
    appendDescriptorType(buffer, descriptor, returnTypePosition(descriptor));
    appendText(buffer, ",\"parameters\":[");
    for (size_t position = 1; descriptor[position] != ')';) {
        if (position != 1) appendText(buffer, ",");
        position = appendDescriptorType(buffer, descriptor, position);
    }
    appendText(buffer, "],\"variadic\":false,\"calling_convention\":\"java\"");
    appendQualifiers(buffer, "unannotated");
}

/* ---- SHA-256 (FIPS 180-4), for the document's reader identity ----------- */

struct Sha256 {
    uint32_t state[8];
    uint64_t length;
    unsigned char block[64];
    size_t used;
};

static const uint32_t sha256Rounds[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

static uint32_t rotateRight(uint32_t value, unsigned count) {
    return value >> count | value << (32 - count);
}

static void sha256Block(struct Sha256 *hash, const unsigned char *block) {
    uint32_t schedule[64];
    for (int index = 0; index < 16; ++index) {
        const unsigned char *word = block + 4 * index;
        schedule[index] = (uint32_t)word[0] << 24 | (uint32_t)word[1] << 16 | (uint32_t)word[2] << 8 | word[3];
    }
    for (int index = 16; index < 64; ++index) {
        uint32_t early = schedule[index - 15];
        uint32_t late = schedule[index - 2];
        uint32_t sigma0 = rotateRight(early, 7) ^ rotateRight(early, 18) ^ early >> 3;
        uint32_t sigma1 = rotateRight(late, 17) ^ rotateRight(late, 19) ^ late >> 10;
        schedule[index] = schedule[index - 16] + sigma0 + schedule[index - 7] + sigma1;
    }
    uint32_t a = hash->state[0], b = hash->state[1], c = hash->state[2], d = hash->state[3];
    uint32_t e = hash->state[4], f = hash->state[5], g = hash->state[6], h = hash->state[7];
    for (int index = 0; index < 64; ++index) {
        uint32_t sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
        uint32_t choose = (e & f) ^ (~e & g);
        uint32_t first = h + sum1 + choose + sha256Rounds[index] + schedule[index];
        uint32_t sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
        uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        h = g;
        g = f;
        f = e;
        e = d + first;
        d = c;
        c = b;
        b = a;
        a = first + sum0 + majority;
    }
    hash->state[0] += a;
    hash->state[1] += b;
    hash->state[2] += c;
    hash->state[3] += d;
    hash->state[4] += e;
    hash->state[5] += f;
    hash->state[6] += g;
    hash->state[7] += h;
}

static void sha256Start(struct Sha256 *hash) {
    static const uint32_t initial[8] = {
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    };
    memcpy(hash->state, initial, sizeof initial);
    hash->length = 0;
    hash->used = 0;
}

static void sha256Update(struct Sha256 *hash, const unsigned char *bytes, size_t length) {
    hash->length += length;
    while (length) {
        size_t take = 64 - hash->used;
        if (take > length) take = length;
        memcpy(hash->block + hash->used, bytes, take);
        hash->used += take;
        bytes += take;
        length -= take;
        if (hash->used == 64) {
            sha256Block(hash, hash->block);
            hash->used = 0;
        }
    }
}

/* Pads, finishes and writes the digest as 64 lowercase hex digits. */
static void sha256Finish(struct Sha256 *hash, char hexDigest[65]) {
    static const char hex[] = "0123456789abcdef";
    uint64_t bits = hash->length * 8;
    unsigned char padding = 0x80;
    sha256Update(hash, &padding, 1);
    padding = 0;
    while (hash->used != 56) sha256Update(hash, &padding, 1);
    unsigned char length[8];
    for (int index = 0; index < 8; ++index) length[index] = (unsigned char)(bits >> (56 - 8 * index));
    sha256Update(hash, length, sizeof length);
    for (int index = 0; index < 32; ++index) {
        unsigned byte = (unsigned)(hash->state[index / 4] >> (24 - 8 * (index % 4))) & 0xFF;
        hexDigest[2 * index] = hex[byte >> 4];
        hexDigest[2 * index + 1] = hex[byte & 0xF];
    }
    hexDigest[64] = '\0';
}

/* ---- Jars: the zip central directory, stored and deflated entries ------ */

struct Jar {
    const char *path;
    FILE *stream;
    uint64_t size;
    unsigned char *directory;
    size_t directorySize;
    unsigned entryCount;
};

static _Noreturn void malformedJar(const struct Jar *jar, const char *problem) {
    fail("malformed jar %s: %s", jar->path, problem);
}

static unsigned littleU2(const unsigned char *bytes) {
    return (unsigned)bytes[0] | (unsigned)bytes[1] << 8;
}

static uint32_t littleU4(const unsigned char *bytes) {
    return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 | (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}

/* Reads length bytes at offset, which must lie inside the archive. */
static void readJarBytes(const struct Jar *jar, uint64_t offset, void *destination, size_t length) {
    if (offset > jar->size || length > jar->size - offset) malformedJar(jar, "a record extends past the end of the archive");
    if (length == 0) return;
    if (fseek(jar->stream, (long)offset, SEEK_SET) != 0 || fread(destination, 1, length, jar->stream) != length) {
        fail("cannot read %s", jar->path);
    }
}

/* Opens an archive and loads its central directory, walking every record
   once so later lookups can trust their bounds. ZIP64 and multi-disk
   archives are refused; a jar of class files needs neither. */
static struct Jar *openJar(const char *path) {
    struct Jar *jar = allocate(sizeof *jar);
    memset(jar, 0, sizeof *jar);
    jar->path = path;
    jar->stream = fopen(path, "rb");
    if (jar->stream == NULL) fail("cannot open classpath entry %s", path);
    if (fseek(jar->stream, 0, SEEK_END) != 0) fail("cannot read %s", path);
    long end = ftell(jar->stream);
    if (end < 0) fail("cannot read %s", path);
    jar->size = (uint64_t)end;

    /* The end record is the last 22 bytes plus a comment of up to 65535. */
    size_t tail = jar->size < 22 + 65535 ? (size_t)jar->size : 22 + 65535;
    if (tail < 22) malformedJar(jar, "too short to be a zip archive");
    unsigned char *bytes = allocate(tail);
    readJarBytes(jar, jar->size - tail, bytes, tail);
    size_t record = 0;
    int found = 0;
    for (size_t position = tail - 22 + 1; position-- > 0;) {
        if (littleU4(bytes + position) == 0x06054b50u && position + 22 + littleU2(bytes + position + 20) == tail) {
            record = position;
            found = 1;
            break;
        }
    }
    if (!found) malformedJar(jar, "no end of central directory record");
    const unsigned char *trailer = bytes + record;
    unsigned entries = littleU2(trailer + 10);
    uint32_t directorySize = littleU4(trailer + 12);
    uint32_t directoryOffset = littleU4(trailer + 16);
    if (entries == 0xFFFF || directorySize == 0xFFFFFFFFu || directoryOffset == 0xFFFFFFFFu) {
        malformedJar(jar, "ZIP64 archives are not supported");
    }
    if (littleU2(trailer + 4) != 0 || littleU2(trailer + 6) != 0 || littleU2(trailer + 8) != entries) {
        malformedJar(jar, "multi-disk archives are not supported");
    }
    uint64_t recordOffset = jar->size - tail + record;
    if (directoryOffset > recordOffset || directorySize > recordOffset - directoryOffset) {
        malformedJar(jar, "the central directory overlaps its end record");
    }
    free(bytes);

    jar->directory = allocate(directorySize);
    jar->directorySize = directorySize;
    jar->entryCount = entries;
    readJarBytes(jar, directoryOffset, jar->directory, directorySize);
    size_t position = 0;
    for (unsigned index = 0; index < entries; ++index) {
        const unsigned char *header = jar->directory + position;
        if (directorySize - position < 46 || littleU4(header) != 0x02014b50u) malformedJar(jar, "bad central directory record");
        size_t length = 46 + (size_t)littleU2(header + 28) + littleU2(header + 30) + littleU2(header + 32);
        if (length > directorySize - position) malformedJar(jar, "bad central directory record");
        position += length;
    }
    return jar;
}

static _Noreturn void malformedEntry(const struct Jar *jar, const char *name, const char *problem) {
    fail("malformed jar %s: entry %s: %s", jar->path, name, problem);
}

/* Extracts the entry a central directory record describes. Sizes and the CRC
   come from the central directory, so entries written with a trailing data
   descriptor (as the jar tool writes them) read the same as any other. */
static unsigned char *extractJarEntry(const struct Jar *jar, const unsigned char *header, const char *name, size_t *size) {
    unsigned flags = littleU2(header + 8);
    unsigned method = littleU2(header + 10);
    uint32_t crc = littleU4(header + 16);
    uint32_t compressedSize = littleU4(header + 20);
    uint32_t inflatedSize = littleU4(header + 24);
    uint32_t localOffset = littleU4(header + 42);
    if (flags & 1) malformedEntry(jar, name, "encrypted entries are not supported");
    if (method != 0 && method != 8) malformedEntry(jar, name, "unsupported compression method");
    if (inflatedSize > MAXIMUM_CLASS_BYTES) malformedEntry(jar, name, "entry is too large");
    if (method == 0 && compressedSize != inflatedSize) malformedEntry(jar, name, "stored entry sizes disagree");

    unsigned char local[30];
    readJarBytes(jar, localOffset, local, sizeof local);
    if (littleU4(local) != 0x04034b50u) malformedEntry(jar, name, "bad local header");
    uint64_t dataOffset = (uint64_t)localOffset + sizeof local + littleU2(local + 26) + littleU2(local + 28);
    if (dataOffset > jar->size || compressedSize > jar->size - dataOffset) {
        malformedEntry(jar, name, "entry data extends past the end of the archive");
    }
    unsigned char *compressed = allocate(compressedSize);
    readJarBytes(jar, dataOffset, compressed, compressedSize);
    unsigned char *bytes = compressed;
    if (method == 8) {
        bytes = allocate(inflatedSize);
        z_stream stream;
        memset(&stream, 0, sizeof stream);
        if (inflateInit2(&stream, -MAX_WBITS) != Z_OK) fail("cannot initialize zlib");
        stream.next_in = compressed;
        stream.avail_in = (uInt)compressedSize;
        stream.next_out = bytes;
        stream.avail_out = (uInt)inflatedSize;
        int status = inflate(&stream, Z_FINISH);
        uLong produced = stream.total_out;
        inflateEnd(&stream);
        free(compressed);
        if (status != Z_STREAM_END || produced != inflatedSize) malformedEntry(jar, name, "corrupt deflate data");
    }
    if (crc32(crc32(0L, Z_NULL, 0), bytes, (uInt)inflatedSize) != crc) malformedEntry(jar, name, "CRC mismatch");
    *size = inflatedSize;
    return bytes;
}

/* The bytes of the named entry, or NULL when the archive has none. */
static unsigned char *readJarEntry(const struct Jar *jar, const char *name, size_t *size) {
    size_t nameLength = strlen(name);
    size_t position = 0;
    for (unsigned index = 0; index < jar->entryCount; ++index) {
        const unsigned char *header = jar->directory + position;
        size_t headerNameLength = littleU2(header + 28);
        position += 46 + headerNameLength + littleU2(header + 30) + littleU2(header + 32);
        if (headerNameLength == nameLength && memcmp(header + 46, name, nameLength) == 0) {
            return extractJarEntry(jar, header, name, size);
        }
    }
    return NULL;
}

/* ---- Class files (JVMS 4) ------------------------------------------------ */

struct Constant {
    unsigned char tag;
    uint32_t offset; /* the entry's payload, just past its tag */
};

struct Member {
    unsigned access;
    unsigned name;
    unsigned descriptor;
};

struct ClassFile {
    char *binaryName; /* java/io/File */
    char *source;     /* <classpath entry>!java/io/File.class */
    unsigned char *bytes;
    size_t size;
    unsigned poolCount;
    struct Constant *pool;
    unsigned access;
    unsigned thisClass;
    unsigned superClass;
    unsigned interfaceCount;
    size_t interfaces; /* offset of the interface index table */
    unsigned fieldCount;
    struct Member *fields;
    unsigned methodCount;
    struct Member *methods;
    int nested; /* an InnerClasses entry describes this class itself */
    unsigned nestedAccess;
    int emitted;
};

static _Noreturn void malformedClass(const struct ClassFile *file, const char *problem) {
    fail("malformed class file %s: %s", file->source, problem);
}

static unsigned bigU2(const unsigned char *bytes) {
    return (unsigned)bytes[0] << 8 | bytes[1];
}

/* A bounds-checked reader over one class file. */
struct Cursor {
    const struct ClassFile *file;
    size_t position;
};

static const unsigned char *take(struct Cursor *cursor, size_t count) {
    if (count > cursor->file->size - cursor->position) malformedClass(cursor->file, "truncated");
    const unsigned char *bytes = cursor->file->bytes + cursor->position;
    cursor->position += count;
    return bytes;
}

static unsigned readU1(struct Cursor *cursor) {
    return take(cursor, 1)[0];
}

static unsigned readU2(struct Cursor *cursor) {
    return bigU2(take(cursor, 2));
}

static uint32_t readU4(struct Cursor *cursor) {
    const unsigned char *bytes = take(cursor, 4);
    return (uint32_t)bytes[0] << 24 | (uint32_t)bytes[1] << 16 | (uint32_t)bytes[2] << 8 | bytes[3];
}

static const struct Constant *poolEntry(const struct ClassFile *file, unsigned index, unsigned tag, const char *problem) {
    if (index == 0 || index >= file->poolCount || file->pool[index].tag != tag) malformedClass(file, problem);
    return &file->pool[index];
}

/* The raw modified UTF-8 bytes of a CONSTANT_Utf8 entry. */
static const unsigned char *utf8Entry(const struct ClassFile *file, unsigned index, size_t *length, const char *problem) {
    const unsigned char *payload = file->bytes + poolEntry(file, index, CONSTANT_UTF8, problem)->offset;
    *length = bigU2(payload);
    return payload + 2;
}

/* Whether a CONSTANT_Utf8 entry holds exactly these modified UTF-8 bytes. */
static int utf8Equals(const struct ClassFile *file, unsigned index, const char *text, size_t length) {
    size_t entryLength;
    const unsigned char *bytes = utf8Entry(file, index, &entryLength, "bad name index");
    return entryLength == length && (length == 0 || memcmp(bytes, text, length) == 0);
}

/* The code unit of the three-byte sequence at bytes[index], or 0 when none
   is there (0 is never a well-formed three-byte value). */
static uint32_t threeByteUnit(const unsigned char *bytes, size_t length, size_t index) {
    if (length - index < 3 || (bytes[index] & 0xF0) != 0xE0 || (bytes[index + 1] & 0xC0) != 0x80
        || (bytes[index + 2] & 0xC0) != 0x80) {
        return 0;
    }
    uint32_t value = (uint32_t)(bytes[index] & 0x0F) << 12 | (uint32_t)(bytes[index + 1] & 0x3F) << 6
                     | (uint32_t)(bytes[index + 2] & 0x3F);
    return value < 0x800 ? 0 : value;
}

/* Decodes a name from modified UTF-8 to UTF-8: the two-byte NUL and each
   surrogate pair get their standard encodings. A name cannot hold NUL or a
   lone surrogate, so either one is malformed. Decoding never lengthens. */
static char *decodeName(const struct ClassFile *file, const unsigned char *bytes, size_t length) {
    char *text = allocate(length + 1);
    size_t out = 0;
    size_t index = 0;
    while (index < length) {
        unsigned lead = bytes[index];
        if (lead >= 0x01 && lead <= 0x7F) {
            text[out++] = (char)lead;
            ++index;
        } else if ((lead & 0xE0) == 0xC0) {
            if (length - index < 2 || (bytes[index + 1] & 0xC0) != 0x80) malformedClass(file, "malformed modified UTF-8");
            uint32_t value = (uint32_t)(lead & 0x1F) << 6 | (uint32_t)(bytes[index + 1] & 0x3F);
            if (value == 0) malformedClass(file, "a name contains NUL");
            if (value < 0x80) malformedClass(file, "malformed modified UTF-8");
            text[out++] = (char)bytes[index];
            text[out++] = (char)bytes[index + 1];
            index += 2;
        } else if ((lead & 0xF0) == 0xE0) {
            uint32_t value = threeByteUnit(bytes, length, index);
            if (value == 0) malformedClass(file, "malformed modified UTF-8");
            if (value >= 0xDC00 && value <= 0xDFFF) malformedClass(file, "a name contains an unpaired surrogate");
            if (value >= 0xD800 && value <= 0xDBFF) {
                uint32_t low = threeByteUnit(bytes, length, index + 3);
                if (low < 0xDC00 || low > 0xDFFF) malformedClass(file, "a name contains an unpaired surrogate");
                uint32_t point = 0x10000 + ((value - 0xD800) << 10) + (low - 0xDC00);
                text[out++] = (char)(0xF0 | point >> 18);
                text[out++] = (char)(0x80 | (point >> 12 & 0x3F));
                text[out++] = (char)(0x80 | (point >> 6 & 0x3F));
                text[out++] = (char)(0x80 | (point & 0x3F));
                index += 6;
            } else {
                memcpy(text + out, bytes + index, 3);
                out += 3;
                index += 3;
            }
        } else {
            malformedClass(file, "malformed modified UTF-8");
        }
    }
    text[out] = '\0';
    return text;
}

/* The decoded internal name of a CONSTANT_Class entry, such as java/io/File. */
static char *className(const struct ClassFile *file, unsigned index, const char *problem) {
    const unsigned char *payload = file->bytes + poolEntry(file, index, CONSTANT_CLASS, problem)->offset;
    size_t length;
    const unsigned char *bytes = utf8Entry(file, bigU2(payload), &length, problem);
    char *name = decodeName(file, bytes, length);
    if (!isBinaryName(name, '/')) malformedClass(file, problem);
    return name;
}

static void skipAttributes(struct Cursor *cursor) {
    unsigned count = readU2(cursor);
    for (unsigned index = 0; index < count; ++index) {
        size_t ignored;
        utf8Entry(cursor->file, readU2(cursor), &ignored, "bad attribute name index");
        take(cursor, readU4(cursor));
    }
}

static void readMembers(struct Cursor *cursor, struct Member **members, unsigned *count, const char *problem) {
    *count = readU2(cursor);
    *members = allocate(*count * sizeof **members);
    for (unsigned index = 0; index < *count; ++index) {
        struct Member *member = &(*members)[index];
        size_t ignored;
        member->access = readU2(cursor);
        member->name = readU2(cursor);
        member->descriptor = readU2(cursor);
        utf8Entry(cursor->file, member->name, &ignored, problem);
        utf8Entry(cursor->file, member->descriptor, &ignored, problem);
        skipAttributes(cursor);
    }
}

/* Records the InnerClasses entry that describes this class itself: a member
   class's own visibility (protected, private) lives there, while its
   access_flags say public or package. */
static void readInnerClasses(struct ClassFile *file, size_t start, uint32_t length) {
    struct Cursor cursor = {file, start};
    if (length < 2) malformedClass(file, "bad InnerClasses attribute");
    unsigned count = readU2(&cursor);
    if (length != 2 + (uint32_t)count * 8) malformedClass(file, "bad InnerClasses attribute");
    for (unsigned index = 0; index < count; ++index) {
        unsigned inner = readU2(&cursor);
        readU2(&cursor);
        readU2(&cursor);
        unsigned access = readU2(&cursor);
        if (inner == file->thisClass && !file->nested) {
            file->nested = 1;
            file->nestedAccess = access;
        }
    }
}

/* Parses and checks the whole class file. Names and descriptors stay in the
   constant pool and are compared there; only the ones the document prints
   are decoded, so an unusual string constant cannot reject a class. */
static void parseClass(struct ClassFile *file) {
    struct Cursor cursor = {file, 0};
    if (readU4(&cursor) != 0xCAFEBABEu) malformedClass(file, "bad magic number");
    readU2(&cursor);
    if (readU2(&cursor) < 45) malformedClass(file, "unsupported class file version");
    file->poolCount = readU2(&cursor);
    if (file->poolCount == 0) malformedClass(file, "empty constant pool");
    file->pool = allocate(file->poolCount * sizeof *file->pool);
    memset(file->pool, 0, file->poolCount * sizeof *file->pool);
    for (unsigned index = 1; index < file->poolCount; ++index) {
        unsigned tag = readU1(&cursor);
        file->pool[index].tag = (unsigned char)tag;
        file->pool[index].offset = (uint32_t)cursor.position;
        switch (tag) {
        case CONSTANT_UTF8:
            take(&cursor, readU2(&cursor));
            break;
        case CONSTANT_INTEGER:
        case CONSTANT_FLOAT:
        case CONSTANT_FIELDREF:
        case CONSTANT_METHODREF:
        case CONSTANT_INTERFACE_METHODREF:
        case CONSTANT_NAME_AND_TYPE:
        case CONSTANT_DYNAMIC:
        case CONSTANT_INVOKE_DYNAMIC:
            take(&cursor, 4);
            break;
        case CONSTANT_LONG:
        case CONSTANT_DOUBLE:
            /* An eight-byte constant also takes the next index, which must
               exist and stays unusable (its tag remains 0). */
            take(&cursor, 8);
            if (++index >= file->poolCount) malformedClass(file, "an eight-byte constant overflows the constant pool");
            break;
        case CONSTANT_CLASS:
        case CONSTANT_STRING:
        case CONSTANT_METHOD_TYPE:
        case CONSTANT_MODULE:
        case CONSTANT_PACKAGE:
            take(&cursor, 2);
            break;
        case CONSTANT_METHOD_HANDLE:
            take(&cursor, 3);
            break;
        default:
            malformedClass(file, "unknown constant pool tag");
        }
    }
    file->access = readU2(&cursor);
    file->thisClass = readU2(&cursor);
    file->superClass = readU2(&cursor);
    file->interfaceCount = readU2(&cursor);
    file->interfaces = cursor.position;
    take(&cursor, (size_t)file->interfaceCount * 2);
    readMembers(&cursor, &file->fields, &file->fieldCount, "bad field name or descriptor index");
    readMembers(&cursor, &file->methods, &file->methodCount, "bad method name or descriptor index");
    unsigned attributes = readU2(&cursor);
    for (unsigned index = 0; index < attributes; ++index) {
        unsigned name = readU2(&cursor);
        uint32_t length = readU4(&cursor);
        size_t start = cursor.position;
        take(&cursor, length);
        size_t nameLength;
        const unsigned char *nameBytes = utf8Entry(file, name, &nameLength, "bad attribute name index");
        if (nameLength == 12 && memcmp(nameBytes, "InnerClasses", 12) == 0) readInnerClasses(file, start, length);
    }
    if (cursor.position != file->size) malformedClass(file, "trailing bytes after the class attributes");
}

/* ---- Symbols -------------------------------------------------------------- */

enum SymbolKind { SYMBOL_CLASS, SYMBOL_METHOD, SYMBOL_FIELD };

struct Symbol {
    const char *text; /* exactly as given */
    enum SymbolKind kind;
    char *className;  /* java.io.File */
    char *binaryName; /* java/io/File */
    char *member;     /* getPath, <init> or MAX_VALUE; members only */
    char *descriptor; /* ()Ljava/lang/String; or I; members only */
    char *encodedMember; /* member and descriptor in modified UTF-8 */
    size_t encodedMemberLength;
    char *encodedDescriptor;
    size_t encodedDescriptorLength;
};

static _Noreturn void invalidSymbol(const char *text, const char *problem) {
    fail("invalid symbol %s: %s", text, problem);
}

/* Splits a symbol into its class and member. A '(' starts a method
   descriptor and otherwise a ':' starts a field descriptor; the member name
   follows the last '.' before either. */
static void parseSymbol(struct Symbol *symbol, const char *text) {
    memset(symbol, 0, sizeof *symbol);
    symbol->text = text;
    if (!isUtf8(text, strlen(text))) invalidSymbol(text, "not UTF-8");
    const char *parenthesis = strchr(text, '(');
    const char *colon = parenthesis ? NULL : strchr(text, ':');
    const char *head = parenthesis ? parenthesis : colon ? colon : text + strlen(text);
    symbol->kind = parenthesis ? SYMBOL_METHOD : colon ? SYMBOL_FIELD : SYMBOL_CLASS;
    const char *classEnd = head;
    if (symbol->kind != SYMBOL_CLASS) {
        const char *dot = NULL;
        for (const char *character = text; character < head; ++character) {
            if (*character == '.') dot = character;
        }
        if (dot == NULL) invalidSymbol(text, "a member symbol is <class>.<member> and its descriptor");
        classEnd = dot;
        symbol->member = copyText(dot + 1, (size_t)(head - dot - 1));
        const char *descriptor = parenthesis ? parenthesis : colon + 1;
        symbol->descriptor = copyText(descriptor, strlen(descriptor));
    }
    symbol->className = copyText(text, (size_t)(classEnd - text));
    if (!isBinaryName(symbol->className, '.')) invalidSymbol(text, "the class is not a dotted binary name");
    symbol->binaryName = copyText(symbol->className, strlen(symbol->className));
    for (char *character = symbol->binaryName; *character; ++character) {
        if (*character == '.') *character = '/';
    }
    if (symbol->kind == SYMBOL_CLASS) return;
    int method = symbol->kind == SYMBOL_METHOD;
    if (!isMemberName(symbol->member, method)) invalidSymbol(text, method ? "bad method name" : "bad field name");
    if (method && !isMethodDescriptor(symbol->descriptor)) invalidSymbol(text, "bad method descriptor");
    if (!method && !isFieldDescriptor(symbol->descriptor)) invalidSymbol(text, "bad field descriptor");
    if (method && strcmp(symbol->member, "<init>") == 0 && symbol->descriptor[returnTypePosition(symbol->descriptor)] != 'V') {
        invalidSymbol(text, "a constructor returns V");
    }
    symbol->encodedMember = toModifiedUtf8(symbol->member, &symbol->encodedMemberLength);
    symbol->encodedDescriptor = toModifiedUtf8(symbol->descriptor, &symbol->encodedDescriptorLength);
}

/* ---- Classpath and class loading ----------------------------------------- */

struct ClasspathEntry {
    const char *path;
    int archive;
    struct Jar *jar; /* opened on first use */
};

struct Reader {
    struct ClasspathEntry *entries;
    size_t entryCount;
    struct ClassFile **classes;
    size_t classCount;
    struct Sha256 digest; /* every class file read, in read order */
};

static int hasArchiveSuffix(const char *path) {
    size_t length = strlen(path);
    if (length < 4) return 0;
    const char *suffix = path + length - 4;
    if (suffix[0] != '.') return 0;
    char lowered[4] = {0};
    for (int index = 1; index < 4; ++index) {
        char character = suffix[index];
        lowered[index - 1] = character >= 'A' && character <= 'Z' ? (char)(character - 'A' + 'a') : character;
    }
    return strcmp(lowered, "jar") == 0 || strcmp(lowered, "zip") == 0;
}

/* Appends each ':'-separated entry. An empty entry would mean the working
   directory to a JVM; a build names its directories, so it is refused. */
static void addClasspath(struct Reader *reader, const char *value) {
    for (const char *start = value;;) {
        const char *end = strchr(start, ':');
        size_t length = end ? (size_t)(end - start) : strlen(start);
        if (length == 0) fail("empty classpath entry in --classpath=%s", value);
        char *path = copyText(start, length);
        if (!isUtf8(path, length)) fail("classpath entry %s is not UTF-8", path);
        reader->entries = reallocate(reader->entries, (reader->entryCount + 1) * sizeof *reader->entries);
        reader->entries[reader->entryCount].path = path;
        reader->entries[reader->entryCount].archive = hasArchiveSuffix(path);
        reader->entries[reader->entryCount].jar = NULL;
        ++reader->entryCount;
        if (end == NULL) return;
        start = end + 1;
    }
}

/* Reads a whole file, or returns NULL when it cannot be opened. Plain C11
   cannot tell a missing directory entry from one without the class, so both
   are simply "not here". */
static unsigned char *readFile(const char *path, size_t *size) {
    FILE *stream = fopen(path, "rb");
    if (stream == NULL) return NULL;
    unsigned char *bytes = NULL;
    size_t length = 0;
    size_t capacity = 0;
    for (;;) {
        if (length == capacity) {
            capacity = capacity ? capacity * 2 : 4096;
            bytes = reallocate(bytes, capacity);
        }
        size_t count = fread(bytes + length, 1, capacity - length, stream);
        length += count;
        if (length > MAXIMUM_CLASS_BYTES) fail("%s is too large to be a class file", path);
        if (count == 0) break;
    }
    int failed = ferror(stream);
    fclose(stream);
    if (failed) fail("cannot read %s", path);
    *size = length;
    return bytes;
}

static int equalsIgnoringAsciiCase(const char *left, const char *right) {
    for (;; ++left, ++right) {
        char a = *left >= 'A' && *left <= 'Z' ? (char)(*left - 'A' + 'a') : *left;
        char b = *right >= 'A' && *right <= 'Z' ? (char)(*right - 'A' + 'a') : *right;
        if (a != b) return 0;
        if (a == '\0') return 1;
    }
}

static void discardClass(struct ClassFile *file) {
    free(file->binaryName);
    free(file->source);
    free(file->bytes);
    free(file->pool);
    free(file->fields);
    free(file->methods);
    free(file);
}

/* Reads and parses entry's copy of a class, or returns NULL when the entry
   has none. A case-insensitive file system answers for another spelling of
   the name; that copy is not this class, so the search goes on, exactly as
   on a case-sensitive one. */
static struct ClassFile *readClass(struct ClasspathEntry *entry, const char *binaryName, const char *entryName) {
    unsigned char *bytes;
    size_t size = 0;
    if (entry->archive) {
        if (entry->jar == NULL) entry->jar = openJar(entry->path);
        bytes = readJarEntry(entry->jar, entryName, &size);
    } else {
        struct Buffer path = {0};
        appendText(&path, entry->path);
        if (entry->path[strlen(entry->path) - 1] != '/') appendText(&path, "/");
        appendText(&path, entryName);
        bytes = readFile(path.data, &size);
        free(path.data);
    }
    if (bytes == NULL) return NULL;

    struct ClassFile *file = allocate(sizeof *file);
    memset(file, 0, sizeof *file);
    file->binaryName = copyText(binaryName, strlen(binaryName));
    file->bytes = bytes;
    file->size = size;
    struct Buffer source = {0};
    appendText(&source, entry->path);
    appendText(&source, "!");
    appendText(&source, entryName);
    file->source = source.data;
    parseClass(file);
    char *declared = className(file, file->thisClass, "bad this_class index");
    int matches = strcmp(declared, binaryName) == 0;
    if (!matches && !equalsIgnoringAsciiCase(declared, binaryName)) {
        fail("class file %s declares %s", file->source, declared);
    }
    free(declared);
    if (matches) return file;
    discardClass(file);
    return NULL;
}

/* Loads a class from the first classpath entry that has it, once, adding its
   bytes to the digest in read order. */
static struct ClassFile *loadClass(struct Reader *reader, const char *binaryName, const char *displayName) {
    for (size_t index = 0; index < reader->classCount; ++index) {
        if (strcmp(reader->classes[index]->binaryName, binaryName) == 0) return reader->classes[index];
    }
    struct Buffer entryName = {0};
    appendText(&entryName, binaryName);
    appendText(&entryName, ".class");
    struct ClassFile *file = NULL;
    for (size_t index = 0; index < reader->entryCount && file == NULL; ++index) {
        file = readClass(&reader->entries[index], binaryName, entryName.data);
    }
    free(entryName.data);
    if (file == NULL) fail("unknown class %s", displayName);
    sha256Update(&reader->digest, file->bytes, file->size);
    reader->classes = reallocate(reader->classes, (reader->classCount + 1) * sizeof *reader->classes);
    reader->classes[reader->classCount++] = file;
    return file;
}

/* ---- Visibility and declarations ----------------------------------------- */

static void requireVisibleClass(const struct ClassFile *file, const char *name) {
    const char *reason = NULL;
    if (file->access & ACC_MODULE) {
        reason = "a module descriptor";
    } else if (!(file->access & ACC_PUBLIC)) {
        reason = "not public";
    } else if (file->access & ACC_SYNTHETIC) {
        reason = "synthetic";
    } else if (file->nested && !(file->nestedAccess & ACC_PUBLIC)) {
        reason = "a member class that is not public";
    }
    if (reason != NULL) fail("unknown class %s (%s)", name, reason);
}

/* Finds the member a symbol selects by name and exact descriptor, so an
   overload is never guessed, and requires it to be visible. */
static const struct Member *findMember(const struct ClassFile *file, const struct Symbol *symbol) {
    int method = symbol->kind == SYMBOL_METHOD;
    const struct Member *members = method ? file->methods : file->fields;
    unsigned count = method ? file->methodCount : file->fieldCount;
    const struct Member *match = NULL;
    for (unsigned index = 0; index < count; ++index) {
        if (!utf8Equals(file, members[index].name, symbol->encodedMember, symbol->encodedMemberLength)) continue;
        if (!utf8Equals(file, members[index].descriptor, symbol->encodedDescriptor, symbol->encodedDescriptorLength)) continue;
        if (match != NULL) malformedClass(file, method ? "a method is declared twice" : "a field is declared twice");
        match = &members[index];
    }
    if (match == NULL) fail("unknown member %s", symbol->text);
    if (!(match->access & ACC_PUBLIC)) fail("unknown member %s (not public)", symbol->text);
    if (method && (match->access & ACC_BRIDGE)) fail("unknown member %s (bridge method)", symbol->text);
    if (match->access & ACC_SYNTHETIC) fail("unknown member %s (synthetic)", symbol->text);
    return match;
}

static void appendClassIdentity(struct Buffer *identity, const char *binaryName) {
    appendText(identity, "L");
    appendText(identity, binaryName);
    appendText(identity, ";");
}

static void appendClass(struct Buffer *buffer, const struct ClassFile *file) {
    char *name = dottedName(file->binaryName);
    struct Buffer identity = {0};
    appendClassIdentity(&identity, file->binaryName);
    appendText(buffer, "{\"kind\":\"java_class\",\"name\":");
    appendJsonText(buffer, name);
    appendText(buffer, ",\"identity\":");
    appendJsonText(buffer, identity.data);
    appendText(buffer, ",\"binary_name\":");
    appendJsonText(buffer, file->binaryName);
    appendText(buffer, ",\"super_name\":");
    if (file->superClass == 0) {
        /* Only java.lang.Object has no superclass (module-info is refused). */
        if (strcmp(file->binaryName, "java/lang/Object") != 0) malformedClass(file, "no superclass");
        appendText(buffer, "null");
    } else {
        char *superName = className(file, file->superClass, "bad super_class index");
        appendJsonText(buffer, superName);
        free(superName);
    }
    appendText(buffer, ",\"super_interfaces\":[");
    for (unsigned index = 0; index < file->interfaceCount; ++index) {
        if (index) appendText(buffer, ",");
        char *interfaceName = className(file, bigU2(file->bytes + file->interfaces + 2 * index), "bad interface index");
        appendJsonText(buffer, interfaceName);
        free(interfaceName);
    }
    appendText(buffer, "],\"interface_class\":");
    appendJsonBool(buffer, (file->access & ACC_INTERFACE) != 0);
    appendText(buffer, ",\"abstract_class\":");
    appendJsonBool(buffer, (file->access & ACC_ABSTRACT) != 0);
    appendText(buffer, ",\"complete\":true,\"type\":");
    appendObjectType(buffer, file->binaryName);
    appendText(buffer, ",\"source\":");
    appendJsonText(buffer, file->source);
    appendText(buffer, ",\"line\":0,\"column\":0}");
    free(identity.data);
    free(name);
}

/* Appends a java_method or java_field. Its identity is the smali form
   Ljava/io/File;->getPath()Ljava/lang/String; or Ljava/lang/Integer;->MAX_VALUE:I. */
static void appendMember(struct Buffer *buffer, const struct ClassFile *file, const struct Symbol *symbol,
                         const struct Member *member) {
    int method = symbol->kind == SYMBOL_METHOD;
    struct Buffer identity = {0};
    appendClassIdentity(&identity, file->binaryName);
    appendText(&identity, "->");
    appendText(&identity, symbol->member);
    if (!method) appendText(&identity, ":");
    appendText(&identity, symbol->descriptor);
    appendText(buffer, method ? "{\"kind\":\"java_method\",\"name\":" : "{\"kind\":\"java_field\",\"name\":");
    appendJsonText(buffer, symbol->text);
    appendText(buffer, ",\"identity\":");
    appendJsonText(buffer, identity.data);
    appendText(buffer, ",\"owner\":");
    appendJsonText(buffer, symbol->className);
    appendText(buffer, method ? ",\"method_name\":" : ",\"field_name\":");
    appendJsonText(buffer, symbol->member);
    appendText(buffer, ",\"descriptor\":");
    appendJsonText(buffer, symbol->descriptor);
    appendText(buffer, ",\"static_member\":");
    appendJsonBool(buffer, (member->access & ACC_STATIC) != 0);
    if (method) {
        appendText(buffer, ",\"constructor\":");
        appendJsonBool(buffer, strcmp(symbol->member, "<init>") == 0);
        appendText(buffer, ",\"native_method\":");
        appendJsonBool(buffer, (member->access & ACC_NATIVE) != 0);
        appendText(buffer, ",\"type\":");
        appendMethodType(buffer, symbol->descriptor);
    } else {
        appendText(buffer, ",\"read_only\":");
        appendJsonBool(buffer, (member->access & ACC_FINAL) != 0);
        appendText(buffer, ",\"type\":");
        appendDescriptorType(buffer, symbol->descriptor, 0);
    }
    appendText(buffer, ",\"source\":");
    appendJsonText(buffer, file->source);
    appendText(buffer, ",\"line\":0,\"column\":0}");
    free(identity.data);
}

/* ---- Entry point ---------------------------------------------------------- */

static const char *optionValue(const char *argument, const char *option) {
    size_t length = strlen(option);
    return strncmp(argument, option, length) == 0 ? argument + length : NULL;
}

int main(int argc, char **argv) {
    const char *target = NULL;
    struct Reader reader;
    memset(&reader, 0, sizeof reader);
    sha256Start(&reader.digest);
    struct Symbol *symbols = allocate((size_t)(argc > 0 ? argc : 1) * sizeof *symbols);
    size_t symbolCount = 0;
    for (int index = 1; index < argc; ++index) {
        const char *argument = argv[index];
        const char *value;
        if (strcmp(argument, "--help") == 0) {
            puts(usageText);
            return 0;
        }
        if ((value = optionValue(argument, "--target=")) != NULL) {
            if (target != NULL) fail("--target is given more than once");
            if (*value == '\0' || !isUtf8(value, strlen(value))) fail("--target must be a non-empty UTF-8 triple");
            target = value;
        } else if ((value = optionValue(argument, "--classpath=")) != NULL) {
            addClasspath(&reader, value);
        } else if ((value = optionValue(argument, "--symbol=")) != NULL) {
            parseSymbol(&symbols[symbolCount++], value);
        } else {
            fail("unknown argument %s; %s", argument, usageText);
        }
    }
    if (target == NULL) fail("--target is required; %s", usageText);
    if (reader.entryCount == 0) fail("--classpath is required; %s", usageText);
    if (symbolCount == 0) fail("at least one --symbol is required; %s", usageText);

    /* Declarations follow the symbols' order. A class precedes its first
       member and appears once; a repeated symbol appears once. */
    struct Buffer declarations = {0};
    for (size_t index = 0; index < symbolCount; ++index) {
        const struct Symbol *symbol = &symbols[index];
        int repeated = 0;
        for (size_t earlier = 0; earlier < index && !repeated; ++earlier) {
            repeated = strcmp(symbols[earlier].text, symbol->text) == 0;
        }
        if (repeated) continue;
        struct ClassFile *file = loadClass(&reader, symbol->binaryName, symbol->className);
        requireVisibleClass(file, symbol->className);
        if (!file->emitted) {
            if (declarations.length) appendText(&declarations, ",");
            appendClass(&declarations, file);
            file->emitted = 1;
        }
        if (symbol->kind == SYMBOL_CLASS) continue;
        const struct Member *member = findMember(file, symbol);
        appendText(&declarations, ",");
        appendMember(&declarations, file, symbol, member);
    }

    char digest[65];
    sha256Finish(&reader.digest, digest);
    struct Buffer document = {0};
    appendText(&document, "{\"schema\":\"" DOCUMENT_SCHEMA "\",\"target\":");
    appendJsonText(&document, target);
    appendText(&document, ",\"clang\":\"" READER_IDENTITY " sha256:");
    appendText(&document, digest);
    appendText(&document, "\",\"big_endian\":false,\"character_bits\":8,\"declarations\":[");
    appendBytes(&document, declarations.data, declarations.length);
    appendText(&document, "],\"records\":[],\"interfaces\":[]}\n");
    if (fwrite(document.data, 1, document.length, stdout) != document.length || fflush(stdout) != 0) {
        fail("cannot write the document");
    }
    return 0;
}
