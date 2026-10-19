/* Drives TerminalConsole.exe through a Windows pseudoconsole (ConPTY).

   usage: ConptyHarness.exe <TerminalConsole.exe>

   The harness creates a 100x30 pseudoconsole, starts the program in it, waits
   for each prompt or marker the program prints, types the input a person
   would (Unicode text, Enter, Ctrl-C, an arrow key) and checks every line the
   program reports, its exit status, and that no secret ever reached the
   screen. Then it runs the program's "default" case, whose Ctrl-C reaches
   Windows' default handler, beside a "probe" on the same pseudoconsole,
   which must find the console's echo restored once "default" has ended.
   Prints one "conpty-terminal" line per check and exits 0 only when every
   check passed.

   Ctrl-C reaches the program only when its process group processes it: the
   harness clears an inherited "ignore Ctrl-C" flag before starting it, and
   never starts it in a new process group. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WAIT_MS 20000

typedef struct {
	HANDLE pipe;
	CRITICAL_SECTION lock;
	char *data;
	size_t length;
	size_t capacity;
	int closed;
} Screen;

static int failures = 0;

static void report(const char *check, int passed, const char *detail)
{
	printf("conpty-terminal %s %s%s%s\n", check, passed ? "ok" : "FAILED", detail ? ": " : "", detail ? detail : "");
	fflush(stdout);
	if (!passed) failures++;
}

/* Keeps reading the pseudoconsole's output: an undrained pipe stalls it. */
static DWORD WINAPI drain(void *argument)
{
	Screen *screen = argument;
	char buffer[4096];
	DWORD count = 0;
	while (ReadFile(screen->pipe, buffer, sizeof buffer, &count, NULL) && count > 0) {
		EnterCriticalSection(&screen->lock);
		if (screen->length + count + 1 > screen->capacity) {
			size_t capacity = (screen->length + count + 1) * 2;
			char *grown = realloc(screen->data, capacity);
			if (grown) {
				screen->data = grown;
				screen->capacity = capacity;
			}
		}
		if (screen->length + count + 1 <= screen->capacity) {
			memcpy(screen->data + screen->length, buffer, count);
			screen->length += count;
			screen->data[screen->length] = 0;
		}
		LeaveCriticalSection(&screen->lock);
	}
	EnterCriticalSection(&screen->lock);
	screen->closed = 1;
	LeaveCriticalSection(&screen->lock);
	return 0;
}

/* Whether `text` appears on the screen at or after `*cursor`; on success the
   cursor moves past it. */
static int seen(Screen *screen, size_t *cursor, const char *text)
{
	EnterCriticalSection(&screen->lock);
	const char *found = screen->data && *cursor <= screen->length ? strstr(screen->data + *cursor, text) : NULL;
	if (found) *cursor = (size_t)(found - screen->data) + strlen(text);
	LeaveCriticalSection(&screen->lock);
	return found != NULL;
}

static int wait_for(Screen *screen, size_t *cursor, const char *text)
{
	for (DWORD waited = 0; waited < WAIT_MS; waited += 10) {
		if (seen(screen, cursor, text)) return 1;
		Sleep(10);
	}
	return 0;
}

/* The rest of the line that starts with `prefix`, once the program has
   printed all of it, without the VT sequences the pseudoconsole renders
   around text. */
static int read_line(Screen *screen, size_t *cursor, const char *prefix, char *line, size_t size)
{
	if (!wait_for(screen, cursor, prefix)) return 0;
	for (DWORD waited = 0; waited < WAIT_MS; waited += 10) {
		EnterCriticalSection(&screen->lock);
		const char *start = screen->data + *cursor;
		const char *end = strpbrk(start, "\r\n");
		if (end) {
			size_t length = 0;
			for (const char *p = start; p < end && length < size - 1; p++) {
				if (*p == '\x1b' && p + 1 < end && p[1] == '[') {
					for (p += 2; p < end && !(*p >= 0x40 && *p <= 0x7e); p++) {}
					continue;
				}
				if (*p == '\x1b' && p + 1 < end && p[1] == ']') {
					for (p += 2; p < end && *p != '\x07'; p++) {}
					continue;
				}
				line[length++] = *p;
			}
			while (length > 0 && line[length - 1] == ' ') length--;
			line[length] = 0;
			*cursor = (size_t)(end - screen->data);
		}
		LeaveCriticalSection(&screen->lock);
		if (end) return 1;
		Sleep(10);
	}
	return 0;
}

