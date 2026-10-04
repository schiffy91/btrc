# HTTP transport and Browser ownership draft

Status: **Revision 2, approval pending**, CX-P2-02; source baseline
`72592d36f560517a39e54f4b92b0149d44bef4d6` (2026-10-04). This document
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

Revision 2 deliberately versions two validation changes before implementation:
row 2 additionally requires the canonical URL syntax below (scheme allowlist
is still row 3, preserving `unsupported URL scheme` precedence); after each row-7
header syntax check and before its row-8 aggregate check, a case-insensitive
provider-owned name fails with literal `HTTP request header is provider-owned`.
The ordered reserved list is Host, Content-Length, Transfer-Encoding, Connection,
Keep-Alive, Proxy-Connection, TE, Trailer, Upgrade and Expect. No provider silently
strips these caller headers: every target rejects them before I/O. Native code
owns authority, framing and hop-by-hop headers. This changes curl pass-through,
including caller Host overrides, and requires CL-P2-01's versioned approval.
Header syntax/reservation and running aggregate checks occur in input order;
preserve that precedence for multiply-invalid input. The 65,536 count currently excludes CRLF
separators; do not silently reinterpret it as a different wire-header budget.
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
and supply a run-environment hook for PATH scrubbing. Today's runner links only
its fixed libraries and cannot satisfy this design. No provider PR may land
first and knowingly break make test or test-c11. Native transport suites remain
additional coverage, not a substitute for those corpus gates.

The following are proposed logical shapes, not new language declarations:

| Shape | Contract |
| --- | --- |
| HTTPTransportRequest | Immutable method, canonical URL components, ordered headers, provider-owned copy of the mutable Bytes payload, maxResponseBytes, one monotonic deadline, redirect policy, cancellation lease, trust policy. No borrowed caller buffer may outlive the call. |
| HTTPTransportOutcome | Final HTTP status, exact body Bytes, typed failure category, native diagnostic domain/code, and compatibility code. On failure status = 0 and body is empty. Native localized prose is diagnostic data, not the stable error string. |
| HTTPTransport.perform(request) | Blocking operation on a non-UI caller (a CLI main thread is allowed); exactly one terminal outcome. Provider owns handles, callbacks and native buffers until quiescent cleanup. |
| HTTPRequestOptions | Additive options for maxRedirects (default 0), the shared IO-owned atomic cancellation flag and normal system trust. Test trust is fixture-only and absent from normal public configuration. |
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

CX-P2-09 owns proposed `HTTP/HTTPURLTarget.btrc` (scope amendment required),
a single RFC 3986 parse/resolve owner. HTTPFraming remains unchanged. Initial
URLs and every Location pass this owner before native dispatch. It emits only
canonical scheme, ASCII host, effective port and path?query; providers receive
those components and never reinterpret the caller's raw URL. If a platform API
requires a URL string, construct it from these components and verify its parsed
host/port against them before connecting. Credentials never come from userinfo.

| Input | Frozen proposal / common two-frontend and every-provider case |
|---|---|
| Scheme/authority | http/https only, lowercase scheme and DNS host; authority required; absent port means 80/443; explicit decimal port must be 1–65535 |
| Userinfo | reject with `invalid URL`; deliberate versioned change from curl's implicit Basic authentication |
| Fragment/backslash/control | reject fragments (including a fragment-only Location), backslashes, whitespace and controls; no native-parser repair |
| DNS/IDN | accept bounded ASCII DNS names and canonical IPv4; reject percent escapes in host and non-ASCII/IDN until one reviewed IDNA owner exists; reject ambiguous numeric IPv4 spellings |
| IPv6 | require bracketed RFC 3986 literal; parse numeric address and serialize one lowercase compressed form; reject zone identifiers; origin equality uses numeric address |
| Path/query | empty path becomes `/`; validate every percent escape, preserve escaped octets, uppercase hex; RFC dot-segment removal applies to literal dot segments only; query is opaque validated bytes |
| Relative Location | RFC 3986 section 5 resolution against last canonical URL; reject invalid authority/port/userinfo before origin comparison; scheme-relative references allowed subject to downgrade policy |
| Origin | canonical scheme + canonical host/address + effective port; default-port spellings compare equal; no suffix/prefix comparison |

