"""HA `sensor` and `binary_sensor` entities for every device category.

These are the read-only half of the integration: each entry names a key under
`state.` in the document `ha/publisher.py::_build_state` publishes, which
`devices/state_parsers.py` fills from HTTP state reports and MQTT property
posts. Nothing here is settable — the writable side lives in switches.py,
numbers.py, selects.py and text.py.

A `value_path` pointing at a key a device *may* not report is fine: the template
defaults it and the entity reads empty until the device sends one, which is what
lets one list serve several firmware versions.

That is NOT a licence to publish an entity nothing can ever fill. A field no
state parser produces and no default seeds reads unknown forever, which a user
cannot tell apart from a device that has not reported yet — four such entities
shipped that way and were removed (see the note further down). The rule is
enforced by `tests/test_entity_backing.py`, which walks every codename.

`devices/categories.py` decides which of these lists a given device type gets.
"""
from petkit_local.devices.state_parsers import WORK_MODE_IDLE
from petkit_local.events import codes
from petkit_local.ha.discovery import EntityDef

#: The work-mode enum, as labels+values for the value template. Imported rather
#: than restated: `events/codes.py` is the single source for protocol tables,
#: and a second copy here is exactly how a table drifts. Sorted so the pairing
#: is stable across runs.
#:
#: `WORK_MODE_IDLE` is prepended because it is NOT one of the device's codes —
#: a box reports no `workState` at all while idle, and the parser turns that
#: absence into this sentinel. It belongs in the rendering, not in the protocol
#: table. An unmapped mode still renders as its raw number rather than blank
#: (see `_enum_sensor_value_template`), so a code we have not seen stays visible.
_WORK_MODE_VALUES = [WORK_MODE_IDLE, *sorted(codes.WORK_MODES)]
_WORK_MODE_LABELS = ["idle", *(codes.WORK_MODES[v] for v in sorted(codes.WORK_MODES))]

LITTER_SENSORS = [
    EntityDef(component="sensor", key="device_status", name="Device Status",
              value_path="state.workingState", icon="mdi:state-machine",
              options=_WORK_MODE_LABELS, option_values=_WORK_MODE_VALUES),
    EntityDef(component="sensor", key="error", name="Error",
              value_path="state.errorMsg", icon="mdi:alert-circle"),
    # GRAMS, not kilograms. The device reports `litter.weight` as an integer
    # gram count (5469 in real T5 reports), `pet_weight` below uses `g` for the
    # same magnitude, and the panel's Timeline divides by 1000 to render kg.
    # This declared `kg` for a while, so HA was told the box held 5469 kg.
    EntityDef(component="sensor", key="litter_weight", name="Litter Weight",
              value_path="state.sandWeight", device_class="weight", unit="g"),
    EntityDef(component="sensor", key="litter_percent", name="Litter Level",
              value_path="state.sandPercent", unit="%", icon="mdi:percent"),
    EntityDef(component="sensor", key="used_times", name="Times Used",
              value_path="state.usedTimes", icon="mdi:counter"),
    EntityDef(component="sensor", key="n50_durability", name="N50 Days Left",
              value_path="state.deodorantLeftDays", unit="days", icon="mdi:air-filter"),
    EntityDef(component="sensor", key="n60_spray_days", name="N60 Spray Days Left",
              value_path="state.sprayLeftDays", unit="days", icon="mdi:spray"),
    # UPTIME, despite the key. `state.totalTime` is assigned straight from the
    # report's `runtime` (state_parsers._extract_litter_nested), which is how
    # long the device has been powered — on a live T5 it equalled `runtime` and
    # tracked `ble_os_run_ms` exactly. It was named "Total Usage Time", which
    # reads as cumulative time cats have spent in the box. `key` stays
    # `total_time` because renaming it would orphan the live entity.
    EntityDef(component="sensor", key="total_time", name="Uptime",
              value_path="state.totalTime", unit="s", device_class="duration",
              icon="mdi:timer", entity_category="diagnostic"),
    EntityDef(component="sensor", key="rssi", name="WiFi Signal",
              value_path="state.rssi", device_class="signal_strength", unit="dBm"),
    EntityDef(component="sensor", key="pet_weight", name="Pet Weight",
              value_path="state.petWeight", device_class="weight", unit="g",
              icon="mdi:scale-bathroom", entity_category="diagnostic"),
    EntityDef(component="sensor", key="last_clean", name="Last Cleaned",
              value_path="state.lastClean", device_class="timestamp",
              icon="mdi:broom", entity_category="diagnostic"),
    EntityDef(component="sensor", key="last_visit", name="Last Visit",
              value_path="state.lastVisit", device_class="timestamp",
              icon="mdi:cat", entity_category="diagnostic"),
]

