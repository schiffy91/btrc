# Windows Regex compatibility

`Library.Regex` specifies POSIX extended regular expressions and leftmost-longest byte spans. Programs can observe the chosen span through `Regex.first`, `fullMatch`, and replacement, even though the public API does not expose subgroup offsets. Keep the legacy Windows provider available while qualifying its replacement.

## A public difference

`Regex.fullMatch("((a{2})?b)?", "ab")` returns true on the legacy Windows provider. Under the written ERE the only complete strings are the empty string, `b`, and `aab`. A first-party matcher following those rules returns false.

The following case also shows the effect on an existing caller's output. Each column was exercised through the reference and self-host compilers in separate Windows x64 executables under Wine. Each executable passed the binary import audit.

With pattern `((b{1,3}){2,3}|.x){0,2}` and subject `ab`:

| Public call | Legacy Windows | First-party candidate |
| --- | --- | --- |
| `Regex.fullMatch` | true | false |
| `CompiledRegex.fullMatch` | true | false |
| `Regex.first` | `"ab"` | `""` |
| `Regex.replace` with literal `"X"` | `"X"` | `"Xab"` |

The left alternative requires at least two `b` bytes. The right alternative requires an `x`. Only the empty prefix satisfies the expression. In a generated comparison using the flags the public API actually passes, 46 of 842,486 cases differed. Independently enumerating every possible substring in leftmost-longest order gave the candidate's span in all 46.

## Preserving the old behavior

A compatibility implementation can reproduce at least one family without bundling the legacy source. For distinct literal bytes X and Y, consider the whole pattern `((X{n})?Y)?`, where n is 2 through 255. Start at byte zero, count the initial run of X bytes as k, and check the next byte. The observed legacy match includes those k bytes and the following Y when k modulo (n−1) is 0 or 1. Otherwise its match is the empty prefix. For n=4, k values 0, 1, 3 and 4 can precede Y, while 2 and 5 cannot.

A first-party btrc prototype encoded that rule. Separate Windows x64 executables from both compilers compared it against the legacy provider's `first`, `replace`, static and compiled `fullMatch`. Each passed 5,980 cases with n=2–24. A separate group-zero oracle exercised every n through 255, two choices of X and Y, and 62,396 cases. The tested rule covers only this grammar and group zero.

A broader compatibility engine would need to model which repeated consuming positions share outbound transitions, then verify the resulting whole spans and subgroup histories. The tests already exhibit interactions with alternation, trailing literals and optional and unbounded outer quantifiers. Loosening each interval independently would change which lengths the client accepts. For an incremental migration, a dispatcher could first select the replacement for validated expressions containing only a single literal or bracket expression and a single optional quantifier. Keep other syntax and invalid patterns on the existing provider until their spans and diagnostics are qualified. The dependency row stays open while any route uses the legacy provider.

The independently qualified bracket fix covers punctuation ranges that the Windows dialect accepts, including `[a-z--@]`. It restores a capability without changing nested-repetition semantics.
