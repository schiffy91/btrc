# Windows Regex compatibility

`Library.Regex` specifies POSIX extended regular expressions and leftmost-longest byte spans. Programs can observe the chosen span through `Regex.first`, `fullMatch`, and replacement, even though the public API does not expose subgroup offsets. Windows now dispatches qualified pattern classes to first-party code and retains the legacy provider for the remaining expressions.

## A public difference

`Regex.fullMatch("((a{2})?b)?", "ab")` returns true on the legacy Windows provider. Under the written ERE the only complete strings are the empty string, `b`, and `aab`. The full first-party candidate returns false. The bounded first-party position matcher returns the legacy result for this pattern.

The following case also shows the effect on an existing caller's output. Each column was exercised through the reference and self-host compilers in separate Windows x64 executables under Wine. Each executable passed the binary import audit.

Both builds used pattern `((b{1,3}){2,3}|.x){0,2}` and subject `ab`.

| Public call | Legacy Windows | Full first-party candidate |
| --- | --- | --- |
| `Regex.fullMatch` | true | false |
| `CompiledRegex.fullMatch` | true | false |
| `Regex.first` | `"ab"` | `""` |
| `Regex.replace` with literal `"X"` | `"X"` | `"Xab"` |

The left alternative requires at least two `b` bytes. The right alternative requires an `x`. Only the empty prefix satisfies the expression. In a generated comparison using the flags the public API actually passes, 46 of 842,486 cases differed. Independently enumerating every possible substring in leftmost-longest order gave the candidate's span in all 46.

## Preserving the old behavior

A compatibility implementation can reproduce at least one family without bundling the legacy source. For distinct literal bytes X and Y, consider the whole pattern `((X{n})?Y)?`, where n is 2 through 255. Start at byte zero, count the initial run of X bytes as k, and check the next byte. The observed legacy match includes those k bytes and the following Y when k modulo (n−1) is 0 or 1. Otherwise its match is the empty prefix. For n=4, k values 0, 1, 3 and 4 can precede Y, while 2 and 5 cannot.

A first-party btrc prototype encoded that rule. Separate Windows x64 executables from both compilers compared it against the legacy provider's `first`, `replace`, static and compiled `fullMatch`. Each passed 5,980 cases with n=2–24. A separate group-zero oracle exercised every n through 255, two choices of X and Y, and 62,396 cases. The tested rule covers only this grammar and group zero.

A broader compatibility engine would need to model which repeated consuming positions share outbound transitions, then verify the resulting whole spans and subgroup histories. The tests already exhibit interactions with alternation, trailing literals and optional and unbounded outer quantifiers. Loosening each interval independently would change which lengths the client accepts.

## Current dispatch

For `REG_EXTENDED`, single byte sets, plain literal searches and their start/end assertions use first-party byte matching. This includes one simple or counted quantifier on a set. Capture-free sequences and nonempty alternatives made entirely from consuming byte atoms and one quantifier per atom can use the bounded first-party Thompson matcher. The flat compiler accepts source patterns of up to 255 bytes. The rules below describe its handling of escapes, captures and assertions.

The compiled regex owns its pattern data. If the Thompson matcher exhausts its working memory or per-input work allowance, the dispatcher retries with the legacy provider. Both execution paths maintain the public `regex_t` layout and support compiling in one translation unit and matching and freeing in another. The dependency audit continues to name bundled Windows regex while this fallback remains.


The independently qualified bracket fix covers punctuation ranges that the Windows dialect accepts, including `[a-z--@]`. It restores a capability without changing nested-repetition semantics.

An unasserted grouped ERE whose whole expression is nullable always supplies a match at byte zero, even when a nonzero outer count encloses a nullable alternative. Within this class the first-party position matcher handles literals, dots, bracket expressions, groups, alternatives and bounded or unbounded repetition. Each repeated byte carries its consuming position. A suffix inside another repetition can share a position with an earlier copy, which lets either occurrence consume a byte and select its own following positions. This reproduces both public examples above.

The position matcher handles up to 255 consuming positions and 511 intermediate nodes. Each active-position set uses four 64-bit words. Larger trees and raw subgroup requests that need historical ranking can use the compatibility provider.

For a repeated captured byte followed by a bounded positive suffix, the winning subgroup can change the whole span. On `1x12345`, `([[:digit:]])+.{2,4}` matches bytes [2,7) and its last digit capture occupies [4,5). Removing the capture from the same expression yields [0,5). With the capture, two paths ending at byte 6 compete for the same start and the better subgroup replaces the earlier whole match. The first-party matcher preserves this result for `(A)+B{m,n}` with byte atoms A and B, an expression of at most 255 bytes, and 1 ≤ m ≤ n ≤ 255. It retains the origin of each possible split in the bounded suffix window and returns the winning whole span and subgroup.

A match-existence query can combine every possible start. A later start can replace an already saved Windows match only when another arrival at the same end improves the subgroup ranking. The matcher retains the earliest origin at every active position and distinguishes a single accepting arrival from competing arrivals. Earlier starts are visited first. An acceptance at the saved or an earlier start resolves the whole span directly. If the result still depends on subgroup ordering, the existing ranked matcher or legacy provider decides it.


