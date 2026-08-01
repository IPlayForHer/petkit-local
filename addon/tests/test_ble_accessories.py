"""Pairing a BLE accessory, and the chain it unlocks.

A K3 purifier or W5 fountain has no network identity: a mains-powered
neighbour relays for it. The device does NOT discover accessories — it pulls a
list from the cloud and scans for exactly those MACs, and no firmware has any
way to report a newly-found one upward. Pairing happens in PetKit's app, i.e.
in the cloud, so with the app gone the cloud is us and the pairing has to be
entered here.

Everything downstream of that already existed and was completely untested,
which is how it stayed unreachable for so long.
"""
import json
import tempfile
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from petkit_local.devices.ble import BLERegistry, normalize_mac
from petkit_local.devices.registry import DeviceRegistry
from petkit_local.http.server import create_app
from petkit_local.mqtt.bridge import MQTTBridge
from petkit_local.web.hub import EventHub
from petkit_local.web.panel import create_panel_app

HDR = {"X-Device": "id=10&sn=SN10"}
DEVICE_CONFIG = {"api_url": "http://x/6/", "mqtt_port": 1883, "proxy_mode": False,
                 "proxy_upstream": "", "proxy_block_run_cmd": True, "capture": False}


def _panel(reg=None, ble=None):
    reg = reg or DeviceRegistry()
    ble = ble or BLERegistry()
    cfg = {"api_url": "http://x/6/", "capture": False, "capture_dir": "/nope"}
    return create_panel_app(reg, ble, EventHub(), cfg, None), reg, ble


async def _client(app):
    c = TestClient(TestServer(app))
    await c.start_server()
    return c


async def _pair(c, **over):
    body = {"ble_type": "w5", "petkit_id": 700, "mac": "AA:BB:CC:DD:EE:FF",
            "secret": "s3cret", "interval": 240, "link_with": 10}
    body.update(over)
    return await c.post("/api/ble", data=json.dumps(body))


# --- MAC handling -----------------------------------------------------------

@pytest.mark.parametrize("written, seen", [
    ("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"),
    ("aa-bb-cc-dd-ee-ff", "AABBCCDDEEFF"),
    ("aabbccddeeff", "AA:BB:CC:DD:EE:FF"),
])
def test_a_mac_matches_however_either_side_spelled_it(written, seen):
    """The MAC arrives from two directions that do not agree on formatting —
    typed by a person, and read out of a relayed frame — and a mismatch is
    invisible: the frame is dropped by a debug log with nothing to show."""
    reg = BLERegistry()
    reg.register(ble_type="w5", petkit_id=700, mac=normalize_mac(written), link_with=10)
    assert reg.get_by_mac(seen) is not None


@pytest.mark.parametrize("bad", ["", "not-a-mac", "AA:BB:CC", "AA:BB:CC:DD:EE:GG", "1234567890123"])
def test_an_unusable_mac_is_rejected_rather_than_stored(bad):
    assert normalize_mac(bad) == ""


# --- pairing ----------------------------------------------------------------

async def test_pairing_makes_the_accessory_appear_everywhere_at_once():
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        body = await (await _pair(c)).json()
        assert [a["petkit_id"] for a in body["accessories"]] == [700]

        dev = ble.get(700)
        assert dev.ble_type == "w5" and dev.link_with == 10
        # Stored canonical, so a frame in any spelling still matches.
        assert dev.mac == "AABBCCDDEEFF"
    finally:
        await c.close()


async def test_the_wire_entry_is_exactly_the_five_keys_the_firmware_parses():
    """`ble_relay_network.c` logs `dev[%d],id/mac/secret/interval/type` — those
    five names ARE the protocol, so the form is not a UI convenience."""
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        body = await (await _pair(c)).json()
        entry = body["accessories"][0]["wire_entry"]
        assert set(entry) == {"id", "mac", "secret", "interval", "type"}
        assert entry["id"] == 700 and entry["type"] == 14  # 14 = W5, per localkit
    finally:
        await c.close()


async def test_an_id_that_is_already_a_real_device_is_refused():
    """An accessory shares the `petkit_{id}` HA identity and the
    `petkit-local/{id}/state` topic with real devices, so a collision makes two
    devices fight over one entity set."""
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        r = await _pair(c, petkit_id=10)
        assert r.status == 409
        assert ble.get(10) is None
    finally:
        await c.close()


async def test_one_mac_cannot_be_paired_twice():
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        assert (await _pair(c)).status == 200
        # Same MAC, different spelling, different id.
        assert (await _pair(c, petkit_id=701, mac="aabbccddeeff")).status == 409
    finally:
        await c.close()