LITTER_BINARY_SENSORS = [
    EntityDef(component="binary_sensor", key="waste_bin", name="Waste Bin Full",
              value_path="state.boxFull", device_class="problem", icon="mdi:delete-variant"),
    EntityDef(component="binary_sensor", key="pet_occupied", name="Toilet Occupied",
              value_path="state.petInTime", device_class="occupancy", icon="mdi:cat"),
    EntityDef(component="binary_sensor", key="waste_bin_present", name="Waste Bin Installed",
              value_path="state.boxState", icon="mdi:delete-empty"),
]
# REMOVED (2026-07-30): `sand_lack` (state.sandLack), `weight_error`
# (state.petError), `frequent_use` (state.frequentRestroom), `low_power`
# (state.lowPower) and `litter_tray` (state.sandTrayState).
#
# Same failure and the same evidence as the two removed below. Each name was
# searched for in three independent places and found in none:
#   * real T5 `ctrl` — absent (while `sprayState`, `boxState` and
#     `refreshState`, which the device really does send, are all present);
#   * every capture file, ~90k lines including 12,115 of real PetKit cloud
#     traffic and 905 state reports — zero occurrences of any of the five;
#   * a live T5's 54 reported state keys — absent.
# They survived only because `tests/test_entity_backing.py` accepted a name
# listed in a parser's passthrough tuple as proof something could fill it,
# which proves nothing at all. That hole is closed in the same commit.

#: The deodorizer state a camera-equipped litter box reports. Both fields are
#: in real T5 firmware, and `_parse_litter_esp32` states that T3/T4 "have no
#: camera or spray fields" — its extract list omits both — so on those models
#: they could only ever read unknown.
LITTER_CAMERA_SENSORS = [
    EntityDef(component="binary_sensor", key="deodorizer_present", name="N60 Deodorizer Present",
              value_path="state.sprayState", icon="mdi:spray-bottle"),
    # Reads the DERIVED flag, not `state.refreshState` itself. That field is an
    # object (`{"workReason":0,"workProcess":1}` in all 32 captured occurrences,
    # never a scalar), and a non-empty dict is truthy in the binary-sensor
    # template — so pointing at it directly latched the sensor ON the first time
    # the box ever deodorized and it could never read OFF again. It is also
    # presence-signalled rather than valued: it appears in only 3 of 905 state
    # reports, exactly the ones during a spray. See
    # `state_parsers._extract_presence_flags` for how absence becomes 0.
    EntityDef(component="binary_sensor", key="deodorization_running", name="Deodorization Running",
              value_path="state.deodorizing", device_class="running", icon="mdi:spray",
              entity_category="diagnostic"),
]
# REMOVED (2026-07-29): `garbage_bag_state` (state.packageState) and
# `purification_days` (state.purificationLeftDays). Neither string appears
# anywhere in real T5 firmware, while every other field on these lists does —
# they came from the reference integration, which models PetKit's CLOUD API,
# whose field names are not the device's. They were published to every litter
# box and could never hold a value.

FEEDER_SENSORS = [
    EntityDef(component="sensor", key="device_status", name="Device Status",
              value_path="state.workingState", icon="mdi:state-machine"),
    EntityDef(component="sensor", key="error", name="Error",
              value_path="state.errorMsg", icon="mdi:alert-circle"),
    EntityDef(component="sensor", key="desiccant_days", name="Desiccant Days Left",
              value_path="state.desiccantLeftDays", unit="days", icon="mdi:water-outline"),
    EntityDef(component="sensor", key="rssi", name="WiFi Signal",
              value_path="state.rssi", device_class="signal_strength", unit="dBm"),
    EntityDef(component="sensor", key="times_dispensed", name="Times Dispensed",
              value_path="state.feedState.times", icon="mdi:counter"),
    EntityDef(component="sensor", key="total_dispensed", name="Total Dispensed",
              value_path="state.feedState.realAmountTotal", unit="g", icon="mdi:scale"),
    EntityDef(component="sensor", key="food_in_bowl", name="Food in Bowl",
              value_path="state.weight", unit="g", icon="mdi:bowl"),
    EntityDef(component="sensor", key="food_bowl_pct", name="Food Bowl Level",
              value_path="state.bowl", unit="%", icon="mdi:bowl-mix"),
    EntityDef(component="sensor", key="amount_eaten", name="Amount Eaten",
              value_path="state.feedState.eatAmountTotal", unit="g", icon="mdi:food"),
    EntityDef(component="sensor", key="last_feed", name="Last Feed",
              value_path="state.lastFeed", device_class="timestamp", icon="mdi:food-fork-drink"),
]

