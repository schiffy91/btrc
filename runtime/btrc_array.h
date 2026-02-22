/*
 * btrc Array<T> — fat pointer (data + length)
 */
#ifndef BTRC_ARRAY_H
#define BTRC_ARRAY_H

#define BTRC_DEFINE_ARRAY(T, NAME)                                             \
typedef struct {                                                               \
    T* data;                                                                   \
    int len;                                                                   \
} btrc_Array_##NAME;

#endif /* BTRC_ARRAY_H */
