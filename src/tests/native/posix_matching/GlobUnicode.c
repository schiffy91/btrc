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

static int flags_match(const char *root)
{
	char pattern[4096];
	glob_t found = {0};
	found.gl_offs = 2;
	if (snprintf(pattern, sizeof pattern, "%s/ascii.txt", root) < 0) return 0;
	int rc = glob(pattern, GLOB_DOOFFS, NULL, &found);
	int ok = rc == 0 && found.gl_pathc == 1 && !found.gl_pathv[0] &&
	         !found.gl_pathv[1] && strcmp(found.gl_pathv[2], pattern) == 0 && !found.gl_pathv[3];
	snprintf(pattern, sizeof pattern, "%s/*.md", root);
	if (ok) ok = !glob(pattern, GLOB_APPEND | GLOB_DOOFFS | GLOB_NOSORT, NULL, &found) &&
	             found.gl_pathc == 2 && strstr(found.gl_pathv[3], "/skip.md") && !found.gl_pathv[4];
	globfree(&found);
	snprintf(pattern, sizeof pattern, "%s/*.none", root);
	if (ok) ok = glob(pattern, 0, NULL, &found) == GLOB_NOMATCH;
	if (ok) ok = glob(pattern, GLOB_NOCHECK | GLOB_NOESCAPE, NULL, &found) == 0 &&
	             found.gl_pathc == 1 && strcmp(found.gl_pathv[0], pattern) == 0;
	globfree(&found);
	snprintf(pattern, sizeof pattern, "%s\\/ascii.txt", root);
	if (ok) ok = !glob(pattern, 0, NULL, &found) && found.gl_pathc == 1 &&
	             !strchr(found.gl_pathv[0], '\\');
	globfree(&found);
	snprintf(pattern, sizeof pattern, "%s/\\", root);
	if (ok) ok = glob(pattern, 0, NULL, &found) == GLOB_NOMATCH;
	globfree(&found);
	if (ok) ok = !glob(root, GLOB_MARK, NULL, &found) && found.gl_pathc == 1 &&
	             found.gl_pathv[0][strlen(found.gl_pathv[0]) - 1] == '/';
	globfree(&found);
	return ok;
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
	if (!flags_match(pattern)) return fail("glob flags");
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
