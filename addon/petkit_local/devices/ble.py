"""BLE accessory devices: the Pura Air spray and the EverSweet fountains.

None of these has a network of its own (`utils/const.py::DEVICE_TYPES_BLE_ONLY`).
Each pairs over BLE to a mains-powered WiFi device — a litter box or a feeder —
which relays for it, so everything here arrives inside that parent's traffic:
K3 readings ride along in its `property/post`, and the fountains' arrive as
`ble_response/post` frames carrying a binary protocol this module decodes.

Pairing is ours to hold because the parent does not discover anything: it asks
the cloud for a list of MACs and scans for exactly those, and no firmware can
report a new one upward.
"""
from __future__ import annotations

import base64
import logging
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from petkit_local.devices.registry import PersistedRegistry
from petkit_local.ha.discovery import EntityDef

log = logging.getLogger(__name__)

# The `type` int the firmware expects in a `dev_ble_device` list entry. K3 is 0
# because it is never listed there at all (it travels inside the parent's
# device_info instead), so its value is only ever a placeholder.
#
# 14 is the only value here anybody has evidence for: it was read off a real W5
# pairing. The other three fountains are MADE UP — they are the same BLE family
# as the W5 (see W5_PROTOCOL), so the same handler is the likeliest answer, but
# "likeliest" is the whole of it. Nothing in the parent's firmware maps a type
# to a model: `pk_schmg_parse_ble_dev_list` (D4SH `ctrl`, `ble_relay_network.c`)
# reads `type` straight out of the JSON, logs `dev[%d],type:%d` and stores it,
# and the parent then scans by MAC. So the value only chooses which protocol it
# speaks once it has connected.
#
# A wrong guess fails silently at both ends, which is why `BLEDevice.scan_type`
# exists: the owner of the hardware can override it without a code change, the
# panel shows the exact entry that will be sent, and whatever value turns out to
# work can be brought back here as a real one.
BLE_TYPE_MAP = {"w5": 14, "k3": 0, "w4": 14, "ctw2": 14, "ctw3": 14}

#: Which of those values is evidence and which is a working assumption.
#: Read by the panel so the guess is visible where somebody can act on it.
BLE_TYPE_CONFIRMED = frozenset({"w5"})

#: The accessory kinds that produce HA entities. Anything else registers fine
#: and then appears nowhere, so callers validate against this rather than
#: letting a typo create an invisible device.
BLE_TYPES = tuple(BLE_TYPE_MAP)

#: The EverSweets that speak the W5 BLE protocol.
#:
#: One pair of GATT UUIDs and one frame parser serve all of them in
#: `phldgmn/ha-petkit-ble`, which advertises for `Petkit_W5`, `Petkit_W5C`,
#: `Petkit_W5N`, `Petkit_W4X`, `Petkit_W4XUVC` and `Petkit_CTW2` — so a frame
#: from any of them decodes with `parse_w5_ble_response` and reads through
#: `W5_ENTITIES`.
#:
#: CTW3 is BLE-only too but is absent from that integration, so nothing says it
#: speaks this protocol; it can be registered, and if its frames turn out to
#: decode here, adding it is one line.
W5_PROTOCOL = frozenset({"w5", "w4", "ctw2"})


def normalize_mac(mac: str) -> str:
    """A MAC in one canonical form: uppercase hex, no separators.

    A BLE MAC reaches us from two directions that do not agree on formatting —
    typed by a person when pairing, and read out of a relayed frame's
    `content.device.mac` — and the only thing that matters is that the two
    match. Comparing canonical forms means `aa:bb:cc:dd:ee:ff`,
    `AA-BB-CC-DD-EE-FF` and `aabbccddeeff` are the same accessory, which is
    what a user means and what avoids a silently dropped frame.

    Returns "" for anything that is not 12 hex digits, so a caller can reject
    it rather than store a MAC no frame will ever match.
    """
    cleaned = "".join(c for c in (mac or "") if c.isalnum()).upper()
    if len(cleaned) != 12 or any(c not in "0123456789ABCDEF" for c in cleaned):
        return ""
    return cleaned


