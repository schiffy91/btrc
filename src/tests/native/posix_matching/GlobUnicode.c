/* The Windows overlay's glob reads directories as UTF-16 and returns UTF-8,
   so names outside the active code page match and come back intact.

   Windows only: it creates its files with the UCRT's wide-character calls,
   which no narrow (code-page) API could spell, globs them through the
   overlay's <glob.h>, and checks the UTF-8 paths it gets back.
   test_windows_posix_overlay.py builds it for windows-x64 and windows-arm64;
   windows.yml's win32-native job runs it. */
#include <direct.h>
#include <glob.h>
#include <io.h>
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static const wchar_t *const NAMES[] = {L"ascii.txt", L"café.txt", L"日本.txt", L"skip.md"};
static const char *const EXPECTED[] = {"ascii.txt", "caf\xc3\xa9.txt", "\xe6\x97\xa5\xe6\x9c\xac.txt"};

static int fail(const char *what)
{
	printf("glob-unicode failed: %s\n", what);
	return 1;
}

int main(void)
{
	const wchar_t *temporary = _wgetenv(L"TEMP");
	if (!temporary) return fail("TEMP is unset");
	wchar_t directory[1024];
	if (swprintf(directory, 1024, L"%ls\\btrc-glob-ünicode-%d", temporary, (int)_getpid()) < 0) return fail("path");
	if (_wmkdir(directory) != 0) return fail("mkdir");
	for (size_t index = 0; index < sizeof NAMES / sizeof NAMES[0]; index++) {
		wchar_t path[1100];
		swprintf(path, 1100, L"%ls\\%ls", directory, NAMES[index]);
		FILE *file = _wfopen(path, L"wb");
		if (!file) return fail("create");
		fclose(file);
	}

	/* The pattern is UTF-8 with '/' separators, as on POSIX. */
	char pattern[4096];
	int length = WideCharToMultiByte(65001U, 0, directory, -1, pattern, (int)sizeof pattern - 8, NULL, NULL);
	if (length <= 0) return fail("utf-8");
	for (char *p = pattern; *p; p++) {
		if (*p == '\\') *p = '/';
	}
	size_t prefix = strlen(pattern) + 1;
	strcat(pattern, "/*.txt");

	glob_t found;
	int status = glob(pattern, 0, NULL, &found);
	int matched = status == 0 && found.gl_pathc == sizeof EXPECTED / sizeof EXPECTED[0];
	for (size_t index = 0; matched && index < found.gl_pathc; index++) {
		matched = strlen(found.gl_pathv[index]) > prefix && strcmp(found.gl_pathv[index] + prefix, EXPECTED[index]) == 0;
	}
	printf("glob-unicode status=%d count=%d matched=%d\n", status, status == 0 ? (int)found.gl_pathc : 0, matched);
	if (status == 0) globfree(&found);

	for (size_t index = 0; index < sizeof NAMES / sizeof NAMES[0]; index++) {
		wchar_t path[1100];
		swprintf(path, 1100, L"%ls\\%ls", directory, NAMES[index]);
		_wremove(path);
	}
	_wrmdir(directory);
	return matched ? 0 : 1;
}
