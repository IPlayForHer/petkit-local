"""HA `button` entities for litter boxes, feeders and fountains.

A button is the one entity kind with no state: pressing it publishes its `key`
and nothing else. That key is the contract with `ha/commands.py::ALL_ACTIONS`,
which owns the actual device action codes — a button whose key has no entry
there appears in HA and does nothing but log a warning, so the two lists must
be kept in step.

`devices/categories.py` decides which of these lists a given device type gets.
"""
from petkit_local.ha.discovery import EntityDef

LITTER_BUTTONS = [
    EntityDef(component="button", key="cleaning_start", name="Scoop", icon="mdi:broom"),
    EntityDef(component="button", key="maintenance_start", name="Enter Maintenance", icon="mdi:wrench"),
    EntityDef(component="button", key="maintenance_stop", name="Exit Maintenance", icon="mdi:wrench-check"),
    EntityDef(component="button", key="dump_litter", name="Dump Litter", icon="mdi:delete-sweep"),
    EntityDef(component="button", key="deodorize", name="Deodorize", icon="mdi:spray"),
    EntityDef(component="button", key="reset_n50", name="Reset N50", icon="mdi:restart"),
    EntityDef(component="button", key="reset_n60", name="Reset N60", icon="mdi:restart"),
    EntityDef(component="button", key="pause", name="Pause", icon="mdi:pause"),
    EntityDef(component="button", key="resume", name="Resume", icon="mdi:play"),
    EntityDef(component="button", key="reset", name="Reset", icon="mdi:stop"),
    EntityDef(component="button", key="level_litter", name="Level Litter", icon="mdi:format-align-bottom"),
]

FEEDER_BUTTONS = [
    EntityDef(component="button", key="feed", name="Feed", icon="mdi:food"),
    EntityDef(component="button", key="reset_desiccant", name="Reset Desiccant", icon="mdi:restart"),
    EntityDef(component="button", key="cancel_manual_feed", name="Cancel Manual Feed", icon="mdi:cancel"),
    EntityDef(component="button", key="food_replenished", name="Food Replenished", icon="mdi:food-apple"),
]

FOUNTAIN_BUTTONS = [
    EntityDef(component="button", key="reset_filter", name="Reset Filter", icon="mdi:filter-remove"),
    EntityDef(component="button", key="pause_fountain", name="Pause", icon="mdi:pause"),
    EntityDef(component="button", key="resume_fountain", name="Resume", icon="mdi:play"),
]
