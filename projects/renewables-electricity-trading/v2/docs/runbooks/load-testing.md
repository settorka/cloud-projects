# Bounded load tests

Run `make demo` and wait for four Trading positions. Start with 100 requests at 10/s:

```sh
make load
```

Explicit stress run (example-only local token is already passed to the tools container):

```sh
docker compose --env-file .env --profile tools run --rm simulator python /tools/simulator.py --url http://trading:8000 --requests 1000 --rate 1000 --concurrency 100 --duplicates
```

This targets one portfolio/interval and deliberately exposes lock contention. It is not a promise of 1,000 accepted trades/s. Trades use tiny quantities to limit accidental exposure. Re-seed or use an isolated portfolio before comparing runs; existing positions affect legitimate rejections.

The generator uses a seeded open-loop schedule and caps in-flight requests. Report intended/sent requests, generator shedding, scheduling lag, response outcomes, idempotent replays, latency percentiles and completion rate. Count unique accepted bookings separately from HTTP 201 replays. It does not blindly retry unknown outcomes with new keys.

During the run inspect `docker stats`, API latency, queue/outbox state and database lock waits. Afterward run `make reconcile`; verify no duplicate keys, partial trades or position drift. Save results with host architecture/resource limits and git revision in `docs/verification.md`; do not infer AWS performance from a laptop test.

Stop with Ctrl-C; pending request outcomes can be unknown. Preserve keys/results when investigating. Increase rate gradually and test many portfolios and multi-interval shapes before making a supported-capacity claim.
