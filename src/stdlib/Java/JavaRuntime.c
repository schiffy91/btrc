/* Process-wide JNI state for Library.Java (docs/design/native-interop-ownership.md
 * section 2.3): the one VM, the per-thread environment, user claim counting and
 * the class and member ID cache. It is C rather than BTRC because the thread key
 * destructor runs after BTRC's thread cleanup and must touch no BTRC state, and
 * because the cache is shared by every module unit.
 *
 * The VM is either created here (btrcJavaCreateHost, a host program) or adopted
 * (btrcJavaAdopt, from the JNI_OnLoad of a library a running VM loaded: an
 * Android application or a host `java` process). An adopted VM belongs to its
 * host: it is never destroyed here, and the threads it attached are never
 * detached here. Its application ClassLoader, read at JNI_OnLoad, resolves
 * every class, so threads this runtime attaches see the application's
 * classes.
 *
 * Java natives registrations (RegisterNatives thunks, interop step 7) install
 * the environment Java called them with for the duration of each call, raise
 * their Java exceptions here, and count their holders.
 *
 * Locking: javaLock guards every field below and is never held across a JNI
 * call except JNI_CreateJavaVM and the cache teardown in btrcJavaDestroy,
 * neither of which calls back into this file. */
#include "JNI.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static pthread_mutex_t javaLock = PTHREAD_MUTEX_INITIALIZER;
static JavaVM* javaMachine;
static int javaDestroyed;
static int javaAdopted;
static pthread_t javaCreator;
static long long javaClaims;
static int javaAttached;
static char** javaOptions;
static int javaOptionCount;
static jclass** javaClassSlots;
static size_t javaClassCount;
static jmethodID** javaMethodSlots;
static size_t javaMethodCount;
static jfieldID** javaFieldSlots;
static size_t javaFieldCount;
static pthread_once_t javaKeyOnce = PTHREAD_ONCE_INIT;
static pthread_key_t javaKey;
static _Thread_local JNIEnv* javaThreadEnvironment;
/* An adopted VM's application ClassLoader and its loadClass, or NULL. */
static jobject javaLoader;
static jmethodID javaLoadClass;
static int javaNatives;

static void javaAbort(const char* message) {
	fprintf(stderr, "Library.Java: %s\n", message);
	abort();
}

static void* javaGrow(void* items, size_t count, size_t size) {
	void* grown = realloc(items, (count + 1) * size);
	if (grown == NULL) { javaAbort("out of memory"); }
	return grown;
}

/* Runs at the exit of a thread this runtime attached, after BTRC's thread
 * cleanup has released that thread's claims; Java's own threads, the creating
 * thread, the thread that adopted the VM and threads Java attached never have
 * a key value. */
static void javaDetach(void* environment) {
	(void)environment;
	pthread_mutex_lock(&javaLock);
	JavaVM* machine = javaMachine;
	pthread_mutex_unlock(&javaLock);
	if (machine != NULL && (*machine)->DetachCurrentThread(machine) != JNI_OK) { javaAbort("cannot detach a thread from the Java VM"); }
	javaThreadEnvironment = NULL;
	pthread_mutex_lock(&javaLock);
	javaAttached--;
	pthread_mutex_unlock(&javaLock);
}

static void javaCreateKey(void) {
	if (pthread_key_create(&javaKey, javaDetach) != 0) { javaAbort("cannot create the Java environment key"); }
}

void btrcJavaAddOption(const char* option) {
	if (option == NULL) { javaAbort("a Java VM option cannot be null"); }
	size_t length = strlen(option);
	char* copy = malloc(length + 1);
	if (copy == NULL) { javaAbort("out of memory"); }
	memcpy(copy, option, length + 1);
	pthread_mutex_lock(&javaLock);
	if (javaAdopted) {
		pthread_mutex_unlock(&javaLock);
		javaAbort("an adopted Java VM takes no options; its host started it");
	}
	if (javaMachine != NULL || javaDestroyed) {
		pthread_mutex_unlock(&javaLock);
		javaAbort("Java VM options must precede its creation");
	}
	javaOptions = javaGrow(javaOptions, (size_t)javaOptionCount, sizeof *javaOptions);
	javaOptions[javaOptionCount++] = copy;
	pthread_mutex_unlock(&javaLock);
}

