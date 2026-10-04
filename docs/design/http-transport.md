# HTTP transport and Browser ownership draft

Status: **Draft**, CX-P2-02; source baseline
`f4317455de1e567d4d6290139e5ba28fbada7d0c` (2026-10-04). This document
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
are an error. The validation order and literal strings are:

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

Header validation and the running aggregate check occur in input order. Preserve
that order for multiply-invalid input. The 65,536 count currently excludes CRLF
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

The following are proposed logical shapes, not new language declarations:

| Shape | Contract |
| --- | --- |
| HTTPTransportRequest | Immutable method, URL, ordered headers, copied/retained immutable Bytes payload, maxResponseBytes, one monotonic deadline, redirect policy, cancellation lease, trust policy. No borrowed caller buffer may outlive the call. |
| HTTPTransportOutcome | Final HTTP status, exact body Bytes, typed failure category, native diagnostic domain/code, and compatibility code. On failure status = 0 and body is empty. Native localized prose is diagnostic data, not the stable error string. |
| HTTPTransport.perform(request) | Blocking operation on an I/O worker; exactly one terminal outcome. Provider owns handles, callbacks and native buffers until quiescent cleanup. |
| HTTPRequestOptions | Additive options for maxRedirects (default 0), monotonic cancellation token and normal system trust. Test trust is fixture-only and absent from normal public configuration. |
| HTTPClient.requestBytes | Additive method using Bytes plus options and returning exact bodyBytes with typed failure information. The existing string methods adapt to the same seam and keep their return type and messages. |

The precise spelling and placement of the additive types is a freeze decision
for CL-P2-01. A source-compatible default overload must exist for every existing
call. The string adapter snapshots bytes up to the existing NUL terminator and
converts the response to the same NUL-terminated text view; limits always count
all received bytes before conversion. Arbitrary binary consumers use bodyBytes.
Neither buffer contains a fabricated curl status trailer.

HTTP depends downward on Bytes, Timer and native provider bindings, not App,
GUI or a compiler-import module that would introduce a reverse dependency.
No global TLS settings or process signal handlers are changed. No implicit
retry of a failed request, including a POST whose outcome is uncertain, occurs.
Production proxy behavior follows the selected platform's documented defaults;
proxy selection is recorded in diagnostics without credentials. Hermetic tests
select direct connections explicitly, with proxy environment variables removed.
Automatic cookie persistence and credential dialogs are disabled; callers pass
explicit headers. These explicit cross-provider policies require approval where
they differ from a platform default or ambient curl configuration.

### Bounds, redirects and deadlines

Request snapshots are bounded before starting native work. Response bytes are
counted with overflow-safe arithmetic before appending each chunk. Limit zero
accepts an empty response only; exactly-limit succeeds, limit-plus-one fails
without exposing a partial body. A declared Content-Length may reject early,
but cannot replace incremental enforcement for chunked, absent, lying or decoded
lengths. Bound headers separately in the provider: proposed 65,536 response
header bytes per hop, including separators, with a distinct typed HeaderTooLarge
failure. This new response-header bound needs explicit CL-P2-01 approval.

Transfer framing is decoded once. Content decoding must be explicit: the
proposed default requests identity and disables optional provider decompression;
if a provider cannot disable transparent decoding, count delivered decoded bytes
and record that parity issue before freeze. No provider may buffer an unbounded
response before enforcing the limit (including an NSURLSession completion-only
data task). Streaming delegates/read callbacks enforce bounds during receipt.
Retain at most the bounded body plus a documented fixed read-buffer allowance;
headers and diagnostic buffers also have independent bounds.

