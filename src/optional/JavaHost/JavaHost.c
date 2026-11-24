/* HotSpot uses the same reference counts, thread-local environment and class
 * cache as ART. This translation unit also owns the JDK invocation entry. */
#define BTRC_JAVA_DESKTOP_HOST 1
#include "../../stdlib/Java/JavaRuntime.h"
#include "JNI.h"

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
}
