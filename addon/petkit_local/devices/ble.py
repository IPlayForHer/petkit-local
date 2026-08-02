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

from petkit_local.devices.base import Refused
from petkit_local.devices.registry import PersistedRegistry
from petkit_local.ha.discovery import EntityDef

log = logging.getLogger(__name__)

# The `type` int the firmware expects in a `dev_ble_device` list entry. K3 is 0
# because it is never listed there at all (it travels inside the parent's
# device_info instead), so its value is only ever a placeholder.
#
# Two of these are evidence. 14 was read off a real W5 pairing; 24 came from a
# CTW3 owner who captured their own `dev_ble_device` list (issue #4).
#
# `w4` and `ctw2` are still assumptions, and the assumption is that a model
# shares its number with its own product line rather than with the other one:
# `ctw2` sits with `ctw3` (both cordless CT-series EverSweets), `w4` with `w5`.
# Nothing in the parent's firmware settles it — `pk_schmg_parse_ble_dev_list`
# (D4SH `ctrl`, `ble_relay_network.c`) reads `type` straight out of the JSON,
# logs `dev[%d],type:%d` and stores it, and the parent then scans by MAC. The
# value only picks which protocol it speaks once connected.
#
# A wrong guess fails silently at both ends, which is why `BLEDevice.scan_type`
# exists: the owner of the hardware can override it without a code change, the
# panel shows the exact entry that will be sent, and whatever value turns out to
# work can be brought back here as a real one — which is exactly how 24 arrived.
BLE_TYPE_MAP = {"w5": 14, "w4": 14, "ctw3": 24, "ctw2": 24, "k3": 0}

#: Which of those values is evidence and which is a working assumption.
#: Read by the panel so the guess is visible where somebody can act on it.
BLE_TYPE_CONFIRMED = frozenset({"w5", "ctw3"})

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
#: CTW3 is absent from that integration and does NOT belong here — its status
#: block is a different length with a different layout, so reading it with
#: these offsets would produce confident nonsense. It has its own decoder
#: further down.
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
    only ever updated as a side effect of the parent reporting. `last_seen` is
    the one exception and is about the accessory itself: when it last said
    anything at all, through whoever relayed it.
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
    #: Two of the table's values are evidence; the rest are a working
    #: assumption (see `BLE_TYPE_MAP`). A wrong one produces a pairing
    #: that fails with no symptom at either end, and the person who can find out
    #: which value is right is the one holding the fountain — not us. So it is
    #: settable per accessory, and persisted with the rest.
    scan_type: int = 0
    #: When a frame from this accessory last decoded. Not a network liveness —
    #: it has no network — but the answer to the only question worth asking
    #: about a relayed device: has it ever spoken, and how long ago. With a
    #: `scan_type` that may be a guess, "never" is the symptom to look for.
    last_seen: float = 0.0
    state: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def wire_mac(self) -> str:
        """The MAC as the cloud puts it on the wire: lowercase, no separators.

        Stored uppercase because that is the canonical form for COMPARING one
        (`normalize_mac`), and a frame's MAC reaches us in whatever shape the
        firmware felt like. Outbound is the other question, and the answer is
        the real cloud's: every captured `dev_ble_device` entry and every
        `connect` carries lowercase. Nothing says the parent compares case
        sensitively — but nothing says it does not, and matching the cloud
        costs nothing.
        """
        return self.mac.lower()

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
            "mac": self.wire_mac,
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
            "last_seen": self.last_seen,
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


