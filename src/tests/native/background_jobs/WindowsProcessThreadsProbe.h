#ifndef BTRC_TEST_WINDOWS_PROCESS_THREADS_PROBE_H
#define BTRC_TEST_WINDOWS_PROCESS_THREADS_PROBE_H

enum ProcessThreadFault {
    PROCESS_THREADS_REAL,
    PROCESS_THREADS_SNAPSHOT_FAILURE,
    PROCESS_THREADS_FIRST_FAILURE,
    PROCESS_THREADS_NEXT_FAILURE,
    PROCESS_THREADS_SHORT_FIRST,
    PROCESS_THREADS_SHORT_NEXT,
    PROCESS_THREADS_SHORT_VALID,
    PROCESS_THREADS_CLOSE_FAILURE,
    PROCESS_THREADS_EMPTY,
    PROCESS_THREADS_FOREIGN_ONLY
};
int process_threads_child_mode(int argc, char **argv);
void process_threads_start_held(void);
void process_threads_stop_held(void);
void process_threads_start_foreign(void);
void process_threads_stop_foreign(void);
void process_threads_reset(int fault);
int process_threads_snapshots(void);
int process_threads_closes(void);
int process_threads_next_calls(void);
int process_threads_bad_sizes(void);
int process_threads_live_snapshots(void);
int process_threads_foreign_seen(void);
#endif
