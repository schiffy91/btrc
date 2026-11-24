#ifndef BTRC_ANDROID_SHIM_PRIVATE_H
#define BTRC_ANDROID_SHIM_PRIVATE_H
/* What the Android shim's source files share. Nothing here is the
 * provider's: BTRC sees only ../Shim/Shim.h, ShimControls.h and ShimWeb.h. */
#include "../Shim/ShimControls.h"

#include <jni.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

struct BtrcShimWindow {
	BtrcShimWindow* next;
	/* The Java side's name for the window, which is also the events'. */
	unsigned int id;
	char* title;
	/* The size the program asked for, which is the window's until it is first
	 * shown: from then on it has the session's. */
	int askedWidth;
	int askedHeight;
	bool sized;
	bool textInput;
	/* The placement in progress: a handle (zero for a hole) and eight numbers each. */
	jint* handles;
	jfloat* rectangles;
	int placed;
	int capacity;
	/* The surface's native window, held from when a WebGPU surface is made on it. */
	void* native;
};

struct BtrcShimControl {
	void* extension;
	void (*release)(void* extension);
	/* The Java side's name for the control, and the id its events carry. */
	int handle;
	unsigned int id;
	int kind;
	/* A level's thresholds. */
	double warning;
	double critical;
	/* A button's symbol, seven numbers a shape, until the view takes it. */
	double symbolSize;
	jdouble* shapes;
	int shapeCount;
	bool shapesChanged;
	/* A select's items, until the view takes them. */
	char** items;
	bool* itemEnabled;
	int itemCount;
	bool itemsChanged;
};

void btrcAndroidFail(const char* message);
/* This thread's JNI environment (the thread is attached if it was not), the
 * Shim class, one of its static methods, and a Java string of UTF-8 text. */
JNIEnv* btrcAndroidEnv(void);
jclass btrcAndroidShimClass(void);
jmethodID btrcAndroidMethod(JNIEnv* env, jclass class, const char* name, const char* signature);
jstring btrcAndroidString(JNIEnv* env, const char* text);
/* True, with the exception described and cleared, when the last call threw. */
bool btrcAndroidFailed(JNIEnv* env);

/* The queue (AndroidShim.c). Push is what Shim.push does with what happened;
 * the other three are for tests that watch the queue being drained. */
bool btrcAndroidPush(const BtrcShimEvent* event, const char* text);
int btrcAndroidQueued(unsigned int firstType, unsigned int lastType);
void btrcAndroidQueueFlush(void);
void btrcAndroidQueueFilter(bool (*accept)(const BtrcShimEvent* event));

/* For a kind of control that has a source file of its own (AndroidWeb.c). */
BtrcShimControl* btrcAndroidControlNew(int kind, unsigned int id, const char* text, const char* more, bool flag);
int btrcAndroidControlHandle(BtrcShimControl* control);
/* Let go of the native window a WebGPU surface was made on (AndroidSurface.c). */
void btrcAndroidReleaseNativeWindow(BtrcShimWindow* window);
#endif
