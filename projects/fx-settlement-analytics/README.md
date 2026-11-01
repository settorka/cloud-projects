# FX settlement analytics

ECB reference-rate ingestion and reproducible synthetic trade/payment fixtures.

Run `uv sync --group dev` then `uv run pytest`. Real source rates are informational;
trades and bank payments are synthetic. Missing rates are not forward-filled.
Later PRs add Azure Windows, SQL Server/SSIS, SSAS and the read-only dashboard.
