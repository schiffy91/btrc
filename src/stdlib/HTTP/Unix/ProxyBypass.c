/* Match a numeric no_proxy entry without resolving either operand. Return
 * -1 for a DNS destination so the caller can perform domain suffix matching. */
#include <arpa/inet.h>
#include <string.h>

int btrcHttpProxyNetwork(const char *host, const char *entry) {
    unsigned char address[16], network[16];
    int family = AF_INET;
    if (inet_pton(family, host, address) != 1) {
        family = AF_INET6;
        if (inet_pton(family, host, address) != 1) { return -1; }
    }
    const char *slash = strchr(entry, '/');
    size_t length = slash == NULL ? strlen(entry) : (size_t)(slash - entry);
    char literal[INET6_ADDRSTRLEN];
    if (length == 0 || length >= sizeof(literal)) { return 0; }
    memcpy(literal, entry, length);
    literal[length] = '\0';
    if (inet_pton(family, literal, network) != 1) { return 0; }
    int bits = family == AF_INET ? 32 : 128;
    if (slash != NULL) {
        int prefix = 0;
        const char *cursor = slash + 1;
        if (*cursor == '\0') { return 0; }
        for (; *cursor; cursor++) {
            if (*cursor < '0' || *cursor > '9') { return 0; }
            prefix = prefix * 10 + (*cursor - '0');
            if (prefix > bits) { return 0; }
        }
        bits = prefix;
    }
    int bytes = bits / 8;
    int partial = bits % 8;
    if (memcmp(address, network, (size_t)bytes) != 0) { return 0; }
    return partial == 0 || ((address[bytes] ^ network[bytes]) >> (8 - partial)) == 0;
}
