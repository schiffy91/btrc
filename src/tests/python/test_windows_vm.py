"""The local Windows 11 guest's host side (tools/target_hosts/windows/vm.py).

These cases need no QEMU and no guest: they hold the machine to what Windows 11
requires, the answer file to its placeholders, and a download to its hash.
"""

import hashlib
import xml.etree.ElementTree as ElementTree

import pytest

from tools.target_hosts.windows.vm import MEDIA, PinnedDownload, WindowsGuest


@pytest.fixture
def guest(tmp_path, monkeypatch):
    firmware = tmp_path / "firmware"
    firmware.mkdir()
    (firmware / "OVMF_CODE.ms.fd").write_bytes(b"code")
    monkeypatch.setattr(WindowsGuest, "tool", lambda self, name: f"/tools/{name}")
    return WindowsGuest(tmp_path / "state", firmware=firmware, port=2244)


def test_the_machine_has_what_windows_11_requires(guest):
    machine = " ".join(guest.machine(installing=False))
    assert "accel=kvm,smm=on" in machine and "property=secure,value=on" in machine
    assert "OVMF_CODE.ms.fd" in machine and "tpm-tis,tpmdev=tpm0" in machine
    assert "-display none" in machine
    assert guest.disk_gib >= 64


def test_the_guest_is_reachable_only_from_this_host(guest):
    assert "hostfwd=tcp:127.0.0.1:2244-:22" in " ".join(guest.machine(installing=False))


def test_only_an_install_attaches_the_discs(guest):
    assert "media=cdrom" not in " ".join(guest.machine(installing=False))
    installing = " ".join(guest.machine(installing=True))
    assert WindowsGuest.IMAGE.name in installing and "setup.iso" in installing
    # The empty disk is tried first, so the installed system boots without the disc's "any key" prompt.
    assert "drive=system,bus=ide.0,bootindex=1" in installing and "drive=windows,bus=ide.1,bootindex=2" in installing


def test_the_machine_refuses_a_missing_firmware(tmp_path):
    with pytest.raises(FileNotFoundError, match="Secure Boot firmware"):
        WindowsGuest(tmp_path, firmware=tmp_path / "absent").machine(installing=False)


def test_the_answer_file_is_well_formed_and_names_every_placeholder_twice():
    answers = (MEDIA / "autounattend.xml").read_text()
    assert answers.count("@USER@") == 2 and answers.count("@PASSWORD@") == 2
    ElementTree.fromstring(answers.replace("@USER@", WindowsGuest.USER).replace("@PASSWORD@", "secret"))
    # The first-logon command finds its script on whichever letter the setup disc got.
    assert "Setup.ps1" in answers and (MEDIA / "Setup.ps1").is_file() and (MEDIA / "RunJob.ps1").is_file()


def test_a_download_is_admitted_only_with_its_hash(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"installer")
    digest = hashlib.sha256(b"installer").hexdigest()
    assert PinnedDownload("good", source.as_uri(), digest).fetch(tmp_path).read_bytes() == b"installer"
    with pytest.raises(ValueError, match="expected SHA-256"):
        PinnedDownload("bad", source.as_uri(), "0" * 64).fetch(tmp_path)
    assert not (tmp_path / "bad").exists() and not (tmp_path / "bad.part").exists()
