/* btrc: musl 1.2.5 src/regex/glob.c, adapted for Windows (MinGW-w64/UCRT).
   Every change is marked "btrc:":
   - directories are read with UCRT's UTF-16 _wfindfirst64/_wfindnext64
     (FindFirstFileExW), and each name is matched and returned as UTF-8; a
     name with no UTF-8 form (an unpaired surrogate) is skipped;
   - "." and ".." are listed first, as readdir lists them, also at a drive
     root, where FindFirstFile omits them;
   - existence and the GLOB_MARK type come from GetFileAttributesW, which,
     like lstat, describes a final reparse point itself;
   - the path buffer is on the heap: MinGW's PATH_MAX is 260;
   - the GNU extensions GLOB_PERIOD and GLOB_TILDE are removed. */
#include <glob.h>
#include <fnmatch.h>
#include <io.h>
#include <limits.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <wchar.h>

#include "../btrc_win_realpath.h" /* btrc: UTF-8 to UTF-16 path conversion */

/* btrc: the longest path, in UTF-8 bytes, a Win32 path of 32767 UTF-16 units
   can need. */
#define PATH_BUFFER_MAX 98304

/* btrc: the readdir d_type values do_glob distinguishes. */
#define DT_UNKNOWN 0
#define DT_DIR 4
#define DT_REG 8

/* btrc: GetFileAttributesW is declared by ../btrc_win_realpath.h. */
#define INVALID_ATTRIBUTES ((unsigned long)-1)
#define ATTRIBUTE_DIRECTORY 0x00000010UL
#define UTF8_CODE_PAGE 65001U
#define NO_INVALID_CHARS 0x00000080UL

/* btrc: one directory being read, readdir-style. */
struct directory {
	intptr_t handle;
	int state;         /* 0: ".", 1: "..", 2: entries, 3: done */
	int pending;       /* data holds an entry not yet returned */
	int error;         /* the errno of a failed _wfindnext64 */
	struct _wfinddata64_t data;
	char name[1024];   /* a 260-unit name needs at most 780 UTF-8 bytes */
};

/* btrc: opendir. An empty path is the current directory; a bare drive
   ("C:") stays drive-relative. */
static int open_directory(struct directory *dir, const char *path)
{
	size_t len = strlen(path);
	char *spec = malloc(len + 3);
	if (!spec) {
		errno = ENOMEM;
		return -1;
	}
	memcpy(spec, path, len);
	if (len && path[len-1] != '/' && path[len-1] != '\\' && path[len-1] != ':')
		spec[len++] = '/';
	spec[len++] = '*';
	spec[len] = 0;
	wchar_t *wide = btrc_win_path_to_wide(spec);
	free(spec);
	if (!wide) return -1;
	dir->handle = _wfindfirst64(wide, &dir->data);
	int find_error = errno;
	if (dir->handle == -1) {
		/* POSIX reports a file named as a directory as ENOTDIR. */
		size_t base = wcslen(wide);
		while (base && wide[base-1] != L'/') base--;
		if (base) wide[base-1] = 0;
		unsigned long attributes = base ? GetFileAttributesW(wide) : INVALID_ATTRIBUTES;
		free(wide);
		if (find_error == ENOENT && attributes != INVALID_ATTRIBUTES
		    && !(attributes & ATTRIBUTE_DIRECTORY))
			find_error = ENOTDIR;
		errno = find_error;
		return -1;
	}
	free(wide);
	dir->state = 0;
	dir->pending = 1;
	dir->error = 0;
	return 0;
}

/* btrc: readdir. Returns the next name and its d_type, or NULL at the end
   (with dir->error set if reading failed). */
static const char *read_directory(struct directory *dir, int *type)
{
	for (;;) {
		if (dir->state == 0) {
			dir->state = 1;
			*type = DT_DIR;
			return ".";
		}
		if (dir->state == 1) {
			dir->state = 2;
			*type = DT_DIR;
			return "..";
		}
		if (dir->state == 3 || !dir->pending) {
			dir->state = 3;
			return NULL;
		}
		const wchar_t *name = dir->data.name;
		int dots = name[0] == L'.' && (!name[1] || (name[1] == L'.' && !name[2]));
		int len = dots ? 0 : WideCharToMultiByte(UTF8_CODE_PAGE, NO_INVALID_CHARS, name, -1,
			dir->name, (int)sizeof dir->name, NULL, NULL);
		*type = (dir->data.attrib & _A_SUBDIR) ? DT_DIR : DT_REG;
		if (_wfindnext64(dir->handle, &dir->data) != 0) {
			dir->pending = 0;
			if (errno != ENOENT) dir->error = errno;
		}
		if (len > 0) return dir->name;
	}
}

