"""Normalize a `dev_state_report` body into the flat camelCase state HA reads.

Devices do not agree with each other, or with themselves. The same value
arrives as `sandPercent` on one model and `litter.percent` on another, as
`workState` (an object) here and `work_state` (a scalar) there, and a field may
be absent entirely on a firmware that predates it. Entity definitions cannot
carry one `value_path` per spelling, so every spelling is collapsed here into
one flat key per value, and `state.<key>` is then the only thing the HA
templates, the panel and the MQTT property path all read.

Everything in this module is best-effort by design: an unrecognised device type
passes its body through untouched, an unexpected shape at any level is skipped
rather than raised on. A state report that fails would cost the device its whole
update, so a partial state always beats an exception.
"""
from __future__ import annotations

import json
import math
import re
import time
from typing import TYPE_CHECKING, Any

from petkit_local.utils.coerce import to_float
from petkit_local.utils.dicts import dig

if TYPE_CHECKING:  # import-cycle-free: base.py imports SPRAY_TOTAL_DAYS from here
    from petkit_local.devices.base import Device

# A litter box has two independent deodorant consumables, and the countdown for
# both is OURS to compute: the device reports only the reset timestamps
# (`sprayResetTime`, `liquidReset`) and never a remaining count.
# `deodorantLeftDays` and `sprayLeftDays` appear in zero of 685 captured state
# reports and nowhere in the `ctrl` or `ble` binaries — they are the cloud's
# vocabulary, and here the cloud is us.
#
#   N60  the ACTIVE one: the box's own sprayer, which fires for ~2 minutes after
#        a visit. Manufacturer's replacement interval is 45 days.
#   N50  the PASSIVE one: sits in the waste bin and needs no mechanism.
#        Manufacturer's replacement interval is 30 days.
#
# SPRAY_TOTAL_DAYS is CONFIRMED: PetKit's own cloud answers `dev_device_info`
# with `sprayDays: 45` alongside `sprayResetTime`, captured in proxy mode, and
# it is the same 45 the manufacturer's replacement interval gives. It is also
# what `Device.to_device_info` advertises to the device, which the firmware
# stores (`set sprayDays (%d)` in `ctrl`), so both sites must read this
# constant. They were once independently hardcoded to 45 and 30, and HA burned
# down a cartridge the device had been told was a third longer.
#
# DEODORANT_TOTAL_DAYS is the manufacturer's interval only, and the field it
# counts from never arrives -- see the N50 note below.
#
# Mind the vocabulary, which is inverted from the products: `deodorantLeftDays`
# is the N50 even though the N60 is the active deodorant, and `sprayLeftDays` is
# the N60. Those are pypetkitapi's cloud names, kept because they are already
# the entities' `value_path`. Do not "correct" one into the other.
#
# Why the cloud vocabulary says "spray" rather than "N60": the deodorizing
# FUNCTION is not tied to the N60. Models with no built-in unit can take an
# optional K3 (Pura Air) over BLE instead, so one field name has to cover both.
# On a T5 it is unambiguously the built-in N60 — `ctrl` holds no `k3` string at
# all and drives the sprayer off its own motor controller
# (`_pki_transmit_spray_over_event_from_mot`, `pk_hmi_get_spray_percent`), while
# `k3LightSwitch` turns up in a T4 property post and the T4 has no N60.
#
# The substitution is functional, NOT a shared data source: a K3 reports
# `battery`/`liquid` LEVELS on its parent's report (`bridge._update_linked_k3`),
# never a reset date, so these date-based countdowns cannot be fed from a K3 and
# a K3-equipped box cannot be assumed to populate them.
# The N50 has NO representation in the device protocol, established by
# experiment on a T5 (2026-07-30). Resetting the N60 from PetKit's app sends
# `thing.service.start {"start_action":10}`, the box answers `liquid_reset_over`
# and its `sprayResetTime` becomes the reset moment. Resetting the N50 from the
# app sends ONLY `thing.service.errState {"show":1,"err_state":1}` -- no start,
# no date, no device reply, and `liquidReset` does not move. PetKit's own
# `dev_device_info` reply carries no N50 field either: just `sprayDays`,
# `sprayResetTime` and the `deodorantTip`/`purificationTip` notify flags. So
# PetKit keeps the N50 replacement date in their account database and only tells
# the box what to display.
#
# Consequence: `deodorantLeftDays` can never be filled from telemetry. Its
# source `liquidReset` has been 0 in every one of 983+ captured reports and
# nothing in any transport ever writes it. For "N50 Days Left" to read anything
# we have to record the replacement date ourselves -- being the cloud is the
# whole point of this add-on, and this is one of the places that has to mean it.
SPRAY_TOTAL_DAYS = 45
DEODORANT_TOTAL_DAYS = 30

