# HTTP transport and Browser ownership draft

Status: **Revision 3, approval pending**, CX-P2-02; source baseline
`0214f3d8df9e0744e9656b32d3773755249b7e34` (2026-10-05). This document
proposes the Stage 26 interface freeze. It changes no production interface,
provider, build input, trust store or qualification result. CL-P2-01 must review
and approve it and record the decision in PLAN.md before implementation.
Provider descriptions below are requirements, not native execution evidence.

## Scope, sources and assumptions

The audited implementation is [HTTPClient](../../src/stdlib/HTTP/HTTPClient.btrc),
[HTTPSocket](../../src/stdlib/HTTP/HTTPSocket.btrc),
[HTTPServer](../../src/stdlib/HTTP/HTTPServer.btrc),
[HTTPFraming](../../src/stdlib/HTTP/HTTPFraming.btrc),
[HTTPRequest](../../src/stdlib/HTTP/HTTPRequest.btrc) and
[HTTPResponse](../../src/stdlib/HTTP/HTTPResponse.btrc). The eight
[Http corpus programs](../../src/tests/stdlib/) are mapped below. Policy comes
from [D22](../../PLAN.md), [adaptations rows 6 and 10 and Q1–Q10](platform-adaptations.md),
[CX-P1-02's recommended answers](../workstreams/codex.md#cx-p1-02),
[WORKSTREAMS Q15](../../WORKSTREAMS.md) and
[the implementation packets](../workstreams/codex.md#cx-p2-09).

These defaults are explicit **assumptions pending adaptation sign-off**:

| Decision | Assumption and consequence |
| --- | --- |
| Adaptations Q1 | Typed outcomes for new APIs; retain the existing HTTPClientResponse status/body/error surface through an adapter. Do not silently convert existing callers to exceptions. |
| Adaptations Q3 | Browser belongs in App, proposed `Library.App.Browser`; HTTP does not import App or GUI. |
| Adaptations Q7 | iOS HTTPServer is OS-restricted unless an identified journey requires a foreground listener. Android follows target API 36 permission policy and anticipates API 37 local-network permission enforcement. |
| Adaptations Q9 | HttpURLConnection over D22 JNI; no Cronet dependency. Cronet is an alternative requiring a changed answer, not an automatic fallback. |
| WORKSTREAMS Q15 / D22 | Linux links libcurl using pkg-config and the system CA store. No curl executable is required. |

CX-P2-11 step 2 currently requests a foreground iOS listener, whereas Q7's
recommended default is OS-restricted. CL-P2-01 must record that reconciliation:
this draft follows Q7, leaves the foreground branch conditional on a documented
journey, and does not claim the iOS server is available. The iOS transport is
available independently of a listener. Q3 is a recommendation, not permission
to edit the App contract before its owner approves it.

## Existing behavior that the seam must preserve

HTTPClient is synchronous. Its defaults are timeoutSecs = 120 and request and
response limits of 8,388,608 bytes each. The timeout setter and request path
clamp seconds to 1…86,400. Public fields remain validated at each call, so a
caller cannot bypass checks by assigning directly. The current process timeout
is the clamped network timeout plus a 1,000 ms child-cleanup allowance; that
allowance is not a second network budget.

`request(method, url, headers, body)`, `get` and `post` return
HTTPClientResponse; status zero denotes transport/validation failure and clears
the body. HTTP 4xx/5xx responses retain their status and body with empty error;
`ok()` means status 200…299. Null request body means empty body, but null headers
are an error. The original validation order and literal strings are:

| Order | Rejection | Existing error |
| --- | --- | --- |
| 1 | Method is not an HTTP token, or exceeds 64 | `invalid HTTP method` |
| 2 | URL fails requestTarget, or exceeds 8,192 | `invalid URL` |
| 3 | Scheme is not http or https | `unsupported URL scheme` |
| 4 | Either byte limit is negative | `HTTP size limits cannot be negative` |
| 5 | Response limit exceeds 2,147,483,582 | `response size limit is too large` |
| 6 | Null headers vector | `headers cannot be null` |
| 7 | A header fails headerLine | `invalid HTTP header` |
| 8 | Sum of header line lengths exceeds 65,536 | `HTTP headers are too large` |
| 9 | Non-null body's strlen exceeds maxRequestBytes | `request body is too large` |

### Revision 3 request admission (before any provider I/O)

The table above records the old implementation, not the new admission set.
The following changes are deliberate, versioned rejections on **every target**,
including the interim MacOS curl provider. Do not let a native API rewrite an
admitted request. Both string and Bytes paths use these checks; null body means
zero bytes, and string bodies retain their existing strlen boundary.

| Order | Admitted input / additional rejection | Literal error |
| --- | --- | --- |
| 1 | Exact uppercase GET, HEAD, POST, PUT, DELETE, OPTIONS or PATCH only; retain token/64-byte check first. TRACE, CONNECT, extension methods and lowercase spellings are rejected, not rewritten. | `invalid HTTP method` |
| 2 | Generic ASCII RFC 3986 URI syntax, valid percent escapes and length ≤8,192 only. Do not apply HTTP authority or userinfo rules here. | `invalid URL` |
| 3 | Scheme http or https, compared case-insensitively; other syntactically valid schemes retain this error. | `unsupported URL scheme` |
| 3a | HTTP authority, host, port, initial-fragment prohibition and canonical path/query rules below. | `invalid URL` |
| 4–6 | Existing limit and null-header checks, unchanged and in their existing order. | Existing literals above |
| 7 | Existing headerLine check, then client field-value bytes restricted to HTAB and ASCII 0x20–0x7e; reject 0x80–0xff, never reinterpret as UTF-8/Latin-1. | `invalid HTTP header` |
| 7a | For each otherwise-valid header, reject a provider-owned name case-insensitively. | `HTTP request header is provider-owned` |
| 7b | Reject a repeated caller header name case-insensitively; do not rely on platform dictionary coalescing or ordering. | `duplicate HTTP request header` |
| 8 | Existing running aggregate count after that header's 7/7a/7b checks. | `HTTP headers are too large` |
| 9 | Existing request-body byte limit. | `request body is too large` |
| 9a | GET and HEAD require an empty body; all other admitted methods may carry an empty or bounded nonempty body. TRACE is already rejected at 1. | `HTTP method does not permit a request body` |
| 10 | Additive options: maxRedirects must be 0…20; then check provider capabilities and pre-cancellation, in that order. | `invalid HTTP redirect limit`; capability/pre-cancellation use the typed mappings below |

The reserved names are Host, Content-Length, Transfer-Encoding, Connection,
Keep-Alive, Proxy-Connection, TE, Trailer, Upgrade, Expect and Accept-Encoding.
The provider emits `Accept-Encoding: identity`; it owns authority/framing and
hop-by-hop headers. A caller's `Expect:` suppression or Host override is rejected,
not silently stripped. The client-only ASCII rule does not narrow server-side
HTTPFraming or its existing byte-preserving parser. Header syntax/reservation
and running aggregate checks occur in input order; preserve that precedence
for multiply-invalid input. The 65,536 count currently excludes CRLF
separators; do not silently reinterpret it as a different wire-header budget.
After validating a field, the portable owner strips leading/trailing SP/HTAB
from its value and preserves the remaining ASCII octets, including internal
whitespace. Native setters receive that canonical value, not the raw header
line. Empty values remain present empty fields (curl uses its `Name;` form,
not the `Name:` form that removes a header). Exact field-value assertions below
compare this canonical value. OWS normalization and duplicate-name rejection
are versioned changes too; a provider unable to preserve an admitted value
returns unsupported before I/O rather than silently omitting it.
The response maximum retains the old upper bound even after the process marker
and its 64-byte capture reserve disappear, until a reviewed API revision.

The curl invocation restricts protocols to http/https but **does not use -L**.
The default therefore returns a redirect response and does not follow it.
There is no public redirect-limit or cancellation API today. The string request
body uses strlen; arbitrary embedded-NUL client bodies are not currently safe.
Server-side HTTPRequest.bodyBytes and HTTPResponse.bytes already preserve NULs.
The new seam must preserve those server guarantees and add a real byte-oriented
client path, rather than claim the old string client provided one.

HttpClientLocal currently creates a shell script called curl and inspects its
arguments, status marker and temporary files. It proves subprocess plumbing,
not TLS or native HTTP behavior. CX-P2-09 must replace this stand-in with the
real local endpoint tests while retaining validation and no-shell-injection
assertions. No existing assertion should be cited as native transport evidence.

## Selected module and proposed interface

HTTPClient owns portable validation, request snapshots, compatibility formatting
and convenience methods. A single target-selected HTTPTransport module owns
network execution. Selection uses manifest provider filters, never runtime
probing for an executable. Linux, MacOS, Windows, IOS and Android directories
are distinct; IOS cannot alias MacOS. Shared policy and byte conversion live
in portable HTTP files with no foreign SDK imports. Any new portable files need
the CX-P2-09 owner/CL-P2-01 scope recorded before editing them.

Every Linux facade consumer (including server-only `import Library.HTTP;`)
therefore needs libcurl development/pkg-config inputs **and**
BTRC_NATIVE_HEADER_READER, a matching explicit BTRC_NATIVE_TARGET triple and
BTRC_NATIVE_SYSROOT. The pinned dev shell supplies these; the harness and
stdlib README must document them for other consumers. This is a new build cost,
not just replacing a runtime curl executable with a transparent dependency.

The Linux-first transition retains an explicit MacOS legacy transport provider
that adapts the existing curl transaction for existing string calls until the
separately approved NSURLSession step lands. Its temporary contract and
qualification limits are specified under interim availability below.

This revision chooses the **link-plan-aware corpus harness route**. The facade
keeps importing HTTPClient, and Http, HttpFramingSafety and HttpClientLocal stay
in the corpus. Consequently even facade/server-only imports may require the
selected provider's build dependency. Before the seam lands, a Claude harness
packet must make runner.py consume pkg-config, frameworks, native/adapter units
from the link plan in both frontend paths and all eight strict test-c11 cells,
and supply bounded run-environment and fixture-lifecycle hooks for PATH
scrubbing and the real local endpoint. Today's runner links only
its fixed libraries and cannot satisfy this design. No provider PR may land
first and knowingly break make test or test-c11. Native transport suites remain
additional coverage, not a substitute for those corpus gates.

The following are proposed logical shapes, not new language declarations:

| Shape | Contract |
| --- | --- |
| HTTPTransportRequest | Immutable admitted method, canonical URL components, ordered ASCII headers, provider-owned copy of the mutable Bytes payload, maxResponseBytes, one monotonic deadline, redirect policy, retained BackgroundJobCancellation reference, trust policy. No borrowed caller buffer may outlive the call. |
| HTTPTransportOutcome | Final HTTP status, exact body Bytes, typed failure category, native diagnostic domain/code, and compatibility code. On failure status = 0 and body is empty. Native localized prose is diagnostic data, not the stable error string. |
| HTTPTransport.perform(request) | Blocking operation on a non-UI caller (a CLI main thread is allowed); exactly one terminal outcome. Provider owns handles, callbacks and native buffers until quiescent cleanup. |
| HTTPRequestOptions | Additive options for maxRedirects (default 0), optional BackgroundJobCancellation and normal system trust. A null cancellation reference means no cancellation. Test trust is fixture-only and absent from normal public configuration. |
| HTTPClient.requestBytes | Additive method using Bytes plus options and returning exact bodyBytes with typed failure information. The existing string methods adapt to the same seam and keep their return type and messages. |

The precise spelling and placement of the additive types is a freeze decision
for CL-P2-01. Existing signatures stay unchanged; btrc has no overloading.
`requestBytes` is the new distinct method, with a trailing defaulted options
parameter if approved. Claude freezes exact btrc spelling in its merge review
of the CX-P2-09 seam before CX-P2-10/11/12 begin. The string adapter snapshots bytes up to the existing NUL terminator and
converts the response through the existing strict `toString()` semantics, not
`toStringLossy()`, with the legacy embedded-NUL response mapped to invalid status; limits always count
all received bytes before conversion. Arbitrary binary consumers use bodyBytes.
Neither buffer contains a fabricated curl status trailer.

HTTP depends downward on Bytes, Timer and native provider bindings, not App,
GUI or a compiler-import module that would introduce a reverse dependency.
No global TLS settings or process signal handlers are changed. The btrc layer never retries a failed request, including an uncertain POST.
Native connection-reuse retries must be disabled or independently qualified;
providers use fresh transactions/connections when needed to prevent replay.
A stale keep-alive POST fixture must prove one server observation, or block
that provider's acceptance.
Linux explicitly follows libcurl's standard proxy environment variables,
with no credential values in diagnostics; Windows uses
WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY. Other rows use OS policy. Hermetic fixture
connections select direct routing through a test-only capability;
production proxy behavior is therefore a documented adaptation per provider;
proxy selection is recorded in diagnostics without credentials. Hermetic tests
select direct connections explicitly, with proxy environment variables removed.
Automatic cookie persistence and credential dialogs are disabled; callers pass
explicit headers. These explicit cross-provider policies require approval where
they differ from a platform default or ambient curl configuration.

### One portable URL parser and origin identity

CX-P2-09 owns proposed `HTTP/HTTPURLTarget.btrc` (CL-P2-01 adds the owned path
and its final HTTP/btrc.toml export fragment), a single RFC 3986 parse/resolve
owner. Reuse HTTPUrl's percent-encoding ownership and HTTPFraming.hexVal rather
than add a second percent codec. HTTPUrl.decode is a form codec (`+` becomes
space), so it must not decode a complete URI component; HTTPURLTarget owns
component grammar and canonicalization, not a duplicate general codec.
HTTPFraming's server behavior remains unchanged. Initial URLs and each Location
pass this owner before dispatch. It emits canonical scheme, ASCII host,
effective port, ASCII encoded path and optional encoded query (including the
distinction between absent and empty query). Native URL construction must
round-trip **all** these components, not just host/port. If the SDK cannot expose
or preserve that representation, return HTTP_FAILURE_UNSUPPORTED before I/O;
do not repair the URL again. Credentials never come from userinfo.

| Input | Frozen proposal / common two-frontend and every-provider case |
|---|---|
| Generic syntax / scheme | Row 2 recognizes a generic RFC 3986 URI, including `file:///etc/passwd`, `mailto:a@example.test`, `javascript:alert(1)` and `ftp://u@h`. All four reach row 3 and fail with `unsupported URL scheme`, not HTTP authority/userinfo validation. |
| HTTP authority | Row 3a: lowercase scheme and DNS host; authority required; absent port means 80/443; explicit decimal port must be 1–65535 |
| Userinfo | reject with `invalid URL`; deliberate versioned change from curl's implicit Basic authentication |
| Fragment/backslash/control | Initial fragments fail at 3a. Strip a redirect Location's fragment before resolving/transmitting (RFC 9110 §10.2.2); a fragment-only redirect resolves to the same resource and consumes a hop. Reject backslashes, raw whitespace and controls; no native-parser repair. |
| DNS/IDN | accept bounded ASCII DNS names and canonical IPv4; reject percent escapes in host and non-ASCII/IDN until one reviewed IDNA owner exists; reject ambiguous numeric IPv4 spellings |
| IPv6 | require bracketed RFC 3986 literal; parse numeric address and serialize one lowercase compressed form; reject zone identifiers; origin equality uses numeric address |
| Path/query | Empty path becomes `/`. Path admits RFC 3986 pchar plus `/`; query admits pchar plus `/` and `?`. Reject raw non-ASCII and characters outside that grammar (including quotes, angle brackets, backtick, braces, pipe, caret and raw brackets). Validate %XX, uppercase hex; decode escaped unreserved octets, then remove dot segments in the path. Preserve all other escaped octets, including `%2F`, `%25` and encoded UTF-8; never turn `+` into space. Percent-encoded dot normalization is explicit portable policy, preventing Android from making a second differing decision. |
| Relative Location | RFC 3986 section 5 resolution against last canonical URL; reject invalid authority/port/userinfo before origin comparison; scheme-relative references allowed subject to downgrade policy |
| Origin | canonical scheme + canonical host/address + effective port; default-port spellings compare equal; no suffix/prefix comparison |

URL length remains 8,192 bytes before and after canonicalization. Case tests
include `:0`, `:65536`, empty ports, bracket mistakes, encoded hosts, Unicode,
userinfo with passwords, mixed-case/default-port origins, escaped slash/dot,
relative query, network-path Location and HTTPS downgrade. Every changed
accepted-input behavior is in the versioned-break list below, not just
ambiguous spellings. Native URL round-trip and a raw endpoint's observed
request-target must equal the portable owner's bytes on each selected SDK.

| Provider | Canonical request transmission |
| --- | --- |
| Linux libcurl | Set the canonical URL and CURLOPT_PATH_AS_IS; no URL globbing exists in the library. Explicit method/body options must not let POSTFIELDS change GET/HEAD or any other method. |
| Apple | Set NSURLComponents.percentEncodedPath and percentEncodedQuery, preserving absent/empty query; compare the resulting components before creating/resuming the task. Never feed unescaped caller text to a repairing NSURL initializer. |
| Windows | ASCII-to-UTF-16 conversion is one code unit per admitted byte. WinHttpOpenRequest uses WINHTTP_FLAG_ESCAPE_DISABLE and WINHTTP_FLAG_ESCAPE_DISABLE_QUERY, plus SECURE for HTTPS. Native object-name bytes must round-trip; no implicit re-escaping. |
| Android | setRequestMethod receives the exact admitted method. Never setDoOutput for GET/HEAD. Use fixed-length output for POST/PUT/PATCH (including zero length) and nonempty DELETE/OPTIONS; zero-body DELETE/OPTIONS need no output stream. Prove OkHttp's canonical encoded path/query equal the portable result, including escaped dots/slashes and query punctuation. Refuse any unsupported SDK method/representation before connect, never retry as another method. |
| Interim MacOS curl | `-q` is the first argument, followed by `--globoff` and `--path-as-is`; pass the canonical URL after `--`. No ambient curlrc may enable insecure TLS, redirects, cookies or alternate URL expansion. |

Caller header value bytes have an ASCII-only conversion on wide/string APIs.
The wire cases compare method, encoded request-target and each admitted caller
field's value octets; they do not pretend HTTP/2 header names/order or native
framing headers are byte-identical to HTTP/1.1. Any provider that changes a
caller field's semantics must reject that capability before I/O and record the
adaptation; silently joining/dropping fields is not parity.

### Bounds, redirects and deadlines

Request snapshots are bounded before starting native work. Response bytes are
counted with overflow-safe arithmetic before appending each chunk. Limit zero
accepts an empty response only; exactly-limit succeeds, limit-plus-one fails
without exposing a partial body. A declared Content-Length may reject early,
but cannot replace incremental enforcement for chunked, absent, lying or decoded
lengths. Bound headers separately in the provider: proposed 65,536 response
header bytes per hop, measured as reconstructed `name: value\r\n` byte
strings (including repeated values), with a distinct HTTP_FAILURE_HEADER_TOO_LARGE
failure. This is not a raw wire-byte bound on Apple/Android header maps. This new response-header bound needs explicit CL-P2-01 approval.

Transfer framing is decoded once. Accept-Encoding is provider-owned and every
provider sends identity. Disable optional decoding in libcurl and WinHTTP;
the explicit identity header disables Android's transparent gzip negotiation.
**Frozen Apple adaptation:** NSURLSession may decode unsolicited content codings
even after identity was requested. On Apple, bodyBytes and limits count the
delivered decoded bytes; on the other providers an unsolicited coding remains
encoded. Record received Content-Encoding, delivered representation and provider
in diagnostics; the API does not promise equal body bytes for a server ignoring
identity. Test this divergence and each provider's incremental limit explicitly.
It is not an unresolved freeze decision or permission to accept caller gzip.
No provider may buffer an unbounded
response before enforcing the limit (including an NSURLSession completion-only
data task). Streaming delegates/read callbacks enforce bounds during receipt.
Retained memory is O(maxResponseBytes + bounded headers/buffers), not an exact
capacity promise: Bytes may geometrically allocate. Never mutate Bytes or a
compiler-import module to claim an exact bound; an exact-capacity API would be
a CL-P1-20 request with its bootstrap gate. Request Bytes are copied into native
provider-owned storage before concurrent access; Bytes itself remains mutable.
Retain only a bounded body and separately bounded native read buffers;
headers and diagnostic buffers also have independent bounds.

maxRedirects = 0 means no follow. An explicit positive value admits at most that
many additional requests; proposed range 0…20, invalid values rejected before
I/O. Exhaustion is HTTP_FAILURE_REDIRECT_LIMIT, not the last redirect reported as success.
All hops share the original deadline and protocol allowlist. The portable policy
resolves relative Location values, rejects malformed locations, strips sensitive
Authorization/Cookie/Proxy-Authorization headers on an origin change, and rejects
HTTPS-to-HTTP downgrade. With following enabled: 303 becomes GET except HEAD;
301/302 convert POST to GET; 307/308 preserve method and bytes. Remove body
framing headers (Content-Length and Transfer-Encoding) when discarding the body.
Derive Host/authority from each canonical hop. The provider-owned header
validation applies to both no-follow and following requests; no caller Host
or framing override survives admission.
Replay uses the immutable bounded payload, never asks a caller to regenerate
a stream. Preserve the Location
response without following when maxRedirects is zero. Disable native automatic
redirects and apply this policy once; a later policy extension must be explicit.

The deadline starts when perform is admitted, includes DNS/connect/TLS/upload,
all redirects and receipt, and is never reset by progress. Each native timeout
uses the remaining budget; per-phase timeout APIs alone do not satisfy the total
deadline. The synchronous wrapper does not pump a nested GUI loop. Call it from
an I/O worker on mobile and in GUI applications; synchronous CLI main-thread
calls remain supported because they are not an App/UI executor. A main-thread synchronous
NSURLSession wait whose delegate uses that same thread is forbidden.

### Cancellation, completion and cleanup

Cancellation is an additive operation, not a claim about current HTTPClient.
A pre-cancelled request starts no I/O. Reuse the existing
`Library.BackgroundJobs.BackgroundJobExecutor` type `BackgroundJobCancellation`:
`request()` release-stores its Atomic<bool>, and `requested()` acquire-loads it
(BackgroundJobExecutor.btrc:65–73). HTTPRequestOptions retains that object for
the duration of perform; no new IO type or compiler-import edit is needed.
CL-P2-01 must reconcile mobile-storage.md's former IO placeholder to this named
owner before its consumers implement the shared cancellation choice.
The flag does not itself wake or close anything. The non-UI perform controller
checks requested() before admission and at most every **100 ms** while waiting,
then invokes the provider's native abort action. Managed token access stays on
that owning executor; callbacks use native retained state only.
Admission reserves R1/R2 native owner
references and terminal result storage. When checked callbacks are used,
CallbackState/CallbackRequest admission and drain rules apply. All native
buffers and the atomic flag remain retained by these existing relationships. Native callbacks touch retained native state,
not borrowed managed references or cross-thread non-atomic ARC. Managed result
construction happens on the caller's owning executor after a bounded native
snapshot transfer; a callback never invokes application UI code.

Completion, cancel and deadline race through one synchronized terminal decision.
The first terminal decision wins; cancel after success is a no-op. Cancel during
upload or after server-side commit means HTTP_FAILURE_CANCELLED locally, **not** proof the
server rolled back. The transport does not retry it. Provider teardown disables
new callback entry and drains existing entries before freeing storage; generation
checks inside freed storage are insufficient. Request close is idempotent.
Cancellation must interrupt blocked network work or use bounded remaining-budget
waits; a cancel flag examined only after the full response is not sufficient.

A 1,000 ms cancellation-observation target is proposed for local deterministic
fixtures, separately from the timeout deadline. Safe cleanup cannot free live
callback state just to meet that target: record a missed bound as a failed test
and retain the R1 native owner and any admitted R2 callback/data references until
quiescent. Underlying platform DNS/cancel
behavior must be measured before promising this as a universal latency SLA.
For blocking JNI I/O, disconnect/close and finite read/connect timeouts need a
retained R1 native owner; do not share a JNIEnv between threads. Obtain each
thread's JNIEnv only from the src/stdlib/Java thread key, never direct attach or
detach. DNS that cannot be interrupted (InetAddress or synchronous libcurl)
runs on a provider-owned native worker. The caller's monotonic wait can expire,
but retained native work is quarantined until actual quiescence. Bound admission
of such outstanding workers; timeout cannot allow unbounded orphan work.

| Provider | Observation, abort and sole cleanup owner |
| --- | --- |
| Linux | The perform controller owns the multi/easy handles; curl_multi_poll waits at most min(remaining budget, 100 ms), then the controller reads requested(). It removes the easy handle to abort and alone performs easy/multi cleanup after callbacks return. curl_multi_wakeup is optional for an already-qualified native wake source, never an action falsely attributed to a stored flag. A resolver fallback retains its separate R1 worker until it actually exits. |
| Apple | The perform controller polls its event at ≤100 ms and enqueues task cancel/session invalidation to the serial delegate owner. That owner serializes delegate entry and teardown; final didBecomeInvalidWithError establishes drain. R2 callback/data references release on the qualified release executor; R1 session/buffer ownership releases once after that drain. The controller never frees a task from under a callback. |
| Windows | The async WinHTTP controller waits on a native event at ≤100 ms. It alone calls WinHttpCloseHandle on request, connection and session, including cancellation. Callback storage and buffers remain until all registered HANDLE_CLOSING notifications and already-entered callbacks drain, as detailed below. |
| Android | A blocking native I/O worker owns the input/output/error streams and closes each exactly once in its finally path. A distinct native cancellation controller, signaled by perform's ≤100 ms token poll, alone calls disconnect() on the connection; it never closes the worker's streams concurrently. Each Java call uses its thread-key JNIEnv. The retained native R1 cleanup owner alone deletes connection/stream global refs after both worker and controller quiesce; each thread deletes its own JNI local refs. If disconnect cannot release blocked I/O promptly, bounded quarantine retains those owners, never a freed global ref or an unbounded new worker. |

The Android normal-completion path also signals the same cancellation controller
to disconnect once; the I/O worker does not become a second connection closer.
The native controller/cleanup service must be explicitly qualified by CL-P2-09,
including failure/timeout cleanup on the Java release thread. If this ownership
cannot be supplied, Android HTTP remains blocked; a shared JNIEnv or arbitrary
cross-thread ARC is not a substitute.

## Error normalization and compatibility

Preserve the existing public error channel. All validation strings above remain
literal. The common adapter retains `response body is too large`,
`curl returned an invalid HTTP status`, and the template `curl failed (exit N)`
for legacy callers, even on a native provider. The word curl in these messages
is compatibility vocabulary, not a claim that curl ran. Typed byte callers get
a semantic category and a native code separately. Never expose secret headers,
URL credentials or response bodies in failure diagnostics.

| Failure | Proposed typed category | Legacy mapping |
| --- | --- | --- |
| DNS / connection refused | HTTP_FAILURE_RESOLVE / HTTP_FAILURE_CONNECT | `curl failed (exit 6)` / `curl failed (exit 7)` |
| Total deadline | HTTP_FAILURE_TIMEOUT | `curl failed (exit 28)` |
| Certificate trust or hostname verification | HTTP_FAILURE_TLS_VERIFICATION with HTTP_TLS_TRUST / HTTP_TLS_HOSTNAME / HTTP_TLS_VALIDITY / HTTP_TLS_UNKNOWN reason | `curl failed (exit 60)` |
| TLS handshake failure other than verification | HTTP_FAILURE_TLS_HANDSHAKE | `curl failed (exit 35)` |
| Cancellation | HTTP_FAILURE_CANCELLED | `curl failed (exit 42)` (new reachable outcome) |
| Redirect exhaustion | HTTP_FAILURE_REDIRECT_LIMIT | `curl failed (exit 47)` (opt-in only) |
| Rejected redirect: malformed/non-http/userinfo target or HTTPS downgrade | HTTP_FAILURE_REDIRECT_REJECTED | `curl failed (exit 3)` (opt-in only; proposed normalization) |
| Receive / send failure | HTTP_FAILURE_RECEIVE / HTTP_FAILURE_SEND | `curl failed (exit 56)` / `curl failed (exit 55)` |
| Invalid/missing final status | HTTP_FAILURE_INVALID_STATUS | `curl returned an invalid HTTP status` |
| Incremental body limit | HTTP_FAILURE_RESPONSE_TOO_LARGE | `response body is too large` |
| New header bound / local provider failure | HTTP_FAILURE_HEADER_TOO_LARGE / HTTP_FAILURE_PROVIDER | Proposed codes 1001 / 2; 1001 deliberately avoids size-code 63; approval required |
| Admitted representation not preservable by the selected SDK, or additive capability unavailable on interim MacOS | HTTP_FAILURE_UNSUPPORTED | `curl failed (exit 4)` if reachable through a string request; typed Bytes outcome retains code 4. Interim MacOS additive calls have no existing string equivalent. |

HTTP status errors are not transport failures. Distinguish 401/403 from local OS
permission denial. A native error unknown to the common taxonomy stays
HTTP_FAILURE_PROVIDER with its domain/code; it is never guessed to be certificate or
permission failure from localized text. Additional errors observed during parity
testing extend the reviewed mapping, not ad hoc per-provider text.

There is a real legacy ambiguity: capture overflow (ChildProcess code 125) maps
to `response body is too large`, while curl's own --max-filesize failure can
produce `curl failed (exit 63)`, including streaming overflow in curl ≥8.4.
Revision 3 versions a common normalization: **every** declared or incremental
body-limit failure becomes `response body is too large` and
HTTP_FAILURE_RESPONSE_TOO_LARGE, including legacy curl exit 63 and capture 125.
There is no per-provider split based on when Content-Length became known.
CL-P2-01 must approve the removal of the old size-code-63 distinction.
Likewise arbitrary executable exit codes have no exact cross-OS equivalent;
the compatibility code table is a proposed finite normalization, not a promise
to reproduce every subprocess failure. Compare old and new diagnostics with
fixtures before removing the old implementation. Pin legacy regressions for
an embedded-NUL response (invalid status), strict toString vs lossy conversion,
ChildProcess expiry code 124 (`curl failed (exit 124)`) versus curl's own
network timeout 28. Normalizing the native total deadline to 28 as above is a
deliberate compatibility change requiring approval. Existing string signatures
have neither cancellation nor redirect options, so codes 42/47 and redirect
rejection are only new typed requestBytes outcomes (with compatibility codes).
This draft introduces no unnamed string-options adapter or overload.

TLS reason sources: libcurl verify-result plus CURLcode; Apple NSURLError and
SecTrust result; WinHTTP secure-failure flags (invalid CA/CN/date); Android
certificate exception/cause through checked JNI. If the platform cannot
reliably distinguish a cause, HTTP_TLS_UNKNOWN preserves the native domain/code;
never classify by localized exception text.

## Native providers

| Target / packet | Provider obligations |
| --- | --- |
| Linux / CX-P2-09 | libcurl >=7.85.0, linked using `pkg-config libcurl`; initialize once behind a once guard, never call curl_global_cleanup from the provider. Use multi with ≤100 ms curl_multi_poll, controller cancellation, CURLOPT_NOSIGNAL=1 and CURL_VERSION_ASYNCHDNS or the bounded quarantined resolver-worker fallback. CURLOPT_PROTOCOLS_STR/http,https, explicit redirect policy, write callback limits and total remaining timeout. Keep peer verification enabled and hostname verification at 2. Use the system CA bundle; no bundled private production roots or curl process. |
| macOS / CX-P2-09 | Ephemeral NSURLSession with no URLCache, cookie store or credential store and a private serial delegate queue and incremental data delegate, bounded native buffer, task cancel and explicit redirect delegate policy. Synchronous worker wrapper waits independently of that queue. Default OS trust/hostname evaluation; no accept-all challenge handler. Interop requires CL-P2-07/Stage 29 or an approved native-only transaction. Invalidate the session on every path; didBecomeInvalidWithError is final quiescence. ATS stays enabled for unbundled executables; blocked cleartext is an explicit policy adaptation until an approved packaged-host exception exists. |
| iOS / CX-P2-11 | Separate IOS module over NSURLSession, sharing portable HTTP policy only; same bounds/cancel/TLS behavior as macOS. No process spawning, no UI-thread wait, no assumption that suspension preserves a live request. ATS remains enabled; cleartext fixture exceptions belong to the test host only. |
| Windows / CX-P2-10 | **WINHTTP_FLAG_ASYNC only**, Schannel, in a static-inline HTTP/Windows transaction header. A single native status callback and retained native context drive bounded reads; the perform controller is the sole WinHttpCloseHandle caller. The state machine and final HANDLE_CLOSING drain below are mandatory, not an optional async alternative. Explicit redirects, escape-disable flags and total remaining deadline; no certificate-ignore flags. |
| Android / CX-P2-12 | HttpURLConnection/HttpsURLConnection through CL-P2-09 JNI; exact admitted method/body rules above, fixed-length output only on permitted methods, bounded input/error-stream reads (HTTP 4xx body is valid), finite timeouts plus total deadline, redirects disabled for portable handling. Default TrustManager and hostname verifier. Separate I/O stream owner and disconnect controller as above; JNIEnv only through the Java thread key, exactly-once ref release. INTERNET required; no release cleartext opt-in. |

Linux's static-inline HTTP/Linux header supplies typed curl setters and C
write/header/xferinfo callbacks into bounded native buffers and native
transaction cancellation/terminal state mirrored by the perform controller.
They never inspect the managed BackgroundJobCancellation or its private atomic;
never bind curl_easy_setopt variadics directly. Define CURL_DISABLE_TYPECHECK
before curl headers in this adapter: GCC's curl typecheck statement-expression
macros are not the strict-C11 contract. The adapter's concrete typed setters
instead enforce long/off_t/pointer/callback option types, with negative compile
fixtures and all gcc/clang O0–O3 cells using
`-std=c11 -pedantic-errors -Wall -Wextra -Werror`. Do not suppress pedantic
warnings or rely on system-header treatment of a macro expanded in the adapter.
CURLOPT_NOSIGNAL does not itself eliminate TLS-backend
SIGPIPE: preserve the caller's disposition and qualify the backend/thread-local
suppression route with peer reset during upload under default SIGPIPE; a backend
that terminates the process fails acceptance and needs a concrete request.

Pin HTTP/1.1 where supported; record negotiated protocol where NSURLSession
cannot force it. Suppress optional Expect: 100-continue on all providers; a stack
that cannot do so must be classified and approved before claiming parity.
No provider adds an application User-Agent; documented platform-inserted values
must be recorded as an adaptation rather than promised identical. Explicit
Authorization/Cookie headers must be proved with automatic credential/cookie
stores disabled; native reserved-header interference blocks that row's parity.

Platform API references for implementation review:
[libcurl easy options](https://curl.se/libcurl/c/curl_easy_setopt.html),
[libcurl error codes](https://curl.se/libcurl/c/libcurl-errors.html),
[URLSession](https://developer.apple.com/documentation/foundation/urlsession),
[URLSessionDataDelegate](https://developer.apple.com/documentation/foundation/urlsessiondatadelegate),
[WinHTTP overview](https://learn.microsoft.com/en-us/windows/win32/winhttp/about-winhttp),
[WinHTTP errors](https://learn.microsoft.com/en-us/windows/win32/winhttp/error-messages),
[HttpURLConnection](https://developer.android.com/reference/java/net/HttpURLConnection).
These references identify API owners; this draft's test matrix must still prove
the behavior on each selected SDK and host.

### Windows async request and final drain

CX-P2-10 step 2 must be amended to this model. There is no synchronous fallback
cancelled by closing from another thread: Microsoft's
[WinHttpCloseHandle contract](https://learn.microsoft.com/en-us/windows/win32/api/winhttp/nf-winhttp-winhttpclosehandle)
explicitly forbids that synchronous-request race.

1. Allocate bounded native request state under R1 before creating an async
   session. Register a single native status callback inherited/configured on
   every owned handle, with native context retained before issuing work. Its
   mask includes the required async completion statuses, SECURE_FAILURE,
   REQUEST_ERROR and WINHTTP_CALLBACK_FLAG_HANDLES (for HANDLE_CLOSING), with
   a non-NULL context on each registered handle. Never unregister the callback
   before the closing drain. Failure to establish callback/context
   ownership aborts setup before network I/O; handles with no registered
   callback/no submitted work are closed by this same owner without awaiting
   a notification they cannot produce.
2. The non-UI perform controller issues async send/receive/read/write operations
   serially. At most one bounded read or write buffer is in flight for a request;
   it remains owned until the matching completion/error and final drain. Use
   async-safe output arguments (for example NULL for ReadData's byte-count
   pointer); never hand WinHTTP a pointer into an expired caller stack.
3. The callback copies bounded status/error data into native synchronized state
   and signals a native event. It neither invokes managed application code nor
   closes handles nor recursively starts another read. Immediate API failure
   and callback completion both enter the same terminal-decision state machine;
   synchronous callback delivery during an async API call must also be safe.
4. The controller waits for min(remaining deadline, 100 ms), observes the token,
   and drives the next operation. WinHttpSetTimeouts uses the remaining budget
   for SDK phase limits; the controller enforces the total deadline. A short
   receive timeout is **not** used as resumable polling, because it kills the
   request. Completion/deadline/cancel each stop admission of further I/O.
5. The controller is the **only** WinHttpCloseHandle caller. It closes request,
   connection and session once, leaf first. Each registered handle has its own
   closing flag and pending callback count. Retain R1/context/read/write buffers
   until HANDLE_CLOSING has arrived for every registered handle **and** all
   entered callbacks have returned (R2 count zero); merely seeing the final
   notification inside a still-running callback is not drain. No callback or
   external cancellation thread frees this storage. A slow final drain retains
   bounded quarantined native ownership, never frees context to meet a timeout.

SECURE_FAILURE callback flags map CERT_CN_INVALID to HTTP_TLS_HOSTNAME,
CERT_DATE_INVALID to HTTP_TLS_VALIDITY, and INVALID_CA/CERT_REVOKED to
HTTP_TLS_TRUST. When several are present retain the full bitmask and choose the
first in that listed order. Other/undifferentiated causes use HTTP_TLS_UNKNOWN;
secure-channel failure without a verification indication remains
HTTP_FAILURE_TLS_HANDSHAKE. Native error domain/code and flags stay diagnostic.
No localized string matching or certificate-ignore flags are allowed.
See [status callback](https://learn.microsoft.com/en-us/windows/win32/api/winhttp/nc-winhttp-winhttp_status_callback),
[WinHttpOpenRequest flags](https://learn.microsoft.com/en-us/windows/win32/api/winhttp/nf-winhttp-winhttpopenrequest)
and [WinHttpReadData](https://learn.microsoft.com/en-us/windows/win32/api/winhttp/nf-winhttp-winhttpreaddata).

### SDK constraints and target classification

Android's method allowlist and GET→POST rewrite come from
[AOSP HttpURLConnectionImpl](https://android.googlesource.com/platform/external/okhttp/+/refs/heads/main/okhttp/src/main/java/com/squareup/okhttp/internal/huc/HttpURLConnectionImpl.java)
and [HttpMethod](https://android.googlesource.com/platform/external/okhttp/+/refs/heads/main/okhttp/src/main/java/com/squareup/okhttp/internal/http/HttpMethod.java).
[Headers](https://android.googlesource.com/platform/external/okhttp/+/refs/heads/main/okhttp/src/main/java/com/squareup/okhttp/Headers.java)
also documents Android's UTF-8 behavior; that is why client header admission is
ASCII, not an unsupported claim that Java rejects every high byte. Apple GET
bodies can fail with NSURLErrorDataLengthExceedsMaximum (-1103); rejecting them
portably is preferable to a changed verb or provider-dependent result. Record
the actual SDK/OS revisions in the wire test evidence, not just these moving
source links.

`windows-aarch64-msvc` exists in targets.toml, but ModuleProvider currently
filters only OS/architecture and NativeBindingResolver accepts Windows GNU
triples only. **This design does not support MSVC.** Before any Windows provider
row lands, CL-P1-14/15 plus the native-import request must supply an
environment-aware missing classification for MSVC (or separately qualify full
MSVC native imports). A broad `windows` provider row selecting a GNU header on
MSVC is not acceptable. Both frontends need a deterministic unsupported-target
diagnostic and applicability classification, rather than accidental SDK-reader
failure. Do not claim an existing os/arch/env filter or hide this behind a skip.

## Winsock server and socket ownership

CX-P2-10 ports socket operations, not the shared HTTPFraming parser into a second
parser. Its network owner pairs successful WSAStartup(2.2) with WSACleanup after
the final listener/connection and bounded registry borrow count drain. Failed startup owns no
cleanup obligation. WSAStartup returns its error directly; subsequent socket
failures capture WSAGetLastError immediately, before any cleanup overwrites it.
SOCKET is pointer-width and INVALID_SOCKET is the invalid value: never truncate
a SOCKET into the existing public int fd or call POSIX close on it.

The current server exposes int fd, acceptConn and closeConn. Proposed compatible
Windows surface uses nonnegative opaque int tokens backed by a bounded registry
of SOCKET owners; -1 remains failure. Tokens are never native descriptors.
Use bounded slot-plus-generation tokens; retire a slot before generation wrap,
rejecting admission on exhaustion so stale tokens can never resolve anew. Borrowers increment the registry owner's in-flight operation count while resolving
a token. Concurrent close invalidates future lookup, signals operation
cancellation and wakes deadline-aware wait loops, then drains current work
before closesocket. Waking a borrower must not close or recycle its SOCKET
while it is still using it; do not rely on waiting out the full request timeout. A portable typed connection owner is preferable long-term,
but removing the int surface is a separate reviewed change. POSIX fd callers
remain POSIX-specific; Windows tests must not treat these tokens as HANDLEs or
CRT descriptors. CL-P2-01 must approve this compatibility boundary explicitly.

Freeze HTTPSocket's portable seam with Unix/ for linux/macos/ios/android and
Windows/ for windows; HTTPServer, including respond shutdown, calls only it.
Use WSASocketW with WSA_FLAG_NO_HANDLE_INHERIT and WSAEventSelect plus a cancel
event for deadline-aware waits; WSAEventSelect itself enables nonblocking mode.
An accepted socket inherits the listener's event association: immediately
re-associate it with its **own** WSAEVENT/mask before its first wait. Closing the
listener must not destroy an event an accepted connection is still using.
Drain the registry's in-flight count, closesocket once, then WSACloseEvent;
never recycle either while a borrower waits. WSAPoll alone is
not wakeable and shutdown does not wake accept. Concurrent public closeConn/stop
is not a portable contract; callers serialize server methods on their owner.
Windows internal cancellation does not imply POSIX thread-safe public methods.
WSAEWOULDBLOCK retries only after readiness; WSAEINTR retries within the same
deadline; FD_WRITE is re-armed only after send returns WSAEWOULDBLOCK, not by
waiting repeatedly on a stale writable notification. Reset/abort/timeout produce the existing false, -1 or empty-Bytes
failure channel with typed diagnostics internally. Short writes advance by the
actual byte count. A zero-byte receive is EOF, not another retry. Use
shutdown(SD_SEND) for successful response completion and closesocket exactly
once on owner close. Windows has no SIGPIPE; preserve the POSIX per-send
suppression and caller signal policy on those providers.

Set SO_EXCLUSIVEADDRUSE before bind; do not translate Unix SO_REUSEADDR into a
Windows port-sharing policy. Bind loopback by default, backlog 64, port 0 for
fixtures; discover the assigned port with getsockname while retaining the
listener, rather than reserve-close-rebind. All-interface opt-in carries row 6's
Windows Firewall warning. Sockets must not leak into child processes. Startup,
listener close, accepted-connection close and subsystem cleanup get independent
leak and double-close tests.

Keep server defaults (15-second timeout; 65,536 header, 8,388,608 body and
16,777,216 total request bytes), one absolute read/send deadline, binary framing,
Host requirements, conflicting Content-Length/Transfer-Encoding rejection,
chunk/trailer bounds, reserved response headers and body-forbidden statuses.
Replace POSIX socketpair/fork fixtures with target-native loopback equivalents
on Windows, without weakening their split-read, backpressure or no-progress
assertions. Android loopback listeners need INTERNET; non-loopback permission
states remain pending/denied/granted, following the target-SDK rule assumed above.
iOS's conditional foreground path must stop on suspension and respect local
network consent; an unsupported path uses the exact row 6 diagnostic, not a
silent transient false that suggests a free port would solve it.

### One additive server-start result

CX-P2-10 is the sole editor of HTTPServer.btrc for proposed `startResult` and
the selected `Library.HTTP.HTTPServerStartPolicy` module. Its `check` operation
returns a portable start-policy result before socket allocation; HTTPServer
maps actual bind/listen failures into that same startResult channel. This is
not a second socket owner. Add `HTTP/Unix/**` and this hook to CX-P2-10's owned
paths. CX-P2-11 and CX-P2-12 **depend on the CX-P2-10 hook landing** and replace
only their own provider rows/implementations. They cannot start against a
nonexistent portable method while claiming parallel independence.

| Selected module | Initial OS rows at the CX-P2-10 landing | Subsequent provider change |
| --- | --- | --- |
| HTTPSocket | linux/macos/ios/android → HTTP/Unix/HTTPSocket; Windows GNU → HTTP/Windows/HTTPSocket | iOS/Android retain the Unix socket owner unless separately approved |
| HTTPServerStartPolicy | linux/macos → HTTP/Unix/HTTPServerStartPolicy (allow existing desktop startup) | No mobile SDK import enters this owner |
| HTTPServerStartPolicy | ios → HTTP/Unix/HTTPServerStartPolicy (pure policy returns OS_RESTRICTED and exact row-6 diagnostic) | CX-P2-11 → HTTP/IOS/HTTPServerStartPolicy; Q7 remains restricted unless approved journey changes it |
| HTTPServerStartPolicy | android → HTTP/Unix/HTTPServerStartPolicy (pure policy returns PERMISSION_PENDING, no bind, until permission-aware provider is installed) | CX-P2-12 → HTTP/Android/HTTPServerStartPolicy; distinguishes INTERNET/loopback and applicable non-loopback permission states |
| HTTPServerStartPolicy | Windows GNU → HTTP/Windows/HTTPServerStartPolicy | Windows MSVC remains explicitly missing under environment-aware selection |

The interim Android diagnostic is `HTTPServer.start is unavailable on Android:
network permission has not been established; use the app's permission-aware
network provider` (one line in the API). CL-P2-01 must approve that temporary
PERMISSION_PENDING diagnostic and classify the server regression; it is not
a denial or an assertion that the OS always requires a runtime INTERNET prompt.
All four Unix rows compile without a mobile SDK; none leaves an import missing.
The iOS/Android server cells must describe these restrictions rather than claim
an active listener. No HTTPServerStartPolicy imports HTTPClient or HTTPTransport.

CL-P2-01 must amend the packet steps and integration rows accordingly.
Proposed outcomes are HTTP_SERVER_STARTED,
HTTP_SERVER_INVALID_PORT, HTTP_SERVER_ADDRESS_IN_USE, HTTP_SERVER_OS_RESTRICTED,
HTTP_SERVER_PERMISSION_PENDING, HTTP_SERVER_PERMISSION_DENIED and
HTTP_SERVER_FAILED, with diagnostic and warning strings and native error data.
Existing start() remains the bool adapter (true only for STARTED). It does not
write unsolicited stderr; callers needing explanations use the additive result.
Successful Windows all-interface binding carries row 6's exact warning; iOS
OS_RESTRICTED carries its exact row-6 diagnostic; Android permission pending is
neither denial nor success. Freeze and test byte-for-byte strings from
platform-adaptations.md through both frontends. No provider invents its own
error field or output channel. iOS server policy still awaits Q7 reconciliation.

## Curl-free endpoint and trust fixture plan

CX-P2-09 owns src/tests/native/http/ and test_http_transports.py. Build and run
through both frontends. A real BTRC HTTPServer loopback fixture serves text,
exact Bytes echo, 404 bodies, redirects and controlled sizes. A small raw
fixture supplements it for intentionally malformed responses, chunk splitting,
lying Content-Length and slow bodies; do not require HTTPServer.respond to
produce invalid framing. Parent/test process receives readiness and the live
listener's assigned port over a bounded control channel, never by sleeping or
parsing an uncontrolled log. All helpers have deadlines and finally cleanup.

A pytest-owned Python ssl TLS server uses a new per-run CA and leaf keys, with
openssl tooling pinned by CL-P2-04 on **each executing test host** (including
Windows and the Android host controlling its emulator). Generate keys on the
host running that job's TLS server, never on another CI job for artifact transfer.
Private keys never enter an APK, uploaded artifact or log; only public test
certificates are copied into the APK/configuration or disposable trust store.
Valid leaves have SANs matching the exact fixture
host/IP, serverAuth usage and a current validity interval, using RSA >=2048,
SHA-2 signatures and leaf validity <=825 days for Apple policy. Separate leaves cover
wrong hostname and expiry, and a distinct untrusted CA covers trust rejection.
Trust is scoped to the fixture, verification stays on, and private keys are
removed during teardown. No external service or public DNS is required.

| Target | Test-only trust mechanism |
| --- | --- |
| Linux | Per-request CURLOPT_CAINFO points to the generated CA bundle; peer and hostname verification stay enabled. Production continues to use system trust. |
| macOS / iOS | Fixture-only server-trust delegate supplies the generated anchor to SecTrust, applies the requested-host SSL policy, and evaluates chain, hostname and validity before returning a credential. Pin the test anchor, not any leaf received. No global keychain change and no unconditional challenge acceptance. |
| Windows | Elevated disposable windows-latest VM: install this run's uniquely identified CA in LocalMachine Root (CurrentUser Root can prompt and is rejected), capture its thumbprint, and remove exactly that certificate in finally. Register cleanup before networking starts; an outer process also cleans after child timeout. Verify absence after removal and a subsequent trust failure. Preflight elevation and non-interactive add/remove before networking; if unavailable, fail the fixture. If cleanup fails, fail and discard the VM. No dedicated user is assumed. |
| Android | Debug test APK network-security-config trusts only the generated test CA for the fixture configuration; release APK contains neither the CA nor the debug override. Standard TrustManager/hostname checks remain enabled. Debug cleartext exception covers local plain fixtures only. Per-run CA/config injection is a required CX-P1-09 / CL-P1-17 host capability; until confirmed and integrated, Android TLS-trust cases are unavailable, not passed with an app_process or accept-all fallback. |

Fixture trust enters through a GUIProviderRoot-style white-box export or
test-only binding; production providers accept no trust-override environment
variables. Android debug overrides may intentionally bypass certificate pinning; that is
not evidence for a production pinning feature. An app_process host does not
inherit an APK's network-security-config: use the APK host for those trust tests
or record them unavailable, never substitute an accept-all TrustManager.
iOS simulator host loopback and Android emulator host routing are different:
record the actual connection address/SAN (for example the emulator host alias),
bind only to the required test interface and verify endpoint identity. Physical
devices require their own reachable fixture arrangement and separate evidence.

| Case | Required assertion |
| --- | --- |
| HTTP-METHOD-* | All seven admitted methods, each with empty and nonempty input; GET/HEAD nonempty rejected before endpoint observation. TRACE/CONNECT/lowercase/extension methods rejected in row-1 order. Raw endpoint asserts actual method/body, especially Android GET never becoming POST. |
| HTTP-URL-* | ASCII pchar/query punctuation, percent escapes and unreserved/dot canonicalization, escaped slash/percent/UTF-8, absent versus empty query; raw bracket/brace/quote/high-byte rejection, all authority/origin cases above. Generic file/mailto/javascript/ftp inputs retain scheme-error precedence. Native encoded target and raw endpoint request-target match the portable result; native reparsing that cannot preserve it returns unsupported before I/O. |
| HTTP-HEADER-* | Each mixed-case reserved name including Accept-Encoding, high-byte rejection, edge SP/HTAB normalization, internal whitespace, present empty field, duplicate names and multiply-invalid ordering. Server compares canonical caller value octets and sees exactly identity coding; characterize platform-generated headers separately. |
| Text and arbitrary bytes | Every admitted body-capable method and Bytes echo including NUL/non-UTF8; empty, exact-limit and limit-plus-one payloads; server byte response arrives intact. |
| HTTP errors | 404/500 return body/status with empty transport error; ok() false. |
| URL/header policy | Every canonical URL case above; every reserved name in mixed case; conflicting framing; credential/cookie transport; default User-Agent and Expect policy. |
| Redirects | Default no-follow; each status/method rule; exact hop limit and overflow; loop; relative and fragment-only Location; cross-origin credential stripping; malformed/scheme/userinfo/downgrade rejection has typed REDIRECT_REJECTED/code 3. |
| Limits/framing | Declared and streaming overflow; chunked/unknown length; zero limit; fragmented header/body; no giant prebuffer; both old curl63/capture125 paths normalize to the same size string. Unsolicited gzip fixture explicitly expects Apple's decoded and other providers' encoded bytes, with limits applied to the delivered representation. |
| Time | Slow/blackholed resolver, slow headers, slow upload and drip-fed body cannot reset total deadline; blocked send times out; no retries of uncertain POST, including stale keep-alive reuse. |
| Cancellation | Before admission, during connect/read/upload, and completion race; one terminal outcome, bounded observation, resources drained, late callback safe. |
| TLS | Trusted valid leaf succeeds; wrong hostname, expired and untrusted leaves fail independently with verification enabled; HTTP cleartext cannot masquerade as TLS success. |
| Failures | Refused connection, deterministic DNS failure through an isolated resolver fixture or injected native resolution failure, truncated response, invalid status, OS permission state; stable categories and legacy strings. |
| Cleanup | Repeated success/failure/cancel cycles leave no request handles, sockets, JNI refs, native buffers, certificate-store entries or named capture files. Windows callback-at-close, setup failure, cancellation while read/write is pending, late callback and HANDLE_CLOSING-before-callback-return cases prove no second closer/use-after-free. Winsock listener stop while an accepted connection waits proves independent event ownership. |

Http, HttpUtil and HttpParseEdges retain pure parsing/utility assertions;
HttpFramingSafety retains validation and smuggling regressions; HttpParseBytes
and HttpBytesResponse retain NUL framing; HttpSocketIo retains deadline,
SIGPIPE-policy and short-I/O coverage on POSIX plus equivalent Windows cases;
HttpClientLocal becomes one provider-neutral real local-client corpus with a
single common golden, receiving the loopback endpoint from the bounded harness
fixture. Move the old PATH-shim/argv/status-marker checks into a **separate**
MacOS-legacy-only fixture under src/tests/native/http/MacOS, with a dedicated
Python driver and its own expected output. Do not use one golden for both a
shell stand-in and a network test. Both fixtures run on interim macOS; Linux
runs the common real endpoint corpus. New provider suites add
TLS, cancellation and redirect coverage absent from today's eight programs.

For each native transport being qualified, the no-executable proof must compile
first, then run the complete HTTP corpus
and provider tests with a minimal explicit PATH whose entries contain no curl
or curl.exe. Assert shutil.which('curl') is None and on Windows also check
curl.exe; use absolute paths for the test interpreter, compiled programs and
necessary helpers. Windows System32 on PATH would invalidate the proof.
Removing PATH cannot exclude absolute paths or Windows' System32 search.
For each frontend additionally inspect optimized IR/reachable link-plan units:
no HTTP-client path reaches ChildProcess, posix_spawn, execve or CreateProcessW.
This static reachability proof is mandatory; process observation is supplemental.
At **CX-P2-09's seam integration**, Claude re-points
test_stdlib_process_security.py's HTTPClient source constant and
`test_http_client_is_direct_and_protocol_restricted` to the moved HTTP/MacOS
legacy file, including its new `-q`/`--globoff` policy, and adds the native
both-frontend no-process proof. This cannot wait for a later harness follow-up
or silently remove the guard. The Linux binary may link libcurl;
that is the intended library provider. The endpoint may invoke openssl during
fixture creation, never to service a client request. Publish provider identity,
SDK/OS, trust mode, frontend, case counts, skip reasons and CI run IDs. A Linux
result does not fill Windows, macOS, simulator, emulator or device evidence.

### Interim availability and case accounting

The first Linux landing must also select a real MacOS legacy provider over the
existing curl implementation. Existing macOS string calls and their corpus
remain working; do not create an unconfigured MacOS row or silently skip that
previously supported surface. That temporary provider preserves current
subprocess transaction/status/body channel beneath the approved versioned
facade admission, size-error normalization and explicit `-q`/`--globoff`/
`--path-as-is`/identity-header policy. Its bounded header/body capture must also
enforce the new response-header bound; configuration whose required capture
size cannot be represented safely returns unsupported before I/O rather than
overflowing the old maxResponseBytes+64 arithmetic. This temporary capture
limitation is an explicit MacOS-legacy adaptation, tested at the arithmetic
boundary. It keeps its re-pointed direct-exec/protocol security guard and
separate legacy plumbing fixture, updating assertions for the approved changes.
It does not qualify the new
requestBytes/options/redirect/cancellation contract: those additive calls return
HTTP_FAILURE_UNSUPPORTED before I/O until the native provider lands.
CL-P2-01 must freeze that transitional outcome and amend the packet scope.
The existing string API has no new options, so this does not change its accepted
call shape. Common corpus coverage still runs on macOS; native-only new cases
get exact temporary capability rules approved by Claude.

The HTTPClient inventory's **macOS per-target reason** continues to say HTTPS
via curl; its single operation title is not edited per target. The no-executable/
no-ChildProcess proof applies only to Linux at this stage. Never claim macOS
curl-free or Stage-26 HTTP completion from that intermediate green run. The
NSURLSession landing atomically replaces this legacy provider, removes its
plumbing fixture/old process guard and temporary capability rules, updates the
inventory and enables the full macOS native corpus/no-process proof. There is
no automatic runtime fallback from a failed native request to curl.

Until their real providers land, windows/ios/android HTTPTransport rows remain
Stage-24 missing, not stub providers. Because the facade imports HTTPClient,
`import Library.HTTP;` now fails with `module ... has no provider for target`,
including server-only programs. The runtime row-10 unavailable diagnostic
cannot fire on those imports. This is an explicit temporary facade regression:
server-only users import Library.HTTP.HTTPServer and Library.HTTP.HTTPSocket
directly; codec users import the specific codec owner. The separate server
hook's complete interim rows above keep those direct imports buildable.

Claude supplies **target-applicability.toml restricted entries**, citing the
HTTPClient inventory row, for Http, HttpFramingSafety and HttpClientLocal on
the affected Windows/iOS/Android lanes. There is no invented iOS/Android
expected-skips manifest; that is not where Stage-25 applicability lives.
Update the stdlib README, per-target reason/regression cells and aggregate to
state the facade regression, and remove each restriction only in its actual
provider landing. iOS/Android server restrictions from the hook landing need
their own operation reason cells, including Q7's pending approval. None of
this is final Stage-26 acceptance or a successful runtime substitute.

Case IDs are stable by family: HTTP-METHOD-*, HTTP-URL-*, HTTP-HEADER-*, HTTP-BYTES-*,
HTTP-REDIRECT-*, HTTP-LIMIT-*, HTTP-TIME-*, HTTP-CANCEL-*, HTTP-TLS-*,
HTTP-FAILURE-* and HTTP-CLEANUP-*, with explicit frontend/provider parameters.
Implementation freezes the expanded case list/count before its first run; this
draft claims no numerical pass count. Publish selected/passed/skipped/failed
counts and exact skip rules per runner. Linux runs ci.yml corpus/unit/native
plan-aware suites; macOS uses macos.yml; Windows/iOS/Android use the provider
jobs from CX-P1-07/08/09, with test_windows_*, test_ios_* and test_android_* entry
modules. App-mode is required for Android trust configuration and mobile policy.

## Browser owner and implementation handoffs

Proposed `Library.App.Browser` owns OS URL dispatch, separately from HTTPClient.
`open(url)` returns a typed App outcome: accepted dispatch, invalid/unsupported
URL, unavailable handler, permission denial or platform error. Accepted dispatch
does not mean a page loaded or an authentication flow completed. A provider that
reports completion asynchronously must retain its admitted CallbackState and
R1/R2 native callback ownership and deliver
once on the App executor. Never shell-concatenate a URL. Validate before any
OS call; Windows allows only https: and ms-settings: per row 10. Other providers
start with https:, extending schemes only through an explicit reviewed policy.
OAuth callbacks belong to a dedicated authentication session owner.

| Packet | Handoff |
| --- | --- |
| CX-P2-09 | Land portable HTTP seam plus Linux libcurl with the explicit MacOS legacy provider and preserved corpus first; split MacOS NSURLSession into a separately approved dependent step and shared endpoint tests after approval/CL-P2-04/provider filters. Record the proposed App.Browser owner; this packet does not own a new portable App contract or promise Linux/macOS browser implementation. Request assignment for those providers. |
| CX-P2-10 | Windows HTTP and Winsock; App/Windows Browser provider uses ShellExecuteExW with verb open, validates allowed schemes and maps Win32 failure. Use the shared COM STA owner and SEE_MASK_FLAG_NO_UI|SEE_MASK_NOASYNC; do not initialize an unrelated apartment model. If requesting a process handle, close it; never wait for browser exit as page-load proof. |
| CX-P2-11 | Separate IOS transport and Q7 reconciliation. Browser remains missing until CX-P2-36 provides UIApplication; then UIApplication open on the main thread supplies its completion outcome. In-app Safari is a separate presentation choice, not transport fallback. |
| CX-P2-12 | Android HTTP and network permission fixtures; explicitly defer Browser to CX-P2-42. |
| CX-P2-42 | App/Android Browser through a visible Activity, Custom Tab where available or ACTION_VIEW, correct URI encoding, manifest <queries> where needed and ActivityNotFoundException handling. A background request is deferred/rejected according to App lifecycle policy, not a forced activity launch. |

## Requests and approval checklist

### Complete versioned-break and adaptation record

CL-P2-01's PLAN entry must enumerate the following; “preserves the existing
API” means return shape and explicitly retained messages, not an unchanged
accepted-input set or ambient curl behavior:

| Change | Approval record |
| --- | --- |
| Method/body admission | Seven exact uppercase methods; reject TRACE/CONNECT/extensions/lowercase and nonempty GET/HEAD at the stated validation positions |
| URI admission | Initial fragments, backslashes, raw whitespace/control/non-ASCII, invalid path/query characters, IDN/escaped hosts, non-canonical numeric IPv4 and IPv6 zones rejected; generic non-HTTP schemes retain row-3 precedence |
| URI canonicalization | Unreserved percent escapes decoded, dot segments removed, other escapes uppercase/preserved; absent/empty query retained; redirect fragment stripped |
| Headers | ASCII client values, portable edge-OWS trim, no repeated caller names, all reserved names including Host/Expect/Accept-Encoding; original line lengths still drive request aggregate limit |
| Content coding | Always identity; Apple unsolicited-coding decode is explicit and delivered bytes determine its limits; no false all-provider encoded-body equality |
| Bounds/errors | New 65,536 reconstructed response-header cap (smaller than curl's roughly 100 KiB header limit); codes 1001/2/4/3, total deadline28 rather than child124, all size63/125 normalized to the size string; new option/body/header literal errors |
| Cancellation/options | Existing BackgroundJobCancellation owner, bounded poll and named native abort/closers; typed requestBytes options only, no unstated string overload |
| Legacy MacOS | `-q` first disables curlrc; globbing disabled and portable path policy preserved; identity header and finite capture constraints are explicit; native-only new APIs unsupported |
| Provider policies | OS proxy differences, Apple ATS/protocol/default-header behavior, system trust and no automatic cookie/credential/replay policy remain documented adaptations requiring their fixtures |
| Build/interim availability | Linux facade imports need native reader/triple/sysroot and libcurl; missing mobile/Windows transport makes the aggregate facade fail at compile time; direct server imports remain possible with explicit start-policy restrictions |
| Target/server ownership | MSVC missing unless separately qualified; selected HTTPServerStartPolicy and complete interim Unix rows; CX-P2-11/12 depend on CX-P2-10; Android interim permission-pending and iOS Q7 restriction are not listener success |

The unsigned adaptations document is still a dependency, not owner approval.
Record Q1/Q3/Q7/Q9/Q15 assumptions and AS14's re-check set explicitly:
CX-P2-09/10/11/12, CX-P2-36 and CX-P2-42 must re-check if the owner overrides
any relevant default. Browser's approved App ownership is separate from this
HTTP proposal. CL-P2-01 records the final choices and exact type/module spelling
before provider implementation; this revision itself freezes nothing on main.

All changes to compiler/spec/runtime/workflow files belong to Claude. No
CX-P2-09…12 implementation edits a compiler-import module or runtime asset.
These concrete requests block implementation until assigned and integrated:

```text
REQUEST(CL-P2-01): Re-review the complete versioned-break table, portable wire admission and mandatory async WinHTTP model.
Expected / actual: Record HTTPURLTarget and HTTPServerStartPolicy ownership/rows, rejection ordering, error codes (header 1001, provider 2, unsupported 4, redirect rejected 3; size63 normalized), 65,536-byte reconstructed header bound, redirect range0–20, token registry, existing BackgroundJobCancellation reuse and Q1/Q3/Q7/Q9/Q15 assumptions plus AS14 re-check set in PLAN.md. Reconcile mobile-storage's IO placeholder. Exact interface spelling freezes at the CX-P2-09 seam merge before Windows/iOS/Android providers begin.
Blocks: Provider work; current draft is unapproved.
Workaround: Existing client remains until this seam and its dependencies pass.

REQUEST(CL-REQ): Assign the link-plan-aware corpus/test-c11 harness before CX-P2-09 lands.
Repro: Http, HttpFramingSafety and HttpClientLocal import HTTPClient; current runner.py links only fixed libraries and ignores native provider plans.
Expected / actual: Both compiler paths and all eight test-c11 cells consume pkg-config/framework/native/adapter units and explicit native reader/triple/sysroot, with bounded run-environment and endpoint lifecycle hooks. Curl's concrete typed setters use CURL_DISABLE_TYPECHECK with no pedantic-warning suppression and negative type fixtures. In CX-P2-09's integration, re-point the process-security guard to HTTP/MacOS and add both-frontend static no-child-process proof for native targets. Separate the legacy PATH-shim fixture from the common real HttpClientLocal golden. Keep the facade and all three corpus programs; conftest/Makefile/applicability changes remain Claude-owned.
Blocks: Any native HTTPTransport import; no known-red intermediate landing.
Workaround: None; native suites supplement rather than replace corpus coverage.

REQUEST(CL-P2-04): Provide libcurl >=7.85.0 development/pkg-config inputs and pinned openssl fixture tooling on every executing host.
Expected / actual: System trust, ASYNCHDNS and native reader/target/sysroot inputs recorded and documented for Linux facade consumers. Test-CA private keys generated in their executing job and never uploaded/shared; no runtime curl executable dependency.
Blocks: Linux transport build. Workaround: none.

REQUEST(CL-REQ): Add data-only Windows native import-library declarations and environment-aware target support in shared spec, both compilers, native_plan and harnesses.
Repro: ws2_32/winhttp and COM's ole32 have no current native manifest/link-plan channel; pragma comment(lib) fails under MinGW.
Expected / actual: Re-review link-plan v5 or bring CL-P2-19/15 forward; share the facility with windows-os-services.md. Current provider filters have only OS/architecture: classify windows-aarch64-msvc missing using a new environment-aware selector before GNU HTTP rows land, unless MSVC native imports are separately qualified. shell32 is already default; crypt32 is fixture-only.
Blocks: CX-P2-10. Workaround: no handwritten link-plan or ABI escape.

REQUEST(CL-P2-14): Set WIN32_LEAN_AND_MEAN and winsock2-before-windows.h in the forced compatibility include.
Expected / actual: Windows headers compose without conflicting socket declarations.
Blocks: Windows socket build. Workaround: provider cannot edit runtime headers.

REQUEST(CL-P2-07): Qualify Apple delegate queue executor/release executor, task-level delegates, completion blocks passed as delegate arguments and data-payload R1/R2 leases.
Expected / actual: Native-state-only callbacks on the serial SDK queue, final didBecomeInvalidWithError drain; re-review native-interop-ownership's closed executor set. Alternatively approve a native-only HTTP/MacOS and HTTP/IOS transaction header.
Blocks: MacOS half of CX-P2-09 and CX-P2-11, after CL-C-40 unless Q48 changes. Split Linux first rather than imply Apple interop already works.
Workaround: Retain the explicit MacOS curl provider and existing string/corpus coverage; new native-only capabilities remain unsupported. No macOS curl-free claim, handwritten compiler lowering or cross-thread ARC.

REQUEST(CL-P2-09): Supply checked HttpURLConnection JNI calls and Java thread-key ownership.
Expected / actual: Checked method/doOutput/fixed-length/disconnect APIs, exact wire admission, separate stream worker and sole disconnect controller, own-thread local-ref release and one retained R1 cleanup owner for global refs after both drain. No direct attach/detach, shared JNIEnv or Java callbacks; retained native state survives deadline/quiescence.
Blocks: CX-P2-12. Workaround: none; Q9 chooses HttpURLConnection, not Cronet.

REQUEST(CX-P1-09 / CL-P1-17): Confirm per-run public test-CA and network-security-config injection into the Android debug APK.
Expected / actual: The executing host generates keys locally; only the public CA enters the test APK, with no release override. Current host capability is unconfirmed; classify Android TLS-trust cases unavailable until it exists.
Blocks: Android trusted/hostname/expiry fixture acceptance. Workaround: none; app_process or an accept-all TrustManager is not equivalent.

REQUEST(CL-P2-01): Amend packet dependencies, collection and integration data.
Expected / actual: Add explicit CL-P1-10 and CL-P1-14/15 dependencies to CX-P2-10. Add HTTP/HTTPURLTarget.btrc and its export fragment to CX-P2-09, HTTP/Unix/** plus HTTPServerStartPolicy to CX-P2-10, and CX-P2-11/12 dependencies on that landing. Amend CX-P2-10 step2 to mandatory async WinHTTP/single closer. Change both CX-P2-02 step5 and CX-P2-10 step4 CA text to elevated disposable LocalMachine Root with preflight/cleanup proof. Reconcile iOS Q7/interim Android policy, assign Browser owners after App approval/shared COM ownership, and remove CX-P2-12's Cronet alternative. App currently has no executor/lifecycle contract.
Blocks: Platform implementation acceptance. Workaround: none; this revision does not edit workflows or workstream assignments.

REQUEST(CL-P2-01): Apply final integration fragments for HTTP/btrc.toml transport/socket/start-policy rows, fixture-only trust exports, target-applicability restrictions and inventory per-target reason/regression/aggregate/server cells.
Expected / actual: Missing transports cause a documented Library.HTTP facade compile-time regression; add restricted Http/HttpFramingSafety/HttpClientLocal applicability citing HTTPClient, not nonexistent mobile expected-skip manifests. README gives direct server/codec imports and Linux native-tool inputs. Complete interim Unix start-policy rows preserve server imports with declared restrictions. Preserve MacOS legacy provider/common real corpus/separate shim fixture until atomic NSURLSession replacement, with process guards, unsupported additive calls and temporary capability rules; no early native/curl-free claim.
Blocks: Green, accurately qualified platform landing.
Workaround: None. Any macOS cleartext exception or exact-capacity Bytes requirement needs a separate concrete request rather than disabling ATS or changing compiler imports.
```

Acceptance for this revision is source coverage, the explicit case design,
owned-path check and docs-tier CI. None of its native, trust-store or provider
fixtures has run in this docs-only revision. CL-P2-01 approval and PLAN entry
remain pending; this does not unblock provider implementation on its own.
