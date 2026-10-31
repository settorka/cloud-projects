# Elexon ETL

Bounded PN/BOD public archive ingestion into checksum-verified raw files, traceable
Parquet publications and local DuckDB queries. Partitions use UTC archive-filename
dates; repeated snapshots are preserved, not final market curves.

Requires Python 3.13 and uv. Run from this directory:

```sh
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen elexon-etl run --date 2025-01-01
uv run --frozen elexon-etl query --date 2025-01-01 --sql sql/coverage.sql
```

Processing is serial and bounded to seven dates per invocation. Cleanup defaults
to a dry run and protects published outputs. Local data is Git-ignored. Azure Blob
support uses managed identity or Azure CLI credentials, without storage keys.

Contains BMRS data © Elexon Limited copyright and database right.
