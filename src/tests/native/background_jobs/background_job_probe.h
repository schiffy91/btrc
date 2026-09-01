#ifndef BACKGROUND_JOB_PROBE_H
#define BACKGROUND_JOB_PROBE_H

enum {
    JOB_PROBE_COMPLETE = 0,
    JOB_PROBE_HOLD = 1,
    JOB_PROBE_CANCEL = 2,
    JOB_PROBE_FAIL = 3,
};

void job_probe_reset(void);
void* job_probe_create(int identity, int behavior);
int job_probe_run(void* context, void* cancellation);
void job_probe_dispose(void* context);
void job_probe_release(void);
int job_probe_started(int identity);
int job_probe_finished(int identity);
int job_probe_runs(int identity);
int job_probe_disposals(int identity);
int job_probe_identity(void* context);
void job_probe_yield(void);

#endif