@dataclass
class BLEDevice:
    """A BLE-only accessory, reachable only through the WiFi device it is paired to.

    `link_with` is the `petkit_id` of that parent, and is what every lookup here
    keys on: the accessory has no network identity of its own, so it has no
    credentials, no heartbeat and no liveness of its own either — `state` is
    only ever updated as a side effect of the parent reporting.
    """

    ble_type: str
    petkit_id: int
    serial_number: str = ""
    mac: str = ""
    secret: str = ""
    link_with: int = 0
    interval: int = 240
    #: Overrides `BLE_TYPE_MAP` for this one accessory. 0 means "use the table".
    #:
    #: Exactly one of the table's values is evidence; the rest are a working
    #: assumption (see `BLE_TYPE_MAP`). A wrong one produces a pairing
    #: that fails with no symptom at either end, and the person who can find out
    #: which value is right is the one holding the fountain — not us. So it is
    #: settable per accessory, and persisted with the rest.
    scan_type: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def ble_type_int(self) -> int:
        """This accessory's `type` code for the `dev_ble_device` list."""
        return self.scan_type or BLE_TYPE_MAP.get(self.ble_type, 0)

    @property
    def scan_type_is_guessed(self) -> bool:
        """Whether this accessory is being scanned for on an invented number."""
        return not self.scan_type and self.ble_type not in BLE_TYPE_CONFIRMED \
            and self.ble_type != "k3"

    def to_ble_list_entry(self) -> dict[str, Any]:
        """One entry of the `dev_ble_device` response: what the parent must scan for."""
        return {
            "id": self.petkit_id,
            "secret": self.secret,
            "type": self.ble_type_int,
            "mac": self.mac,
            "interval": self.interval,
        }

    def to_dict(self) -> dict[str, Any]:
        """The persisted form. Unlike `Device`, `state` IS kept.

        An accessory only reports when its parent happens to poll it, so
        dropping the last reading would leave its HA entities unknown for
        minutes after every restart.
        """
        return {
            "ble_type": self.ble_type,
            "petkit_id": self.petkit_id,
            "serial_number": self.serial_number,
            "mac": self.mac,
            "secret": self.secret,
            "link_with": self.link_with,
            "interval": self.interval,
            "scan_type": self.scan_type,
            "state": self.state,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BLEDevice:
        """Rebuild from `to_dict`, ignoring keys this version no longer has."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


K3_ENTITIES = [
    EntityDef(component="sensor", key="k3_liquid", name="K3 Liquid",
              value_path="consumables.liquid", unit="%", icon="mdi:water-percent"),
    EntityDef(component="sensor", key="k3_battery", name="K3 Battery",
              value_path="consumables.battery", unit="%", device_class="battery",
              icon="mdi:battery"),
]

W5_ENTITIES = [
    EntityDef(component="sensor", key="w5_filter", name="W5 Filter",
              value_path="consumables.filterPercentage", unit="%", icon="mdi:filter"),
    EntityDef(component="binary_sensor", key="w5_power", name="W5 Power",
              value_path="states.powerStatus", device_class="power", icon="mdi:power"),
    EntityDef(component="binary_sensor", key="w5_running", name="W5 Running",
              value_path="states.runningStatus", device_class="running",
              icon="mdi:pump"),
    EntityDef(component="binary_sensor", key="w5_water_missing", name="W5 Water Missing",
              value_path="states.warningWaterMissing", device_class="problem",
              icon="mdi:water-off"),
    EntityDef(component="binary_sensor", key="w5_filter_warn", name="W5 Filter Warning",
              value_path="states.warningFilter", device_class="problem",
              icon="mdi:filter-remove"),
]


def get_ble_entities(ble_type: str) -> list[EntityDef]:
    """HA entity definitions for a BLE accessory type; empty for an unknown one."""
    if ble_type == "k3":
        return list(K3_ENTITIES)
    if ble_type in W5_PROTOCOL:
        return list(W5_ENTITIES)
    return []


# W5 (Eversweet) BLE status frame — cmd 230 DATA layout, taken verbatim from
# localkit W5/Parser.php::parseDeviceStatus. Offsets index into the DATA bytes
# (after any FA FC FD framing is stripped).
W5_HEADER = bytes([0xFA, 0xFC, 0xFD])
CMD_DEVICE_STATUS = 230
CMD_DEVICE_STATE = 210

_W5_STATUS_STATE_OFFSETS = {
    "powerStatus": 0,
    "mode": 1,
    "dndState": 2,
    "warningBreakdown": 3,
    "warningWaterMissing": 4,
    "warningFilter": 5,
    "runningStatus": 11,
}
_W5_STATUS_FILTER_OFFSET = 10  # filterPercentage, raw byte 0-100 for cmd 230


def _w5_decode_data(blob: Any) -> bytes | None:
    """Decode one `ble_response` frame's `data` field into raw bytes.

    The field is urlencode(base64(bytes)) — localkit's W5/Device.php reads it as
    `base64_decode(urldecode(payload))`. Returns None for anything that is
    neither that nor the observed hex fallback, so a garbled frame is skipped
    rather than decoded into nonsense.
    """
    if isinstance(blob, (bytes, bytearray)):
        return bytes(blob)
    if not isinstance(blob, str):
        return None
    s = urllib.parse.unquote(blob).strip()
    try:
        return base64.b64decode(s)
    except Exception:
        # Not every payload is base64; the hex form is the observed fallback.
        try:
            return bytes.fromhex(s)
        except ValueError:
            return None


def _w5_unframe(raw: bytes) -> tuple[int | None, bytes]:
    """Split a W5 BLE frame into `(cmd, data_bytes)`.

    Handles both a full `FA FC FD` frame and the pre-split case where `data`
    already IS the DATA payload; in the latter case the command is None and the
    caller falls back to the `cmd` the JSON carried alongside it.
    """
    if len(raw) >= 9 and raw[:3] == W5_HEADER:
        return raw[3], raw[8:-1]
    return None, raw


def _iter_w5_frames(content: Any) -> Iterator[tuple[Any, bytes]]:
    """Yield `(cmd, data_bytes)` for every frame in a `ble_response` content.

    The content shape is `{device: {mac}, payload: [{cmd, data}, ...]}`; a
    single loose blob under `data`/`value`/`frame` is accepted too, because the
    proxying firmware does not always wrap one frame in a list. Undecodable
    entries are skipped silently — a BLE accessory is a best-effort extra, and
    one bad frame must not cost the parent's whole report.
    """
    if not isinstance(content, dict):
        return
    payload = content.get("payload")
    items = payload if isinstance(payload, list) else []
    # tolerate a single loose blob too
    for alt in ("data", "value", "frame"):
        if alt in content and content[alt] is not None:
            items = items + [{"cmd": None, "data": content[alt]}]
    for item in items:
        if not isinstance(item, dict) or "data" not in item:
            continue
        raw = _w5_decode_data(item.get("data"))
        if raw is None:
            continue
        framed_cmd, data = _w5_unframe(raw)
        yield (framed_cmd if framed_cmd is not None else item.get("cmd"), data)


def _decode_w5_status(data: bytes) -> dict[str, dict[str, int]]:
    """Decode a cmd-230 DATA block into `{"states": {...}, "consumables": {...}}`.

    Every field is read only if the blob is long enough to hold it: firmware
    builds differ in how much they send, and a short frame must yield fewer
    fields rather than an IndexError on the state-report path.
    """
    states: dict[str, int] = {}
    consumables: dict[str, int] = {}
    for name, off in _W5_STATUS_STATE_OFFSETS.items():
        if off < len(data):
            states[name] = data[off]
    if _W5_STATUS_FILTER_OFFSET < len(data):
        consumables["filterPercentage"] = data[_W5_STATUS_FILTER_OFFSET]
    if len(data) >= 10:
        states["pumpRuntime"] = int.from_bytes(bytes(data[6:10]), "big")
    return {"states": states, "consumables": consumables}


def parse_w5_ble_response(content: Any) -> dict[str, dict[str, Any]]:
    """Decode a W5 `ble_response` into the state a `W5_ENTITIES` value_path reads.

    Accepts a structured firmware payload (fields already named) OR the real
    binary frame(s), and merges both. Decoded frames are applied last and
    therefore win on any field both forms carry.

    Returns:
        `{"states": {...}, "consumables": {...}}`, matching the `value_path`
        prefixes in `W5_ENTITIES`. A section with nothing in it is DROPPED, so
        an empty dict means nothing was decodable and the caller should leave
        the previous state alone instead of publishing blanks.
    """
    result: dict[str, dict[str, Any]] = {"states": {}, "consumables": {}}

    if isinstance(content, dict):
        for section in ("states", "consumables"):
            if isinstance(content.get(section), dict):
                result[section].update(content[section])
        for key in ("powerStatus", "runningStatus", "warningWaterMissing", "warningFilter", "mode"):
            if key in content:
                result["states"][key] = content[key]
        if "filterPercentage" in content:
            result["consumables"]["filterPercentage"] = content["filterPercentage"]

    for cmd, data in _iter_w5_frames(content):
        if cmd in (CMD_DEVICE_STATUS, CMD_DEVICE_STATE) and data:
            dec = _decode_w5_status(data)
            result["states"].update(dec["states"])
            result["consumables"].update(dec["consumables"])

    return {k: v for k, v in result.items() if v}


class BLERegistry(PersistedRegistry):
    """Every BLE accessory, keyed by its PetKit id, persisted to ble_devices.json.

    Separate from `DeviceRegistry` because the two have different lifecycles: an
    accessory is created from whatever its parent reports, has no credentials of
    its own, and is looked up by parent (`link_with`) far more often than by id.
    """

    _label = "BLE registry"

    def __init__(self, persist_path: str | Path | None = None, *,
                 flush_interval: float | None = None) -> None:
        """See `PersistedRegistry.__init__` for the arguments."""
        self._devices: dict[int, BLEDevice] = {}
        super().__init__(persist_path, flush_interval=flush_interval)

    def get(self, petkit_id: int) -> BLEDevice | None:
        """The accessory with this id, or None."""
        return self._devices.get(petkit_id)

    def get_by_mac(self, mac: str) -> BLEDevice | None:
        """The accessory with this BLE MAC, or None.

        Compared in canonical form (see `normalize_mac`) rather than verbatim.
        This used to be an exact string match, which made the single most
        likely pairing mistake invisible: a MAC typed as `aa:bb:...` never
        matches a frame carrying `AA-BB-...`, and the frame is then dropped by
        a `log.debug` in `mqtt/bridge.py` with nothing to show for it.
        """
        wanted = normalize_mac(mac)
        if not wanted:
            return None
        for d in self._devices.values():
            if normalize_mac(d.mac) == wanted:
                return d
        return None

    def remove(self, petkit_id: int) -> bool:
        """Unpair an accessory. Returns whether it existed.

        The parent stops being told to scan for it on its next
        `dev_ble_device`, which is the whole of "unpairing" from the device's
        point of view — there is no command that revokes one.
        """
        if petkit_id not in self._devices:
            return False
        dev = self._devices.pop(petkit_id)
        log.info("BLE device removed: %s id=%d mac=%s", dev.ble_type, petkit_id, dev.mac)
        self.save()
        return True

    def get_linked(self, parent_id: int) -> list[BLEDevice]:
        """Every accessory paired to this WiFi device."""
        return [d for d in self._devices.values() if d.link_with == parent_id]

    def get_linked_k3(self, parent_id: int) -> BLEDevice | None:
        """This device's K3 purifier, if it has one.

        Its own lookup because K3 is the one accessory that is NOT served
        through `dev_ble_device`: it is embedded in the parent's device_info
        (`withK3`/`k3Device`) instead. Only the first is returned — the firmware
        has one K3 slot.
        """
        for d in self._devices.values():
            if d.link_with == parent_id and d.ble_type == "k3":
                return d
        return None

    def register(self, **kwargs: Any) -> BLEDevice:
        """Create the accessory, or update the one already stored under this id.

        On update, only TRUTHY values overwrite: the parent re-reports the whole
        accessory on every poll and pads fields it did not read this time with
        empty values, which must not erase what we already know.

        Args:
            kwargs: `BLEDevice` field values; `petkit_id` is the key and
                defaults to 0 if absent.
        """
        pid = kwargs.get("petkit_id", 0)
        if pid in self._devices:
            dev = self._devices[pid]
            changed = False
            for k, v in kwargs.items():
                if v and hasattr(dev, k) and getattr(dev, k) != v:
                    setattr(dev, k, v)
                    changed = True
            if changed:
                # Same bug as DeviceRegistry.get_or_create had: the update was
                # only ever written by some later, unrelated save().
                self.mark_dirty()
            return dev
        dev = BLEDevice(**kwargs)
        self._devices[pid] = dev
        log.info("BLE device registered: %s id=%d mac=%s linked=%d",
                 dev.ble_type, pid, dev.mac, dev.link_with)
        self.save()
        return dev

    def all(self) -> list[BLEDevice]:
        """A snapshot list of every accessory, safe to iterate while mutating."""
        return list(self._devices.values())

    def non_k3_for_parent(self, parent_id: int) -> list[BLEDevice]:
        """The accessories that belong in this device's `dev_ble_device` list.

        K3 is excluded on purpose: listing it there as well as in the parent's
        device_info makes the firmware treat it as a second, unpaired device.
        """
        return [d for d in self._devices.values()
                if d.link_with == parent_id and d.ble_type != "k3"]

    def _serialize(self) -> dict[str, Any]:
        """`{"<petkit_id>": BLEDevice.to_dict()}` — the shape of ble_devices.json."""
        return {str(pid): d.to_dict() for pid, d in self._devices.items()}

    def _restore(self, data: Any) -> None:
        """Load `_serialize`'s shape, skipping entries that cannot be read."""
        if not isinstance(data, dict):
            log.error("BLE registry at %s is not a JSON object - starting empty",
                      self._persist_path)
            return
        for key, d_data in data.items():
            try:
                dev = BLEDevice.from_dict(d_data)
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                log.warning("Skipping unreadable BLE device entry %r: %s", key, e)
                continue
            self._devices[dev.petkit_id] = dev
        log.info("BLE registry loaded: %d devices", len(self._devices))
