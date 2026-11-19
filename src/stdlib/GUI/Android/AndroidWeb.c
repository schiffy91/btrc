/* The Android shim's web view; ../Shim/ShimWeb.h is the contract. The view
 * is the system's WebView, owned by dev.btrc.shim.ShimWeb. */
#include "../Shim/ShimWeb.h"
#include "AndroidShimPrivate.h"

enum { BTRC_ANDROID_WEB = 11 };

/* The program's thread runs inside a method of the application's own
 * classes, so its lookups find them. */
static jclass btrcAndroidWeb(JNIEnv* env) {
	static jclass class;
	if (class == NULL) {
		jclass found = (*env)->FindClass(env, "dev/btrc/shim/ShimWeb");
		if (btrcAndroidFailed(env) || found == NULL) { abort(); }
		class = (*env)->NewGlobalRef(env, found);
	}
	return class;
}

static void btrcAndroidWebText(const char* name, jmethodID* method, BtrcShimControl* web, const char* text) {
	JNIEnv* env = btrcAndroidEnv();
	(*env)->PushLocalFrame(env, 16);
	jclass class = btrcAndroidWeb(env);
	if (*method == NULL) { *method = btrcAndroidMethod(env, class, name, "(ILjava/lang/String;)V"); }
	(*env)->CallStaticVoidMethod(env, class, *method, (jint)btrcAndroidControlHandle(web), btrcAndroidString(env, text));
	btrcAndroidFailed(env);
	(*env)->PopLocalFrame(env, NULL);
}

BtrcShimControl* btrcShimWebCreate(unsigned int id) {
	BtrcShimControl* control = btrcAndroidControlNew(BTRC_ANDROID_WEB, id, "", "", false);
	if (control == NULL) { btrcAndroidFail("the system has no web view"); }
	return control;
}

void btrcShimWebServeDirectory(BtrcShimControl* web, const char* directory) { static jmethodID method; btrcAndroidWebText("serveDirectory", &method, web, directory); }

void btrcShimWebServeFiles(BtrcShimControl* web) {
	static jmethodID method;
	JNIEnv* env = btrcAndroidEnv();
	(*env)->PushLocalFrame(env, 16);
	jclass class = btrcAndroidWeb(env);
	if (method == NULL) { method = btrcAndroidMethod(env, class, "serveFiles", "(I)V"); }
	(*env)->CallStaticVoidMethod(env, class, method, (jint)btrcAndroidControlHandle(web));
	btrcAndroidFailed(env);
	(*env)->PopLocalFrame(env, NULL);
}

void btrcShimWebServeFile(BtrcShimControl* web, const char* path, const unsigned char* bytes, unsigned long long length) {
	static jmethodID method;
	JNIEnv* env = btrcAndroidEnv();
	(*env)->PushLocalFrame(env, 16);
	jclass class = btrcAndroidWeb(env);
	if (method == NULL) { method = btrcAndroidMethod(env, class, "serveFile", "(ILjava/lang/String;[B)V"); }
	jbyteArray content = (*env)->NewByteArray(env, (jsize)length);
	if (content != NULL) {
		if (length > 0u) { (*env)->SetByteArrayRegion(env, content, 0, (jsize)length, (const jbyte*)bytes); }
		(*env)->CallStaticVoidMethod(env, class, method, (jint)btrcAndroidControlHandle(web), btrcAndroidString(env, path), content);
	}
	btrcAndroidFailed(env);
	(*env)->PopLocalFrame(env, NULL);
}

void btrcShimWebAllowOrigin(BtrcShimControl* web, const char* origin) { static jmethodID method; btrcAndroidWebText("allowOrigin", &method, web, origin); }

void btrcShimWebLoad(BtrcShimControl* web, const char* entryPath) { static jmethodID method; btrcAndroidWebText("load", &method, web, entryPath); }

void btrcShimWebPost(BtrcShimControl* web, const char* json) { static jmethodID method; btrcAndroidWebText("post", &method, web, json); }