maxRedirects = 0 means no follow. An explicit positive value admits at most that
many additional requests; proposed range 0…20, invalid values rejected before
I/O. Exhaustion is RedirectLimit, not the last redirect reported as success.
All hops share the original deadline and protocol allowlist. The portable policy
resolves relative Location values, rejects malformed locations, strips sensitive
Authorization/Cookie/Proxy-Authorization headers on an origin change, and rejects
HTTPS-to-HTTP downgrade. With following enabled: 303 becomes GET except HEAD;
301/302 convert POST to GET; 307/308 preserve method and bytes. Remove body
framing headers (Content-Length and Transfer-Encoding) when discarding the body.
Recompute Host/authority from each hop URL; following mode removes a caller
Host override before dispatching any redirected request, even on the same
origin. The initial no-follow request retains existing custom-header behavior.
Replay uses the immutable bounded payload, never asks a caller to regenerate
a stream. Preserve the Location
response without following when maxRedirects is zero. Disable native automatic
redirects and apply this policy once; a later policy extension must be explicit.

The deadline starts when perform is admitted, includes DNS/connect/TLS/upload,
all redirects and receipt, and is never reset by progress. Each native timeout
uses the remaining budget; per-phase timeout APIs alone do not satisfy the total
deadline. The synchronous wrapper does not pump a nested GUI loop. Call it from
an I/O worker on mobile and in GUI applications. A main-thread synchronous
NSURLSession wait whose delegate uses that same thread is forbidden.

### Cancellation, completion and cleanup

Cancellation is an additive operation, not a claim about current HTTPClient.
A pre-cancelled request starts no I/O. Admission reserves a native cancellation
lease and terminal result storage. Native callbacks touch retained native state,
not borrowed managed references or cross-thread non-atomic ARC. Managed result
construction happens on the caller's owning executor after a bounded native
snapshot transfer; a callback never invokes application UI code.

Completion, cancel and deadline race through one synchronized terminal decision.
The first terminal decision wins; cancel after success is a no-op. Cancel during
upload or after server-side commit means Cancelled locally, **not** proof the
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
explicit cross-thread native lease; do not share a JNIEnv between threads.

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
| DNS / connection refused | Resolve / Connect | `curl failed (exit 6)` / `curl failed (exit 7)` |
| Total deadline | Timeout | `curl failed (exit 28)` |
| Certificate trust or hostname verification | TLSVerification with reason Trust / Hostname | `curl failed (exit 60)` |
| TLS handshake failure other than verification | TLSHandshake | `curl failed (exit 35)` |
| Cancellation | Cancelled | `curl failed (exit 42)` (new reachable outcome) |
| Redirect exhaustion | RedirectLimit | `curl failed (exit 47)` (opt-in only) |
| Receive / send failure | Receive / Send | `curl failed (exit 56)` / `curl failed (exit 55)` |
| Invalid/missing final status | InvalidStatus | `curl returned an invalid HTTP status` |
| Incremental body limit | ResponseTooLarge | `response body is too large` |
| New header bound / local provider failure | HeaderTooLarge / ProviderFailure | Proposed codes 63 / 2; approve new mappings before implementation |

HTTP status errors are not transport failures. Distinguish 401/403 from local OS
permission denial. A native error unknown to the common taxonomy stays
ProviderFailure with its domain/code; it is never guessed to be certificate or
permission failure from localized text. Additional errors observed during parity
testing extend the reviewed mapping, not ad hoc per-provider text.

There is a real legacy ambiguity: capture overflow (ChildProcess code 125) maps
to `response body is too large`, while curl's own --max-filesize failure can
produce `curl failed (exit 63)`. This draft proposes preserving code 63 for
up-front declared-length rejection and the existing size string for a streaming
limit crossing; both become ResponseTooLarge in the typed outcome. CL-P2-01 must
approve that distinction or explicitly version a normalization to one string.
Likewise arbitrary executable exit codes have no exact cross-OS equivalent;
the compatibility code table is a proposed finite normalization, not a promise
to reproduce every subprocess failure. Compare old and new diagnostics with
fixtures before removing the old implementation.

## Native providers

