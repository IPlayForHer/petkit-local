"""Format checks that stand between a downloaded device file and a patcher.

The fixtures here are hand-built 52-byte ELF headers rather than firmware, so
the suite still needs no device and no blobs in the repo — which is exactly why
`patchers/verify.py` reads the header itself instead of going through
pyelftools.
"""
import os
import struct

import pytest

from petkit_local.patchers.cacert import patch_ca_bundle
from petkit_local.patchers.cloud import patch_cloud
from petkit_local.patchers.mqtt import patch_ctrl
from petkit_local.patchers.ssh import DROPBEAR_LOCAL
from petkit_local.patchers.verify import (
    EM_MIPS, ET_DYN, ET_EXEC, assert_ca_bundle, assert_download_plausible,
    assert_mips_elf, describe_elf, is_mips_elf,
)


def elf_header(*, e_machine=EM_MIPS, e_type=ET_EXEC, ei_class=1, ei_data=1) -> bytes:
    """A 52-byte Elf32_Ehdr, valid enough for everything verify.py reads."""
    ident = b"\x7fELF" + bytes([ei_class, ei_data, 1, 0]) + b"\x00" * 8
    return ident + struct.pack("<HH", e_type, e_machine) + b"\x00" * 32


PEM = (b"-----BEGIN CERTIFICATE-----\nMIIBogIB\n-----END CERTIFICATE-----\n")


# --- what a MIPS binary is --------------------------------------------------

def test_a_real_mips32_executable_is_accepted():
    assert is_mips_elf(elf_header()) is True
    assert_mips_elf(elf_header(), "ctrl", exec_only=True)


def test_a_position_independent_mips_binary_is_accepted_by_default():
    assert is_mips_elf(elf_header(e_type=ET_DYN)) is True


def test_a_position_independent_binary_is_refused_where_the_load_address_matters():
    """`vaddr - 0x400000` is only a file offset for a fixed-load-address ELF.

    A PIE `ctrl` would otherwise be patched at a wrong offset in silence, which
    is the difference between a failed patch and a bricked device.
    """
    pie = elf_header(e_type=ET_DYN)
    assert is_mips_elf(pie, exec_only=True) is False
    with pytest.raises(ValueError, match="not PIE"):
        assert_mips_elf(pie, "ctrl", exec_only=True)


@pytest.mark.parametrize("data, why", [
    (elf_header(e_machine=62), "x86-64"),
    (elf_header(e_machine=40), "arm"),
    (elf_header(e_machine=183), "aarch64"),
    (elf_header(ei_class=2), "64-bit"),
    (elf_header(ei_data=2), "big-endian"),
    (PEM, "a certificate"),
    (b"<!DOCTYPE html><html>404</html>", "an error page"),
    (b"", "nothing at all"),
    (b"\x7fELF\x01\x01", "a truncated header"),
])
def test_anything_that_is_not_a_mips32_le_binary_is_refused(data, why):
    assert is_mips_elf(data) is False, why
    with pytest.raises(ValueError):
        assert_mips_elf(data, "ctrl")


def test_the_shipped_dropbear_is_a_mips_binary():
    """A regression test on the artefact itself: it is installed as the
    device's SSH daemon, so a corrupted or substituted file matters."""
    with open(os.path.normpath(DROPBEAR_LOCAL), "rb") as f:
        head = f.read(64)
    assert is_mips_elf(head) is True
    # Confirms the permissive form is the right one for it — it is PIE.
    assert is_mips_elf(head, exec_only=True) is False


def test_the_error_says_what_actually_arrived():
    """Naming the real content is what stops a transport failure being read as
    a firmware mismatch."""
    with pytest.raises(ValueError) as e:
        assert_mips_elf(b"<!DOCTYPE html>...", "cloud")
    assert "cloud" in str(e.value)
    with pytest.raises(ValueError, match="EM_X86_64"):
        assert_mips_elf(elf_header(e_machine=62), "cloud")
    assert "empty" in describe_elf(b"")


def test_the_binary_patchers_refuse_before_searching_for_a_symbol():
    for patch in (patch_ctrl, patch_cloud):
        with pytest.raises(ValueError, match="MIPS32"):
            patch(PEM)
        with pytest.raises(ValueError, match="MIPS32"):
            patch(b"<!DOCTYPE html>" + b"\x00" * 200)


# --- the CA bundle ----------------------------------------------------------

def test_a_bundle_with_certificates_passes():
    assert_ca_bundle(PEM * 2, "ca.crt")


@pytest.mark.parametrize("data", [b"", b"   \n ", b"<!DOCTYPE html>404 not found"])
def test_an_empty_or_garbage_ca_download_is_refused(data):
    """The old behaviour returned a bundle containing ONLY our certificate,
    which would leave the device unable to verify any other TLS peer."""
    with pytest.raises(ValueError):
        assert_ca_bundle(data, "ca.crt")


@pytest.mark.parametrize("original", [None, b"", b"  \n", b"not a certificate at all"])
def test_the_ca_patcher_refuses_rather_than_replacing_the_whole_trust_store(original):
    ours = b"-----BEGIN CERTIFICATE-----\nOURS\n-----END CERTIFICATE-----\n"
    with pytest.raises(ValueError):
        patch_ca_bundle(original, ours)


def test_the_ca_patcher_still_appends_to_a_real_bundle():
    original = PEM * 2
    ours = b"-----BEGIN CERTIFICATE-----\nOURS\n-----END CERTIFICATE-----\n"
    out = patch_ca_bundle(original, ours)
    assert out.count(b"-----BEGIN CERTIFICATE-----") == 3
    assert out.startswith(original.rstrip())
    with pytest.raises(ValueError, match="already"):
        patch_ca_bundle(out, ours)


# --- transport plausibility -------------------------------------------------

def test_a_short_download_is_named_as_a_transport_failure():
    with pytest.raises(ValueError, match="did not serve"):
        assert_download_plausible(b"x" * 10, "ctrl")


def test_an_html_body_is_named_as_a_transport_failure():
    with pytest.raises(ValueError, match="HTML"):
        assert_download_plausible(b"<html><body>Index of /</body></html>" + b" " * 2000, "ctrl")


def test_a_plausible_download_passes():
    assert_download_plausible(b"\x7fELF" + b"\x00" * 5000, "ctrl")
