# Changelog

## 0.2.0 — 2026-07-29

First release prepared for a public repository.

### Security

- **The repository could have published your secrets.** `.gitignore` said
  `/data/` — root-anchored, so it matched a repo-root `data/` and NOT
  `petkit-local/data/`, which is the path the README tells you to create. One
  `git add -A` would have committed the TLS private key, the real PetKit/Aliyun
  credentials proxy mode collects, per-device signing secrets, the media AES key
  and every capture.
- **The README told you to post those secrets.** It asked contributors to attach
  `/data/capture/*.jsonl` to issues, with proxy mode on. Captures are verbatim
  and nothing in them is redacted — redaction sanitises what is sent to a
  device, never what is written to disk — so those files hold your Wi-Fi SSID,
  LAN topology, the device signing secret and, in proxy mode, your PetKit
  account credentials. There is now a warning everywhere a capture is offered,
  and the Capture tab tags the four sensitive streams.
- **The unauthenticated HTTPS panel on port 8098 is gone.** It served this
  entire API — device settings, commands, pet records, the event and media
  history, the on-device patchers — to anyone on the LAN, with a self-signed
  certificate and no login, purely so Web Bluetooth had a top-level secure
  context. Provisioning now asks for a certificate you control: serve Home
  Assistant over HTTPS and it works from the sidebar, Ingress included
  (confirmed on hardware). Over plain HTTP the Provision tab says so and links a
  hosted build of the same page. `web_tls_port` and the 8098 port mapping are
  removed; `ensure_self_signed` stays, because the media bucket on 9000 and the
  device-facing MQTT listener on 443 both still need it.
### Removed

Two of these change what appears in Home Assistant. See the note at the end of
this section before upgrading.

- **Four entities that could never hold a value.** Two litter sensors
  (`garbage_bag_state`, `purification_days`) and two feeder switches
  (`feed_tone`, `disturb_mode`) read fields whose names appear nowhere in real
  T5, T6 or D4SH firmware, while every field beside them does. They came from
  the reference integration, which models PetKit's *cloud* API — a different
  vocabulary from the device protocol this add-on speaks. **These entities will
  disappear from Home Assistant** and, on a feeder, so will `surplus_level`'s
  history if it had any.
- **The deodorizer and sound entities are now camera-gated.** `auto_spray`,
  `fixed_time_spray`, `deep_spray` and `volume` on litter boxes, and
  `voice_dispense`/`volume` on feeders, were published to every model but seeded
  only for camera models — and the ESP32 state parser states outright that T3/T4
  "have no camera or spray fields". They move to the camera bundle, so **a T3,
  T4 or non-camera feeder loses entities it could never populate**. Camera
  models are unaffected.
- The Setup tab's "Connected devices" table, which repeated the Devices tab
  verbatim from the same API call, and a stray "On-device AI" card that was a
  heading and a paragraph with no controls.
- `api_device_detail` no longer returns `events`; nothing read it, and it was 60
  event objects per device per refresh.

### Fixed

- **A device could be told about an internal failure with a status code**, which
  the firmware reads as a server fault and retries forever — so a transient
  problem became a permanent request storm. A full disk escaping the bucket's
  narrow exception tuple, an `MqttError` during a Home Assistant broker restart,
  a database error on a read-only disk: each 500'd the device. All are handled,
  and a `never_fail_middleware` backstops the rest.
- **The registry's debounced write could lose a window of changes.** It claimed
  to snapshot before handing work to a thread and did not, so `json.dumps` walked
  dicts that request handlers were still mutating; a resize mid-encode killed the
  writer task silently.
- **Nothing pruned three stores.** Staged uploads whose metadata never arrived,
  the thumbnail cache, and the hub's per-device diagnostics (keyed by an
  unauthenticated request header) all grew forever.
- **No ffmpeg call had a timeout**, so a wedged process on a corrupt clip pinned
  its task indefinitely.
- **A standalone install pointed devices at a hardcoded LAN address** when
  `--api-url` was omitted.

- **Home Assistant `event` entities never fired for any device reporting over
  HTTP.** The handler looked its numeric `event_type` up in a table keyed by
  MQTT *names*, so the lookup always missed. Every ESP32 model, and every
  Ingenic device before the `mqtt` patcher is applied, was affected — Toilet
  Event, Cleaning Event, Error Event and Feeding Event simply never happened.
  Resolution now goes through the code table, which handles both namespaces.
