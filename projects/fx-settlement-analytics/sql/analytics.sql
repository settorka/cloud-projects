USE FxWarehouse;
GO
IF SCHEMA_ID('analytics') IS NULL EXEC('CREATE SCHEMA analytics AUTHORIZATION dbo');
GO
CREATE OR ALTER VIEW analytics.Batch AS
SELECT b.batch_id AS BatchId,b.as_of_date AS SimulationAsOf,b.reconciled_as_of AS ReconciledAsOf,
    r.finished_at AS ReconciledAt,b.seed AS Seed,b.generator_version AS GeneratorVersion,b.is_synthetic AS IsSynthetic,
    TRY_CONVERT(int,JSON_VALUE(b.manifest_json,'$.trade_count')) AS TradeCount,
    b.rate_source_sha256 AS RateSourceHash
FROM audit.SettlementBatch b JOIN audit.PipelineRun r ON r.run_id=b.reconciliation_run_id AND r.status='succeeded';
GO
CREATE OR ALTER VIEW analytics.Currency AS SELECT currency AS Currency FROM warehouse.DimCurrency;
GO
CREATE OR ALTER VIEW analytics.Counterparty AS
SELECT counterparty AS Counterparty,display_name AS DisplayName FROM warehouse.DimCounterparty;
GO
CREATE OR ALTER VIEW analytics.CurrencyPair AS
SELECT pair_code AS Pair FROM warehouse.DimCurrencyPair;
GO
CREATE OR ALTER VIEW analytics.SettlementDate AS
SELECT calendar_date AS [Date],calendar_year AS [Year],calendar_month AS [Month],day_of_month AS [Day]
FROM warehouse.DimDate;
GO
CREATE OR ALTER VIEW analytics.SettlementLeg AS
SELECT batch_id AS BatchId,leg_id AS LegId,trade_id AS TradeId,counterparty AS Counterparty,pair_code AS Pair,
    currency AS Currency,direction AS Direction,due_date AS DueDate,expected_amount AS ExpectedAmount,
    allocated_amount AS AllocatedAmount,outstanding_amount AS OutstandingAmount,is_late AS IsLate,
    is_overdue AS IsOverdue,settlement_status AS SettlementStatus
FROM warehouse.SettlementStatus;
GO
CREATE OR ALTER VIEW analytics.Payment AS
SELECT batch_id AS BatchId,payment_id AS PaymentId,reference AS Reference,currency AS Currency,
    direction AS Direction,payment_date AS PaymentDate,amount AS Amount,allocated_amount AS AllocatedAmount,
    unapplied_amount AS UnappliedAmount,payment_status AS PaymentStatus,counterparty AS Counterparty,pair_code AS Pair
FROM warehouse.PaymentExceptions;
GO
CREATE OR ALTER VIEW analytics.TradeLineage AS
SELECT t.batch_id AS BatchId,t.trade_id AS TradeId,t.source_row AS TradeSourceRow,
    t.run_id AS TradeRunId,run.code_version AS TradeCodeVersion,
    b.trade_source_sha256 AS TradeSourceHash,src.blob_path AS TradeBlobPath,
    t.rate_date AS RateDate,t.rate_source_sha256 AS RateSourceHash,
    rate.source_row AS RateSourceRow,rate.input_currencies AS RateInputCurrencies,
    rate.classification AS RateClassification,rate.run_id AS RateRunId,
    ecb.source_url AS RateSourceUrl,ecb.blob_path AS RateBlobPath
FROM warehouse.FactTrade t JOIN audit.SettlementBatch b ON b.batch_id=t.batch_id
JOIN audit.SourceFile src ON src.source_sha256=b.trade_source_sha256
JOIN audit.SourceFile ecb ON ecb.source_sha256=t.rate_source_sha256
JOIN audit.PipelineRun run ON run.run_id=t.run_id
JOIN warehouse.FactFxRate rate ON rate.rate_date=t.rate_date AND rate.pair_id=t.pair_id AND rate.source_sha256=t.rate_source_sha256;
GO
CREATE OR ALTER VIEW analytics.PaymentLineage AS
SELECT p.batch_id AS BatchId,p.payment_id AS PaymentId,p.source_row AS PaymentSourceRow,p.run_id AS PaymentRunId,
    run.code_version AS CodeVersion,b.payment_source_sha256 AS SourceHash,s.blob_path AS BlobPath
FROM warehouse.FactPayment p JOIN audit.SettlementBatch b ON b.batch_id=p.batch_id
JOIN audit.SourceFile s ON s.source_sha256=b.payment_source_sha256 JOIN audit.PipelineRun run ON run.run_id=p.run_id;
GO
CREATE OR ALTER VIEW analytics.PipelineHealth AS
SELECT run_id AS RunId,pipeline_name AS Pipeline,status AS Status,started_at AS StartedAt,finished_at AS FinishedAt,
    elapsed_ms AS ElapsedMs,rows_received AS RowsReceived,rows_loaded AS RowsLoaded,rows_inserted AS RowsInserted,
    rows_rejected AS RowsRejected,recorded_rejections AS RecordedRejections,
    ssis_execution_id AS SsisExecutionId,code_version AS CodeVersion,error_message AS ErrorMessage
FROM audit.PipelineHealth;
GO

CREATE OR ALTER VIEW analytics.Direction AS
SELECT v.Direction FROM (VALUES(CONVERT(varchar(7),'pay')),('receive')) v(Direction);
GO
