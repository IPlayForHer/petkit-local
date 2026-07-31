# petkit-local

A Home Assistant add-on that impersonates the PetKit cloud: a litter box, feeder, fountain or
purifier connects to it over HTTP + MQTT instead of PetKit's servers, and petkit-local answers as
the official API, stores events and media locally, and publishes entities via MQTT discovery. It is
an add-on **repository** — `repository.yaml` at the root, the add-on in `addon/`, the package in
`addon/petkit_local/`. It also runs as a plain container or bare process (`docker-compose.yml` at
the root, or `--no-ha`); HA Container and HA Core have no add-on system, so that path is supported,
not a fallback.

**Stack.** Python 3.11+, one asyncio loop, one container. aiohttp (device API, bucket, panel), amqtt
(embedded device-facing broker), aiomqtt (client for HA's broker), SQLAlchemy 2.0 async + aiosqlite
(`{data_dir}/petkit.db`), Jinja2, ffmpeg. Device identity and settings persist as atomic JSON
(`devices.json`, `ble_devices.json`). `README.md` credits the projects the payloads came from.

## Layout

```
petkit_local/
├── main.py        # process lifecycle: builds every server, starts/cancels background tasks
├── config.py      # Config dataclass; /data/options.json + Supervisor + CLI + panel overrides
├── http/          # the cloud a device believes it is talking to. server.py route table + catch-all
│                  #   · middleware.py X-Device/logging/proxy · proxy.py upstream + forward()
│                  #   · redact.py what a cloud reply may contain · bucket.py unauthenticated
│                  #   OSS sink · handlers/ one per endpoint
├── mqtt/          # broker.py (amqtt) · auth.py (Aliyun HMAC) · topics.py · bridge.py
│                  #   · upstream.py proxy-mode bridge to the real Aliyun broker
├── devices/       # base.py Device + every device-facing response body · registry.py (debounced
│                  #   atomic JSON) · categories.py CATEGORY_SPECS · state_parsers.py · ble.py (K3/W5)
├── ha/            # discovery.py EntityDef -> payload/topics · publisher.py (the one HA-broker
│                  #   connection) · commands.py HA write -> device command · entities/ per component
├── events/        # codes.py THE protocol tables (all 6 namespaces, graded, per device family) ·
│                  #   decode.py renders content for humans · models.py SQLAlchemy models ·
│                  #   store.py EventStore (async, plain dicts) · ingest.py transport
│                  #   normalizers + group_sessions()
├── media/         # pipeline.py decrypt -> remux -> friendly path -> row · crypto · transcode ·
│                  #   layout · stitch.py joins an episode's ~4s chunks · retention.py caps
├── web/           # panel.py routes + JSON API · hub.py event ring/WS/diagnostics ·
│                  #   templates/index.html · static/app.js · static/styles.css
├── patchers/      # on-device patches: cacert · mqtt · cloud · camera · ssh · common.py
│                  #   (delivery, staging, device space probe) · verify.py (MIPS/PEM
│                  #   guards, run before anything is written)
├── ai/pets.py     # pet CRUD + the face photos the device's NPU matches against
│                  #   (pet_faces table, N per pet; resolve_pet_ref binds a reported id)
└── utils/         # const · crypto · capture · jsonio · paths · coerce · dicts · timeutil
```

## Invariants — do not break these

- **All protocol knowledge lives in `events/codes.py`** — six namespaces, each row graded
  (`confirmed`/`inferred`/`unverified`/`conflicted`) and carrying the firmware function behind it.
  Add a code there, not in a private set somewhere: the nine parallel collections this replaced are
  exactly why seven real codes were classified by none of them. `events/decode.py` renders values;
  `events/ingest.py` only does transport.
- **HTTP `event_type` codes are PER DEVICE CATEGORY, not global.** Code `2` is `err_over` on a
  litter box and `feed_over` on a D4H feeder. Always pass `device_type` to `codes.lookup` /
  `classify_event_kind` / `event_label`; omitting it assumes a litter box.
- **Two event-code namespaces, never merged.** Our `dev_event_report` codes are authoritative here;
  the cloud-record API's `LitterRecord.subContent[].eventType` ints overlap on 5/8/10 with
  *different* meanings, so only namespace-independent sub-field decoding (`result`/`start_reason`/
  `err`) is borrowed. NS2 stays quarantined in `codes.CLOUD_RECORD_TYPES`, read by nothing.
- **The capture wins on SHAPE, the firmware RE wins on MEANING.** Where they disagree the row is
  graded `conflicted` and its `note` says how — never pick silently. The repo's original labels
  were neither source: code `8` read "Cleaning started" but is the deodorizing cycle's completion.
- **Days are cut at LOCAL midnight** (`utils/timeutil.local_day_bounds`), and the end of a day is
  midnight-next-day re-localized, never `start + 86400` — DST makes days 23 and 25 hours long.
- **`event_id` is a SESSION key** shared by several distinct reports of one visit; it becomes
  `related_event`, and the dedup key is `event_id + event_type` — deduping on `event_id` alone
  loses every report of a session but the last.
- **`petEvent` alone is not a toilet visit** — only `toiletEvent` means the box was used. Code `20`
  is a pet-appeared episode (`petEvent=1`, `toiletEvent=0`, no weight, no cleaning cycle) that the
  app counts under "Pet", never "Toileting".
- **A state report is a FIXED 29-key dump plus 3 optional keys, and absence is the signal.**
  Measured over 1254 real snapshots across both transports: 29 keys in every single one, and only
  `workState` (166), `lightState` (166) and `refreshState` (32) come and go. Those three are sent
  ONLY while the thing they describe is happening and carry no "off" value — so they must be turned
  into a real 0/1 (`state_parsers.PRESENCE_FLAGS`), because `device.state` is merged into and never
  pruned and a key that stops arriving keeps its last value forever. `refreshState` is also an
  OBJECT, and a non-empty dict is truthy, so a binary sensor bound straight to it latches on at the
  first spray and never returns. Gate any such derivation on `SNAPSHOT_MARKER`: reading absence as
  "off" is exactly as wrong as reading presence as "on" if the payload was never going to carry the
  key. Same rule gives `workState` — a default of 0 there is `WORK_MODES[0] == "cleaning"`, which
  had an idle box reporting itself as cleaning 79% of the time.
- **Every MQTT `params` carries the transport envelope with the telemetry** — `XDevice`, `event_id`,
  `timestamp`, `content`, `state` (`ingest.MQTT_ENVELOPE_KEYS`). `XDevice` is the signed request
  credential. Strip it with `telemetry_only()` before anything merges `params` into `device.state`,
  which the panel renders verbatim.
- **`CLOUD_STORAGE` and `CLOUD_DOUBLE` cover the same timespan and must never be joined** — hence
  the stitch episode key `(device_id, related_event, category)`. A stitch deletes its sources, so
  the joined output is verified before anything is removed (`media/stitch.py`).
- **moduleType -> role -> capability**; roles share capabilities, so never assume role == capability
  (`_MODULE_TYPE_TO_CATEGORY` / `CATEGORY_TO_CAPABILITY`, `events/ingest.py`):

  | moduleType | role | capability | folder |
  |---|---|---|---|
  | `CLOUD_STORAGE` | fullVideo | fullVideo | Playback — main stream, ~4s chunks |
  | `CLOUD_DOUBLE` | cloudDouble | fullVideo | Timelapse — ~4x, silent, low-res |
  | `EVENT_VIDEO` | dynamicVideo | dynamicVideo | Clips — the app's "Highlight" |
  | `EVENT_PREVIEW` | eventImage | eventImage | Snapshots — one poster per event |
  | `SHIT_PICTURE` | wasteCheck | eventImage | Waste — the "check waste" gallery |
  | `HEALTH_PRED` | healthPic | eventImage | Health — stool analysis |

- **Never 404 a device.** Unhandled endpoints fall through to `handle_catchall`; firmware reads 4xx
  as a server fault and retries forever. The `/{path:.*}` route stays registered last. Proxy mode
  holds the same line from the far side: an upstream that is unreachable, slow, or that REFUSES
  (a device the real cloud never heard of gets 401 on everything) falls back to the local answer.
- **Proxy mode never hands a device an upstream credential, server address or firmware.** Redaction
  is content-keyed, not endpoint-keyed (`http/redact.py`), so a hostile field is caught on an
  endpoint nobody expected it on. Only *blocked* rules are persisted — the address, MQTT, STS and
  timezone rewrites fire on routine polling, so recording each one would bury the attempts that
  matter. Proxy mode and capture are configured ONLY from the panel; no add-on option, no CLI flag.
- **A heartbeat delivering a command is never forwarded in proxy mode.** `pop_commands` is
  destructive and at-most-once and has already run by the time forwarding could start, so ANY await
  between the pop and the send can lose the command — and `wait_for_heartbeat`, which watches the
  queue drain, then reports it delivered. `handlers/heartbeat.py::carries_commands` is the gate.
- **A device on MQTT STOPS polling the HTTP heartbeat.** Confirmed on a T5: it went quiet over HTTP
  ~40s after its CONNECT and stayed quiet for as long as the session lived. So liveness may never be
  judged on HTTP timestamps alone — `mqtt/auth.py::on_mqtt_packet_received` stamps `last_mqtt` from
  every packet the broker reads, PINGREQ included, and `device_is_stale` counts it. Get this wrong
  and the watchdog calls the healthiest device offline, clears `mqtt_connected`, and routes its
  commands to a queue the device is no longer polling — the failure that needed an add-on restart.
- **`mqtt_connected` picks the transport and the transport has no delivery report.** Publishing to a
  topic with no subscriber raises nothing, so a stale True does not fail — it swallows commands. It
  goes up only on an authenticated CONNECT and comes down three ways:
  `on_broker_client_disconnected` (immediate), the heartbeat's `?iotStatus=0` (backstop for a
  session that ends without the broker noticing), and the offline watchdog (last resort). The
  device's client id carries `timestamp=`, so a returning device is a NEW client, never a take-over
  — which is why the disconnect hook compares `Session` objects instead of trusting the client id.
