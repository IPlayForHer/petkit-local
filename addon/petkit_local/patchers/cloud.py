"""Cloud binary patcher — local storage support.

Patches the cloud binary (media uploader) to:
1. Accept LAN IP addresses (isCClassIP → return 0)
2. Skip CURLOPT_CONNECT_TO (curl uses primaryParUrl directly)

Combined with the CA Certificate patch (which adds our self-signed cert to the
device's CA bundle), this enables local media uploads over HTTPS.

All patching is done server-side in Python. The device only transfers
the original binary and receives the pre-validated patched version.
"""
from __future__ import annotations

import io
import logging

from petkit_local.patchers.common import md5hex
from petkit_local.patchers.verify import assert_mips_elf

log = logging.getLogger(__name__)

#: Fixed load address of an ET_EXEC MIPS binary — `vaddr - MIPS_ELF_BASE` is
#: the file offset. Only valid for a non-PIE executable, which is why
#: `patch_cloud` asserts `exec_only`.
MIPS_ELF_BASE = 0x400000


# --- Patch 1: isCClassIP → always return 0 -----------------------------------
# Function ends with: sltu s0,s0,v0; b return; xori s0,s0,1
# The xori inverts the result so s0=1 when IP >= 192.0.0.0.
# Replacing xori with "move s0,zero" makes it always return 0.

ISCC_ORIGINAL = b'\x01\x00\x10\x3a'  # xori s0, s0, 1
ISCC_PATCHED = b'\x21\x80\x00\x00'   # move s0, zero


def _find_isCClassIP(data: bytes) -> int:
    """Find isCClassIP patch point via symbol table or byte pattern."""
    for needle in (ISCC_ORIGINAL, ISCC_PATCHED):
        offset = _find_insn_in_function(data, "isCClassIP", needle,
                                        label="isCClassIP xori/patched")
        if offset is not None:
            return offset
    offset = _find_by_pattern(data, ISCC_ORIGINAL,
                              context_before=b'\x2b\x80\x02\x02',  # sltu s0,s0,v0
                              label="isCClassIP")
    if offset is not None:
        return offset
    raise ValueError("Cannot find isCClassIP in cloud binary")


# --- Patch 2: skip CONNECT_TO ------------------------------------------------
# cloud_do_queue_upload sets CURLOPT_CONNECT_TO with IP from cloudDomain file,
# overriding the URL host. This causes uploads to go to the cached OCI IP
# instead of our server. Patching the beqz that guards CONNECT_TO setopt →
# unconditional branch → CONNECT_TO is never set → curl uses primaryParUrl
# directly. Cloud already handles the NULL CONNECT_TO case (logs warning,
# continues upload).

CONNECT_TO_PATTERN = b'\x03\x28\x05\x24'  # addiu a1, zero, 0x2803


def _find_upload_connect_to(data: bytes) -> int:
    """Find the beqz that guards CURLOPT_CONNECT_TO in cloud_do_queue_upload."""
    func_range = _get_function_range(data, "cloud_do_queue_upload")
    if func_range:
        start, end = func_range
        region = data[start:end]
    else:
        log.warning("Symbol cloud_do_queue_upload not found, searching entire binary")
        region = data
        start = 0

    ct_idx = region.find(CONNECT_TO_PATTERN)
    if ct_idx == -1:
        raise ValueError("Cannot find CURLOPT_CONNECT_TO pattern in cloud_do_queue_upload")
    for back in range(4, 24, 4):
        insn_offset = ct_idx - back
        if insn_offset < 0:
            break
        word = int.from_bytes(region[insn_offset:insn_offset + 4], "little")
        opcode = (word >> 26) & 0x3F
        rs = (word >> 21) & 0x1F
        rt = (word >> 16) & 0x1F
        if opcode == 4 and rt == 0:
            abs_offset = start + insn_offset
            if rs == 0:
                log.info("Found CONNECT_TO guard (already patched to b) at 0x%x",
                         abs_offset)
            else:
                log.info("Found CONNECT_TO guard beqz $%d at 0x%x", rs, abs_offset)
            return abs_offset
    raise ValueError("Cannot find beqz before CURLOPT_CONNECT_TO")


# --- Helpers ------------------------------------------------------------------

def _get_function_range(data: bytes, func_name: str) -> tuple[int, int] | None:
    """Get (file_start, file_end) for a named function via ELF symbols."""
    try:
        from elftools.elf.elffile import ELFFile
        elf = ELFFile(io.BytesIO(data))
        for section_name in (".dynsym", ".symtab"):
            section = elf.get_section_by_name(section_name)
            if not section:
                continue
            for sym in section.iter_symbols():
                if sym.name == func_name and sym["st_info"]["type"] == "STT_FUNC" and sym["st_size"] > 0:
                    start = sym["st_value"] - MIPS_ELF_BASE
                    end = start + sym["st_size"]
                    return start, end
    except Exception as e:
        log.debug("Symbol lookup for %s failed: %s", func_name, e)
    return None