int btrcJavaCreateHost(void) {
#ifdef __ANDROID__
	javaAbort("Android runs the application's own VM; JNI_OnLoad adopts it (btrcJavaAdopt), it is never created");
	return JNI_ERR;
#else
	pthread_mutex_lock(&javaLock);
	if (javaMachine != NULL || javaDestroyed) {
		pthread_mutex_unlock(&javaLock);
		javaAbort("a process runs at most one Java VM");
	}
	JavaVMOption* options = calloc(javaOptionCount > 0 ? (size_t)javaOptionCount : 1u, sizeof *options);
	if (options == NULL) { javaAbort("out of memory"); }
	for (int index = 0; index < javaOptionCount; index++) {
		options[index].optionString = javaOptions[index];
		options[index].extraInfo = NULL;
	}
	JavaVMInitArgs arguments;
	arguments.version = JNI_VERSION_1_8;
	arguments.nOptions = javaOptionCount;
	arguments.options = options;
	arguments.ignoreUnrecognized = JNI_FALSE;
	JavaVM* machine = NULL;
	JNIEnv* environment = NULL;
	jint status = JNI_CreateJavaVM(&machine, (void**)&environment, &arguments);
	free(options);
	for (int index = 0; index < javaOptionCount; index++) { free(javaOptions[index]); }
	free(javaOptions);
	javaOptions = NULL;
	javaOptionCount = 0;
	if (status == JNI_OK) {
		javaMachine = machine;
		javaCreator = pthread_self();
		javaThreadEnvironment = environment;
	}
	pthread_mutex_unlock(&javaLock);
	return (int)status;
#endif
}

/* The context class loader of the thread running JNI_OnLoad, as a global
 * reference, and ClassLoader.loadClass. Returns 0 when reading them fails,
 * with no exception left pending; *loader stays NULL when the thread has no
 * context class loader, and classes then resolve through FindClass. */
static int javaReadLoader(JNIEnv* env, jobject* loader, jmethodID* loadClass) {
	*loader = NULL;
	*loadClass = NULL;
	if ((*env)->PushLocalFrame(env, 4) != 0) {
		(*env)->ExceptionClear(env);
		return 0;
	}
	int read = 0;
	jvalue none[1];
	none[0].j = 0;
	jclass threads = (*env)->FindClass(env, "java/lang/Thread");
	if ((*env)->ExceptionCheck(env) || threads == NULL) { goto done; }
	jmethodID current = (*env)->GetStaticMethodID(env, threads, "currentThread", "()Ljava/lang/Thread;");
	if ((*env)->ExceptionCheck(env) || current == NULL) { goto done; }
	jobject thread = (*env)->CallStaticObjectMethodA(env, threads, current, none);
	if ((*env)->ExceptionCheck(env) || thread == NULL) { goto done; }
	jmethodID context = (*env)->GetMethodID(env, threads, "getContextClassLoader", "()Ljava/lang/ClassLoader;");
	if ((*env)->ExceptionCheck(env) || context == NULL) { goto done; }
	jobject found = (*env)->CallObjectMethodA(env, thread, context, none);
	if ((*env)->ExceptionCheck(env)) { goto done; }
	if (found == NULL) {
		read = 1;
		goto done;
	}
	jclass loaders = (*env)->FindClass(env, "java/lang/ClassLoader");
	if ((*env)->ExceptionCheck(env) || loaders == NULL) { goto done; }
	jmethodID load = (*env)->GetMethodID(env, loaders, "loadClass", "(Ljava/lang/String;)Ljava/lang/Class;");
	if ((*env)->ExceptionCheck(env) || load == NULL) { goto done; }
	jobject global = (*env)->NewGlobalRef(env, found);
	if ((*env)->ExceptionCheck(env) || global == NULL) { goto done; }
	*loader = global;
	*loadClass = load;
	read = 1;
done:
	if ((*env)->ExceptionCheck(env)) { (*env)->ExceptionClear(env); }
	(*env)->PopLocalFrame(env, NULL);
	return read;
}