URL length remains 8,192 bytes before and after canonicalization. Case tests
include `:0`, `:65536`, empty ports, bracket mistakes, encoded hosts, Unicode,
userinfo with passwords, mixed-case/default-port origins, escaped slash/dot,
relative query, network-path Location and HTTPS downgrade. No compatibility
claim is made for previously accepted ambiguous curl spellings.

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

Transfer framing is decoded once. Content decoding must be explicit: the
proposed default requests identity and disables optional provider decompression;
if a provider cannot disable transparent decoding, count delivered decoded bytes
and record that parity issue before freeze. No provider may buffer an unbounded
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
A pre-cancelled request starts no I/O. Cancellation is the same IO-owned
atomic flag as mobile-storage.md, pending CL-P2-01 assignment; no per-provider
managed cancellation ABI is invented. Admission reserves R1/R2 native owner
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
and retain the cleanup lease until quiescent. Underlying platform DNS/cancel
behavior must be measured before promising this as a universal latency SLA.
For blocking JNI I/O, disconnect/close and finite read/connect timeouts need an
retained R1 native owner; do not share a JNIEnv between threads. Obtain each
thread's JNIEnv only from the src/stdlib/Java thread key, never direct attach or
detach. DNS that cannot be interrupted (InetAddress or synchronous libcurl)
runs on a provider-owned native worker. The caller's monotonic wait can expire,
but retained native work is quarantined until actual quiescence. Bound admission
of such outstanding workers; timeout cannot allow unbounded orphan work.

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
| Receive / send failure | HTTP_FAILURE_RECEIVE / HTTP_FAILURE_SEND | `curl failed (exit 56)` / `curl failed (exit 55)` |
| Invalid/missing final status | HTTP_FAILURE_INVALID_STATUS | `curl returned an invalid HTTP status` |
| Incremental body limit | HTTP_FAILURE_RESPONSE_TOO_LARGE | `response body is too large` |
| New header bound / local provider failure | HTTP_FAILURE_HEADER_TOO_LARGE / HTTP_FAILURE_PROVIDER | Proposed codes 1001 / 2; 1001 deliberately avoids size-code 63; approval required |
| Additive capability unavailable on interim MacOS provider | HTTP_FAILURE_UNSUPPORTED | Not reachable from existing string signatures; proposed byte/options outcome only, approval required |

HTTP status errors are not transport failures. Distinguish 401/403 from local OS
permission denial. A native error unknown to the common taxonomy stays
HTTP_FAILURE_PROVIDER with its domain/code; it is never guessed to be certificate or
permission failure from localized text. Additional errors observed during parity
testing extend the reviewed mapping, not ad hoc per-provider text.

There is a real legacy ambiguity: capture overflow (ChildProcess code 125) maps
to `response body is too large`, while curl's own --max-filesize failure can
produce `curl failed (exit 63)`. This draft proposes preserving code 63 for
up-front declared-length rejection and the existing size string for a streaming
limit crossing; both become HTTP_FAILURE_RESPONSE_TOO_LARGE in the typed outcome. CL-P2-01 must
approve that distinction or explicitly version a normalization to one string.
Likewise arbitrary executable exit codes have no exact cross-OS equivalent;
the compatibility code table is a proposed finite normalization, not a promise
to reproduce every subprocess failure. Compare old and new diagnostics with
fixtures before removing the old implementation. Pin legacy regressions for
an embedded-NUL response (invalid status), strict toString vs lossy conversion,
ChildProcess expiry code 124 (`curl failed (exit 124)`) versus curl's own
network timeout 28. Normalizing the native total deadline to 28 as above is a
deliberate compatibility change requiring approval, not an unchanged behavior, and string callers: unchanged signatures have no cancellation input,
so new exit 42 is only reachable through an approved new options adapter.

