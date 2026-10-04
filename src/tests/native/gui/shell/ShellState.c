/* Fixture-owned E47 checkpoint, not a stdlib restoration implementation.
 * A rename publishes the draft and anchor together; reopening never executes
 * the action journal. The harness compares the journal bytes across restarts. */
#define _POSIX_C_SOURCE 200809L
#include "ShellProbe.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

void shellStateCommit(const char *directory, int sequence) {
    char journal[4096];
    assert(snprintf(journal, sizeof journal, "%s/journal", directory) < (int)sizeof journal);
    FILE *sideEffects = fopen(journal, "a");
    assert(sideEffects);
    assert(fprintf(sideEffects, "commit %d\n", sequence) > 0);
    assert(fflush(sideEffects) == 0 && fsync(fileno(sideEffects)) == 0);
    assert(fclose(sideEffects) == 0);
}
void shellStateCheckpoint(const char *directory, const char *draft, double anchor, int commits) {
    char temporary[4096], checkpoint[4096];
    assert(snprintf(temporary, sizeof temporary, "%s/checkpoint.tmp", directory) < (int)sizeof temporary);
    assert(snprintf(checkpoint, sizeof checkpoint, "%s/checkpoint", directory) < (int)sizeof checkpoint);
    FILE *state = fopen(temporary, "w");
    assert(state);
    assert(fprintf(state, "%s\n%.0f\n%d\n", draft, anchor, commits) > 0);
    assert(fflush(state) == 0 && fsync(fileno(state)) == 0);
    assert(fclose(state) == 0 && rename(temporary, checkpoint) == 0);
}
static char draft[32];
static double anchor;
static int commits;
const char *shellStateDraft(void) { return draft; }
double shellStateAnchor(void) { return anchor; }
int shellStateCommits(void) { return commits; }
void shellStateLoad(const char *directory) {
    char checkpoint[4096];
    assert(snprintf(checkpoint, sizeof checkpoint, "%s/checkpoint", directory) < (int)sizeof checkpoint);
    FILE *state = fopen(checkpoint, "r");
    assert(state);
    assert(fscanf(state, "%31s\n%lf\n%d", draft, &anchor, &commits) == 3);
    assert(fclose(state) == 0);
    assert(strcmp(draft, "draft") == 0 && anchor > 0 && commits > 0);
}
