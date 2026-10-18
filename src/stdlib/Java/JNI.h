/* JNI for Library.Java. The manifest binds the btrcJava* functions below to
 * JavaVirtualMachine.btrc; compiler-generated Java adapters call the rest by
 * name and dispatch through the JNIEnv function table themselves
 * (docs/design/native-interop-ownership.md section 2.3). JavaRuntime.c owns
 * the one VM, the per-thread environment key, user claim counting and the
 * class and member ID cache, because their state is process-wide. */
#ifndef BTRC_JAVA_JNI_H
#define BTRC_JAVA_JNI_H
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include <jni.h>
#include <stddef.h>

/* VM lifetime, for JavaVirtualMachine.btrc. Options are queued, then the VM
 * starts with all of them; creation returns the JNI status (0 is JNI_OK). */
void btrcJavaAddOption(const char* option);
int btrcJavaCreateHost(void);
int btrcJavaRunning(void);
int btrcJavaAdopted(void);
long long btrcJavaLiveClaims(void);
long long btrcJavaLiveWeaks(void);
int btrcJavaAttachedThreads(void);
void btrcJavaDestroy(void);

/* For the JNI_OnLoad of a library a running VM loaded (an Android app, or
 * System.load in a host `java` process): makes `machine` the process's VM.
 * Returns JNI_OK, or GetEnv's status when the VM lacks JNI 1.6 (or the
 * application class loader cannot be read), for JNI_OnLoad to refuse the
 * load. An adopted VM is the host's: queued options, a second VM and
 * btrcJavaDestroy all terminate. The loading thread keeps the environment its
 * VM gave it; other threads attach as daemons on first use and detach when
 * they exit, as with a created VM.
 *
 * The application ClassLoader is the context class loader of the thread
 * running JNI_OnLoad (an Android application's main thread runs with its
 * PathClassLoader). It is cached as a global reference, and every class then
 * resolves through its loadClass, on every thread: FindClass on a thread
 * the runtime attached would search the system class loader instead. */
int btrcJavaAdopt(JavaVM* machine);

/* For generated adapters. The environment of the calling thread, attached as
 * a daemon on first use when the VM is running and the thread is not Java's. */
JNIEnv* btrcJavaEnvironment(void);
/* One user global reference created or deleted by a class owner. */
void btrcJavaClaim(void);
void btrcJavaUnclaim(void);
/* One weak global reference created or deleted by a JavaWeak owner. */
void btrcJavaWeakClaim(void);
void btrcJavaWeakUnclaim(void);
/* executor = "main" (interop step 7): returns on the main thread, the thread
 * of android.os.Looper.getMainLooper(), which this runtime captures through
 * its own checked JNI at the first check and caches as a global reference
 * outside the user count. Any other thread terminates naming `what`, and so
 * does the first check of a VM with no main Looper (a host JVM). */
void btrcJavaRequireMain(JNIEnv* env, const char* what);
/* Cached global class reference and member IDs, resolved once per slot. Each
 * returns NULL with the Java exception still pending, or aborts naming the
 * member when the class file and the running VM disagree. */
jclass btrcJavaClass(JNIEnv* env, jclass* slot, const char* binaryName);
jmethodID btrcJavaMethod(JNIEnv* env, jclass owner, jmethodID* slot, const char* name, const char* descriptor, int isStatic);
jfieldID btrcJavaField(JNIEnv* env, jclass owner, jfieldID* slot, const char* name, const char* descriptor, int isStatic);
/* Strings copy through UTF-16, never modified UTF-8. A NULL text is Java's
 * null. On failure the Java exception is pending and the result is NULL. */
jstring btrcJavaNewString(JNIEnv* env, const char* text);
/* The UTF-8 length of a Java string's UTF-16 units, or -1 when it holds
 * U+0000, which a BTRC string cannot carry; unpaired surrogates become
 * U+FFFD. btrcJavaEncodeString writes exactly that many bytes. */
long long btrcJavaStringLength(const jchar* units, jsize count);
void btrcJavaEncodeString(const jchar* units, jsize count, char* text);
/* Clears the pending exception, pops the adapter's local frame when `pop`,
 * and formats "JavaException: <Throwable.toString()>" into `message`. */
void btrcJavaTakeException(JNIEnv* env, int pop, char* message, size_t capacity);

/* For the generated thunks of a Java `natives` registration (Java -> BTRC,
 * interop step 7). A thunk makes the environment Java called it with the
 * calling thread's for the duration of the call, so the BTRC code it runs
 * calls back into Java through it (btrcJavaEnvironment returns it), and
 * restores the one btrcJavaEnter returned when it returns; calls nest. */
JNIEnv* btrcJavaEnter(JNIEnv* env);
void btrcJavaLeave(JNIEnv* previous);
/* Leaves a new `className` (a Throwable taking one String) pending, its
 * message copied through UTF-16. When that fails, the failure (an
 * OutOfMemoryError) is what is pending instead; either way the thunk then
 * returns to Java. */
void btrcJavaThrow(JNIEnv* env, const char* className, const char* message);
/* A malloc'd UTF-8 copy of a Java string, or NULL with an exception pending:
 * IllegalArgumentException when it holds U+0000, which a BTRC string cannot
 * carry, or when it is too long for one. Unpaired surrogates become U+FFFD. */
char* btrcJavaCopyString(JNIEnv* env, jstring value);
/* Fills one RegisterNatives entry. `function` is the thunk, as a generic
 * function pointer: JNI stores it as void*, which ISO C cannot convert to. */
void btrcJavaNativeMethod(JNINativeMethod* entry, const char* name, const char* signature, void (*function)(void));
/* RegisterNatives on `owner`. A class that does not declare the natives the
 * class file did terminates as a metadata/runtime API mismatch; any other
 * failure returns JNI_ERR with its exception pending. */
jint btrcJavaRegisterNatives(JNIEnv* env, jclass owner, const JNINativeMethod* methods, jint count, const char* binaryName);
/* Registration holders not yet freed, for JavaVirtualMachine.liveNatives(). */
void btrcJavaNativesOpened(void);
void btrcJavaNativesClosed(void);
int btrcJavaLiveNatives(void);

#endif