#: CTW3 (EverSweet Max Cordless). Named after the fields the decoder produces,
#: which are PetKit's own — see the block above `_decode_ctw3_status`.
#:
#: `electricStatus` is a plain sensor, not a binary one: 2 has been observed and
#: nobody knows what 3 would mean. `detectStatus` is the opposite case — the
#: value varies (0x02 seen) but the question it answers is yes/no, so it is a
#: binary sensor with a non-zero test rather than a raw byte.
CTW3_ENTITIES = [
    EntityDef(component="sensor", key="ctw3_filter", name="Filter",
              value_path="consumables.filterPercent", unit="%", icon="mdi:filter"),
    EntityDef(component="sensor", key="ctw3_battery", name="Battery",
              value_path="states.batteryPercent", unit="%", device_class="battery",
              icon="mdi:battery"),
    # Writable. A switch shows the state AND sets it, so these replace the
    # binary sensors they would otherwise duplicate; `ble_command_for` maps the
    # key to the frame.
    EntityDef(component="switch", key="ctw3_power", name="Power",
              value_path="states.powerStatus", icon="mdi:power"),
    EntityDef(component="switch", key="ctw3_working", name="Working",
              value_path="states.suspendStatus", icon="mdi:play-pause"),
    EntityDef(component="select", key="ctw3_mode", name="Flow Mode",
              value_path="states.mode", icon="mdi:water-pump",
              options=["continuous", "intermittent"], option_values=[1, 2]),
    EntityDef(component="switch", key="ctw3_light", name="Light",
              value_path="states.lightSwitch", icon="mdi:lightbulb"),
    EntityDef(component="select", key="ctw3_brightness", name="Brightness",
              value_path="states.brightness", icon="mdi:brightness-6",
              options=["low", "medium", "high"], option_values=[1, 2, 3]),
    EntityDef(component="switch", key="ctw3_dnd", name="Do Not Disturb",
              value_path="states.noDisturbingSwitch", icon="mdi:sleep"),
    EntityDef(component="number", key="ctw3_energy_interval", name="Battery Mode Interval",
              value_path="states.energyInterval", unit="s", icon="mdi:timer-outline",
              min_value=15, max_value=3600, step=15, entity_category="config"),
    EntityDef(component="number", key="ctw3_sleep_time", name="Sleep Time",
              value_path="states.sleepTime", unit="s", icon="mdi:timer-sand",
              min_value=60, max_value=7200, step=60, entity_category="config"),
    # Read-only: the pump is not something you switch, it is what the fountain
    # is doing right now.
    EntityDef(component="binary_sensor", key="ctw3_running", name="Pump Running",
              value_path="states.runStatus", device_class="running", icon="mdi:pump"),
    EntityDef(component="binary_sensor", key="ctw3_drinking", name="Drinking",
              value_path="states.detectStatus", icon="mdi:cup-water"),
    EntityDef(component="binary_sensor", key="ctw3_water_lack", name="Water Low",
              value_path="states.lackWarning", device_class="problem",
              icon="mdi:water-off"),
    EntityDef(component="binary_sensor", key="ctw3_filter_warn", name="Filter Warning",
              value_path="states.filterWarning", device_class="problem",
              icon="mdi:filter-remove"),
    EntityDef(component="binary_sensor", key="ctw3_breakdown", name="Breakdown",
              value_path="states.breakdownWarning", device_class="problem",
              icon="mdi:alert"),
    EntityDef(component="binary_sensor", key="ctw3_low_battery", name="Low Battery",
              value_path="states.lowBattery", device_class="battery",
              icon="mdi:battery-alert"),
    EntityDef(component="sensor", key="ctw3_power_source", name="Power Source",
              value_path="states.electricStatus", icon="mdi:power-plug",
              entity_category="diagnostic"),
    # `duration` rather than a bare second count: 1056887 says nothing, and
    # both the panel and HA render the class as something readable.
    EntityDef(component="sensor", key="ctw3_pump_runtime", name="Pump Runtime",
              value_path="states.waterPumpRunTime", unit="s",
              device_class="duration", icon="mdi:timer-outline",
              entity_category="diagnostic"),
    EntityDef(component="sensor", key="ctw3_pump_today", name="Pump Runtime Today",
              value_path="states.todayPumpRunTime", unit="s",
              device_class="duration", icon="mdi:timer-outline",
              entity_category="diagnostic"),
    EntityDef(component="sensor", key="ctw3_battery_voltage", name="Battery Voltage",
              value_path="states.batteryVoltage", unit="mV",
              device_class="voltage", entity_category="diagnostic"),
    EntityDef(component="sensor", key="ctw3_supply_voltage", name="Supply Voltage",
              value_path="states.supplyVoltage", unit="mV",
              device_class="voltage", entity_category="diagnostic"),
]


def get_ble_entities(ble_type: str) -> list[EntityDef]:
    """HA entity definitions for a BLE accessory type; empty for an unknown one."""
    if ble_type == "k3":
        return list(K3_ENTITIES)
    if ble_type == "ctw3":
        return list(CTW3_ENTITIES)
    if ble_type in W5_PROTOCOL:
        return list(W5_ENTITIES)
    return []


