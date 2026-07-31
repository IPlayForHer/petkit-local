"""Persistent SSH access patcher.

Installs dropbear on port 22 with public-key authentication, using the
/system/app_init.sh boot hook shared with the other patchers. Dropbear starts
before the stock init, survives reboots and app OTA.

Unlike the binary patchers (mqtt, cloud, cacert), this one needs user input:
a public key. The panel accepts it at apply time, stores it on
`device.config["ssh_pubkey"]`, and writes it to `/system/authorized_keys` on
the device. Password auth is disabled.

The dropbear binary is a pre-built static MIPS32 LE build (musl, UPX, ~153 KB)
served from the device-facing patcher download path, NOT from the panel's
/static/ — the device wget's from api_url, which is the device-facing app.

If an older `test_case_root` persistence script exists from a prior ssh method,
it is renamed out of the `test_case_*` glob so only one thing listens on port 22.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

DROPBEAR_PATH = "/system/dropbear"
DBKEY_PATH = "/system/dbkey_ecdsa"
AUTHKEYS_PATH = "/system/authorized_keys"
#: The ECDSA host key is generated ON the device by `dropbearkey`, so its size
#: is not known here. An ECDSA-256 dropbear key file is a few hundred bytes;
#: reserve 4 KB so the space check accounts for a file we never see.
DBKEY_RESERVE_BYTES = 4096
TEST_CASE_ROOT = "/system/test_case_root"
TEST_CASE_ROOT_OLD = "/system/old_test_case_root"

# The binary lives inside the package and is staged for download on apply.
DROPBEAR_BIN_NAME = "dropbear-mipsel"
DROPBEAR_LOCAL = os.path.join(os.path.dirname(__file__), "..", "web", "static", "bin", DROPBEAR_BIN_NAME)

PATCHER_INFO = {
    "id": "ssh",
    "name": "Persistent SSH Access",
    "description": (
        "Installs Dropbear SSH on port 22 with public key authentication. "
        "Uses the /system/app_init.sh boot hook for persistence — SSH starts "
        "before any PetKit processes and survives reboots, app OTA updates, and "
        "factory resets (as long as /system is not formatted).\n\n"
        "The dropbear binary is a static MIPS32 LE build (musl, UPX, ~153 KB) "
        "with ECDSA host key and RSA/ECDSA pubkey auth. Password auth is "
        "disabled. The host key is generated once at install and kept on "
        "/system, so the fingerprint stays the same across reboots.\n\n"
        "Requires a public key — paste one in the field below before applying. "
        "The key is stored per device and reused on re-apply.\n\n"
        "If a test_case_root script from a prior ssh method is found, it is "
        "renamed to old_test_case_root (outside the test_case_* glob) to avoid "
        "running two SSH servers on port 22."
    ),
    "files": [DROPBEAR_PATH, DBKEY_PATH, AUTHKEYS_PATH],
    # Installs a prebuilt binary — the shipped dropbear is a static MIPS32 LE
    # build. Unlike the two code patchers this needs no new logic for another
    # CPU, only a dropbear built for it.
    "arch": "mips",
    # Conservative UI figure: what to tell the user BEFORE we know the model.
    # the shipped dropbear-mipsel is 156,208 B, plus a host key and
    # authorized_keys.
    "needs_bytes": 262144,
    "needs_pubkey": True,
}


AUTHKEYS_STAGED_NAME = "authorized_keys"


def build_install_commands(download_base: str) -> list[str]:
    """Shell commands to install dropbear on the device.

    Each is queued as a separate run_cmd and waited on individually, because
    the heartbeat queue is at-most-once and a chained `&&` that fails partway
    through cannot be retried from the failure point.

    The pubkey is NOT written via `echo '...' > file` — an RSA key is ~580
    bytes, and the heartbeat's run_cmd content field is embedded inside a JSON
    string inside an HTTP response body. Escaping, quoting and shell expansion
    across that many layers turned out to produce garbage on the device (the
    `authorized_keys?Q` incident). Instead the key is staged as a file and
    fetched with wget, exactly like the dropbear binary — the one path that is
    proven to deliver bytes unchanged.

    The host key IS pre-generated and stored on `/system` so it survives every
    reboot. Without this, `-R` writes to `/tmp` (its default), `/tmp` is wiped
    on reboot, and the key changes every boot — which means every reboot prints
    `REMOTE HOST IDENTIFICATION HAS CHANGED` on the client. The generation
    uses the multi-call trick: `cp dropbear /tmp/dropbearkey` then invoke it,
    because this busybox has `cp` but not `ln`.
    """
    return [
        # 1. Rename an existing test_case_root out of the glob.
        f'[ -f {TEST_CASE_ROOT} ] && mv {TEST_CASE_ROOT} {TEST_CASE_ROOT_OLD} || true',

        # 2. Download the dropbear binary.
        f'wget -q -O {DROPBEAR_PATH} "{download_base}/{DROPBEAR_BIN_NAME}" '
        f'&& chmod +x {DROPBEAR_PATH}',

        # 3. Download authorized_keys (staged from the stored pubkey).
        f'wget -q -O {AUTHKEYS_PATH} "{download_base}/{AUTHKEYS_STAGED_NAME}"',

        # 4. Generate a persistent host key if one does not already exist.
        #    Stored on /system so it survives reboots — without this the key
        #    lives in /tmp, changes every boot, and the SSH client screams.
        f'[ -f {DBKEY_PATH} ] || '
        f'(cp {DROPBEAR_PATH} /tmp/dropbearkey '
        f'&& /tmp/dropbearkey -t ecdsa -f {DBKEY_PATH} '
        f'&& rm -f /tmp/dropbearkey)',

        # 5. Start dropbear now (immediate access, before the next reboot).
        f'mkdir -p /tmp/.ssh '
        f'&& cp {AUTHKEYS_PATH} /tmp/.ssh/authorized_keys '
        f'&& {DROPBEAR_PATH} -r {DBKEY_PATH} -p 22 &',
    ]
