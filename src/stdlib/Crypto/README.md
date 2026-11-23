# Library.Crypto

Identity keys, a trusted-key list and an encrypted channel, enough for two
programs to pair and then talk privately over a `TCPStream`.

| Module | What it is |
| --- | --- |
| `Base64` | RFC 4648 encoding and decoding. Pure btrc; builds on every target. |
| `SigningKey` | `PublicKey` and `SigningKey`: Ed25519 identities that read and write OpenSSH's formats. |
| `TrustedKeys` | The public keys a program trusts, kept as OpenSSH key lines in a file (mode 0600). |
| `SecureChannel` | A mutually authenticated, encrypted message channel over a `TCPStream`. |
| `Sodium` | The primitives the others are built from, on raw buffers, and the system's random bytes. |
| `Primitives.*` | The primitives themselves, in btrc: `SHA512`, `BLAKE2b`, `X25519`, `Ed25519`, `ChaCha20`, `Poly1305`, `SecretStream`. |

`import Library.Crypto;` brings the first four. Signatures, key exchange and message encryption use first-party btrc on every
supported target. Random bytes come from the operating system.

## Identities

A `PublicKey` names a party and a `SigningKey` proves it is that party.

```btrc
SigningKey? host = SigningKey.fromOpenSSH(Path.readAll("/etc/ssh/ssh_host_ed25519_key"));
SigningKey own = SigningKey.generate();
print(own.publicKey().toOpenSSH("my desk"));   // an authorized_keys line
print(own.publicKey().fingerprint());          // what `ssh-keygen -l` prints
```

`SigningKey.fromOpenSSH` reads an unencrypted OpenSSH private key file, so a
machine's SSH host key can be its identity, and `toOpenSSH` writes one that
`ssh-keygen` reads. `PublicKey.fromOpenSSH` reads the
key out of an `authorized_keys` or `known_hosts` line, so a peer can be
trusted by a line that already exists. Passphrase-protected keys and other
key types are refused (null).

## Trust

`TrustedKeys(path)` loads a list, `contains(key)` answers whether a peer is
trusted, and `add`, `addLine` and `remove` change the list and save it.

## The channel

```btrc
SecureChannel channel = SecureChannel.connect(stream, own, 3000);   // or .accept
if (!trusted.contains(channel.peer())) {
	print(f"Pair with {channel.peer().fingerprint()}? Code {channel.pairingCode()}");
}
channel.send(message, 1000);
int length = channel.receive(reply, 1000);   // a length, or a SecureChannelResult
```

The handshake follows SIGMA-I: both sides exchange fresh X25519 keys and
derive one key per direction, then each signs the hash of that exchange under
its role with its Ed25519 identity, and the proofs travel encrypted. Every
later message is one XChaCha20-Poly1305 secretstream frame, so an altered,
replayed or reordered frame ends the channel.

The channel proves who the peer is; the program decides whether to trust it.
For a key it has not seen, both sides show `pairingCode()` (six digits from
the exchange and both identities) and a person confirms they match. An
attacker in the middle holds different exchange keys, so the codes differ.

The wire format, for another implementation:

1. Initiator sends `"BTRCSC01"` and its 32-byte exchange key; the responder
   answers with its 32-byte exchange key.
2. Each side sends the 24-byte secretstream header for its sending direction.
   Keys are the session keys of libsodium's `crypto_kx` (the initiator is the
   client): BLAKE2b-512 of the X25519 secret, the initiator's exchange key and
   the responder's; the initiator receives with the first half and sends with
   the second. The stream is libsodium's
   `crypto_secretstream_xchacha20poly1305`, with tag 0 on every frame.
3. Each side sends one frame holding its 32-byte public key and its 64-byte
   signature of `role || BLAKE2b-256("BTRCSC01" || initiatorKey || responderKey)`,
   where role is `I` or `R`.
4. A frame is a 2-byte big-endian length and that many sealed bytes: a
   message of 1 to 16384 bytes plus the 17-byte secretstream overhead.

Neither the construction nor the code under it has been audited.

## Primitives

`Primitives/` holds the cryptography, written in btrc and the same on every
target. `Sodium` is the seam the rest of the group calls: it computes what
libsodium's functions of the same purpose compute, bit for bit, so a peer or a
file made with libsodium works unchanged. That is where its name comes from;
libsodium itself is not used, and nothing else is linked in its place.

