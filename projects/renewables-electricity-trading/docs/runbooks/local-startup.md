# Local startup

Symptoms: new checkout, stopped environment or readiness failure. Impact: no local API availability.

1. Check Docker is running: `docker info`. Copy `.env.example` to `.env` and keep the file out of Git. Defaults are deliberately local-only.
2. Run `make up`. This waits for PostgreSQL, initializes/migrates/seeds services, then starts API/worker roles. Check `docker compose --env-file .env ps -a`; init jobs should exit 0, APIs should become healthy.
3. Run `make demo` once to publish synthetic inputs. Check authenticated Trading positions until four intervals appear.
4. Run `make e2e` for the complete acceptance workflow. Its portfolio is separate from manual demo data.

Diagnosis: `docker compose --env-file .env logs --tail 100 postgres trading-init market-data-init valuation-init trading trading-worker`. Database passwords in `.env` must match the existing volume: editing them does not rotate roles in an initialized PostgreSQL volume. Do not reset the volume to hide a migration error.

Verification: each `/health/ready` returns ready, demo positions have forecast revisions, an authenticated booking changes its interval and the valuation eventually contains its trade revision. A healthy API alone does not prove worker progress.

If public image pulls hang at credential lookup, inspect Docker Desktop/keychain status. Do not publish credentials or change shared Docker settings as part of the project. This is host tooling, not a queue failure.
