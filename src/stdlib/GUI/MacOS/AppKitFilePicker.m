#import "AppKitFilePicker.h"
#import <AppKit/AppKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include <stdlib.h>
#include <string.h>

struct BtrcMacFilePickerResult {
	int state;
	char** paths;
	int pathCount;
	char* error;
};

static BtrcMacFilePickerResult* makeResult(int state, const char* error) {
	BtrcMacFilePickerResult* result = calloc(1, sizeof *result);
	if (result == NULL) { return NULL; }
	result->state = state;
	if (error != NULL && error[0] != '\0') { result->error = strdup(error); }
	return result;
}

static NSString* utf8String(const char* text) {
	if (text == NULL) { return nil; }
	return [[NSString alloc] initWithUTF8String:text];
}

static NSArray<UTType*>* buildAllowedTypes(const char* filters, bool includeFolders) {
	if (filters == NULL || filters[0] == '\0') { return nil; }
	NSMutableArray<UTType*>* types = [[NSMutableArray alloc] init];
	NSMutableSet<NSString*>* seen = [[NSMutableSet alloc] init];
	const char* cursor = filters;
	while (*cursor != '\0') {
		const char* lineEnd = strchr(cursor, '\n');
		size_t lineLen = lineEnd == NULL ? strlen(cursor) : (size_t)(lineEnd - cursor);
		const char* tab = memchr(cursor, '\t', lineLen);
		if (tab != NULL) {
			const char* extStart = tab + 1;
			const char* extLimit = cursor + lineLen;
			while (extStart < extLimit) {
				const char* comma = memchr(extStart, ',', (size_t)(extLimit - extStart));
				size_t extLen = comma == NULL ? (size_t)(extLimit - extStart) : (size_t)(comma - extStart);
				if (extLen > 0) {
					NSString* ext = [[NSString alloc] initWithBytes:extStart length:extLen encoding:NSUTF8StringEncoding];
					if (ext != nil) {
						NSString* lower = [ext lowercaseString];
						if (![seen containsObject:lower]) {
							[seen addObject:lower];
							UTType* type = [UTType typeWithFilenameExtension:lower];
							if (type != nil) { [types addObject:type]; }
						}
						[ext release];
					}
				}
				if (comma == NULL) { break; }
				extStart = comma + 1;
			}
		}
		if (lineEnd == NULL) { break; }
		cursor = lineEnd + 1;
	}
	[seen release];
	if ([types count] == 0) {
		[types release];
		return nil;
	}
	if (includeFolders && ![types containsObject:UTTypeFolder]) {
		[types addObject:UTTypeFolder];
	}
	return types;
}

static bool extractPath(NSURL* url, int maximumPathBytes, char** outPath) {
	if (url == nil || maximumPathBytes <= 0 || outPath == NULL) { return false; }
	char* buffer = calloc((size_t)maximumPathBytes, 1);
	if (buffer == NULL) { return false; }
	if (![url getFileSystemRepresentation:buffer maxLength:(NSUInteger)maximumPathBytes] || buffer[0] == '\0') {
		free(buffer);
		return false;
	}
	*outPath = buffer;
	return true;
}