- **Last Clean, Last Visit, Last Feed and Pet Weight never populated on the same
  devices**, for the same reason: they are derived from events, and the
  derivation existed only in the MQTT bridge. It now lives in one place both
  transports call, so they cannot drift apart again. "Cleaning done" is read
  from the code table rather than a literal list, so a deodorizing cycle or the
  LED illuminator no longer counts as the box having been cleaned.
- **Expanding "Diagnostics & raw payloads" no longer collapses a few seconds
  later.** The whole detail pane was rebuilt through `innerHTML` on every
  WebSocket ping, which destroyed the `<details>` element along with its open
  state. Open state is now remembered per device and per section.
- **The `ssh` patcher was broken in a pip-installed copy.** `package-data`
  listed `static/*`, which does not match `static/bin/dropbear-mipsel`, so the
  binary was missing and the patcher raised on opening it. The Docker image
  copies the tree verbatim, which is why the add-on never hit it.
- `patch_ca_bundle` treated an empty or garbled download as "this device has no
  CA bundle" and returned a file containing only our self-signed certificate —
  which, written over `/app/bin/ca.crt`, would have left the device unable to
  verify any other TLS peer. It now refuses.

### Added

- **Patchers check the device before they write.** Each declares how much free
  space it needs and shows it in the UI; each binary patcher verifies the
  downloaded file is a 32-bit little-endian MIPS ELF, and refuses a
  position-independent one — `ctrl` and `cloud` locate their patch points by
  subtracting a fixed load address, so a PIE binary would have been patched at
  the wrong offset **silently**. Free space on `/system` is measured before
  anything is staged, crediting the file about to be overwritten so re-applying
  a patch does not fail on the devices that already have it. Reading a command's
  output back off the device is new (`run_cmd_capture`); it is written to a
  unique file under `/tmp` and served over a second short-lived httpd, so a
  stale or partial result cannot be mistaken for a fresh one. A probe that
  cannot answer warns and continues — unknown is not the same as insufficient.
- **The Devices tab is one expandable panel per device**, all open by default,
  collapse state remembered across reloads. Each panel refreshes on its own, so
  one device's update no longer disturbs another's scroll position, open
  sections or half-typed input.
- **The panel now shows every entity it publishes to Home Assistant.** Schedule
  editors (`text`), event entities, the camera and the last snapshot were all
  published to HA and rendered nowhere; a declared component→card table makes a
  future unrouted component show up as a visible warning instead of vanishing.
  Each panel also has a full entity list, and `entity_category` is used to group
  config and diagnostic entities the way HA does.
- **A timezone picker in Bluetooth provisioning.** The device has no clock
  settings of its own and takes a fixed UTC offset from the provisioning payload
  only — a device provisioned without one stamps UTC onto its video forever. The
  offset was previously taken silently from the browser, which is wrong whenever
  the phone doing the provisioning is not in the device's timezone.
- **The live traffic log can be saved to a file**, in the same format the
  expanded rows show, honouring the heartbeat filter.
- A test that walks every device codename and asserts each published entity has
  something that can actually fill it — a state parser that produces the field, a
  seeded default, or a documented exemption naming its evidence. This is what
  found everything under Removed above, and it fails the next time an entity is
  added without a backing field.

### Changed

- "Sand Saving" and "Sand Lack" are now "Litter Saving" and "Litter Low". The
  entity *keys* are unchanged, so no history is lost.
- Timeline filter chips are one compact group that scrolls rather than wrapping
  onto a second line.
- The live traffic card has a heading, so the Log tab no longer reads as one
  unlabelled block followed by a labelled one.
- The README gains a full feature list and is honest about how well each device
  model is actually verified: T5, T6 and D4SH against real firmware, T4 and T5
  against captures, and everything else inferred from cloud-API clients.

### Device debug-log collection

- **The device's own debug log can now be collected here instead of PetKit.**
  `dev_upload_log_token` was answered "no token" and `dev_upload_log` was an
  acknowledgement of an upload that went nowhere; both are now real. Switched on
  per device (Devices → Debug log collection, off by default), the device is
  handed an STS block pointing at our own bucket, PUTs its `devRun.log` there,
  and the Log tab gains a Device logs section that lists what arrived and greps
  it. Retention defaults to 18 MB / 1 day, sized from the rate measured on
  hardware: once a token is always available the device uploads on *every* poll,
  so every ~5 minutes at 12–234 KB a time — about 36 MB/day. (PetKit's own
  capture showed 5 uploads in 428 polls, which understates it badly; that device
  was mostly being refused a token.) The size cap is what bites; the age cap is
  a backstop for a device that goes quiet.