@pytest.mark.parametrize("over, status", [
    ({"ble_type": "zz"}, 400),          # no entities would ever be published
    ({"ble_type": ""}, 400),
    ({"mac": "nope"}, 400),
    ({"petkit_id": -1}, 400),
    ({"link_with": 999}, 400),          # parent does not exist
])
async def test_bad_input_is_refused_with_a_reason(over, status):
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        r = await _pair(c, **over)
        assert r.status == status
        assert (await r.json())["error"]
    finally:
        await c.close()


async def test_unpairing_removes_it_and_says_what_it_did_not_do():
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        await _pair(c)
        body = await (await c.delete("/api/ble/700")).json()
        assert body["ok"] is True and body["accessories"] == []
        assert ble.get(700) is None
        # HA keeps the entities — nothing publishes an empty discovery payload.
        assert "Home Assistant" in body["note"]
        assert (await c.delete("/api/ble/700")).status == 404
    finally:
        await c.close()


# --- what pairing unlocks: the relay list -----------------------------------

async def test_the_device_is_told_to_scan_for_a_paired_accessory():
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    ble = BLERegistry()
    ble.register(ble_type="w5", petkit_id=700, mac="AABBCCDDEEFF",
                 secret="s3cret", interval=240, link_with=10)
    app = create_app(reg, dict(DEVICE_CONFIG))
    app["ble_registry"] = ble
    c = await _client(app)
    try:
        body = await (await c.get("/6/t5/dev_ble_device", headers=HDR)).json()
        assert body["result"]["nextTick"] == 3600
        assert body["result"]["list"] == [
            {"id": 700, "mac": "AABBCCDDEEFF", "secret": "s3cret",
             "interval": 240, "type": 14}]
    finally:
        await c.close()


async def test_nothing_paired_omits_the_list_key_entirely():
    """Both transports must agree on this, and they had drifted — the MQTT twin
    always sent `list`, empty or not."""
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app = create_app(reg, dict(DEVICE_CONFIG))
    app["ble_registry"] = BLERegistry()
    c = await _client(app)
    try:
        http_body = await (await c.get("/6/t5/dev_ble_device", headers=HDR)).json()
        assert "list" not in http_body["result"]
    finally:
        await c.close()

    bridge = MQTTBridge(reg, None, BLERegistry())
    mqtt_body = bridge._user_get_payload(reg.get(10), "dev_ble_device")
    assert mqtt_body == http_body, "the two transports answer the same question differently"


async def test_a_k3_is_never_put_in_the_relay_list():
    """It is attached by naming it on the parent instead; listing it as well
    makes the firmware treat it as a second, unpaired device."""
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    ble = BLERegistry()
    ble.register(ble_type="k3", petkit_id=555, mac="AABBCCDDEE01", link_with=10)
    app = create_app(reg, dict(DEVICE_CONFIG))
    app["ble_registry"] = ble
    c = await _client(app)
    try:
        body = await (await c.get("/6/t5/dev_ble_device", headers=HDR)).json()
        assert "list" not in body["result"]
    finally:
        await c.close()


# --- what pairing unlocks: a relayed frame reaching HA ----------------------

class _FakePublisher:
    def __init__(self):
        self.states = []

    async def publish_ble_discovery(self, dev):
        pass

    async def publish_ble_state(self, dev):
        self.states.append(dev.petkit_id)

    async def publish_state(self, device):
        pass

    async def publish_availability(self, device):
        pass


async def test_a_relayed_w5_frame_reaches_home_assistant():
    """The whole chain, which had no test: a paired accessory, a frame arriving
    under its MAC, decoded into the state the entity value_paths read."""
    import base64

    reg = DeviceRegistry()
    parent = reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    ble = BLERegistry()
    ble.register(ble_type="w5", petkit_id=700, mac="AABBCCDDEEFF", link_with=10)
    pub = _FakePublisher()
    bridge = MQTTBridge(reg, pub, ble)

    # cmd 230 status frame: powerStatus=1, mode=2, runningStatus=1, filter=65%.
    data = bytes([1, 2, 0, 0, 1, 0, 0, 0, 0, 0, 65, 1])
    await bridge._handle_event(parent, "ble_response", {"params": {"content": json.dumps({
        "device": {"mac": "aa:bb:cc:dd:ee:ff"},   # a different spelling on purpose
        "payload": [{"cmd": 230, "data": base64.b64encode(data).decode()}],
    })}})

    dev = ble.get(700)
    assert dev.state["states"]["powerStatus"] == 1
    assert dev.state["consumables"]["filterPercentage"] == 65
    assert 700 in pub.states