| Target / packet | Provider obligations |
| --- | --- |
| Linux / CX-P2-09 | libcurl easy API, linked using `pkg-config libcurl`; process-scoped initialization and teardown after all easy handles drain. CURLOPT_PROTOCOLS_STR/http,https, explicit redirect policy, write callback limits, total remaining timeout and cancellation progress callback. Keep peer verification enabled and hostname verification at 2. Use the system CA bundle; no bundled private production roots or curl process. |
| macOS / CX-P2-09 | NSURLSession with a private delegate queue and incremental data delegate, bounded native buffer, task cancel and explicit redirect delegate policy. Synchronous worker wrapper waits independently of that queue. Default OS trust/hostname evaluation; no accept-all challenge handler. Interop blocks/delegates require the approved compiler support or a Claude request. |
| iOS / CX-P2-11 | Separate IOS module over NSURLSession, sharing portable HTTP policy only; same bounds/cancel/TLS behavior as macOS. No process spawning, no UI-thread wait, no assumption that suspension preserves a live request. ATS remains enabled; cleartext fixture exceptions belong to the test host only. |
| Windows / CX-P2-10 | WinHTTP and Schannel: session/connection/request handles with one owner, explicit redirect policy, remaining-budget WinHttpSetTimeouts plus an overall deadline/cancel mechanism, incremental WinHttpReadData. WinHttpCloseHandle cancellation must observe callback/handle shutdown rules before freeing context. Never set certificate-ignore flags. Distinguish secure-failure flags for hostname and trust where supplied. |
| Android / CX-P2-12 | HttpURLConnection/HttpsURLConnection through CL-P2-09 JNI; blocking worker calls, fixed-length byte upload, bounded input/error-stream reads (HTTP 4xx body is valid), finite timeouts plus total deadline, redirects disabled for portable handling. Default TrustManager and hostname verifier. Attach/detach worker JNI environment and release local/global references exactly once. INTERNET required; no release cleartext opt-in. |

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
Retire tokens instead of wrapping/reusing a stale identity; reject admission on
registry/token exhaustion. Borrowers retain an operation lease while resolving
a token. Concurrent close invalidates future lookup, signals operation
cancellation and wakes deadline-aware wait loops, then drains current work
before closesocket. Waking a borrower must not close or recycle its SOCKET
while it is still using it; do not rely on waiting out the full request timeout. A portable typed connection owner is preferable long-term,
but removing the int surface is a separate reviewed change. POSIX fd callers
remain POSIX-specific; Windows tests must not treat these tokens as HANDLEs or
CRT descriptors. CL-P2-01 must approve this compatibility boundary explicitly.

Use ioctlsocket nonblocking mode and deadline-aware wait/read/write loops.
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
host/IP, serverAuth usage and a current validity interval. Separate leaves cover
wrong hostname and expiry, and a distinct untrusted CA covers trust rejection.
Trust is scoped to the fixture, verification stays on, and private keys are
removed during teardown. No external service or public DNS is required.

| Target | Test-only trust mechanism |
| --- | --- |
| Linux | Per-request CURLOPT_CAINFO points to the generated CA bundle; peer and hostname verification stay enabled. Production continues to use system trust. |
| macOS / iOS | Fixture-only server-trust delegate supplies the generated anchor to SecTrust, applies the requested-host SSL policy, and evaluates chain, hostname and validity before returning a credential. Pin the test anchor, not any leaf received. No global keychain change and no unconditional challenge acceptance. |
| Windows | Dedicated disposable runner user: install this run's uniquely identified CA in CurrentUser Root, capture its thumbprint, and remove exactly that certificate in finally. Register cleanup before networking starts; an outer process also cleans after child timeout. Verify absence after removal and a subsequent trust failure. If store isolation or cleanup fails, fail the fixture and discard the runner. |
| Android | Debug test APK network-security-config trusts only the generated test CA for the fixture configuration; release APK contains neither the CA nor the debug override. Standard TrustManager/hostname checks remain enabled. Debug cleartext exception covers local plain fixtures only. |

Android debug overrides may intentionally bypass certificate pinning; that is
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
| Redirects | Default no-follow; each status/method rule; exact hop limit and overflow; loop; relative Location; cross-origin credential stripping; downgrade rejection. |
| Limits/framing | Declared and streaming overflow; chunked/unknown length; zero limit; fragmented header/body; no giant prebuffer; verify both legacy size-error branches. |
| Time | Slow headers, slow upload and drip-fed body cannot reset total deadline; blocked send times out; no retries of uncertain POST. |
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

