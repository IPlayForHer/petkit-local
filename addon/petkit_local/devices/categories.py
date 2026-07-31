"""Catalogue mapping each device category to its HA entities and MQTT topics.

PetKit ships many device codenames but only four behavioural families: litter
box, feeder, water fountain, Pura Air spray. Everything a family contributes to
Home Assistant -- which entity lists it publishes, which extra ones a
camera-equipped model adds, and which MQTT event topics carry its state -- used
to live in four near-identical modules (`litter.py`, `feeder.py`,
`water_fountain.py`, `purifier.py`) that had already drifted apart in ordering
and signature. This module replaces them with one table so that supporting a
new family is a `CATEGORY_SPECS` entry, not a fifth copy of the same skeleton.

The table is deliberately data, not code: the entity set it produces is the
user's Home Assistant state. A reordered or renamed entry orphans entities in
live installations and loses their recorded history, so `CategorySpec` composes
existing lists in a fixed order and never rewrites them.
"""
from __future__ import annotations

from dataclasses import dataclass

from petkit_local.devices.base import Device
from petkit_local.ha.discovery import EntityDef
from petkit_local.ha.entities.buttons import FEEDER_BUTTONS, FOUNTAIN_BUTTONS, LITTER_BUTTONS
from petkit_local.ha.entities.camera import CAMERA_ENTITIES
from petkit_local.ha.entities.events import FEEDER_EVENTS, LITTER_EVENTS
from petkit_local.ha.entities.numbers import (
    FEEDER_CAMERA_NUMBERS, FEEDER_NUMBERS, FOUNTAIN_NUMBERS,
    LITTER_CAMERA_NUMBERS, LITTER_NUMBERS,
)
from petkit_local.ha.entities.selects import FEEDER_SELECTS, FOUNTAIN_SELECTS, LITTER_SELECTS
from petkit_local.ha.entities.sensors import (
    FEEDER_BINARY_SENSORS, FEEDER_SENSORS,
    FOUNTAIN_BINARY_SENSORS, FOUNTAIN_SENSORS,
    LITTER_BINARY_SENSORS, LITTER_CAMERA_SENSORS, LITTER_SENSORS,
    PURIFIER_BINARY_SENSORS, PURIFIER_SENSORS,
)
from petkit_local.ha.entities.switches import (
    CAPABILITY_SWITCHES,
    FEEDER_CAMERA_SWITCHES, FEEDER_SWITCHES,
    FOUNTAIN_SWITCHES,
    LITTER_CAMERA_SWITCHES, LITTER_SWITCHES,
    PURIFIER_SWITCHES,
)
from petkit_local.ha.entities.text import FEEDER_SCHEDULE_TEXT, LITTER_SCHEDULE_TEXT
from petkit_local.utils.const import (
    DEVICE_TYPES_FEEDER, DEVICE_TYPES_LITTER, DEVICE_TYPES_PURIFIER,
    DEVICE_TYPES_WATER_FOUNTAIN,
)

#: Every camera-capable category ends its camera bundle with the same trio of
#: camera/snapshot/clip entities plus the media-capability toggles; only the
#: leading per-category switches differ. Order is load-bearing (see module
#: docstring), which is why this is appended, never merged in.
_COMMON_CAMERA_ENTITIES: tuple[EntityDef, ...] = (*CAMERA_ENTITIES, *CAPABILITY_SWITCHES)


@dataclass(frozen=True)
class CategorySpec:
    """What one device category publishes to Home Assistant.

    Invariant: `entities` and `camera_entities` are in HA discovery order and
    that order is part of the contract -- entity identity is derived from
    `EntityDef.key`, so appending is safe but reordering or renaming breaks
    existing installations.

    `device_types` is the set of device codenames belonging to this category,
    shared with `utils/const.py` so there is exactly one such list per family.
    """

    device_types: frozenset[str]
    entities: tuple[EntityDef, ...]
    state_topics: tuple[str, ...]
    #: Extra entities a camera-equipped model of this category adds. Empty for
    #: categories with no camera model (the Pura Air spray is BLE-only).
    camera_entities: tuple[EntityDef, ...] = ()
    #: Extra MQTT event topics a camera-equipped model of this category emits.
    camera_state_topics: tuple[str, ...] = ()

    def entities_for(self, has_camera: bool) -> list[EntityDef]:
        """HA entity definitions for one device, in discovery order.

        Returns a fresh list per call because callers treat it as their own.
        """
        entities = list(self.entities)
        if has_camera:
            entities.extend(self.camera_entities)
        return entities

    def state_topics_for(self, has_camera: bool) -> list[str]:
        """MQTT event topic suffixes this device reports state on."""
        topics = list(self.state_topics)
        if has_camera:
            topics.extend(self.camera_state_topics)
        return topics


