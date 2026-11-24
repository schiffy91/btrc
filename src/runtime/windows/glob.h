/* POSIX directory expansion for the MinGW targets. Names are read through
   the wide UCRT directory API; the caller sees UTF-8 paths. */
#pragma once

#include <stddef.h>

#include "fnmatch.h"

typedef struct {
	size_t gl_pathc;
	char **gl_pathv;
	size_t gl_offs;
	int __dummy1;
	void *__dummy2[5];
} glob_t;

#define GLOB_ERR      0x01
#define GLOB_MARK     0x02
#define GLOB_NOSORT   0x04
#define GLOB_DOOFFS   0x08
#define GLOB_NOCHECK  0x10
#define GLOB_APPEND   0x20
#define GLOB_NOESCAPE 0x40

#define GLOB_NOSPACE 1
#define GLOB_ABORTED 2
#define GLOB_NOMATCH 3

#include <errno.h>
#include <io.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "btrc_win_realpath.h"

typedef struct {
	char **items;
	size_t count;
	size_t capacity;
} btrc_win_path_list;

static inline void btrc_win_paths_clear(btrc_win_path_list *list)
{
	for (size_t i = 0; i < list->count; ++i) free(list->items[i]);
	free(list->items);
	memset(list, 0, sizeof *list);
}

/* Take ownership even when there is no memory to extend the list. */
static inline int btrc_win_paths_push(btrc_win_path_list *list, char *path)
{
	if (!path) return GLOB_NOSPACE;
	if (list->count == list->capacity) {
		if (list->capacity > SIZE_MAX / (2 * sizeof *list->items)) {
			free(path);
			return GLOB_NOSPACE;
		}
		size_t size = list->capacity ? list->capacity * 2 : 8;
		char **next = (char **)realloc(list->items, size * sizeof *next);
		if (!next) {
			free(path);
			return GLOB_NOSPACE;
		}
		list->items = next;
		list->capacity = size;
	}
	list->items[list->count++] = path;
	return 0;
}

static inline char *btrc_win_path_concat(const char *prefix, const char *name, size_t length)
{
	size_t n = strlen(prefix);
	if (length > SIZE_MAX - 1 - n) return NULL;
	char *path = (char *)malloc(n + length + 1);
	if (path) {
		memcpy(path, prefix, n);
		memcpy(path + n, name, length);
		path[n + length] = 0;
	}
	return path;
}

static inline int btrc_win_glob_error(const char *path, int flags, int (*onerror)(const char *, int))
{
	int error = errno;
	if (error == ENOMEM) return GLOB_NOSPACE;
	if (error == ENOTDIR || error == ENOENT) return 0;
	return ((onerror && onerror(*path ? path : ".", error)) || (flags & GLOB_ERR)) ? GLOB_ABORTED : 0;
}

/* A slash in the pattern requires an actual directory. Literal components
   go straight to the filesystem, retaining Windows' case-insensitive lookup. */
static inline int btrc_win_glob_path(btrc_win_path_list *output, const char *prefix, const char *name,
                                    size_t slashes, int flags, int (*onerror)(const char *, int))
{
	size_t length = strlen(name);
	char *path = btrc_win_path_concat(prefix, name, length);
	if (!path) return GLOB_NOSPACE;
	wchar_t *wide = btrc_win_path_to_wide(path);
	if (!wide) {
		free(path);
		return errno == ENOMEM ? GLOB_NOSPACE : 0;
	}
	unsigned long attributes = GetFileAttributesW(wide);
	free(wide);
	if (attributes == 0xffffffffUL) {
		btrc_win_path_error(BTRC_WIN_GET_LAST_ERROR());
		int error = btrc_win_glob_error(path, flags, onerror);
		free(path);
		return error;
	}
	if (!(attributes & 0x10UL) && slashes) { free(path); return 0; }
	size_t n = strlen(path);
	if (!slashes && (flags & GLOB_MARK) && (attributes & 0x10UL) && n && path[n - 1] != '/') slashes = 1;
	if (slashes) {
		char *marked = slashes <= SIZE_MAX - 1 - n ? (char *)realloc(path, n + slashes + 1) : NULL;
		if (!marked) { free(path); return GLOB_NOSPACE; }
		path = marked;
		memset(path + n, '/', slashes);
		path[n + slashes] = 0;
	}
	return btrc_win_paths_push(output, path);
}

static inline int btrc_win_glob_scan(btrc_win_path_list *output, const char *prefix, const char *part,
                                    size_t slashes, int flags, int (*onerror)(const char *, int))
{
	char *query = btrc_win_path_concat(prefix, "*", 1);
	if (!query) return GLOB_NOSPACE;
	wchar_t *wide = btrc_win_path_to_wide(query);
	free(query);
	if (!wide) return errno == ENOMEM ? GLOB_NOSPACE : 0;
	struct _wfinddata64_t file;
	intptr_t dir = _wfindfirst64(wide, &file);
	free(wide);
	if (dir == -1 && errno != ENOENT) return btrc_win_glob_error(prefix, flags, onerror);
	int match_flags = FNM_PERIOD | ((flags & GLOB_NOESCAPE) ? FNM_NOESCAPE : 0);
	int result = 0;
	/* Windows omits these entries at some roots; POSIX glob can match them. */
	if (*part == '.') {
		const char *dots[2] = {".", ".."};
		for (size_t i = 0; !result && i < 2; ++i) {
			if (!fnmatch(part, dots[i], match_flags))
				result = btrc_win_glob_path(output, prefix, dots[i], slashes, flags, onerror);
		}
	}
	if (dir == -1) return result;
	while (!result) {
		if (!(file.name[0] == L'.' && (!file.name[1] || (file.name[1] == L'.' && !file.name[2])))) {
			char *name = btrc_win_path_to_utf8(file.name);
			if (name) {
				if (!fnmatch(part, name, match_flags))
					result = btrc_win_glob_path(output, prefix, name, slashes, flags, onerror);
				free(name);
			} else if (errno == ENOMEM) result = GLOB_NOSPACE;
		}
		if (_wfindnext64(dir, &file) != 0) {
			if (!result && errno != ENOENT) result = btrc_win_glob_error(prefix, flags, onerror);
			break;
		}
	}
	_findclose(dir);
	return result;
}