For the no-executable proof, compile first, then run the complete HTTP corpus
and provider tests with a minimal explicit PATH whose entries contain no curl
or curl.exe. Assert shutil.which('curl') is None and on Windows also check
curl.exe; use absolute paths for the test interpreter, compiled programs and
necessary helpers. Windows System32 on PATH would invalidate the proof.
Removing PATH alone cannot exclude an absolute-path executable fallback, so
also audit provider dependencies and record child-process launches for the
network operation (no child may be curl). The Linux binary may link libcurl;
that is the intended library provider. The endpoint may invoke openssl during
fixture creation, never to service a client request. Publish provider identity,
SDK/OS, trust mode, frontend, case counts, skip reasons and CI run IDs. A Linux
result does not fill Windows, macOS, simulator, emulator or device evidence.

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
| CX-P2-09 | Land portable HTTP seam plus Linux libcurl and MacOS NSURLSession and shared endpoint tests after approval/CL-P2-04/provider filters. Record the proposed App.Browser owner; this packet does not own a new portable App contract or promise Linux/macOS browser implementation. Request assignment for those providers. |
| CX-P2-10 | Windows HTTP and Winsock; App/Windows Browser provider uses ShellExecuteExW with verb open, validates allowed schemes and maps Win32 failure. If requesting a process handle, close it; never wait for browser exit as page-load proof. |
| CX-P2-11 | Separate IOS transport and Q7 reconciliation. Browser remains missing until CX-P2-36 provides UIApplication; then UIApplication open completion supplies dispatch outcome. In-app Safari is a separate presentation choice, not transport fallback. |
| CX-P2-12 | Android HTTP and network permission fixtures; explicitly defer Browser to CX-P2-42. |
| CX-P2-42 | App/Android Browser through a visible Activity, Custom Tab where available or ACTION_VIEW, correct URI encoding and missing-handler mapping. A background request is deferred/rejected according to App lifecycle policy, not a forced activity launch. |

## Requests and approval checklist

| Request | Concrete decision / work |
| --- | --- |
| CL-P2-01 | Review with the required two adversarial and one parity reviewers; record assumed Q1/Q3/Q7/Q9/Q15 defaults. Freeze additive Bytes/options shapes, compatibility codes (especially size failures), header/redirect limits, callback ownership and the Windows int-token boundary. Reconcile iOS listener scope and assign portable Browser/Linux/macOS ownership. Record approval in PLAN.md. |
| CL-P2-04 | Add curl.dev/libcurl pkg-config metadata and openssl test-CA tooling to dev-shell/devcontainer inputs; keep system trust available. Verify pkg-config resolves libcurl. No new curl executable dependency for runtime tests; fixture PATH is scrubbed after build. |
| CL-P1-14 / CL-P1-15 | Provider-directory selection and cache identity must prevent foreign SDK imports, including IOS vs MacOS. Manifest/export changes remain integrator fragments. |
| CL-P2-09 | JNI calls needed for HttpURLConnection, worker attachment and reference ownership; no Java callback feature is required for blocking I/O. |
| Apple interop owner | Validate the incremental NSURLSession delegate and trust/redirect delegate shapes against interop steps 3/6; file a minimal paired-frontend reproducer before requesting a compiler change. No hand-emitted compiler/runtime shim in this docs packet. |
| CL-P2-01 / runtime owner as needed | Validate SOCKET width, close/cancel synchronization and native cancellation lease ABI. Any compiler-import, runtime or ABI change is a separate Claude request, never a cast-around workaround. |

Acceptance for this draft is source coverage, an explicit test design, an
owned-path check and docs-tier CI. Implementation acceptance additionally needs
the target suites above, through both frontends, with actual native execution
and exact counts. CL-P2-01 approval and PLAN entry remain pending; this document
does not unblock CX-P2-09 or claim completion of Stage 26 on its own.
