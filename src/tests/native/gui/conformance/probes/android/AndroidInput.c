/* Real input on Android: events injected through the system into this
 * program's own windows (java/dev/btrc/probe/Input.java), which is as far as
 * the system lets a program reach. The probe's positions are in points, as
 * a window's are; the system's are in pixels. */
#include "../shim/RealInput.h"
#include "../ConformanceProbe.h"

#include <jni.h>
#include <stdlib.h>
#include <string.h>

/* The provider's own way to its Java side (GUI/Android/AndroidShimPrivate.h). */
JNIEnv *btrcAndroidEnv(void);
jclass btrcAndroidShimClass(void);

enum { POINTER_MOVE = 0, POINTER_PRESS = 1, POINTER_RELEASE = 2, POINTER_WHEEL = 3 };
/* android.view.KeyEvent's key codes. */
enum { CODE_DPAD_UP = 19, CODE_DPAD_DOWN = 20, CODE_DPAD_LEFT = 21, CODE_DPAD_RIGHT = 22, CODE_A = 29, CODE_TAB = 61, CODE_ENTER = 66, CODE_DEL = 67, CODE_ESCAPE = 111 };

static struct { jclass input; jmethodID pointer, key, text; double density, x, y; } android;

static jmethodID shimMethod(JNIEnv *env, const char *name, const char *signature) {
    jmethodID method = (*env)->GetStaticMethodID(env, btrcAndroidShimClass(), name, signature);
    if (!method) { (*env)->ExceptionClear(env); }
    return method;
}

static bool refused(JNIEnv *env) {
    if (!(*env)->ExceptionCheck(env)) { return false; }
    (*env)->ExceptionDescribe(env);
    (*env)->ExceptionClear(env);
    return true;
}

static bool send(int kind, double deltaX, double deltaY) {
    JNIEnv *env = btrcAndroidEnv();
    jboolean sent = (*env)->CallStaticBooleanMethod(env, android.input, android.pointer, (jint)kind, (jfloat)(android.x * android.density), (jfloat)(android.y * android.density), (jfloat)deltaX, (jfloat)deltaY);
    return !refused(env) && sent;
}

static bool androidMove(double x, double y) {
    android.x = x;
    android.y = y;
    return send(POINTER_MOVE, 0.0, 0.0);
}

static bool androidButton(bool down) { return send(down ? POINTER_PRESS : POINTER_RELEASE, 0.0, 0.0); }

static bool androidWheel(double deltaX, double deltaY) { return send(POINTER_WHEEL, deltaX, deltaY); }

static bool tap(int code, bool control) {
    JNIEnv *env = btrcAndroidEnv();
    jboolean sent = (*env)->CallStaticBooleanMethod(env, android.input, android.key, (jint)code, (jboolean)control);
    return !refused(env) && sent;
}

static bool androidKey(int key) {
    switch (key) {
    case CONFORMANCE_KEY_RETURN: return tap(CODE_ENTER, false);
    case CONFORMANCE_KEY_ESCAPE: return tap(CODE_ESCAPE, false);
    case CONFORMANCE_KEY_TAB: return tap(CODE_TAB, false);
    case CONFORMANCE_KEY_LEFT: return tap(CODE_DPAD_LEFT, false);
    case CONFORMANCE_KEY_RIGHT: return tap(CODE_DPAD_RIGHT, false);
    case CONFORMANCE_KEY_UP: return tap(CODE_DPAD_UP, false);
    case CONFORMANCE_KEY_DOWN: return tap(CODE_DPAD_DOWN, false);
    case CONFORMANCE_KEY_BACKSPACE: return tap(CODE_DEL, false);
    case CONFORMANCE_KEY_SELECT_ALL: return tap(CODE_A, true);
    default: return false;
    }
}