BtrcMacFilePickerResult* btrcMacFilePickerRun(
	int mode,
	const char* title,
	const char* prompt,
	const char* initialDirectory,
	const char* defaultName,
	const char* filters,
	bool canCreateDirectories,
	int maximumPathBytes
) {
	if (title == NULL || title[0] == '\0' || prompt == NULL || prompt[0] == '\0' || maximumPathBytes <= 0) {
		return makeResult(3, "invalid file picker request or configuration");
	}
	if (mode < 1 || mode > 6) {
		return makeResult(3, "invalid file picker mode");
	}
	@autoreleasepool {
		@try {
			NSString* nsTitle = utf8String(title);
			NSString* nsPrompt = utf8String(prompt);
			if (nsTitle == nil || nsPrompt == nil) {
				[nsTitle release];
				[nsPrompt release];
				return makeResult(3, "file picker text is not valid UTF-8 or could not be allocated");
			}
			NSSavePanel* panel = nil;
			NSOpenPanel* openPanel = nil;
			bool allowsMultiple = (mode == 2 || mode == 4 || mode == 5);
			if (mode == 6) {
				panel = [NSSavePanel savePanel];
			} else {
				openPanel = [NSOpenPanel openPanel];
				panel = openPanel;
			}
			if (panel == nil) {
				[nsTitle release];
				[nsPrompt release];
				return makeResult(4, "file picker is unavailable");
			}
			[panel setTitle:nsTitle];
			[panel setPrompt:nsPrompt];
			[panel setCanCreateDirectories:canCreateDirectories ? YES : NO];
			[nsTitle release];
			[nsPrompt release];

			if (filters != NULL && filters[0] != '\0') {
				NSArray<UTType*>* allowedTypes = buildAllowedTypes(filters, mode == 5);
				if (allowedTypes != nil) {
					[panel setAllowedContentTypes:allowedTypes];
					[allowedTypes release];
				}
			}

			if (openPanel != nil) {
				[openPanel setCanChooseFiles:(mode == 1 || mode == 2 || mode == 5) ? YES : NO];
				[openPanel setCanChooseDirectories:(mode == 3 || mode == 4 || mode == 5) ? YES : NO];
				[openPanel setAllowsMultipleSelection:allowsMultiple ? YES : NO];
				[openPanel setResolvesAliases:YES];
			} else if (defaultName != NULL && defaultName[0] != '\0') {
				NSString* nsDefaultName = utf8String(defaultName);
				if (nsDefaultName == nil) { return makeResult(3, "default filename is not valid UTF-8"); }
				[panel setNameFieldStringValue:nsDefaultName];
				[nsDefaultName release];
			}

			if (initialDirectory != NULL && initialDirectory[0] != '\0') {
				NSString* nsInitial = utf8String(initialDirectory);
				if (nsInitial == nil) { return makeResult(3, "initial directory is not valid UTF-8"); }
				NSURL* dirURL = [NSURL fileURLWithPath:nsInitial isDirectory:YES];
				[nsInitial release];
				if (dirURL == nil) { return makeResult(3, "initial directory could not be represented"); }
				[panel setDirectoryURL:dirURL];
			}

			NSModalResponse response = [panel runModal];
			if (response == NSModalResponseCancel || response == NSModalResponseAbort) {
				return makeResult(2, NULL);
			}
			if (response != NSModalResponseOK) {
				return makeResult(3, "file picker returned an unknown response");
			}

			NSMutableArray<NSURL*>* urls = [[NSMutableArray alloc] init];
			if (openPanel != nil && allowsMultiple) {
				NSArray<NSURL*>* selected = [openPanel URLs];
				if (selected != nil) { [urls addObjectsFromArray:selected]; }
			} else {
				NSURL* selected = [panel URL];
				if (selected != nil) { [urls addObject:selected]; }
			}
			NSUInteger count = [urls count];
			if (count == 0) {
				[urls release];
				return makeResult(3, "file picker selected no path");
			}
			if (!allowsMultiple && count > 1) {
				[urls release];
				return makeResult(3, "file picker returned multiple paths for a single-selection request");
			}

			BtrcMacFilePickerResult* out = makeResult(1, NULL);
			if (out == NULL) {
				[urls release];
				return NULL;
			}
			out->paths = calloc(count, sizeof(char*));
			if (out->paths == NULL) {
				[urls release];
				btrcMacFilePickerRelease(out);
				return makeResult(3, "cannot allocate file picker result list");
			}
			for (NSUInteger i = 0; i < count; i++) {
				char* path = NULL;
				if (!extractPath([urls objectAtIndex:i], maximumPathBytes, &path)) {
					[urls release];
					btrcMacFilePickerRelease(out);
					return makeResult(3, "selected path exceeds the path buffer or could not be represented");
				}
				out->paths[out->pathCount++] = path;
			}
			[urls release];
			return out;
		} @catch (NSException* exception) {
			const char* reason = [[exception reason] UTF8String];
			return makeResult(3, reason != NULL && reason[0] != '\0' ? reason : "file picker raised a native exception");
		}
	}
}

int btrcMacFilePickerState(const BtrcMacFilePickerResult* result) { return result == NULL ? 3 : result->state; }

int btrcMacFilePickerPathCount(const BtrcMacFilePickerResult* result) { return result == NULL ? 0 : result->pathCount; }

const char* btrcMacFilePickerPathAt(const BtrcMacFilePickerResult* result, int index) {
	if (result == NULL || index < 0 || index >= result->pathCount || result->paths[index] == NULL) { return ""; }
	return result->paths[index];
}

const char* btrcMacFilePickerError(const BtrcMacFilePickerResult* result) {
	if (result == NULL || result->error == NULL) { return ""; }
	return result->error;
}

void btrcMacFilePickerRelease(BtrcMacFilePickerResult* result) {
	if (result == NULL) { return; }
	for (int i = 0; i < result->pathCount; i++) { free(result->paths[i]); }
	free(result->paths);
	free(result->error);
	free(result);
}
