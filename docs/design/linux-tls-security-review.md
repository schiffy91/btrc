# Linux First-Party TLS Security Review and Hardening Record

This document records the independent read-only security audit of `src/stdlib/TLS/`
and `src/stdlib/Crypto/` prior to retiring `curl` from Linux `Library.HTTP`, along
with the fixes applied and their regression coverage.

## Audit Findings and Fixes

### High

- **H1 — Explicit CA override isolation (`TLS/Linux/TrustFiles.btrc`)**:
  `LinuxTrustFiles.configured` previously populated `/etc/ssl/certs` when only
  `CURL_CA_BUNDLE` or `SSL_CERT_FILE` was set, and populated the default system
  CA bundle when only `SSL_CERT_DIR` was set, silently merging system roots into
  explicitly pinned trust stores. Fixed by tracking `explicit` whenever any of
  `CURL_CA_BUNDLE`, `SSL_CERT_FILE`, or `SSL_CERT_DIR` is non-empty on origin
  connections and falling back to system CA paths only when no override is set
  (or for `proxyTrust`).
  - Regression coverage: `src/tests/python/test_tls_trust_store.py` (isolated
    `bwrap` `/etc/ssl/certs` checks for each env override).

- **H2 — X.509 outer `signatureAlgorithm` malleability vs. explicit distrust
  (`TLS/X509Certificate.btrc`, `TLS/X509ServerPath.btrc`)**:
  Adding or stripping ASN.1 `NULL` (`05 00`) on the unsigned outer
  `Certificate.signatureAlgorithm` changed the outer DER bytes while keeping
  `tbsCertificate` intact, allowing a rejected certificate (`-addreject
  serverAuth`) to miss byte-exact `sameCertificate` lookup. Fixed by requiring
  byte-for-byte DER equality (`DER.same`) between outer `signatureAlgorithm` and
  `tbsCertificate.signature` for all parsed certificates and trust anchors, and
  by matching identical `TBSCertificate` bytes (`sameTBS`) inside
  `X509ServerPath.rejected`.
  - Regression coverage: `src/tests/python/test_tls_x509.py` (mismatched outer
    and inner `signatureAlgorithm` rejected by both `parse` and
    `parseTrustAnchor`), `src/tests/python/test_tls_server_path.py` (`--rejected`
    with mutated signature still blocks equal TBS).

- **H3 — Unbounded control, empty-record, alert, and 1-byte fragment DoS
  (`TLS/Linux/ClientStream.btrc`, `TLS/TLS13ClientHandshake.btrc`,
  `TLS/TLS12Handshake.btrc`)**:
  Added hard per-connection and consecutive bounds that abort with fatal alerts:
  - Consecutive `KeyUpdate` without intervening application data: `<= 8` (total
    per connection `<= 32`).
  - Total `NewSessionTicket` messages per connection: `<= 32`.
  - Consecutive empty `application_data` records (TLS 1.2 and 1.3): `<= 32`.
  - Consecutive warning / `user_canceled` alerts (handshake and post-handshake):
    `<= 4`.
  - Total handshake records per handshake (TLS 1.2 and 1.3): `<= 256`; initial
    `chooseProtocol` records: `<= 16` (and buffered bytes `<= 32768`, with
    ServerHello header length validated).
  - Regression coverage: `src/tests/python/test_tls13_key_update.py`
    (`ticket-flood`, `key-update-flood`), `src/tests/python/test_tls_hello_records.py`
    (1-byte fragment flood), `src/tests/python/test_tls12_handshake.py` (warning
    flood and 1-byte fragment flood), `src/tests/python/test_tls_alerts.py`
    (empty application-data flood and `chooseProtocol` record flood).

- **H4 — TLS 1.3 `ChangeCipherSpec` and mid-fragment alert enforcement
  (`TLS/TLS13ClientHandshake.btrc`)**:
  Previously accepted unlimited CCS records in any state, including before
  `ServerHello` and mid-fragment. Fixed per RFC 8446 §5 / §D.4 to reject CCS
  before the first `ServerHello`/`HelloRetryRequest`, reject CCS and
  `user_canceled` alerts while `self.messages` holds a partial handshake
  fragment, and accept at most one dummy CCS (`0x01`) per handshake.
  - Regression coverage: `src/tests/python/test_tls_hello_records.py`
    (pre-ServerHello CCS, mid-fragment CCS, repeated CCS, malformed CCS),
    `src/tests/python/test_tls_security_hardening.py` (mid-fragment
    `user_canceled` and > 4 `user_canceled` alerts).

### Medium

- **M1 — TLS 1.2 `renegotiation_info` (`0xff01`) required
  (`TLS/TLS12PeerMessages.btrc`)**:
  Required both `extended_master_secret` (0x0017) and `renegotiation_info`
  (0xff01) in TLS 1.2 `ServerHello`.
  - Regression coverage: `src/tests/python/test_tls12_handshake.py`.