int btrcJavaAdopt(JavaVM* machine) {
	if (machine == NULL) { javaAbort("an adopted Java VM cannot be null"); }
	/* JNI_OnLoad runs on a thread the VM attached, so GetEnv answers without
	 * attaching; this thread's JNI calls run outside javaLock. */
	JNIEnv* environment = NULL;
	jint status = (*machine)->GetEnv(machine, (void**)&environment, JNI_VERSION_1_6);
	if (status != JNI_OK || environment == NULL) { return status != JNI_OK ? (int)status : JNI_ERR; }
	jobject loader = NULL;
	jmethodID loadClass = NULL;
	if (!javaReadLoader(environment, &loader, &loadClass)) { return JNI_ERR; }
	pthread_mutex_lock(&javaLock);
	if (javaMachine != NULL || javaDestroyed) {
		pthread_mutex_unlock(&javaLock);
		javaAbort("a process runs at most one Java VM");
	}
	if (javaOptionCount != 0) {
		pthread_mutex_unlock(&javaLock);
		javaAbort("Java VM options apply only to a VM this library creates, not to an adopted one");
	}
	javaMachine = machine;
	javaAdopted = 1;
	javaLoader = loader;
	javaLoadClass = loadClass;
	pthread_mutex_unlock(&javaLock);
	javaThreadEnvironment = environment;
	return JNI_OK;
}

int btrcJavaRunning(void) {
	pthread_mutex_lock(&javaLock);
	int running = javaMachine != NULL;
	pthread_mutex_unlock(&javaLock);
	return running;
}

int btrcJavaAdopted(void) {
	pthread_mutex_lock(&javaLock);
	int adopted = javaAdopted;
	pthread_mutex_unlock(&javaLock);
	return adopted;
}

long long btrcJavaLiveClaims(void) {
	pthread_mutex_lock(&javaLock);
	long long claims = javaClaims;
	pthread_mutex_unlock(&javaLock);
	return claims;
}

int btrcJavaAttachedThreads(void) {
	pthread_mutex_lock(&javaLock);
	int attached = javaAttached;
	pthread_mutex_unlock(&javaLock);
	return attached;
}

JNIEnv* btrcJavaEnvironment(void) {
	if (javaThreadEnvironment != NULL) { return javaThreadEnvironment; }
	pthread_mutex_lock(&javaLock);
	JavaVM* machine = javaMachine;
	pthread_mutex_unlock(&javaLock);
	if (machine == NULL) { javaAbort("no Java VM is running; create one with JavaVirtualMachine"); }
	JNIEnv* environment = NULL;
	jint status = (*machine)->GetEnv(machine, (void**)&environment, JNI_VERSION_1_6);
	if (status == JNI_EDETACHED) {
		pthread_once(&javaKeyOnce, javaCreateKey);
		/* A daemon thread never holds DestroyJavaVM back. */
#ifdef __ANDROID__
		status = (*machine)->AttachCurrentThreadAsDaemon(machine, &environment, NULL);
#else
		status = (*machine)->AttachCurrentThreadAsDaemon(machine, (void**)&environment, NULL);
#endif
		if (status != JNI_OK || environment == NULL) { javaAbort("cannot attach this thread to the Java VM"); }
		if (pthread_setspecific(javaKey, environment) != 0) { javaAbort("cannot mark an attached thread"); }
		pthread_mutex_lock(&javaLock);
		javaAttached++;
		pthread_mutex_unlock(&javaLock);
	} else if (status != JNI_OK || environment == NULL) {
		javaAbort("the Java VM does not support JNI 1.6");
	}
	javaThreadEnvironment = environment;
	return environment;
}

void btrcJavaClaim(void) {
	pthread_mutex_lock(&javaLock);
	if (javaMachine == NULL) {
		pthread_mutex_unlock(&javaLock);
		javaAbort("a Java reference outlived its VM");
	}
	javaClaims++;
	pthread_mutex_unlock(&javaLock);
}

