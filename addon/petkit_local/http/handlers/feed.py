"""dev_feed_get — the feeder's scheduled meals.

A feeder dispenses on its own clock, from the schedule it fetches here; the
server is not in the loop at feeding time. So the answer must always be a
well-formed schedule — an unidentified device gets an empty-but-valid one rather
than an error, which leaves it dispensing nothing instead of retrying forever.
"""
from __future__ import annotations

import time

from aiohttp import web

from petkit_local.http.handlers._common import request_device


async def handle_feed_get(request: web.Request) -> web.Response:
    """Return the device's stored feeding schedule, or an empty default.

    Returns:
        ``{"result": ...}`` — verbatim ``device.config["feed_schedule"]`` when
        one has been set, otherwise ``{"schedule": [{re, it, itemJsonString}],
        "nextTick": <now+2h>, "latest": []}``: every day of the week enabled
        with no meals in it, which schedules no feeding at all.
    """
    device = request_device(request)

    if device and device.config.get("feed_schedule"):
        return web.json_response({"result": device.config["feed_schedule"]})

    ts = int(time.time())
    return web.json_response({
        "result": {
            "schedule": [
                {
                    "re": "1,2,3,4,5,6,7",
                    "it": [],
                    "itemJsonString": "[]",
                },
            ],
            "nextTick": ts + 7200,
            "latest": [],
        }
    })
