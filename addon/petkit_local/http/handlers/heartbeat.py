"""poll/{type}/heartbeat — the device's ~15s poll, and how commands reach it.

This is the slow but always-available command channel. The device asks "anything
for me?" every few seconds over plain HTTP; whatever is in its `command_queue`
comes back in the response and is executed. MQTT delivers the same commands
instantly, but only to a device whose `ctrl` binary trusts our broker, so the
heartbeat is the path that works on stock firmware and the fallback when MQTT
is down.

Producers therefore enqueue in MQTT envelope form and let this module translate:
`ha/publisher.py` falls back to the queue whenever the device has no live MQTT
session, and `web/panel.py` queues the same envelopes. `_to_heartbeat_content`
converts them to the flat `{msgType, payload, type, timestamp}` object the HTTP
path expects, so a caller never has to know which channel will carry its
command. (`patchers/common.py` is the exception: it queues an already-serialized
string, which passes straight through.)

The poll is also where we find out that the *other* channel died: the device
reports its own MQTT state in `?iotStatus=`, and `note_iot_status` is what stops
a lost session from swallowing commands forever.

`carries_commands` lives here too, because it is the same concern seen from the
other side: in proxy mode every other endpoint's local answer is discarded in
favour of the cloud's, but this one has already spent the queue to build itself,
so a reply that is delivering something is sent as-is and never forwarded.
"""
from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web

from petkit_local.http.handlers._common import request_device
from petkit_local.utils.coerce import to_bool

if TYPE_CHECKING:
    from petkit_local.devices.base import Device

log = logging.getLogger(__name__)

# MQTT service suffix → heartbeat msgType + type field
_SERVICE_MAP = {
    "start": (2, "start"),
    "end": (3, "end"),
    "property/set": (5, "property_set"),
    "feed_realtime": (6, "feed_realtime"),
    "connect": (7, "connect"),
}


def _to_heartbeat_content(cmd: Any) -> str:
    """Convert a queued command into the heartbeat `content` string.

    Accepts the several shapes producers queue, in this order: an already
    serialized string (passed through untouched — see `patchers/common.py`);
    a dict already in heartbeat form, i.e. carrying `msgType`, which only gets a
    `timestamp` if it lacks one; and otherwise an MQTT envelope, whose service
    is read from the `_service_suffix` marker the producer attached or, failing
    that, inferred from a substring match on its `method`.

    Returns:
        A JSON string ``{"msgType": int, "payload": ..., "type": str,
        "timestamp": int}``. An envelope for an unrecognised service falls back
        to the `start` service (msgType 2) rather than being dropped, since a
        command that arrives mislabelled is easier to diagnose from the device's
        reaction than one that silently disappears.
    """
    if isinstance(cmd, str):
        return cmd

    if not isinstance(cmd, dict):
        return json.dumps(cmd)

    # Already in heartbeat format (has msgType)
    if "msgType" in cmd:
        if "timestamp" not in cmd:
            cmd["timestamp"] = int(time.time())
        return json.dumps(cmd)

    # Queued as (service_suffix, mqtt_envelope) tuple stored as dict with
    # _service_suffix key, or as raw MQTT envelope with method field.
    service = cmd.pop("_service_suffix", "")
    params = cmd.get("params", cmd)

    if not service:
        method = cmd.get("method", "")
        for suffix in _SERVICE_MAP:
            if suffix in method:
                service = suffix
                break

    msg_type, type_str = _SERVICE_MAP.get(service, (2, "start"))
    ts = int(time.time())

    return json.dumps({
        "msgType": msg_type,
        "payload": params,
        "type": type_str,
        "timestamp": ts,
    })


#: How long after a CONNECT an `iotStatus=0` is treated as a lagging sample
#: rather than a lost session. The device fills the value in before it sends the
#: request, so a poll in flight when the session came up reports the state from
#: just before it — observed 112ms after the CONNECT on a real T5. One poll
#: period plus room to spare; the cost of being wrong is one heartbeat's delay
#: before the backstop can fire.
IOT_STATUS_GRACE = 15.0


