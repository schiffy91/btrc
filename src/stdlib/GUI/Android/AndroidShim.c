/* The Android side of the shim provider; ../Shim/Shim.h and ShimControls.h
 * are the contract.
 *
 * The views are Android's, made and owned by dev.btrc.shim.Shim on the
 * activity's UI thread (Java, package dev.btrc.shim). The program runs on a thread
 * of its own: each function here calls one static method of that class and
 * returns when the UI thread has done the work. What a person does comes
 * back as events the Java side pushes onto the queue below, which the
 * program polls; no callback enters BTRC. */
#include "AndroidShimPrivate.h"

#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

/* The values Shim.java pushes are this header's. */
_Static_assert(BTRC_SHIM_EVENT_WINDOW_SHOWN == 3 && BTRC_SHIM_EVENT_WINDOW_RESIZED == 6 && BTRC_SHIM_EVENT_WINDOW_PIXEL_SIZE_CHANGED == 7, "Shim.java's window events");
_Static_assert(BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER == 11 && BTRC_SHIM_EVENT_WINDOW_FOCUS_GAINED == 13 && BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED == 15, "Shim.java's window events");
_Static_assert(BTRC_SHIM_EVENT_KEY_DOWN == 16 && BTRC_SHIM_EVENT_TEXT_INPUT == 19 && BTRC_SHIM_EVENT_MOUSE_MOTION == 20 && BTRC_SHIM_EVENT_MOUSE_WHEEL == 23, "Shim.java's input events");
_Static_assert(BTRC_SHIM_EVENT_CONTROL_ACTIVATED == 24 && BTRC_SHIM_EVENT_CONTROL_SLIDER_PRESSED == 27 && BTRC_SHIM_EVENT_CONTROL_SELECT_OPENED == 31, "Shim.java's control events");
_Static_assert(BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED == 35 && BTRC_SHIM_EVENT_CONTROL_SCROLLBAR_CHANGED == 38 && BTRC_SHIM_EVENT_CONTROL_WEB_NAVIGATION == 40, "Shim.java's control events");
_Static_assert(BTRC_SHIM_KEY_ESCAPE == 1 && BTRC_SHIM_KEY_RETURN == 2 && BTRC_SHIM_KEY_SPACE == 4 && BTRC_SHIM_KEY_TAB == 9 && BTRC_SHIM_KEY_END == 13 && BTRC_SHIM_KEY_V == 20, "Shim.java's keys");
_Static_assert(BTRC_SHIM_MOD_SHIFT == 1 && BTRC_SHIM_MOD_CTRL == 2 && BTRC_SHIM_MOD_ALT == 4, "Shim.java's modifiers");

enum { BTRC_ANDROID_QUEUE = 16384 };

struct BtrcShimFolderDialog {
	int state;
};

struct BtrcShimFileDialog {
	int id;
	char** paths;
	int pathCount;
	bool pathsLoaded;
};

static struct {
	BtrcShimEvent events[BTRC_ANDROID_QUEUE];
	char* texts[BTRC_ANDROID_QUEUE];
	unsigned int head;
	unsigned int count;
	pthread_mutex_t lock;
	pthread_cond_t arrived;
	bool (*accept)(const BtrcShimEvent* event);
	char* handed;
	unsigned long serial;
} btrcAndroidQueue = {.lock = PTHREAD_MUTEX_INITIALIZER, .arrived = PTHREAD_COND_INITIALIZER};

static JavaVM* btrcAndroidMachine;
static jclass btrcAndroidShim;
static pthread_t btrcAndroidThread;
static bool btrcAndroidStarted;
static BtrcShimWindow* btrcAndroidWindows;
static char btrcAndroidFailure[160];

void btrcAndroidFail(const char* message) { snprintf(btrcAndroidFailure, sizeof btrcAndroidFailure, "%s", message); }

const char* btrcShimError(void) { return btrcAndroidFailure; }

JNIEnv* btrcAndroidEnv(void) {
	JNIEnv* env = NULL;
	if (btrcAndroidMachine == NULL) { return NULL; }
	if ((*btrcAndroidMachine)->GetEnv(btrcAndroidMachine, (void**)&env, JNI_VERSION_1_6) == JNI_OK) { return env; }
	/* The program's thread stays attached for its life. */
	return (*btrcAndroidMachine)->AttachCurrentThread(btrcAndroidMachine, &env, NULL) == JNI_OK ? env : NULL;
}

jclass btrcAndroidShimClass(void) { return btrcAndroidShim; }

/* A static method of Shim, looked up once per call site. A missing one is a
 * build that does not match its Java: nothing can be done but say so. */
jmethodID btrcAndroidMethod(JNIEnv* env, jclass class, const char* name, const char* signature) {
	jmethodID method = (*env)->GetStaticMethodID(env, class, name, signature);
	if (method == NULL) {
		(*env)->ExceptionClear(env);
		fprintf(stderr, "btrc: dev.btrc.shim has no %s%s\n", name, signature);
		abort();
	}
	return method;
}

jstring btrcAndroidString(JNIEnv* env, const char* text) { return (*env)->NewStringUTF(env, text == NULL ? "" : text); }

/* A Java exception in a shim call is a defect of the shim: report it and
 * carry on with the call's zero result. */
bool btrcAndroidFailed(JNIEnv* env) {
	if (!(*env)->ExceptionCheck(env)) { return false; }
	(*env)->ExceptionDescribe(env);
	(*env)->ExceptionClear(env);
	return true;
}

/* When linked, Library.Java owns the application VM for non-UI providers. */
extern int btrcJavaAdopt(JavaVM*) __attribute__((weak));

jint JNI_OnLoad(JavaVM* machine, void* reserved) {
	(void)reserved;
	JNIEnv* env = NULL;
	btrcAndroidMachine = machine;
	if (btrcJavaAdopt && btrcJavaAdopt(machine) != JNI_OK) { return JNI_ERR; }
	if ((*machine)->GetEnv(machine, (void**)&env, JNI_VERSION_1_6) != JNI_OK) { return JNI_ERR; }
	/* The application's own classes are found from this thread, which loaded the library. */
	jclass shim = (*env)->FindClass(env, "dev/btrc/shim/Shim");
	if (shim == NULL) { (*env)->ExceptionClear(env); return JNI_VERSION_1_6; }
	btrcAndroidShim = (*env)->NewGlobalRef(env, shim);
	return JNI_VERSION_1_6;
}

bool btrcAndroidPush(const BtrcShimEvent* event, const char* text) {
	bool queued = false;
	pthread_mutex_lock(&btrcAndroidQueue.lock);
	bool (*accept)(const BtrcShimEvent*) = btrcAndroidQueue.accept;
	if ((accept == NULL || accept(event)) && btrcAndroidQueue.count < BTRC_ANDROID_QUEUE) {
		unsigned int slot = (btrcAndroidQueue.head + btrcAndroidQueue.count) % BTRC_ANDROID_QUEUE;
		btrcAndroidQueue.events[slot] = *event;
		btrcAndroidQueue.events[slot].text = NULL;
		btrcAndroidQueue.texts[slot] = text == NULL ? NULL : strdup(text);
		btrcAndroidQueue.count++;
		queued = true;
	}
	btrcAndroidQueue.serial++;
	pthread_cond_broadcast(&btrcAndroidQueue.arrived);
	pthread_mutex_unlock(&btrcAndroidQueue.lock);
	return queued;
}

