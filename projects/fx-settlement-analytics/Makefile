.NOTPARALLEL:
COUNT ?= 1000
SEED ?= 42
PYTHON = uv run python
COMMON_ASSETS = --asset pipeline/common.py=pipeline/common.py \
 --asset scripts/ssis-runtime.ps1=scripts/ssis-runtime.ps1 \
 --asset ssis/build-package.ps1=ssis/build-package.ps1
RATE_ASSETS = $(COMMON_ASSETS) \
 --asset pipeline/__init__.py=pipeline/__init__.py \
 --asset pipeline/download_ecb.py=pipeline/download_ecb.py \
 --asset pipeline/prepare_rates.py=pipeline/prepare_rates.py \
 --asset pipeline/build_rate_batch.py=pipeline/build_rate_batch.py \
 --asset sql/load_rates.sql=sql/load_rates.sql
SETTLEMENT_ASSETS = $(COMMON_ASSETS) \
 --asset pipeline/generate_settlements.py=pipeline/generate_settlements.py \
 --asset pipeline/build_settlement_batch.py=pipeline/build_settlement_batch.py \
 --asset scripts/verify-settlements.ps1=scripts/verify-settlements.ps1 \
 --asset sql/settlements.sql=sql/settlements.sql \
 --asset sql/load_settlements.sql=sql/load_settlements.sql

.PHONY: rates settlements deploy-sql test-sql test model dashboard connect batch
rates:
	$(PYTHON) scripts/run_windows.py scripts/load-rates.ps1 $(RATE_ASSETS)

settlements:
	$(PYTHON) scripts/run_windows.py scripts/load-settlements.ps1 --parameter "Count=$(COUNT)" --parameter "Seed=$(SEED)" $(SETTLEMENT_ASSETS)

deploy-sql:
	$(PYTHON) scripts/run_sql.py sql/schema.sql sql/load_rates.sql
	$(PYTHON) scripts/run_sql.py sql/settlements.sql sql/load_settlements.sql sql/pipeline_health.sql sql/analytics.sql

test-sql:
	$(PYTHON) scripts/run_sql.py tests/integration/warehouse_checks.sql tests/integration/rate_load_checks.sql tests/integration/reconciliation_checks.sql tests/integration/analytics_source_checks.sql

test:
	uv run pytest

model:
	$(PYTHON) ssas/build_model.py
	$(PYTHON) scripts/run_windows.py scripts/deploy-ssas.ps1 --asset ssas/Model.bim=ssas/Model.bim --asset scripts/test-ssas.ps1=scripts/test-ssas.ps1

dashboard:
	$(PYTHON) scripts/run_windows.py scripts/setup-dashboard.ps1 --asset app.py=app.py --asset dashboard_data.py=dashboard_data.py --asset pipeline/connections.py=pipeline/connections.py --asset pyproject.toml=pyproject.toml --asset uv.lock=uv.lock --asset scripts/smoke_dashboard.py=scripts/smoke_dashboard.py --asset scripts/start-dashboard.ps1=scripts/start-dashboard.ps1

connect:
	$(PYTHON) scripts/connect_dashboard.py

batch: rates settlements model

.PHONY: disconnect bastion-off
disconnect:
	$(PYTHON) scripts/connect_dashboard.py --stop

bastion-off:
	$(PYTHON) scripts/bastion_off.py
