"""HA `number` entities — the numeric device settings, per device category.

Each one reads `settings.<field>` from the state document and writes the same
field back via `property.set`. `min_value`/`max_value`/`step` are HA-side
validation only: the device does its own clamping, so these bounds exist to
stop an obviously-wrong value from ever being sent, not to guarantee one.

`devices/categories.py` decides which of these lists a given device type gets.
"""
from petkit_local.ha.discovery import EntityDef

LITTER_NUMBERS = [
    EntityDef(component="number", key="cleaning_delay", name="Cleaning Delay",
              value_path="settings.stillTime", icon="mdi:timer-sand",
              unit="s", min_value=0, max_value=3600, step=60),
]

FEEDER_NUMBERS = [
]

#: Seeded by `Device.default_settings()` only inside its `is_camera` branch,
#: so on a non-camera model these render blank forever. Two sources agree
#: they belong to the camera hardware: the defaults table and the state
#: parsers (`_parse_litter_camera` is documented as "the ESP32 litter set
#: PLUS the camera, spray and package fields").
#:
#: THE VOLUME RANGE IS UNVERIFIED for a litter box, and 0-9 should not be read
#: as evidence. The field itself is real — PetKit's own cloud sends `volume` in
#: `dev_device_info` — but in all 508 captured replies it was `1` and never
#: anything else, so no capture bounds it. 0-9 comes from localkit's validator
#: for the YumShare Solo, a FEEDER (`PetkitYumshareSolo.php`, whose own picker
#: offers 1-9, not 0-9); its litter-box model declares no volume at all. The
#: panel shows the range so the bound is at least visible to whoever hits it.
LITTER_CAMERA_NUMBERS = [
    EntityDef(component="number", key="volume", name="Volume",
              value_path="settings.volume", icon="mdi:volume-high",
              min_value=0, max_value=9, step=1),
]

#: How much each hopper of a Dual-Hopper dispenses per press.
#:
#: `local.` and not `settings.`, which is the whole point of that prefix: this
#: is our intent, not a device setting. `Device.to_device_info` serves
#: `config["settings"]` straight back to the device, so a value parked there
#: would be pushed to the feeder as a setting it never had.
#:
#: The unit really is portions on this model — its firmware reads `amount1`
#: verbatim with no scaling, and PetKit's app sends 1 for a single portion
#: (issue #2). That is NOT true of the single-hopper `amount`, which the device
#: divides before use, which is why these entities exist for the dual model
#: alone.
#:
#: 1..10 is a soft bound. The only limit the firmware evidences is its own
#: single-byte store (`sb`), so 255 is where a value would start wrapping;
#: 10 is a sane ceiling for a control someone taps, not a measured maximum.
FEEDER_DUAL_NUMBERS = [
    EntityDef(component="number", key="hopper1_portions", name="Hopper 1 Portions",
              value_path="local.feedAmount1", icon="mdi:silverware-fork-knife",
              min_value=0, max_value=10, step=1),
    EntityDef(component="number", key="hopper2_portions", name="Hopper 2 Portions",
              value_path="local.feedAmount2", icon="mdi:silverware-fork-knife",
              min_value=0, max_value=10, step=1),
]

FEEDER_CAMERA_NUMBERS = [
    EntityDef(component="number", key="volume", name="Volume",
              value_path="settings.volume", icon="mdi:volume-high",
              min_value=0, max_value=9, step=1),
]

FOUNTAIN_NUMBERS = [
    EntityDef(component="number", key="fountain_time", name="Fountain Time",
              value_path="settings.fountainTime", icon="mdi:clock-outline",
              unit="h", min_value=1, max_value=24, step=1),
    EntityDef(component="number", key="sleep_time", name="Sleep Time",
              value_path="settings.sleepTime", icon="mdi:sleep",
              unit="h", min_value=1, max_value=24, step=1),
]