static inline int btrc_win_glob_compare(const void *left, const void *right)
{
	return strcmp(*(char *const *)left, *(char *const *)right);
}

static inline int btrc_win_glob(const char *restrict pattern, int flags,
                               int (*onerror)(const char *, int), glob_t *restrict found)
{
	if (!(flags & GLOB_APPEND)) {
		found->gl_pathv = NULL;
		found->gl_pathc = 0;
		if (!(flags & GLOB_DOOFFS)) found->gl_offs = 0;
	}
	btrc_win_path_list paths = {NULL, 0, 0};
	const char *p = pattern;
	/* Preserve drive-relative (C:x), rooted and leading double-slash paths. */
	if (btrc_win_fold((unsigned char)*p) >= 'a' && btrc_win_fold((unsigned char)*p) <= 'z' && p[1] == ':') p += 2;
	/* A UNC share is a filesystem root. A bare server name cannot be
	   stat'ed on Windows, so start walking after the share. */
	if (p == pattern && p[0] == '/' && p[1] == '/' && p[2] && p[2] != '/') {
		const char *server_end = p + 2 + strcspn(p + 2, "/");
		if (*server_end && server_end[1] && server_end[1] != '/') {
			const char *share = server_end + 1;
			p = share + strcspn(share, "/");
		}
	}
	while (*p == '/') ++p;
	int result;
	if (!*p) {
		result = *pattern ? btrc_win_glob_path(&paths, "", pattern, 0, flags, onerror) : 0;
	} else {
		result = btrc_win_paths_push(&paths, btrc_win_path_concat("", pattern, (size_t)(p - pattern)));
	}
	while (*p && paths.count && !result) {
		const char *end = p + strcspn(p, "/");
		const char *next = end;
		while (*next == '/') ++next;
		char *part = btrc_win_path_concat("", p, (size_t)(end - p));
		if (!part) { result = GLOB_NOSPACE; break; }
		int magic = 0, incomplete_escape = 0;
		for (char *s = part; *s; ++s) {
			if (!(flags & GLOB_NOESCAPE) && *s == '\\') {
				if (s[1]) ++s;
				else if (*end) *s = 0; /* the separator itself was escaped */
				else incomplete_escape = 1;
			} else if (*s == '*' || *s == '?') magic = 1;
			else if (*s == '[') {
				const unsigned char *after = (const unsigned char *)s + 1;
				btrc_win_byte_set set = {{0}};
				if (btrc_win_parse_list(&after, &set, 1, 0, NULL) == btrc_win_list_ok) {
					magic = 1;
					s = (char *)after - 1;
				}
			}
		}
		if (!magic && !(flags & GLOB_NOESCAPE)) {
			char *out = part;
			for (const char *s = part; *s; ++s) {
				if (*s == '\\' && s[1]) ++s;
				*out++ = *s;
			}
			*out = 0;
		}
		btrc_win_path_list expanded = {NULL, 0, 0};
		for (size_t i = 0; !incomplete_escape && !result && i < paths.count; ++i) {
			int component_flags = *next ? (flags & ~GLOB_MARK) : flags;
			if (magic) result = btrc_win_glob_scan(&expanded, paths.items[i], part,
			                                       (size_t)(next - end), component_flags, onerror);
			else result = btrc_win_glob_path(&expanded, paths.items[i], part,
			                                 (size_t)(next - end), component_flags, onerror);
		}
		free(part);
		btrc_win_paths_clear(&paths);
		paths = expanded;
		p = next;
	}
	if (!result && !paths.count) {
		if (flags & GLOB_NOCHECK) result = btrc_win_paths_push(&paths, btrc_win_path_concat("", pattern, strlen(pattern)));
		else result = GLOB_NOMATCH;
	}
	if (!result) {
		size_t start = found->gl_offs;
		size_t max = SIZE_MAX / sizeof(char *);
		if (start >= max || found->gl_pathc >= max - start || paths.count >= max - start - found->gl_pathc)
			result = GLOB_NOSPACE;
		else {
			start += found->gl_pathc;
			int first = found->gl_pathv == NULL;
			char **items = (char **)realloc(found->gl_pathv, (start + paths.count + 1) * sizeof *items);
			if (!items) result = GLOB_NOSPACE;
			else {
				if (first) for (size_t i = 0; i < start; ++i) items[i] = NULL;
				if (!(flags & GLOB_NOSORT)) qsort(paths.items, paths.count, sizeof *items, btrc_win_glob_compare);
				memcpy(items + start, paths.items, paths.count * sizeof *items);
				items[start + paths.count] = NULL;
				found->gl_pathv = items;
				found->gl_pathc += paths.count;
				paths.count = 0;
			}
		}
	}
	btrc_win_paths_clear(&paths);
	return result;
}

static inline void btrc_win_globfree(glob_t *found)
{
	for (size_t i = 0; i < found->gl_pathc; ++i) free(found->gl_pathv[found->gl_offs + i]);
	free(found->gl_pathv);
	found->gl_pathv = NULL;
	found->gl_pathc = 0;
}

#define glob btrc_win_glob
#define globfree btrc_win_globfree
