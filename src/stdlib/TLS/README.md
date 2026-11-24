# TLS

First-party TLS 1.2 and 1.3 client in pure BTRC over `Library.Crypto`, wired
into `Library.HTTP` as the production Linux HTTPS and proxy TLS transport with
no `curl` or OpenSSL library dependency. See
`docs/design/linux-tls-security-review.md` for the security review findings,
hardening fixes, and verified invariants.

## Architecture and package boundary

`TLS` has no dependency on `HTTP` (`HTTP -> TLS -> Crypto -> Digest` is
strictly acyclic):

- `TLSStream` exports `ITLSByteStream` (`receive`, `send`, `close`).
- `Linux.ClientStream` exports `LinuxTLSStream`, which wraps a connected
  `ITLSByteStream`, negotiates TLS 1.3 or TLS 1.2 on one ClientHello under one
  absolute deadline, and verifies the peer's certificate chain, identity,
  handshake signature, and Finished before admitting application data.
- `TLS13Keys.expandLabel` implements RFC 8446 HKDF-Expand-Label (SHA-256 /
  SHA-384).
- `TLS13Records.create` implements one TLS 1.3 AEAD direction bounded to 2^24
  records per traffic-key epoch, accepting RFC 8446 padded records up to 16640
  ciphertext bytes while capping unpadded inner content at 16384 bytes.

## Protocol scope and limits

- **TLS 1.3 (RFC 8446)**: X25519 key share with P-256 and P-384 via
  HelloRetryRequest; cipher suites `TLS_AES_128_GCM_SHA256`,
  `TLS_AES_256_GCM_SHA384`, and `TLS_CHACHA20_POLY1305_SHA256`; ALPN `http/1.1`;
  middlebox compatibility accepting at most one dummy `ChangeCipherSpec` after
  the first `ServerHello`/`HelloRetryRequest` and never mid-fragment; bounded
  `KeyUpdate` (<= 8 consecutive, <= 32 total) and validated-then-discarded
  `NewSessionTicket` (<= 32 total); empty `Certificate` response to optional
  client-certificate requests; no PSK, no resumption, no 0-RTT.
- **TLS 1.2 (RFC 5246 / 7627 / 7905 / 5746)**: ECDHE with X25519 only, RSA or
  ECDSA/Ed25519 authentication, AEAD suites only (`ECDHE-*-AES128-GCM-SHA256`,
  `ECDHE-*-AES256-GCM-SHA384`, `ECDHE-*-CHACHA20-POLY1305`); requires both
  `extended_master_secret` (0x0017) and `renegotiation_info` (0xff01); enforces
  RFC 8446 §4.1.3 downgrade sentinels (`DOWNGRD\x01` and `DOWNGRD\x00`); refuses
  renegotiation, CBC, RSA key transport, compression, and session resumption.
- **Closure**: close-delimited HTTP bodies require an authenticated
  `close_notify` alert before treating EOF as clean completion.
- **No insecure opt-out**: certificate, hostname, and signature checks cannot
  be disabled.

## X.509 and Linux trust stores

- Strict DER X.509 v3 reader up to 128 KiB per certificate, requiring exact DER
  equality between outer `signatureAlgorithm` and `tbsCertificate.signature`,
  RSA moduli 2048–8192 bits with public exponent <= 8 bytes, uncompressed P-256
  or P-384, or Ed25519, rejecting MD5/SHA-1 below trust anchors and unknown
  critical extensions.
- Bounded path search (<= 10 peer certs, <= 64 signature checks) with
  `basicConstraints`, `pathLenConstraint`, `keyUsage`, `extendedKeyUsage`
  (`serverAuth`), `nameConstraints` (DNS and IP permitted/excluded), RFC 9525
  SAN-only hostname/IP matching (no CN fallback), and OpenSSL `TRUSTED
  CERTIFICATE` explicit distrust matching both full DER and signed TBS bytes.
- Trust anchor selection on Linux (`Linux/TrustFiles.btrc`): explicit
  `CURL_CA_BUNDLE` (isolated, never merges system CAs), or explicit
  `SSL_CERT_FILE` and/or `SSL_CERT_DIR` (isolated, never merges system CAs), or
  the system default CA bundle (`/etc/ssl/certs/ca-certificates.crt`,
  `/etc/pki/tls/certs/ca-bundle.crt`,
  `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`, `/etc/ssl/ca-bundle.pem`,
  `/etc/ssl/cert.pem`) and `/etc/ssl/certs`. HTTPS proxy connections use the
  system store independently of origin CA environment overrides. Unreadable or
  empty configured stores fail closed.
- **Behavioral differences from curl on Linux**: SOCKS5 GSSAPI (Kerberos) and
  non-HTTP/HTTPS/SOCKS proxy schemes (such as `ftp://`) fail closed instead of
  spawning `curl`; `Proxy-Authorization` headers are sent only to HTTP/HTTPS
  proxies and stripped from origin requests.
