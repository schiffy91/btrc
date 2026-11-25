#ifndef BTRC_MACOS_APPKIT_FILE_PICKER_H
#define BTRC_MACOS_APPKIT_FILE_PICKER_H

#include <stdbool.h>

typedef struct BtrcMacFilePickerResult BtrcMacFilePickerResult;

/* mode: 1=OPEN_FILE, 2=OPEN_FILES, 3=OPEN_DIRECTORY, 4=OPEN_DIRECTORIES,
 * 5=OPEN_FILES_AND_DIRECTORIES, 6=SAVE_FILE.
 * state: 1=selected, 2=cancelled, 3=failed, 4=unavailable. */
BtrcMacFilePickerResult* btrcMacFilePickerRun(
	int mode,
	const char* title,
	const char* prompt,
	const char* initialDirectory,
	const char* defaultName,
	const char* filters,
	bool canCreateDirectories,
	int maximumPathBytes
);
int btrcMacFilePickerState(const BtrcMacFilePickerResult* result);
int btrcMacFilePickerPathCount(const BtrcMacFilePickerResult* result);
const char* btrcMacFilePickerPathAt(const BtrcMacFilePickerResult* result, int index);
const char* btrcMacFilePickerError(const BtrcMacFilePickerResult* result);
void btrcMacFilePickerRelease(BtrcMacFilePickerResult* result);

#endif