- The upload URL is the constraint that shaped all of it. `logUpload` builds it
  from one format string, `https://%s.%s%s/%s` — hardcoded scheme,
  virtual-host style, no path-style fallback — so our own address has to be cut
  at a dot and handed over as `bucketName` + `endPoint` for the firmware to
  concatenate back (`split_bucket_authority`). PetKit's two values happen to
  form a public DNS name; ours is a LAN address with a port.
- Two things this needs that are easy to miss, both stated in the UI: the
  `cacert` patcher, because the upload is HTTPS to our self-signed bucket, and a
  bucket address with a dot in it. Neither failure is something the device
  reports — the log simply never arrives — so the panel names which one it is.
- **The log-upload proxy guard is stronger, not weaker.** It still defaults to
  blocking and still never lets the cloud's token reach the device; what changed
  is that with collection on it substitutes *our* token rather than an empty
  result, which additionally denies PetKit the log itself. `dev_upload_log` in
  proxy mode now returns the bare-string result the real cloud sends rather than
  the empty object.
- **`dev_upload_log` is no longer forwarded upstream once the log comes here.**
  That endpoint reports the object URL as a *query parameter*, and redaction
  only sanitises response bodies — so proxy mode was handing PetKit this add-on's
  LAN address and bucket layout in the request while the guard scrubbed the
  reply. Caught on hardware during the first real upload. Keyed on where the
  object actually is, so a device still uploading to PetKit's own OSS reports it
  as before.
- Uploaded logs live under `data_dir`, never in the media tree: `media/pipeline`
  finds raw files by substring match and deletes what it finds, so a `.log` in
  `.raw` could have been consumed by a media job.

- **Which devices do recognition is no longer a guess.** `DEVICE_TYPES_AI` was
  three codenames and a comment admitting it was an assumption. It is now a
  seed: a device also earns the capability the first time it ASKS for
  `dev_discern_config` or `dev_discern_pic`, which firmware without an NPU never
  does. That is the only thing that can settle the feeders — PetKit sells a
  YumShare Solo 2 and Dual-Hopper 2 that do recognition alongside non-"2" models
  that do not, and both generations share one codename (`d4h`/`d4sh`; localkit's
  own gen-2 branch handles the newer as plain `d4sh` and adds no new name).
  Gated on having a camera, since recognition needs something to see with, and
  it only ever turns on: not having polled yet is not evidence of absence.
- **`w7h` (EverSweet Ultra AI) is seeded too** — PetKit's Pet Identification
  screen lists it, and we were hiding the feature from it. `t7` stays despite
  being absent from that same list; nothing suggests it lacks the hardware.
- **Yowling Detection and Urine pH Detection** are exposed as switches, on the
  device page and in Home Assistant. `settings.voice` and `settings.phDetection`
  already existed and nothing read them; a captured `dev_device_info` whose
  values matched the app's own switch positions identified which is which, each
  corroborated by the event field it produces — `petVoice`/`voice_time` on a
  visit summary, `ph_reason` on a cleaning. Those event fields now decode to
  something readable instead of `_raw`; a yowl renders as "12s at 19:42".
  `ph_reason`'s values stay unexplained on purpose: pH detection was off for the
  whole capture, so 5 and 4 are its "not measured" codes.
- The AI / Pets tab names the supported products from the codename table rather
  than a hardcoded string that had already gone stale, and says a device not on
  the list will be recognised when it asks.

## 0.1.7 — pet recognition actually works

Proxy mode paid for itself. 2261 exchanges captured against PetKit's real cloud
show our `dev_discern_pic` and `dev_discern_config` bodies were the wrong shape
in every field, which is why no event was ever attributed to a pet — the
"Pets/AI is broken and known" limitation this project has carried from the
start. A firmware RE pass on `ctrl` confirmed the reading.

- **The AI endpoints now send what the cloud sends.** `dev_discern_config`
  returns `{"result":{"list":{"area":6000,"score":25.0}}}` — the detector's
  thresholds — instead of `{"aiAnalyse":1,"discernPic":1}`, which was two
  *state-report* field names (device → us) reused as config names in the
  opposite direction. `dev_discern_pic` sends integer `id` at both levels
  instead of `petId`/`faceId` strings.
  - This also explains why detection worked at all while the endpoint was
    wrong: the parser bailed on the missing `result.list` and the device kept
    running on thresholds PetKit had already written to its flash.
