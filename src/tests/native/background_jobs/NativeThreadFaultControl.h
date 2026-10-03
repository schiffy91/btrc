#ifndef BTRC_TEST_NATIVE_THREAD_FAULT_CONTROL_H
#define BTRC_TEST_NATIVE_THREAD_FAULT_CONTROL_H

/* The controls BackgroundJobsFailures.btrc and NativeWorkerFailures.btrc bind
 * through their harness-written [[native.bindings]]; NativeThreadFaults.c implements them. Kept apart from
 * NativeThreadFaults.h, whose pthread macros the implementation cannot see. */
typedef enum ThreadFault {
    FAULT_MUTEX_INIT,
    FAULT_COND_INIT,
    FAULT_CREATE,
    FAULT_JOIN,
    FAULT_MUTEX_DESTROY,
    FAULT_COND_DESTROY,
    FAULT_OPERATION_COUNT
} ThreadFault;

void job_fault_reset(void);
void job_fault_at(int operation, int call);
int job_fault_calls(int operation);
int job_fault_live_threads(void);
int job_fault_disposals(void);
void job_fault_dispose(void);

#endif
