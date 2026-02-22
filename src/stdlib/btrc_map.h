/*
 * btrc Map<K,V> — open-addressing hash map
 * Monomorphized via BTRC_DEFINE_MAP macro.
 *
 * The codegen emits inline definitions directly,
 * so this header is provided for reference and manual use.
 */
#ifndef BTRC_MAP_H
#define BTRC_MAP_H

#include <stdlib.h>
#include <stdbool.h>
#include <string.h>

/* String hash function */
static inline unsigned int __btrc_hash_str(const char* s) {
    unsigned int h = 5381;
    while (*s) h = h * 33 + (unsigned char)*s++;
    return h;
}

#define BTRC_DEFINE_MAP(K, V, KNAME, VNAME, HASH_FN, EQ_FN)                   \
typedef struct {                                                               \
    K key; V value; bool occupied;                                             \
} btrc_Map_##KNAME##_##VNAME##_entry;                                          \
                                                                               \
typedef struct {                                                               \
    btrc_Map_##KNAME##_##VNAME##_entry* buckets;                               \
    int cap;                                                                   \
    int len;                                                                   \
} btrc_Map_##KNAME##_##VNAME;                                                  \
                                                                               \
static inline btrc_Map_##KNAME##_##VNAME                                       \
btrc_Map_##KNAME##_##VNAME##_new() {                                           \
    btrc_Map_##KNAME##_##VNAME m;                                              \
    m.cap = 16;                                                                \
    m.len = 0;                                                                 \
    m.buckets = (btrc_Map_##KNAME##_##VNAME##_entry*)calloc(                   \
        m.cap, sizeof(btrc_Map_##KNAME##_##VNAME##_entry));                    \
    return m;                                                                  \
}                                                                              \
                                                                               \
static inline void btrc_Map_##KNAME##_##VNAME##_put(                           \
    btrc_Map_##KNAME##_##VNAME* m, K key, V value) {                           \
    unsigned int idx = HASH_FN(key) % m->cap;                                  \
    while (m->buckets[idx].occupied) {                                         \
        if (EQ_FN(m->buckets[idx].key, key)) {                                \
            m->buckets[idx].value = value; return;                             \
        }                                                                      \
        idx = (idx + 1) % m->cap;                                             \
    }                                                                          \
    m->buckets[idx].key = key;                                                 \
    m->buckets[idx].value = value;                                             \
    m->buckets[idx].occupied = true;                                           \
    m->len++;                                                                  \
}                                                                              \
                                                                               \
static inline V btrc_Map_##KNAME##_##VNAME##_get(                              \
    btrc_Map_##KNAME##_##VNAME* m, K key) {                                    \
    unsigned int idx = HASH_FN(key) % m->cap;                                  \
    while (m->buckets[idx].occupied) {                                         \
        if (EQ_FN(m->buckets[idx].key, key))                                   \
            return m->buckets[idx].value;                                      \
        idx = (idx + 1) % m->cap;                                             \
    }                                                                          \
    V zero = {0}; return zero;                                                 \
}                                                                              \
                                                                               \
static inline void btrc_Map_##KNAME##_##VNAME##_free(                          \
    btrc_Map_##KNAME##_##VNAME* m) {                                           \
    free(m->buckets);                                                          \
    m->buckets = NULL; m->cap = 0; m->len = 0;                                \
}

#endif /* BTRC_MAP_H */