#: Where a replacement date WE recorded lives, inside `Device.config`. It has to
#: be config rather than `state`: state is rebuilt from the device's next
#: contact and does not survive a restart, and for the N50 there is no next
#: contact that would ever carry it.
CONSUMABLE_RECORD_KEY = "consumables"

#: The consumables a "replaced" action can stamp, and what each one fills.
CONSUMABLE_TOTALS = {
    "n50": ("deodorantLeftDays", DEODORANT_TOTAL_DAYS),
    "n60": ("sprayLeftDays", SPRAY_TOTAL_DAYS),
}

#: OURS, not the device's: no work-mode code means "idle", because the device
#: says so by omitting `workState` entirely. Deliberately negative so it can
#: never collide with a real `WORK_MODES` code, and deliberately NOT added to
#: that table, which is the device's vocabulary and not ours. `sensors.py` pairs
#: it with the label; nothing else should read it as a protocol value.
WORK_MODE_IDLE = -1

#: Fields the device sends ONLY while the thing they describe is happening.
#: Presence is the whole signal — the payload never carries an "off" value, it
#: just stops appearing. Measured over 1254 captured snapshots (both
#: transports): the report is a fixed 29-key dump plus at most these extras,
#: `workState` (166), `lightState` (166) and `refreshState` (32).
#:
#: They MUST be turned into a real 0/1 here, because `device.state` is only ever
#: merged into and never pruned: a key that stops being sent keeps its last
#: value forever. `refreshState` is also an object, and a non-empty dict is
#: truthy — so the "Deodorization Running" sensor latched ON at the box's first
#: spray and stayed on for good. `lightState` is mapped too, since it has the
#: identical shape and would repeat the bug the moment anyone gives it an entity.
PRESENCE_FLAGS = {
    "refreshState": "deodorizing",
    "lightState": "lightOn",
}


#: Proof that a payload is a whole-device snapshot rather than a fragment.
#: `litter` was present in all 1254 captured litter-box reports across both
#: transports, so its absence means we are looking at something partial (a
#: hand-built dict in a test, a device that frames its report differently) and
#: must not conclude anything from a key not being there.
SNAPSHOT_MARKER = "litter"


def _extract_presence_flags(body: dict[str, Any], state: dict[str, Any]) -> None:
    """Turn the presence-signalled fields into 0/1 in `state`.

    Only for a full snapshot: reading absence as "off" is exactly as wrong as
    reading presence as "on" if the payload was never going to carry the key in
    the first place. `SNAPSHOT_MARKER` is what separates the two cases.
    """
    if SNAPSHOT_MARKER not in body:
        return
    for field_name, flag in PRESENCE_FLAGS.items():
        state[flag] = 1 if body.get(field_name) else 0