- **A T5 sends no SUBSCRIBE — the broker subscribes it, or it receives nothing.** Confirmed on
  hardware: a session that authenticated, PINGREQ'd and posted telemetry for minutes held an empty
  subscription list, so every `thing/service/*` publish — ours and every one proxy mode relayed
  down from the real cloud — was accepted by the broker and dropped. `mqtt/auth.py::_server_subscribe`
  adds `topics.downstream_filters` on `CLIENT_CONNECTED`, at QoS 0 (what we publish; a higher value
  could deliver a QoS-1 message this firmware may never ack). The OTA topic is deliberately NOT among
  them. `Device.mqtt_subscriptions` makes it visible, because a publish to a filter nobody holds
  looks exactly like one that was obeyed.
- **A `_reply` travels the opposite way to the topic it answers.** The device acknowledges a
  `thing/service/{name}` on `thing/service/{name}_reply`, so `topics.is_server_published` must not
  claim it — classifying it as ours dropped the only evidence a command ever arrived. (Our own
  `thing/event/{t}/post_reply` never reaches that check: `EVENT_PATTERN` anchors on `/post`.)
- **Entity keys are user state** — renaming an `EntityDef` orphans live entities. HA's silent-
  rejection rules (select labels, `text` max 255, `| default(...)`, `'None'`) are in `ha/discovery.py`.