static void type(HANDLE input, const char *bytes)
{
	DWORD written = 0;
	WriteFile(input, bytes, (DWORD)strlen(bytes), &written, NULL);
}

static void expect_line(Screen *screen, size_t *cursor, const char *check, const char *prefix, const char *expected)
{
	char line[512];
	int read = read_line(screen, cursor, prefix, line, sizeof line);
	report(check, read && strcmp(line, expected) == 0, read ? line : "no line");
}

static int start(HPCON console, const wchar_t *program, const wchar_t *scenario, PROCESS_INFORMATION *process)
{
	SIZE_T size = 0;
	InitializeProcThreadAttributeList(NULL, 1, 0, &size);
	LPPROC_THREAD_ATTRIBUTE_LIST attributes = malloc(size);
	if (!attributes || !InitializeProcThreadAttributeList(attributes, 1, 0, &size)) return 0;
	if (!UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE, console, sizeof console, NULL, NULL)) {
		return 0;
	}
	STARTUPINFOEXW startup;
	ZeroMemory(&startup, sizeof startup);
	startup.StartupInfo.cb = sizeof startup;
	/* Null standard handles: the program takes the pseudoconsole's, never the
	   harness's own (redirected) ones. */
	startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
	startup.lpAttributeList = attributes;
	SetEnvironmentVariableW(L"TERMINAL_CONSOLE_CASE", scenario);
	wchar_t command[2048];
	_snwprintf(command, 2047, L"\"%ls\"", program);
	command[2047] = 0;
	BOOL started = CreateProcessW(program, command, NULL, NULL, FALSE, EXTENDED_STARTUPINFO_PRESENT, NULL, NULL,
		&startup.StartupInfo, process);
	DeleteProcThreadAttributeList(attributes);
	free(attributes);
	return started != 0;
}

static DWORD finish(PROCESS_INFORMATION *process)
{
	DWORD status = 0;
	if (WaitForSingleObject(process->hProcess, WAIT_MS) != WAIT_OBJECT_0) {
		TerminateProcess(process->hProcess, 99);
		WaitForSingleObject(process->hProcess, WAIT_MS);
	}
	GetExitCodeProcess(process->hProcess, &status);
	CloseHandle(process->hThread);
	CloseHandle(process->hProcess);
	return status;
}

static void contains_no(Screen *screen, const char *check, const char *secret)
{
	EnterCriticalSection(&screen->lock);
	int leaked = screen->data && strstr(screen->data, secret) != NULL;
	LeaveCriticalSection(&screen->lock);
	report(check, !leaked, leaked ? secret : NULL);
}