In the position matcher, copying a positive bracket consumes one internal slot per listed term. A negated bracket uses the gaps between the explicit excluded ranges, with named exclusions applied to each gap. A zero repetition discards its subtree while retaining the original numbering of subsequent source atoms. These rules preserve the Windows answer when a later counted interval shares positions with earlier terms.


The position matcher can also prove an internal subject anchor unreachable when a byte must precede a start assertion or follow an end assertion. It preserves the consuming positions on both sides of the failed path. The same consuming positions also remain available when other branches carry live assertions.

A repeated group made of fixed-width blocks can also replace an earlier match. For example, `((..){1,3})+` matches `ab` in `abc` and `bcde` in `abcde`. Once two blocks fit in a run, two capture histories become available. The trailing partial block shifts the start while keeping the longest complete-block length. The first-party matcher recognizes equal-byte-set blocks with this structure. A leading single-byte alternative can be excluded for a subject that contains none of its bytes.

The same bounded suffix window can recover a whole span after an optional bounded prefix. For example, `(((b)?){2})?([abc]){2,4}` selects `bbba` in `abbba`. Eligible starts include an empty prefix at each split until the first match ends. Two splits can subsequently compete through the captured prefix.

A leading word-boundary alternative can compete with the repeated choice of a nullable byte capture and a fixed-width block. When the nullable byte is absent, the first boundary or complete block limits the set of eligible starts. Trailing empty mandatory repetitions decide which later starts can replace the previous match. For example, `(\B|(((a){0,3}|([^ab]){2})){2,4})` matches the last two bytes of `xxx` on Windows. Mixed inputs containing the nullable byte still use the legacy provider.

The flat matcher also reports raw subgroups when every capture encloses the complete expression or every captured span has a fixed byte offset. Those groups either share the whole match or use offsets calculated once during compilation. The tagged matcher can also report variable interior captures when their boundaries are unambiguous.

For eligible flat expressions the hosted interface supports BRE and ERE, including `REG_ICASE`, `REG_NEWLINE` and `REG_NOSUB`. The compiled object retains these flags when it needs the legacy retry for a resource limit. In no-submatch mode the caller’s match array remains untouched.

Escaped consuming atoms can enter the same flat matcher, including Windows shorthand classes and escaped BRE groups. Hex escapes retain their exact byte in case-insensitive mode. Negated shorthand classes exclude a newline in newline-sensitive mode.

Flat sequences and alternatives also support subject and word assertions. In newline-sensitive mode, internal line boundaries can satisfy a subject anchor even when the caller suppresses beginning-of-subject or end-of-subject matches.

Empty patterns, empty alternatives and captures around an empty expression retain their zero-length spans in the flat matcher.

Variable-width interior captures can use the tagged matcher when each variable-width atom has a disjoint boundary with the next reachable byte sets. This covers separated fields such as `([a-z]+)-([0-9]+)` and preserves the actual offsets of both captures. Overlapping fields keep their previous routing.

Groups may also follow an initial byte sequence, as in `item([[:digit:]])+`, or appear in a later top-level alternative. The position matcher applies the same expansion and origin checks to the entire expression.

The position matcher can combine all six subject and word assertions in a grouped expression. Its context table contains only truth combinations that can occur at a subject endpoint or between two bytes. Repeated uses of the same assertion share its truth value. Counted copies preserve Windows’ preference for the first syntactically nullable arm. For example, `(a|$){1,2}` matches the empty subject unless the caller supplies `REG_NOTEOL`. A repeat of a single assertion tests it once, except when a zero-minimum counted tail takes the empty alternative first. For example, `(\B){2}` matches between the bytes in `ab`, while `(\B){0,2}` already matches at the beginning. For outgoing transitions, consecutive entries with the same destination preserve the predicate of their first occurrence. Copies of a zero-width group share its chosen empty path. Nested counted copies of a nullable group preserve the order in which their consuming positions reach the next byte.

Raw BRE callers can use backreferences to completed, nonempty fixed-width groups and variable-width captures with an unambiguous preceding separator. For example, `\([a-z]\+\):\1` matches `Ab:Ab` with `REG_ICASE`. The captured bytes are case-sensitive when read by the backreference. A potentially empty referenced group keeps its legacy behavior.

A fixed number of copies of a positive-width literal or bracket group also has fixed capture offsets. For `(id([0-9])){2}` on `id7id8`, the whole match covers both copies and the two subgroups contain `id8` and `8`.

Grouped extended expressions honor raw multiline and no-submatch flags. With `REG_NEWLINE`, line anchors also match adjacent to interior line feeds. Dot and negated brackets exclude line feeds, including inside counted groups. With `REG_NOSUB`, callers can pass a match array and its contents remain untouched. With `REG_ICASE`, counted groups preserve the consuming positions of both literal case variants and the opposite-case spans of a bracket range.

Grouped extended expressions also accept the Windows literal, hex, digit, whitespace and word escapes. A hex escape retains its exact byte in a case-insensitive pattern.

Basic regular expressions use the same position matcher, with escaped grouping, bounds, alternation and repetition operators. An unescaped question mark stays literal in basic mode. Backreferences still use the capture-aware path.
