/*
 * btrc List<T> — dynamic array
 * Monomorphized via BTRC_DEFINE_LIST(T, NAME) macro.
 *
 * The codegen emits inline struct + function definitions directly,
 * so this header is provided for reference and manual use.
 */
#ifndef BTRC_LIST_H
#define BTRC_LIST_H

#include <stdlib.h>

#define BTRC_DEFINE_LIST(T, NAME)                                              \
typedef struct {                                                               \
    T* data;                                                                   \
    int len;                                                                   \
    int cap;                                                                   \
} btrc_List_##NAME;                                                            \
                                                                               \
static inline btrc_List_##NAME btrc_List_##NAME##_new() {                      \
    return (btrc_List_##NAME){NULL, 0, 0};                                     \
}                                                                              \
                                                                               \
static inline void btrc_List_##NAME##_push(btrc_List_##NAME* l, T val) {       \
    if (l->len >= l->cap) {                                                    \
        l->cap = l->cap ? l->cap * 2 : 4;                                     \
        l->data = (T*)realloc(l->data, sizeof(T) * l->cap);                   \
    }                                                                          \
    l->data[l->len++] = val;                                                   \
}                                                                              \
                                                                               \
static inline T btrc_List_##NAME##_get(btrc_List_##NAME* l, int i) {           \
    return l->data[i];                                                         \
}                                                                              \
                                                                               \
static inline void btrc_List_##NAME##_set(btrc_List_##NAME* l, int i, T v) {   \
    l->data[i] = v;                                                            \
}                                                                              \
                                                                               \
static inline int btrc_List_##NAME##_len(btrc_List_##NAME* l) {                \
    return l->len;                                                             \
}                                                                              \
                                                                               \
static inline void btrc_List_##NAME##_free(btrc_List_##NAME* l) {              \
    free(l->data);                                                             \
    l->data = NULL; l->len = 0; l->cap = 0;                                   \
}

#endif /* BTRC_LIST_H */