int main(void)
{
	int argc = 0;
	wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
	if (!argv || argc != 2) {
		fprintf(stderr, "usage: ConptyHarness.exe <TerminalConsole.exe>\n");
		return 2;
	}
	wchar_t program[MAX_PATH * 4];
	if (!GetFullPathNameW(argv[1], MAX_PATH * 4, program, NULL)) return 2;
	for (wchar_t *p = program; *p; p++) {
		if (*p == L'/') *p = L'\\';
	}
	/* A parent that ignores Ctrl-C passes that on; this program must not. */
	SetConsoleCtrlHandler(NULL, FALSE);

	HANDLE input_read, input_write, output_read, output_write;
	if (!CreatePipe(&input_read, &input_write, NULL, 0) || !CreatePipe(&output_read, &output_write, NULL, 0)) return 2;
	COORD size = {100, 30};
	HPCON console;
	if (FAILED(CreatePseudoConsole(size, input_read, output_write, 0, &console))) {
		report("pseudoconsole", 0, "CreatePseudoConsole failed");
		return 1;
	}
	CloseHandle(input_read);
	CloseHandle(output_write);
	Screen screen;
	ZeroMemory(&screen, sizeof screen);
	screen.pipe = output_read;
	InitializeCriticalSection(&screen.lock);
	HANDLE reader = CreateThread(NULL, 0, drain, &screen, 0, NULL);
	size_t cursor = 0;

	PROCESS_INFORMATION process;
	if (!start(console, program, NULL, &process)) {
		report("start", 0, "CreateProcessW failed");
		return 1;
	}
	report("ready", wait_for(&screen, &cursor, "ready"), NULL);
	report("first prompt", wait_for(&screen, &cursor, "first secret:"), NULL);
	type(input_write, "alpha-s3cr3t-\xc3\xa9\r");
	expect_line(&screen, &cursor, "password", "first ", "match=1 echo=1");

	report("second prompt", wait_for(&screen, &cursor, "second secret:"), NULL);
	Sleep(300);
	type(input_write, "\x03");
	expect_line(&screen, &cursor, "ctrl-c", "second ", "empty=1 calls=1 saw=1 echo=1");

	report("third prompt", wait_for(&screen, &cursor, "third secret:"), NULL);
	type(input_write, "omega-s3cr3t\r");
	expect_line(&screen, &cursor, "after ctrl-c", "third ", "match=1 echo=1");

	report("burst prompt", wait_for(&screen, &cursor, "burst secret:"), NULL);
	Sleep(300);
	type(input_write, "\x03\x03\x03");
	expect_line(&screen, &cursor, "ctrl-c burst", "burst ", "empty=1 echo=1");

	report("plain prompt", wait_for(&screen, &cursor, "plain line:"), NULL);
	type(input_write, "h\xc3\xa9llo w\xc3\xb6rld \xe6\x97\xa5\xe6\x9c\xac\r");
	expect_line(&screen, &cursor, "unicode line", "plain ", "match=1");

	expect_line(&screen, &cursor, "raw mode", "raw echo", "=0 line=0 processed=0");
	report("raw ready", wait_for(&screen, &cursor, "raw ready"), NULL);
	type(input_write, "ab\x03\x1b[A");
	expect_line(&screen, &cursor, "raw keys", "raw keys=", "97,98,3,27,91,65 restored=1 echo=1 line=1 processed=1");
	expect_line(&screen, &cursor, "size", "size ", "100x30");
	expect_line(&screen, &cursor, "colors", "colors ", "1");
	report("pass", wait_for(&screen, &cursor, "PASS: terminal console"), NULL);
	DWORD status = finish(&process);
	report("exit", status == 0, status == 0 ? NULL : "nonzero exit");
	contains_no(&screen, "first secret hidden", "alpha-s3cr3t");
	contains_no(&screen, "third secret hidden", "omega-s3cr3t");

	/* Windows' default handler ends the process; the prompt's handler has
	   restored the echo first, as a probe kept on the same console sees once
	   the gate file appears. The probe survives the Ctrl-C, which reaches
	   every process on the console, with a handler of its own. */
	wchar_t gate[MAX_PATH + 64];
	DWORD temporary = GetTempPathW(MAX_PATH, gate);
	_snwprintf(gate + temporary, 63, L"btrc-conpty-gate-%lu.txt", (unsigned long)GetCurrentProcessId());
	DeleteFileW(gate);
	SetEnvironmentVariableW(L"TERMINAL_CONSOLE_GATE", gate);
	PROCESS_INFORMATION probe;
	int probing = start(console, program, L"probe", &probe);
	report("probe ready", probing && wait_for(&screen, &cursor, "probe waiting"), NULL);
	if (start(console, program, L"default", &process)) {
		report("default prompt", wait_for(&screen, &cursor, "default secret:"), NULL);
		Sleep(300);
		type(input_write, "\x03");
		status = finish(&process);
		report("default ctrl-c exit", status == (DWORD)STATUS_CONTROL_C_EXIT, status == (DWORD)STATUS_CONTROL_C_EXIT ? NULL : "not STATUS_CONTROL_C_EXIT");
	} else {
		report("default start", 0, "CreateProcessW failed");
	}
	HANDLE opened = CreateFileW(gate, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
	if (opened != INVALID_HANDLE_VALUE) CloseHandle(opened);
	if (probing) {
		expect_line(&screen, &cursor, "restored before exit", "probe echo", "=1 line=1 processed=1");
		status = finish(&probe);
		report("probe exit", status == 0, NULL);
	}
	DeleteFileW(gate);

	ClosePseudoConsole(console);
	CloseHandle(input_write);
	WaitForSingleObject(reader, WAIT_MS);
	CloseHandle(reader);
	CloseHandle(output_read);
	printf("conpty-terminal %s\n", failures ? "FAILED" : "PASS");
	return failures ? 1 : 0;
}
