#include <fcntl.h>
#include <io.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

int main(int argc, char **argv) {
    (void)_setmode(_fileno(stdin), _O_BINARY);
    (void)_setmode(_fileno(stdout), _O_BINARY);
    (void)_setmode(_fileno(stderr), _O_BINARY);
    if (argc < 2) return 2;
    if (strcmp(argv[1], "streams") == 0) {
        (void)fwrite("out\0\xff\n", 1, 6, stdout);
        (void)fwrite("err\0\xfe\n", 1, 6, stderr);
    } else if (strcmp(argv[1], "stdin") == 0) {
        unsigned char buffer[8192];
        size_t size;
        while ((size = fread(buffer, 1, sizeof(buffer), stdin)) != 0) {
            if (fwrite(buffer, 1, size, stdout) != size) return 3;
        }
        if (ferror(stdin)) return 4;
    } else if (strcmp(argv[1], "exit") == 0) {
        return argc == 3 ? atoi(argv[2]) : 2;
    } else if (strcmp(argv[1], "crash") == 0) {
        SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
        RaiseException(EXCEPTION_ACCESS_VIOLATION, EXCEPTION_NONCONTINUABLE, 0, NULL);
        return 5;
    } else if (strcmp(argv[1], "timeout") == 0) {
        Sleep(INFINITE);
    } else if (strcmp(argv[1], "argv") == 0) {
        for (int index = 2; index < argc; ++index) (void)printf("%s\n", argv[index]);
    } else if (strcmp(argv[1], "env") == 0) {
        const char *value = getenv("BTRC_HOST_PROBE");
        if (value == NULL) return 6;
        (void)printf("%s\n", value);
    } else if (strcmp(argv[1], "cwd") == 0) {
        wchar_t path[32768];
        if (GetCurrentDirectoryW(32768, path) == 0) return 7;
        if (wcsstr(path, L"btrc host \x03bb ") == NULL) return 8;
        (void)puts("isolated spaces unicode cwd");
    } else {
        return 2;
    }
    return 0;
}
