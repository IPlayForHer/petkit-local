"""dev_signup — device registration, the first call of a device's life.

A device that has just been pointed at us announces itself here, and the reply
is what convinces it that it belongs to an account and may proceed to fetch MQTT
credentials, its config and its schedules. Everything downstream assumes the
registry entry this creates.

One of the two handlers that may CREATE a registry entry (the other is
iot_device_info); `handlers/_common.py` resolves but never creates, so the
`get_or_create` below stays here.
"""
from __future__ import annotations

import logging

from aiohttp import web

from petkit_local.http.handlers._common import device_field, device_id, device_serial

log = logging.getLogger(__name__)


async def handle_signup(request: web.Request) -> web.Response:
    """Register the calling device, then hand it its identity back.

    `mac` and `firmware` are read from the query string or the POST body — they
    are not part of the `X-Device` header — and are stored as reported, since
    nothing else in the system can supply them. Reading them from the body is
    not cosmetic: a device that sends everything there would otherwise register
    with a blank serial, and `mqtt_device_name` is built from the serial once
    and never repaired (`registry.get_or_create` only fills blanks).

    Returns:
        `Device.to_signup()` for the created or existing device. The one
        endpoint here that answers with an error status: without a usable id
        there is nothing to key a registry entry on, so a 400 is returned rather
        than minting a device under a fabricated id.

    Fires the app's ``on_signup`` callback (HA discovery) before replying, so a
    device is published to Home Assistant before it starts reporting state.
    """
    registry = request.app["registry"]
    device_type = request.get("device_type", "t5")

    petkit_id = device_id(request)
    sn = device_serial(request)
    mac = device_field(request, "mac") or ""
    firmware = device_field(request, "firmware") or ""

    if petkit_id is None:
        return web.json_response({"error": "missing device id"}, status=400)

    device = registry.get_or_create(
        petkit_id=petkit_id,
        device_type=device_type,
        serial_number=sn,
        mac=mac,
        firmware=firmware,
    )
    # An ESP32 feeder is the only source of its own BLE address, and it offers
    # it exactly once, here. `devices/base.py` already reads `bt_mac` out of
    # `config` when answering `dev_device_info`; nothing had ever written it.
    bt_mac = device_field(request, "bt_mac")
    if bt_mac and not device.config.get("bt_mac"):
        device.config["bt_mac"] = bt_mac
        registry.mark_dirty()
    log.info("Signup: %s id=%d sn=%s fw=%s", device_type, petkit_id, sn, firmware)

    on_signup = request.app.get("on_signup")
    if on_signup:
        await on_signup(device)

    return web.json_response(device.to_signup())