#: Category name -> spec. Iteration order is the resolution order used by
#: `spec_for_device`, so a codename listed in two categories resolves to the
#: first -- litter, feeder, fountain, spray -- exactly as the if-chain this
#: table replaced did.
CATEGORY_SPECS: dict[str, CategorySpec] = {
    "litter": CategorySpec(
        device_types=frozenset(DEVICE_TYPES_LITTER),
        entities=(
            *LITTER_SENSORS,
            *LITTER_BINARY_SENSORS,
            *LITTER_SWITCHES,
            *LITTER_BUTTONS,
            *LITTER_NUMBERS,
            *LITTER_SELECTS,
            *LITTER_EVENTS,
            *LITTER_SCHEDULE_TEXT,
        ),
        camera_entities=(*LITTER_CAMERA_SENSORS, *LITTER_CAMERA_SWITCHES,
                         *LITTER_CAMERA_NUMBERS, *_COMMON_CAMERA_ENTITIES),
        state_topics=(
            "work_start", "work_continue", "work_suspend",
            "clean_over", "dump_over", "reset_over",
            "pet_in", "pet_out",
            "error_start", "error_over",
            "property/post", "data_get/post",
            "ble_response/post",
        ),
        camera_state_topics=("move_detect", "pet_detect"),
    ),
    "feeder": CategorySpec(
        device_types=frozenset(DEVICE_TYPES_FEEDER),
        entities=(
            *FEEDER_SENSORS,
            *FEEDER_BINARY_SENSORS,
            *FEEDER_SWITCHES,
            *FEEDER_BUTTONS,
            *FEEDER_NUMBERS,
            *FEEDER_SELECTS,
            *FEEDER_EVENTS,
            *FEEDER_SCHEDULE_TEXT,
        ),
        camera_entities=(*FEEDER_CAMERA_SWITCHES, *FEEDER_CAMERA_NUMBERS,
                         *_COMMON_CAMERA_ENTITIES),
        state_topics=(
            "feed_start", "feed_stop", "feed_over",
            "property/post", "data_get/post",
            "ble_response/post",
        ),
        camera_state_topics=(
            "eat_start", "eat_over",
            "move_detect", "pet_detect",
        ),
    ),
    "fountain": CategorySpec(
        device_types=frozenset(DEVICE_TYPES_WATER_FOUNTAIN),
        entities=(
            *FOUNTAIN_SENSORS,
            *FOUNTAIN_BINARY_SENSORS,
            *FOUNTAIN_SWITCHES,
            *FOUNTAIN_BUTTONS,
            *FOUNTAIN_NUMBERS,
            *FOUNTAIN_SELECTS,
        ),
        # No fountain-specific camera switches exist; the W7H publishes only
        # the common bundle.
        camera_entities=_COMMON_CAMERA_ENTITIES,
        state_topics=("property/post", "data_get/post"),
    ),
    "purifier": CategorySpec(
        device_types=frozenset(DEVICE_TYPES_PURIFIER),
        entities=(
            *PURIFIER_SENSORS,
            *PURIFIER_BINARY_SENSORS,
            *PURIFIER_SWITCHES,
        ),
        # K2/K3 are BLE-only accessories with no camera, so the camera bundle
        # stays empty rather than the signature differing from its siblings.
        state_topics=("property/post",),
    ),
}


def spec_for_device(device: Device) -> CategorySpec | None:
    """Category spec for a device, or None for a codename we don't classify.

    Unknown codenames are supported everywhere else (they register, connect
    and heartbeat); they simply publish no entities, so returning None here
    rather than raising keeps an unrecognised device usable.
    """
    for spec in CATEGORY_SPECS.values():
        if device.device_type in spec.device_types:
            return spec
    return None
