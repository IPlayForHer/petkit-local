# Architecture

This is a cloud, not a client. A PetKit device is pointed at this add-on instead of PetKit's
servers, and everything follows from that one fact: the device believes it is talking to the cloud,
so every answer has to be shaped like the cloud's, and a wrong answer is not an error message — it
is a device that reboots, retries forever, or silently stops working.

One process, one asyncio loop, one container. Four servers run inside it:

| Server | Port | What talks to it |
|---|---|---|
| Device HTTP API | 80 | The device, for everything except telemetry |
| MQTT broker (amqtt) | 443 (TLS) | The device, for telemetry and pushed commands |
| Media bucket | 9000 | The device, uploading photos and video |
| Web panel | 8099 | You, through Home Assistant Ingress |

Plus one outbound client: `aiomqtt` connected to *Home Assistant's* broker, which is where entities
are published. Do not confuse the two brokers. The one we run is for devices; the one we connect to
is HA's.

## Packages

```
petkit_local/
├── main/          process lifecycle: cli -> wiring -> lifecycle
├── config.py      every tunable, from /data/options.json + Supervisor + CLI + panel
├── http/          the cloud a device believes it is talking to
│   ├── server.py      route table, and the catch-all that must stay last
│   ├── handlers/      one module per endpoint
│   ├── middleware/    device identity, proxy forwarding, request logging
│   ├── redact/        what a cloud reply is allowed to contain
│   ├── proxy.py       upstream session + forward()
│   ├── bucket.py      unauthenticated OSS sink, listening on 0.0.0.0
│   ├── dns.py         resolver for upstream lookups only
│   └── cloud_fetch.py signs as the device to ask PetKit something directly
├── mqtt/          broker.py (amqtt) · auth.py (Aliyun HMAC) · topics.py
│                  bridge.py (device <-> us) · upstream.py (us <-> real Aliyun)
├── devices/       base.py Device + its wire payloads · registry.py (atomic JSON)
│                  state_parsers.py · ble/ (framing, W5, CTW3, registry)
├── ha/            categories.py device category -> entities · discovery.py EntityDef -> payload
│                  publisher.py (the one HA-broker connection) · commands.py HA write -> command
│                  entities/ one module per component
├── events/        codes.py THE protocol tables · decode.py renders values for humans
│                  normalize.py transport -> row · sessions.py rows -> visits
│                  store.py SQLAlchemy async · models.py · migrations.py
├── media/         pipeline.py decrypt -> remux -> path -> row · stitch.py joins ~4s chunks
│                  crypto · transcode · layout · retention · go2rtc
├── web/           panel.py routes + JSON API · hub.py event ring/WS · static/ · templates/
├── patchers/      on-device patches: cacert · mqtt · cloud · camera · ssh
├── ai/pets.py     pet CRUD + the face photos the device's NPU matches against
└── utils/         const · crypto · capture · jsonio · paths · coerce · dicts · timeutil
```

**Layering.** `devices` depends only on `events` and `utils` — it does not know Home Assistant
exists. `ha` depends on `devices`; asking "which entities does this device publish" is an HA
question and is answered in `ha/categories.py`. Nothing imports `web` except `main`.

## How a device request travels

```
device --HTTP--> http/server.py route table
                   │
                   ├─ middleware/device.py     identify the caller from X-Device
                   ├─ middleware/proxy.py      (proxy mode) forward upstream, redact the reply
                   ├─ middleware/logging.py    record it for the panel
                   │
                   └─> handlers/<endpoint>.py
                         │  reads and mutates one Device
                         └─> devices/base.py builds the response body the firmware expects
```

Telemetry takes the other road:

```
device --MQTT--> mqtt/broker.py --> mqtt/auth.py (HMAC, and it SUBSCRIBES the device:
                                    a T5 sends no SUBSCRIBE of its own)
                                 --> mqtt/bridge.py
                                       ├─> events/normalize.py -> events/store.py
                                       ├─> devices/state_parsers.py -> device.state
                                       └─> ha/publisher.py -> Home Assistant
```

And the way back, when you flip a switch in Home Assistant:

```
HA --MQTT--> ha/publisher.py --> ha/commands.py builds the device command
                                   │
                                   ├─ device on MQTT?  mqtt/bridge.py publishes it
                                   └─ otherwise        queued for the HTTP heartbeat
```

Which of those two the command takes is decided by `Device.mqtt_connected`, and that flag is
load-bearing: publishing to a topic nobody subscribes to raises nothing, so a stale `True` does not
fail — it swallows the command.

## Media

A device uploads to `http/bucket.py` under a key it chose. `media/pipeline.py` decrypts it, remuxes
it, gives it a path a human can read, and records a row. Recordings arrive as many ~4-second chunks;
`media/stitch.py` joins each episode into one file and deletes the sources only after verifying the
result. `media/go2rtc.py` runs go2rtc in front of the device's own stream, because the device
refuses a second connection for several seconds and because Home Assistant's camera stack segfaults
reading its FLV directly.

## Where the knowledge lives

Two files carry almost all of the reverse-engineered protocol, and both are deliberately large:

- **`events/codes.py`** — every event code, in six namespaces that must never be merged, each row
  graded by the evidence behind it and naming the firmware function it came from. It is one file
  because the namespaces collide, and the collisions are only visible when they sit together.
- **`devices/base.py`** — the response bodies. What a device is told about itself, its server, its
  storage credentials and its schedule.

Read [`.claude/CLAUDE.md`](.claude/CLAUDE.md) before changing either. It collects the invariants
that are not obvious from the code — the ones where the natural-looking change is the wrong one.