def _extract_shared(body: dict[str, Any], state: dict[str, Any]) -> None:
    """Everything derived identically from either transport's payload.

    ONE call site per transport instead of one per derivation. The module
    docstring calls hand-syncing the two lists "the standard bug in this
    module", and it had already happened three times to the consumables alone;
    `runtime` was the fourth. Anything computed the same way from the same
    fields belongs in here, not copied into both parsers.
    """
    # runtime (seconds of uptime) -> totalTime. This lived only in the HTTP
    # parser, and a T5 STOPS polling the HTTP heartbeat once it is on MQTT --
    # so the Uptime sensor was permanently unknown on exactly the devices that
    # had the healthiest connection.
    if "runtime" in body:
        state["totalTime"] = body["runtime"]
    _extract_consumable_days(body, state)
    _extract_presence_flags(body, state)


def record_consumable_reset(device: Device, which: str,
                            when: float | None = None) -> float | None:
    """Stamp `which` ("n50"/"n60") as replaced now and refresh its countdown.

    Returns:
        The stamp written, or None for a name we do not track — the caller logs
        it rather than guessing which consumable was meant.
    """
    if which not in CONSUMABLE_TOTALS:
        return None
    ts = float(when) if when is not None else time.time()
    device.config.setdefault(CONSUMABLE_RECORD_KEY, {})[which] = ts
    apply_consumable_state(device)
    return ts


def apply_consumable_state(device: Device) -> None:
    """Fill both consumable countdowns, and persist the N60 stamp.

    The N50 has no representation anywhere in the device protocol — see the note
    above — so a date we recorded is its ONLY possible source.

    The N60 does have one, and the DEVICE wins: `sprayResetTime` is also moved by
    a reset from PetKit's app, so the box's stamp can be newer than ours. What we
    keep is a copy, and that copy earns its place twice: the countdown survives a
    restart, and `to_device_info` stops echoing a zero back over a live reset
    date during the window before the device has reported.

    Call this AFTER the state parsers, which is where `sprayResetTime` arrives.
    """
    rec = device.config.get(CONSUMABLE_RECORD_KEY)
    if not isinstance(rec, dict):
        rec = {}
        device.config[CONSUMABLE_RECORD_KEY] = rec

    reported = to_float(device.state.get("sprayResetTime"), None)
    if reported:
        rec["n60"] = reported
    else:
        remembered = to_float(rec.get("n60"), None)
        if remembered:
            device.state["sprayResetTime"] = remembered

    for which, (state_key, total) in CONSUMABLE_TOTALS.items():
        left = _days_left_from_reset(rec.get(which), total)
        if left is not None:
            device.state[state_key] = left


def parse_state_report(device_type: str, body: dict[str, Any]) -> dict[str, Any]:
    """Flatten a state report for `device_type` into the keys HA entities read.

    Returns:
        A flat dict of camelCase keys (plus the nested `feedState` / `workState`
        sub-objects a few entities index into). An unknown device type gets its
        body back UNCHANGED rather than an empty dict, so a model we have not
        classified yet still shows whatever it happens to name correctly.
    """
    if not body:
        return {}

    if device_type in ("t5", "t6", "t7"):
        return _parse_litter_camera(body)
    if device_type in ("t3", "t4"):
        return _parse_litter_esp32(body)
    if device_type in ("d4h", "d4sh", "d4", "d3", "d4s", "feeder", "feedermini"):
        return _parse_feeder(body)
    if device_type in ("w4", "w5", "ctw2", "ctw3", "w7h"):
        return _parse_water_fountain(body)
    if device_type in ("k2", "k3"):
        return _parse_purifier(body)

    return body


def _extract_camel(body: dict[str, Any], keys: list[str], state: dict[str, Any]) -> None:
    """Copy `keys` from `body` into `state`, accepting either spelling.

    Each key is looked up as written and again in snake_case, because a device
    mixes the two spellings within one payload. The snake_case hit is applied
    second and therefore WINS if a payload somehow carries both; no device has
    been observed doing that, so the precedence is arbitrary, not meaningful.
    """
    for key in keys:
        if key in body:
            state[key] = body[key]
        snake = _to_snake(key)
        if snake != key and snake in body:
            state[key] = body[snake]


