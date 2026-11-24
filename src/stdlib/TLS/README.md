# TLS

This first-party, unaudited package implements the TLS 1.2 and 1.3 client
under qualification for Linux HTTP. Production Linux HTTPS still uses curl.
The dependency policy calls for independent security review before changing
that default.

The package-private `LinuxTLSStream` wraps a connected `IHTTPByteStream`.
It sends one ClientHello, negotiates the protocol on that connection, and
verifies the peer's certificate path, identity, handshake signature and
Finished before exchanging HTTP data. Socket setup, proxy negotiation, TLS
and HTTP share the request's absolute deadline.

TLS 1.3 offers X25519 with P-256 and P-384 available through HelloRetryRequest.
TLS 1.2 supports ECDHE with X25519, RSA or ECDSA authentication and the
extended master secret. Both support AES-128-GCM, AES-256-GCM and
ChaCha20-Poly1305. The HTTP client offers HTTP/1.1 through ALPN. TLS 1.3
processes traffic-key updates, validates and discards session tickets, and
answers optional client-certificate requests with an empty certificate.
A server requiring a client certificate can reject the handshake. For a
close-delimited HTTP body the transport requires an authenticated
`close_notify` before treating the response as complete.

The public `TLS13Keys.expandLabel` implements RFC 8446 key derivation with
SHA-256 or SHA-384. `TLS13Records.create` creates one traffic direction
and bounds each epoch to 2^24 records.

The Linux qualification provider exercises the public HTTP client directly,
over HTTP CONNECT, over HTTPS CONNECT with separately authenticated proxy
and origin, and over SOCKS4, SOCKS4a, SOCKS5 and SOCKS5h. The HTTPS proxy
uses the system trust store. Origin CA environment overrides apply to the
origin only. An installed curl still handles SOCKS5 GSSAPI negotiation and
requests whose explicit Proxy-Authorization header relies on curl semantics.
`src/tests/python/test_linux_tls_http.py` and `test_linux_tls_socks.py`
exercise these routes with both compilers. `test_tls_alerts.py` and
`test_tls13_key_update.py` verify alerts, closure and traffic-key changes
with an independent OpenSSL peer.

The package-private `X509Certificate.parse` reader copies one DER-encoded
v3 certificate of up to 128 KiB. It exposes the original signed bytes,
signature, issuer and subject encodings, Unix validity times and public key.
Supported keys are RSA with a 2048–8192-bit modulus, uncompressed P-256 or
P-384, and Ed25519. RSA-PSS signatures over RSA encryption keys are supported
with matching SHA-256, SHA-384 or SHA-512 message and MGF1 digests and a
digest-length salt. Keys with the RSASSA-PSS identifier also enforce the
hash, mask digest and minimum salt length declared in the public key.

The parser reads basic constraints, key usage, extended key usage, SANs,
DNS/IP name constraints and authority and subject key identifiers. Unknown critical extensions and unsupported
constraint types fail parsing. One certificate admits up to 64 extensions,
128 subject alternative names and 128 names per constraint list.
Signature verification, EC point verification, trust path construction,
hostname matching and current-time checks belong to the calling validator.

`parseTrustAnchor` is for entries read from the configured trust store.
It also accepts serial zero, pre-2050 GeneralizedTime, and an extra trailing
zero bit in the deployed Trustwave roots' key usage. It decodes the same
validity and usage values and checks critical extensions.

The package-private `X509ServerPath.verify` accepts the parsed leaf, peer
intermediates, local anchors, reference identity and current Unix time in
seconds. It verifies RSA PKCS#1/PSS, NIST P-256/P-384 ECDSA and Ed25519 certificate
signatures. The verifier checks DNS and binary IP subject alternative names,
validity, server purpose, signing
key usage, basic constraints, path length and DNS/IP name constraints. The
search tries alternate issuers, allows explicit non-self-signed local anchors
and bounds peer depth, candidate count and signature work. A TLS 1.3 caller
must separately verify CertificateVerify and Finished before releasing data.

Linux reads PEM trust bundles and consecutive OpenSSL subject-hash
directory entries. Issuer selection compares canonical distinguished names
and available key identifiers. When the authority names an issuing
certificate by issuer and serial number, both must match.
DNS reference identities use A-labels. A configured trust file that cannot
be read or parsed fails verification. OpenSSL TRUSTED CERTIFICATE records
preserve explicit server trust and distrust. A rejected certificate cannot reenter the path as an ordinary peer
or a duplicate anchor. Unsupported auxiliary fields and signature algorithms
still require the existing HTTPS transport. The TLS transport switch remains
subject to the independent review recorded in the dependency ledger.