TLS reason sources: libcurl verify-result plus CURLcode; Apple NSURLError and
SecTrust result; WinHTTP secure-failure flags (invalid CA/CN/date); Android
certificate exception/cause through checked JNI. If the platform cannot
reliably distinguish a cause, HTTP_TLS_UNKNOWN preserves the native domain/code;
never classify by localized exception text.

## Native providers

| Target / packet | Provider obligations |
| --- | --- |
| Linux / CX-P2-09 | libcurl >=7.85.0, linked using `pkg-config libcurl`; initialize once behind a once guard, never call curl_global_cleanup from the provider. Use multi with curl_multi_poll/curl_multi_wakeup for cancellation, CURLOPT_NOSIGNAL=1 on every handle and CURL_VERSION_ASYNCHDNS or the quarantined resolver-worker fallback. CURLOPT_PROTOCOLS_STR/http,https, explicit redirect policy, write callback limits, total remaining timeout and cancellation/wakeup. Keep peer verification enabled and hostname verification at 2. Use the system CA bundle; no bundled private production roots or curl process. |
| macOS / CX-P2-09 | Ephemeral NSURLSession with no URLCache, cookie store or credential store and a private serial delegate queue and incremental data delegate, bounded native buffer, task cancel and explicit redirect delegate policy. Synchronous worker wrapper waits independently of that queue. Default OS trust/hostname evaluation; no accept-all challenge handler. Interop requires CL-P2-07/Stage 29 or an approved native-only transaction. Invalidate the session on every path; didBecomeInvalidWithError is final quiescence. ATS stays enabled for unbundled executables; blocked cleartext is an explicit policy adaptation until an approved packaged-host exception exists. |
| iOS / CX-P2-11 | Separate IOS module over NSURLSession, sharing portable HTTP policy only; same bounds/cancel/TLS behavior as macOS. No process spawning, no UI-thread wait, no assumption that suspension preserves a live request. ATS remains enabled; cleartext fixture exceptions belong to the test host only. |
| Windows / CX-P2-10 | Synchronous WinHTTP on the provider worker and Schannel: session/connection/request handles with one owner, explicit redirect policy, remaining-budget WinHttpSetTimeouts plus an overall deadline/cancel mechanism, incremental WinHttpReadData. WinHttpCloseHandle cancellation must observe callback/handle shutdown rules before freeing context. Async native adapters, if used, retain context through WINHTTP_CALLBACK_STATUS_HANDLE_CLOSING. Never set certificate-ignore flags. Distinguish secure-failure flags for hostname and trust where supplied. |
| Android / CX-P2-12 | HttpURLConnection/HttpsURLConnection through CL-P2-09 JNI; blocking worker calls, fixed-length byte upload, bounded input/error-stream reads (HTTP 4xx body is valid), finite timeouts plus total deadline, redirects disabled for portable handling. Default TrustManager and hostname verifier. Acquire JNIEnv exclusively through the Java thread key; release local/global references exactly once. INTERNET required; no release cleartext opt-in. |

Linux's static-inline HTTP/Linux header supplies typed curl setters and C
write/header/xferinfo callbacks into bounded native buffers and the atomic flag;
never bind curl_easy_setopt variadics directly. Exact option types must pass
curl's checks at O0–O3. CURLOPT_NOSIGNAL does not itself eliminate TLS-backend
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

## Winsock server and socket ownership

CX-P2-10 ports socket operations, not the shared HTTPFraming parser into a second
parser. Its network owner pairs successful WSAStartup(2.2) with WSACleanup after
the final listener/connection and operation lease drain. Failed startup owns no
cleanup obligation. WSAStartup returns its error directly; subsequent socket
failures capture WSAGetLastError immediately, before any cleanup overwrites it.
SOCKET is pointer-width and INVALID_SOCKET is the invalid value: never truncate
a SOCKET into the existing public int fd or call POSIX close on it.

