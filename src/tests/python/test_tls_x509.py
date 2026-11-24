"""Read OpenSSL-generated certificates, compare the exact verification inputs, and reject malformed DER."""

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder
from tools.qualification.dependencies import DependencyAudit

ROOT = Path(__file__).resolve().parents[3]


def tlv(tag, body):
    size = len(body)
    width = (size.bit_length() + 7) // 8
    length = bytes([size]) if size < 128 else bytes([128 + width]) + size.to_bytes(width, "big")
    return bytes([tag]) + length + body


def body(value):
    width = value[1] & 127
    return value[2 + width :] if value[1] & 128 else value[2:]


def children(value):
    result = []
    data = body(value)
    while data:
        length = data[1]
        start = 2
        if length & 128:
            start += length & 127
            length = int.from_bytes(data[2:start], "big")
        assert start + length <= len(data)
        result.append(data[: start + length])
        data = data[start + length :]
    return result


def change(value, index, replacement):
    parts = children(value)
    parts[index] = replacement
    return tlv(value[0], b"".join(parts))


def extension(oid, raw, critical=False):
    return tlv(48, tlv(6, bytes.fromhex(oid)) + (b"\x01\x01\xff" if critical else b"") + tlv(4, raw))


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("requires OpenSSL to issue independent test certificates")
    directory = tmp_path_factory.mktemp("x509-certificates")
    curves = {"P256": ("P-256", "-sha256"), "P384": ("P-384", "-sha384")}
    examples = []
    for name, scheme, bits in (
        ("RSA", 0x0401, 2048),
        ("P256", 0x0403, 256),
        ("P384", 0x0503, 384),
        ("ed25519", 0x0807, 256),
        ("pss256", 0x0804, 2048),
        ("pss384", 0x0805, 2048),
        ("pss512", 0x0806, 2048),
        ("rsa384", 0x0501, 2048),
        ("rsa512", 0x0601, 2048),
    ):
        if name == "RSA":
            options = ["-newkey", "rsa:2048", "-keyout", str(directory / "rsa.key"), "-sha256"]
        elif name in curves:
            curve, digest = curves[name]
            options = ["-newkey", "ec", "-pkeyopt", f"ec_paramgen_curve:{curve}", digest]
        elif name == "ed25519":
            options = ["-newkey", "ed25519"]
        else:
            options = ["-key", str(directory / "rsa.key"), "-sha" + name[-3:]]
            if name.startswith("pss"):
                options += ["-sigopt", "rsa_padding_mode:pss", "-sigopt", "rsa_pss_saltlen:digest"]
        if "-newkey" in options and "-keyout" not in options:
            options += ["-keyout", str(directory / f"{name}.key")]
        cmd = [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-days",
            "3",
            "-set_serial",
            "149",
            "-subj",
            "/O=btrc/CN=test.example",
            "-addext",
            "basicConstraints=critical,CA:TRUE,pathlen:3",
            "-addext",
            "keyUsage=critical,digitalSignature,keyCertSign",
            "-addext",
            "extendedKeyUsage=serverAuth",
            "-addext",
            "subjectAltName=DNS:test.example,IP:127.0.0.1,IP:2001:db8::1",
            "-addext",
            "nameConstraints=critical,permitted;DNS:.example,excluded;IP:127.0.0.0/255.0.0.0",
            *options,
            "-outform",
            "DER",
        ]
        result = subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        examples.append((name, scheme, bits, result.stdout))
    return examples