void btrcJavaUnclaim(void) {
	pthread_mutex_lock(&javaLock);
	if (javaClaims <= 0) {
		pthread_mutex_unlock(&javaLock);
		javaAbort("a Java reference was released twice");
	}
	javaClaims--;
	pthread_mutex_unlock(&javaLock);
}

/* Formats Throwable.toString() in its own local frame. A second exception
 * while doing so has no meaningful translation, so it terminates. */
static void javaDescribe(JNIEnv* env, jthrowable thrown, const char* prefix, char* message, size_t capacity) {
	if ((*env)->PushLocalFrame(env, 4) != 0) { javaAbort("out of memory while describing a Java exception"); }
	jclass object = (*env)->FindClass(env, "java/lang/Object");
	if ((*env)->ExceptionCheck(env) || object == NULL) { javaAbort("cannot describe a Java exception"); }
	jmethodID toString = (*env)->GetMethodID(env, object, "toString", "()Ljava/lang/String;");
	if ((*env)->ExceptionCheck(env) || toString == NULL) { javaAbort("cannot describe a Java exception"); }
	jvalue none[1];
	none[0].j = 0;
	jstring text = (jstring)(*env)->CallObjectMethodA(env, thrown, toString, none);
	if ((*env)->ExceptionCheck(env) || text == NULL) { javaAbort("a Java exception's toString failed"); }
	jsize count = (*env)->GetStringLength(env, text);
	if ((*env)->ExceptionCheck(env)) { javaAbort("cannot describe a Java exception"); }
	jchar* units = malloc((count > 0 ? (size_t)count : 1u) * sizeof *units);
	if (units == NULL) { javaAbort("out of memory"); }
	(*env)->GetStringRegion(env, text, 0, count, units);
	if ((*env)->ExceptionCheck(env)) { javaAbort("cannot describe a Java exception"); }
	/* U+0000 cannot reach a message; it reads as U+FFFD instead. */
	for (jsize index = 0; index < count; index++) {
		if (units[index] == 0) { units[index] = 0xFFFD; }
	}
	long long length = btrcJavaStringLength(units, count);
	char* encoded = malloc((size_t)length + 1);
	if (encoded == NULL) { javaAbort("out of memory"); }
	btrcJavaEncodeString(units, count, encoded);
	encoded[length] = '\0';
	snprintf(message, capacity, "%s%s", prefix, encoded);
	free(encoded);
	free(units);
	(*env)->PopLocalFrame(env, NULL);
}

void btrcJavaTakeException(JNIEnv* env, int pop, char* message, size_t capacity) {
	jthrowable thrown = (*env)->ExceptionOccurred(env);
	if (thrown == NULL) { javaAbort("no Java exception is pending"); }
	(*env)->ExceptionClear(env);
	javaDescribe(env, thrown, "JavaException: ", message, capacity);
	(*env)->DeleteLocalRef(env, thrown);
	if (pop) { (*env)->PopLocalFrame(env, NULL); }
}

/* The class file and the running VM disagree about a member or class: no
 * program can recover, so this terminates naming both. Any other pending
 * exception (a static initializer's failure) is thrown again for the adapter
 * to translate. */
static void javaRequireLinked(JNIEnv* env, const char* owner, const char* name, const char* descriptor) {
	jthrowable thrown = (*env)->ExceptionOccurred(env);
	(*env)->ExceptionClear(env);
	static const char* const linkage[] = {"java/lang/NoSuchMethodError", "java/lang/NoSuchFieldError", "java/lang/NoClassDefFoundError", "java/lang/ClassNotFoundException"};
	int mismatch = 0;
	for (size_t index = 0; index < sizeof linkage / sizeof linkage[0] && !mismatch; index++) {
		jclass type = (*env)->FindClass(env, linkage[index]);
		if ((*env)->ExceptionCheck(env) || type == NULL) { javaAbort("cannot classify a Java linkage failure"); }
		mismatch = (*env)->IsInstanceOf(env, thrown, type) == JNI_TRUE;
		(*env)->DeleteLocalRef(env, type);
	}
	if (mismatch) {
		char detail[512];
		javaDescribe(env, thrown, "", detail, sizeof detail);
		fprintf(stderr, "Library.Java: metadata/runtime API mismatch for %s%s%s%s: %s\n", owner, name[0] ? "." : "", name, descriptor, detail);
		abort();
	}
	if ((*env)->Throw(env, thrown) != 0) { javaAbort("cannot rethrow a Java exception"); }
	(*env)->DeleteLocalRef(env, thrown);
}