int btrcAndroidQueued(unsigned int firstType, unsigned int lastType) {
	int found = 0;
	pthread_mutex_lock(&btrcAndroidQueue.lock);
	for (unsigned int index = 0; index < btrcAndroidQueue.count; index++) {
		unsigned int type = btrcAndroidQueue.events[(btrcAndroidQueue.head + index) % BTRC_ANDROID_QUEUE].type;
		if (type >= firstType && type <= lastType) { found++; }
	}
	pthread_mutex_unlock(&btrcAndroidQueue.lock);
	return found;
}

void btrcAndroidQueueFlush(void) {
	pthread_mutex_lock(&btrcAndroidQueue.lock);
	for (unsigned int index = 0; index < btrcAndroidQueue.count; index++) {
		unsigned int slot = (btrcAndroidQueue.head + index) % BTRC_ANDROID_QUEUE;
		free(btrcAndroidQueue.texts[slot]);
		btrcAndroidQueue.texts[slot] = NULL;
	}
	btrcAndroidQueue.head = 0u;
	btrcAndroidQueue.count = 0u;
	pthread_mutex_unlock(&btrcAndroidQueue.lock);
}

void btrcAndroidQueueFilter(bool (*accept)(const BtrcShimEvent* event)) {
	pthread_mutex_lock(&btrcAndroidQueue.lock);
	btrcAndroidQueue.accept = accept;
	pthread_mutex_unlock(&btrcAndroidQueue.lock);
}

/* Shim.push: what a person did, from the UI thread or the web engine's. */
JNIEXPORT void JNICALL Java_dev_btrc_shim_Shim_push(JNIEnv* env, jclass class, jint type, jint window, jint control, jfloat x, jfloat y, jfloat wheelX, jfloat wheelY, jint button, jint clicks, jint scancode, jint key, jint modifiers, jint data1, jint data2, jint down, jdouble value, jstring text) {
	(void)class;
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = (unsigned int)type;
	event.window = (unsigned int)window;
	event.control = (unsigned int)control;
	event.x = x;
	event.y = y;
	event.wheelX = wheelX;
	event.wheelY = wheelY;
	event.button = (unsigned int)button;
	event.clicks = (unsigned int)clicks;
	event.scancode = (unsigned int)scancode;
	event.key = (unsigned int)key;
	event.modifiers = (unsigned int)modifiers;
	event.data1 = data1;
	event.data2 = data2;
	event.down = down;
	if (type == BTRC_SHIM_EVENT_KEY_DOWN || type == BTRC_SHIM_EVENT_KEY_UP) {
		if (data1 > 0) { event.physicalSet = BTRC_SHIM_PHYSICAL_EVDEV; event.physicalCode = (unsigned int)data1; }
		event.repeat = down && data2 > 0;
	}
	event.value = value;
	const char* characters = text == NULL ? NULL : (*env)->GetStringUTFChars(env, text, NULL);
	btrcAndroidPush(&event, characters);
	if (characters != NULL) { (*env)->ReleaseStringUTFChars(env, text, characters); }
}

/* Points one of the program's standard streams at a file, in one step. The
 * activity's other threads open descriptors of their own meanwhile, and
 * freopen closes the stream's descriptor before it takes the number again:
 * a render thread's descriptor could be given that number in between, and
 * the program's output was lost when that thread closed it. */
static bool btrcAndroidRedirect(FILE* stream, int descriptor, const char* path) {
	int file = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0666);
	if (file < 0) { return false; }
	fflush(stream);
	bool moved = dup2(file, descriptor) == descriptor;
	close(file);
	return moved;
}

/* The program's main, on the thread the activity made for it. Its standard
 * output and error go to files in the application's own directory, where a
 * test host reads them, with its result beside them when it ends. */
extern int main(int count, char** arguments);

JNIEXPORT jint JNICALL Java_dev_btrc_shim_ShimActivity_nativeMain(JNIEnv* env, jclass class, jstring directory, jobjectArray arguments) {
	(void)class;
	const char* home = (*env)->GetStringUTFChars(env, directory, NULL);
	char path[1024];
	if (chdir(home) != 0) { return 127; }
	setenv("HOME", home, 1);
	setenv("TMPDIR", home, 0);
	snprintf(path, sizeof path, "%s/stdout.txt", home);
	if (!btrcAndroidRedirect(stdout, STDOUT_FILENO, path)) { return 127; }
	snprintf(path, sizeof path, "%s/stderr.txt", home);
	if (!btrcAndroidRedirect(stderr, STDERR_FILENO, path)) { return 127; }
	/* Arguments of the form NAME=VALUE before a "--" are the environment. */
	jsize given = (*env)->GetArrayLength(env, arguments);
	char** values = calloc((size_t)given + 2u, sizeof *values);
	int count = 0;
	bool environment = true;
	values[count++] = strdup("program");
	for (jsize index = 0; index < given; index++) {
		jstring item = (*env)->GetObjectArrayElement(env, arguments, index);
		const char* text = (*env)->GetStringUTFChars(env, item, NULL);
		const char* equals = strchr(text, '=');
		if (environment && strcmp(text, "--") == 0) { environment = false; }
		else if (environment && equals != NULL) {
			char* name = strndup(text, (size_t)(equals - text));
			setenv(name, equals + 1, 1);
			free(name);
		} else { environment = false; values[count++] = strdup(text); }
		(*env)->ReleaseStringUTFChars(env, item, text);
		(*env)->DeleteLocalRef(env, item);
	}
	int result = main(count, values);
	fflush(stdout);
	fflush(stderr);
	snprintf(path, sizeof path, "%s/exit.txt", home);
	FILE* status = fopen(path, "w");
	if (status != NULL) { fprintf(status, "%d\n", result); fclose(status); }
	(*env)->ReleaseStringUTFChars(env, directory, home);
	return result;
}

bool btrcShimInit(void) {
	if (btrcAndroidStarted) { return pthread_equal(btrcAndroidThread, pthread_self()) != 0; }
	if (btrcAndroidEnv() == NULL || btrcAndroidShim == NULL) { btrcAndroidFail("the program is not running in an activity of dev.btrc.shim"); return false; }
	btrcAndroidThread = pthread_self();
	btrcAndroidStarted = true;
	return true;
}

bool btrcShimIsMainThread(void) { return !btrcAndroidStarted || pthread_equal(btrcAndroidThread, pthread_self()) != 0; }

unsigned long long btrcShimTicksNS(void) {
	struct timespec now;
	clock_gettime(CLOCK_MONOTONIC, &now);
	return (unsigned long long)now.tv_sec * 1000000000ULL + (unsigned long long)now.tv_nsec;
}

#define BTRC_ANDROID_CALL(env, name, signature) \
	static jmethodID method; \
	JNIEnv* env = btrcAndroidEnv(); \
	if (method == NULL) { method = btrcAndroidMethod(env, btrcAndroidShim, name, signature); } \
	(*env)->PushLocalFrame(env, 16)

