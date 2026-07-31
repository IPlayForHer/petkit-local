"""Property tests over the protocol tables in events/codes.py.

These are deliberately properties rather than examples. The gap this module
exists to close was not "one code had the wrong label" -- it was that a code's
kind, label, detail-ness and anchor role lived in six separate collections, so
seven codes ended up in none of them and nobody noticed until a real device had
been reporting them for days. An example test would have to be written for each
new code to catch that; a property test catches the next one for free.
"""
from petkit_local.events import codes, ingest
from petkit_local.utils.const import DEVICE_TYPES_ALL

#: Every HTTP code observed at least once in the reference capture (268 events
#: from a real T5, firmware 943). None of these may classify as "other".
OBSERVED_HTTP_CODES = (
    "1", "2", "3", "4", "5", "7", "8", "9", "10",
    "13", "14", "15", "16", "17", "20", "24",
)


def _all_rows():
    """(table name, key, EventCode) for every row in every namespace."""
    for name, table in (("litter", codes.LITTER_HTTP_CODES),
                        ("feeder", codes.FEEDER_HTTP_CODES),
                        ("mqtt", codes.MQTT_EVENT_TOPICS)):
        for key, code in table.items():
            yield name, key, code


def test_every_row_is_well_formed():
    for table, key, code in _all_rows():
        assert code.kind in codes.EVENT_KINDS, f"{table}:{key} has kind {code.kind!r}"
        assert code.label, f"{table}:{key} has no label"
        assert code.grade in codes.GRADES, f"{table}:{key} has grade {code.grade!r}"
        # A completion label is built as "<trigger> <done_word> <outcome>", so
        # a role=done row without the noun would render "Auto  completed".
        if code.role == codes.ROLE_DONE:
            assert code.done_word, f"{table}:{key} completes nothing"


def test_families_only_name_real_device_codenames():
    """A typo'd codename would silently exclude a device from `codes_for`."""
    for table, key, code in _all_rows():
        unknown = set(code.families) - set(DEVICE_TYPES_ALL)
        assert not unknown, f"{table}:{key} names unknown devices {unknown}"


def test_every_observed_code_is_classified_and_labelled():
    """The regression that started this: 23 of 268 events read "Event N"."""
    for code in OBSERVED_HTTP_CODES:
        assert ingest.classify_event_kind(code, device_type="t5") != codes.KIND_OTHER, \
            f"code {code} still falls through to 'other'"
        label = ingest.event_type_label(code, "t5")
        assert not label.startswith("Event "), f"code {code} still reads {label!r}"


def test_unmapped_codes_stay_unmapped():
    """12/19/22/23 are in neither the firmware RE nor any capture.

    Mapping them to a plausible-looking neighbour would hide the moment a
    T6/T7 starts sending one; the warning path is the feature.
    """
    for code in sorted(codes.UNKNOWN_HTTP_CODES):
        assert codes.lookup(code, "t5") is None
        assert ingest.event_type_label(code, "t5") == f"Event {code}"


def test_http_codes_are_resolved_per_device_category():
    """Code 2 is `err_over` on a litter box and `feed_over` on a feeder.

    A flat table would call a feeder's completed meal a cleared fault. This is
    the single most dangerous property of the HTTP namespace.
    """
    litter = codes.lookup("2", "t5")
    feeder = codes.lookup("2", "d4h")
    assert litter.kind == codes.KIND_ERROR and litter.label == "Error cleared"
    assert feeder.kind == codes.KIND_FEEDING and feeder.label == "Feeding done"
    assert ingest.classify_event_kind("2", device_type="d4") == codes.KIND_FEEDING
    assert ingest.classify_event_kind("2", device_type="t6") == codes.KIND_ERROR


def test_unknown_device_type_falls_back_rather_than_dropping():
    """Labelling an unclassified device beats showing its owner a bare code."""
    assert codes.lookup("10", "some-new-model") is not None
    assert codes.lookup("10", None) is not None


def test_mqtt_topics_resolve_for_every_category():
    """MQTT names are global, so a sparse HTTP table must not hide them."""
    for device_type in ("t5", "d4h", "w7h"):
        assert codes.lookup("pet_detect", device_type) is not None


def test_every_topic_the_bridge_dispatches_on_is_in_the_table():
    """`mqtt/bridge.py` reacting to a topic the table does not know means the
    event is stored with a label the table cannot produce."""
    from petkit_local.devices.categories import CATEGORY_SPECS
    for spec in CATEGORY_SPECS.values():
        for topic in spec.state_topics_for(True):
            if topic.endswith("/post"):      # transport, handled separately
                continue
            assert codes.lookup(topic) is not None, f"{topic} is dispatched but unmapped"