FEEDER_BINARY_SENSORS = [
    EntityDef(component="binary_sensor", key="food_low", name="Food Low",
              value_path="state.food", device_class="problem", icon="mdi:food-drumstick-off"),
    EntityDef(component="binary_sensor", key="feeding", name="Feeding",
              value_path="state.feeding", device_class="running", icon="mdi:food"),
    EntityDef(component="binary_sensor", key="eating", name="Eating",
              value_path="state.eating", device_class="occupancy", icon="mdi:cat"),
    EntityDef(component="binary_sensor", key="battery_installed", name="Battery Installed",
              value_path="state.batteryPower", icon="mdi:battery"),
]

FOUNTAIN_SENSORS = [
    EntityDef(component="sensor", key="device_status", name="Device Status",
              value_path="state.workingState", icon="mdi:state-machine"),
    EntityDef(component="sensor", key="error", name="Error",
              value_path="state.errorMsg", icon="mdi:alert-circle"),
    EntityDef(component="sensor", key="rssi", name="WiFi Signal",
              value_path="state.rssi", device_class="signal_strength", unit="dBm"),
    EntityDef(component="sensor", key="filter_percent", name="Filter Level",
              value_path="state.filterPercent", unit="%", icon="mdi:filter"),
    EntityDef(component="sensor", key="filter_days", name="Filter Days Left",
              value_path="state.filterLeftDays", unit="days", icon="mdi:filter"),
    EntityDef(component="sensor", key="temperature", name="Water Temperature",
              value_path="state.heatRealTemp", device_class="temperature", unit="°C"),
    EntityDef(component="sensor", key="battery", name="Battery",
              value_path="state.batteryPercent", device_class="battery", unit="%"),
    EntityDef(component="sensor", key="drink_times", name="Drink Times",
              value_path="state.drinkTime", icon="mdi:cup-water"),
]

FOUNTAIN_BINARY_SENSORS = [
    EntityDef(component="binary_sensor", key="water_lack", name="Water Lack",
              value_path="state.lackWarning", device_class="problem", icon="mdi:water-off"),
    EntityDef(component="binary_sensor", key="low_battery", name="Low Battery",
              value_path="state.lowBattery", device_class="battery"),
    EntityDef(component="binary_sensor", key="replace_filter", name="Replace Filter",
              value_path="state.filterWarning", device_class="problem", icon="mdi:filter-remove"),
    EntityDef(component="binary_sensor", key="pet_detected", name="Pet Detected",
              value_path="state.detectStatus", device_class="occupancy", icon="mdi:cat"),
]

PURIFIER_SENSORS = [
    EntityDef(component="sensor", key="device_status", name="Device Status",
              value_path="state.workingState", icon="mdi:state-machine"),
    EntityDef(component="sensor", key="error", name="Error",
              value_path="state.errorMsg", icon="mdi:alert-circle"),
    EntityDef(component="sensor", key="humidity", name="Humidity",
              value_path="state.humidity", device_class="humidity", unit="%"),
    EntityDef(component="sensor", key="temperature", name="Temperature",
              value_path="state.temp", device_class="temperature", unit="°C"),
    EntityDef(component="sensor", key="air_purified", name="Air Purified",
              value_path="state.refresh", unit="m³", icon="mdi:air-purifier"),
    EntityDef(component="sensor", key="liquid", name="Liquid",
              value_path="state.liquid", unit="%", icon="mdi:water-percent"),
    EntityDef(component="sensor", key="battery", name="Battery",
              value_path="state.battery", device_class="battery", unit="%"),
]

PURIFIER_BINARY_SENSORS = [
    EntityDef(component="binary_sensor", key="spray", name="Spraying",
              value_path="state.refreshing", device_class="running", icon="mdi:spray"),
    EntityDef(component="binary_sensor", key="liquid_lack", name="Liquid Lack",
              value_path="state.liquidLack", device_class="problem", icon="mdi:water-off"),
]
