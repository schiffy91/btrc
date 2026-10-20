#ifndef BTRC_MACOS_SHELL_PROBE_H
#define BTRC_MACOS_SHELL_PROBE_H
#include "ShellProbe.h"

/* Two successive journey turns exercise the public field-editor caret path. */
int shellProbeCaretBegin(void);
int shellProbeCaretFinish(void);
#endif