/* An adopted VM's application classes resolve through its cached ClassLoader,
 * so a thread this runtime attached sees them too; FindClass there would
 * search the system class loader (native-interop-ownership.md 2.3, "VM
 * lifetime"). A class that loader does not know falls back to FindClass, for
 * a host whose JNI_OnLoad thread had an unrelated context class loader.
 * Returns a local reference, or NULL with an exception pending. */
static jclass javaLoadClassNamed(JNIEnv* env, jobject loader, jmethodID loadClass, const char* binaryName) {
	size_t length = strlen(binaryName);
	char* dotted = malloc(length + 1);
	if (dotted == NULL) { javaAbort("out of memory"); }
	for (size_t index = 0; index <= length; index++) { dotted[index] = binaryName[index] == '/' ? '.' : binaryName[index]; }
	jstring name = btrcJavaNewString(env, dotted);
	free(dotted);
	if ((*env)->ExceptionCheck(env)) { return NULL; }
	jvalue argument[1];
	argument[0].l = name;
	jclass local = (jclass)(*env)->CallObjectMethodA(env, loader, loadClass, argument);
	int failed = (*env)->ExceptionCheck(env);
	(*env)->DeleteLocalRef(env, name);
	if (!failed) { return local; }
	(*env)->ExceptionClear(env);
	return (*env)->FindClass(env, binaryName);
}

jclass btrcJavaClass(JNIEnv* env, jclass* slot, const char* binaryName) {
	pthread_mutex_lock(&javaLock);
	jclass cached = *slot;
	jobject loader = javaLoader;
	jmethodID loadClass = javaLoadClass;
	pthread_mutex_unlock(&javaLock);
	if (cached != NULL) { return cached; }
	jclass local = loader != NULL ? javaLoadClassNamed(env, loader, loadClass, binaryName) : (*env)->FindClass(env, binaryName);
	if ((*env)->ExceptionCheck(env)) {
		javaRequireLinked(env, binaryName, "", "");
		return NULL;
	}
	if (local == NULL) { javaAbort("FindClass returned null without an exception"); }
	jclass global = (jclass)(*env)->NewGlobalRef(env, local);
	(*env)->DeleteLocalRef(env, local);
	if (global == NULL) { javaAbort("out of memory for a global class reference"); }
	pthread_mutex_lock(&javaLock);
	if (*slot == NULL) {
		javaClassSlots = javaGrow(javaClassSlots, javaClassCount, sizeof *javaClassSlots);
		javaClassSlots[javaClassCount++] = slot;
		*slot = global;
		global = NULL;
	}
	cached = *slot;
	pthread_mutex_unlock(&javaLock);
	if (global != NULL) { (*env)->DeleteGlobalRef(env, global); }
	return cached;
}

jmethodID btrcJavaMethod(JNIEnv* env, jclass owner, jmethodID* slot, const char* name, const char* descriptor, int isStatic) {
	pthread_mutex_lock(&javaLock);
	jmethodID cached = *slot;
	pthread_mutex_unlock(&javaLock);
	if (cached != NULL) { return cached; }
	jmethodID found = isStatic ? (*env)->GetStaticMethodID(env, owner, name, descriptor) : (*env)->GetMethodID(env, owner, name, descriptor);
	if ((*env)->ExceptionCheck(env)) {
		javaRequireLinked(env, "", name, descriptor);
		return NULL;
	}
	if (found == NULL) { javaAbort("a method ID lookup returned null without an exception"); }
	pthread_mutex_lock(&javaLock);
	if (*slot == NULL) {
		javaMethodSlots = javaGrow(javaMethodSlots, javaMethodCount, sizeof *javaMethodSlots);
		javaMethodSlots[javaMethodCount++] = slot;
		*slot = found;
	}
	cached = *slot;
	pthread_mutex_unlock(&javaLock);
	return cached;
}

