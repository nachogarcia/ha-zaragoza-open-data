# VIRTUAL_ENV from another project makes uv warn; this project uses its own .venv.
unexport VIRTUAL_ENV

COV = --cov=custom_components.zaragoza_open_data --cov-report=term-missing --cov-fail-under=95
# npm writes this on every install: the card's tools are reinstalled when the lockfile changes.
CARD_TOOLS = frontend/node_modules/.package-lock.json

.PHONY: test test-unit test-integration test-acceptance test-live lint format types types-py types-card card card-fixtures

# The flows are what people click through, so every line of them is tested.
test:
	uv run pytest tests/unit tests/integration tests/acceptance tests/architecture $(COV)
	uv run coverage report --include='*/config_flow.py' --fail-under=100

test-unit:
	uv run pytest tests/unit --no-cov

test-integration:
	uv run pytest tests/integration --no-cov

test-acceptance:
	uv run pytest tests/acceptance --no-cov

test-live:
	uv run pytest -m live --no-cov

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

types: types-py types-card

types-py:
	uv run mypy custom_components scripts tests

types-card: $(CARD_TOOLS)
	cd frontend && npm run typecheck

# Lints, tests and builds the card into the integration, from a clean install as in CI.
card:
	cd frontend && npm ci && npm run lint && npm test && npm run build

$(CARD_TOOLS): frontend/package-lock.json
	cd frontend && npm ci

# The card's tests replay the actions' response and error snapshots: each
# `test_<…>_snapshot[<name>].json` is copied as `<name>.json`. Nothing is
# deleted: tests/architecture/test_card_fixtures.py names any copy left to remove.
ACTION_SNAPSHOTS = tests/acceptance/snapshots/test_actions
CARD_FIXTURES = frontend/test/fixtures

card-fixtures:
	mkdir -p $(CARD_FIXTURES)
	for snapshot in $(ACTION_SNAPSHOTS)/*.json; do \
		name=$${snapshot##*\[}; \
		cp "$$snapshot" "$(CARD_FIXTURES)/$${name%\]*}.json"; \
	done