# The framing both fountain families share: `FA FC FD | opcode | 01 | seq |
# len | payload | FB`, carried as urlencode(base64(...)) inside a relayed
# `ble_response`. Only the DATA layout inside it differs per model, so the
# decode/unframe helpers below are shared and the offset tables are not.
BLE_FRAME_HEADER = bytes([0xFA, 0xFC, 0xFD])
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


def _ble_decode_data(blob: Any) -> bytes | None:
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


def _ble_unframe(raw: bytes) -> tuple[int | None, bytes]:
    """Split a W5 BLE frame into `(cmd, data_bytes)`.

    Handles both a full `FA FC FD` frame and the pre-split case where `data`
    already IS the DATA payload; in the latter case the command is None and the
    caller falls back to the `cmd` the JSON carried alongside it.
    """
    if len(raw) >= 9 and raw[:3] == BLE_FRAME_HEADER:
        return raw[3], raw[8:-1]
    return None, raw


def _iter_ble_frames(content: Any) -> Iterator[tuple[Any, bytes]]:
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
        raw = _ble_decode_data(item.get("data"))
        if raw is None:
            continue
        framed_cmd, data = _ble_unframe(raw)
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

    for cmd, data in _iter_ble_frames(content):
        if cmd in (CMD_DEVICE_STATUS, CMD_DEVICE_STATE) and data:
            dec = _decode_w5_status(data)
            result["states"].update(dec["states"])
            result["consumables"].update(dec["consumables"])

    return {k: v for k, v in result.items() if v}


# --- CTW3 (EverSweet Max Cordless) ------------------------------------------
#
# A different DATA layout in the same framing, contributed with the hardware in
# hand (issue #4, firmware 111). Do NOT read it with the W5 offsets: the blocks
# are 30 bytes (cmd 210) or 42 (cmd 230, with a 12-byte config tail), against
# the W5's much shorter one, and the multi-byte values here are big-endian.
#
# The names are PetKit's own, taken from the account API's `kv` for this model
# rather than translated into the W5's vocabulary — `runStatus` not
# `runningStatus`, `lackWarning` not `warningWaterMissing`. Where the two
# families disagree, matching the cloud is what lets a report be compared with
# what the PetKit app shows.

_CTW3_MIN_STATUS_LEN = 30

#: Single-byte fields, offset into the DATA block.
_CTW3_BYTE_FIELDS = {
    "powerStatus": 0,
    # Inverted against the English: 0 is paused/sleeping, 1 is working.
    "suspendStatus": 1,
    "mode": 2,                  # 1 continuous, 2 intermittent
    # NOT a boolean. 2 has been seen, on the AC/charging path.
    "electricStatus": 3,
    "noDisturbingSwitch": 4,
    "breakdownWarning": 5,
    "lackWarning": 6,
    "lowBattery": 7,
    "filterWarning": 8,
    "filterPercent": 13,
    "runStatus": 14,
    # 0 is nobody; anything else (0x02 observed) is a pet at the bowl.
    "detectStatus": 19,
    "batteryPercent": 24,
}

#: Multi-byte fields as `(offset, width)`, big-endian.
_CTW3_INT_FIELDS = {
    "waterPumpRunTime": (9, 4),
    "todayPumpRunTime": (15, 4),
    "supplyVoltage": (20, 2),
    "batteryVoltage": (22, 2),
}

#: Where the 12-byte config tail starts in a cmd-230 block. Same layout as the
#: payload of a cmd-221 write, which is what makes a read-modify-write of one
#: setting possible at all.
CTW3_CONFIG_OFFSET = 30
CTW3_CONFIG_LEN = 12


def decode_ctw3_config(tail: bytes) -> dict[str, int]:
    """The 12-byte config blob, as named fields.

    Shared by the status tail and by whatever we are about to write, so a
    single-setting change can be built from the last reading rather than from
    zeros.
    """
    if len(tail) < CTW3_CONFIG_LEN:
        return {}
    return {
        "energyInterval": int.from_bytes(tail[2:4], "big"),
        "sleepTime": int.from_bytes(tail[4:6], "big"),
        "lightSwitch": tail[6],
        "brightness": tail[7],          # 1 low, 2 medium, 3 high
        "noDisturbingSwitch": tail[8],
    }


