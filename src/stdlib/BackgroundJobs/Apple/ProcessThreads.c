/* Mach lists a task's threads. iOS and iPadOS count them this way: libproc.h,
 * which macOS counts them with, is not in the iOS SDK. The list and the port
 * rights in it are the caller's to give back. ProcessThreadsProvider.btrc
 * imports this file on those systems. */
#include <mach/mach.h>

int btrcProcessThreadCount(void) {
	thread_act_array_t threads = NULL;
	mach_msg_type_number_t count = 0;
	if (task_threads(mach_task_self(), &threads, &count) != KERN_SUCCESS) { return -1; }
	for (mach_msg_type_number_t index = 0; index < count; index++) { mach_port_deallocate(mach_task_self(), threads[index]); }
	vm_deallocate(mach_task_self(), (vm_address_t)threads, (vm_size_t)count * sizeof(thread_act_t));
	return (int)count;
}