static void close_directory(struct directory *dir)
{
	_findclose(dir->handle);
}

/* btrc: lstat for existence and the GLOB_MARK type. */
static int path_type(const char *path, int *type)
{
	wchar_t *wide = btrc_win_path_to_wide(*path ? path : ".");
	if (!wide) return -1;
	unsigned long attributes = GetFileAttributesW(wide);
	free(wide);
	if (attributes == INVALID_ATTRIBUTES) {
		btrc_win_path_error(BTRC_WIN_GET_LAST_ERROR());
		return -1;
	}
	*type = (attributes & ATTRIBUTE_DIRECTORY) ? DT_DIR : DT_REG;
	return 0;
}

struct match
{
	struct match *next;
	char name[];
};

static int append(struct match **tail, const char *name, size_t len, int mark)
{
	struct match *new = malloc(sizeof(struct match) + len + 2);
	if (!new) return -1;
	(*tail)->next = new;
	new->next = NULL;
	memcpy(new->name, name, len+1);
	if (mark && len && name[len-1]!='/') {
		new->name[len] = '/';
		new->name[len+1] = 0;
	}
	*tail = new;
	return 0;
}

static int do_glob(char *buf, size_t pos, int type, char *pat, int flags, int (*errfunc)(const char *path, int err), struct match **tail)
{
	/* If GLOB_MARK is unused, we don't care about type. */
	if (!type && !(flags & GLOB_MARK)) type = DT_REG;

	/* Special-case the remaining pattern being all slashes, in
	 * which case we can use caller-passed type if it's a dir. */
	if (*pat && type!=DT_DIR) type = 0;
	while (pos+1 < PATH_BUFFER_MAX && *pat=='/') buf[pos++] = *pat++;

	/* Consume maximal [escaped-]literal prefix of pattern, copying
	 * and un-escaping it to the running buffer as we go. */
	ptrdiff_t i=0, j=0;
	int in_bracket = 0, overflow = 0;
	for (; pat[i]!='*' && pat[i]!='?' && (!in_bracket || pat[i]!=']'); i++) {
		if (!pat[i]) {
			if (overflow) return 0;
			pat += i;
			pos += j;
			i = j = 0;
			break;
		} else if (pat[i] == '[') {
			in_bracket = 1;
		} else if (pat[i] == '\\' && !(flags & GLOB_NOESCAPE)) {
			/* Backslashes inside a bracket are (at least by
			 * our interpretation) non-special, so if next
			 * char is ']' we have a complete expression. */
			if (in_bracket && pat[i+1]==']') break;
			/* Unpaired final backslash never matches. */
			if (!pat[i+1]) return 0;
			i++;
		}
		if (pat[i] == '/') {
			if (overflow) return 0;
			in_bracket = 0;
			pat += i+1;
			i = -1;
			pos += j+1;
			j = -1;
		}
		/* Only store a character if it fits in the buffer, but if
		 * a potential bracket expression is open, the overflow
		 * must be remembered and handled later only if the bracket
		 * is unterminated (and thereby a literal), so as not to
		 * disallow long bracket expressions with short matches. */
		if (pos+(j+1) < PATH_BUFFER_MAX) {
			buf[pos+j++] = pat[i];
		} else if (in_bracket) {
			overflow = 1;
		} else {
			return 0;
		}
		/* If we consume any new components, the caller-passed type
		 * or dummy type from above is no longer valid. */
		type = 0;
	}
	buf[pos] = 0;
	if (!*pat) {
		/* If we consumed any components above, or if GLOB_MARK is
		 * requested and we don't yet know if the match is a dir,
		 * we must confirm the file exists and/or determine its type. */
		/* btrc: one GetFileAttributesW answers both questions. */
		if (!type && path_type(buf, &type)) {
			if (errno!=ENOENT && (errfunc(buf, errno) || (flags & GLOB_ERR)))
				return GLOB_ABORTED;
			return 0;
		}
		if (append(tail, buf, pos, (flags & GLOB_MARK) && type==DT_DIR))
			return GLOB_NOSPACE;
		return 0;
	}
	char *p2 = strchr(pat, '/'), saved_sep = '/';
	/* Check if the '/' was escaped and, if so, remove the escape char
	 * so that it will not be unpaired when passed to fnmatch. */
	if (p2 && !(flags & GLOB_NOESCAPE)) {
		char *p;
		for (p=p2; p>pat && p[-1]=='\\'; p--);
		if ((p2-p)%2) {
			p2--;
			saved_sep = '\\';
		}
	}
	struct directory dir;
	if (open_directory(&dir, pos ? buf : ".")) {
		if (errfunc(buf, errno) || (flags & GLOB_ERR))
			return GLOB_ABORTED;
		return 0;
	}
	int old_errno = errno;
	const char *name;
	int name_type;
	while ((name = read_directory(&dir, &name_type))) {
		/* Quickly skip non-directories when there's pattern left. */
		if (p2 && name_type!=DT_DIR)
			continue;

		size_t l = strlen(name);
		if (l >= PATH_BUFFER_MAX-pos) continue;

		if (p2) *p2 = 0;

		int fnm_flags= ((flags & GLOB_NOESCAPE) ? FNM_NOESCAPE : 0)
			| FNM_PERIOD;

		if (fnmatch(pat, name, fnm_flags))
			continue;

		memcpy(buf+pos, name, l+1);
		if (p2) *p2 = saved_sep;
		int r = do_glob(buf, pos+l, name_type, p2 ? p2 : "", flags, errfunc, tail);
		if (r) {
			close_directory(&dir);
			return r;
		}
	}
	int readerr = dir.error;
	if (p2) *p2 = saved_sep;
	close_directory(&dir);
	if (readerr && (errfunc(buf, readerr) || (flags & GLOB_ERR)))
		return GLOB_ABORTED;
	errno = old_errno;
	return 0;
}