def _find_insn_in_function(data: bytes, func_name: str, needle: bytes,
                           label: str = "") -> int | None:
    """Find a unique instruction within a named function's range."""
    func_range = _get_function_range(data, func_name)
    if not func_range:
        return None
    start, end = func_range
    region = data[start:end]
    idx = region.find(needle)
    if idx == -1:
        return None
    if region.count(needle) > 1:
        log.warning("Multiple %s matches in %s — ambiguous", label, func_name)
        return None
    offset = start + idx
    log.info("Found %s in %s via symbol range at 0x%x", label, func_name, offset)
    return offset


def _find_by_pattern(data: bytes, pattern: bytes, context_before: bytes = b"",
                     label: str = "") -> int | None:
    """Find a byte pattern with optional preceding context bytes."""
    if context_before:
        full = context_before + pattern
        idx = data.find(full)
        if idx != -1 and data.count(full) == 1:
            offset = idx + len(context_before)
            log.info("Found %s via context+pattern at 0x%x", label, offset)
            return offset
    idx = data.find(pattern)
    if idx != -1 and data.count(pattern) == 1:
        log.info("Found %s via unique pattern at 0x%x", label, idx)
        return idx
    return None


def _patch_beqz_to_branch(data: bytes, offset: int) -> bytes:
    """Convert a beqz instruction to an unconditional branch (keep offset).
    BEQ rs,$zero,off → BEQ $zero,$zero,off (= unconditional branch)."""
    word = int.from_bytes(data[offset:offset + 4], "little")
    word &= ~(0x1F << 21)  # zero out rs field (bits 25:21)
    return word.to_bytes(4, "little")


# --- Main entry point ---------------------------------------------------------

def patch_cloud(data: bytes) -> tuple[bytes, list[dict]]:
    """Patch the cloud binary. Returns (patched_data, applied_patches).

    Raises:
        ValueError: If `data` is not a fixed-load-address MIPS32 LE executable,
            if a patch point cannot be found, or if both patches are already in.
    """
    # Both patch points are located by virtual address minus MIPS_ELF_BASE, so
    # a PIE binary would resolve to a wrong offset and be patched silently.
    assert_mips_elf(data, "cloud", exec_only=True)
    patched = bytearray(data)
    applied = []

    # Patch 1: isCClassIP
    offset = _find_isCClassIP(data)
    if data[offset:offset + 4] == ISCC_PATCHED:
        applied.append({"name": "isCClassIP", "offset": offset, "status": "already_applied"})
    else:
        patched[offset:offset + 4] = ISCC_PATCHED
        applied.append({"name": "isCClassIP", "offset": offset, "status": "applied"})

    # Patch 2: skip CONNECT_TO — let curl use URL directly
    offset = _find_upload_connect_to(data)
    new_insn = _patch_beqz_to_branch(data, offset)
    if data[offset:offset + 4] == new_insn:
        applied.append({"name": "skip CONNECT_TO", "offset": offset, "status": "already_applied"})
    else:
        patched[offset:offset + 4] = new_insn
        applied.append({"name": "skip CONNECT_TO", "offset": offset, "status": "applied"})

    patched = bytes(patched)
    if len(patched) != len(data):
        raise RuntimeError(f"Size changed: {len(data)} -> {len(patched)}")

    newly_applied = [a for a in applied if a["status"] == "applied"]
    if not newly_applied:
        raise ValueError("All patches already applied - cloud binary is already patched")

    log.info("Patched cloud binary: %d/%d patches applied (md5 %s -> %s)",
             len(newly_applied), len(applied), md5hex(data), md5hex(patched))
    return patched, applied


PATCHER_INFO = {
    "id": "cloud",
    "name": "Local Storage (Cloud Upload)",
    "description": (
        "Patches the cloud binary to upload photos and videos to your local "
        "bucket server instead of PetKit's cloud. This enables local storage "
        "of event images, video clips, and continuous recordings - no cloud "
        "subscription needed.\n\n"
        "Two changes are made:\n"
        "  1. Accept LAN IP addresses (the firmware blocks uploads to private "
        "IPs by default)\n"
        "  2. Use upload URL directly instead of overriding the connection "
        "target with a cached IP (CURLOPT_CONNECT_TO bypass)\n\n"
        "Requires the CA Certificate patch to be applied as well - cloud "
        "verifies the bucket's TLS certificate against the CA bundle.\n\n"
        "Where uploads go is controlled entirely by the STS token response. "
        "Switching back to PetKit cloud requires no patch changes - just "
        "change the server configuration.\n\n"
        "What it does: copies /app/bin/cloud to /system/cloud_patched, applies "
        "2 byte-level patches (8 bytes total), then updates "
        "/system/app_init.sh to bind-mount the patched binary at boot."
    ),
    "files": ["/system/cloud_patched"],
    # Rewrites machine code: both patch points are found by symbol address and
    # converted with `vaddr - MIPS_ELF_BASE`, and the bytes written are MIPS
    # instructions. Needs a variant per CPU, not a recompile.
    "arch": "mips",
    # Conservative UI figure: what to tell the user BEFORE we know the model.
    # cloud is 304,204 B on a T5 and 188,452 B on a D4SH; size-preserving.
    "needs_bytes": 524288,
}
