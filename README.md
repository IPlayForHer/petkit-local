# PetKit Local

PetKit's devices route everything through PetKit's servers: the app, the history, the notifications,
and the video from inside your home. This is a stand-in for those servers that runs on your own
machine. Your device connects to it the same way it connected to them and behaves the same, except
that what it records now stays with you. It works with the internet unplugged, and Home Assistant is
supported but not required.

<details>
<summary><b>📸 Screenshots</b></summary>

<br>

**Timeline.** One card per visit: how long, how heavy, what the camera saw, and which cat it was.
Filterable per pet and per day.

![The Timeline tab](assets/panel-timeline.png)

**Devices.** Live state, every entity, editable controls and the named actions.

![The Devices tab](assets/panel-devices.png)

**AI / Pets.** Mugshots are pushed to the camera's own NPU, which matches against them on the
device. The panel says plainly when a box is still using photos cached from PetKit's cloud.

![The AI and Pets tab](assets/panel-pets.png)

**Provision.** Wi-Fi credentials, the server address and the timezone, handed to a device over
Bluetooth from the browser. No PetKit app involved.

![The Provision tab](assets/panel-provision.png)

**Patchers.** Applied and undone from here, each one explaining exactly what it changes on the
device and how much space it needs.

![The Patchers tab](assets/panel-patchers.png)

**Setup.** Proxy mode for adding models, and the guards that stop the real cloud pushing firmware,
shell commands or a log upload through it.

![The Setup tab](assets/panel-setup.png)

</details>

## ✨ Features

- **One container, nothing to maintain around it.** Python in a single process. No database server,
  no web server, no queue. Install it as a Home Assistant app, or `docker compose up`.
- **Set a device up without the PetKit app at all.** Wi-Fi credentials, the server address and the
  timezone go over Bluetooth straight from your browser.
- **The recordings stay on your disk.** It stands in for the cloud's object storage, so the clips
  and snapshots the device uploads are decrypted, converted and filed where Home Assistant's media
  browser can play them, sorted by device and day.
- **A timeline laid out like the official app.** One card per visit with its video, its waste and
  stool-health photos, and which cat it was, instead of a stream of raw events.
- **Face recognition on the device itself.** Photos you register are pushed to the camera's NPU and
  matched there, so visits are attributed to the right cat without anything leaving your network.
- **Device patching from the panel.** Certificate trust, local camera streaming and local storage
  are applied, and undone, from a tab.
- **Bluetooth accessories show up too.** A Pura Air spray or an EverSweet fountain paired to a box
  appears as its own Home Assistant device, relayed through it.
- **Home Assistant is optional.** Entities appear by themselves over MQTT discovery when you want
  them; the local cloud and the web panel work without it.
- **It tells you when something reaches for the cloud.** Proxy mode is there for adding models, and
  what it blocks on the way through is listed.
- **The camera feed, as a stream Home Assistant can actually take.** A bundled go2rtc turns the
  patched device's video into RTSP, so it plays in a Generic Camera or anything else that speaks it.
  It only pulls from the device while somebody is watching, and it holds a single connection —
  which matters, because the device's own server wants seconds between them.

## 🐈 Supported devices

**Confirmed working.** This is the whole list, and it is one box — the author's. Every other model
below is inference until somebody reports back.

| Product | Codename | Camera | On-device AI |
|---|---|---|---|
| Purobot Max Pro 2 | T5 | ✅ | ✅ |

**Should work.** Same firmware family, and the protocol was verified against their firmware — but
nobody has run one.

| Product | Codename | Camera | On-device AI |
|---|---|---|---|
| Purobot Ultra | T6 | ✅ | ✅ |
| Purobot Crystal Duo | T7 | ✅ | ✅ |