The current server exposes int fd, acceptConn and closeConn. Proposed compatible
Windows surface uses nonnegative opaque int tokens backed by a bounded registry
of SOCKET owners; -1 remains failure. Tokens are never native descriptors.
Use bounded slot-plus-generation tokens; retire a slot before generation wrap,
rejecting admission on exhaustion so stale tokens can never resolve anew. Borrowers retain an operation lease while resolving
a token. Concurrent close invalidates future lookup, signals operation
cancellation and wakes deadline-aware wait loops, then drains current work
before closesocket. Waking a borrower must not close or recycle its SOCKET
while it is still using it; do not rely on waiting out the full request timeout. A portable typed connection owner is preferable long-term,
but removing the int surface is a separate reviewed change. POSIX fd callers
remain POSIX-specific; Windows tests must not treat these tokens as HANDLEs or
CRT descriptors. CL-P2-01 must approve this compatibility boundary explicitly.

Freeze HTTPSocket's portable seam with Unix/ for linux/macos/ios/android and
Windows/ for windows; HTTPServer, including respond shutdown, calls only it.
Use WSASocketW with WSA_FLAG_NO_HANDLE_INHERIT, ioctlsocket nonblocking mode and
WSAEventSelect plus a cancel event for deadline-aware waits. WSAPoll alone is
not wakeable and shutdown does not wake accept. Concurrent public closeConn/stop
is not a portable contract; callers serialize server methods on their owner.
Windows internal cancellation does not imply POSIX thread-safe public methods.
WSAEWOULDBLOCK retries only after readiness; WSAEINTR retries within the same
deadline; reset/abort/timeout produce the existing false, -1 or empty-Bytes
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
its provider hook; CX-P2-11/12 implement the hook only in their own directories.
CL-P2-01 must amend those packet steps. Proposed outcomes are HTTP_SERVER_STARTED,
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
openssl tooling from CL-P2-04. Valid leaves have SANs matching the exact fixture
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
| Android | Debug test APK network-security-config trusts only the generated test CA for the fixture configuration; release APK contains neither the CA nor the debug override. Standard TrustManager/hostname checks remain enabled. Debug cleartext exception covers local plain fixtures only. |

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
| Text and arbitrary bytes | GET/POST and Bytes echo including NUL/non-UTF8; empty, exact-limit and limit-plus-one payloads; server byte response arrives intact. |
| HTTP errors | 404/500 return body/status with empty transport error; ok() false. |
| URL/header policy | Every canonical URL case above; every reserved name in mixed case; conflicting framing; credential/cookie transport; default User-Agent and Expect policy. |
| Redirects | Default no-follow; each status/method rule; exact hop limit and overflow; loop; relative Location; cross-origin credential stripping; downgrade rejection. |
| Limits/framing | Declared and streaming overflow; chunked/unknown length; zero limit; fragmented header/body; no giant prebuffer; verify both legacy size-error branches. |
| Time | Slow/blackholed resolver, slow headers, slow upload and drip-fed body cannot reset total deadline; blocked send times out; no retries of uncertain POST, including stale keep-alive reuse. |
| Cancellation | Before admission, during connect/read/upload, and completion race; one terminal outcome, bounded observation, resources drained, late callback safe. |
| TLS | Trusted valid leaf succeeds; wrong hostname, expired and untrusted leaves fail independently with verification enabled; HTTP cleartext cannot masquerade as TLS success. |
| Failures | Refused connection, deterministic DNS failure through an isolated resolver fixture or injected native resolution failure, truncated response, invalid status, OS permission state; stable categories and legacy strings. |
| Cleanup | Repeated success/failure/cancel cycles leave no request handles, sockets, JNI refs, native buffers, certificate-store entries or named capture files. |