jfieldID btrcJavaField(JNIEnv* env, jclass owner, jfieldID* slot, const char* name, const char* descriptor, int isStatic) {
	pthread_mutex_lock(&javaLock);
	jfieldID cached = *slot;
	pthread_mutex_unlock(&javaLock);
	if (cached != NULL) { return cached; }
	jfieldID found = isStatic ? (*env)->GetStaticFieldID(env, owner, name, descriptor) : (*env)->GetFieldID(env, owner, name, descriptor);
	if ((*env)->ExceptionCheck(env)) {
		javaRequireLinked(env, "", name, descriptor);
		return NULL;
	}
	if (found == NULL) { javaAbort("a field ID lookup returned null without an exception"); }
	pthread_mutex_lock(&javaLock);
	if (*slot == NULL) {
		javaFieldSlots = javaGrow(javaFieldSlots, javaFieldCount, sizeof *javaFieldSlots);
		javaFieldSlots[javaFieldCount++] = slot;
		*slot = found;
	}
	cached = *slot;
	pthread_mutex_unlock(&javaLock);
	return cached;
}

jstring btrcJavaNewString(JNIEnv* env, const char* text) {
	if (text == NULL) { return NULL; }
	const unsigned char* bytes = (const unsigned char*)text;
	size_t length = strlen(text);
	if (length > 0x7fffffffu) { javaAbort("a string is too long for Java"); }
	jchar* units = malloc((length > 0 ? length : 1u) * sizeof *units);
	if (units == NULL) { javaAbort("out of memory"); }
	size_t count = 0;
	for (size_t index = 0; index < length;) {
		unsigned int first = bytes[index];
		unsigned int point = 0xFFFD;
		size_t width = 1;
		if (first < 0x80) { point = first; }
		else if (first >= 0xC2 && first < 0xE0 && index + 1 < length && (bytes[index + 1] & 0xC0) == 0x80) {
			point = ((first & 0x1Fu) << 6) | (bytes[index + 1] & 0x3Fu);
			width = 2;
		} else if (first >= 0xE0 && first < 0xF0 && index + 2 < length && (bytes[index + 1] & 0xC0) == 0x80 && (bytes[index + 2] & 0xC0) == 0x80) {
			unsigned int decoded = ((first & 0x0Fu) << 12) | ((bytes[index + 1] & 0x3Fu) << 6) | (bytes[index + 2] & 0x3Fu);
			if (decoded >= 0x800 && (decoded < 0xD800 || decoded > 0xDFFF)) {
				point = decoded;
				width = 3;
			}
		} else if (first >= 0xF0 && first < 0xF5 && index + 3 < length && (bytes[index + 1] & 0xC0) == 0x80 && (bytes[index + 2] & 0xC0) == 0x80 && (bytes[index + 3] & 0xC0) == 0x80) {
			unsigned int decoded = ((first & 0x07u) << 18) | ((bytes[index + 1] & 0x3Fu) << 12) | ((bytes[index + 2] & 0x3Fu) << 6) | (bytes[index + 3] & 0x3Fu);
			if (decoded >= 0x10000 && decoded <= 0x10FFFF) {
				point = decoded;
				width = 4;
			}
		}
		if (point >= 0x10000) {
			point -= 0x10000;
			units[count++] = (jchar)(0xD800 + (point >> 10));
			units[count++] = (jchar)(0xDC00 + (point & 0x3FFu));
		} else {
			units[count++] = (jchar)point;
		}
		index += width;
	}
	jstring result = (*env)->NewString(env, units, (jsize)count);
	free(units);
	return result;
}

