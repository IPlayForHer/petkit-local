# Changelog

## 1.8.2 — 2026-08-08

### The empty `dev_ble_device` answer goes back to omitting `list`

1.8.1 started sending `list: []` to a device with no accessories paired, on the
grounds that PetKit's own cloud does. Owners have since reported that empty
array crashing devices, so it is out again: with nothing paired the reply
carries `nextTick` and no `list` key, which is the shape that ran for months
without the complaint.

The argument 1.8.1 made was from analogy — the cloud sends the empty array 234
times in one capture, therefore it cannot be what breaks a device — and the
field beat it. What is still not known is which models are affected or why the
cloud gets away with it; that needs a capture from someone it happens to, and
until then the code says so rather than claiming more.

`nextTick` stays in both shapes and is not implicated in any of this. It is the
half of 1.8.1 that fixed something real: without it, a parent with nothing
paired was told neither what to scan for nor when to ask again.

Both transports changed together. The HTTP handler and the MQTT `data_get`
answer the same question and have drifted apart once already.

## 1.8.1 — 2026-08-08

### `dev_ble_device` now answers exactly as PetKit does

Comparing our reply against a capture of the real cloud (issue #6) turned up two
differences.

With nothing paired we sent `{"result": {}}`, where PetKit sends
`{"result": {"list": [], "nextTick": 3600}}`. Omitting `list` rested on one
firmware log line — an empty array producing `ERR:...parse item NULL`, read as a
null dereference that aborts the boot chain — and that reading did not survive
its own evidence: the same capture has PetKit answering the empty array 234
times in one session, so every unaccessorised device receives it routinely.

It was not free, either. The omission took `nextTick` with it, so a device with
nothing paired was told neither what to scan for nor when to ask again. Nobody
decided that half; it fell out of a shared empty-response helper.

The accessory MAC is canonicalised where it is stored rather than by each
caller. Both existing callers did normalise, so nothing was broken — but a third
that forgot would have put `aa:bb:cc:dd:ee:01` on the wire where the cloud sends
`aabbccddee01`, and every lookup here would have carried on working, because
those compare canonical forms. The device would have been the only thing to
notice, by never finding the accessory.

## 1.8.0 — 2026-08-08

### The API is published on port 80 now — read this before updating

An ESP32 model provisioned with any other port gets onto Wi-Fi and then fails at
the server connection, tested repeatedly across two devices by @strxno, and one
pointed here by a DNS redirect dials 80 with nowhere to tell it otherwise. The
add-on publishes on host 80, and the compose example maps `80:8080`. Inside the
container nothing moved.

The auto-detected `api_url` moves with it, which is the same change and not a
second one: left at `:8080` the add-on would advertise a port it no longer
publishes. An explicit `api_url` is still honoured verbatim, and Home Assistant
keeps a port override set in Network across updates.

**Anyone already provisioned on `:8080` has that port burnt into the device**
and needs re-provisioning, or the old mapping set back by hand in Network.

### Ask PetKit for what only PetKit knows

An accessory's pairing secret and a pet's reference photos exist in one place —
the account — and until now the only way to get either was to read it off the
hardware or retype it from the app. Two buttons now ask for them directly: one
on a device's BLE card, one on the AI / Pets tab.

The request is signed the way the firmware signs its own. T4 firmware 1.652
carries both halves of it as adjacent format strings —
`id%snonce%stimestamp%utype%s%s` hashed, `id=%s&nonce=%s&timestamp=%u&type=%s&sign=%s`
sent — so this reproduces the header rather than guessing at it. Confirmed
against the real cloud: `dev_ble_device` and `dev_device_info` both answered
200 to a request built here, eleven seconds before the device asked for the
same two and got the same answer.

Two details that are easy to get wrong. The `type` field is hashed, so `T5` and
`t5` are different requests — the device's own spelling is recorded from live
traffic and persisted, because a restart that lost it would sign the next fetch
with our lowercase codename and be refused. And PetKit answers `704` when the
credential is one we issued rather than one it knows, which the panel says in
those words instead of reporting a generic failure.

Nothing is fetched on a schedule. This runs when a button is pressed and at no
other time — the add-on does not poll PetKit, and must not start.

A pet imports under a new local id with PetKit's own id bound to it as an
alias, because that foreign id is exactly what a box still matching against
cloud-cached faces reports back. Binding it names the history already recorded
under it, retroactively. Names are in no payload a device receives, so an
imported pet arrives as `PetKit pet <id>` — click the name on its card to
change it, which was not possible here before at all.

### A litter box can finally be told about its spray

`dev_k3_device_info` had no route: it fell through to the catch-all, and a T4
asking what its Pura Air is configured as was answered `{}`, forever
(issue #17). The reply now carries what we actually know, in the field set T4
firmware 1.652 parses by name — identity, whatever readings the spray has
reported, and its settings when a real value exists. Every key in that parser is
looked up individually, so an absent one is skipped rather than read as zero;
that is what makes it safe to send only what we have and invent nothing.

`settings.k3Config` used to go out as an empty object against six keys the
firmware reads by name. It now carries them.

`relateT4` is deliberately still absent. Its name and its `%d` admit two
readings — the parent's id, or a 0/1 flag — and the wrong one lands on the
firmware's `diff ID` path.

The reboot half of that issue is not addressed.

### Bluetooth accessories, from @strxno's hardware

- **A write opens the session it needs.** Published on its own,
  `thing/service/ble` is accepted by the parent, forwarded, and does nothing.
  The same 221 frame is acknowledged with a session held open and ignored in
  silence without one, and from here those two look identical.
- **The session is held open, and hung up only on a real reading.**
  `thing/service/connect` carries a `time` field; without it the parent lets the
  radio go before the accessory has said anything worth having. We also hung up
  on ANY reply, including the short 251/252 that precedes a CTW3's run-info
  pass — which is most of why a CTW3 was so hard to get anything out of.
- **A parent is told its accessory list changed.** `dev_ble_device` answers
  `nextTick: 3600` and the parent honours it, so pairing left the device that is
  meant to scan knowing nothing for up to an hour — while the poll pushed
  `connect` for a MAC it had never been told about, which fails looking exactly
  like a wrong scan type. `ble_relay_update` is the trigger, confirmed on a T5.
- **A CTW3 answers cmd 211 over the relay**, though it is silent to a direct
  GATT client on firmware 111. The reply also settles the byte order by
  write-and-read-back: "light off" moved byte 6 and left byte 7 alone.
- **A fountain that is switched off no longer forgets its mode.** A W4, W5, W4X
  or CTW2 reports mode 0 while powered off; that is not a mode, and storing it
  cost the last real one — so switching the fountain back on silently made a
  smart-mode fountain a normal-mode one.

### Provisioning

- The Bluetooth characteristics are found by property when the expected UUIDs
  are not there, and a failure now lists what the device actually exposed
  instead of giving up quietly.
- BLUFI `0x0f` and `0x12` are decoded again, read-only. Neither decides
  anything — the PetKit keys inside custom data drive provisioning — but a
  device that fails at the BLUFI layer says so in one of them, and undecoded
  that arrived as "ignored ESP32 packet subtype 0x12".

### Also

- The patchers work on Axera ARM boards, which keep the writable boot override
  under `/opt` where Ingenic boards use `/system`. Probed rather than decided by
  codename, because D4SH and D4H ship as both.
- The bucket endpoint can be set for a standalone Docker run.

## 1.7.0 — 2026-08-03

### An ESP32 device was being provisioned onto PetKit's cloud

A T4 came up online, visible in PetKit's own app, having never once called this
add-on. The Bluetooth log said it had connected to a server, and it had — just
not to ours.

BLUFI can provision Wi-Fi by itself: set the mode, hand it the SSID and the
password, tell it to connect. This did all of that, and sent PetKit's own
document with the server address alongside as an extra. So the ESP's BLUFI
layer joined the network on its own, the firmware's handler for that document
never ran, and the device carried on with the server list it already had.

PetKit's app sends no native Wi-Fi frames at all — `PetkitBLEManager` has one
outbound call in it — and the SSID and password travel inside the same JSON as
everything else, so the firmware does the joining itself *after* reading where
to phone home. This now does the same. A device that ignores the document will
fail to join, which is loud, rather than join somebody else, which is silent.

### The log-upload guard also stops the device reporting what it recorded

`dev_upload_file_info_v2` is how a device says what it just uploaded: the file
id, the module type, the AES IV, the event it belongs to and the
pet/clean/toilet flags. Proxied, that is a running account of what happened in
somebody's home — every visit, every clip, timestamped — sent to PetKit by a
device its owner has taken off PetKit. The media itself never gets there, which
makes the metadata the whole of what they would learn.

Redaction could not cover it: that rewrites response bodies, and by the time
there is a body the request has been delivered. So it is withheld on the way
out, the same way a log upload naming our own bucket already was. Switching the
guard off proxies it again — it is a guard, not a permanent exemption.

### PetKit's own app, as a source

The provisioning payload and the CTW3 settings block were both settled by
decompiling PetKit's Android app (13.8.1, `com.petkit.android`). Nothing from it
is in this repo — only what the protocol is.

- **`locale` is a time ZONE name, not a language.** The app fills it with
  `TimeZone.getDefault().getID()` — `Europe/Amsterdam`, `America/New_York` —
  right beside the numeric offset, and a captured D4 signup body echoes exactly
  that back. This sent `navigator.language`, so devices were being told their
  zone was called "en-US".
- **The CTW3 settings block is twelve bytes, in the order this already read
  it.** 1.6.0 reordered three of them for the write, following a third-party
  capture, and that was wrong: the app writes lamp switch, brightness,
  do-not-disturb, child lock at bytes 6-9, exactly as the status tail reads.
  Bytes 10 and 11 are two more switches nobody had named — the smart and
  battery inductive sensors — and they are decoded and restated now.
- **Filter reset carries no payload.** The app sends cmd 222 empty; 1.6.1 sent
  a single zero byte.
- **Choosing a flow mode sends power on and pump un-paused**, both fixed at 1.
  1.6.0 derived the pause byte from the mode, which the app does not do.
- **The join report now names what went wrong.** Its ten states come from the
  app's own per-state log lines, including the four failures it had none of:
  a wrong Wi-Fi password used to render as "state 3" and the panel kept polling
  for another twenty-four seconds. State **9 is "connecting to MQTT"** and
  **10 is "online"** — an ESP32 device cannot reach either against this add-on,
  because the TLS bypass it would need has no ESP32 patcher, so it settles on
  the HTTP heartbeat. Stopping at 7 is therefore not a failure.
- The transport split is confirmed to be by model, and it is the same list this
  already calls next-gen: T5, D4SH, D4H, T6, T7, T7 Lite and W7H take PetKit's
  own GATT profile, everything else BLUFI. The JSON document is identical on
  both; only the framing differs.

### Camera feeders had no stream URL, and no patchers either

A D4H or D4SH reports its LAN address in the same free-form string a litter box
does, and the feeder parser was the one that dropped it. Nothing downstream said
so: go2rtc quietly skips a device with no address, and the Patchers tab reports
the whole device as unsupported. Found and fixed by **@nklmilojevic** (PR #12),
confirmed on a D4H.

The extraction now lives in one place for all three parsers — the litter one
knew only the flat key, the MQTT one only the string — and it checks what it
matched. The old pattern accepted `....` as readily as an address, and this
value becomes a go2rtc source and an SSH target.

### A device is told back the timezone it reported

Its signup body carries `timezone` and `locale`, and both were read off the wire
and dropped, so the reply came back with the SERVER's offset and an empty
locale. A device that had just said it was at -4.0 was answered 2.0. The device
is the authority on where it is; a manual override still wins over both.

### The panel can tell you when you are looking at an old copy of it

A 1.6.1 install reported a Bluetooth failure whose log was, word for word, the
output from before the fix — the browser was still running the previous
`app.js`. The server was fine. Nothing anywhere said so, and the only way to
establish it was to compare log strings against the source.

Assets are already versioned by a hash of their content, which defeats a stale
asset. It cannot defeat a stale *document*: `?v=<hash>` only reaches the
browser inside the markup that carries it, so a cached index asks for the old
asset URL and every cache answers it correctly. The index now says `no-cache`
itself instead of getting the header from a match on its path — behind Home
Assistant Ingress the panel is mounted under an opaque prefix, and how that
request arrives was never ours to decide.

And the page now knows which build it is. The stamp travels in the document,
`/api/info` answers the same value live, and a difference between them can only
mean the page is old — so the panel says so, at the top, with a reload button.
The version in **Setup** does not answer this: it comes from the server, so a
fresh server behind a stale page reports the new number while running the old
code.

## 1.6.1 — 2026-08-03

Bluetooth provisioning, from three device reports. The short version: the panel
was writing in one dialect and reading in another, and where a device did
answer, the answer was thrown away.

### Which way a device wants to be written to is now asked

A Purobot Ultra takes a framed envelope — `FA FC FD 46 | type | seq | len |
json | crc16 | FB` — and ignores anything else. A YumShare Solo takes bare JSON
with response, ignores a framed write in silence, and drops the first write
after a connect. The two are mirror images, so no single hardcoded direction
could ever serve both.

The panel now probes with `key 110`, uses whichever framing the device answered
in, and runs the real handshake: credentials, then the device's own join
report, rather than a fixed wait. Contributed by **@nklmilojevic**, verified on
a D4H (fw 867), on top of the protocol **@strxno** reverse-engineered and
verified on a T6 (fw 951). Both models are confirmed working.

Both join states count as joined: the T6 goes `0 → 1 → 6 → 10` and never
reports 7, the D4H stops at 7. Waiting on either alone hangs on half the
models.

### A Pura Max was answering, and was told it had not

A T4 replied three times, the log printed `type 1 subtype 0x13`, and the panel
said the device never answered. `0x13` is BLUFI's **custom data** — the channel
PetKit's own document travels on, the one this sends the credentials over — and
the only replies being read were BLUFI's Wi-Fi report and its error report. The
device was answering in PetKit's protocol, inside BLUFI, and it was discarded.

Custom data is decoded now, reassembled across fragments (BLUFI splits anything
past its chunk size, and a fragment is not JSON on its own), and provisioning
counts as done on either protocol's confirmation.

### Smaller

- A device that accepts the credentials but does not report joining within 25
  seconds says so, with its last known state. It used to return success with
  nothing in the log at all — the one habit 1.5.0 set out to break.
- The join report is logged as it changes, so the log shows progress rather
  than one line at the end.
- Notifications are read from their own offset within the underlying buffer.
  Reading the buffer whole works in Chrome today and is the kind of thing that
  stops working on one platform with nothing to see.
- The credentials now carry `hide`, `ipServers` and the timezone as the
  one-decimal string, matching the only payload confirmed to provision a
  device.
- The provisioning decoders have real tests: the frames from all three reports,
  run through the actual panel code in node. Skipped where node is absent.

### Two feeder details, from a capture of the real cloud

Both from **@cipheredsyntax** (PR #10), taken off PetKit's own servers talking
to a Fresh Element Solo:

- **A feed's id carries its number twice** — `r_20260802_882_882-1` — where
  this sent it once. That shape came from localkit's reimplementation; two
  independent captures agreeing outrank it.
- **A settings write carries no `type` key.** It is inert — the firmware reads
  `payload` and nothing else — but a body shaped like the cloud's is one a
  capture of ours can be compared against.

The rest of that report — a feeder sending its identity in the POST body, and
the heartbeat's `msgType` numbers being wrong — was found independently and
fixed in 1.5.0 and earlier, in both cases more broadly than the report needed:
identity is resolved from the body for every endpoint rather than signup alone,
and the `msgType` values come from the firmware's own three-way branch, read in
two different binaries, rather than being special-cased per family.

### Still true, and worth saying plainly

The bytes this sends an Ingenic device were never the regression. They are
identical in 1.4.0 and 1.6.0 — same document, same chunking, same write. What
1.4.0 did was print "provisioned" without looking at the reply; 1.5.0 started
telling the truth and 1.5.1 fixed the model detection it had broken. This
release is the first that reads what the device says back.

## 1.6.0 — 2026-08-02

### Every Bluetooth write this has ever sent was malformed

The frame that carries a command to a fountain announces its own payload length
in two bytes, low half first. This wrote one. Everything after it was therefore
shifted by one, and the accessory read the first byte of the payload as the
high half of the length: a mode change claimed four bytes and delivered three
and a trailer, and a settings change claimed **780 bytes** and was still being
waited for when the session closed.

Both fail in silence — there is no error, the frame is simply never acted on —
which is why "a settings write cannot be verified" has been in the notes here
since the write path was added. It could not have worked.

Found by comparing this against [aavdberg/ha-petkit](https://github.com/aavdberg/ha-petkit),
which reaches these fountains straight from Home Assistant rather than through
a relay and has therefore had every one of its command layouts exercised on
real hardware. Three sources agree on the eight-byte header, including this
project's own frame *reader*, which has always expected one — so the encoder
and the decoder here were written to two different specifications and nobody
noticed, because nothing ever round-tripped one.

With the length fixed, the mode frame drops the leading zero it used to carry
— that zero was the missing length byte, compensated for in the wrong place —
and becomes byte-identical to the one ha-petkit sends.

### Fountain controls that did the wrong thing when they worked at all

- **Picking a flow mode switched the pump off.** The frame carries power, pause
  and mode together, so it was rebuilt from the last reading — and a CTW3
  reports power 0 in the sleep half of its smart cycle. Choosing a mode now
  states that the pump should run, because that is what choosing a mode means.
- **A mode of 0 was believed.** Same sleep phase, same report: it is not a mode
  and it is not "off", it is the fountain resting between runs. Latched, it
  turned the next touch of the power switch into "off, in no mode". It is
  discarded now and the last real mode stands.
- **Switching a fountain off left it marked as pumping.** The pause byte is
  forced to 0 when the power is.
- **The settings block was written with invented bytes.** Two constants at the
  front were the smart-cycle times one captured frame happened to carry,
  mistaken for structure, and one byte near the end was a value that frame does
  not have. It is rebuilt from the reading now, and the smart-cycle times are
  yours to set.
- **The flow modes are called Normal and Smart**, as PetKit's app calls them
  and as both reference projects do. They were "continuous" and "intermittent"
  — accurate about the pump, matching nothing you can compare against. An
  automation that names the old labels needs updating.

### Where the two projects disagree, the code says so

Three bytes of the CTW3 settings block are read one way here and the other way
by ha-petkit. This reads them from a real status frame, where they are coherent
as light / brightness / do-not-disturb; ha-petkit reads the same positions in a
capture of PetKit's own app writing, where they are do-not-disturb / light /
brightness. Neither observed the other's direction, and nothing says a status
echo is byte-identical to a write.

So the status is decoded the way the status frame reads, the write goes out the
way the write capture reads, and the disagreement is written down where the
bytes are rather than resolved by preference. If a CTW3 owner finds the Light
switch turning do-not-disturb on, that is the note to read.

### Fountains gained what they were already reporting

- **CTW3**: child lock, both smart-cycle times, a module status byte, and a
  power source that says "mains" instead of `2`. An older firmware that sends a
  26-byte status is read rather than dropped — this demanded 30.
- **W4 / W5 / CTW2**: today's pump runtime and both smart-cycle times, and the
  settings frame is decoded at all now, which is where the light, its
  brightness, both schedules and the child lock live.
- **A filter reset** on both families, as a button. It carries nothing built
  from state, so it is the one write that works on an accessory that has never
  reported.
- A status frame too short to be one is dropped whole on the W5 family too. It
  used to emit every field whose offset happened to fit, which turned a
  one-byte acknowledgement into a confident "the pump is on".

### Controls for the W4 / W5 / CTW2 fountains — untested

They had five entities, all read-only. They now have power, mode, light,
brightness, do-not-disturb, child lock, both smart-cycle times and the filter
reset. **Nobody involved owns one.** The layouts come from two independent
sources that agree, and that is all that can be said for them; a settings write
is refused until the fountain has sent a settings frame, rather than guessed
from defaults that would erase both schedules.

`w5_power` became a switch, having been a read-only sensor. If you are running
one, the old `binary_sensor` entity is orphaned and the switch replaces it.

## 1.5.1 — 2026-08-02

### Bluetooth provisioning worked again, on the models 1.5.0 had not broken

1.5.0 taught the Provision tab to recognise BLUFI as well as PetKit's own
protocol, and picked between them by asking the device to list its Bluetooth
services. That list turns out not to be the same thing as what a device hands
over when asked for a service by name: a YumShare Dual-Hopper that opens
PetKit's `0xAAA0` on request does not appear in it, so the tab decided it did
not recognise the feeder and stopped.

Reported by an owner who paired the same device from the hosted provisioning
page minutes later — that page still runs the older code, which asked by name.
Two pages, one device, one difference; without that comparison this would have
read as a broken feeder.

Both services are asked for by name now. The listing survives in one place,
describing a device that answered to neither, where being incomplete costs
nothing.

### Two places pointed at tabs that do not exist

The provisioning log told anyone who selected a Bluetooth-only accessory to
pair it under "Setup", and the capture toggle was described as living under
"Setup → Live settings". Neither exists: accessories pair from **Devices**, on
the panel of the litter box or feeder that relays for them, and the capture
toggle is under **Setup → Settings**.

## 1.5.0 — 2026-08-02

### Some models could never register at all

A Feeder D4 sends its id and serial in the body of its signup request, not in
the header every other model uses. Nothing here looked at the body, so the
device was answered "missing device id" and stopped there — and the endpoint
that hands out MQTT credentials answered **200 with nothing in it**, which is
worse, because there is no error to see. The device simply never appeared.

The body is a third place identity can come from now, after the header and the
query string. This is one report's evidence (thank you), but it is not one
model's bug: about eighteen endpoints resolve a device the same way.

### Bluetooth provisioning on the ESP32 models

The Provision tab spoke one protocol and assumed every PetKit device spoke it.
The ESP32 models do not: a D4 and a T4 carry **BLUFI**, Espressif's own
provisioning profile, and expose nothing at the address the panel was looking
for. Selecting one produced a Bluetooth error about a missing GATT service.

The panel now asks the device which of the two it speaks and uses that one. The
Wi-Fi credentials, the server address and the timezone are the same either way.

Two related things that were wrong for every model:

- **"Provisioned" meant "the write returned".** It was printed whether or not
  the device had understood a word, and the Bluetooth link was cut a second and
  a half later — before a slower reply could arrive. It now means the device
  answered, and says plainly when it did not.
- **The device chooser offered accessories.** A W5, a CTW3 or a Pura Air would
  appear in the list and then fail with a raw error. They have no Wi-Fi to
  configure; the panel says so and points at where they are actually paired.

Feeder Mini and its generation have no Bluetooth setup at all — those still
need a DNS redirect, and the panel names that too instead of failing silently.

### The EverSweet Max Cordless

A CTW3 owner mapped their fountain's whole protocol and sent it in, which is
the only reason any of this exists. It is supported now: tanks, pump, battery,
filter, drinking detection, faults — and its controls, which is the first time
any Bluetooth accessory here could be *set* rather than only read.

Power, working, flow mode, light, brightness, do-not-disturb and both timers.
Two caveats worth knowing: a setting can only be changed once the fountain has
reported at least once, because the device takes its settings as one block and
the rest of it has to be read before one part of it can be written; and the
number the relay is told to scan for is **24** for this model, not the 14 that
1.4.0 guessed.

### A Bluetooth accessory is a device in the panel now

It was three cells in its parent's card: type, address, unpair. Everything the
last two releases added to it — the decoded readings, twenty-one entities, the
controls — existed only in Home Assistant.

It gets its own panel in **Devices**, next to the device that relays for it,
with its state and its controls. Not a copy of a device panel: there are no
HTTP or MQTT counters, no command queue, no patchers. An accessory has no
network of its own, so every one of those numbers would be a zero pretending to
be a reading. What it does have is a **BLE** badge instead of MQTT-or-heartbeat,
a line saying which device relays for it, and — at last — when it last said
anything, which was previously not recorded anywhere at all.

Its controls work from the panel too, not just from Home Assistant, and there
is a **Read now** button: an accessory speaks only when its parent is told to
open a Bluetooth session, which otherwise happens on a timer up to four minutes
away — no way to answer "did that pairing work" except to wait. Where the scan
type is still a guess, the panel now says so on the accessory itself rather
than keeping it in a field nobody reads.

### Accessories were never being asked to report

An accessory only speaks when its parent is told to open a Bluetooth session,
and the only thing that ever told it was the arrival of a status report from
the parent itself. A feeder does not send those. So a fountain relayed by a
feeder was polled zero times, for ever, while looking perfectly paired.

There is a timer now, which is what the real cloud uses. The session is also
closed once the reading is in, instead of being left open indefinitely, and a
Pura Air is no longer asked to open one at all — it is not reachable that way
and never was.

## 1.4.0 — 2026-08-02

### Commands sent over HTTP never arrived

A device that is not on MQTT gets its commands in the answer to its heartbeat
poll. Each one is tagged with a `msgType` telling the firmware what kind of
message it is — and four of the five numbers we used were not numbers the
firmware knows. It logs `error msgType` and discards the message: no reply, no
error, nothing this end can see. The queue drains, the add-on reports the
command delivered, and the device does nothing.

Only "start" was right, by coincidence. **Every settings change, every manual
feed and every connect sent to a device without an MQTT session was thrown
away.** They are the three real values now (0, 1 and 2), read out of two
different models' firmware to be sure it is not one device's quirk.

Two commands answered in the same poll also collided: the device drops a
message whose timestamp is not newer than the last one it ran, so only the
first of a batch was executed. They are spaced now.

This affects every model, not just the fountain.

### The EverSweet Ultra AI had its tanks the wrong way round

The tray and the waste tank were swapped. "Waste Tank Full" was the drinking
tray being full; "Drinking Tray Installed" was the waste tank being seated. An
owner reported this and was told the firmware said otherwise — it does not. The
field is filled by a function the firmware itself calls "get water tray full
state", which is as direct as evidence gets.

Four entities are renamed as a result. **The old ones will stop updating and can
be deleted from Home Assistant:** Waste Tank Full, Waste Tank Installed,
Drinking Tray Installed and Drinking Tray State. What replaces them is Tray
Full, Tray Installed, Waste Tank Installed and Waste Tank State. Transfer Pump
is now Refill Pump, which is what the firmware calls it.

### Flush, Refill and Water Change

The W7H can be told to run its water cycles. It had no buttons at all, because
the values its `start` service takes were unknown; they are now read out of the
firmware, which accepts exactly twenty of them and silently ignores everything
else. Flush and Water Change name themselves in the firmware. Refill is on the
accepted list but not named there, so if one of the three turns out to do
something else, it is that one.

Deep clean is deliberately absent: the cycle exists, but nothing ties it to an
accepted value, and it is the one that needs somebody standing there with a
kettle of boiling water.

### The fountain stops borrowing a litter box's vocabulary

A refill showed up in the timeline as "Odor removal", a flush as "Dumping". The
work-mode names are per device family and the fountain was being read out of
the litter table. It has its own now.

Five more faults are spelled out — clean and waste tank missing, clean tank low,
waste tank full, heater missing — and a fault that arrives as an event reads the
same as the same fault arriving in a status report, instead of showing the
device's abbreviation.

The W7H also gets its Work, Drinking and Error event entities, which are what
automations trigger on. Until now its events were published to entities it had
never announced, so nothing fired.

### Which fountains can actually connect

Only the EverSweet Ultra AI. The EverSweet, EverSweet 3 Pro, Solo 2 and Max
Cordless have no Wi-Fi at all — they pair over Bluetooth to a litter box or a
feeder, which relays for them. They were listed here as network devices because
PetKit's cloud describes them that way, and from the account side a relayed
fountain looks exactly like a connected one.

The add-on knows which ones those are now: a model with no radio that somehow
registers over the network is logged as the anomaly it is, rather than quietly
getting an entity list nothing can fill. The Pura Air spray is marked the same
way. Nothing changes for a fountain you already have paired through a box.

All four can now be paired, not just the W5 — they share one Bluetooth protocol,
so the same entities and the same frame decoding cover them. One number in that
pairing is a guess: what the relay is told to scan for. Only the W5's was read
off a real exchange, and the rest reuse it. If one of them stays silent, there
is a **Scan type** field under Advanced to try another value in; it is the kind
of thing only somebody holding the hardware can settle.

### Under the hood

The W7H is separated from the Bluetooth EverSweets throughout. It shares a
category with them because it is a fountain, but almost none of its protocol:
two tanks, a lift valve, ten hall switches, a camera and an NPU against a pump
and a filter. Every table read out of its firmware is now keyed on that model
alone, so a W4 or W5 can never be answered in a vocabulary describing hardware
it does not have.

## 1.3.0 — 2026-08-01

### The EverSweet Ultra AI can be patched

The MQTT TLS bypass and Local Storage patches now work on the W7H — the first
ARM device. Previously only the Ingenic MIPS models (T5, T6, T7, D4H, D4SH)
could be patched; the W7H showed "no arm variant yet" on every card.

The patchers detect the device's CPU from the binary they download rather than
from a static table, so a device the table has never heard of still gets the
right patch — and one the table has wrong (such as a hypothetical ARM
generation of an existing codename) is refused instead of silently mis-patched.
`DEVICE_CPU_ARCH` and the panel's architecture gate are removed; the binary
itself is the authority now.

ARM patch points were contributed by an external reverse engineer and verified
against the W7H 456 firmware image in the test suite. The MQTT stub is an
8-byte Thumb sequence that clears the TLS verification flags and returns
success, mirroring the 16-byte MIPS stub. The cloud patcher finds isCClassIP
by its unique ITE instruction tail and the five CONNECT_TO guards by the
CURLOPT constant they load, distinguishing them from two structurally similar
sites that must not be touched.

## 1.2.0 — 2026-08-01

### The YumShare Dual-Hopper can be patched again

Applying the MQTT patch to a D4SH failed outright with "Cannot find
mbedtls_x509_crt_verify_with_profile". The symbol was there and was found — the
patcher then threw the answer away, because it checked the first four
instructions against a copy taken from a Purobot Ultra. Those instructions carry
an offset that differs in every binary, so the check could only ever pass on the
one model it was recorded from. It now trusts the symbol, and the fallback for
a binary without one matches the *shape* of a function entry rather than one
build's bytes.

The Local Storage patch had the same fault in a quieter form: it expected an
instruction to be the last one in its function, which is where the compiler put
it on a Purobot and not on a Dual-Hopper. It now looks through the whole
function.

Both are fixed against real firmware rather than reasoning — T5, T6 and D4SH
images are now part of the test suite (`pytest --firmware`), so a patcher that
works on one model and not another fails here instead of on your device.

### The panel says which version is running

New row at the top of **Setup → Connection**. This exists because there was no
way to answer "did the update actually take effect?" — an owner updated, saw
the old entities, and neither of us could tell a stale build from a bug. The
number is now on screen.

### Fountain events

- **Refill done** (`add_water_over`) is a real event. A live EverSweet Ultra AI
  sends it a second after it starts drinking-detection; with no entry for it the
  timeline said `add_water_over (other)`.
- **Work started** was filed as something only litter boxes send. Fountains send
  it too.

### The AI detections moved

Pet, drink and vomit detection now sit on the **AI / Pets** tab beside the
recognition toggle, instead of among Controls with the heater and the flush
cycle. They decide whether a whole class of event is raised at all, which is
what the AI card is about. Vomit detection also gained a description.

Feeders with a camera but no on-device AI (D4H, D4SH) keep their pet-detection
switch where it was — they have no AI card for it to move to.

### Add-ons are called Apps now

Home Assistant renamed them in the interface, so the README, the documentation
and the panel say "app" where they mean the thing you installed. If your menu
still says *Settings → Add-ons*, you are on an older release and everything
works the same; the install steps note both. The word "add-on" survives
everywhere it is still correct — `ha addons`, the Supervisor API, this
repository's own layout.

## 1.1.0 — 2026-08-01

### The EverSweet Ultra AI (W7H) reports what it actually sends

Its entities were borrowed from PetKit's cloud API, which describes a different
generation of fountain. The ones that mattered read unknown forever while the
device was reporting a full mechanism nobody was looking at.

- **New:** waste and clean water tanks, drinking tray, waste lock, heater,
  circulation and transfer pumps, refill, flush and disinfect cycles, the lift
  valve, and the ten hall switches behind them. Plus Last Drink, Last Pet
  Detected and Reboot Reason.
- **Faults are spelled out.** "Tray full" rather than `taryF`.
- **Removed, because this hardware has none of it:** filter level, filter days,
  battery, low battery, replace filter, water lack, pet detected, drink times.
  Also the pause and resume buttons — `power` is not a command this firmware
  answers, so they wrote a field nothing reads and reported success. Delete them
  from Home Assistant if they linger.
- **Drink Times became Last Drink.** The device reports the *time* of the last
  drink, not a count, so the old sensor would have shown a ten-digit number.
- A W7H no longer reports a Device Status of 0. It never sends one, and 0 is a
  real mode — the same defaulting that once had an idle litter box calling
  itself busy.
- New switches for settings its firmware really accepts: drink and vomit
  detection, auto flush, auto water change, the three status lights, the WiFi
  light, and quiet modes for refill and water-level alerts.
- `drink_start` and `pet_discern` are recognised on fountains instead of being
  filed as unknown events, and a detection that recognised nobody is no longer
  recorded as a match on a pet.

### Everything else

- **Provisioning over HTTP said the wrong thing.** On a plain-HTTP page it
  reported that your browser could not provision — on Chrome, where the real
  and fixable problem was the page not being HTTPS. It now says so, the warning
  is coloured like a warning instead of a plain card, and the form is visibly
  switched off while it cannot be used.
- Litter boxes with a camera (T5/T6/T7) gained their six hall switches as
  diagnostics, which is how you tell where a stalled mechanism stopped.

## 1.0.1 — 2026-07-31

- The web panel adds itself to Home Assistant's sidebar on first start. It is
  not something an add-on can declare, and a fresh install hid the panel that is
  its whole interface. Done once — if you take it out of the sidebar, it stays
  out.
- Say that the MQTT broker needs configuring. With the Mosquitto add-on there is
  nothing to do; with any other broker you must set `ha_mqtt_host`, and skipping
  it produced no error at all — the device worked, the panel worked, and Home
  Assistant showed no entities. The add-on now warns.
- **Standalone only:** the device was told to upload its photos and video to
  `https://localhost:9000`, which on the device is the device. The address is
  derived from `api_url` now. Add-on installs were never affected — the
  Supervisor supplies a host address there.

## 1.0.0 — 2026-07-31

Initial release.

What it does, which models are actually verified, and the rough edges worth
knowing before you trust it are in the [README](../README.md) and
[DOCS.md](DOCS.md).
