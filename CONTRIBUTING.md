# Contributing

## What helps

**A report that your model works.** This one is easy to skip, because nothing is
wrong. But one person owns one litter box, so every other model in the README is
inference until somebody says otherwise, and only an owner can change that. *"T4, everything
works"* is enough to move a model up the table, and issues that report nothing
wrong are welcome here. There is a
[Device report](https://github.com/alex-so-3/petkit-local/issues/new?template=device_report.yml)
template that asks for nothing you would have to go and collect.

Also welcome:

- **Payload captures**, when a model does something unexplained. Most remaining
  unknowns are "what does model X actually send?".
- **New models.** A codename in `utils/const.py`, plus any spelling differences in
  `devices/state_parsers.py`, is usually the whole change.
- **Entity fixes.** A wrong unit, a wrong device class, a control that does not
  take effect. Common on models nobody has tested, because their definitions come
  from a client of PetKit's *cloud* API and the cloud's field names are not always
  the device's.

## Before you attach a capture, read it

A capture is a verbatim recording of everything the device said and was told.
Nothing in it is filtered, because it is only useful if it is exact.

Any of these files can contain your **Wi-Fi SSID**, your LAN addresses, the device
serial and its signing secret. If proxy mode was on, `proxy_http.jsonl` and
`proxy_mqtt.jsonl` also carry the **full exchanges with PetKit, including your
account credentials**, which is enough for someone else to talk to their cloud as
you.

`requests.jsonl`, `state_report.jsonl`, `mqtt.jsonl` and `event_report.jsonl`
usually answer the question on their own. Grep your SSID out first and attach only
what the question needs.

## Working on the code

```sh
cd addon
pip install -e ".[dev]"
pytest                              # the whole suite
pytest -k stitch                    # by name
ruff check petkit_local/ tests/
```

The suite needs no device, no broker and no network. CI runs it on Python 3.11 and
3.12, imports every module so a runtime-only one cannot break unnoticed, and builds
the container image for amd64, arm64 and armv7, because a passing test suite says
nothing about whether the image builds.

The panel's JavaScript and CSS are prettier-formatted, and CI checks it:

```sh
npx prettier@3 --write addon/petkit_local/web/static/{app.js,styles.css}
```

Please run the tests before opening a PR.

## Things that are easy to break

- **Entity keys are user state.** Renaming one orphans that entity in every
  existing installation and loses its history. Labels can change freely; keys
  change only deliberately.
- **Protocol facts live in `events/codes.py`**, graded by the evidence behind
  them. Add a code there rather than in a private set somewhere, and say what
  convinced you. Where a capture and the firmware disagree, the row is marked
  `conflicted` rather than quietly picking one.
- **Nothing is written to a device on a guess.** A setting whose value has never
  been observed is left unset rather than given an invented default, because
  `dev_device_info` serves those values straight back to the device.

The invariants worth knowing before a larger change are collected in
[`.claude/CLAUDE.md`](.claude/CLAUDE.md), which points at the module docstrings
that document each one in full.

## House style

Full type hints. Comments that explain *why* rather than restate the code. Match
the file you are editing.
