# Changelog

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
