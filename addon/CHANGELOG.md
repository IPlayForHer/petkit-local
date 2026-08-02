# Changelog

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