def run_batch(client, directory, records, *, details=False, anchor=False):
    source = directory / "records"
    with source.open("wb") as file:
        for record in records:
            file.write(len(record).to_bytes(3, "big") + record)
    env = os.environ | {"ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"}
    result = subprocess.run(
        [str(client), str(source), *(["details"] if details else (["anchor"] if anchor else []))],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr, result.stderr
    return result.stdout.splitlines()


def unix_seconds(value):
    return int(datetime.strptime(body(value).decode("ascii"), "%y%m%d%H%M%SZ").replace(tzinfo=UTC).timestamp())


def verify_fields(client, directory, scheme, bits, cert):
    fields = run_batch(client, directory, [cert], details=True)
    tbs, _, signature = children(cert)
    _, _, _, issuer, validity, subject, key_info, _ = children(tbs)
    since, until = children(validity)
    raw_key = body(children(key_info)[1])[1:]
    assert fields[:3] == [
        f"valid {scheme} {bits} {unix_seconds(since)} {unix_seconds(until)} true 3 33 true",
        tbs.hex(),
        body(signature)[1:].hex(),
    ]
    if bits == 2048:
        modulus, exponent = children(raw_key)
        assert fields[3:5] == [body(modulus).lstrip(b"\0").hex(), body(exponent).hex()]
    else:
        assert fields[3:5] == ["", ""]
    assert fields[5:] == [
        raw_key.hex(),
        issuer.hex(),
        subject.hex(),
        "2=746573742e6578616d706c65,7=7f000001,7=20010db8000000000000000000000001",
        "2=2e6578616d706c65",
        "7=7f000000ff000000",
    ]


def malformed(cert):
    tbs, algorithm, signature = children(cert)
    tbs_fields = children(tbs)
    extra = children(tbs_fields[-1])[0]
    entries = children(extra)

    def with_extensions(items):
        return change(cert, 0, change(tbs, -1, tlv(163, tlv(48, b"".join(items)))))

    def swap_extension(oid, value):
        return with_extensions([e for e in entries if body(children(e)[0]).hex() != oid] + [value])

    def bad_san(value):
        return swap_extension("551d11", extension("551d11", tlv(48, value)))

    def bad_authority(fields):
        return swap_extension("551d23", extension("551d23", tlv(48, fields)))

    named_issuer = tlv(161, tlv(130, b"ca.example"))

    def bad_time(value):
        return change(cert, 0, change(tbs, 4, change(tbs_fields[4], 0, value)))

    bad = [
        b"",
        b"\x30\x80\x00\x00",
        b"\x30\x81\x01\x00",
        bytes(131073),
        cert + b"\0",
        cert[1:],
        b"\x30\x84\0" + cert[2:],
        change(cert, 0, change(tbs, 0, tlv(160, tlv(2, b"\1")))),
        change(cert, 0, change(tbs, 1, tlv(2, b"\0"))),
        change(cert, 0, change(tbs, 1, tlv(2, b"\xff"))),
        change(cert, 0, change(tbs, 1, tlv(2, b"\0\x01"))),
        change(cert, 0, change(tbs, 1, tlv(2, bytes(21)))),
        change(cert, 1, tlv(48, tlv(6, bytes.fromhex("2a864886f70d01010b")))),
        change(cert, 1, tlv(48, body(algorithm) + tlv(5, b""))),
        change(cert, 2, tlv(3, b"\x08" + body(signature)[1:])),
        change(cert, 2, tlv(3, body(signature)[:-1])),
        with_extensions(entries + [entries[0]]),
        with_extensions(entries + [extension("2a0304", tlv(5, b""), True)]),
        bad_san(tlv(130, b"hi\0.attacker")),
        bad_san(tlv(130, b"bad\xff.example")),
        bad_san(tlv(135, bytes(5))),
        bad_san(tlv(130, b"a" * 64 + b".example")),
        bad_san(tlv(130, b"left.*.example")),
        bad_time(tlv(23, b"261332120000Z")),
        bad_time(tlv(23, b"250229120000Z")),
        bad_time(tlv(23, b"261101126000Z")),
        bad_time(tlv(24, b"20261101120000Z")),
        bad_time(tlv(23, b"261101120000+0000")),
        swap_extension("551d0e", extension("551d0e", tlv(4, b""))),
        bad_authority(tlv(130, b"\x01")),
        bad_authority(named_issuer),
        bad_authority(named_issuer + tlv(130, b"\xff")),
        bad_authority(named_issuer + tlv(130, b"\x01" * 21)),
        swap_extension("551d13", extension("551d13", tlv(48, tlv(1, b"\0")))),
        swap_extension("551d13", extension("551d13", tlv(48, tlv(2, b"\1")))),
        swap_extension("551d0f", extension("551d0f", tlv(3, b"\x00\x80"))),
        swap_extension("551d1e", extension("551d1e", tlv(48, tlv(160, tlv(48, tlv(134, b"https://example")))), True)),
        swap_extension(
            "551d1e", extension("551d1e", tlv(48, tlv(160, tlv(48, tlv(135, bytes.fromhex("7f000000ff00ff00"))))), True)
        ),
    ]
    # Every proper prefix is invalid irrespective of which inner field it cuts through.
    return bad + [cert[:end] for end in range(1, len(cert))]


def malformed_keys_and_signatures(certificates):
    fixtures = {name: cert for name, _, _, cert in certificates}
    rsa, ec, ed, pss = (fixtures[name] for name in ("RSA", "P256", "ed25519", "pss256"))

    def with_key(cert, key):
        tbs = children(cert)[0]
        return change(cert, 0, change(tbs, 6, key))

    def parts(cert):
        spki = children(children(cert)[0])[6]
        alg, public = children(spki)
        return spki, alg, body(public)[1:]

    spki, _, ints = parts(rsa)
    modulus, exponent = children(ints)

    def rsa_pair(n, e):
        return with_key(rsa, change(spki, 1, tlv(3, b"\0" + tlv(48, n + e))))

    invalid = [
        rsa_pair(tlv(2, b"\x01" + bytes(126) + b"\x01"), exponent),
        rsa_pair(tlv(2, body(modulus)[:-1] + b"\xfe"), exponent),
        rsa_pair(tlv(2, b"\0" + body(modulus)), exponent),
        rsa_pair(modulus, tlv(2, b"\x02")),
        rsa_pair(modulus, modulus),
    ]
    ec_spki, curve, point = parts(ec)
    invalid += [
        with_key(ec, change(ec_spki, 0, change(curve, 1, tlv(6, bytes.fromhex("2b81040023"))))),
        with_key(ec, change(ec_spki, 1, tlv(3, b"\0\x02" + point[1:33]))),
        with_key(ec, change(ec_spki, 1, tlv(3, b"\0" + point[:-1]))),
    ]
    for integer in (b"\x00", b"\xff", b"\x00\x01", bytes(50)):
        invalid.append(change(ec, 2, tlv(3, b"\0" + tlv(48, tlv(2, integer) + tlv(2, b"\x01")))))
    ed_spki, ed_alg, _ = parts(ed)
    invalid += [
        with_key(ed, change(ed_spki, 0, tlv(48, body(ed_alg) + tlv(5, b"")))),
        with_key(ed, change(ed_spki, 1, tlv(3, bytes(32)))),
    ]
    tbs, sig_alg, _ = children(pss)
    parameters = children(sig_alg)[1]
    for altered in (
        change(parameters, 2, tlv(162, tlv(2, b"\x14"))),
        change(
            parameters,
            1,
            tlv(
                161,
                tlv(
                    48,
                    tlv(6, bytes.fromhex("2a864886f70d010108")) + tlv(48, tlv(6, bytes.fromhex("608648016503040202"))),
                ),
            ),
        ),
        tlv(48, body(parameters) + tlv(163, tlv(2, b"\x01"))),
    ):
        # Set both identifiers alike so only the malformed PSS parameters fail.
        alg = change(sig_alg, 1, altered)
        invalid.append(change(change(pss, 0, change(tbs, 2, alg)), 1, alg))
    return invalid


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", False), ("gcc", True), ("clang", True)])
def test_x509_reader(tmp_path, request, compiler, c_compiler, sanitized, certificates):
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    for path in (ROOT / "src/stdlib/TLS").glob("*.btrc"):
        if path.name == "DER.btrc" or path.name.startswith("X509"):
            shutil.copy(path, tmp_path / path.name)
    source = tmp_path / "X509Inspect.btrc"
    shutil.copy(ROOT / "src/tests/native/tls" / source.name, source)
    generated = tmp_path / "Program.c"
    plan = _transpile(compiler, source, generated, request)
    client = tmp_path / "Program"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=client,
        cc=c_compiler,
        optimization=1 if sanitized else 2,
        compile_flags=["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", *flags],
        link_flags=flags,
    )
    assert DependencyAudit().binary_problems(client, PackageTarget.parse(None).label) == []
    for _, scheme, bits, cert in certificates:
        verify_fields(client, tmp_path, scheme, bits, cert)
    ed = next(cert for name, _, _, cert in certificates if name == "ed25519")
    invalid = malformed(ed) + malformed_keys_and_signatures(certificates)
    assert run_batch(client, tmp_path, invalid) == ["invalid"] * len(invalid)
    tbs = children(ed)[0]
    year = body(children(children(tbs)[4])[0])
    legacy_time = change(tbs, 4, change(children(tbs)[4], 0, tlv(24, b"20" + year)))
    entries = children(children(children(tbs)[-1])[0])
    assert any(body(children(e)[0]).hex() == "551d0f" for e in entries)
    legacy_key_usage = [
        extension("551d0f", tlv(3, b"\x07\x06\x00"), True) if body(children(e)[0]).hex() == "551d0f" else e
        for e in entries
    ]
    historical = [
        change(ed, 0, change(tbs, 1, tlv(2, b"\x00"))),
        change(ed, 0, legacy_time),
        change(ed, 0, change(tbs, -1, tlv(163, tlv(48, b"".join(legacy_key_usage))))),
    ]
    assert run_batch(client, tmp_path, historical) == ["invalid"] * 3
    assert run_batch(client, tmp_path, historical, anchor=True) == ["valid"] * 3
    unknown = change(
        ed, 0, change(tbs, -1, tlv(163, tlv(48, b"".join(entries) + extension("2a0304", tlv(5, b""), True))))
    )
    assert run_batch(client, tmp_path, [unknown, ed[:-1]], anchor=True) == ["invalid", "invalid"]
    # Mutating public keys or signatures can leave the DER syntactically valid;
    # that is the later cryptographic verifier's responsibility.
    flips = [ed[:i] + bytes([ed[i] ^ (1 << (i % 8))]) + ed[i + 1 :] for i in range(len(ed))]
    results = run_batch(client, tmp_path, flips)
    assert len(results) == len(flips) and set(results) == {"valid", "invalid"}