static int ignore_err(const char *path, int err)
{
	(void)path; /* btrc: -Wunused-parameter */
	(void)err;
	return 0;
}

static void freelist(struct match *head)
{
	struct match *match, *next;
	for (match=head->next; match; match=next) {
		next = match->next;
		free(match);
	}
}

static int sort(const void *a, const void *b)
{
	return strcmp(*(const char **)a, *(const char **)b);
}

int glob(const char *restrict pat, int flags, int (*errfunc)(const char *path, int err), glob_t *restrict g)
{
	struct match head = { .next = NULL }, *tail = &head;
	size_t cnt, i;
	size_t offs = (flags & GLOB_DOOFFS) ? g->gl_offs : 0;
	int error = 0;
	char *buf;

	if (!errfunc) errfunc = ignore_err;

	if (!(flags & GLOB_APPEND)) {
		g->gl_offs = offs;
		g->gl_pathc = 0;
		g->gl_pathv = NULL;
	}

	if (*pat) {
		char *p = malloc(strlen(pat) + 1); /* btrc: strdup is not ISO C11 */
		if (!p) return GLOB_NOSPACE;
		strcpy(p, pat);
		buf = malloc(PATH_BUFFER_MAX); /* btrc: on the heap */
		if (!buf) {
			free(p);
			return GLOB_NOSPACE;
		}
		buf[0] = 0;
		error = do_glob(buf, 0, 0, p, flags, errfunc, &tail);
		free(buf);
		free(p);
	}

	if (error == GLOB_NOSPACE) {
		freelist(&head);
		return error;
	}

	for (cnt=0, tail=head.next; tail; tail=tail->next, cnt++);
	if (!cnt) {
		if (flags & GLOB_NOCHECK) {
			tail = &head;
			if (append(&tail, pat, strlen(pat), 0))
				return GLOB_NOSPACE;
			cnt++;
		} else if (!error)
			return GLOB_NOMATCH;
	}

	if (flags & GLOB_APPEND) {
		char **pathv = realloc(g->gl_pathv, (offs + g->gl_pathc + cnt + 1) * sizeof(char *));
		if (!pathv) {
			freelist(&head);
			return GLOB_NOSPACE;
		}
		g->gl_pathv = pathv;
		offs += g->gl_pathc;
	} else {
		g->gl_pathv = malloc((offs + cnt + 1) * sizeof(char *));
		if (!g->gl_pathv) {
			freelist(&head);
			return GLOB_NOSPACE;
		}
		for (i=0; i<offs; i++)
			g->gl_pathv[i] = NULL;
	}
	for (i=0, tail=head.next; i<cnt; tail=tail->next, i++)
		g->gl_pathv[offs + i] = tail->name;
	g->gl_pathv[offs + i] = NULL;
	g->gl_pathc += cnt;

	if (!(flags & GLOB_NOSORT))
		qsort(g->gl_pathv+offs, cnt, sizeof(char *), sort);

	return error;
}

void globfree(glob_t *g)
{
	size_t i;
	for (i=0; i<g->gl_pathc; i++)
		free(g->gl_pathv[g->gl_offs + i] - offsetof(struct match, name));
	free(g->gl_pathv);
	g->gl_pathc = 0;
	g->gl_pathv = NULL;
}
