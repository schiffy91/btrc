#ifndef BTRC_TEST_PROCESS_THREAD_FAULT_CONTROL_H
#define BTRC_TEST_PROCESS_THREAD_FAULT_CONTROL_H

enum ProcessThreadFault {
    PROCESS_THREADS_NORMAL,
    PROCESS_THREADS_OPEN_ERROR,
    PROCESS_THREADS_INITIAL_ERROR,
    PROCESS_THREADS_PARTIAL_ERROR,
    PROCESS_THREADS_STALE_ERRNO
};
void process_threads_fault_reset(int mode);
int process_threads_fault_entries(void);
int process_threads_fault_closes(void);
int process_threads_fault_live(void);
#endif
