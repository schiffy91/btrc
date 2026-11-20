#ifndef BTRC_STDLIB_BACKGROUNDJOBS_APPLE_PROCESS_THREADS_H
#define BTRC_STDLIB_BACKGROUNDJOBS_APPLE_PROCESS_THREADS_H

/* Mach lists a task's threads on every Apple system (libproc.h, which also
 * counts them, is not in the iOS SDK). The list and the port rights in it are
 * the caller's to give back. */
#include <mach/mach.h>

static inline int btrcProcessThreadCount(void) {
	thread_act_array_t threads = NULL;
	mach_msg_type_number_t count = 0;
	if (task_threads(mach_task_self(), &threads, &count) != KERN_SUCCESS) { return -1; }
	for (mach_msg_type_number_t index = 0; index < count; index++) { mach_port_deallocate(mach_task_self(), threads[index]); }
	vm_deallocate(mach_task_self(), (vm_address_t)threads, (vm_size_t)count * sizeof(thread_act_t));
	return (int)count;
}

#endif