Http, HttpUtil and HttpParseEdges retain pure parsing/utility assertions;
HttpFramingSafety retains validation and smuggling regressions; HttpParseBytes
and HttpBytesResponse retain NUL framing; HttpSocketIo retains deadline,
SIGPIPE-policy and short-I/O coverage on POSIX plus equivalent Windows cases;
HttpClientLocal becomes the real local-client corpus. New provider suites add
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
Assign replacement of test_stdlib_process_security.py's
`test_http_client_is_direct_and_protocol_restricted` to the Claude harness packet,
with both-frontend no-process proof, rather than silently removing the guard. The Linux binary may link libcurl;
that is the intended library provider. The endpoint may invoke openssl during
fixture creation, never to service a client request. Publish provider identity,
SDK/OS, trust mode, frontend, case counts, skip reasons and CI run IDs. A Linux
result does not fill Windows, macOS, simulator, emulator or device evidence.

### Interim availability and case accounting

The first Linux landing must also select a real MacOS legacy provider over the
existing curl implementation. Existing macOS string calls and their corpus
remain working; do not create an unconfigured MacOS row or silently skip that
previously supported surface. That temporary provider preserves current
subprocess transaction/status/body behavior beneath the approved versioned
facade validation, and keeps its direct-exec/protocol
security guard and legacy plumbing fixture, updating their expected admission
results for those deliberate common URL/header changes. It does not qualify the new
requestBytes/options/redirect/cancellation contract: those additive calls return
HTTP_FAILURE_UNSUPPORTED before I/O until the native provider lands.
CL-P2-01 must freeze that transitional outcome and amend the packet scope.
The existing string API has no new options, so this does not change its accepted
call shape. Common corpus coverage still runs on macOS; native-only new cases
get exact temporary capability rules approved by Claude.

Inventory continues to say macOS HTTPS client via curl, and the no-executable/
no-ChildProcess proof applies only to Linux at this stage. Never claim macOS
curl-free or Stage-26 HTTP completion from that intermediate green run. The
NSURLSession landing atomically replaces this legacy provider, removes its
plumbing fixture/old process guard and temporary capability rules, updates the
inventory and enables the full macOS native corpus/no-process proof. There is
no automatic runtime fallback from a failed native request to curl.

Until their real providers land, windows/ios/android HTTPTransport rows remain
Stage-24 missing, not stub providers. Claude supplies expected-skip fragments for
Http, HttpFramingSafety and HttpClientLocal on affected runner rows, and updates
platform-inventory cells, including replacing "HTTPS client via curl" only for
rows whose native provider has actually landed, regression IDs and aggregate. This is honest interim availability, not final
Stage-26 acceptance. HTTPServer's iOS inventory also waits for Q7's decision.

Case IDs are stable by family: HTTP-URL-*, HTTP-HEADER-*, HTTP-BYTES-*,
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
reports completion asynchronously must retain its completion lease and deliver
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

All changes to compiler/spec/runtime/workflow files belong to Claude. No
CX-P2-09…12 implementation edits a compiler-import module or runtime asset.
These concrete requests block implementation until assigned and integrated:

