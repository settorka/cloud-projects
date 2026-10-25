# Fixture policy

`manage.py scenario` creates deterministic-shape synthetic inputs relative to tomorrow, so a fresh deployment always has valid future delivery intervals. Four intervals have forecast 100 MWh and mark £80/MWh unless overridden. Publication time is real and source revisions are persisted.

`synthetic-replay.json` is a fixed historical example for duplicate/version replay, not a live booking forecast. Its explicit timestamps intentionally do not move. Tests use HTTPX recorded-shape data inline and never call the network. No Elexon response is relabelled as a private asset forecast.
