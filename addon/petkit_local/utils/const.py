"""Device codename tables: which models exist, what they are and what they can do.

A device identifies itself only by a lowercase codename ("t5", "d4h", ...) — the
firmware never states its category, whether it has a camera or what its
commercial name is. Every such fact is answered from the sets below, so a new
model is supported by adding its codename here rather than by touching the
payload builders, entity tables and parsers that ask these questions.

The sets are the raw data; `devices/base.py` exposes them as the `Device.is_*`
predicates the rest of the code actually reads.
"""

DEVICE_TYPES_LITTER = {"t3", "t4", "t5", "t6", "t7"}
DEVICE_TYPES_FEEDER = {"feeder", "feedermini", "d3", "d4", "d4s", "d4h", "d4sh"}
DEVICE_TYPES_WATER_FOUNTAIN = {"w4", "w5", "ctw2", "ctw3", "w7h"}
DEVICE_TYPES_PURIFIER = {"k2", "k3"}
DEVICE_TYPES_ALL = DEVICE_TYPES_LITTER | DEVICE_TYPES_FEEDER | DEVICE_TYPES_WATER_FOUNTAIN | DEVICE_TYPES_PURIFIER

DEVICE_TYPES_CAMERA = {"t5", "t6", "t7", "d4h", "d4sh", "w7h"}
# Embedded-Linux models, as opposed to the ESP32 ones. Same membership as
# DEVICE_TYPES_CAMERA today, but a different question: "camera" decides media/STS
# behaviour, "next gen" decides how the device talks to us (HTTPS, MQTT-capable
# ctrl binary, BLE provisioning).
DEVICE_TYPES_NEXT_GEN = {"t5", "t6", "t7", "d4h", "d4sh", "w7h"}

# The CPU behind that Linux userland, which is NOT the same across the family.
# The T-series and the camera feeders are Ingenic MIPS; W7H is ARM — its app
# partition (W7-262863, extracted) holds 14 binaries, every one of them
# `ELF 32-bit LSB executable, ARM, EABI5, /lib/ld-linux-armhf.so.3`, with `ctrl`
# an ET_EXEC loading at 0x10000 rather than MIPS's 0x400000. Do not take this
# from the firmware's uImage header: it says "Linux/MIPS" on every W7H part.
#
# Only the patchers that rewrite machine code or install a prebuilt binary care
# — see `PATCHER_INFO["arch"]`. The ones that move files around do not, and a
# device is not disqualified from the whole tab by its CPU.
DEVICE_CPU_ARCH = {
    "t5": "mips", "t6": "mips", "t7": "mips", "d4h": "mips", "d4sh": "mips",
    "w7h": "arm",
}

# Devices whose NPU runs on-device facial recognition (dev_discern_pic /
# dev_discern_config). This is only a SEED: `Device.supports_ai` also returns
# True once a device has actually asked for those endpoints, because a codename
# cannot answer the question on its own —
#
#   * PetKit's own "Pet Identification" screen lists three litter boxes (Purobot
#     Max Pro 2, Purobot Ultra, Purobot Max Pro), two feeders (YumShare Solo 2,
#     Dual-Hopper 2) and one fountain (EverSweet Ultra AI). `w7h` is here for
#     that last one.
#   * It also says the NON-"2" YumShare Solo and Dual-Hopper do NOT do
#     recognition — and both generations share one codename (`d4h` / `d4sh`;
#     localkit's own gen-2 branch handles the newer one as plain `d4sh` and
#     introduces no new name). So no list keyed on codename can be right for the
#     feeders, and they are deliberately absent: a gen-2 earns `supports_ai` by
#     polling, a gen-1 never does.
#   * "Purobot Max Pro" (without the 2) maps to no codename in this repo or in
#     localkit. Same resolution — it will identify itself by asking.
#   * `t7` is ours but is NOT on PetKit's list. Left in rather than removed:
#     nothing suggests it lacks the NPU, and dropping it would take the feature
#     away from anyone using one.
DEVICE_TYPES_AI = {"t5", "t6", "t7", "w7h"}

# Commercial product names per device codename. Verified against pypetkitapi
# doc/API.md, except T5/T6 which were corrected against a real device (T5 is a
# Purobot Max Pro 2). A codename that is not listed here is still supported —
# see `device_display_name` for what is shown for it.
#
# Two entries are known to be imprecise, and are left as they are because the
# alternative is a guess:
#   * `d4h`/`d4sh` — PetKit sells a "2" of each (YumShare Solo 2, Dual-Hopper 2)
#     that shares the codename, so one name here covers two products that differ
#     in whether they can recognise a pet at all. See DEVICE_TYPES_AI above.
#   * `t7` — localkit calls it "Purobot Crystal"; pypetkitapi says "Crystal Duo".
#     Unresolved without hardware.
#   * `k2` — the generation before the K3, named by analogy. PetKit's own listing
#     for it could not be found.
#
# `k2`/`k3` were "Air Purifier K2"/"Air Purifier K3" here, which is wrong and
# actively misleading: PetKit also sells real air purifiers. These are the Pura
# Air smart spray, a Bluetooth deodoriser that mounts inside a litter box (or on
# a wall) and sprays after a visit. Several retailers do list the K3 as an "air
# purifier", which is presumably where the name came from.
DEVICE_NAMES = {
    "feeder": "Feeder",
    "feedermini": "Feeder Mini",
    "d3": "Feeder D3",
    "d4": "Feeder D4",
    "d4s": "Feeder D4s",
    "d4h": "YumShare Solo",
    "d4sh": "YumShare Dual-Hopper",
    "t3": "Pura X",
    "t4": "Pura Max",
    "t5": "Purobot Max Pro 2",
    "t6": "Purobot Ultra",
    "t7": "Purobot Crystal Duo",
    "w4": "EverSweet",
    "w5": "EverSweet 3 Pro",
    "ctw2": "EverSweet Solo 2",
    "ctw3": "EverSweet Max Cordless",
    "w7h": "EverSweet Ultra AI",
    "k2": "Pura Air",
    "k3": "Pura Air K3",
}

# The object-key prefix our own `dev_upload_log_token` hands out as `pathPrefix`,
# and the one key shape `http/bucket.py` stores OUTSIDE the media tree. It lives
# here because the two ends must agree exactly and they sit in different layers:
# `devices/base.py::Device.to_log_upload_token` mints it, `http/bucket.py::_route`
# consumes it. It must never collide with a device codename, because a media key
# begins with one (`{device_type}/{petkit_id}/{capability}`) — asserted in tests.
DEVICE_LOG_KEY_PREFIX = "devlog"


def device_display_name(code: str) -> str:
    """The commercial product name for a device codename.

    An unlisted codename yields "Unknown" rather than the code itself: such a
    device is still fully supported (it registers, connects and publishes
    entities), and the panel shows the raw codename next to this name anyway, so
    echoing the code here would only duplicate it. An empty code yields an empty
    string, because there is nothing to name.
    """
    if not code:
        return ""
    return DEVICE_NAMES.get(code.lower(), "Unknown")