- **Device input never raises.** Untrusted scalars go through `utils/coerce`, untrusted path
  components through `utils/paths.safe_join` — `http/bucket.py` listens unauthenticated on 0.0.0.0.

## Dev commands

```sh
cd addon && pytest                   # 1206 tests, no device or broker needed
ruff check petkit_local/ tests/      # narrow lint gate; CI runs it too
# The panel's CSS/JS are prettier-formatted (.prettierrc at the repo root).
# CI checks this, so run it before pushing rather than after:
npx prettier@3 --write addon/petkit_local/web/static/{app.js,styles.css}
pytest tests/test_media_stitch.py    # one module
# deploy to a HAOS box — code/Dockerfile only. If config.yaml itself changed, the Supervisor
# caches it by mtime: rsync, `touch` it, `ha supervisor restart`, `ha addons update <addon>`.
rsync -av --delete --exclude='__pycache__' --exclude='*.pyc' \
  addon/ root@<HAOS-HOST>:/addons/petkitlocal/
ssh root@<HAOS-HOST> 'chown -R root:root /addons/petkitlocal && ha addons rebuild local_petkitlocal'
```

**NEVER deploy an untested Dockerfile.** The Supervisor deletes the old image before rebuilding, so
a build that fails leaves NO image: the add-on drops to `state: error` and the devices lose their
local cloud until it is fixed. Build it first with plain `docker build` in `/tmp` on the box, then
rsync. Recovery is restore-known-good, `ha addons rebuild`, then `ha addons start` — rebuild alone
does not restart it.

**`build.yaml` is dead** (removed in Supervisor 2026.04.0) and so is `ARG BUILD_FROM`: the Supervisor
substitutes its own base image, one with no Python, and the build dies with `pip: not found`. The
Dockerfile is the single source of truth now — hardcode `FROM`, and key anything per-arch on
BuildKit's own `TARGETARCH` (which is what the 32-bit-ARM glibc base does).

## Known limitations / unverified