def note_iot_status(device: Device, request: web.Request) -> None:
    """Believe the device when it says it has no MQTT session.

    Every heartbeat carries `?iotStatus=`: 1 while the firmware's Aliyun Link
    session is up, 0 while it is not. It is the only report we get from the
    device's own side of the connection, and it arrives every ~10s.

    This is the backstop, not the primary: `mqtt/auth.py` clears the flag the
    moment a session ends. What that hook cannot see is a session that ended
    without the broker noticing — a device that reboots or drops off Wi-Fi
    leaves a half-open socket, and amqtt only reaps it after the CONNECT's
    keepalive expires, which for a keepalive of 0 is never. That is the shape of
    "MQTT stopped working and the add-on had to be restarted".

    It only ever CLEARS `mqtt_connected`, never sets it. `iotStatus=1` says the
    device is on *a* broker; only a CONNECT we authenticated proves it is on
    *ours*, and in proxy mode the other answer is Aliyun's. So setting the flag
    stays with auth, and this is the half that can be believed on its own.
    Clearing on a stale 0 costs little either: the command falls back to the
    heartbeat queue, which is the path that always works.

    No await, and called before `pop_commands`, so it cannot come between the
    pop and the send (see this module's `carries_commands`).
    """
    raw = request.query.get("iotStatus")
    if raw is None or not device.mqtt_connected:
        return
    # Default True on an unparseable value: no news is not bad news.
    if to_bool(raw, True):
        return
    if time.time() - device.mqtt_connected_at < IOT_STATUS_GRACE:
        # Sampled before the session we just accepted; not evidence of a loss.
        return
    device.mqtt_connected = False
    log.info("Heartbeat %s (id=%d): device reports iotStatus=%s - clearing "
             "mqtt_connected, commands go back to the heartbeat queue",
             device.device_type, device.petkit_id, raw)
    hub = request.app.get("event_hub")
    if hub is not None:
        hub.publish("connect", device.petkit_id,
                    f"no MQTT session (device reports iotStatus={raw})")


async def handle_heartbeat(request: web.Request) -> web.Response:
    """Answer the device's poll, delivering any commands queued for it.

    Also the liveness signal for models with no MQTT session: a heartbeat stamps
    `last_heartbeat` and marks the device online.

    Returns:
        ``{"result": [{"time": ms, "timestamp": s, "content": str}, ...]}`` with
        one entry per queued command, or ``{"result": [{"time": ms}]}`` — the
        idle answer — when there is nothing to send. In proxy mode this response
        is not thrown away like the other handlers' when it carries a command:
        see `carries_commands`, because the queue has already been drained by the
        time anything else could decide.

    Delivery is at-most-once: `pop_commands` empties the queue as it builds the
    response, and nothing re-queues a command whose response never arrived.
    `patchers/common.py::wait_for_heartbeat` depends on exactly that — an empty
    queue is its signal that the device picked the command up.
    """
    device = request_device(request)

    ts_ms = int(time.time() * 1000)

    if device:
        device.last_heartbeat = time.time()
        device.online = True
        note_iot_status(device, request)

        cmds = device.pop_commands()
        if cmds:
            ts = int(time.time())
            result = []
            for cmd in cmds:
                result.append({
                    "time": ts_ms,
                    "timestamp": ts,
                    "content": _to_heartbeat_content(cmd),
                })
            log.info("Heartbeat %s (id=%d): delivering %d commands",
                     device.device_type, device.petkit_id, len(cmds))
            return web.json_response({"result": result})

    return web.json_response({"result": [{"time": ts_ms}]})


def _is_idle_marker(entry: Any) -> bool:
    """Whether a `result[]` entry is the "nothing to do" filler.

    The idle answer is exactly ``{"time": ms}`` — no `content`, nothing to
    execute. Both sides of a merge produce one, and two of them in a row is a
    shape no device has ever been sent. Matched on the key set rather than on
    "has no content", so an upstream command in a shape we do not recognise is
    kept rather than quietly dropped.
    """
    return isinstance(entry, dict) and set(entry) <= {"time", "timestamp"}


def carries_commands(response: web.StreamResponse) -> bool:
    """Whether this heartbeat reply is actually delivering something.

    `proxy_middleware` asks before it forwards anything: building this response
    already drained `device.command_queue` (`devices/base.py::pop_commands` is
    destructive and at-most-once), and there is no way to put a command back. So
    when the answer carries one, it is sent straight to the device with no await
    in between — no upstream call, no redaction, nothing that a cancellation, a
    timeout or an exception could interrupt.

    That is the whole protection. Merging the two replies, which this module used
    to do, only guards against the upstream's answer *replacing* ours; it does
    nothing about the reply never being sent at all. `patchers/common.py::
    wait_for_heartbeat` watches the queue drain, so a command lost after the pop
    is reported as delivered.

    Returns:
        False for anything unreadable — the safe direction is to forward, and a
        body we cannot parse did not come from `handle_heartbeat`.
    """
    body = bytes(getattr(response, "body", b"") or b"")
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError, TypeError):
        return False
    result = data.get("result") if isinstance(data, dict) else None
    return isinstance(result, list) and any(not _is_idle_marker(e) for e in result)
