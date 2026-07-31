"""dev_schedule_get — the litter box's scheduled cleaning times.

Like the feeder's schedule, this is executed by the device against its own
clock, not driven from here, so the response has to be a valid schedule under
all circumstances — including for a device we cannot identify, which still gets
the three-entry default below rather than an error.
"""
from __future__ import annotations

from aiohttp import web

from petkit_local.http.handlers._common import device_id, request_device
from petkit_local.utils.timeutil import cloud_timestamp

#: The default cleaning times, in the device's own units (minutes past
#: midnight: 585 = 09:45). Never confirmed against a device, so left as the
#: literals they have always been rather than derived from a wall clock.
DEFAULT_SCHEDULE_TIMES = (585, 825, 1125)


async def handle_schedule_get(request: web.Request) -> web.Response:
    """Return the device's stored cleaning schedule, or the default three.

    Returns:
        ``{"result": [...]}`` — verbatim ``device.config["schedule"]`` when one
        has been set, otherwise one entry per `DEFAULT_SCHEDULE_TIMES`.

    Two fields follow the real cloud rather than what this used to send
    (captured 2026-07-27). `id` is distinct per entry — the cloud numbers them
    (103382, 103383, 103384) while every row here shared `id: 0`, which is not
    an id at all. `updatedAt` is an ISO-8601 string, not a unix int; it is also
    now a FIXED instant rather than `now()`, so the body is byte-stable between
    polls instead of claiming the schedule changed every few seconds.
    """
    device = request_device(request)

    if device and device.config.get("schedule"):
        return web.json_response({"result": device.config["schedule"]})

    # The default schedule echoes the requester's id back in `deviceId`; an
    # unidentified device keeps the 0 the firmware has always received here.
    petkit_id = device.petkit_id if device else (device_id(request) or 0)
    # The epoch — these entries are built-in and have never been edited, so
    # "last updated" is as far back as we can honestly claim.
    updated_at = cloud_timestamp(0)
    return web.json_response({
        "result": [
            {"id": i, "deviceId": petkit_id, "time": t, "type": 0,
             "repeats": "1,2,3,4,5,6,7", "updatedAt": updated_at}
            for i, t in enumerate(DEFAULT_SCHEDULE_TIMES, start=1)
        ]
    })