| Module | What it computes |
| --- | --- |
| `Primitives.SHA512` | SHA-512 (FIPS 180-4). SHA-256 is `Library.Digest.SHA256`. |
| `Primitives.BLAKE2b` | BLAKE2b (RFC 7693), unkeyed, 1 to 64 bytes. |
| `Primitives.X25519` | X25519 (RFC 7748). A result of all zeros, which a small-order point gives, is reported as unusable. |
| `Primitives.Ed25519` | Ed25519 (RFC 8032): keys from a seed, deterministic signatures, verification. |
| `Primitives.ChaCha20` | ChaCha20 with a 96-bit nonce (RFC 8439) and HChaCha20. |
| `Primitives.Poly1305` | Poly1305 (RFC 8439). |
| `Primitives.SecretStream` | libsodium's `crypto_secretstream_xchacha20poly1305`, state layout included. |

Verification is as strict as libsodium's default. It refuses a signature
whose scalar is not below the group order, a signature point or public key of
small order, a public key that is not the canonical encoding of a point, and
anything whose recomputed point differs from the one sent.

What handles secrets (the X25519 ladder, the Ed25519 base-point multiplication,
the field arithmetic under both, Poly1305 and the comparison of
authenticators) is written to run the same instructions whatever the secret:
choices are masked swaps and selections, never branches or table indices.
That is a property of the source. Nothing measures the machine code a C
compiler makes of it, and the multiplication is the simple one: 16 limbs of 16
bits, about as fast as TweetNaCl, far slower than libsodium's.

`Sodium.wipe` overwrites through a volatile view, which a C compiler may not
remove as a dead store. The primitives clear the same way what they are done
with and can name: expanded keys, scalars, ladder state, cipher blocks, and a
hash's or authenticator's state when it finishes. The products inside a field
multiplication are not cleared, as they are not in libsodium.

**The primitives are first-party and have not been audited.** They are tested
against published vectors and against libsodium, which is evidence of
agreement, not of the absence of side channels or of errors the vectors do not
reach.

## Random bytes

`Sodium.random` and `Sodium.randomBytes` read the operating system's
generator, which is the one part of the seam that differs by target:

| Target | Source |
| --- | --- |
| Linux, Android | `getrandom` (`Unix/SystemRandomProvider.btrc`) |
| macOS, iOS, iPadOS | `arc4random_buf` (`Apple/SystemRandomProvider.btrc`) |
| Windows | `BCryptGenRandom` with the system-preferred generator, from bcrypt.dll (`Windows/SystemRandomProvider.btrc`) |

A call the system interrupts is retried. If the system cannot supply the
bytes the call throws: nothing weaker is ever substituted.

## Providers

`Sodium`, `SigningKey`, `Base64` and the primitives build on every target.
`TrustedKeys` has rows where a file can be kept private with a POSIX mode:
Linux, macOS, iOS and Android. `SecureChannel`, and so the `Crypto` facade
that imports it, has rows where `Library.Network`'s `TCPStream` does: Linux,
macOS and iOS.

## Tests

- `src/tests/stdlib/Base64Codec.btrc`: the corpus, on every target.
- `src/tests/stdlib/CryptoPrimitives.btrc`: the corpus, on every target.
  SHA-512, BLAKE2b, X25519, Ed25519, ChaCha20, Poly1305 and HChaCha20 against
  their published vectors; secretstream frames and states captured from
  libsodium 1.0.22, across a rekey and a counter wrap; and what must be
  refused: small-order points, non-canonical keys and scalars, three
  signatures that satisfy the verification equation through a small-order
  point, and altered, repeated, shortened or reordered frames.
- `src/tests/python/test_crypto_runtime.py` builds
  `src/tests/native/crypto/CryptoConformance.btrc` with both frontends, gcc,
  clang and the sanitizers: RFC 8032 signatures, a key line and fingerprint
  from `ssh-keygen`, the trusted-key file, and the channel between two
  processes over a socket pair and over TCP, including a tampered frame, an
  unexpected identity and a peer speaking another protocol. It also has
  `ssh-keygen` write a fresh key pair and checks that btrc loads it and prints
  the same fingerprint, and has `ssh-keygen` read a key btrc wrote.
  `SodiumVectors.btrc` holds the seam to SHA-256's vectors, to the key
  exchange and stream libsodium computes for fixed keys, and draws from the
  system's generator. The driver asserts that every link plan names no
  package, library or framework, that the executables import only system and compiler runtime libraries, that Android builds the seam and the keys, and that Windows
  builds them into an executable linked with bcrypt alone.
- `src/tests/python/test_stdlib_ios_programs.py` runs the conformance program
  as a process of the iPhone and iPad simulators, through both frontends,
  plain and sanitized. No physical device has run it.

The first-party code was compared with libsodium 1.0.22 on random inputs for
every operation before libsodium was removed (hashes, X25519, the key
exchange, signing, verification of valid and malformed signatures, ChaCha20,
Poly1305, and streams of several frames with each side played by each
implementation). That comparison is not in the tree, because it needs
libsodium; the vectors above are what it left behind.