async def test_k3_consumables_ride_in_on_the_parents_own_report():
    reg = DeviceRegistry()
    parent = reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    ble = BLERegistry()
    ble.register(ble_type="k3", petkit_id=555, mac="AABBCCDDEE01", link_with=10)
    pub = _FakePublisher()
    bridge = MQTTBridge(reg, pub, ble)

    await bridge._handle_event(parent, "property", {"params": {"battery": 88, "liquid": 60}})
    k3 = ble.get(555)
    assert k3.state["consumables"] == {"battery": 88, "liquid": 60}
    assert 555 in pub.states


# --- what pairing unlocks: the K3 block in device_info ----------------------

def test_a_linked_k3_is_named_in_the_parents_device_info():
    reg = DeviceRegistry()
    parent = reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    ble = BLERegistry()
    ble.register(ble_type="k3", petkit_id=555, mac="AABBCCDDEE01",
                 serial_number="K3SN", secret="k3s", link_with=10)

    info = parent.to_device_info(ble)["result"]
    assert info["withK3"] == 1 and info["k3Id"] == 555
    assert info["k3Device"]["mac"] == "AABBCCDDEE01"
    assert info["k3Device"]["sn"] == "K3SN"


def test_no_k3_says_so_explicitly():
    reg = DeviceRegistry()
    parent = reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    assert parent.to_device_info(BLERegistry())["result"]["withK3"] == 0


# --- pairing a K3 tells the parent about it ---------------------------------

async def test_pairing_a_k3_writes_k3id_on_the_parent():
    """A K3 is not in the relay list, so this property is the only thing that
    links it. Queued for the heartbeat when the parent is not on MQTT."""
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        await _pair(c, ble_type="k3", petkit_id=555, mac="AABBCCDDEE01")
        queued = [json.loads(x) if isinstance(x, str) else x
                  for x in reg.get(10).command_queue]
        assert any(q.get("params", {}).get("k3Id") == 555 for q in queued)
    finally:
        await c.close()


async def test_unpairing_a_k3_clears_it_on_the_parent():
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        await _pair(c, ble_type="k3", petkit_id=555, mac="AABBCCDDEE01")
        reg.get(10).command_queue.clear()
        await c.delete("/api/ble/555")
        queued = [json.loads(x) if isinstance(x, str) else x
                  for x in reg.get(10).command_queue]
        assert any(q.get("params", {}).get("k3Id") == 0 for q in queued)
    finally:
        await c.close()


# --- persistence ------------------------------------------------------------

def test_a_pairing_survives_a_restart():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ble_devices.json"
        reg = BLERegistry(persist_path=path)
        reg.register(ble_type="w5", petkit_id=700, mac="AABBCCDDEEFF",
                     secret="s3cret", link_with=10)
        reg.save()

        fresh = BLERegistry(persist_path=path)
        dev = fresh.get(700)
        assert dev is not None and dev.secret == "s3cret" and dev.link_with == 10


def test_removal_survives_a_restart():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ble_devices.json"
        reg = BLERegistry(persist_path=path)
        reg.register(ble_type="w5", petkit_id=700, mac="AABBCCDDEEFF", link_with=10)
        reg.remove(700)
        assert BLERegistry(persist_path=path).get(700) is None


# --- the id is ours to choose -----------------------------------------------

async def test_an_omitted_id_is_allocated_rather_than_demanded():
    """The id is a handle for our side — it becomes the Home Assistant device
    id — and the firmware reports accessories back by MAC only, never by id.
    So there is nothing for a user to go and look up, and the form should not
    ask."""
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        body = await (await _pair(c, petkit_id=0)).json()
        allocated = body["accessories"][0]["petkit_id"]
        assert allocated >= 900001
        assert ble.get(allocated) is not None
    finally:
        await c.close()


async def test_allocated_ids_do_not_collide_with_each_other_or_a_device():
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=10, device_type="t5", serial_number="SN10")
    reg.get_or_create(petkit_id=900001, device_type="t5", serial_number="ODD")
    app, reg, ble = _panel(reg=reg)
    c = await _client(app)
    try:
        first = (await (await _pair(c, petkit_id=0)).json())["accessories"][0]["petkit_id"]
        await _pair(c, petkit_id=0, mac="AABBCCDDEE02")
        ids = sorted(a["petkit_id"] for a in
                     (await (await c.get("/api/ble")).json())["accessories"])
        assert len(set(ids)) == 2
        # 900001 is taken by a (contrived) real device, so it was skipped.
        assert 900001 not in ids and first >= 900002
    finally:
        await c.close()


