#ifndef BTRC_ANDROID_JSSE_NAME_H
#define BTRC_ANDROID_JSSE_NAME_H
#include <jni.h>
#include <stdint.h>
/* OpenSSL CApath's subject index, computed using public Java APIs. */
int btrcJSSESubjectIndex(JNIEnv *env, jobject certificate, uint32_t *hash);
#endif