/* One character at a time, each as the keys the system's keyboard map has for it. */
static bool androidText(const char *text, void (*typed)(void)) {
    JNIEnv *env = btrcAndroidEnv();
    for (const char *at = text; *at; ) {
        char one[5] = {0};
        int length = (*at & 0x80) == 0 ? 1 : (*at & 0xE0) == 0xC0 ? 2 : (*at & 0xF0) == 0xE0 ? 3 : 4;
        for (int index = 0; index < length && at[index]; index++) { one[index] = at[index]; }
        at += strlen(one);
        jstring character = (*env)->NewStringUTF(env, one);
        jboolean sent = (*env)->CallStaticBooleanMethod(env, android.input, android.text, character);
        (*env)->DeleteLocalRef(env, character);
        if (refused(env) || !sent) { return false; }
        typed();
    }
    return true;
}

unsigned int btrcShimWindowNamed(const char *title);

/* {x, y} of the titled window's content on the screen, in pixels, when it is the one on show. */
static bool androidOrigin(const char *title, double *x, double *y) {
    static jmethodID method;
    JNIEnv *env = btrcAndroidEnv();
    unsigned int window = btrcShimWindowNamed(title);
    if (!method) { method = shimMethod(env, "windowOrigin", "(I)[I"); }
    if (!window || !method) { return false; }
    jintArray origin = (*env)->CallStaticObjectMethod(env, btrcAndroidShimClass(), method, (jint)window);
    if (refused(env) || !origin) { return false; }
    jint values[2] = {0, 0};
    (*env)->GetIntArrayRegion(env, origin, 0, 2, values);
    (*env)->DeleteLocalRef(env, origin);
    *x = values[0] / android.density;
    *y = values[1] / android.density;
    return true;
}

/* The window on show has the screen and the keyboard: there is nothing to raise. */
static bool androidActivate(const char *title) {
    double x = 0.0;
    double y = 0.0;
    return androidOrigin(title, &x, &y);
}

/* The system's close request is Back. */
static bool androidClose(const char *title) {
    enum { CODE_BACK = 4 };
    return androidActivate(title) && tap(CODE_BACK, false);
}

/* The frame the windows share stands for the screen. */
static void androidExtent(double *width, double *height) {
    static jmethodID method;
    JNIEnv *env = btrcAndroidEnv();
    jint values[2] = {0, 0};
    if (!method) { method = shimMethod(env, "windowPixelSize", "(I)[I"); }
    jintArray size = method ? (*env)->CallStaticObjectMethod(env, btrcAndroidShimClass(), method, (jint)0) : NULL;
    if (!refused(env) && size) { (*env)->GetIntArrayRegion(env, size, 0, 2, values); (*env)->DeleteLocalRef(env, size); }
    *width = values[0] / android.density;
    *height = values[1] / android.density;
}

/* Every window has the whole screen, at first and always. */
static bool androidFillsScreen(void) { return true; }

static const RealInput androidInput = {
    .move = androidMove, .button = androidButton, .wheel = androidWheel, .key = androidKey, .text = androidText,
    .activate = androidActivate, .close = androidClose, .origin = androidOrigin, .extent = androidExtent,
    .fillsScreen = androidFillsScreen, .keepsScreen = androidFillsScreen,
};

const RealInput *realInputAndroid(void) {
    JNIEnv *env = btrcAndroidEnv();
    if (android.input) { return &androidInput; }
    if (!env || !btrcAndroidShimClass()) { return NULL; }
    jclass found = (*env)->FindClass(env, "dev/btrc/probe/Input");
    if (refused(env) || !found) { return NULL; }
    jmethodID density = shimMethod(env, "windowDensity", "()F");
    android.pointer = (*env)->GetStaticMethodID(env, found, "pointer", "(IFFFF)Z");
    android.key = (*env)->GetStaticMethodID(env, found, "key", "(IZ)Z");
    android.text = (*env)->GetStaticMethodID(env, found, "text", "(Ljava/lang/String;)Z");
    if (refused(env) || !density || !android.pointer || !android.key || !android.text) { return NULL; }
    android.density = (*env)->CallStaticFloatMethod(env, btrcAndroidShimClass(), density);
    if (refused(env) || android.density <= 0.0) { return NULL; }
    android.input = (*env)->NewGlobalRef(env, found);
    return &androidInput;
}
