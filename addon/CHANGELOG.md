# Changelog

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
