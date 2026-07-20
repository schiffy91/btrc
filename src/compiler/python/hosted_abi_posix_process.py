"""Exact POSIX process, identity, signal, and terminal ABI seams."""

from .hosted_abi_model import (
    CHAR_PTR,
    CHAR_PTR_PTR,
    CONST_CHAR_PTR,
    INT,
    MUTATE,
    READ,
    SIZE,
    VALUE,
    HostedFunction,
    abi_type,
    function,
)

_PID = abi_type("pid_t")
_INT_PTR = abi_type("int", 1)
_STRUCT_TERMIOS_PTR = abi_type("struct termios", 1, const=True)
_STRUCT_WINSIZE_PTR = abi_type("struct winsize", 1, const=True)
_PASSWD_PTR = abi_type("struct passwd", 1)
_PASSWD_PTR_PTR = abi_type("struct passwd", 2)
_CLOCK_ID = abi_type("clockid_t")
_GID = abi_type("gid_t")
_UID = abi_type("uid_t")
_TIMESPEC_PTR = abi_type("struct timespec", 1)
_CONST_TIMESPEC_PTR = abi_type("struct timespec", 1, const=True)
_TERMIOS_PTR = abi_type("struct termios", 1)
_CLOCK = abi_type("clock_t")
_NFDS = abi_type("nfds_t")
_POLLFD_PTR = abi_type("struct pollfd", 1)
_RLIMIT_PTR = abi_type("struct rlimit", 1)
_CONST_RLIMIT_PTR = abi_type("struct rlimit", 1, const=True)
_SIGACTION_PTR = abi_type("struct sigaction", 1)
_CONST_SIGACTION_PTR = abi_type("struct sigaction", 1, const=True)
_SIGSET_PTR = abi_type("sigset_t", 1)
_TIME = abi_type("time_t")
_TIME_PTR = abi_type("time_t", 1)

HOSTED_POSIX_PROCESS_FUNCTIONS: dict[str, HostedFunction] = {
    "clock_gettime": function(
        INT,
        _CLOCK_ID,
        _TIMESPEC_PTR,
        effects=(VALUE, MUTATE),
    ),
    "clock": function(_CLOCK),
    "execve": function(
        INT,
        CONST_CHAR_PTR,
        CHAR_PTR_PTR,
        CHAR_PTR_PTR,
        effects=(READ, READ, READ),
    ),
    "fork": function(_PID),
    "forkpty": function(
        _PID,
        _INT_PTR,
        CHAR_PTR,
        _STRUCT_TERMIOS_PTR,
        _STRUCT_WINSIZE_PTR,
        effects=(MUTATE, MUTATE, READ, READ),
    ),
    "getpid": function(_PID),
    "getrlimit": function(INT, INT, _RLIMIT_PTR, effects=(VALUE, MUTATE)),
    "geteuid": function(_UID),
    "getpwnam_r": function(
        INT,
        CONST_CHAR_PTR,
        _PASSWD_PTR,
        CHAR_PTR,
        SIZE,
        _PASSWD_PTR_PTR,
        effects=(READ, MUTATE, MUTATE, VALUE, MUTATE),
    ),
    "initgroups": function(
        INT,
        CONST_CHAR_PTR,
        _GID,
        effects=(READ, VALUE),
    ),
    "isatty": function(INT, INT, effects=(VALUE,)),
    "kill": function(INT, _PID, INT, effects=(VALUE, VALUE)),
    "nanosleep": function(
        INT,
        _CONST_TIMESPEC_PTR,
        _TIMESPEC_PTR,
        effects=(READ, MUTATE),
    ),
    "pipe": function(INT, _INT_PTR, effects=(MUTATE,)),
    "poll": function(
        INT,
        _POLLFD_PTR,
        _NFDS,
        INT,
        effects=(MUTATE, VALUE, VALUE),
    ),
    "raise": function(INT, INT, effects=(VALUE,)),
    "setenv": function(
        INT,
        CONST_CHAR_PTR,
        CONST_CHAR_PTR,
        INT,
        effects=(READ, READ, VALUE),
    ),
    "setgid": function(INT, _GID, effects=(VALUE,)),
    "setpgid": function(INT, _PID, _PID, effects=(VALUE, VALUE)),
    "setrlimit": function(INT, INT, _CONST_RLIMIT_PTR, effects=(VALUE, READ)),
    "setuid": function(INT, _UID, effects=(VALUE,)),
    "sigaction": function(
        INT,
        INT,
        _CONST_SIGACTION_PTR,
        _SIGACTION_PTR,
        effects=(VALUE, READ, MUTATE),
    ),
    "sigaddset": function(INT, _SIGSET_PTR, INT, effects=(MUTATE, VALUE)),
    "sigemptyset": function(INT, _SIGSET_PTR, effects=(MUTATE,)),
    "sysconf": function(abi_type("long"), INT, effects=(VALUE,)),
    "tcgetattr": function(
        INT,
        INT,
        _TERMIOS_PTR,
        effects=(VALUE, MUTATE),
    ),
    "tcsetattr": function(
        INT,
        INT,
        INT,
        _STRUCT_TERMIOS_PTR,
        effects=(VALUE, VALUE, READ),
    ),
    "time": function(_TIME, _TIME_PTR, effects=(MUTATE,)),
    "unsetenv": function(INT, CONST_CHAR_PTR, effects=(READ,)),
    "waitpid": function(_PID, _PID, _INT_PTR, INT, effects=(VALUE, MUTATE, VALUE)),
}

__all__ = ["HOSTED_POSIX_PROCESS_FUNCTIONS"]
