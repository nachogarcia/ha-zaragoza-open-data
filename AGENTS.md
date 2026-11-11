# Working in this repo

Home Assistant custom integration for Zaragoza Open Data (Python) plus its Lit search card and an
Assist blueprint. These are the rules that matter day to day.

## Architecture

- **Two layers.** `custom_components/zaragoza_open_data/api/` reads the sources: models, ports,
  one adapter per source and the operator-then-city fallback. It never imports `homeassistant`
  or anything outside `api/`. The rest is the Home Assistant side: setup, coordinators,
  entities, flows, actions, repairs.
- **Providers:** `api/providers.py` is the one place that decides which adapter serves which port,
  and in what order: bus from Avanza then the city, Bizi from GBFS then the city, the rest from
  the city.
- **Coordinators:** one per kind in `coordinator.py`, on one base (`_SourceCoordinator`) that keeps
  the last good data through a short failure, then makes the entities unavailable and logs the
  outage once, and once more when it ends.
- **Tests** come in layers (see "Testing"): unit, integration on recorded responses, live,
  acceptance through Home Assistant, and architecture. Among its checks, `tests/architecture/`
  keeps `api/` free of Home Assistant and `en.json` and `es.json` with identical keys.

## Development conventions

- **TDD,** with tests through public entry points: ruff `SLF001` applies to `tests/**`, and patch
  the HTTP boundary, never a private helper.
- **Tooling:**
  - `uv` with a `uv.lock`
  - make targets `test`, `lint`, `format`, `types`
  - Home Assistant's test package `pytest-homeassistant`, the release of the Home Assistant
    version the tests run on; the frontend and conversation pins come from that release's
    manifests
  - Home Assistant core's ruff configuration, plus `SLF001` for tests
  - mypy `--strict`
  - the card: Node 22 or 24, npm with exact versions and a committed `package-lock.json`;
    `make card` lints, tests and builds it into `custom_components/zaragoza_open_data/frontend/`
    (the built file is committed; CI fails when it doesn't match the source)
- **Code:** every function annotated; frozen dataclasses for data; no exports from
  `__init__.py`; comments explain why.
- **Typing:**
  - Python: mypy `--strict` with no `Any`, `cast` or bare `type: ignore` in the integration;
    tests are type-checked too.
  - Codes: `StopCode`/`StationCode` (`NewType`) so codes of different kinds can't be mixed.
  - Raw JSON: typed readers that turn a wrong shape into `SourceUnavailableError`.
  - Options and subentry data: read only through typed objects.
  - Datetimes: models reject naive datetimes.
  - The card: TypeScript `strict` (plus `noUncheckedIndexedAccess` and
    `exactOptionalPropertyTypes`), no `any`, Home Assistant types from
    `home-assistant-js-websocket`.
  - Action responses: built in one module, mirrored in the card's types, and pinned by shared
    test fixtures.
- **Errors users see:** translation keys and placeholders, never text built with the data.
- **Logging:** Home Assistant's normal style. Expected outages log once when they start and once
  when they end; nothing at warning level for normal situations.

## Testing

Tests cover behaviour, always: named for it, driven through the public entry point its real
caller uses, asserting what a caller can observe (return values, entity states and attributes,
history, requests sent to providers, log records, repair issues, the rendered card). Never
private state, never mocks of our own code.

Behaviour is tested in layers, even when that covers the same behaviour more than once:

| Layer | Folder | Fakes only |
| --- | --- | --- |
| Unit | `tests/unit/` | the unit's collaborators |
| Integration | `tests/integration/` | provider HTTP (recorded real responses) |
| Integration, live | `tests/integration/live/` | nothing (`live` marker, daily CI) |
| Acceptance | `tests/acceptance/` | provider HTTP and time |
| Architecture | `tests/architecture/` | nothing |

Acceptance is the default layer: every behaviour has at least one acceptance test. Coverage across
the default layers combined: the config, options and subentry flows (`config_flow.py`) 100%, the
whole integration at least 95%. `make test` fails below either.

## Deliberately left out (don't add back)

| Left out | Why |
| --- | --- |
| A separate domain layer, DDD modules, value-object wrappers per id | Everything is a read; the rules are a handful of small methods on the models. |
| `application/` layer, use cases, CQRS, a dependency-injection container | No business commands; setup in `__init__.py` wires the clients. |
| Separate circuit-breaker and throttle classes | "Fallback for 5 min" and "bus stops one at a time" cover the real risks. |
| More than one architecture rule | Two code layers need one import rule (plus translation parity). |
| pytest-testmon, commit tags, per-layer agent docs, ADRs | Built for a large multi-developer codebase. |
| Event-name logging, long docstrings, "one dot per line", experimental ruff rules | Clash with Home Assistant's own style. |
| A maintainers' command-line tool, a week-long cache of the bus list | The live tests and a fixture-capture script do the job; the list is three requests when a picker opens. |
