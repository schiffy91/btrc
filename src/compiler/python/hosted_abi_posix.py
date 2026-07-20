"""Exact POSIX ABI seams used by canonical stdlib borrow wrappers."""

from .hosted_abi_model import (
    ALIAS_DEPENDENT,
    ALIAS_EXACT,
    CHAR_PTR,
    CONST_CHAR_PTR,
    CONST_VOID_PTR,
    CONSUME,
    DEALLOC_FREE,
    INT,
    MUTATE,
    READ,
    RETURN_ALIAS,
    RETURN_FRESH,
    RETURN_INDEPENDENT,
    SIZE,
    UNKNOWN,
    VALUE,
    VOID,
    VOID_PTR,
    HostedFunction,
    abi_type,
    function,
)
from .hosted_abi_posix_process import HOSTED_POSIX_PROCESS_FUNCTIONS

_SSIZE = abi_type("ssize_t")
_MODE = abi_type("mode_t")
_DIR_PTR = abi_type("DIR", 1)
_STRUCT_STAT_PTR = abi_type("struct stat", 1)
_REGEX_PTR = abi_type("regex_t", 1)
_CONST_REGEX_PTR = abi_type("regex_t", 1, const=True)
_REGMATCH_PTR = abi_type("regmatch_t", 1)
_SOCKLEN = abi_type("socklen_t")
_CONST_SOCKADDR_PTR = abi_type("struct sockaddr", 1, const=True)
_SOCKADDR_PTR = abi_type("struct sockaddr", 1)
_SOCKLEN_PTR = abi_type("socklen_t", 1)
_INT_PTR = abi_type("int", 1)
_OFF = abi_type("off_t")
_CONST_TIME_PTR = abi_type("time_t", 1, const=True)
_TM_PTR = abi_type("struct tm", 1)
_DIRENT_PTR = abi_type("struct dirent", 1)

