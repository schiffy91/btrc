#import "btrc_app.h"
#import "btrc_app_directory_picker_internal.h"

#import <Cocoa/Cocoa.h>

#include <string.h>

int btrc_app_platform_choose_directory(const char* title, const char* initial_directory, char* selected_directory, size_t selected_directory_capacity, int* error_out) {
	if (error_out) { *error_out = BTRC_APP_ERROR_NONE; }
	if (selected_directory && selected_directory_capacity > 0) { selected_directory[0] = '\0'; }
	if (!title || title[0] == '\0' || !initial_directory || !selected_directory || selected_directory_capacity == 0 || !error_out) {
		if (error_out) { *error_out = BTRC_APP_ERROR_INVALID_ARGUMENT; }
		return BTRC_APP_DIRECTORY_PICKER_FAILED;
	}
	if (![NSThread isMainThread]) {
		*error_out = BTRC_APP_ERROR_NOT_MAIN_THREAD;
		return BTRC_APP_DIRECTORY_PICKER_FAILED;
	}

	@autoreleasepool {
		NSString* native_title = [NSString stringWithUTF8String:title];
		if (!native_title) {
			*error_out = BTRC_APP_ERROR_INVALID_ARGUMENT;
			return BTRC_APP_DIRECTORY_PICKER_FAILED;
		}
		NSOpenPanel* panel = [NSOpenPanel openPanel];
		if (!panel) {
			*error_out = BTRC_APP_ERROR_BACKEND_UNAVAILABLE;
			return BTRC_APP_DIRECTORY_PICKER_FAILED;
		}
		panel.title = native_title;
		panel.prompt = @"Choose";
		panel.canChooseDirectories = YES;
		panel.canChooseFiles = NO;
		panel.allowsMultipleSelection = NO;
		panel.canCreateDirectories = YES;
		panel.resolvesAliases = YES;
		if (initial_directory[0] != '\0') {
			NSString* native_initial_directory = [NSString stringWithUTF8String:initial_directory];
			if (!native_initial_directory) {
				*error_out = BTRC_APP_ERROR_INVALID_ARGUMENT;
				return BTRC_APP_DIRECTORY_PICKER_FAILED;
			}
			panel.directoryURL = [NSURL fileURLWithPath:native_initial_directory isDirectory:YES];
		}

		NSModalResponse response = [panel runModal];
		if (response == NSModalResponseCancel) { return BTRC_APP_DIRECTORY_PICKER_CANCELLED; }
		if (response != NSModalResponseOK || panel.URL == nil) {
			*error_out = BTRC_APP_ERROR_INTERNAL;
			return BTRC_APP_DIRECTORY_PICKER_FAILED;
		}
		const char* path = panel.URL.fileSystemRepresentation;
		if (!path) {
			*error_out = BTRC_APP_ERROR_INTERNAL;
			return BTRC_APP_DIRECTORY_PICKER_FAILED;
		}
		size_t length = strlen(path);
		if (length >= selected_directory_capacity) {
			*error_out = BTRC_APP_ERROR_INTERNAL;
			return BTRC_APP_DIRECTORY_PICKER_FAILED;
		}
		memcpy(selected_directory, path, length + 1);
		return BTRC_APP_DIRECTORY_PICKER_SELECTED;
	}
}