/* The scalar value of the unit at `index`, and how many units it spans. */
static unsigned int javaScalar(const jchar* units, jsize count, jsize index, jsize* width) {
	unsigned int unit = units[index];
	*width = 1;
	if (unit >= 0xD800 && unit <= 0xDBFF && index + 1 < count && units[index + 1] >= 0xDC00 && units[index + 1] <= 0xDFFF) {
		*width = 2;
		return 0x10000 + ((unit - 0xD800) << 10) + (units[index + 1] - 0xDC00u);
	}
	return unit >= 0xD800 && unit <= 0xDFFF ? 0xFFFD : unit;
}

long long btrcJavaStringLength(const jchar* units, jsize count) {
	long long length = 0;
	for (jsize index = 0, width = 1; index < count; index += width) {
		unsigned int point = javaScalar(units, count, index, &width);
		if (point == 0) { return -1; }
		length += point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
	}
	return length;
}

void btrcJavaEncodeString(const jchar* units, jsize count, char* text) {
	unsigned char* out = (unsigned char*)text;
	for (jsize index = 0, width = 1; index < count; index += width) {
		unsigned int point = javaScalar(units, count, index, &width);
		if (point < 0x80) { *out++ = (unsigned char)point; }
		else if (point < 0x800) {
			*out++ = (unsigned char)(0xC0 | (point >> 6));
			*out++ = (unsigned char)(0x80 | (point & 0x3F));
		} else if (point < 0x10000) {
			*out++ = (unsigned char)(0xE0 | (point >> 12));
			*out++ = (unsigned char)(0x80 | ((point >> 6) & 0x3F));
			*out++ = (unsigned char)(0x80 | (point & 0x3F));
		} else {
			*out++ = (unsigned char)(0xF0 | (point >> 18));
			*out++ = (unsigned char)(0x80 | ((point >> 12) & 0x3F));
			*out++ = (unsigned char)(0x80 | ((point >> 6) & 0x3F));
			*out++ = (unsigned char)(0x80 | (point & 0x3F));
		}
	}
}

JNIEnv* btrcJavaEnter(JNIEnv* env) {
	if (env == NULL) { javaAbort("a Java native thunk requires its environment"); }
	JNIEnv* previous = javaThreadEnvironment;
	javaThreadEnvironment = env;
	return previous;
}

void btrcJavaLeave(JNIEnv* previous) { javaThreadEnvironment = previous; }

void btrcJavaThrow(JNIEnv* env, const char* className, const char* message) {
	if ((*env)->ExceptionCheck(env)) { return; }
	if ((*env)->PushLocalFrame(env, 3) != 0) { return; }
	jclass type = (*env)->FindClass(env, className);
	if ((*env)->ExceptionCheck(env) || type == NULL) {
		(*env)->PopLocalFrame(env, NULL);
		return;
	}
	jmethodID create = (*env)->GetMethodID(env, type, "<init>", "(Ljava/lang/String;)V");
	if ((*env)->ExceptionCheck(env) || create == NULL) {
		(*env)->PopLocalFrame(env, NULL);
		return;
	}
	jstring text = btrcJavaNewString(env, message);
	if ((*env)->ExceptionCheck(env)) {
		(*env)->PopLocalFrame(env, NULL);
		return;
	}
	jvalue argument[1];
	argument[0].l = text;
	jthrowable thrown = (jthrowable)(*env)->NewObjectA(env, type, create, argument);
	if ((*env)->ExceptionCheck(env) || thrown == NULL) {
		(*env)->PopLocalFrame(env, NULL);
		return;
	}
	if ((*env)->Throw(env, thrown) != 0) { javaAbort("cannot throw a Java exception"); }
	(*env)->PopLocalFrame(env, NULL);
}

char* btrcJavaCopyString(JNIEnv* env, jstring value) {
	jsize count = (*env)->GetStringLength(env, value);
	if ((*env)->ExceptionCheck(env)) { return NULL; }
	jchar* units = malloc((count > 0 ? (size_t)count : 1u) * sizeof *units);
	if (units == NULL) { javaAbort("out of memory"); }
	(*env)->GetStringRegion(env, value, 0, count, units);
	if ((*env)->ExceptionCheck(env)) {
		free(units);
		return NULL;
	}
	long long length = btrcJavaStringLength(units, count);
	if (length < 0 || length > 2147483646) {
		free(units);
		btrcJavaThrow(env, "java/lang/IllegalArgumentException", length < 0 ? "Java string contains U+0000, which a BTRC string cannot hold" : "Java string is too long for a BTRC string");
		return NULL;
	}
	char* text = malloc((size_t)length + 1);
	if (text == NULL) { javaAbort("out of memory"); }
	btrcJavaEncodeString(units, count, text);
	text[length] = '\0';
	free(units);
	return text;
}

