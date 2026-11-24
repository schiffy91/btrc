# Windows Regex compatibility

The MinGW-w64 Windows overlay (`src/runtime/windows/regex.h` and its helper
headers) implements POSIX ERE and BRE matching (`regcomp`, `regexec`,
`regerror`, `regfree`) entirely in first-party C11. The previously bundled
musl 1.2.5 TRE-derived sources (`src/runtime/windows/musl/` and
`src/runtime/windows/btrc_win_musl.h`) have been removed.

## Architecture and bounds

* **Locale and character model:** Byte-oriented C/POSIX locale. Each non-NUL
  byte is one character; POSIX character classes (`[:alnum:]` through
  `[:xdigit:]`) and `REG_ICASE` cover ASCII only.
* **Fast path (`btrc_win_regex_atom.h`, `btrc_win_regex_literal.h`):**
  Zero-allocation KMP search for plain literals and tight byte-set scan for
  single-atom EREs under `REG_EXTENDED` (with optional `^`/`$` anchors and
  `REG_NOSUB`).
* **General engine (`btrc_win_regex_compile.h`, `btrc_win_regex_exec.h`):**
  Full POSIX ERE and BRE compiler and executor supporting `REG_EXTENDED`,
  `REG_ICASE`, `REG_NEWLINE`, `REG_NOSUB`, `REG_NOTBOL`, `REG_NOTEOL`,
  `RE_DUP_MAX = 255`, bracket expressions, POSIX classes, single-byte
  C-locale collating elements (`[[.a.]]`) and equivalence classes (`[[=a=]]`),
  anchors (`^`, `$`), word assertions (`\b`, `\B`, `\<`, `\>`), shorthand and
  hex escapes (`\d`, `\D`, `\s`, `\S`, `\w`, `\W`, `\xHH`, `\x{...}`), BRE
  `\+`, `\?`, `\|` extensions, nested counted repetitions, and BRE
  backreferences (`\1`–`\9`).
* **ReDoS and resource bounds:** Parser/compiler depth is capped at 256,
  AST nodes and emitted NFA instructions at 262,144 (`REG_ESPACE` on overflow).
  Pass 1 finds `[rm_so, rm_eo)` in `O(|code| * |text|)` time using sorted
  start origins (stack-allocated for `code_count <= 256`). Pass 2 extracts
  exact IEEE Std 1003.1 leftmost-longest subgroup spans on `[rm_so, rm_eo)`
  using a backward-pruned top-down extractor (capped at 16 MiB workspace,
  falling back cleanly to Pass 3 on multi-megabyte spans). Pass 3 executes BRE
  backreferences (and large-span fallback) in a bounded tagged NFA capped at
  16 MiB per frontier and 16,000,000 total state operations (`REG_ESPACE` if
  exceeded).

## Observable differences from the retired musl 1.2.5 TRE overlay

In a 20,116-case differential comparison against both macOS host libc and the
retired musl 1.2.5 Windows overlay, plus 18,026 cases verified against an
independent brute-force IEEE Std 1003.1 POSIX evaluator (0 mismatches), every
difference from the retired musl overlay falls into one of the intentional
POSIX conformance fixes below:

1. **Nested counted repetitions (TRE position-aliasing bug fixed):**
   musl 1.2.5's TRE corrupted AST position indices when expanding nested
   counted intervals, causing `Regex.fullMatch("((a{2})?b)?", "ab")` to return
   `true` and `Regex.first("((b{1,3}){2,3}|.x){0,2}", "ab")` to return `"ab"`,
   even though neither string is in the ERE's language. The first-party engine
   evaluates the exact POSIX language (`fullMatch` returns `false`, `first`
   returns `""`), matching glibc and macOS libc.
2. **Leftmost-longest start priority (TRE parallel-TNFA bug fixed):**
   musl 1.2.5's TRE allowed a later match start to overwrite an earlier
   leftmost match when competing subgroup histories arrived at the same end
   offset, returning `"12345"` for `([[:digit:]])+.{2,4}` on `"1x12345"` and
   `"bcde"` for `((..){1,3})+` on `"abcde"`. The first-party engine enforces
   strict POSIX leftmost-longest priority (`"1x123"` and `"abcd"`), matching
   glibc and IEEE Std 1003.1 §9.1.
3. **Submatch disambiguation on repeated alternations and `{0}` groups (TRE
   tag bugs fixed):**
   For `(a|aa|aaa)*` on `"aaaa"`, `(a|aa)*` on `"aaa"`, and `(a|aa){1,2}` on
   `"aa"`, earlier iterations now maximize first (`g1 = [3,4)`, `[2,3)`,
   `[0,2)`), matching POSIX and macOS libc instead of musl's `[1,4)`, `[1,3)`,
   `[1,2)`. Erased groups such as `(a){0}` report `[-1, -1)` instead of
   `[0, 0)`, and non-participating empty arms such as `(a|())` on `"a"` report
   `g2 = [-1, -1)` instead of `[1, 1)`.
4. **Optional and alternating zero-width assertions (TRE bugs fixed):**
   `(^)?a` on `"ba"` now matches `"a"`, `($|^)a` on `"a"` now matches `"a"`,
   and `($|)` on `"a"` matches `[0, 0)` instead of failing or skipping the
   second branch.
5. **Word-boundary assertions `\b` and `\B` at non-word subject endpoints:**
   `\b` now matches strictly on word/non-word transitions (`word != previous`)
   and `\B` on its exact complement (`word == previous`), matching glibc, PCRE,
   and RE2, rather than treating start/end of `""` or `"---"` as word
   boundaries.
6. **Bracket expression C-locale collating elements and class range endpoints:**
   Single-byte `[[.a.]]` (including ranges like `[[.a.]-[.c.]]`) and
   `[[=a=]]` now succeed in the C locale (multi-byte forms still return
   `REG_ECOLLATE`). Using a character class as a range endpoint (such as
   `[0-[:alpha:]]`) now returns `REG_ERANGE`, matching POSIX, glibc and macOS.
7. **BRE backreference rules (POSIX/glibc conformance):**
   * Self-referencing or forward backreferences before the referenced group's
     closing `\)` (such as `\(\1\)`) fail compilation with `REG_ESUBREG`.
   * Backreferences to an unmatched capture group (such as `\(\(a\)\|b\)\2`
     on `"b"` or `\(a\)\{0\}\1`) fail to match (`REG_NOMATCH`) instead of
     matching the empty string.
   * Under `REG_ICASE`, BRE backreferences fold ASCII case (`\(a\)\1` matches
     `"aA"`), matching POSIX.1-2017 and glibc.
   * Unterminated intervals (`a{1,2`, `a\{1`) return `REG_EBRACE` (`Missing '}'`).