def _days_left_from_reset(reset_ts: Any, total_days: int = 30) -> int | None:
    """Compute remaining days from a unix reset timestamp (e.g. sprayResetTime).

    Rounded UP, because a part-used day is still a day you have: 19.5 days
    remaining is "20 days left", and it reaches 0 only when the interval is
    genuinely spent. Truncating instead made a consumable replaced one second
    ago report `total - 1`, so pressing Reset N50 showed 29 of 30 days
    immediately — visibly wrong at the one moment the user is looking.

    `reset_ts` is whatever the device put in the field, hence `to_float`
    rather than a numeric annotation. An isinstance check is not enough:
    `json.loads` accepts bare `Infinity`/`NaN` by default and an int is
    unbounded, so the arithmetic could raise OverflowError on a device payload
    and take the whole state report down with it. `to_float` rejects both, and
    accepts the numeric-string form the field sometimes has.
    """
    ts = to_float(reset_ts, None)
    if not ts:
        return None
    days_since = (time.time() - ts) / 86400
    return max(0, math.ceil(total_days - days_since))


def _extract_consumable_days(body: dict[str, Any], state: dict[str, Any]) -> None:
    """Derive the N60 spray and N50 deodorant countdowns from their reset stamps.

    Shared by BOTH transports on purpose. This lived only in
    `_extract_litter_nested`, which the MQTT property post never reaches, so a
    device that speaks only MQTT — a T5 stops polling the HTTP heartbeat once it
    connects, and may never send a single `dev_state_report` — left both sensors
    permanently empty while reporting a perfectly good `sprayResetTime`.

    A zero stamp is not a fresh cartridge, it is "never reset": `liquidReset` was
    0 in all 685 captured reports of a box whose N50 had never been replaced.
    `_days_left_from_reset` returns None for it and the key is left unset, so HA
    shows unknown rather than a confident zero days remaining.
    """
    spray_left = _days_left_from_reset(body.get("sprayResetTime"), SPRAY_TOTAL_DAYS)
    if spray_left is not None:
        state["sprayLeftDays"] = spray_left

    liquid_left = _days_left_from_reset(body.get("liquidReset"), DEODORANT_TOTAL_DAYS)
    if liquid_left is not None:
        state["deodorantLeftDays"] = liquid_left


def _extract_litter_nested(body: dict[str, Any], state: dict[str, Any]) -> None:
    """Flatten the nested sub-objects a real litter box sends into `state`.

    Confirmed against a real T5. Sets, when the source is present: `sandWeight`,
    `sandPercent`, `usedTimes`, `sandType` (from `litter`), `errorMsg` and
    `boxFull` (from `err`), `petInTime` (from `device`), `totalTime` (from
    `runtime`), and the two countdowns derived from reset timestamps,
    `sprayLeftDays` and `deodorantLeftDays`. Absent sources leave `state`
    untouched rather than writing a zero, so a missing field stays unknown in HA
    instead of reading as a real measurement of nothing.
    """
    # litter{weight, percent, usedTimes, sandType}
    litter = body.get("litter")
    if isinstance(litter, dict):
        if "weight" in litter:
            state["sandWeight"] = litter["weight"]
        if "percent" in litter:
            state["sandPercent"] = litter["percent"]
        if "usedTimes" in litter:
            state["usedTimes"] = litter["usedTimes"]
        if "sandType" in litter:
            state["sandType"] = litter["sandType"]

    # err{DC:0, mcu:0, scale:0, ...} -> errorMsg (comma-sep active), boxFull
    err = body.get("err")
    if isinstance(err, dict):
        active = [k for k, v in err.items() if v and k != "full"]
        state["errorMsg"] = ",".join(active) if active else ""
        if "full" in err:
            state["boxFull"] = err["full"]

    # device{sw, pet_in_time}
    dev = body.get("device")
    if isinstance(dev, dict):
        if "pet_in_time" in dev:
            state["petInTime"] = dev["pet_in_time"]

    _extract_shared(body, state)


