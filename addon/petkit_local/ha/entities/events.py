"""HA `event` entities for litter boxes and feeders — momentary occurrences.

A sensor answers "what is the state now"; these answer "something just
happened" (a pet visit, a cleaning cycle, a feed), which is what automations
actually trigger on. `events/ingest.py::entity_for_event` maps each device
event_type onto one of the entities below and fires it non-retained, so an HA
restart does not replay a visit that happened yesterday.

`options` is the list of event_types HA will accept: an event_type fired but
not listed here is rejected by HA, so the two must be kept in step. The device
event_type strings themselves are not capture-confirmed — see
`events/ingest.py`'s header for what is.

`devices/categories.py` decides which of these lists a given device type gets.
"""
from petkit_local.ha.discovery import EntityDef

LITTER_EVENTS = [
    EntityDef(component="event", key="toilet_event", name="Toilet Event",
              icon="mdi:cat",
              options=["pet_in", "pet_out"]),
    EntityDef(component="event", key="cleaning_event", name="Cleaning Event",
              icon="mdi:broom",
              options=["work_start", "work_continue", "work_suspend",
                       "clean_over", "dump_over", "reset_over"]),
    EntityDef(component="event", key="error_event", name="Error Event",
              icon="mdi:alert",
              options=["error_start", "error_over"]),
]

FEEDER_EVENTS = [
    EntityDef(component="event", key="feeding_event", name="Feeding Event",
              icon="mdi:food",
              options=["feed_start", "feed_stop", "feed_over",
                       "eat_start", "eat_over"]),
]
