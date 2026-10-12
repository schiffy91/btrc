#ifndef BTRC_TEST_PROCESS_THREAD_FAULTS_H
#define BTRC_TEST_PROCESS_THREAD_FAULTS_H

/* Like NativeThreadFaults.h, fix the feature set before the generated prelude. */
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include <dirent.h>
#undef _DEFAULT_SOURCE

DIR *process_threads_fault_opendir(const char *path);
struct dirent *process_threads_fault_readdir(DIR *directory);
int process_threads_fault_closedir(DIR *directory);
#define opendir process_threads_fault_opendir
#define readdir process_threads_fault_readdir
#define closedir process_threads_fault_closedir
#endif