#define BTRC_ANDROID_DONE(env) \
	btrcAndroidFailed(env); \
	(*env)->PopLocalFrame(env, NULL)

/* Controls made from now on take the appearance's theme. */
void btrcShimSetDarkAppearance(bool dark) {
	if (btrcAndroidEnv() == NULL || btrcAndroidShim == NULL) { return; }
	BTRC_ANDROID_CALL(env, "setDark", "(Z)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jboolean)dark);
	BTRC_ANDROID_DONE(env);
}

static double btrcAndroidDensity(void) {
	static double density;
	if (density <= 0.0) {
		BTRC_ANDROID_CALL(env, "windowDensity", "()F");
		density = (double)(*env)->CallStaticFloatMethod(env, btrcAndroidShim, method);
		BTRC_ANDROID_DONE(env);
		if (density <= 0.0) { density = 1.0; }
	}
	return density;
}

BtrcShimWindow* btrcShimWindowCreate(const char* title, int width, int height) {
	BtrcShimWindow* window = calloc(1, sizeof *window);
	if (window == NULL) { btrcAndroidFail("out of memory"); return NULL; }
	BTRC_ANDROID_CALL(env, "windowCreate", "(Ljava/lang/String;)I");
	window->id = (unsigned int)(*env)->CallStaticIntMethod(env, btrcAndroidShim, method, btrcAndroidString(env, title));
	BTRC_ANDROID_DONE(env);
	if (window->id == 0u) { free(window); btrcAndroidFail("the activity has no frame for a window"); return NULL; }
	window->title = strdup(title == NULL ? "" : title);
	window->askedWidth = width;
	window->askedHeight = height;
	window->next = btrcAndroidWindows;
	btrcAndroidWindows = window;
	return window;
}

void btrcShimWindowDestroy(BtrcShimWindow* window) {
	if (window == NULL) { return; }
	for (BtrcShimWindow** link = &btrcAndroidWindows; *link != NULL; link = &(*link)->next) {
		if (*link == window) { *link = window->next; break; }
	}
	btrcAndroidReleaseNativeWindow(window);
	{
		BTRC_ANDROID_CALL(env, "windowDestroy", "(I)V");
		(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)window->id);
		BTRC_ANDROID_DONE(env);
	}
	free(window->title);
	free(window->handles);
	free(window->rectangles);
	free(window);
}

unsigned int btrcShimWindowId(BtrcShimWindow* window) { return window->id; }