def test_an_http_code_fires_the_same_ha_event_entity_as_its_mqtt_twin():
    """The bug this replaced: the HTTP handler looked its numeric `event_type`
    up in a table keyed by MQTT NAMES, so it always missed and the four `event`
    entities never fired for any device reporting over HTTP."""
    from petkit_local.events.ingest import entity_for_event

    # (mqtt name, http code, device type, entity)
    for name, code, device_type, entity in [
        ("pet_out", "10", "t5", "toilet_event"),
        ("clean_over", "5", "t5", "cleaning_event"),
        ("dump_over", "6", "t5", "cleaning_event"),
        ("feed_over", "2", "d4h", "feeding_event"),
    ]:
        assert entity_for_event(name) == entity
        assert entity_for_event(code, device_type) == entity


def test_every_declared_ha_event_entity_can_actually_be_fired():
    """An `event` entity nothing maps to is published to HA and stays silent
    forever — indistinguishable from a device that never does the thing."""
    from petkit_local.devices.categories import CATEGORY_SPECS
    from petkit_local.events.ingest import KIND_TO_ENTITY

    declared = {e.key for spec in CATEGORY_SPECS.values()
                for e in spec.entities_for(True) if e.component == "event"}
    assert declared and declared <= set(KIND_TO_ENTITY.values())


def test_transport_topics_are_not_timeline_events():
    """Property updates and BLE plumbing must never become Timeline rows."""
    for topic in codes.MQTT_TRANSPORT_TOPICS:
        code = codes.lookup(topic)
        assert code is not None and code.kind == codes.KIND_SYSTEM
        assert code.detail, f"{topic} would render as a card"


def test_primary_done_codes_exclude_detail_steps():
    """A cycle emits several completions; only the non-detail one heads a card
    and carries the episode's media."""
    assert codes.PRIMARY_DONE_CODES <= codes.DONE_CODES
    assert "5" in codes.PRIMARY_DONE_CODES     # cleaning done
    assert "17" not in codes.PRIMARY_DONE_CODES  # light cycle, folded away


def test_anchor_codes_cover_every_card_heading_kind():
    for code in ("10", "20", "1"):
        assert code in codes.ANCHOR_CODES, f"{code} can no longer head a card"


def test_codes_for_filters_by_family():
    """Hardware one model lacks must not be advertised on it."""
    t4, t5, t6 = (codes.codes_for(d) for d in ("t4", "t5", "t6"))
    assert "melt_over" in t6 and "melt_over" not in t5        # T6+ cycle
    assert "feed_over" in codes.codes_for("d4h")

    # The N60 is built into the Purobot Max Pro/Pro 2, Ultra and Crystal Duo,
    # so its codes belong to t5/t6/t7 alike. This used to assert the opposite
    # -- "spray_over in t5 and not in t6" -- which withheld the deodorizer
    # codes from two thirds of the models that ship the hardware.
    for name in ("spray_over", "liquid_reset_over"):
        assert name in t5 and name in t6, name
        # The T4 has no built-in N60; where it sprays at all it is via an
        # optional BLE K3, whose consumables arrive as levels on the parent's
        # report rather than through these codes.
        assert name not in t4, name


def test_conflicts_and_caveats_are_recorded_not_silent():
    """A row whose sources disagree has to say so -- the Debug view renders
    `note`, and an unexplained `conflicted` badge is worse than none."""
    for table, key, code in _all_rows():
        if code.grade == codes.CONFLICTED:
            assert code.note, f"{table}:{key} is conflicted but says nothing"


def test_code_17_is_the_led_light_and_no_longer_conflicted():
    """Resolved from the device's own firmware: `ctrl` drives white and IR
    LEDs over PWM, raises an event carrying a `light_open_reason`, and closes
    it on `pk_toilet_over_judge_light_off`. LBCommand.LIGHT is action 7,
    matching NS5 workMode 7.
    """
    code = codes.lookup("17", "t5")
    assert code.grade == codes.CONFIRMED
    assert code.role == codes.ROLE_DONE
    # Noise the official app never surfaces: it stays folded away.
    assert code.detail is True
    # It fires on the way on AND on the way off with an identical payload, so
    # the direction can only come from the attached state.
    assert code.state_label == ("lightState", "light on", "light off")
