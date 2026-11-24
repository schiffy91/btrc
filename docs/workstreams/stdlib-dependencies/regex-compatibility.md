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

For `REG_EXTENDED`, single byte sets, plain literal searches and their start/end assertions use first-party byte matching. This includes one simple or counted quantifier on a set. Capture-free sequences and nonempty alternatives made entirely from consuming byte atoms and one quantifier per atom can use the bounded first-party Thompson matcher. Its current eligibility check limits this latter class to expressions of up to 255 bytes and routes parentheses, escapes, assertions, stacked quantifiers and other syntax to the legacy provider. Those bounds apply to the capture-free Thompson matcher.

The compiled regex owns its pattern data. If the Thompson matcher exhausts its working memory or per-input work allowance, the dispatcher retries with the legacy provider. Both execution paths maintain the public `regex_t` layout and support compiling in one translation unit and matching and freeing in another. The dependency audit continues to name bundled Windows regex while this fallback remains.


The independently qualified bracket fix covers punctuation ranges that the Windows dialect accepts, including `[a-z--@]`. It restores a capability without changing nested-repetition semantics.

An unasserted ERE consisting of an outer optional or zero-minimum repeated group always supplies a match at byte zero. Within this class the first-party position matcher handles literals, dots, groups, alternatives and bounded or unbounded repetition. Each repeated byte carries its consuming position. A suffix inside another repetition can share a position with an earlier copy, which lets either occurrence consume a byte and select its own following positions. This reproduces both public examples above.

This implementation handles up to 63 consuming positions and 255 intermediate nodes. Brackets, escapes, subject assertions, zero-count removals, stacked quantifiers, requests for subgroup offsets and larger trees retain the legacy provider. It computes the longest reachable prefix with one read-only compiled table and a 64-bit active-position set. The optional empty prefix also lets a caller asking only whether anything matched receive its answer immediately.