def _decode_ctw3_status(data: bytes) -> dict[str, dict[str, int]]:
    """Decode a CTW3 cmd-210/230 DATA block.

    Refuses anything shorter than the 30 bytes the short form is defined to be,
    rather than emitting the handful of fields that happen to fit. The W5
    decoder does the permissive thing — every field if its offset is in range —
    which turns a one-byte frame into a confident `powerStatus`. Here the block
    length is known, so a short one is a broken frame and is dropped.
    """
    if len(data) < _CTW3_MIN_STATUS_LEN:
        log.warning("CTW3 status frame is %d bytes, expected at least %d — dropped",
                    len(data), _CTW3_MIN_STATUS_LEN)
        return {"states": {}, "consumables": {}}

    states: dict[str, int] = {name: data[off] for name, off in _CTW3_BYTE_FIELDS.items()}
    for name, (off, width) in _CTW3_INT_FIELDS.items():
        states[name] = int.from_bytes(data[off:off + width], "big")

    # `filterPercent` is the one field a human treats as a consumable rather
    # than a state, and the entity reads it from there.
    consumables = {"filterPercent": states.pop("filterPercent")}

    if len(data) >= CTW3_CONFIG_OFFSET + CTW3_CONFIG_LEN:
        tail = data[CTW3_CONFIG_OFFSET:CTW3_CONFIG_OFFSET + CTW3_CONFIG_LEN]
        # `noDisturbingSwitch` appears in both halves; the tail is the one the
        # config write round-trips, so let it win.
        states.update(decode_ctw3_config(tail))

    return {"states": states, "consumables": consumables}


def parse_ctw3_ble_response(content: Any) -> dict[str, dict[str, Any]]:
    """Decode a CTW3 `ble_response` into the state its entities read.

    Same contract as `parse_w5_ble_response`: an empty dict means nothing was
    decodable, and the caller leaves the previous state alone.
    """
    result: dict[str, dict[str, Any]] = {"states": {}, "consumables": {}}
    for cmd, data in _iter_ble_frames(content):
        if cmd in (CMD_DEVICE_STATUS, CMD_DEVICE_STATE) and data:
            dec = _decode_ctw3_status(data)
            result["states"].update(dec["states"])
            result["consumables"].update(dec["consumables"])
    return {k: v for k, v in result.items() if v}


# --- writing to a CTW3 -------------------------------------------------------
#
# The other direction of the same relay: we publish `thing/service/ble` to the
# PARENT, which forwards the bytes over its open BLE session. Nothing here had
# a write path at all before — an accessory was read-only.
#
# `cmd` in the MQTT envelope and `opcode` inside the frame are two different
# numbers for the same operation, which is the trap: 220 carries `DC`, 221
# carries `DD`. Both are sent.

CTW3_CMD_SET_POWER = 220        # opcode DC — power / suspend / mode
CTW3_CMD_SET_CONFIG = 221       # opcode DD — the 12-byte config blob
CTW3_CMD_SET_LIGHT_SCHEDULE = 225   # opcode E1
CTW3_CMD_SET_DND_SCHEDULE = 226     # opcode E2

_CTW3_OPCODES = {
    CTW3_CMD_SET_POWER: 0xDC,
    CTW3_CMD_SET_CONFIG: 0xDD,
    CTW3_CMD_SET_LIGHT_SCHEDULE: 0xE1,
    CTW3_CMD_SET_DND_SCHEDULE: 0xE2,
}

BLE_FRAME_TRAILER = 0xFB


def build_ble_frame(opcode: int, seq: int, payload: bytes) -> str:
    """One outbound BLE frame, encoded the way `thing/service/ble` carries it.

    `FA FC FD | opcode | 01 | seq | len | payload | FB`, then base64, then
    urlencode — the exact inverse of what `_ble_decode_data` and `_ble_unframe`
    undo on the way in.

    `seq` wraps at a byte. Nothing has been observed rejecting a repeat, but it
    is a sequence number and sending a constant would be the kind of detail
    that works until it does not.
    """
    body = bytes([*BLE_FRAME_HEADER, opcode & 0xFF, 0x01, seq & 0xFF,
                  len(payload), *payload, BLE_FRAME_TRAILER])
    return urllib.parse.quote(base64.b64encode(body).decode())