- **MQTT-side, a real T5 has now connected — the transport is confirmed, the semantics are not.**
  Settled on hardware: TLS CONNECT with the `mqtt` patcher applied, `keep_alive=62s`, and an
  HMAC-SHA256 signature that matches ours exactly except that the device sends it in UPPERCASE hex
  (compared case-sensitively it fails every CONNECT, invisibly, until `mqtt_strict_auth` locks the
  device out). `property` events arrive and round-trip. Still unconfirmed: the semantic event types
  (`pet_in`, `clean_over`, …) `mqtt/bridge.py` and `ingest.from_mqtt` dispatch on — a wrong guess
  degrades to `event_kind="other"`. The device offers only RSA and PSK cipher suites, so the broker
  sets `DEFAULT:@SECLEVEL=0` (`mqtt/broker.py`) — Python 3.12's default context drops plain RSA and
  the handshake finds no shared cipher.
- **`mqtt/upstream.py` has now reached the real Aliyun broker, and its TLS is NOT authenticated.**
  The CONNECT is accepted, which confirms port 8883, `securemode=2`, the client-id shape and
  `build_credentials` at once. The endpoint chains to `CN=Aliyun IoT Root CA`, a private root in no
  public store, never sent, with no AIA to fetch it from — so the default context failed every
  connection with CERTIFICATE_VERIFY_FAILED. `build_tls_context` therefore encrypts without
  verifying. The device is in the same position (`/app/bin/ctrl` embeds only GlobalSign Root CA,
  which does not validate this chain, and the T5 rootfs holds no copy of the Aliyun root), so this
  matches the firmware rather than relaxing something it enforces — but anything on the path can
  pose as the cloud and have its commands relayed down. OTA stays blocked and redaction still
  applies, neither resting on server identity.
- **A settings write cannot be verified from telemetry.** The T5's `property/post` carries sensors,
  errors, memory and wifi — no settings at all — and in proxy mode `dev_device_info` is answered by
  the real cloud, not the device. So whether a `property.set` took effect is observable only on the
  box itself. Note the raw `{"suffix","payload"}` panel escape hatch publishes VERBATIM: a command
  sent that way lacks the `method`/`id`/`params` envelope and the firmware has nothing to dispatch
  on. Use the `entity` form, which builds it (`ha/commands.py`).
- **State parsing** is confirmed against real T4/T5 captures; spellings for other codenames come
  from pypetkitapi and localkit. Capture mode (panel: Setup -> Live settings) collects
  what is needed to fix one.
- **Protocol soft spots** (all graded in `events/codes.py`, all visible in the panel's Debug info):
  codes `4`/`13` have no firmware name and are labelled from their work mode; the `key` field the
  RE gives `8`/`17` appears in none of our 68 captures. (`17` is settled: it is the LED
  illuminator, once per recorded episode -- see its note in `events/codes.py`.) `highLight` has no
  observed `moduleType`.
- **The AI chain is settled, and its two `score`s are not the same number.** `dev_discern_config`'s
  `score` (25) is the BODY-DETECTION floor deciding whether an episode opens at all;
  `content.score_info[].score` is a face-match similarity running to 1846. Never compare them —
  that confusion is how the endpoint was misread for a year. `area` (6000) IS a floor on the
  detected bounding box in detector pixels, and both values persist to device flash
  (`user.conf` `other.minArea`). Confirmed in `ctrl`: `get_pet_discern_config_by_network`,
  `get_update_face_score_info`.
- **`score_info[].id` is the pet id we handed out**, copied verbatim from `dev_discern_pic`'s outer
  `list[].id`. It lands in `events.pet_ref`; only `PetRegistry.resolve_pet_ref` promotes it to
  `pet_id`, because a box still holding faces cached from PetKit's cloud reports THAT cloud's id.
  Writing an unresolved ref into `pet_id` fabricates an HA pet device for a row that does not exist.
- **`discernPic` in the state report is a readback**, not a config echo: the `discern[].id` values
  the device downloaded and feature-extracted (features persist in `/system/feature.bin` there). It
  is the only proof a `dev_discern_pic` payload was accepted, and the first thing to check when
  recognition does not work.
- **Camera `still_image_url`** needs the device IP from a state report plus a rooted Ingenic device
  running `tserver`. **Video thumbnails need ffmpeg**; image thumbnails are the original file.
- **The device has no timezone**: `ctrl` takes one from the BLE provisioning payload only, so a
  device provisioned before that field was sent burns UTC into video watermarks until it is
  re-provisioned. **K2/K3 entity definitions assume a WiFi purifier** that does not exist — both
  models are BLE-only today.
