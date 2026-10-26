ENV_FILE ?= $(abspath v2.env)
export V2_ENV_FILE = $(ENV_FILE)
DC = docker compose --env-file $(ENV_FILE)
TEST_DC = $(DC) -f compose.yaml -f compose.test.yaml
.PHONY: up down demo test e2e lint logs reconcile load live
up:
	$(DC) up -d --build --wait

down:
	$(DC) down

demo:
	$(DC) exec -T market-data python manage.py scenario

test:
	$(TEST_DC) build test-trading test-market-data test-valuation
	$(TEST_DC) run --rm test-trading
	$(TEST_DC) run --rm test-market-data
	$(TEST_DC) run --rm test-valuation

e2e:
	uv run --project services/trading python tools/e2e.py --env-file $(ENV_FILE)

lint:
	uv run --project services/trading ruff check --config services/trading/pyproject.toml .
	uv run --project services/trading ruff format --check .
	python3 tools/check_contracts.py

logs:
	$(DC) logs --tail 100 -f

reconcile:
	$(DC) exec -T trading python manage.py reconcile demo

load:
	$(DC) --profile tools run --rm simulator

live:
	$(DC) --profile live up -d scheduler

broker-test:
	$(DC) exec -T trading python manage.py broker_check