def _extract_wifi_rssi(body: dict[str, Any], state: dict[str, Any]) -> None:
    """Pull signal strength out of `wifi`, which spells it `rsq` or `rssi`.

    Falls back to whatever is already in `state` so calling this after a flat
    top-level `rssi` was extracted cannot blank it.
    """
    wifi = dig(body, "wifi", default={})
    if isinstance(wifi, dict):
        state["rssi"] = wifi.get("rsq", wifi.get("rssi", state.get("rssi")))


def _parse_content_field(body: dict[str, Any], state: dict[str, Any]) -> None:
    """Merge the `content` sub-document, which arrives as a dict OR a JSON string.

    Unparseable content is dropped silently: the rest of the report is still
    worth publishing, and this field is not where the primary values live.
    """
    if "content" not in body:
        return
    content = body["content"]
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return
    if isinstance(content, dict):
        state.update(content)


def _extract_work_mode(body: dict[str, Any], state: dict[str, Any]) -> None:
    """Set `workingState` (the mode int) and, when sent as one, `workState` (the object)."""
    # `workState` is an object {workMode, workProcess, ...}, not a scalar. The
    # HA "Device Status" sensor wants the mode int.
    ws = dig(body, "workState", default=dig(body, "work_state"))
    if isinstance(ws, dict):
        state["workState"] = ws
        state["workingState"] = ws.get("workMode", ws.get("work_mode", 0))
    elif ws is not None:
        state["workingState"] = ws
    elif SNAPSHOT_MARKER in body:
        # A litter box sends `workState` ONLY while a cycle is running: it is
        # absent from 988 of 1254 captured snapshots, present in 166, and the
        # payload is otherwise a fixed 29-key dump. This used to default to 0,
        # which is `WORK_MODES[0] == "cleaning"` -- so an idle box reported
        # itself as cleaning about 79% of the time. Absence means idle, but
        # only in a payload that would have carried the key had it applied.
        state["workingState"] = WORK_MODE_IDLE
    # else: nothing is known, so nothing is written and HA reads unknown --
    # the same rule the rest of this module follows.


def _parse_litter_camera(body: dict[str, Any]) -> dict[str, Any]:
    """State for the Ingenic camera litters (T5/T6/T7).

    The ESP32 litter set plus the camera, spray and package fields, and the
    `content` / `Ip` extras only these models send.
    """
    state: dict[str, Any] = {}
    _extract_work_mode(body, state)
    _parse_content_field(body, state)
    _extract_camel(body, [
        "sandWeight", "sandPercent", "boxFull",
        "petInTime", "deodorantLeftDays", "sprayLeftDays",
        "errorMsg", "rssi", "usedTimes", "totalTime",
        "boxState", "sprayState", "refreshState",
        "cameraStatus", "power",
        # The raw reset stamps, not just the countdowns derived from them:
        # `to_device_info` echoes `sprayResetTime` straight back to the device,
        # and `apply_consumable_state` needs to see what the box reported to
        # know whether to prefer it over the date we recorded ourselves.
        "sprayResetTime", "liquidReset",
        # `discernPic` is the READBACK of on-device facial recognition: the
        # `discern[].id` values whose photos the device downloaded and
        # feature-extracted (features persist in /system/feature.bin there).
        # It is the only way to see whether a dev_discern_pic payload was
        # accepted, which is why it is worth a state field of its own.
        # `aiAnalyse` sits beside it and was 0 in all 733 captured reports;
        # what turns it on is not known.
        "discernPic", "aiAnalyse",
    ], state)
    # Extract from nested sub-objects (real T5 format). Placed AFTER
    # _extract_camel so nested values override any flat keys.
    _extract_litter_nested(body, state)
    ip = body.get("Ip", body.get("ip", ""))
    if ip:
        state["ip"] = ip
    _extract_wifi_rssi(body, state)
    return state


