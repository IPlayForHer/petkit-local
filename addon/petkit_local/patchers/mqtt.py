"""MQTT cert bypass patcher.

Patches one function in the ctrl binary — mbedtls_x509_crt_verify_with_profile
— so the device accepts our self-signed broker certificate.

This function is called DURING the TLS handshake by ssl_parse_certificate to
validate the server's cert chain against the built-in ali_ca_cert (GlobalSign
Root CA for Aliyun IoT). With the stock code our self-signed cert fails here,
the handshake returns a non-zero error, and the Aliyun Link SDK reports
-0x0F23. Zeroing the return value AND the *flags output makes the handshake
succeed; mbedtls_ssl_get_verify_result (post-handshake readback) then returns 0
naturally because ssl_parse_certificate stored the zeroed flags.

Verified: patching verify_with_profile alone is sufficient. The earlier attempt
patching only get_verify_result failed because that function is behind the
handshake gate — it is never reached when the handshake itself fails.

The function is statically linked into ctrl (no shared library).
"""
from __future__ import annotations

import io
import logging

from petkit_local.patchers.common import md5hex
from petkit_local.patchers.verify import assert_mips_elf

log = logging.getLogger(__name__)

#: Fixed load address of an ET_EXEC MIPS binary — `vaddr - MIPS_ELF_BASE` is
#: the file offset. Only valid for a non-PIE executable, which is why
#: `patch_ctrl` asserts `exec_only`.
MIPS_ELF_BASE = 0x400000

SYMBOL_NAME = "mbedtls_x509_crt_verify_with_profile"

# Original prologue (MIPS32 LE):
#   lui   $gp, 0x000b          = 0b 00 1c 3c
#   addiu $gp, $gp, -0x6e48    = b8 91 9c 27
#   addu  $gp, $gp, $t9        = 21 e0 99 03
#   addiu $sp, $sp, -0x68      = 98 ff bd 27
ORIGINAL_PROLOGUE = b'\x0b\x00\x1c\x3c\xb8\x91\x9c\x27\x21\xe0\x99\x03\x98\xff\xbd\x27'

# Replacement (16 bytes, same size as the overwritten prologue):
#
# MIPS o32 ABI: args 1-4 in $a0-$a3, arg 5+ on stack.
#   arg6 = uint32_t *flags  →  at sp+0x14 on entry
#
#   lw    $v1, 0x14($sp)   → load flags pointer (arg6)
#   sw    $zero, 0($v1)    → *flags = 0
#   jr    $ra              → return
#   move  $v0, $zero       → return value = 0 (delay slot)
PATCH_BYTES = (
    b'\x14\x00\xa3\x8f'   # lw   $v1, 0x14($sp)
    b'\x00\x00\x60\xac'   # sw   $zero, 0($v1)
    b'\x08\x00\xe0\x03'   # jr   $ra
    b'\x21\x10\x00\x00'   # move $v0, $zero
)


def _find_via_dynsym(data: bytes) -> int | None:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return None
    try:
        elf = ELFFile(io.BytesIO(data))
        dynsym = elf.get_section_by_name(".dynsym")
        if not dynsym:
            return None
        for sym in dynsym.iter_symbols():
            if sym.name == SYMBOL_NAME and sym["st_info"]["type"] == "STT_FUNC":
                vaddr = sym["st_value"]
                offset = vaddr - MIPS_ELF_BASE
                log.info("Found %s via .dynsym at vaddr 0x%x (file offset 0x%x)",
                         SYMBOL_NAME, vaddr, offset)
                return offset
    except Exception as e:
        log.warning("pyelftools parsing failed: %s", e)
    return None


def _find_via_pattern(data: bytes) -> int | None:
    offset = data.find(ORIGINAL_PROLOGUE)
    if offset == -1:
        return None
    if data.count(ORIGINAL_PROLOGUE) > 1:
        log.warning("Multiple matches for %s prologue — ambiguous", SYMBOL_NAME)
        return None
    log.info("Found %s via byte pattern at file offset 0x%x", SYMBOL_NAME, offset)
    return offset


def find_offset(data: bytes) -> int:
    """Find mbedtls_x509_crt_verify_with_profile in the ctrl binary."""
    offset = _find_via_dynsym(data)
    if offset is not None:
        if data[offset:offset + len(ORIGINAL_PROLOGUE)] != ORIGINAL_PROLOGUE:
            log.warning("Symbol offset 0x%x doesn't match expected prologue, "
                        "trying byte pattern", offset)
            offset = None
    if offset is None:
        offset = _find_via_pattern(data)
    if offset is None:
        raise ValueError(f"Cannot find {SYMBOL_NAME} in ctrl binary — "
                         "neither .dynsym nor byte pattern matched")
    return offset


def patch_ctrl(data: bytes) -> tuple[bytes, int]:
    """Patch the ctrl binary. Returns (patched_data, offset).

    Raises:
        ValueError: If `data` is not a fixed-load-address MIPS32 LE executable,
            or if the symbol cannot be located, or if it is already patched.
    """
    # Before searching for anything: both offset paths below convert a virtual
    # address with MIPS_ELF_BASE, so a PIE binary would yield a plausible-looking
    # offset into the wrong place and be patched without complaint.
    assert_mips_elf(data, "ctrl", exec_only=True)
    offset = find_offset(data)

    if data[offset:offset + len(PATCH_BYTES)] == PATCH_BYTES:
        raise ValueError("ctrl binary is already patched")

    patched = bytearray(data)
    patched[offset:offset + len(PATCH_BYTES)] = PATCH_BYTES
    patched = bytes(patched)

    if patched[offset:offset + len(PATCH_BYTES)] != PATCH_BYTES:
        raise RuntimeError("Patch verification failed — bytes don't match after write")
    if len(patched) != len(data):
        raise RuntimeError(f"Size changed: {len(data)} -> {len(patched)}")

    log.info("Patched %s at offset 0x%x (md5 %s -> %s)",
             SYMBOL_NAME, offset, md5hex(data), md5hex(patched))
    return patched, offset


PATCHER_INFO = {
    "id": "mqtt",
    "name": "MQTT TLS Bypass",
    "description": (
        "Patches the ctrl binary so it accepts any MQTT broker certificate "
        "(mbedtls_x509_crt_verify_with_profile → return 0). This is the "
        "function that validates the server's cert chain during the TLS "
        "handshake; with the stock code, our self-signed cert is rejected "
        "before any MQTT byte is exchanged.\n\n"
        "This allows the device to connect to petkit-local's embedded MQTT "
        "broker over TLS, enabling real-time commands and event streaming "
        "instead of the slower HTTP heartbeat polling.\n\n"
        "What it does: copies /app/bin/ctrl to /system/ctrl_patched, patches "
        "16 bytes (the x509 certificate chain verification function), then "
        "updates /system/app_init.sh to bind-mount the patched binary before "
        "the stock init starts ctrl. Requires a reboot to take effect."
    ),
    "files": ["/system/ctrl_patched"],
    # Rewrites machine code: the verify function is neutered by writing a MIPS
    # `return 0` at an address found with `vaddr - MIPS_ELF_BASE`. Needs a
    # variant per CPU, not a recompile.
    "arch": "mips",
    # Conservative UI figure: what to tell the user BEFORE we know the model.
    # ctrl is 1,420,656 B on a T5 and 903,148 B on a D4SH; the patch
    # preserves size, so the write is one full copy of the binary.
    "needs_bytes": 2097152,
    "check_field": "mqtt_connected",
}