bool btrcShimWindowShow(BtrcShimWindow* window) {
	window->sized = true;
	BTRC_ANDROID_CALL(env, "windowShow", "(I)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)window->id);
	BTRC_ANDROID_DONE(env);
	return true;
}

bool btrcShimWindowHide(BtrcShimWindow* window) {
	BTRC_ANDROID_CALL(env, "windowHide", "(I)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)window->id);
	BTRC_ANDROID_DONE(env);
	return true;
}

bool btrcShimWindowIsHidden(BtrcShimWindow* window) {
	BTRC_ANDROID_CALL(env, "windowIsShown", "(I)Z");
	bool shown = (*env)->CallStaticBooleanMethod(env, btrcAndroidShim, method, (jint)window->id) != JNI_FALSE;
	BTRC_ANDROID_DONE(env);
	return !shown;
}

bool btrcShimWindowIsMinimized(BtrcShimWindow* window) { (void)window; return false; }

void btrcShimWindowSetTitle(BtrcShimWindow* window, const char* title) {
	free(window->title);
	window->title = strdup(title == NULL ? "" : title);
	BTRC_ANDROID_CALL(env, "windowSetTitle", "(ILjava/lang/String;)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)window->id, btrcAndroidString(env, title));
	BTRC_ANDROID_DONE(env);
}

/* The session gives every window the whole screen: a size asked for is the
 * window's until it is first shown, and no more. */
void btrcShimWindowSetSize(BtrcShimWindow* window, int width, int height) {
	window->askedWidth = width;
	window->askedHeight = height;
}

void btrcShimWindowSetMinimumSize(BtrcShimWindow* window, int width, int height) {
	(void)window;
	(void)width;
	(void)height;
}

static void btrcAndroidPixelSize(BtrcShimWindow* window, int* width, int* height) {
	*width = 0;
	*height = 0;
	if (!window->sized) { return; }
	BTRC_ANDROID_CALL(env, "windowPixelSize", "(I)[I");
	jintArray size = (*env)->CallStaticObjectMethod(env, btrcAndroidShim, method, (jint)window->id);
	jint values[2] = {0, 0};
	if (!btrcAndroidFailed(env) && size != NULL) { (*env)->GetIntArrayRegion(env, size, 0, 2, values); }
	BTRC_ANDROID_DONE(env);
	*width = values[0];
	*height = values[1];
}

int btrcShimWindowWidth(BtrcShimWindow* window) {
	int width = 0;
	int height = 0;
	btrcAndroidPixelSize(window, &width, &height);
	return width > 0 ? (int)((double)width / btrcAndroidDensity() + 0.5) : window->askedWidth;
}

int btrcShimWindowHeight(BtrcShimWindow* window) {
	int width = 0;
	int height = 0;
	btrcAndroidPixelSize(window, &width, &height);
	return height > 0 ? (int)((double)height / btrcAndroidDensity() + 0.5) : window->askedHeight;
}

int btrcShimWindowPixelWidth(BtrcShimWindow* window) {
	int width = 0;
	int height = 0;
	btrcAndroidPixelSize(window, &width, &height);
	return width > 0 ? width : (int)((double)window->askedWidth * btrcAndroidDensity() + 0.5);
}

int btrcShimWindowPixelHeight(BtrcShimWindow* window) {
	int width = 0;
	int height = 0;
	btrcAndroidPixelSize(window, &width, &height);
	return height > 0 ? height : (int)((double)window->askedHeight * btrcAndroidDensity() + 0.5);
}

double btrcShimWindowPixelDensity(BtrcShimWindow* window) { (void)window; return btrcAndroidDensity(); }

void btrcShimWindowSetCursor(BtrcShimWindow* window, int cursor) { (void)window; (void)cursor; }

void btrcShimWindowShowMessage(BtrcShimWindow* window, const char* title, const char* message) {
	(void)window;
	BTRC_ANDROID_CALL(env, "windowShowMessage", "(Ljava/lang/String;Ljava/lang/String;)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, btrcAndroidString(env, title), btrcAndroidString(env, message));
	BTRC_ANDROID_DONE(env);
}

/* Frames are presented on the window's surface, never as pictures. */
bool btrcShimWindowSupportsSoftware(BtrcShimWindow* window) { (void)window; return false; }

bool btrcShimWindowShowsPictures(BtrcShimWindow* window) { (void)window; return false; }

void btrcShimWindowShowPicture(BtrcShimWindow* window, const unsigned char* pixels, int pixelWidth, int pixelHeight) {
	(void)window;
	(void)pixels;
	(void)pixelWidth;
	(void)pixelHeight;
}

/* Text entry is the system's fields' own; the provider's editor is not used here. */
void btrcShimWindowStartTextInput(BtrcShimWindow* window) { window->textInput = true; }

void btrcShimWindowStopTextInput(BtrcShimWindow* window) { window->textInput = false; }

bool btrcShimWindowTextInputActive(BtrcShimWindow* window) { return window->textInput; }

void btrcShimWindowClearComposition(BtrcShimWindow* window) { (void)window; }

void btrcShimWindowSetTextInputArea(BtrcShimWindow* window, int x, int y, int width, int height) {
	(void)window;
	(void)x;
	(void)y;
	(void)width;
	(void)height;
}

unsigned int btrcShimModState(void) { return 0u; }

bool btrcShimSetClipboardText(const char* text) {
	BTRC_ANDROID_CALL(env, "clipboardSet", "(Ljava/lang/String;)Z");
	bool set = (*env)->CallStaticBooleanMethod(env, btrcAndroidShim, method, btrcAndroidString(env, text)) != JNI_FALSE;
	BTRC_ANDROID_DONE(env);
	return set;
}

char* btrcShimGetClipboardText(void) {
	char* copy = NULL;
	BTRC_ANDROID_CALL(env, "clipboardGet", "()Ljava/lang/String;");
	jstring text = (*env)->CallStaticObjectMethod(env, btrcAndroidShim, method);
	if (!btrcAndroidFailed(env) && text != NULL) {
		const char* characters = (*env)->GetStringUTFChars(env, text, NULL);
		if (characters != NULL) { copy = strdup(characters); (*env)->ReleaseStringUTFChars(env, text, characters); }
	}
	BTRC_ANDROID_DONE(env);
	return copy;
}

bool btrcShimHasClipboardText(void) {
	char* text = btrcShimGetClipboardText();
	bool has = text != NULL && text[0] != '\0';
	free(text);
	return has;
}

void btrcShimFree(char* text) { free(text); }

/* The system draws the line as coverage; the picture is that coverage as white's alpha. */
unsigned char* btrcShimRasterizeText(const char* text, double pixelSize, bool bold, int lineHeight, int* width, int* height) {
	if (text == NULL || width == NULL || height == NULL || pixelSize <= 0.0) { btrcAndroidFail("invalid text run"); return NULL; }
	unsigned char* pixels = NULL;
	BTRC_ANDROID_CALL(env, "rasterizeText", "(Ljava/lang/String;FZI)[B");
	jbyteArray drawn = (*env)->CallStaticObjectMethod(env, btrcAndroidShim, method, btrcAndroidString(env, text), (jfloat)pixelSize, (jboolean)bold, (jint)lineHeight);
	if (!btrcAndroidFailed(env) && drawn != NULL) {
		jsize length = (*env)->GetArrayLength(env, drawn);
		jbyte* bytes = (*env)->GetByteArrayElements(env, drawn, NULL);
		if (bytes != NULL && length >= 8) {
			const unsigned char* raw = (const unsigned char*)bytes;
			int drawnWidth = (int)((unsigned int)raw[0] << 24 | (unsigned int)raw[1] << 16 | (unsigned int)raw[2] << 8 | raw[3]);
			int drawnHeight = (int)((unsigned int)raw[4] << 24 | (unsigned int)raw[5] << 16 | (unsigned int)raw[6] << 8 | raw[7]);
			if (drawnWidth > 0 && drawnHeight > 0 && (jsize)(8 + drawnWidth * drawnHeight) <= length) {
				pixels = malloc((size_t)drawnWidth * (size_t)drawnHeight * 4u);
				for (size_t index = 0; pixels != NULL && index < (size_t)drawnWidth * (size_t)drawnHeight; index++) {
					pixels[index * 4u] = 255u;
					pixels[index * 4u + 1u] = 255u;
					pixels[index * 4u + 2u] = 255u;
					pixels[index * 4u + 3u] = raw[8u + index];
				}
				*width = drawnWidth;
				*height = drawnHeight;
			}
		}
		if (bytes != NULL) { (*env)->ReleaseByteArrayElements(env, drawn, bytes, JNI_ABORT); }
	}
	BTRC_ANDROID_DONE(env);
	if (pixels == NULL) { btrcAndroidFail("the text run cannot be drawn"); }
	return pixels;
}

void btrcShimFreePixels(unsigned char* pixels) { free(pixels); }

static int btrcAndroidPop(BtrcShimEvent* out) {
	int popped = 0;
	free(btrcAndroidQueue.handed);
	btrcAndroidQueue.handed = NULL;
	if (btrcAndroidQueue.count > 0u) {
		unsigned int slot = btrcAndroidQueue.head;
		*out = btrcAndroidQueue.events[slot];
		btrcAndroidQueue.handed = btrcAndroidQueue.texts[slot];
		btrcAndroidQueue.texts[slot] = NULL;
		out->text = btrcAndroidQueue.handed;
		btrcAndroidQueue.head = (btrcAndroidQueue.head + 1u) % BTRC_ANDROID_QUEUE;
		btrcAndroidQueue.count--;
		popped = 1;
	}
	return popped;
}

/* The UI thread runs by itself: there is nothing to let run before looking. */
int btrcShimPollEvent(BtrcShimEvent* out) {
	pthread_mutex_lock(&btrcAndroidQueue.lock);
	int popped = btrcAndroidPop(out);
	pthread_mutex_unlock(&btrcAndroidQueue.lock);
	return popped;
}

static struct timespec btrcAndroidDeadline(int milliseconds) {
	struct timespec deadline;
	clock_gettime(CLOCK_REALTIME, &deadline);
	deadline.tv_sec += milliseconds / 1000;
	deadline.tv_nsec += (long)(milliseconds % 1000) * 1000000L;
	if (deadline.tv_nsec >= 1000000000L) { deadline.tv_sec++; deadline.tv_nsec -= 1000000000L; }
	return deadline;
}

int btrcShimWaitEvent(BtrcShimEvent* out, int timeoutMilliseconds) {
	pthread_mutex_lock(&btrcAndroidQueue.lock);
	if (btrcAndroidQueue.count == 0u) {
		if (timeoutMilliseconds < 0) { pthread_cond_wait(&btrcAndroidQueue.arrived, &btrcAndroidQueue.lock); }
		else if (timeoutMilliseconds > 0) {
			struct timespec deadline = btrcAndroidDeadline(timeoutMilliseconds);
			pthread_cond_timedwait(&btrcAndroidQueue.arrived, &btrcAndroidQueue.lock, &deadline);
		}
	}
	int popped = btrcAndroidPop(out);
	pthread_mutex_unlock(&btrcAndroidQueue.lock);
	return popped;
}

bool btrcShimPushWake(void) {
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = BTRC_SHIM_EVENT_USER;
	return btrcAndroidPush(&event, NULL);
}

/* The system's folder picker names a document tree, not a directory a
 * program can open by path: there is no folder chooser here. */
BtrcShimFolderDialog* btrcShimFolderDialogOpen(BtrcShimWindow* window, const char* initialDirectory, const char* title) {
	(void)window;
	(void)initialDirectory;
	(void)title;
	btrcAndroidFail("Android has no folder to choose by path");
	return NULL;
}

int btrcShimFolderDialogState(BtrcShimFolderDialog* dialog) { return dialog->state; }

const char* btrcShimFolderDialogPath(const BtrcShimFolderDialog* dialog) { (void)dialog; return ""; }

void btrcShimFolderDialogRelease(BtrcShimFolderDialog* dialog) { free(dialog); }

BtrcShimFileDialog* btrcShimFileDialogOpen(BtrcShimWindow* window, int mode, const char* title, const char* initialDirectory, const char* defaultName, const char* filters, bool canCreateDirectories) {
	(void)window;
	(void)initialDirectory;
	(void)defaultName;
	(void)canCreateDirectories;
	JNIEnv* env = btrcAndroidEnv();
	if (env == NULL || btrcAndroidShim == NULL) {
		btrcAndroidFail("Android UI is not attached");
		return NULL;
	}
	jmethodID method = btrcAndroidMethod(env, btrcAndroidShim, "openFileDialog", "(ILjava/lang/String;Ljava/lang/String;)I");
	jstring jTitle = btrcAndroidString(env, title);
	jstring jFilters = btrcAndroidString(env, filters);
	jint id = (*env)->CallStaticIntMethod(env, btrcAndroidShim, method, (jint)mode, jTitle, jFilters);
	(*env)->DeleteLocalRef(env, jTitle);
	(*env)->DeleteLocalRef(env, jFilters);
	if (btrcAndroidFailed(env) || id <= 0) {
		btrcAndroidFail("Android file picker failed to open");
		return NULL;
	}
	BtrcShimFileDialog* dialog = calloc(1, sizeof *dialog);
	if (dialog == NULL) { return NULL; }
	dialog->id = (int)id;
	return dialog;
}

static void btrcAndroidCopyFileDialogError(JNIEnv* env, int id) {
	jmethodID method = btrcAndroidMethod(env, btrcAndroidShim, "fileDialogError", "(I)Ljava/lang/String;");
	jstring err = (jstring)(*env)->CallStaticObjectMethod(env, btrcAndroidShim, method, (jint)id);
	if (!btrcAndroidFailed(env) && err != NULL) {
		const char* utf = (*env)->GetStringUTFChars(env, err, NULL);
		if (utf != NULL) {
			if (utf[0] != '\0') { btrcAndroidFail(utf); }
			(*env)->ReleaseStringUTFChars(env, err, utf);
		}
		(*env)->DeleteLocalRef(env, err);
	}
}

static void btrcAndroidLoadFileDialogPaths(BtrcShimFileDialog* dialog) {
	if (dialog == NULL || dialog->pathsLoaded) { return; }
	dialog->pathsLoaded = true;
	JNIEnv* env = btrcAndroidEnv();
	if (env == NULL || btrcAndroidShim == NULL) { return; }
	jmethodID countMethod = btrcAndroidMethod(env, btrcAndroidShim, "fileDialogPathCount", "(I)I");
	jint count = (*env)->CallStaticIntMethod(env, btrcAndroidShim, countMethod, (jint)dialog->id);
	if (btrcAndroidFailed(env) || count <= 0) { return; }
	dialog->paths = calloc((size_t)count, sizeof(char*));
	if (dialog->paths == NULL) { return; }
	jmethodID atMethod = btrcAndroidMethod(env, btrcAndroidShim, "fileDialogPathAt", "(II)Ljava/lang/String;");
	for (jint i = 0; i < count; i++) {
		jstring value = (jstring)(*env)->CallStaticObjectMethod(env, btrcAndroidShim, atMethod, (jint)dialog->id, i);
		if (btrcAndroidFailed(env) || value == NULL) { continue; }
		const char* utf = (*env)->GetStringUTFChars(env, value, NULL);
		if (utf != NULL) {
			dialog->paths[dialog->pathCount++] = strdup(utf);
			(*env)->ReleaseStringUTFChars(env, value, utf);
		}
		(*env)->DeleteLocalRef(env, value);
	}
}

int btrcShimFileDialogState(BtrcShimFileDialog* dialog) {
	if (dialog == NULL) { return 3; }
	JNIEnv* env = btrcAndroidEnv();
	if (env == NULL || btrcAndroidShim == NULL) { return 3; }
	jmethodID method = btrcAndroidMethod(env, btrcAndroidShim, "fileDialogState", "(I)I");
	jint state = (*env)->CallStaticIntMethod(env, btrcAndroidShim, method, (jint)dialog->id);
	if (btrcAndroidFailed(env)) { return 3; }
	if (state == 1) { btrcAndroidLoadFileDialogPaths(dialog); }
	else if (state == 3 || state == 4) { btrcAndroidCopyFileDialogError(env, dialog->id); }
	return (int)state;
}

int btrcShimFileDialogPathCount(const BtrcShimFileDialog* dialog) { return dialog == NULL ? 0 : dialog->pathCount; }

const char* btrcShimFileDialogPathAt(const BtrcShimFileDialog* dialog, int index) {
	if (dialog == NULL || index < 0 || index >= dialog->pathCount || dialog->paths[index] == NULL) { return ""; }
	return dialog->paths[index];
}

void btrcShimFileDialogRelease(BtrcShimFileDialog* dialog) {
	if (dialog == NULL) { return; }
	JNIEnv* env = btrcAndroidEnv();
	if (env != NULL && btrcAndroidShim != NULL && dialog->id > 0) {
		jmethodID method = btrcAndroidMethod(env, btrcAndroidShim, "fileDialogRelease", "(I)V");
		(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)dialog->id);
		btrcAndroidFailed(env);
	}
	for (int i = 0; i < dialog->pathCount; i++) { free(dialog->paths[i]); }
	free(dialog->paths);
	free(dialog);
}

int btrcShimAutomationDisplay(void) { return BTRC_SHIM_DISPLAY_ANDROID; }

unsigned int btrcShimWindowNamed(const char* title) {
	for (BtrcShimWindow* window = btrcAndroidWindows; window != NULL; window = window->next) {
		if (strcmp(window->title, title) == 0) { return window->id; }
	}
	return 0u;
}

unsigned long btrcShimAutomationSerial(void) {
	pthread_mutex_lock(&btrcAndroidQueue.lock);
	unsigned long serial = btrcAndroidQueue.serial;
	pthread_mutex_unlock(&btrcAndroidQueue.lock);
	return serial;
}

/* Wait until something arrives after `serial` and arrivals then pause, or the timeout passes. */
int btrcShimAutomationAwait(unsigned long serial, int timeoutMilliseconds) {
	struct timespec deadline = btrcAndroidDeadline(timeoutMilliseconds < 0 ? 0 : timeoutMilliseconds);
	int arrived = 0;
	pthread_mutex_lock(&btrcAndroidQueue.lock);
	while (btrcAndroidQueue.serial == serial) {
		if (pthread_cond_timedwait(&btrcAndroidQueue.arrived, &btrcAndroidQueue.lock, &deadline) != 0) { break; }
	}
	if (btrcAndroidQueue.serial != serial) {
		arrived = 1;
		for (;;) {
			unsigned long seen = btrcAndroidQueue.serial;
			struct timespec pause = btrcAndroidDeadline(20);
			pthread_cond_timedwait(&btrcAndroidQueue.arrived, &btrcAndroidQueue.lock, &pause);
			if (btrcAndroidQueue.serial == seen) { break; }
		}
	}
	pthread_mutex_unlock(&btrcAndroidQueue.lock);
	return arrived;
}

int btrcShimAutomationPointer(unsigned int window, double* x, double* y) {
	int inside = 0;
	BTRC_ANDROID_CALL(env, "windowPointer", "(I)[F");
	jfloatArray where = (*env)->CallStaticObjectMethod(env, btrcAndroidShim, method, (jint)window);
	if (!btrcAndroidFailed(env) && where != NULL) {
		jfloat values[3] = {0.0f, 0.0f, 0.0f};
		(*env)->GetFloatArrayRegion(env, where, 0, 3, values);
		inside = values[0] != 0.0f ? 1 : 0;
		*x = values[1];
		*y = values[2];
	}
	BTRC_ANDROID_DONE(env);
	return inside;
}

int btrcShimAutomationWindows(void) {
	int count = 0;
	for (BtrcShimWindow* window = btrcAndroidWindows; window != NULL; window = window->next) { count++; }
	return count;
}

int btrcShimAutomationTextFocused(unsigned int window) {
	BTRC_ANDROID_CALL(env, "windowTextFocused", "(I)Z");
	int focused = (*env)->CallStaticBooleanMethod(env, btrcAndroidShim, method, (jint)window) != JNI_FALSE ? 1 : 0;
	BTRC_ANDROID_DONE(env);
	return focused;
}

/* Controls (ShimControls.h). */

enum { BTRC_ANDROID_BUTTON = 1, BTRC_ANDROID_LABEL, BTRC_ANDROID_SPINNER, BTRC_ANDROID_LEVEL, BTRC_ANDROID_SLIDER, BTRC_ANDROID_SELECT, BTRC_ANDROID_TEXT, BTRC_ANDROID_PICTURE, BTRC_ANDROID_FILL, BTRC_ANDROID_SCROLLBAR };

BtrcShimControl* btrcAndroidControlNew(int kind, unsigned int id, const char* text, const char* more, bool flag) {
	BtrcShimControl* control = calloc(1, sizeof *control);
	if (control == NULL) { return NULL; }
	BTRC_ANDROID_CALL(env, "controlCreate", "(IILjava/lang/String;Ljava/lang/String;Z)I");
	control->handle = (*env)->CallStaticIntMethod(env, btrcAndroidShim, method, (jint)kind, (jint)id, btrcAndroidString(env, text), btrcAndroidString(env, more), (jboolean)flag);
	BTRC_ANDROID_DONE(env);
	if (control->handle == 0) { free(control); return NULL; }
	control->id = id;
	control->kind = kind;
	return control;
}

int btrcAndroidControlHandle(BtrcShimControl* control) { return control->handle; }

void btrcShimControlDestroy(BtrcShimControl* control) {
	if (control == NULL) { return; }
	BTRC_ANDROID_CALL(env, "controlDestroy", "(I)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)control->handle);
	BTRC_ANDROID_DONE(env);
	for (int index = 0; index < control->itemCount; index++) { free(control->items[index]); }
	free(control->items);
	free(control->itemEnabled);
	free(control->shapes);
	if (control->release) { control->release(control->extension); }
	free(control);
}

void btrcShimControlSetEnabled(BtrcShimControl* control, bool enabled) {
	BTRC_ANDROID_CALL(env, "controlSetEnabled", "(IZ)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)control->handle, (jboolean)enabled);
	BTRC_ANDROID_DONE(env);
}

void btrcShimControlSetToolTip(BtrcShimControl* control, const char* text) {
	BTRC_ANDROID_CALL(env, "controlSetToolTip", "(ILjava/lang/String;)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)control->handle, btrcAndroidString(env, text));
	BTRC_ANDROID_DONE(env);
}

void btrcShimControlSetFont(BtrcShimControl* control, double size, bool bold) {
	BTRC_ANDROID_CALL(env, "controlSetFont", "(IDZ)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)control->handle, (jdouble)size, (jboolean)bold);
	BTRC_ANDROID_DONE(env);
}

/* A button's symbol and a select's items are given piece by piece; the
 * views take them whole, the next time something depends on them. */
static void btrcAndroidSettle(BtrcShimControl* control) {
	if (control->shapesChanged) {
		control->shapesChanged = false;
		BTRC_ANDROID_CALL(env, "buttonSetSymbol", "(ID[D)V");
		jdoubleArray shapes = (*env)->NewDoubleArray(env, control->shapeCount * 7);
		if (shapes != NULL && control->shapeCount > 0) { (*env)->SetDoubleArrayRegion(env, shapes, 0, control->shapeCount * 7, control->shapes); }
		(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)control->handle, (jdouble)control->symbolSize, shapes);
		BTRC_ANDROID_DONE(env);
	}
	if (control->itemsChanged) {
		control->itemsChanged = false;
		BTRC_ANDROID_CALL(env, "selectSetItems", "(I[Ljava/lang/String;[Z)V");
		jobjectArray titles = (*env)->NewObjectArray(env, control->itemCount, (*env)->FindClass(env, "java/lang/String"), NULL);
		jbooleanArray enabled = (*env)->NewBooleanArray(env, control->itemCount);
		for (int index = 0; titles != NULL && enabled != NULL && index < control->itemCount; index++) {
			jstring title = btrcAndroidString(env, control->items[index]);
			jboolean allowed = control->itemEnabled[index] ? JNI_TRUE : JNI_FALSE;
			(*env)->SetObjectArrayElement(env, titles, index, title);
			(*env)->DeleteLocalRef(env, title);
			(*env)->SetBooleanArrayRegion(env, enabled, index, 1, &allowed);
		}
		(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)control->handle, titles, enabled);
		BTRC_ANDROID_DONE(env);
	}
}

static void btrcAndroidNatural(BtrcShimControl* control, int forWidth, int* width, int* height) {
	btrcAndroidSettle(control);
	BTRC_ANDROID_CALL(env, "controlNatural", "(II)[I");
	jintArray size = (*env)->CallStaticObjectMethod(env, btrcAndroidShim, method, (jint)control->handle, (jint)forWidth);
	jint values[2] = {0, 0};
	if (!btrcAndroidFailed(env) && size != NULL) { (*env)->GetIntArrayRegion(env, size, 0, 2, values); }
	BTRC_ANDROID_DONE(env);
	*width = values[0];
	*height = values[1];
}

int btrcShimControlNaturalWidth(BtrcShimControl* control) {
	int width = 0;
	int height = 0;
	btrcAndroidNatural(control, 0, &width, &height);
	return width;
}

int btrcShimControlNaturalHeight(BtrcShimControl* control) {
	int width = 0;
	int height = 0;
	btrcAndroidNatural(control, 0, &width, &height);
	return height;
}

int btrcShimControlNaturalHeightFor(BtrcShimControl* control, int forWidth) {
	int width = 0;
	int height = 0;
	btrcAndroidNatural(control, forWidth, &width, &height);
	return height;
}

void btrcShimWindowBeginPlacement(BtrcShimWindow* window) { window->placed = 0; }

static void btrcAndroidPlace(BtrcShimWindow* window, BtrcShimControl* control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	if (window->placed == window->capacity) {
		int capacity = window->capacity == 0 ? 32 : window->capacity * 2;
		jint* handles = realloc(window->handles, (size_t)capacity * sizeof *handles);
		if (handles == NULL) { return; }
		window->handles = handles;
		jfloat* rectangles = realloc(window->rectangles, (size_t)capacity * 8u * sizeof *rectangles);
		if (rectangles == NULL) { return; }
		window->rectangles = rectangles;
		window->capacity = capacity;
	}
	if (control != NULL) { btrcAndroidSettle(control); }
	window->handles[window->placed] = control == NULL ? 0 : control->handle;
	jfloat* rectangle = window->rectangles + (size_t)window->placed * 8u;
	rectangle[0] = (jfloat)x; rectangle[1] = (jfloat)y; rectangle[2] = (jfloat)width; rectangle[3] = (jfloat)height;
	rectangle[4] = (jfloat)clipX; rectangle[5] = (jfloat)clipY; rectangle[6] = (jfloat)clipWidth; rectangle[7] = (jfloat)clipHeight;
	window->placed++;
}

void btrcShimWindowPlace(BtrcShimWindow* window, BtrcShimControl* control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	btrcAndroidPlace(window, control, x, y, width, height, clipX, clipY, clipWidth, clipHeight);
}

void btrcShimWindowPlaceHole(BtrcShimWindow* window, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	btrcAndroidPlace(window, NULL, x, y, width, height, clipX, clipY, clipWidth, clipHeight);
}

/* The whole placement crosses to the UI thread at once. */
void btrcShimWindowEndPlacement(BtrcShimWindow* window) {
	BTRC_ANDROID_CALL(env, "windowPlace", "(I[I[F)V");
	jintArray handles = (*env)->NewIntArray(env, window->placed);
	jfloatArray rectangles = (*env)->NewFloatArray(env, window->placed * 8);
	if (handles != NULL && rectangles != NULL) {
		if (window->placed > 0) {
			(*env)->SetIntArrayRegion(env, handles, 0, window->placed, window->handles);
			(*env)->SetFloatArrayRegion(env, rectangles, 0, window->placed * 8, window->rectangles);
		}
		(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)window->id, handles, rectangles);
	}
	BTRC_ANDROID_DONE(env);
}

/* The controls as the system draws them, laid over a picture of the content. */
bool btrcShimWindowDrawControls(BtrcShimWindow* window, unsigned char* pixels, int pixelWidth, int pixelHeight) {
	if (pixels == NULL || pixelWidth <= 0 || pixelHeight <= 0) { return false; }
	bool drawn = false;
	BTRC_ANDROID_CALL(env, "windowDrawControls", "(III)[B");
	jbyteArray picture = (*env)->CallStaticObjectMethod(env, btrcAndroidShim, method, (jint)window->id, (jint)pixelWidth, (jint)pixelHeight);
	if (!btrcAndroidFailed(env) && picture != NULL && (*env)->GetArrayLength(env, picture) == (jsize)(pixelWidth * pixelHeight * 4)) {
		jbyte* bytes = (*env)->GetByteArrayElements(env, picture, NULL);
		if (bytes != NULL) {
			const unsigned char* over = (const unsigned char*)bytes;
			for (size_t index = 0; index < (size_t)pixelWidth * (size_t)pixelHeight * 4u; index += 4u) {
				unsigned int covered = 255u - over[index + 3u];
				for (size_t channel = 0; channel < 3u; channel++) { pixels[index + channel] = (unsigned char)(over[index + channel] + (pixels[index + channel] * covered + 127u) / 255u); }
				pixels[index + 3u] = (unsigned char)(over[index + 3u] + (pixels[index + 3u] * covered + 127u) / 255u);
			}
			(*env)->ReleaseByteArrayElements(env, picture, bytes, JNI_ABORT);
			drawn = true;
		}
	}
	BTRC_ANDROID_DONE(env);
	return drawn;
}

/* One call of the shape (handle, text), (handle, flag) or (handle, numbers). */
static void btrcAndroidSetText(const char* name, jmethodID* method, BtrcShimControl* control, const char* text) {
	JNIEnv* env = btrcAndroidEnv();
	if (*method == NULL) { *method = btrcAndroidMethod(env, btrcAndroidShim, name, "(ILjava/lang/String;)V"); }
	(*env)->PushLocalFrame(env, 8);
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, *method, (jint)control->handle, btrcAndroidString(env, text));
	BTRC_ANDROID_DONE(env);
}

static void btrcAndroidSetFlag(const char* name, jmethodID* method, BtrcShimControl* control, bool flag) {
	JNIEnv* env = btrcAndroidEnv();
	if (*method == NULL) { *method = btrcAndroidMethod(env, btrcAndroidShim, name, "(IZ)V"); }
	(*env)->PushLocalFrame(env, 8);
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, *method, (jint)control->handle, (jboolean)flag);
	BTRC_ANDROID_DONE(env);
}

BtrcShimControl* btrcShimButtonCreate(unsigned int id, const char* title) { return btrcAndroidControlNew(BTRC_ANDROID_BUTTON, id, title, "", false); }

void btrcShimButtonSetTitle(BtrcShimControl* button, const char* title) { static jmethodID method; btrcAndroidSetText("buttonSetTitle", &method, button, title); }

void btrcShimButtonSetCentered(BtrcShimControl* button, bool centered) { static jmethodID method; btrcAndroidSetFlag("buttonSetCentered", &method, button, centered); }

void btrcShimButtonBeginSymbol(BtrcShimControl* button, double size) {
	button->symbolSize = size;
	button->shapeCount = 0;
	button->shapesChanged = true;
}

static void btrcAndroidShape(BtrcShimControl* button, double kind, double a, double b, double c, double d, double e, double f) {
	jdouble* shapes = realloc(button->shapes, ((size_t)button->shapeCount + 1u) * 7u * sizeof *shapes);
	if (shapes == NULL) { return; }
	button->shapes = shapes;
	jdouble* shape = shapes + (size_t)button->shapeCount * 7u;
	shape[0] = kind; shape[1] = a; shape[2] = b; shape[3] = c; shape[4] = d; shape[5] = e; shape[6] = f;
	button->shapeCount++;
	button->shapesChanged = true;
}

void btrcShimButtonSymbolLine(BtrcShimControl* button, double x0, double y0, double x1, double y1, double width) { btrcAndroidShape(button, 1.0, x0, y0, x1, y1, width, 0.0); }

void btrcShimButtonSymbolTriangle(BtrcShimControl* button, double x0, double y0, double x1, double y1, double x2, double y2) { btrcAndroidShape(button, 2.0, x0, y0, x1, y1, x2, y2); }

void btrcShimButtonSymbolRectangle(BtrcShimControl* button, double x, double y, double width, double height, double radius, double stroke) { btrcAndroidShape(button, 3.0, x, y, width, height, radius, stroke); }

void btrcShimButtonSymbolCircle(BtrcShimControl* button, double centerX, double centerY, double radius, double stroke) { btrcAndroidShape(button, 4.0, centerX, centerY, radius, stroke, 0.0, 0.0); }

void btrcShimButtonSetBordered(BtrcShimControl* button, bool bordered) { static jmethodID method; btrcAndroidSetFlag("buttonSetBordered", &method, button, bordered); }

void btrcShimButtonSetSelected(BtrcShimControl* button, bool selected) { static jmethodID method; btrcAndroidSetFlag("buttonSetSelected", &method, button, selected); }

void btrcShimButtonSetTransparent(BtrcShimControl* button, bool transparent) { static jmethodID method; btrcAndroidSetFlag("buttonSetTransparent", &method, button, transparent); }

BtrcShimControl* btrcShimLabelCreate(unsigned int id, const char* text) { return btrcAndroidControlNew(BTRC_ANDROID_LABEL, id, text, "", false); }

void btrcShimLabelSetText(BtrcShimControl* label, const char* text) { static jmethodID method; btrcAndroidSetText("labelSetText", &method, label, text); }

void btrcShimLabelSetSecondary(BtrcShimControl* label, bool secondary) { static jmethodID method; btrcAndroidSetFlag("labelSetSecondary", &method, label, secondary); }

void btrcShimLabelSetCentered(BtrcShimControl* label, bool centered) { static jmethodID method; btrcAndroidSetFlag("labelSetCentered", &method, label, centered); }

void btrcShimLabelSetWrapping(BtrcShimControl* label, bool wrapping) { static jmethodID method; btrcAndroidSetFlag("labelSetWrapping", &method, label, wrapping); }

BtrcShimControl* btrcShimSpinnerCreate(unsigned int id) { return btrcAndroidControlNew(BTRC_ANDROID_SPINNER, id, "", "", false); }

void btrcShimSpinnerSetRunning(BtrcShimControl* spinner, bool running) { static jmethodID method; btrcAndroidSetFlag("spinnerSetRunning", &method, spinner, running); }

BtrcShimControl* btrcShimLevelCreate(unsigned int id, double warning, double critical) {
	BtrcShimControl* control = btrcAndroidControlNew(BTRC_ANDROID_LEVEL, id, "", "", false);
	if (control != NULL) { control->warning = warning; control->critical = critical; }
	return control;
}

void btrcShimLevelSetValue(BtrcShimControl* level, double value) {
	BTRC_ANDROID_CALL(env, "levelSet", "(IDDD)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)level->handle, (jdouble)level->warning, (jdouble)level->critical, (jdouble)value);
	BTRC_ANDROID_DONE(env);
}

BtrcShimControl* btrcShimSliderCreate(unsigned int id) { return btrcAndroidControlNew(BTRC_ANDROID_SLIDER, id, "", "", false); }

void btrcShimSliderSet(BtrcShimControl* slider, double minimum, double maximum, double step, double value) {
	(void)step;
	BTRC_ANDROID_CALL(env, "sliderSet", "(IDDD)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)slider->handle, (jdouble)minimum, (jdouble)maximum, (jdouble)value);
	BTRC_ANDROID_DONE(env);
}

BtrcShimControl* btrcShimSelectCreate(unsigned int id) { return btrcAndroidControlNew(BTRC_ANDROID_SELECT, id, "", "", false); }

void btrcShimSelectClear(BtrcShimControl* select) {
	for (int index = 0; index < select->itemCount; index++) { free(select->items[index]); }
	select->itemCount = 0;
	select->itemsChanged = true;
}

void btrcShimSelectAppend(BtrcShimControl* select, const char* title, bool enabled) {
	char** items = realloc(select->items, ((size_t)select->itemCount + 1u) * sizeof *items);
	if (items == NULL) { return; }
	select->items = items;
	bool* allowed = realloc(select->itemEnabled, ((size_t)select->itemCount + 1u) * sizeof *allowed);
	if (allowed == NULL) { return; }
	select->itemEnabled = allowed;
	items[select->itemCount] = strdup(title == NULL ? "" : title);
	allowed[select->itemCount] = enabled;
	select->itemCount++;
	select->itemsChanged = true;
}

void btrcShimSelectShow(BtrcShimControl* select, int selected, const char* shown, bool available) {
	btrcAndroidSettle(select);
	BTRC_ANDROID_CALL(env, "selectShow", "(IILjava/lang/String;Z)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)select->handle, (jint)selected, btrcAndroidString(env, shown), (jboolean)available);
	BTRC_ANDROID_DONE(env);
}

void btrcShimSelectDismiss(BtrcShimControl* select) {
	BTRC_ANDROID_CALL(env, "selectDismiss", "(I)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)select->handle);
	BTRC_ANDROID_DONE(env);
}

int btrcShimSelectNaturalWidth(BtrcShimControl* select) { return btrcShimControlNaturalWidth(select); }

BtrcShimControl* btrcShimTextCreate(unsigned int id, const char* text, const char* placeholder) { return btrcAndroidControlNew(BTRC_ANDROID_TEXT, id, text, placeholder, false); }

void btrcShimTextSet(BtrcShimControl* field, const char* text) { static jmethodID method; btrcAndroidSetText("textSet", &method, field, text); }

void btrcShimTextSetPlaceholder(BtrcShimControl* field, const char* placeholder) { static jmethodID method; btrcAndroidSetText("textSetPlaceholder", &method, field, placeholder); }

BtrcShimControl* btrcShimPictureCreate(unsigned int id) { return btrcAndroidControlNew(BTRC_ANDROID_PICTURE, id, "", "", false); }

void btrcShimPictureSet(BtrcShimControl* picture, const unsigned char* pixels, int width, int height) {
	BTRC_ANDROID_CALL(env, "pictureSet", "(I[BII)V");
	jbyteArray bytes = NULL;
	if (pixels != NULL && width > 0 && height > 0) {
		bytes = (*env)->NewByteArray(env, width * height * 4);
		if (bytes != NULL) { (*env)->SetByteArrayRegion(env, bytes, 0, width * height * 4, (const jbyte*)pixels); }
	}
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)picture->handle, bytes, (jint)width, (jint)height);
	BTRC_ANDROID_DONE(env);
}

BtrcShimControl* btrcShimFillCreate(unsigned int id) { return btrcAndroidControlNew(BTRC_ANDROID_FILL, id, "", "", false); }

void btrcShimFillSet(BtrcShimControl* fill, int red, int green, int blue, int alpha, double radius) {
	BTRC_ANDROID_CALL(env, "fillSet", "(IIIIID)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)fill->handle, (jint)red, (jint)green, (jint)blue, (jint)alpha, (jdouble)radius);
	BTRC_ANDROID_DONE(env);
}

BtrcShimControl* btrcShimScrollbarCreate(unsigned int id, bool vertical) { return btrcAndroidControlNew(BTRC_ANDROID_SCROLLBAR, id, "", "", vertical); }

void btrcShimScrollbarSet(BtrcShimControl* bar, double offset, double viewport, double content) {
	BTRC_ANDROID_CALL(env, "scrollbarSet", "(IDDD)V");
	(*env)->CallStaticVoidMethod(env, btrcAndroidShim, method, (jint)bar->handle, (jdouble)offset, (jdouble)viewport, (jdouble)content);
	BTRC_ANDROID_DONE(env);
}
