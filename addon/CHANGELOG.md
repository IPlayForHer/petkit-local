# Changelog

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
