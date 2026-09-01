#ifndef BACKGROUND_JOB_PROBE_H
#define BACKGROUND_JOB_PROBE_H

enum {
    JOB_PROBE_COMPLETE = 0,
    JOB_PROBE_HOLD = 1,
    JOB_PROBE_CANCEL = 2,
    JOB_PROBE_FAIL = 3,
    JOB_PROBE_THROW = 4,
};

void job_probe_reset(void);
void job_probe_release(void);
int job_probe_released(void);
void job_probe_mark_started(int identity);
void job_probe_mark_finished(int identity);
void job_probe_record_disposal(int identity);
int job_probe_started(int identity);
int job_probe_finished(int identity);
int job_probe_runs(int identity);
int job_probe_disposals(int identity);
void job_probe_yield(void);

#endif