```text
REQUEST(CL-P2-01): Re-review the versioned URL and provider-owned header validation, additive server-start result and exact btrc text.
Expected / actual: Freeze HTTPURLTarget and server hook ownership, rejection ordering, error codes (header 1001, provider 2, size 63), 65,536-byte reconstructed header bound, redirect range 0–20, token registry, shared IO atomic cancellation, and the Q1/Q3/Q7/Q9/Q15 assumptions in PLAN.md. Exact interface spelling freezes at the CX-P2-09 seam merge before Windows/iOS/Android providers begin.
Blocks: Provider work; current draft is unapproved.
Workaround: Existing client remains until this seam and its dependencies pass.

REQUEST(CL-REQ): Assign the link-plan-aware corpus/test-c11 harness before CX-P2-09 lands.
Repro: Http, HttpFramingSafety and HttpClientLocal import HTTPClient; current runner.py links only fixed libraries and ignores native provider plans.
Expected / actual: Both compiler paths and all test-c11 cells consume pkg-config/framework/native/adapter units, with a bounded run-environment hook for PATH scrub; conftest/Makefile/skip changes are Claude-owned. Replace the process-security guard with both-frontend static no-child-process reachability proof for each native target when it lands; retain the MacOS legacy guard until its native replacement. Keep the facade and all three corpus programs.
Blocks: Any native HTTPTransport import; no known-red intermediate landing.
Workaround: None; native suites supplement rather than replace corpus coverage.

REQUEST(CL-P2-04): Provide libcurl >=7.85.0 development/pkg-config inputs and openssl fixture tooling in the dev shell/container.
Expected / actual: System trust and ASYNCHDNS capability recorded; no runtime curl executable dependency.
Blocks: Linux transport build. Workaround: none.

REQUEST(CL-REQ): Add data-only Windows native import-library declarations, os/arch/env filtered, in shared spec, both compilers, native_plan and harnesses.
Repro: ws2_32/winhttp and COM's ole32 have no current native manifest/link-plan channel; pragma comment(lib) fails under MinGW.
Expected / actual: Re-review link-plan v5 or bring CL-P2-19/15 forward; share the facility with windows-os-services.md. shell32 is already default; crypt32 is fixture-only.
Blocks: CX-P2-10. Workaround: no handwritten link-plan or ABI escape.

REQUEST(CL-P2-14): Set WIN32_LEAN_AND_MEAN and winsock2-before-windows.h in the forced compatibility include.
Expected / actual: Windows headers compose without conflicting socket declarations.
Blocks: Windows socket build. Workaround: provider cannot edit runtime headers.

REQUEST(CL-P2-07): Qualify Apple delegate queue executor/release executor, task-level delegates, completion blocks passed as delegate arguments and data-payload R1/R2 leases.
Expected / actual: Native-state-only callbacks on the serial SDK queue, final didBecomeInvalidWithError drain; re-review native-interop-ownership's closed executor set. Alternatively approve a native-only HTTP/MacOS and HTTP/IOS transaction header.
Blocks: MacOS half of CX-P2-09 and CX-P2-11, after CL-C-40 unless Q48 changes. Split Linux first rather than imply Apple interop already works.
Workaround: Retain the explicit MacOS curl provider and existing string/corpus coverage; new native-only capabilities remain unsupported. No macOS curl-free claim, handwritten compiler lowering or cross-thread ARC.

REQUEST(CL-P2-09): Supply checked HttpURLConnection JNI calls and Java thread-key ownership.
Expected / actual: No direct attach/detach, shared JNIEnv or Java callbacks; retained R1 native state survives deadline/quiescence.
Blocks: CX-P2-12. Workaround: none; Q9 chooses HttpURLConnection, not Cronet.

REQUEST(CL-P2-01): Amend packet dependencies, collection and integration data.
Expected / actual: CL-P1-10 native bindings and CL-P1-14/15 provider selection/cache identity are explicit. CX-P2-10 owns portable HTTPServer changes; CX-P2-11/12 only implement hooks. Amend Windows CA text to elevated disposable LocalMachine Root with preflight/cleanup proof. Reconcile iOS listener Q7, assign portable/Linux/MacOS Browser owners after App approval and shared COM apartment ownership, and amend CX-P2-12's Cronet alternative. App currently has no executor/lifecycle contract.
Blocks: Platform implementation acceptance. Workaround: none; this revision does not edit workflows or workstream assignments.

REQUEST(CL-P2-01): Apply final integration fragments for HTTP/btrc.toml transport/socket rows, fixture-only trust exports, expected skips for each landing and platform-inventory regression/title/aggregate/iOS-server cells.
Expected / actual: Missing targets stay classified missing until native evidence; no stub success. Preserve the explicit MacOS legacy provider/corpus until the atomic NSURLSession replacement, with target-specific process guards, typed unsupported additive calls and exact temporary capability rules; do not mark its inventory native or curl-free early.
Blocks: Green, accurately qualified platform landing.
Workaround: None. Any macOS cleartext exception or exact-capacity Bytes requirement needs a separate concrete request rather than disabling ATS or changing compiler imports.
```

Acceptance for this revision is source coverage, the explicit case design,
owned-path check and docs-tier CI. None of its native, trust-store or provider
fixtures has run in this docs-only revision. CL-P2-01 approval and PLAN entry
remain pending; this does not unblock provider implementation on its own.