- **M2 — TLS 1.3 `AlertLevel` validation (`TLS/TLSAlert.btrc`)**:
  Validated `level == 1 || level == 2` (else `TLS_ALERT_INVALID`), treated all
  `level == 2` alerts as `TLS_ALERT_FATAL`, and admitted `TLS_ALERT_CLOSE` /
  `TLS_ALERT_CONTINUE` only for `level == 1` with description `0` or `90`.
  - Regression coverage: `src/tests/python/test_tls_security_hardening.py`.

- **M3 — TLS 1.3 padded record limit and `record_overflow` alerts
  (`TLS/TLS13Records.btrc`, `TLS/TLS13ClientHandshake.btrc`,
  `TLS/TLS12Records.btrc`, `TLS/TLS12Handshake.btrc`)**:
  Accepted RFC 8446 §5.2 encrypted records up to `16640` ciphertext bytes while
  rejecting unpadded plaintext `> 16384` bytes with `TLS_RECORD_OVERFLOW` (22);
  moved TLS 1.2 plaintext record-length check above alert handling and propagated
  `TLS_RECORD_OVERFLOW` from encrypted record overflow.
  - Regression coverage: `src/tests/python/test_tls_security_hardening.py`,
    `src/tests/python/test_tls12_handshake.py`, `src/tests/stdlib/TLSRecords.btrc`.

- **M4 — Secret hygiene and destructor wiping
  (`TLS/TLS13Hello.btrc`, `TLS/TLS13ClientHandshake.btrc`,
  `TLS/Linux/ClientStream.btrc`)**:
  Added `TLS13Hello.close()`, wiped the unused TLS 1.3 ephemeral scalar
  immediately on TLS 1.2 fallback, closed all handshake/traffic `TLS13Records`
  and `TLS13HandshakeKeys` on teardown, wiped buffered plaintext in
  `LinuxTLSStream.abort()`, and added `__del__` destructors.

### Low

- **L1**: Bounded RSA public exponent to `<= 8` bytes directly in
  `Crypto/Primitives/RSA.btrc` and `TLS/X509Algorithm.btrc`.
- **L2**: Used a `volatile` mask in `Field25519.swap`, wiped stack limb buffers
  in `Field25519` (`pack`, `multiply`, `invert`, `power2523`, `equal`,
  `parity`), added `__del__` wiping to `Poly1305`, `SHA512State`, and
  `SHA256State`, rejected negative `length` in `SHA512State.update`, and added
  defensive null checks in `AESGCM` and `ChaCha20Poly1305` and finite-point
  check in `ECDH.multiply`.
- **L3**: Accepted RFC 5280 20-octet positive serial numbers whose MSB >= 0x80
  (21 DER content bytes with leading `0x00`), rejected duplicate identical
  attributes in one RDN SET (`X509Identity.btrc`), raised the SAN cap to 512,
  and aligned the TLS 1.2 single-certificate cap with TLS 1.3 (128 KiB).

## Scope and Caveats

- Review provenance: this was an internal AI-assisted adversarial source audit
  paired with ASan/UBSan and OpenSSL interoperability tests, not an external
  third-party human cryptographic audit, formal proof, or side-channel
  (dudect/Valgrind/disassembly) evaluation.
- Whole-bundle fail-closed parsing (`src/stdlib/TLS/X509TrustBundle.btrc:63-64`):
  `X509TrustBundle.parse` rejects the entire CA bundle if any `CERTIFICATE`
  block contains malformed or truncated DER, unknown critical extensions, or
  mismatched outer/inner `signatureAlgorithm` (H2). Well-formed trust anchors
  with unsupported verification algorithms or constraints (such as P-521 or
  Ed448 roots, X.509 v1 roots, legacy negative serial numbers, or non-DNS/IP
  `nameConstraints`) remain parsed for subject-hash indexing and explicit
  `-addreject serverAuth` matching, while failing closed during path
  verification (`X509_KEY_UNSUPPORTED` / `unsupportedNameConstraints` / missing
  `basicConstraints`).
- No Public Suffix List (`src/stdlib/TLS/X509PeerName.btrc:45`): wildcard DNS
  matching requires at least two suffix labels (`*.a.b`), so two-label public
  suffixes such as `*.co.uk` are syntactically accepted if signed by a trusted
  CA.

## Known Scope Limits

- Key exchange: X25519 (TLS 1.2 & 1.3); P-256 and P-384 via TLS 1.3 HRR.
- No session resumption, PSK, 0-RTT, client certificates, OCSP stapling, or CRL
  checking.
- No SOCKS5 GSSAPI (Kerberos) or non-HTTP/HTTPS/SOCKS proxy schemes (such as
  `ftp://`), which now fail closed on Linux instead of invoking `curl`.
- Package architecture: `HTTP -> TLS -> Crypto -> Digest` is acyclic via
  `Library.TLS.TLSStream` (`ITLSByteStream`).
