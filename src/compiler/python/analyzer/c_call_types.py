"""Declared scalar results for libc/POSIX calls accepted by btrc source."""

C_SCALAR_CALL_RESULTS = {
    "S_ISDIR": "bool",
    "S_ISLNK": "bool",
    "S_ISREG": "bool",
    "WEXITSTATUS": "int",
    "WIFEXITED": "bool",
    "WIFSIGNALED": "bool",
    "WTERMSIG": "int",
    "bind": "int",
    "chdir": "int",
    "chmod": "int",
    "clock_gettime": "int",
    "dup2": "int",
    "feof": "bool",
    "ferror": "bool",
    "fflush": "int",
    "fnmatch": "int",
    "fputc": "int",
    "fputs": "int",
    "geteuid": "uid_t",
    "initgroups": "int",
    "kill": "int",
    "listen": "int",
    "lstat": "int",
    "memcmp": "int",
    "nanosleep": "int",
    "pipe": "int",
    "regcomp": "int",
    "regexec": "int",
    "setenv": "int",
    "setgid": "int",
    "setsockopt": "int",
    "setuid": "int",
    "send": "ssize_t",
    "stat": "int",
    "strcmp": "int",
    "strncmp": "int",
    "strtod": "double",
    "strtof": "float",
    "strtold": "long double",
    "strlen": "size_t",
    "tcgetattr": "int",
    "tcsetattr": "int",
    "unsetenv": "int",
}

C_POINTER_CALL_RESULTS = {
    "__btrc_str_track": ("string", 0),
    "__btrc_string_adopt": ("string", 0),
    "__btrc_string_alloc": ("string", 0),
    "getcwd": ("char", 1),
}


def c_integer_identifier(name: str) -> bool:
    """Whether an identifier is accepted by the C integer-constant seam."""
    return name == "errno" or (name.isupper() and name != "NULL")


def c_opaque_value_identifier(name: str) -> bool:
    """Whether C, rather than btrc, determines an identifier's value type."""
    return name != "errno" and c_integer_identifier(name)
