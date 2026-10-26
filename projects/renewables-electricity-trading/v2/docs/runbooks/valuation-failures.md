# Missing, stale or incorrect valuation

Inspect the run's state, input versions, leg results and calculation time. `INCOMPLETE` means missing marks and a null total; `STALE` means an expired applied mark. `CURRENT` only describes applied local inputs, not global event completion.

Check valuation queue/outbox progress and `/v1/status`. Verify the Trading trade revision appears in the valuation's `input_versions.trades`. If messages are missing follow queue recovery. If marks are missing, publish a documented synthetic demo scenario or ingest the appropriate labelled data; do not substitute zero.

Request an explicit new run through `POST /v1/valuation-runs` with a portfolio-access token, or run:

```sh
docker compose --env-file v2.env exec -T valuation python manage.py value_portfolio demo
```

Old results are immutable snapshots. Recovery creates a new run rather than editing a prior total. Verify sign, leg quantity, price revision, HALF_EVEN rounding and completeness. A large price move can be real; do not discard it just because P&L changed sharply. These are simplified marks, not official settlement or audited profit.