def _parse_litter_esp32(body: dict[str, Any]) -> dict[str, Any]:
    """State for the ESP32 litters (T3/T4), which have no camera or spray fields."""
    state: dict[str, Any] = {}
    _extract_work_mode(body, state)
    _extract_camel(body, [
        "sandWeight", "sandPercent", "boxFull",
        "petInTime", "deodorantLeftDays", "errorMsg", "rssi",
        "usedTimes", "totalTime", "boxState", "power",
        "sprayResetTime", "liquidReset",
    ], state)
    # Extract from nested sub-objects (same nested format as camera models).
    # Placed AFTER _extract_camel so nested values override any flat keys.
    _extract_litter_nested(body, state)
    _extract_wifi_rssi(body, state)
    return state


def _parse_feeder(body: dict[str, Any]) -> dict[str, Any]:
    """State for every feeder, camera or not.

    One parser for both: the camera models add camera fields to the same
    payload, and the camera-only keys are simply absent on the ESP32 ones, so
    asking for them costs nothing. `feedState` is kept as a NESTED dict because
    the feeder entities address it as `feedState.<key>`.
    """
    state: dict[str, Any] = {}
    state["workingState"] = body.get("workState", body.get("work_state", 0))
    _extract_camel(body, [
        "errorMsg", "rssi", "desiccantLeftDays",
        "batteryPower", "batteryStatus",
        "door", "bowl", "weight", "food", "food1", "food2",
        "cameraStatus", "feeding", "eating",
    ], state)

    feed_state = dig(body, "feedState", default=dig(body, "feed_state", default={}))
    if isinstance(feed_state, dict) and feed_state:
        parsed_fs: dict[str, Any] = {}
        _extract_camel(feed_state, [
            "times", "realAmountTotal", "eatAmountTotal", "addAmountTotal",
            "planAmountTotal", "planRealAmountTotal", "eatAvg", "eatCount",
            "addAmountTotal1", "addAmountTotal2",
            "planAmountTotal1", "planAmountTotal2",
            "realAmountTotal1", "realAmountTotal2",
        ], parsed_fs)
        state["feedState"] = parsed_fs

    _extract_wifi_rssi(body, state)
    return state


def _parse_water_fountain(body: dict[str, Any]) -> dict[str, Any]:
    """State for the water fountains (W4/W5/CTW2/CTW3/W7H)."""
    state: dict[str, Any] = {}
    state["workingState"] = body.get("workState", body.get("work_state", 0))
    _extract_camel(body, [
        "errorMsg", "rssi", "filterLeftDays", "filterPercent",
        # real fountain field names (pypetkitapi water_fountain_container):
        "lackWarning", "heatRealTemp", "drinkTime",
        "batteryPercent", "lowBattery", "filterWarning", "detectStatus",
        "pumpState", "waterPumpState", "cwtState", "wtState",
        "addWaterState", "flushState", "disinfectState",
        "heatInstall", "stgFullState", "runStatus", "powerStatus",
    ], state)

    electricity = dig(body, "electricity", default={})
    if isinstance(electricity, dict):
        state["batteryPercent"] = electricity.get("battery_percent", electricity.get("batteryPercent", state.get("batteryPercent")))

    status = dig(body, "status", default={})
    if isinstance(status, dict):
        state["detectStatus"] = status.get("detect_status", status.get("detectStatus", state.get("detectStatus")))

    _extract_wifi_rssi(body, state)
    return state