def ctw3_power_payload(power: int, suspend: int, mode: int) -> bytes:
    """cmd 220 — the three settings that share one frame.

    All three travel together, so changing one means restating the other two.
    `suspend` is 1 for WORKING and 0 for paused, inverted against its name.
    """
    return bytes([0x00, power & 0xFF, suspend & 0xFF, mode & 0xFF])


def ctw3_config_payload(state: dict[str, Any]) -> bytes | None:
    """cmd 221 — the 12-byte config blob, rebuilt from the last status.

    The device takes the blob whole, so a single-setting change has to restate
    everything else. `state` is the accessory's decoded `states`, which carries
    those values only because a cmd-230 status includes the same blob as its
    tail.

    Returns None when the accessory has never reported a long status. Writing
    zeros instead would silently reset the light, the brightness and both
    intervals — a settings write is not worth guessing at.
    """
    needed = ("energyInterval", "sleepTime", "lightSwitch", "brightness",
              "noDisturbingSwitch")
    if any(k not in state for k in needed):
        return None
    return bytes([
        0x03, 0x03,
        *int(state["energyInterval"]).to_bytes(2, "big"),
        *int(state["sleepTime"]).to_bytes(2, "big"),
        int(state["lightSwitch"]) & 0xFF,
        int(state["brightness"]) & 0xFF,
        int(state["noDisturbingSwitch"]) & 0xFF,
        0x00, 0x01, 0x00,
    ])


def ble_command_frame(cmd: int, seq: int, payload: bytes) -> str | None:
    """The encoded frame for one MQTT `cmd`, or None if we know no opcode."""
    opcode = _CTW3_OPCODES.get(cmd)
    if opcode is None:
        return None
    return build_ble_frame(opcode, seq, payload)


#: Entity key -> the field of `states` it sets. Both frames restate every field
#: they carry, so which frame a key belongs to decides what else must be read
#: back out of the last status.
_CTW3_POWER_FIELDS = {
    "ctw3_power": "powerStatus",
    "ctw3_working": "suspendStatus",
    "ctw3_mode": "mode",
}
_CTW3_CONFIG_FIELDS = {
    "ctw3_light": "lightSwitch",
    "ctw3_brightness": "brightness",
    "ctw3_dnd": "noDisturbingSwitch",
    "ctw3_energy_interval": "energyInterval",
    "ctw3_sleep_time": "sleepTime",
}

CTW3_WRITABLE = frozenset(_CTW3_POWER_FIELDS) | frozenset(_CTW3_CONFIG_FIELDS)


def ctw3_command_for(ble_dev: BLEDevice, key: str, value: int) -> tuple[int, bytes]:
    """The `(cmd, payload)` that sets one CTW3 entity to `value`.

    Neither frame carries a single field: 220 restates power, suspend and mode
    together, and 221 restates the whole config blob. So both are built from
    the accessory's last decoded status with one value replaced.

    Raises:
        Refused: when the accessory has not reported the fields the frame needs.
            An accessory that has never sent a long status cannot have its
            config written without inventing the rest of the blob, and inventing
            it would switch the light off and reset both intervals as a side
            effect of changing brightness.
    """
    states = dict(ble_dev.state.get("states") or {})
    if key in _CTW3_POWER_FIELDS:
        states[_CTW3_POWER_FIELDS[key]] = value
        missing = [f for f in ("powerStatus", "suspendStatus", "mode") if f not in states]
        if missing:
            raise Refused(f"no reading yet for {', '.join(missing)}")
        return CTW3_CMD_SET_POWER, ctw3_power_payload(
            states["powerStatus"], states["suspendStatus"], states["mode"])

    if key in _CTW3_CONFIG_FIELDS:
        states[_CTW3_CONFIG_FIELDS[key]] = value
        payload = ctw3_config_payload(states)
        if payload is None:
            raise Refused("no full status reported yet — the config blob is "
                          "written whole, and the rest of it is not known")
        return CTW3_CMD_SET_CONFIG, payload

    raise Refused(f"{key} is not a writable CTW3 field")


#: Which decoder an accessory's frames go through.
BLE_PARSERS = {
    "ctw3": parse_ctw3_ble_response,
}


def parser_for(ble_type: str):
    """The frame decoder for an accessory kind, or None if it has none."""
    if ble_type in W5_PROTOCOL:
        return parse_w5_ble_response
    return BLE_PARSERS.get(ble_type)


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