- **Several mugshots per pet, up to six** — the count the official app's own
  upload grid offers. More angles is the main lever on whether the NPU matches
  anything, so a pet holds a `pet_faces` collection rather than one column. The
  AI/Pets tab shows them as thumbnails; an existing single photo is migrated on
  first start.
- **The Timeline says which cat.** A card carried a bare `pet_id` that nothing
  resolved to a name. It now shows the pet with its photo, including on
  "appeared" episodes, where the recognition arrives on a *sub-event* (code 24)
  that can never head a card.
- **Two identities, kept apart.** `content.score_info[].id` lands in a new
  `events.pet_ref` verbatim; only a value that resolves to a real pet becomes
  `pet_id`. A box still matching against faces cached from PetKit's cloud
  reports that cloud's id, and writing it straight into `pet_id` would fabricate
  a Home Assistant pet device for a row that does not exist. Those ids are
  offered in the Pets tab for binding — never guessed — and binding one
  attributes its past events in place.
- **Nothing filters on the recognition score.** `dev_discern_config`'s `score`
  is the body-detection floor that decides whether an episode opens;
  `score_info[].score` is a face-match similarity running to 1846. They are
  different quantities, and comparing them is how the endpoint got misread.

### Fidelity fixes from the same capture

- `dev_serverinfo` `nextTick` 30 → **3600**, the cloud's value, cutting ~2800
  requests a day. `dev_ota_check` returns `{}`, an **object** — the array was
  documented as "the real cloud's shape" and was not. `dev_schedule_get` gets
  distinct row ids and an ISO-8601 `updatedAt` that no longer claims the
  schedule changed on every poll. `dev_signup` gains the six fields the cloud
  sends; `signupAt`/`createdAt` stay, because the capture is of an already
  registered device and cannot speak to what a first signup needs.
  `dev_upload_log` is answered `{"result": "success"}` instead of falling
  through to the catch-all.
- `dev_state_report`'s `interval` deliberately stays 30 where the cloud says
  3600: it is how often an idle device pushes the state every HA sensor reads.
- **Settings added in a later version are backfilled.** `setdefault` only fired
  when the whole block was absent, so a device registered by an older build
  never gained a new key — the reference T5 was short ~25 of them.
- **Proxy mode no longer lets the cloud rewrite the device's timezone.** It rode
  in on `dev_device_info` and the device adopted it (`Etc/UTC` over local),
  which is what burns UTC into video watermarks.

## 0.1.6 — proxy mode as an observation tool

Proxy mode used to forward exactly two things: paths we don't implement, and
heartbeats with nothing queued. Every endpoint the firmware actually exercises
was answered locally, so the mode you'd turn on to learn what the real cloud
sends never showed you any of it. It is now the reverse-engineering instrument
it was supposed to be.

- **Everything is forwarded, and the device gets the cloud's answer.** Proxying
  moved out of two `if config.get("proxy_mode")` branches and into a middleware
  wrapping the whole route table, so no handler knows the mode exists. Our own
  handler still runs first and in full — the event store, the HA entities and
  the media pipeline keep working while a device is being watched.
- **A redaction layer decides what may reach the device** (`http/redact.py`),
  keyed on the SHAPE of a decoded reply rather than on a list of safe endpoints,
  so a hostile field is caught wherever it turns up. It removes shell commands
  and firmware pushes, and substitutes our own values for `apiServers`/`dns`,
  the MQTT host and credential trio, the STS bucket block, and a `secret` — each
  of which would otherwise hand the device back to PetKit, quietly.
  - The old `run_cmd` filter only looked inside `result[]` when it was a list,
    only decoded a `content` that was a JSON *string*, and raised on a list of
    non-dicts. The new walker descends the whole structure, including JSON
    encoded as a string, and re-encodes it in place.
- **Blocked attempts are kept; routine substitutions are not.** A shell command
  or a firmware push goes to a new `blocked_attempts` table and the Setup tab. An
  `apiServers` rewrite does not — `dev_serverinfo` is polled every 30s, so that
  would be thousands of rows a day burying the handful that matter. Nor does a
  `secret` substitution, tempting though it looks: every ordinary `dev_signup`
  and `dev_device_info` reply carries one, so recording it would both bury the
  table and put the device's real PetKit credential in something the panel
  serves. Those are counters plus a line in the Log tab.
  - The firmware-shape heuristic is deliberately narrow, because a false
    positive DELETES a working payload: `dev_discern_pic` sends a `url` per face
    and a media listing sends `url`+`size`. A generic URL now has to point at
    something actually packaged as an image before it counts.