void btrcJavaNativeMethod(JNINativeMethod* entry, const char* name, const char* signature, void (*function)(void)) {
	_Static_assert(sizeof(void (*)(void)) == sizeof(void*), "JNI stores a native function as void*");
	entry->name = (char*)name;
	entry->signature = (char*)signature;
	memcpy(&entry->fnPtr, &function, sizeof entry->fnPtr);
}

jint btrcJavaRegisterNatives(JNIEnv* env, jclass owner, const JNINativeMethod* methods, jint count, const char* binaryName) {
	jint status = (*env)->RegisterNatives(env, owner, methods, count);
	if ((*env)->ExceptionCheck(env)) {
		javaRequireLinked(env, binaryName, "", "");
		return JNI_ERR;
	}
	if (status != JNI_OK) { javaAbort("RegisterNatives failed without an exception"); }
	return status;
}

void btrcJavaNativesOpened(void) {
	pthread_mutex_lock(&javaLock);
	javaNatives++;
	pthread_mutex_unlock(&javaLock);
}

void btrcJavaNativesClosed(void) {
	pthread_mutex_lock(&javaLock);
	if (javaNatives <= 0) {
		pthread_mutex_unlock(&javaLock);
		javaAbort("a Java natives holder was freed twice");
	}
	javaNatives--;
	pthread_mutex_unlock(&javaLock);
}

int btrcJavaLiveNatives(void) {
	pthread_mutex_lock(&javaLock);
	int natives = javaNatives;
	pthread_mutex_unlock(&javaLock);
	return natives;
}

void btrcJavaDestroy(void) {
	pthread_mutex_lock(&javaLock);
	JavaVM* machine = javaMachine;
	char problem[160] = "";
	if (machine == NULL) { snprintf(problem, sizeof problem, "no Java VM is running"); }
	else if (javaAdopted) { snprintf(problem, sizeof problem, "an adopted Java VM belongs to its host and is never destroyed"); }
	else if (!pthread_equal(javaCreator, pthread_self())) { snprintf(problem, sizeof problem, "only the thread that created the Java VM can destroy it"); }
	else if (javaClaims != 0) { snprintf(problem, sizeof problem, "the Java VM was destroyed with %lld live references", javaClaims); }
	else if (javaAttached != 0) { snprintf(problem, sizeof problem, "the Java VM was destroyed with %d attached threads", javaAttached); }
	pthread_mutex_unlock(&javaLock);
	if (problem[0]) { javaAbort(problem); }
	JNIEnv* env = btrcJavaEnvironment();
	/* The cache is outside the user count: its global class references go
	 * first, and its IDs die with the VM. */
	pthread_mutex_lock(&javaLock);
	for (size_t index = 0; index < javaClassCount; index++) {
		(*env)->DeleteGlobalRef(env, *javaClassSlots[index]);
		*javaClassSlots[index] = NULL;
	}
	for (size_t index = 0; index < javaMethodCount; index++) { *javaMethodSlots[index] = NULL; }
	for (size_t index = 0; index < javaFieldCount; index++) { *javaFieldSlots[index] = NULL; }
	free(javaClassSlots);
	free(javaMethodSlots);
	free(javaFieldSlots);
	javaClassSlots = NULL;
	javaMethodSlots = NULL;
	javaFieldSlots = NULL;
	javaClassCount = javaMethodCount = javaFieldCount = 0;
	javaMachine = NULL;
	javaDestroyed = 1;
	pthread_mutex_unlock(&javaLock);
	javaThreadEnvironment = NULL;
	if ((*machine)->DestroyJavaVM(machine) != JNI_OK) { javaAbort("the Java VM did not shut down"); }
}
