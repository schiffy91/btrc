/* btrc-runtime-helper:begin __btrc_string_registry */
typedef struct __btrc_string_entry {
    char* value;
    size_t references;
    struct __btrc_string_entry* next;
} __btrc_string_entry;

static __btrc_string_entry* __btrc_string_inline_buckets[64] = {0};
static __btrc_string_entry** __btrc_string_buckets =
    __btrc_string_inline_buckets;
static size_t __btrc_string_bucket_count = 64;
/* btrc-runtime-helper:end __btrc_string_registry */
/* btrc-runtime-helper:begin __btrc_string_registry_lock_state */
static atomic_flag __btrc_string_lock = ATOMIC_FLAG_INIT;
/* btrc-runtime-helper:end __btrc_string_registry_lock_state */
/* btrc-runtime-helper:begin __btrc_string_registry_lock */
static inline void __btrc_string_registry_lock(void) {
    unsigned int delay = 1;
    while (atomic_flag_test_and_set_explicit(
            &__btrc_string_lock, memory_order_acquire)) {
        for (unsigned int spin = 0; spin < delay; spin++) {
            atomic_signal_fence(memory_order_seq_cst);
        }
        if (delay < 1024) delay *= 2;
    }
}

static inline void __btrc_string_registry_unlock(void) {
    atomic_flag_clear_explicit(&__btrc_string_lock, memory_order_release);
}
/* btrc-runtime-helper:end __btrc_string_registry_lock */
/* btrc-runtime-helper:begin __btrc_string_registry_hash */
static inline size_t __btrc_string_hash(const char* value, size_t buckets) {
    uintptr_t bits = (uintptr_t)(const void*)value;
    bits ^= bits >> 17;
    bits *= (uintptr_t)0xed5ad4bbU;
    bits ^= bits >> 11;
    return (size_t)(bits % (uintptr_t)buckets);
}
/* btrc-runtime-helper:end __btrc_string_registry_hash */
/* btrc-runtime-helper:begin __btrc_string_registry_slot */
static inline __btrc_string_entry** __btrc_string_slot(const char* value) {
    size_t index = __btrc_string_hash(value, __btrc_string_bucket_count);
    __btrc_string_entry** slot = &__btrc_string_buckets[index];
    while (*slot && (*slot)->value != value) slot = &(*slot)->next;
    return slot;
}
/* btrc-runtime-helper:end __btrc_string_registry_slot */
/* btrc-runtime-helper:begin __btrc_string_registry_count */
static size_t __btrc_string_entry_count = 0;
/* btrc-runtime-helper:end __btrc_string_registry_count */
/* btrc-runtime-helper:begin __btrc_string_registry_resize */
static inline void __btrc_string_registry_resize(size_t capacity) {
    __btrc_string_entry** old_buckets = __btrc_string_buckets;
    size_t old_capacity = __btrc_string_bucket_count;
    __btrc_string_entry** buckets = (__btrc_string_entry**)
        __btrc_safe_calloc(capacity, sizeof(__btrc_string_entry*));
    for (size_t index = 0; index < old_capacity; index++) {
        __btrc_string_entry* entry = old_buckets[index];
        while (entry) {
            __btrc_string_entry* next = entry->next;
            size_t target = __btrc_string_hash(entry->value, capacity);
            entry->next = buckets[target];
            buckets[target] = entry;
            entry = next;
        }
    }
    if (old_buckets == __btrc_string_inline_buckets) {
        memset(__btrc_string_inline_buckets, 0,
            sizeof(__btrc_string_inline_buckets));
    } else {
        free(old_buckets);
    }
    __btrc_string_buckets = buckets;
    __btrc_string_bucket_count = capacity;
}
/* btrc-runtime-helper:end __btrc_string_registry_resize */
/* btrc-runtime-helper:begin __btrc_string_adopt */
static inline char* __btrc_string_adopt(char* value) {
    if (!value) return NULL;
    __btrc_string_entry* candidate = (__btrc_string_entry*)
        __btrc_safe_realloc(NULL, sizeof(__btrc_string_entry));
    candidate->value = value;
    candidate->references = 1;
    candidate->next = NULL;

    __btrc_string_registry_lock();
    __btrc_string_entry** slot = __btrc_string_slot(value);
    if (*slot) {
        __btrc_string_registry_unlock();
        free(candidate);
        return value;
    }
    if (__btrc_string_entry_count >= __btrc_string_bucket_count
            - __btrc_string_bucket_count / 4) {
        if (__btrc_string_bucket_count > SIZE_MAX / 2) {
            __btrc_string_registry_unlock();
            fprintf(stderr, "btrc: string registry overflow\n");
            exit(1);
        }
        __btrc_string_registry_resize(__btrc_string_bucket_count * 2);
        slot = __btrc_string_slot(value);
    }
    candidate->next = *slot;
    *slot = candidate;
    __btrc_string_entry_count++;
    __btrc_string_registry_unlock();
    return value;
}
/* btrc-runtime-helper:end __btrc_string_adopt */
/* btrc-runtime-helper:begin __btrc_string_retain */
static inline char* __btrc_string_retain(const char* value) {
    if (!value) return NULL;
    __btrc_string_registry_lock();
    if (__btrc_string_bucket_count != 0) {
        __btrc_string_entry* entry = *__btrc_string_slot(value);
        if (entry) {
            if (entry->references == SIZE_MAX) {
                __btrc_string_registry_unlock();
                fprintf(stderr, "btrc: string reference overflow\n");
                exit(1);
            }
            entry->references++;
        }
    }
    __btrc_string_registry_unlock();
    return (char*)value;
}
/* btrc-runtime-helper:end __btrc_string_retain */
/* btrc-runtime-helper:begin __btrc_string_release */
static inline void __btrc_string_release(const char* value) {
    if (!value) return;
    __btrc_string_entry* removed = NULL;
    __btrc_string_entry** retired_buckets = NULL;
    __btrc_string_registry_lock();
    __btrc_string_entry** slot = __btrc_string_slot(value);
    __btrc_string_entry* entry = *slot;
    if (entry && entry->references > 1) {
        entry->references--;
    } else if (entry) {
        *slot = entry->next;
        removed = entry;
        __btrc_string_entry_count--;
        if (__btrc_string_entry_count == 0
                && __btrc_string_buckets != __btrc_string_inline_buckets) {
            retired_buckets = __btrc_string_buckets;
            __btrc_string_buckets = __btrc_string_inline_buckets;
            __btrc_string_bucket_count = 64;
            memset(__btrc_string_inline_buckets, 0,
                sizeof(__btrc_string_inline_buckets));
        }
    }
    __btrc_string_registry_unlock();
    if (removed) {
        free(removed->value);
        free(removed);
    }
    free(retired_buckets);
}
/* btrc-runtime-helper:end __btrc_string_release */
/* btrc-runtime-helper:begin __btrc_string_release_cleanup */
static inline void __btrc_string_release_cleanup(void* value) {
    __btrc_string_release((const char*)value);
}
/* btrc-runtime-helper:end __btrc_string_release_cleanup */
/* btrc-runtime-helper:begin __btrc_string_live_count */
static inline size_t __btrc_string_live_count(void) {
    __btrc_string_registry_lock();
    size_t result = __btrc_string_entry_count;
    __btrc_string_registry_unlock();
    return result;
}
/* btrc-runtime-helper:end __btrc_string_live_count */
/* btrc-runtime-helper:begin __btrc_str_track */
static inline char* __btrc_str_track(char* s) {
    return __btrc_string_adopt(s);
}
/* btrc-runtime-helper:end __btrc_str_track */
/* btrc-runtime-helper:begin __btrc_str_flush */
static inline void __btrc_str_flush(void) {
    /* Retained for source compatibility; ownership is explicit. */
}
/* btrc-runtime-helper:end __btrc_str_flush */
/* btrc-runtime-helper:begin __btrc_string_or_empty */
static inline const char* __btrc_string_or_empty(const char* s) {
    return s ? s : "";
}
/* btrc-runtime-helper:end __btrc_string_or_empty */
/* btrc-runtime-helper:begin __btrc_string_length */
static inline int __btrc_string_length(const char* s) {
    if (!s) return 0;
    size_t length = strlen(s);
    if (length > (size_t)INT_MAX) {
        fprintf(stderr, "btrc: string length overflow\n"); exit(1);
    }
    return (int)length;
}
/* btrc-runtime-helper:end __btrc_string_length */
/* btrc-runtime-helper:begin __btrc_string_alloc */
static inline char* __btrc_string_alloc(int length) {
    if (length < 0) {
        fprintf(stderr, "btrc: negative string allocation\n"); exit(1);
    }
    char* result = (char*)__btrc_safe_realloc(
        NULL, (size_t)length + 1);
    result[length] = '\0';
    char* adopted = __btrc_string_adopt(result);
    if (!adopted) {
        fprintf(stderr, "btrc: string allocation adoption failed\n"); exit(1);
    }
    return adopted;
}
/* btrc-runtime-helper:end __btrc_string_alloc */
/* btrc-runtime-helper:begin __btrc_ascii_upper */
static inline char __btrc_ascii_upper(char value) {
    unsigned char byte = (unsigned char)value;
    return (byte >= 'a' && byte <= 'z') ? (char)(byte - 'a' + 'A') : value;
}
/* btrc-runtime-helper:end __btrc_ascii_upper */
/* btrc-runtime-helper:begin __btrc_ascii_lower */
static inline char __btrc_ascii_lower(char value) {
    unsigned char byte = (unsigned char)value;
    return (byte >= 'A' && byte <= 'Z') ? (char)(byte - 'A' + 'a') : value;
}
/* btrc-runtime-helper:end __btrc_ascii_lower */
/* btrc-runtime-helper:begin __btrc_ascii_space */
static inline bool __btrc_ascii_space(char value) {
    unsigned char byte = (unsigned char)value;
    return byte == ' ' || (byte >= '\t' && byte <= '\r');
}
/* btrc-runtime-helper:end __btrc_ascii_space */
/* btrc-runtime-helper:begin __btrc_substring */
static inline char* __btrc_substring(const char* s, int start, int len) {
    if (!s) return __btrc_string_alloc(0);
    int slen = __btrc_string_length(s);
    if (start < 0) start = 0;
    if (start > slen) start = slen;
    if (len < 0) len = 0;
    if (len > slen - start) len = slen - start;
    char* result = __btrc_string_alloc(len);
    memcpy(result, s + start, (size_t)len);
    return result;
}
/* btrc-runtime-helper:end __btrc_substring */
/* btrc-runtime-helper:begin __btrc_trim */
static inline char* __btrc_trim(const char* s) {
    if (!s) return __btrc_string_alloc(0);
    int slen = __btrc_string_length(s);
    int start = 0;
    while (start < slen && __btrc_ascii_space(s[start])) start++;
    int end = slen;
    while (end > start && __btrc_ascii_space(s[end - 1])) end--;
    int length = end - start;
    char* result = __btrc_string_alloc(length);
    memcpy(result, s + start, (size_t)length);
    return result;
}
/* btrc-runtime-helper:end __btrc_trim */
/* btrc-runtime-helper:begin __btrc_toUpper */
static inline char* __btrc_toUpper(const char* s) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    char* result = __btrc_string_alloc(len);
    for (int i = 0; i < len; i++) result[i] = __btrc_ascii_upper(s[i]);
    return result;
}
/* btrc-runtime-helper:end __btrc_toUpper */
/* btrc-runtime-helper:begin __btrc_toLower */
static inline char* __btrc_toLower(const char* s) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    char* result = __btrc_string_alloc(len);
    for (int i = 0; i < len; i++) result[i] = __btrc_ascii_lower(s[i]);
    return result;
}
/* btrc-runtime-helper:end __btrc_toLower */
/* btrc-runtime-helper:begin __btrc_replace */
static inline char* __btrc_replace(const char* s, const char* old, const char* rep) {
    if (!s) return __btrc_string_alloc(0);
    if (!old || !old[0]) return __btrc_strdup(s);
    if (!rep) rep = "";
    int slen = __btrc_string_length(s);
    int oldlen = __btrc_string_length(old);
    int replen = __btrc_string_length(rep);
    int matches = 0;
    const char* scan = s;
    while ((scan = strstr(scan, old)) != NULL) { matches++; scan += oldlen; }
    long long total = (long long)slen
        + (long long)matches * ((long long)replen - (long long)oldlen);
    if (total < 0 || total > INT_MAX) {
        fprintf(stderr, "btrc: string replace overflow\n"); exit(1);
    }
    char* result = __btrc_string_alloc((int)total);
    const char* input = s;
    char* output = result;
    const char* found;
    while ((found = strstr(input, old)) != NULL) {
        size_t prefix = (size_t)(found - input);
        memcpy(output, input, prefix); output += prefix;
        memcpy(output, rep, (size_t)replen); output += replen;
        input = found + oldlen;
    }
    memcpy(output, input, strlen(input));
    return result;
}
/* btrc-runtime-helper:end __btrc_replace */
/* btrc-runtime-helper:begin __btrc_split */
static inline char** __btrc_split(const char* s, const char* delim) {
    if (!s || !delim) { char** r = (char**)__btrc_safe_realloc(NULL, sizeof(char*)); r[0] = NULL; return r; }
    int slen = __btrc_string_length(s);
    int dlen = __btrc_string_length(delim);
    if (dlen == 0) { fprintf(stderr, "Empty delimiter in split()\n"); exit(1); }
    int cap = 8;
    char** result = (char**)__btrc_safe_realloc(NULL, sizeof(char*) * (size_t)cap);
    int count = 0;
    const char* p = s;
    for (;;) {
        const char* found = strstr(p, delim);
        int offset = (int)(p - s);
        int seglen = found ? (int)(found - p) : slen - offset;
        if (count > INT_MAX - 2) { fprintf(stderr, "btrc: split result overflow\n"); exit(1); }
        if (count + 2 > cap) {
            if (cap > INT_MAX / 2
                    || (size_t)(cap * 2) > SIZE_MAX / sizeof(char*)) {
                fprintf(stderr, "btrc: split result overflow\n"); exit(1);
            }
            cap *= 2;
            result = (char**)__btrc_safe_realloc(
                result, sizeof(char*) * (size_t)cap);
        }
        result[count] = __btrc_string_alloc(seglen);
        memcpy(result[count], p, (size_t)seglen);
        count++;
        if (!found) break;
        p = found + dlen;
    }
    result[count] = NULL;
    return result;
}
/* btrc-runtime-helper:end __btrc_split */
/* btrc-runtime-helper:begin __btrc_repeat */
static inline char* __btrc_repeat(const char* s, int count) {
    if (!s) return __btrc_string_alloc(0);
    if (count <= 0) return __btrc_string_alloc(0);
    int slen = __btrc_string_length(s);
    if (slen == 0) return __btrc_string_alloc(0);
    if (slen > 0 && count > INT_MAX / slen) {
        fprintf(stderr, "btrc: string repeat overflow\n"); exit(1);
    }
    int total = slen * count;
    char* result = __btrc_string_alloc(total);
    for (int i = 0; i < count; i++)
        memcpy(result + (size_t)i * (size_t)slen, s, (size_t)slen);
    return result;
}
/* btrc-runtime-helper:end __btrc_repeat */
/* btrc-runtime-helper:begin __btrc_reverse */
static inline char* __btrc_reverse(const char* s) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    char* result = __btrc_string_alloc(len);
    for (int i = 0; i < len; i++) result[i] = s[len - 1 - i];
    return result;
}
/* btrc-runtime-helper:end __btrc_reverse */
/* btrc-runtime-helper:begin __btrc_removePrefix */
static inline char* __btrc_removePrefix(const char* s, const char* prefix) {
    if (!s) return __btrc_string_alloc(0);
    if (!prefix) return __btrc_strdup(s);
    int slen = __btrc_string_length(s);
    int plen = __btrc_string_length(prefix);
    if (plen <= slen && memcmp(s, prefix, (size_t)plen) == 0) {
        int length = slen - plen;
        char* result = __btrc_string_alloc(length);
        memcpy(result, s + plen, (size_t)length);
        return result;
    }
    return __btrc_strdup(s);
}
/* btrc-runtime-helper:end __btrc_removePrefix */
/* btrc-runtime-helper:begin __btrc_removeSuffix */
static inline char* __btrc_removeSuffix(const char* s, const char* suffix) {
    if (!s) return __btrc_string_alloc(0);
    if (!suffix) return __btrc_strdup(s);
    int slen = __btrc_string_length(s);
    int suflen = __btrc_string_length(suffix);
    if (suflen <= slen
            && memcmp(s + slen - suflen, suffix, (size_t)suflen) == 0) {
        int length = slen - suflen;
        char* result = __btrc_string_alloc(length);
        memcpy(result, s, (size_t)length);
        return result;
    }
    return __btrc_strdup(s);
}
/* btrc-runtime-helper:end __btrc_removeSuffix */
/* btrc-runtime-helper:begin __btrc_capitalize */
static inline char* __btrc_capitalize(const char* s) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    char* result = __btrc_string_alloc(len);
    for (int i = 0; i < len; i++) result[i] = __btrc_ascii_lower(s[i]);
    if (len > 0) result[0] = __btrc_ascii_upper(result[0]);
    return result;
}
/* btrc-runtime-helper:end __btrc_capitalize */
/* btrc-runtime-helper:begin __btrc_title */
static inline char* __btrc_title(const char* s) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    char* result = __btrc_string_alloc(len);
    int cap_next = 1;
    for (int i = 0; i < len; i++) {
        if (__btrc_ascii_space(s[i])) { result[i] = s[i]; cap_next = 1; }
        else if (cap_next) { result[i] = __btrc_ascii_upper(s[i]); cap_next = 0; }
        else { result[i] = __btrc_ascii_lower(s[i]); }
    }
    return result;
}
/* btrc-runtime-helper:end __btrc_title */
/* btrc-runtime-helper:begin __btrc_swapCase */
static inline char* __btrc_swapCase(const char* s) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    char* result = __btrc_string_alloc(len);
    for (int i = 0; i < len; i++) {
        unsigned char byte = (unsigned char)s[i];
        if (byte >= 'A' && byte <= 'Z') result[i] = __btrc_ascii_lower(s[i]);
        else if (byte >= 'a' && byte <= 'z') result[i] = __btrc_ascii_upper(s[i]);
        else result[i] = s[i];
    }
    return result;
}
/* btrc-runtime-helper:end __btrc_swapCase */
/* btrc-runtime-helper:begin __btrc_padLeft */
static inline char* __btrc_padLeft(const char* s, int width, char fill) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    int result_len = len >= width ? len : width;
    char* result = __btrc_string_alloc(result_len);
    int pad = result_len - len;
    memset(result, (unsigned char)fill, (size_t)pad);
    memcpy(result + pad, s, (size_t)len);
    return result;
}
/* btrc-runtime-helper:end __btrc_padLeft */
/* btrc-runtime-helper:begin __btrc_padRight */
static inline char* __btrc_padRight(const char* s, int width, char fill) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    int result_len = len >= width ? len : width;
    char* result = __btrc_string_alloc(result_len);
    memcpy(result, s, (size_t)len);
    memset(result + len, (unsigned char)fill, (size_t)(result_len - len));
    return result;
}
/* btrc-runtime-helper:end __btrc_padRight */
/* btrc-runtime-helper:begin __btrc_center */
static inline char* __btrc_center(const char* s, int width, char fill) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    int result_len = len >= width ? len : width;
    char* result = __btrc_string_alloc(result_len);
    int left = (result_len - len) / 2;
    int right = result_len - len - left;
    memset(result, (unsigned char)fill, (size_t)left);
    memcpy(result + left, s, (size_t)len);
    memset(result + left + len, (unsigned char)fill, (size_t)right);
    return result;
}
/* btrc-runtime-helper:end __btrc_center */
/* btrc-runtime-helper:begin __btrc_lstrip */
static inline char* __btrc_lstrip(const char* s) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    int start = 0;
    while (start < len && __btrc_ascii_space(s[start])) start++;
    int result_len = len - start;
    char* result = __btrc_string_alloc(result_len);
    memcpy(result, s + start, (size_t)result_len);
    return result;
}
/* btrc-runtime-helper:end __btrc_lstrip */
/* btrc-runtime-helper:begin __btrc_rstrip */
static inline char* __btrc_rstrip(const char* s) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    while (len > 0 && __btrc_ascii_space(s[len - 1])) len--;
    char* result = __btrc_string_alloc(len);
    memcpy(result, s, (size_t)len);
    return result;
}
/* btrc-runtime-helper:end __btrc_rstrip */
/* btrc-runtime-helper:begin __btrc_zfill */
static inline char* __btrc_zfill(const char* s, int width) {
    if (!s) return __btrc_string_alloc(0);
    int len = __btrc_string_length(s);
    int result_len = len >= width ? len : width;
    char* result = __btrc_string_alloc(result_len);
    int start = (len > 0 && (s[0] == '-' || s[0] == '+')) ? 1 : 0;
    int pad = result_len - len;
    if (start) result[0] = s[0];
    memset(result + start, '0', (size_t)pad);
    memcpy(result + start + pad, s + start, (size_t)(len - start));
    return result;
}
/* btrc-runtime-helper:end __btrc_zfill */
/* btrc-runtime-helper:begin __btrc_strcat */
static inline char* __btrc_strcat(const char* a, const char* b) {
    if (!a && !b) return __btrc_string_alloc(0);
    if (!a) return __btrc_strdup(b);
    if (!b) return __btrc_strdup(a);
    int left_len = __btrc_string_length(a);
    int right_len = __btrc_string_length(b);
    if (right_len > INT_MAX - left_len) {
        fprintf(stderr, "btrc: string concatenation overflow\n"); exit(1);
    }
    int total = left_len + right_len;
    char* result = __btrc_string_alloc(total);
    memcpy(result, a, (size_t)left_len);
    memcpy(result + left_len, b, (size_t)right_len);
    return result;
}
/* btrc-runtime-helper:end __btrc_strcat */
/* btrc-runtime-helper:begin __btrc_join */
static inline char* __btrc_join(char** items, int count, const char* sep) {
    if (count <= 0 || !items) return __btrc_string_alloc(0);
    if (!sep) sep = "";
    int separator_len = __btrc_string_length(sep);
    long long total = (long long)separator_len * (long long)(count - 1);
    if (total > INT_MAX) {
        fprintf(stderr, "btrc: string join overflow\n"); exit(1);
    }
    for (int i = 0; i < count; i++) {
        int item_len = __btrc_string_length(items[i]);
        if (item_len > INT_MAX - (int)total) {
            fprintf(stderr, "btrc: string join overflow\n"); exit(1);
        }
        total += item_len;
    }
    char* result = __btrc_string_alloc((int)total);
    int position = 0;
    for (int i = 0; i < count; i++) {
        if (i > 0) {
            memcpy(result + position, sep, (size_t)separator_len);
            position += separator_len;
        }
        const char* item = items[i] ? items[i] : "";
        int item_len = __btrc_string_length(item);
        memcpy(result + position, item, (size_t)item_len);
        position += item_len;
    }
    return result;
}
/* btrc-runtime-helper:end __btrc_join */
/* btrc-runtime-helper:begin __btrc_charAt */
static inline char __btrc_charAt(const char* s, int idx) {
    if (!s) { fprintf(stderr, "String index on NULL\n"); exit(1); }
    int len = __btrc_string_length(s);
    if (idx < 0 || idx >= len) { fprintf(stderr, "String index out of bounds: %d (length %d)\n", idx, len); exit(1); }
    return s[idx];
}
/* btrc-runtime-helper:end __btrc_charAt */
/* btrc-runtime-helper:begin __btrc_indexOf */
static inline int __btrc_indexOf(const char* s, const char* sub) {
    if (!s || !sub) return -1;
    (void)__btrc_string_length(s);
    (void)__btrc_string_length(sub);
    const char* found = strstr(s, sub);
    return found ? (int)(found - s) : -1;
}
/* btrc-runtime-helper:end __btrc_indexOf */
/* btrc-runtime-helper:begin __btrc_lastIndexOf */
static inline int __btrc_lastIndexOf(const char* s, const char* sub) {
    if (!s || !sub) return -1;
    int slen = __btrc_string_length(s);
    int sublen = __btrc_string_length(sub);
    if (sublen == 0) return slen;
    for (int i = slen - sublen; i >= 0; i--) {
        if (memcmp(s + i, sub, (size_t)sublen) == 0) return i;
    }
    return -1;
}
/* btrc-runtime-helper:end __btrc_lastIndexOf */
/* btrc-runtime-helper:begin __btrc_isEmpty */
static inline bool __btrc_isEmpty(const char* s) {
    return !s || s[0] == '\0';
}
/* btrc-runtime-helper:end __btrc_isEmpty */
/* btrc-runtime-helper:begin __btrc_startsWith */
static inline bool __btrc_startsWith(const char* s, const char* prefix) {
    if (!s || !prefix) return false;
    int slen = __btrc_string_length(s);
    int prefix_len = __btrc_string_length(prefix);
    return prefix_len <= slen
        && memcmp(s, prefix, (size_t)prefix_len) == 0;
}
/* btrc-runtime-helper:end __btrc_startsWith */
/* btrc-runtime-helper:begin __btrc_endsWith */
static inline bool __btrc_endsWith(const char* s, const char* suffix) {
    if (!s || !suffix) return false;
    int slen = __btrc_string_length(s);
    int suffix_len = __btrc_string_length(suffix);
    return suffix_len <= slen
        && memcmp(s + slen - suffix_len, suffix, (size_t)suffix_len) == 0;
}
/* btrc-runtime-helper:end __btrc_endsWith */
/* btrc-runtime-helper:begin __btrc_strContains */
static inline bool __btrc_strContains(const char* s, const char* sub) {
    if (!s || !sub) return false;
    (void)__btrc_string_length(s);
    (void)__btrc_string_length(sub);
    return strstr(s, sub) != NULL;
}
/* btrc-runtime-helper:end __btrc_strContains */
/* btrc-runtime-helper:begin __btrc_count */
static inline int __btrc_count(const char* s, const char* sub) {
    if (!s || !sub) return 0;
    (void)__btrc_string_length(s);
    int sublen = __btrc_string_length(sub);
    if (sublen == 0) return 0;
    int count = 0;
    const char* cursor = s;
    while ((cursor = strstr(cursor, sub)) != NULL) {
        count++; cursor += sublen;
    }
    return count;
}
/* btrc-runtime-helper:end __btrc_count */
/* btrc-runtime-helper:begin __btrc_find */
static inline int __btrc_find(const char* s, const char* sub, int start) {
    if (!s || !sub) return -1;
    int len = __btrc_string_length(s);
    int sublen = __btrc_string_length(sub);
    if (start < 0) start = 0;
    if (start > len) return -1;
    if (sublen == 0) return start;
    const char* found = strstr(s + start, sub);
    return found ? (int)(found - s) : -1;
}
/* btrc-runtime-helper:end __btrc_find */
/* btrc-runtime-helper:begin __btrc_isDigitStr */
static inline bool __btrc_isDigitStr(const char* s) {
    if (!s || !*s) return false;
    for (; *s; s++) if (*s < '0' || *s > '9') return false;
    return true;
}
/* btrc-runtime-helper:end __btrc_isDigitStr */
/* btrc-runtime-helper:begin __btrc_isAlphaStr */
static inline bool __btrc_isAlphaStr(const char* s) {
    if (!s || !*s) return false;
    for (; *s; s++) {
        unsigned char byte = (unsigned char)*s;
        if (!((byte >= 'A' && byte <= 'Z')
                || (byte >= 'a' && byte <= 'z'))) return false;
    }
    return true;
}
/* btrc-runtime-helper:end __btrc_isAlphaStr */
/* btrc-runtime-helper:begin __btrc_isBlank */
static inline bool __btrc_isBlank(const char* s) {
    if (!s) return true;
    for (; *s; s++) if (!__btrc_ascii_space(*s)) return false;
    return true;
}
/* btrc-runtime-helper:end __btrc_isBlank */
/* btrc-runtime-helper:begin __btrc_isUpper */
static inline bool __btrc_isUpper(const char* s) {
    if (!s || *s == '\0') return false;
    for (; *s; s++) {
        unsigned char byte = (unsigned char)*s;
        if (!(byte >= 'A' && byte <= 'Z') && !__btrc_ascii_space(*s))
            return false;
    }
    return true;
}
/* btrc-runtime-helper:end __btrc_isUpper */
/* btrc-runtime-helper:begin __btrc_isLower */
static inline bool __btrc_isLower(const char* s) {
    if (!s || *s == '\0') return false;
    for (; *s; s++) {
        unsigned char byte = (unsigned char)*s;
        if (!(byte >= 'a' && byte <= 'z') && !__btrc_ascii_space(*s))
            return false;
    }
    return true;
}
/* btrc-runtime-helper:end __btrc_isLower */
/* btrc-runtime-helper:begin __btrc_isAlnumStr */
static inline bool __btrc_isAlnumStr(const char* s) {
    if (!s || *s == '\0') return false;
    for (; *s; s++) {
        unsigned char byte = (unsigned char)*s;
        if (!((byte >= '0' && byte <= '9')
                || (byte >= 'A' && byte <= 'Z')
                || (byte >= 'a' && byte <= 'z'))) return false;
    }
    return true;
}
/* btrc-runtime-helper:end __btrc_isAlnumStr */
/* btrc-runtime-helper:begin __btrc_utf8_charlen */
static inline int __btrc_utf8_charlen(const char* s) {
    if (!s) return 0;
    int length = __btrc_string_length(s);
    int count = 0;
    int index = 0;
    while (index < length) {
        int remaining = length - index;
        unsigned char c0 = (unsigned char)s[index];
        unsigned char c1 = remaining > 1 ? (unsigned char)s[index + 1] : 0;
        unsigned char c2 = remaining > 2 ? (unsigned char)s[index + 2] : 0;
        unsigned char c3 = remaining > 3 ? (unsigned char)s[index + 3] : 0;
        int advance = 1;
        if (c0 >= 0xC2 && c0 <= 0xDF
                && c1 >= 0x80 && c1 <= 0xBF) advance = 2;
        else if (((c0 == 0xE0 && c1 >= 0xA0 && c1 <= 0xBF)
                    || (c0 >= 0xE1 && c0 <= 0xEC && c1 >= 0x80 && c1 <= 0xBF)
                    || (c0 == 0xED && c1 >= 0x80 && c1 <= 0x9F)
                    || (c0 >= 0xEE && c0 <= 0xEF && c1 >= 0x80 && c1 <= 0xBF))
                && c2 >= 0x80 && c2 <= 0xBF) advance = 3;
        else if (((c0 == 0xF0 && c1 >= 0x90 && c1 <= 0xBF)
                    || (c0 >= 0xF1 && c0 <= 0xF3 && c1 >= 0x80 && c1 <= 0xBF)
                    || (c0 == 0xF4 && c1 >= 0x80 && c1 <= 0x8F))
                && c2 >= 0x80 && c2 <= 0xBF
                && c3 >= 0x80 && c3 <= 0xBF) advance = 4;
        index += advance;
        count++;
    }
    return count;
}
/* btrc-runtime-helper:end __btrc_utf8_charlen */
/* btrc-runtime-helper:begin __btrc_charLen */
static inline int __btrc_charLen(const char* s) {
    return __btrc_utf8_charlen(s);
}
/* btrc-runtime-helper:end __btrc_charLen */
/* btrc-runtime-helper:begin __btrc_parseLong */
static inline long __btrc_parseLong(const char* s) {
    if (!s) return 0;
    while (*s == ' ' || *s == '\t' || *s == '\n'
            || *s == '\r' || *s == '\v' || *s == '\f') ++s;
    bool negative = false;
    if (*s == '-' || *s == '+') { negative = *s == '-'; ++s; }
    unsigned long limit = negative
        ? (unsigned long)LONG_MAX + 1UL : (unsigned long)LONG_MAX;
    unsigned long value = 0UL;
    bool any = false;
    while (*s >= '0' && *s <= '9') {
        unsigned long digit = (unsigned long)(*s - '0');
        any = true;
        if (value > (limit - digit) / 10UL)
            return negative ? LONG_MIN : LONG_MAX;
        value = value * 10UL + digit;
        ++s;
    }
    if (!any) return 0L;
    if (!negative) return (long)value;
    if (value == (unsigned long)LONG_MAX + 1UL) return LONG_MIN;
    return -(long)value;
}
/* btrc-runtime-helper:end __btrc_parseLong */
/* btrc-runtime-helper:begin __btrc_parseInt */
static inline int __btrc_parseInt(const char* s) {
    long value = __btrc_parseLong(s);
    if (value > INT_MAX) return INT_MAX;
    if (value < INT_MIN) return INT_MIN;
    return (int)value;
}
/* btrc-runtime-helper:end __btrc_parseInt */
/* btrc-runtime-helper:begin __btrc_parseBool */
static inline bool __btrc_parseBool(const char* s) {
    return s && *s != '\0' && strcmp(s, "false") != 0
        && strcmp(s, "0") != 0;
}
/* btrc-runtime-helper:end __btrc_parseBool */
/* btrc-runtime-helper:begin __btrc_intToString */
static inline char* __btrc_intToString(int n) {
    char* buf = __btrc_string_alloc(31);
    snprintf(buf, 32, "%d", n);
    return buf;
}
/* btrc-runtime-helper:end __btrc_intToString */
/* btrc-runtime-helper:begin __btrc_longToString */
static inline char* __btrc_longToString(long n) {
    char* buf = __btrc_string_alloc(31);
    snprintf(buf, 32, "%ld", n);
    return buf;
}
/* btrc-runtime-helper:end __btrc_longToString */
/* btrc-runtime-helper:begin __btrc_longLongToString */
static inline char* __btrc_longLongToString(long long n) {
    char* buf = __btrc_string_alloc(31);
    snprintf(buf, 32, "%lld", n);
    return buf;
}
/* btrc-runtime-helper:end __btrc_longLongToString */
/* btrc-runtime-helper:begin __btrc_uintToString */
static inline char* __btrc_uintToString(unsigned int n) {
    char* buf = __btrc_string_alloc(31);
    snprintf(buf, 32, "%u", n);
    return buf;
}
/* btrc-runtime-helper:end __btrc_uintToString */
/* btrc-runtime-helper:begin __btrc_ulongToString */
static inline char* __btrc_ulongToString(unsigned long n) {
    char* buf = __btrc_string_alloc(31);
    snprintf(buf, 32, "%lu", n);
    return buf;
}
/* btrc-runtime-helper:end __btrc_ulongToString */
/* btrc-runtime-helper:begin __btrc_ulongLongToString */
static inline char* __btrc_ulongLongToString(unsigned long long n) {
    char* buf = __btrc_string_alloc(31);
    snprintf(buf, 32, "%llu", n);
    return buf;
}
/* btrc-runtime-helper:end __btrc_ulongLongToString */
/* btrc-runtime-helper:begin __btrc_floatToString */
static inline char* __btrc_floatToString(float f) {
    char* buf = __btrc_string_alloc(63);
    snprintf(buf, 64, "%g", (double)f);
    return buf;
}
/* btrc-runtime-helper:end __btrc_floatToString */
/* btrc-runtime-helper:begin __btrc_doubleToString */
static inline char* __btrc_doubleToString(double d) {
    char* buf = __btrc_string_alloc(63);
    snprintf(buf, 64, "%g", d);
    return buf;
}
/* btrc-runtime-helper:end __btrc_doubleToString */
/* btrc-runtime-helper:begin __btrc_longDoubleToString */
static inline char* __btrc_longDoubleToString(long double d) {
    char* buf = __btrc_string_alloc(63);
    snprintf(buf, 64, "%Lg", d);
    return buf;
}
/* btrc-runtime-helper:end __btrc_longDoubleToString */
/* btrc-runtime-helper:begin __btrc_charToString */
static inline char* __btrc_charToString(char c) {
    char* buf = __btrc_string_alloc(1);
    buf[0] = c; buf[1] = '\0';
    return buf;
}
/* btrc-runtime-helper:end __btrc_charToString */
/* btrc-runtime-helper:begin __btrc_fromInt */
static inline char* __btrc_fromInt(int n) {
    char* r = __btrc_string_alloc(20);
    snprintf(r, 21, "%d", n);
    return r;
}
/* btrc-runtime-helper:end __btrc_fromInt */
/* btrc-runtime-helper:begin __btrc_fromFloat */
static inline char* __btrc_fromFloat(float f) {
    char* r = __btrc_string_alloc(31);
    snprintf(r, 32, "%g", (double)f);
    return r;
}
/* btrc-runtime-helper:end __btrc_fromFloat */