# --- which models have no network at all ------------------------------------

def test_the_fountains_without_wifi_are_marked_as_such():
    """Only the W7H has a radio that can reach us.

    W4, W5 and CTW2 are one BLE accessory family — `phldgmn/ha-petkit-ble`
    serves all three from one GATT profile and one parser, and it is a
    cloud-less integration. The CT-W3 manual is explicit that remote access
    needs a PetKit feeder or litter box within ~8 m acting as the WiFi master.
    They were listed as network devices only because PetKit's cloud API models
    them that way, and the account-side view is the same either way.
    """
    from petkit_local.devices.base import Device

    for codename in ("w4", "w5", "ctw2", "ctw3", "k2", "k3"):
        assert Device(device_type=codename, petkit_id=1).is_ble_only, codename
    for codename in ("w7h", "t5", "d4sh", "t3"):
        assert not Device(device_type=codename, petkit_id=1).is_ble_only, codename


def test_a_ble_only_model_registering_over_the_network_says_so(caplog):
    """It cannot happen, and if it does the table above is wrong about that
    model — so the log has to name it rather than let a wrong entity set be the
    first symptom. Registered anyway: a device is never told no."""
    import logging

    reg = DeviceRegistry()
    with caplog.at_level(logging.WARNING):
        device = reg.get_or_create(petkit_id=42, device_type="ctw2")
    assert device.device_type == "ctw2"          # never refused
    assert "BLE-only" in caplog.text
    assert "ctw2" in caplog.text


def test_a_normal_model_registers_quietly(caplog):
    import logging

    reg = DeviceRegistry()
    with caplog.at_level(logging.WARNING):
        reg.get_or_create(petkit_id=43, device_type="t5")
    assert "BLE-only" not in caplog.text


def test_the_w5_frame_decoder_covers_its_whole_family():
    """One protocol, one entity set. The `w5` string was hardcoded in three
    places, so a paired W4 or CTW2 would have decoded to nothing."""
    from petkit_local.devices.ble import W5_PROTOCOL, get_ble_entities

    assert W5_PROTOCOL == {"w4", "w5", "ctw2"}
    for codename in W5_PROTOCOL:
        assert get_ble_entities(codename), codename
    # CTW3 is BLE-only too, but nothing says it speaks this protocol.
    assert get_ble_entities("ctw3") == []


def test_only_the_w5_scan_type_is_a_captured_value():
    """`dev_ble_device` hands the parent a `type` int to scan for. 14 was read
    off a real W5 pairing; the other fountains reuse it on the strength of
    being the same BLE family, which is an assumption and is marked as one."""
    from petkit_local.devices.ble import BLE_TYPE_CONFIRMED, BLE_TYPE_MAP, BLE_TYPES

    assert set(BLE_TYPES) == {"w5", "k3", "w4", "ctw2", "ctw3"}
    assert BLE_TYPE_MAP["w5"] == 14
    assert BLE_TYPE_CONFIRMED == {"w5"}


def test_a_guessed_scan_type_says_it_is_guessed():
    """A wrong `type` fails silently at both ends, so the panel has to be able
    to show which accessories are running on an invented number."""
    from petkit_local.devices.ble import BLEDevice

    assert BLEDevice(ble_type="ctw2", petkit_id=1).scan_type_is_guessed
    assert not BLEDevice(ble_type="w5", petkit_id=1).scan_type_is_guessed
    # K3 is never in the scan list at all; its 0 is a placeholder, not a guess.
    assert not BLEDevice(ble_type="k3", petkit_id=1).scan_type_is_guessed


def test_the_owner_of_the_hardware_can_correct_the_guess():
    """The one person who can find out which value works is the one holding the
    fountain. An override beats waiting for a capture that may never come."""
    from petkit_local.devices.ble import BLEDevice

    default = BLEDevice(ble_type="ctw3", petkit_id=1, mac="AABBCCDDEEFF")
    assert default.to_ble_list_entry()["type"] == 14

    corrected = BLEDevice(ble_type="ctw3", petkit_id=1, mac="AABBCCDDEEFF",
                          scan_type=17)
    assert corrected.to_ble_list_entry()["type"] == 17
    assert not corrected.scan_type_is_guessed
    # And it survives a restart, or the correction is lost on every reload.
    assert BLEDevice.from_dict(corrected.to_dict()).scan_type == 17