- **A heartbeat that is delivering a command is never forwarded at all.**
  Building that reply already drained the device's command queue (at-most-once,
  by design, and there is no way to put a command back), so any await between
  the pop and the send is a window where a cancelled request, a slow upstream or
  an exception loses it for good — while `wait_for_heartbeat`, which watches the
  queue drain, reports success. It now goes straight out. Heartbeats are ~15s
  apart and almost always idle, so the cloud's own commands still get through.
- **Upstream is selectable** — `auto`, `petkit-eu`, `petkit-global`, `petkit-cn`,
  or your own URL, validated when saved.
- **Failure never reaches the device.** An unreachable or slow upstream falls
  back to our own answer instead of a 502 (firmware reads one as a server fault
  and retries forever), and so does a reachable one that REFUSES: a device whose
  serial the real cloud does not know gets 401 on every endpoint, and relaying
  that would break the never-404 rule from the far side. The refusal is still
  recorded — observing it is the point, showing it to the device is not. The
  timeout is down to 8s now that every call waits on it, a run of failures trips
  a breaker that stops dialling for a minute, and anything that goes wrong in
  forwarding or redaction answers locally rather than becoming a 500.
- **An unidentified request is never forwarded** — with no registered device
  there is nothing to substitute into the reply.
- **Media keeps landing locally** by default; a **Media → real OSS** toggle sends
  the device to PetKit's bucket when you want to watch the real upload path. The
  real STS payload is recorded either way.