HOSTED_POSIX_FUNCTIONS: dict[str, HostedFunction] = {
    **HOSTED_POSIX_PROCESS_FUNCTIONS,
    "accept": function(
        INT,
        INT,
        _SOCKADDR_PTR,
        _SOCKLEN_PTR,
        effects=(VALUE, MUTATE, MUTATE),
    ),
    "access": function(INT, CONST_CHAR_PTR, INT, effects=(READ, VALUE)),
    "bind": function(
        INT,
        INT,
        _CONST_SOCKADDR_PTR,
        _SOCKLEN,
        effects=(VALUE, READ, VALUE),
    ),
    "chdir": function(INT, CONST_CHAR_PTR, effects=(READ,)),
    "chmod": function(INT, CONST_CHAR_PTR, _MODE, effects=(READ, VALUE)),
    "close": function(INT, INT, effects=(VALUE,)),
    "closedir": function(
        INT,
        _DIR_PTR,
        effects=(CONSUME,),
        raw_lifetime=True,
        consume_deallocator="closedir",
    ),
    "dirfd": function(INT, _DIR_PTR, effects=(READ,)),
    "dup2": function(INT, INT, INT, effects=(VALUE, VALUE)),
    "fnmatch": function(
        INT,
        CONST_CHAR_PTR,
        CONST_CHAR_PTR,
        INT,
        effects=(READ, READ, VALUE),
    ),
    "fcntl": function(
        INT,
        INT,
        INT,
        effects=(VALUE, VALUE),
        variadic=True,
    ),
    "fdopendir": function(
        _DIR_PTR,
        INT,
        # The descriptor transfers only on success.  Scalar conditional
        # consumption is not representable yet, so fail closed on escape.
        effects=(UNKNOWN,),
        return_effect=RETURN_INDEPENDENT,
        return_deallocator="closedir",
    ),
    "fstat": function(INT, INT, _STRUCT_STAT_PTR, effects=(VALUE, MUTATE)),
    "fsync": function(INT, INT, effects=(VALUE,)),
    "getcwd": function(
        CHAR_PTR,
        CHAR_PTR,
        SIZE,
        effects=(MUTATE, VALUE),
        return_effect=RETURN_ALIAS,
        return_alias_parameter=0,
        return_alias_null_effect=RETURN_FRESH,
        return_alias_null_deallocator=DEALLOC_FREE,
        return_alias_shape=ALIAS_EXACT,
    ),
    "lstat": function(
        INT,
        CONST_CHAR_PTR,
        _STRUCT_STAT_PTR,
        effects=(READ, MUTATE),
    ),
    "listen": function(INT, INT, INT, effects=(VALUE, VALUE)),
    "localtime_r": function(
        _TM_PTR,
        _CONST_TIME_PTR,
        _TM_PTR,
        effects=(READ, MUTATE),
        return_effect=RETURN_ALIAS,
        return_alias_parameter=1,
        return_alias_shape=ALIAS_EXACT,
    ),
    "lseek": function(_OFF, INT, _OFF, INT, effects=(VALUE, VALUE, VALUE)),
    "mkdir": function(INT, CONST_CHAR_PTR, _MODE, effects=(READ, VALUE)),
    "open": function(
        INT,
        CONST_CHAR_PTR,
        INT,
        effects=(READ, VALUE),
        variadic=True,
    ),
    "openat": function(
        INT,
        INT,
        CONST_CHAR_PTR,
        INT,
        effects=(VALUE, READ, VALUE),
        variadic=True,
    ),
    "opendir": function(
        _DIR_PTR,
        CONST_CHAR_PTR,
        effects=(READ,),
        return_effect=RETURN_INDEPENDENT,
        return_deallocator="closedir",
    ),
    "readlink": function(
        _SSIZE,
        CONST_CHAR_PTR,
        CHAR_PTR,
        SIZE,
        effects=(READ, MUTATE, VALUE),
    ),
    "read": function(
        _SSIZE,
        INT,
        VOID_PTR,
        SIZE,
        effects=(VALUE, MUTATE, VALUE),
    ),
    "realpath": function(
        CHAR_PTR,
        CONST_CHAR_PTR,
        CHAR_PTR,
        effects=(READ, MUTATE),
        return_effect=RETURN_ALIAS,
        return_alias_parameter=1,
        return_alias_null_effect=RETURN_FRESH,
        return_alias_null_deallocator=DEALLOC_FREE,
        return_alias_shape=ALIAS_EXACT,
    ),
    "readdir": function(
        _DIRENT_PTR,
        _DIR_PTR,
        effects=(MUTATE,),
        return_effect=RETURN_ALIAS,
        return_alias_parameter=0,
        return_alias_shape=ALIAS_DEPENDENT,
    ),
    "recv": function(
        _SSIZE,
        INT,
        VOID_PTR,
        SIZE,
        INT,
        effects=(VALUE, MUTATE, VALUE, VALUE),
    ),
    "regcomp": function(
        INT,
        _REGEX_PTR,
        CONST_CHAR_PTR,
        INT,
        effects=(MUTATE, READ, VALUE),
    ),
    "regexec": function(
        INT,
        _CONST_REGEX_PTR,
        CONST_CHAR_PTR,
        SIZE,
        _REGMATCH_PTR,
        INT,
        effects=(READ, READ, VALUE, MUTATE, VALUE),
    ),
    "regfree": function(VOID, _REGEX_PTR, effects=(MUTATE,)),
    "rmdir": function(INT, CONST_CHAR_PTR, effects=(READ,)),
    "send": function(
        _SSIZE,
        INT,
        CONST_VOID_PTR,
        SIZE,
        INT,
        effects=(VALUE, READ, VALUE, VALUE),
    ),
    "setsockopt": function(
        INT,
        INT,
        INT,
        INT,
        CONST_VOID_PTR,
        _SOCKLEN,
        effects=(VALUE, VALUE, VALUE, READ, VALUE),
    ),
    "shutdown": function(INT, INT, INT, effects=(VALUE, VALUE)),
    "socket": function(INT, INT, INT, INT, effects=(VALUE, VALUE, VALUE)),
    "socketpair": function(
        INT,
        INT,
        INT,
        INT,
        _INT_PTR,
        effects=(VALUE, VALUE, VALUE, MUTATE),
    ),
    "stat": function(
        INT,
        CONST_CHAR_PTR,
        _STRUCT_STAT_PTR,
        effects=(READ, MUTATE),
    ),
    "symlink": function(
        INT,
        CONST_CHAR_PTR,
        CONST_CHAR_PTR,
        effects=(READ, READ),
    ),
    "unlink": function(INT, CONST_CHAR_PTR, effects=(READ,)),
    "unlinkat": function(
        INT,
        INT,
        CONST_CHAR_PTR,
        INT,
        effects=(VALUE, READ, VALUE),
    ),
    "fstatat": function(
        INT,
        INT,
        CONST_CHAR_PTR,
        _STRUCT_STAT_PTR,
        INT,
        effects=(VALUE, READ, MUTATE, VALUE),
    ),
    "write": function(
        _SSIZE,
        INT,
        CONST_VOID_PTR,
        SIZE,
        effects=(VALUE, READ, VALUE),
    ),
}

HOSTED_POSIX_NAMES = frozenset(HOSTED_POSIX_FUNCTIONS)

__all__ = ["HOSTED_POSIX_FUNCTIONS", "HOSTED_POSIX_NAMES"]
