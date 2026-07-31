# Shipped binaries

## `dropbear-mipsel`

The SSH daemon the `ssh` patcher installs onto a rooted Ingenic device
(`petkit_local/patchers/ssh.py`). It is served to the device over the patcher
download path and written to `/system/dropbear`.

| | |
|---|---|
| Upstream | [mkj/dropbear](https://github.com/mkj/dropbear) |
| Licence | MIT-style, plus PuTTY-derived and LibTomCrypt/LibTomMath components — see [`LICENSE.dropbear`](LICENSE.dropbear) |
| Target | `ELF 32-bit LSB pie executable, MIPS, MIPS32 rel2, statically linked` |
| Size | 156,208 bytes |
| SHA-256 | `726110926001c3942b6dfd8d980c6eed7675c5b6bb8e376a11a073ff47232431` |
| Compression | UPX 4.24 |

**The upstream version is not recorded and cannot be recovered from the binary:**
UPX packing leaves only its own banner in the string table, so nothing here can
tell you which Dropbear release this is. That is a gap — if you rebuild it,
replace this file with the real version and the build recipe. A reproducible
build (musl toolchain, `mips-linux-muslsf`, static, then `upx --best`) would be
strictly better than a binary of unknown provenance being installed as a
device's SSH daemon.

`patchers/verify.py::assert_mips_elf` is run against this file before it is
staged, so a corrupted or substituted copy is refused rather than installed.
The SHA-256 above is the check a cautious user can make by hand.

Dropbear's licence requires its copyright notice to accompany binary
redistributions, which is what `LICENSE.dropbear` is doing here. It is
unaffected by this project's own GPL-3.0 licence.