**Supported, not tested.** Entity definitions exist and should be close, but most come from
[pypetkitapi](https://github.com/Jezza34000/py-petkit-api), a client of PetKit's *cloud* API — whose
field names are not always the device's. Expect the common things to work and the occasional entity
to sit at "unknown".

| Product | Codename | Camera | On-device AI |
|---|---|---|---|
| Pura X | T3 | — | — |
| Pura Max | T4 | — | — |
| YumShare Solo | D4H | ✅ | — |
| YumShare Solo 2 | D4H | ✅ | ✅ |
| YumShare Dual-Hopper | D4SH | ✅ | — |
| YumShare Dual-Hopper 2 | D4SH | ✅ | ✅ |
| Fresh Element Solo | D4 | — | — |
| Feeder D3 / D4s | D3, D4S | — | — |
| Feeder / Feeder Mini | feeder, feedermini ‡ | — | — |
| EverSweet Ultra AI | W7H | ✅ | ✅ |
| EverSweet 3 Pro | W5 † | — | — |
| EverSweet | W4 † | — | — |
| EverSweet Solo 2 | CTW2 † | — | — |
| EverSweet Max Cordless | CTW3 † | — | — |
| Pura Air smart spray | K2, K3 † | — | — |

**† No Wi-Fi — Bluetooth only.** They pair to a mains-powered litter box or feeder, which relays for
them, so their readings arrive inside its traffic; no parent nearby means no data at all. They still
appear as their own Home Assistant devices. Pair them from the **Devices** tab, on the panel of the
device that will relay for them — a parent never discovers anything, it asks the cloud what to scan
for, and the cloud is now this. For every fountain but the W5 that scan number is a guess: if one
never reports, change **Scan type** under Advanced and tell us which value worked.

**‡ No Bluetooth radio at all.** So the Provision tab cannot reach one — DNS redirect only. And its
signup carries no id and no serial, which this add-on has no way to mint, so a factory-fresh feeder
might be refused before it gets anywhere. Nobody has run one.

**Not listed at all?** It should still work with **proxy mode** on — every request is forwarded to
PetKit and the device gets the real cloud's answer, so it keeps behaving normally while everything
it says is recorded. That recording is exactly what is needed to add it properly; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## 🤖 Is this project another vibecoded AI slop?

<details>
<summary><b>Yes, it is.</b></summary>

<br>

Most of the code was written with an LLM. Saying so up front seems better than letting you work it
out on your own later.

The scope is the reason, and so is the hurry. A fake cloud, an MQTT broker, a media pipeline, ten
entity platforms, a web panel, on-device patchers: more than I would have got through alone in my
spare time, and I wanted my litter box off a Chinese cloud sooner than that would have taken. It has
a camera and a microphone pointed into my flat.

What matters more is the part it did not do. It wrote code; it did not decide what the protocol
means. That came from packet captures off my own litter box and from strings and functions in the
firmware, and where those two sources disagree the code says so rather than quietly picking one.
`events/codes.py` grades every protocol fact by what backs it: confirmed, inferred, unverified,
conflicted.

Where something is still a guess it says so. The device table above is one model I own and a longer
list I cannot vouch for.

If the code is confidently wrong somewhere, that is a bug and I want the issue. Contributions are
welcome however you write them, LLM-assisted or not. What counts is whether it is right about the
device, and that you can point at what convinced you: a capture, a firmware string, your own box. If
you would rather not run LLM-assisted software on your network, that is fair and I will not try to
talk you out of it.

</details>

## 📦 Install

<details>
<summary><b>Home Assistant app</b> — for Home Assistant OS or Supervised</summary>

<br>

**Settings → Apps → Install app → ⋮ → Repositories**, add:

```
https://github.com/alex-so-3/petkit-local
```

> Recent Home Assistant releases renamed **Add-ons** to **Apps** in the interface. If your menu still
> says *Settings → Add-ons → Add-on Store*, you are on an older version — the same ⋮ → Repositories
> step is there. Everything under the hood is still called an add-on, so `ha addons`, the Supervisor
> API and this repository's own layout keep that word.

Install **PetKit Local**, then open its **Configuration** tab before starting it:

- **If you run the Mosquitto app**, there is nothing to fill in — the Supervisor hands over the
  broker and its credentials.
- **If your broker is anywhere else**, set `ha_mqtt_host` (and `ha_mqtt_user` / `ha_mqtt_pass` if it
  wants them). Leave it empty and everything still works except the part you probably came for:
  nothing is published to Home Assistant, so no entities appear.

`api_url` can stay empty — it asks the Supervisor for your host's LAN IP. Now start it and open the
panel from the sidebar. Every option, the ports and troubleshooting are in
[the documentation](addon/DOCS.md).

</details>

<details>
<summary><b>Docker</b> — for Home Assistant Container, Core, or no Home Assistant at all</summary>

<br>

Apps need the Supervisor, so the app store only exists on Home Assistant OS and Supervised.
Everywhere else this runs as an ordinary container — same image, same features, configured on the
command line instead of from an options screen.

`docker-compose.yml` in the repository root is ready to use. Set the two `CHANGE-ME` values — the
address your devices will call, and your MQTT broker — and start it:

```sh
docker compose up -d --build
```

The panel is then on port 8099. Note that it has **no authentication** of its own: as an app
it sits behind Home Assistant Ingress, and there is no Ingress here. The compose file explains how
to bind it to localhost instead if the machine is not somewhere you trust.

</details>

<details>
<summary><b>Straight from source</b> — not recommended</summary>

<br>

No isolation, no restart-on-failure, and you own the dependencies. Fine for development or a quick
look; use one of the two above for anything you rely on.

```sh
cd addon
pip install -r requirements.txt
python -m petkit_local.main \
    --port 8080 \
    --api-url "http://<your-host>:8080/6/" \
    --data-dir ./data \
    --no-ha
```

`--help` lists every flag; the useful ones are `--mqtt-tls` / `--mqtt-tls-port`, `--web-port`,
`--offline-timeout` and `--debug`. `--no-ha` turns the Home Assistant side off entirely — drop it and
pass `--ha-mqtt-host` to publish entities.

</details>

## 🔀 Point a device at it

A device only ever talks to the URL it was provisioned with, so it has to be redirected. This is the
real work of setting the project up; everything else configures itself.

**BLE provisioning works on every model** and is the most reliable route. Re-run Wi-Fi setup over
Bluetooth and hand the device an `apiServers` value pointing here instead of at PetKit. The panel's
**Provision** tab does it from your browser (Chrome or Edge, on a page served over HTTPS). It is also
the only way a device ever gets a timezone — one provisioned without it stamps UTC onto its video.

**ESP32 models** — Pura X, Pura Max and the non-camera feeders — can also be redirected by
DNS, because they talk plain HTTP. Which name to redirect is a property of your device rather than of
its model: these are handed their API server during Bluetooth setup too, so it is whichever of
PetKit's regional servers the app gave it. Your DNS server's query log will name it — or redirect
every PetKit domain and be done. Note that DNS only changes where a *name* resolves, not the port:
the device keeps dialling whatever its provisioned `apiServers` URL says, which on a factory device
is port 80 — so **this has to be reachable on port 80**, or you have to change the port by
provisioning over BLE instead. The app maps its API to host port 8080 by default; a DNS-redirected
device needs that changed to 80.

**Ingenic/Linux models** — Purobot, YumShare, EverSweet Ultra AI — enforce HTTPS, so a DNS override
alone will not do: you would also have to serve a certificate for their name and make the device
trust it. Use BLE provisioning, which sidesteps HTTPS entirely.

These models also compile the cloud's CA into their `ctrl` binary, so they will not trust any other
MQTT broker until it is patched. The **Patchers** tab does that for you.

## 🔧 Under the hood

Some of this exists because the protocol had to be worked out first, and those tools are still in
the box — useful if you want to add a model, or are just curious.

- **Proxy mode** forwards every request to the real PetKit API and answers the device with the
  cloud's own reply, so both the payloads and the firmware's reaction to them are observable. Shell
  commands, firmware pushes, credentials and anything else that would hand the device back to PetKit
  are stripped on the way through — matched by content, not by endpoint, so a hostile field is caught
  on an endpoint nobody expected it on.
- **Payload capture** to JSONL, browsable and downloadable from the panel.
- **The device's own debug log** — the firmware uploads `devRun.log` here instead of to PetKit.
- **On-device patchers**: MQTT certificate bypass, local media storage, CA trust, local camera
  streaming, persistent SSH. Each checks the binary really is a MIPS executable and that the device
  has room, before writing anything.
- **Human-readable event decoding.** Six protocol namespaces, each code carrying its meaning, its
  evidence grade and the firmware function behind it — so the panel can explain an event instead of
  printing a number.

The protocol invariants a contributor must not break are summarised in
[`.claude/CLAUDE.md`](.claude/CLAUDE.md).

## 🙌 Contributing

**A report that your model works is worth opening an issue for.** There is exactly one device behind
the "confirmed working" list, so everything else is inference until an owner says otherwise. *"T4,
everything works"* is enough to move a model up the table, and issues that report nothing wrong are
welcome here.

Also: captures from a model doing something unexplained, new codenames, and entity fixes. See
[CONTRIBUTING.md](CONTRIBUTING.md) for what each of those involves, how to develop against this
without a device, and what is easy to break.

> **⚠ If you attach a capture, read it first.** It records everything the device said and was told,
> unfiltered, which can include your Wi-Fi SSID and, if proxy mode was on, your PetKit credentials.

## 🙇 Credits

Two projects published reverse engineering that saved a great deal of time here. This is an
independent implementation and no code was copied from either, but they answered questions that
would otherwise have had to be answered from scratch:

- **[dwyschka/localkit](https://github.com/dwyschka/localkit)** and its
  [MQTT broker](https://github.com/dwyschka/localkit-broker) — the original local PetKit cloud
  replacement, in PHP. Which endpoints a device calls, what shape it expects back, how the MQTT
  topics are laid out and how a BLE accessory is proxied were all first worked out and published by
  Daniel. Documentation at [localkit.io](https://localkit.io/).
- **[Jezza34000/homeassistant_petkit](https://github.com/Jezza34000/homeassistant_petkit)** and
  **[pypetkitapi](https://github.com/Jezza34000/py-petkit-api)** (both MIT) — the Home Assistant
  entity definitions, device groupings and value mappings started from this integration and its data
  models.

The rest was worked out here, against real firmware and real traffic: the event code tables and the
evidence grade on every row, the MQTT authentication, the media encryption and the stitching of a
visit's chunks, the on-device patches, and the handful of device behaviours that only ever show up
in a capture.

## ⚖️ License

[GPL-3.0-or-later](LICENSE). Free to use, study, modify and redistribute, including commercially —
but a modified version you distribute has to stay under the same terms with its source available.

Third-party components keep their own licences: the reference work above (both Jezza34000 projects
are MIT), the shipped `dropbear-mipsel` binary carries its own notice in
[`addon/petkit_local/web/static/bin/`](addon/petkit_local/web/static/bin/), and the image installs
FFmpeg from Alpine (Debian on 32-bit ARM).
