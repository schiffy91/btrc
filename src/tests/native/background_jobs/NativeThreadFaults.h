#ifndef BTRC_TEST_NATIVE_THREAD_FAULTS_H
#define BTRC_TEST_NATIVE_THREAD_FAULTS_H

#include <pthread.h>

/* Test-only interception: successful operations always use real SDK threads. */
int job_fault_mutex_init(pthread_mutex_t *, const pthread_mutexattr_t *);
int job_fault_cond_init(pthread_cond_t *, const pthread_condattr_t *);
int job_fault_create(pthread_t *, const pthread_attr_t *, void *(*)(void *), void *);
int job_fault_join(pthread_t, void **);
int job_fault_mutex_destroy(pthread_mutex_t *);
int job_fault_cond_destroy(pthread_cond_t *);

#define pthread_mutex_init job_fault_mutex_init
#define pthread_cond_init job_fault_cond_init
#define pthread_create job_fault_create
#define pthread_join job_fault_join
#define pthread_mutex_destroy job_fault_mutex_destroy
#define pthread_cond_destroy job_fault_cond_destroy

#endif