def _parse_purifier(body: dict[str, Any]) -> dict[str, Any]:
    """State for a purifier reporting over HTTP.

    K2/K3 are BLE-only in every shipping product, so this path is only reached
    if a WiFi purifier ever exists; the K3 values we actually see arrive
    piggybacked on its parent litter's report instead.
    """
    state: dict[str, Any] = {}
    state["workingState"] = body.get("workState", body.get("work_state", 0))
    _extract_camel(body, [
        "errorMsg", "humidity", "temp", "refresh",
        "liquid", "battery", "power", "mode",
        "refreshing", "liquidLack", "leftDay",
    ], state)
    _extract_wifi_rssi(body, state)
    return state


def _to_snake(s: str) -> str:
    """`sandPercent` -> `sand_percent`. Naive by design; only used to widen a lookup."""
    return re.sub(r'([A-Z])', r'_\1', s).lower().lstrip('_')


def normalize_property_params(device_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Flatten an MQTT `thing/event/property/post` into the HA state keys.

    Produces the same flat camelCase keys as `parse_state_report`
    (`sandPercent`, `rssi`, `errorMsg`, ...), so one entity definition serves
    both transports.

    The MQTT property post nests data differently from the HTTP state_report
    (verified against a real T4 capture): litter under params.litter, signal
    under params.wifi.rsq, errors under params.err. Only keys that are present
    get mapped, so this is safe to run on any device type.

    Args:
        device_type: Currently unused — every call site already passes it, and
            keeping it means adding a per-model branch will not have to change
            three signatures across two transports.
    """
    if not isinstance(params, dict):
        return {}
    flat: dict[str, Any] = {}

    litter = params.get("litter")
    if isinstance(litter, dict):
        for src, dst in (("percent", "sandPercent"), ("weight", "sandWeight"),
                         ("usedTimes", "usedTimes"), ("sandType", "sandType")):
            if src in litter:
                flat[dst] = litter[src]

    wifi = params.get("wifi")
    if isinstance(wifi, dict):
        rssi = wifi.get("rsq", wifi.get("rssi"))
        if rssi is not None:
            flat["rssi"] = rssi

    dev = params.get("device")
    if isinstance(dev, dict):
        if "pet_in_time" in dev:
            flat["petInTime"] = dev["pet_in_time"]

    # Flat state fields the device reports at the top level.
    # Kept in step with `_parse_litter_camera`'s list by hand — the two
    # transports share no table, and forgetting the second is the standard bug
    # in this module.
    for key in ("cameraStatus", "sprayState", "boxState", "weightState",
                "refreshState", "ota",
                "discernPic", "aiAnalyse",
                "sprayResetTime", "liquidReset"):
        if key in params:
            flat[key] = params[key]

    if "box" in params and isinstance(params.get("box"), (int, bool)):
        flat["boxFull"] = int(params["box"])

    # Everything both transports derive the same way: the consumable
    # countdowns, the presence flags and uptime. The fields sit at the top level
    # of a property post exactly as they do in a state report, so one helper
    # serves both -- which is the point, see `_extract_shared`.
    _extract_shared(params, flat)

    err = params.get("err")
    if isinstance(err, dict):
        active = [k for k, v in err.items() if v]
        flat["errorMsg"] = ",".join(active) if active else ""
        if err.get("full"):
            flat["boxFull"] = err["full"]

    ws = params.get("work_state", params.get("workState"))
    if isinstance(ws, dict):
        flat["workingState"] = ws.get("work_mode", ws.get("workMode", 0))
    elif SNAPSHOT_MARKER in params:
        # Same presence rule as `_extract_work_mode`: no work cycle means idle.
        # Gated on a full litter snapshot so this cannot invent a work mode for
        # a feeder or fountain, whose own parsers own that key.
        flat["workingState"] = WORK_MODE_IDLE

    if "firmware" in params:
        flat["firmware"] = params["firmware"]

    # The `other` free-form string carries the device IP (needed for the camera).
    other = params.get("other")
    if isinstance(other, str):
        m = re.search(r'Ip:"?([0-9.]+)"?', other)
        if m:
            flat["ip"] = m.group(1)

    return flat