- **MQTT is bridged to the real Aliyun broker** (`mqtt/upstream.py`). The
  credentials a device uses are minted by us, so the real ones can only be
  learned by proxying `dev_iot_device_info` — captured there and reused to
  connect. Frames are re-addressed in both directions, the upward path is an
  allow-list (the bridge's `#` subscription hears its own echo), and an
  `/ota/device/upgrade/` frame is blocked and recorded rather than relayed.
  `parse_topic` now recognises that topic at all; it used to be dropped silently.
  **None of the MQTT half has met a real device.**
- **Capture gained a proxy stream** — `proxy_http.jsonl` (both bodies side by
  side, unlike `requests.jsonl`, which records none), `proxy_redactions.jsonl`
  and `proxy_mqtt.jsonl`, written only when capture and proxy are both on.
- **MQTT capture follows the panel toggle.** It was frozen into the bridge at
  construction, so flipping capture in the UI started HTTP capture immediately
  and MQTT capture never — until a restart.
- The catch-all's "Unhandled: …" warning is unconditional again. It was
  suppressed in proxy mode, which is exactly the mode you use to find new
  endpoints.

**Breaking:** the `capture`, `proxy` and `proxy_upstream` add-on options and the
`--capture`, `--proxy`, `--proxy-upstream` and `--no-block-rce` flags are gone.
All of it lives in the panel's **Setup → Live settings** now, which is where you
want it for something you switch on mid-session. An install with `proxy: true`
saved in its options will lose that value when the Supervisor re-validates the
schema — turn it back on in the panel, which persists it to
`/data/settings_overrides.json`.

### timeline: processing state + clip previews

- **Video no longer shows as a fragment while it's still being assembled.**
  A visit's long recording arrives as many ~4s chunks that get stitched into
  one clip; until that's done the timeline now shows a "Video processing…"
  placeholder (or the still with a badge) instead of playing a lone 4-second
  fragment. The card auto-refreshes to the real clip when stitching finishes
  (the stitcher emits a WebSocket event).
- **Thumbnails autoplay the event clip, not the timelapse** — the short
  `dynamicVideo` clip is a complete single file (a real preview), whereas the
  timelapse is chunked; the timelapse is used only as a fallback once stitched.
- The single-file roles (clip, poster, waste photos) still appear immediately;
  only the chunked recordings wait for stitching.

### event-code completeness, filenames, readable timeline

Cross-checked event codes against pypetkitapi, localkit, **ha_petkit_clone**, and a
**T5 firmware dump**; results in CLAUDE.md.

- **All 6 device moduleTypes are now mapped** — added `HEALTH_PRED` (the T5's
  stool-health-analysis photos) → a "Health" folder + timeline gallery. The
  firmware string tables confirm this is the complete set, so nothing lands
  in an uncategorised "Other" folder any more.
- **Rich cleaning labels** — decoded from the `result`/`start_reason`/`err`
  sub-fields (grounded in ha_petkit_clone's mapping, applied to our namespace):
  e.g. "Auto cleaning completed", "Manual cleaning canceled", "… failed — bin
  full". Applied only to completion events, so a cycle shows one clear
  "cleaning done" line instead of three identical ones.
- Cross-referenced cloud-API codes **6 (litter empty)** and **7 (reset)** are
  mapped low-confidence so they'd read sensibly if the device ever sends them.
- **Fixed nonsensical waste-photo filenames** (`(3 of 4)`, `(4 of 4)`, …): the
  total was the count-so-far at upload time, wrong for every photo but the
  last. Filenames now carry a plain index; the true "n of m" is shown in the
  viewer, computed from the actual group.
- **Timeline UI pass**: preserves aspect ratio (no more cropped fisheye —
  `object-fit: contain`), clearer card header with a kind chip and summary,
  low-level steps collapsed behind a quiet "show N more steps" expander.
- **GIF-like preview thumbnails**: the timelapse clip autoplays (muted,
  looping) as the card thumbnail — **no re-encoding**, the browser just plays
  the existing mp4 — and only while scrolled into view (IntersectionObserver).

### pet "appeared" events, malformed-JSON tolerance

- **Decoded event types 20 and 24**, which showed as bare "Event 20"/"Event 24"
  rows. `20` is a pet episode with **no toilet usage** — the app's
  "<pet> appeared" — and `24` is the recognition result that closes it. They
  now form a single "Appeared" card carrying its clip.
- **`petEvent` no longer implies a toilet visit.** Only `toiletEvent` means the
  box was used; an "appeared" episode carries `petEvent=1`/`toiletEvent=0`
  throughout, so the old reading mislabelled both the event kind and the
  media filenames (a pet-detection clip was saved as "Toilet visit").
- **The device emits invalid JSON** for type 24 (`"related_event":3_3002...`,
  unquoted): `json.loads` failed and the entire content — including the parent
  link and the pet score — was silently dropped. Now repaired and re-parsed,
  and only trusted if the repair yields valid JSON.
- Timeline filter chips are now disjoint like the app's: "Pet" counts appeared
  episodes, "Toileting" counts real visits.
- `cloudDouble` renamed **Timelapse** — measurement shows it packs ~1s of
  footage per 4s of wall clock (~4x), so it is a time-lapse of the same span,
  not a low-res mirror. It looking "sped up" is inherent to the stream.
- Chunks now merge sooner (quiet window 180s→90s, sweep 120s→60s), shrinking
  the window where the media folder shows individual ~4s chunks.

### timeline layout + HA entity corrections

- **The "Check waste" gallery was missing entirely.** `SHIT_PICTURE` (~5 photos
  per cleaning) wasn't in the moduleType map, so it fell through to an
  uncategorised "Other" folder under one colliding filename. `EVENT_PREVIEW` —
  a single poster image — had been standing in for it.
- **Media no longer mixes between events.** A cleaning cycle's recording and
  waste photos stay with the cleaning and render on its "Cleaning done" line;
  the visit card shows only the visit's own media, as in the official app.
- **Highlight ⇄ Playback toggle now works.** The short clip the app calls
  "Highlight" is `EVENT_VIDEO` (filed by the device under the `dynamicVideo`
  capability); no `highLight` moduleType is ever sent, so the toggle had
  nothing to switch to.
- Low-level cleaning steps (mechanism, cycle-start, weight samples) are
  collapsed behind a "more steps" expander instead of listed as events.
- Media *roles* are now distinct from STS *capabilities* — several roles share
  one capability, so the capability gate and retention resolve through
  `CATEGORY_TO_CAPABILITY` rather than assuming they're the same thing.
- Unknown `moduleType`/`event_type` values now log a warning once each; silent
  degradation is what hid the waste gallery in the first place.
- **Home Assistant fixes** (all were breaking entities, found in `ha core logs`):
  `select` entities published the raw device value instead of the option label,
  so every one of them errored and never tracked; `text` entities declared
  `max: 2048` which makes HA reject the whole discovery message, so the
  schedule editors never existed; templates now default missing keys instead of
  warning on every publish; timestamp sensors render `None` rather than an
  empty payload.
- Generated media names are URL-safe (no `#`) — HA's media browser builds its
  URL without escaping, so the old `(T5 #10000001)` folder truncated at the
  fragment and preview never worked.

### real-device corrections (T5 capture, 2026-07-22)

Everything below was found by capturing a real T5 (firmware 943) rather than
inferred. See CLAUDE.md for the confirmed protocol details.

- **Events were being lost.** `dev_event_report`'s top-level `event_id` is a
  *session* key shared by several distinct reports, not a per-report id —
  deduping on it alone meant each later report in a visit silently overwrote
  the earlier one (6 real reports collapsed to 3 rows). The dedup key is now
  `event_id + event_type`, and `event_id` groups the session.
- `event_type` on `dev_event_report` is a **numeric code**, not a semantic
  name; codes are mapped (incl. "5" = cleaning done + waste report, which used
  to render as a stray "Event 5" card) and shown with readable labels.
- Cleaning cycles now attach to their visit via the device's own
  `content.relate_event` link instead of timestamp proximity.
- **`CLOUD_DOUBLE` is a separate low-res substream** (528×528, silent), not
  part of the main recording — mapping both to `fullVideo` mixed two
  incompatible streams into one folder. It gets its own category/folder.
  There is no `cycleType` field at all; category comes from `moduleType`.
- **Video chunk stitching** (`media/stitch.py`): a visit is uploaded as many
  ~4s chunks, now joined into one continuous clip (lossless `-c copy`) once
  the episode goes quiet. Sources are only deleted after the join is verified
  (stream present, plausible duration, full `-xerror` decode); mismatched or
  undecodable chunks are excluded and kept rather than sinking the episode.
- **Fixed media corruption at the source**: concurrent uploads could compute
  the same friendly filename and two writers would interleave into one file
  (observed as an MP4 containing two moov atoms, which broke playback and
  stitching). Names are now claimed atomically (`O_CREAT | O_EXCL`).
- **Thumbnails/videos never loaded in the browser**: `encodeURI` leaves `#`
  unescaped and the device folder name contains one, so the request was
  truncated at the fragment. Paths are now encoded per segment.
- Timeline refreshes when the WebSocket reports new media/events, instead of
  showing a permanently blank thumbnail for a file that wasn't ready yet.
- Startup migrations repair databases written by the earlier versions
  (adds `parent_event`/`stitch_state`, re-derives `event_kind`/category).

### media, events, timeline, retention, capabilities & on-device AI

Turns the raw `cloud`-process uploads (working since 0.1.3-era bucket support)
into a full, cloud-free replacement for the official app's media/events/AI
features.

- **Media pipeline** (`media/`): raw uploads land in a hidden `.raw` staging
  dir (out of the HA media browser); `dev_upload_file_info_v2` triggers
  AES-128-CBC decrypt (magic-byte verified, falls back to the raw file on a
  bad key/IV guess) + ffmpeg stream-copy remux (`.ts`→`.mp4`, degrades to
  `.ts` if ffmpeg is unavailable) + a move into a friendly, playable tree:
  `/media/petkit/{Device}/{Playback,Highlight,Waste,Clips}/YYYY-MM-DD/...`.
- **Persistent event store** (`events/`): SQLite (`events`/`media`/`pets`
  tables) fed by both transports — `dev_event_report` (HTTP, always present)
  and MQTT `thing/event/*` — via shared normalizers in `events/ingest.py`,
  paired with media by `related_event`. Visit **sessions** (toilet visit +
  nearby cleaning/deodorizing sub-events + waste photos) are grouped at query
  time, not stored pre-grouped.
- **Retention** (`media/retention.py`): background sweeper enforces
  per-capability size + age caps on media (oldest-first) and an age cap on
  events; configurable from the panel (Setup tab) or `GET/POST /api/retention`.
- **Capabilities**: the STS `capability[]` array (`fullVideo`/`eventImage`/
  `highLight`/`dynamicVideo`) is now per-device *and* toggleable — turning one
  off drops it from the next `dev_oss_sts_info_new_v2` response, so the device
  stops uploading that type at the source. Exposed as HA switches and a panel
  "Media Capabilities" card.
- **Timeline tab** (panel): per-day feed of visit session cards (pet, duration,
  weight, Highlight⇄Playback toggle, waste photo carousel, nested sub-events),
  with filter chips (All/Pet/Toileting/Health Alert) and counts.
- **HA**: momentary `event` entities now fire from HTTP too (previously
  MQTT-only); new per-device **Last Snapshot** (`image`, raw bytes over MQTT)
  and **Last Clip** (`sensor`) entities, updated as media becomes ready.
- **On-device AI**: `dev_discern_pic`/`dev_discern_config` now serve real pet
  face photos (NPU camera litters only — T5/T6/T7) instead of empty stubs;
  panel "AI / Pets" tab for pet management + face photo upload; per-pet HA
  virtual devices (Last Visit, Visits Today, Last Visit Weight/Duration, Last
  Device Used) once a device attributes an event to a pet.
- Packaging: `ffmpeg` added to the Docker image (stream-copy only — small,
  no re-encode cost).

## 0.1.3 — Bluetooth provisioning

- **Web Bluetooth device provisioning** in the panel (Provision tab): pairs the
  PetKit device over BLE (GATT service `aaa0`, write `aaa2`, notify `aaa1`) and
  sends `{"key":151,"payload":{"ssid","pwd","apiServers":[...]}}` — no CLI/root
  needed. Feature-detects Chrome/Edge + secure context and guides the user.
- The panel is also served over **HTTPS** (self-signed, port 8098) so Web
  Bluetooth has a secure top-level context outside the HA Ingress iframe.
- Runs on a plain `python:alpine` base (no s6/bashio); self-configures from
  `/data/options.json` + the Supervisor MQTT service.

### web panel

- **HA Ingress web panel** (`web/`) — a dependency-free SPA in the HA sidebar:
  device list + online status, live HTTP/MQTT log (WebSocket), per-device
  raw+parsed state, a **manual command sender** (fire `thing/service/*`
  envelopes to verify action codes/transport on a real device), a **capture
  browser/downloader**, and a setup/health page (connection values, cert
  status, observed MQTT connection incl. clientId/username/signmethod).
- Device-facing ports simplified: MQTT plain listener is internal-only (no
  host clash with Mosquitto); TLS on `mqtt_tls_port` (default 443, configurable
  — the device's actual MQTT port is unverified, so it's a knob not an
  assumption); `mqtt_tls` on by default. Self-signed cert auto-generated.

### reference cross-check hardening

Cross-checked against dwyschka/localkit (+ real device capture) and
Jezza34000/pypetkitapi; fixed the divergences that would break a real device:

- **Connect layer:** device-facing MQTT **TLS** listener (Aliyun securemode=2,
  self-signed cert auto-generated); auth now selects the digest from
  `signmethod` and is **accept-all by default** (like the reference broker),
  with an optional strict mode; ESP32 `dev_iot_device_info` now returns the
  **flat** credential block (Ingenic `dev_only_*` stays `ali`-wrapped);
  `serverinfo.dns` is an array.
- **Commands:** corrected all litter **action codes** (LBCommand) — several were
  scrambled (Reset N60 had triggered maintenance mode); real-time control now
  goes over MQTT `thing/service/{start,end,feed_realtime,property/set}` instead
  of the heartbeat queue (heartbeat kept as fallback).
- **State fields:** fixed field names — litter `workState.workMode`, fountain
  `lackWarning`/`heatRealTemp`/`drinkTime`, purifier `temp`; pet weight now read
  from the `pet_out` event content.
- **W5 BLE:** correct decoder — real cmd-230 byte layout, `payload[0].data`
  urldecode→base64 path, cmd gating — plus the `ServiceConnect` poll that makes
  the parent relay W5 frames at all.
- **MQTT `user/get`:** answer `data_get` requests (device_info / multi_config /
  serverinfo / schedule / feed / ble).
- **Fidelity:** `multi_config` values are JSON-encoded strings; `ota_check` /
  `sound_get` / `attire_over` return arrays.

## 0.1.0

Initial release.

- HTTP API server impersonating the PetKit cloud (signup, iot device info,
  serverinfo, state report, heartbeat, OTA, OSS/STS, schedules, feed, BLE list).
- Embedded MQTT broker (amqtt) with Aliyun IoT HMAC-SHA256 authentication.
- MQTT bridge: device events → HA state; HA commands → device.
- HA MQTT discovery for litter boxes, feeders, water fountains, purifiers and
  BLE accessories (K3, W5), including sensors, binary sensors, switches, buttons,
  numbers, selects, camera, **event** and schedule **text** entities.
- Per-entity command topics so switches/numbers/selects/schedules are routable;
  settings pushed to the device via Aliyun `property.set` with optimistic HA
  state; actions delivered via the heartbeat queue.
- Offline detection watchdog (stale devices → unavailable in HA).
- Device-originated setting changes synced back into HA controls.
- Pet-weight and last-clean/last-visit/last-feed timestamp sensors.
- Capture mode (`capture: true`) — raw state reports + MQTT frames to
  `/data/capture/*.jsonl` for parser tuning.
- W5 BLE response parser (structured payloads; provisional binary frame layout).
- Proxy mode with automatic `run_cmd` RCE blocking.
- Supervisor MQTT service integration; single-container add-on packaging.
