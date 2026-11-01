-- Initial rate warehouse slice. Deployment is additive and replay-safe.
USE master;
GO
IF DB_ID(N'FxWarehouse') IS NULL
    CREATE DATABASE FxWarehouse
    ON PRIMARY (NAME = N'FxWarehouse_data', FILENAME = N'F:\fx\sql\FxWarehouse.mdf', SIZE = 64MB, FILEGROWTH = 64MB)
    LOG ON (NAME = N'FxWarehouse_log', FILENAME = N'F:\fx\sql\FxWarehouse_log.ldf', SIZE = 64MB, FILEGROWTH = 64MB);
GO
USE FxWarehouse;
GO
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF SCHEMA_ID(N'audit') IS NULL EXEC(N'CREATE SCHEMA audit');
IF SCHEMA_ID(N'warehouse') IS NULL EXEC(N'CREATE SCHEMA warehouse');
IF OBJECT_ID(N'audit.SourceFile') IS NULL
CREATE TABLE audit.SourceFile (
    source_sha256 char(64) NOT NULL PRIMARY KEY,
    source_url nvarchar(2048) NOT NULL,
    blob_path nvarchar(1024) NOT NULL,
    retrieved_at datetimeoffset NOT NULL,
    byte_count bigint NOT NULL CHECK (byte_count > 0)
);
IF OBJECT_ID(N'audit.PipelineRun') IS NULL
CREATE TABLE audit.PipelineRun (
    run_id uniqueidentifier NOT NULL PRIMARY KEY,
    source_sha256 char(64) NOT NULL REFERENCES audit.SourceFile(source_sha256),
    code_version varchar(64) NOT NULL,
    started_at datetimeoffset NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    finished_at datetimeoffset NULL,
    status varchar(16) NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    rows_received int NULL,
    rows_loaded int NULL,
    rows_rejected int NULL,
    error_message nvarchar(2048) NULL,
    CONSTRAINT CK_RunCounts CHECK (
        rows_received >= 0 AND rows_loaded >= 0 AND rows_rejected >= 0
    ),
    CONSTRAINT CK_RunComplete CHECK (
        status <> 'succeeded' OR (
            finished_at IS NOT NULL AND rows_received IS NOT NULL
            AND rows_loaded IS NOT NULL AND rows_rejected IS NOT NULL
            AND rows_received = rows_loaded + rows_rejected
        )
    )
);
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints WHERE parent_object_id=OBJECT_ID('audit.PipelineRun') AND name='UQ_RunSource')
    ALTER TABLE audit.PipelineRun ADD CONSTRAINT UQ_RunSource UNIQUE(run_id,source_sha256);
IF OBJECT_ID(N'warehouse.DimCurrencyPair') IS NULL
CREATE TABLE warehouse.DimCurrencyPair (
    pair_id tinyint NOT NULL PRIMARY KEY,
    pair_code char(7) NOT NULL UNIQUE,
    base_currency char(3) NOT NULL,
    quote_currency char(3) NOT NULL,
    CONSTRAINT CK_PairCurrencies CHECK (base_currency <> quote_currency)
);
INSERT warehouse.DimCurrencyPair (pair_id, pair_code, base_currency, quote_currency)
SELECT v.* FROM (VALUES (1, 'EUR/USD', 'EUR', 'USD'), (2, 'EUR/GBP', 'EUR', 'GBP'),
    (3, 'GBP/USD', 'GBP', 'USD')) v(pair_id, pair_code, base_currency, quote_currency)
WHERE NOT EXISTS (SELECT 1 FROM warehouse.DimCurrencyPair p WHERE p.pair_id = v.pair_id);
IF OBJECT_ID(N'warehouse.FactFxRate') IS NULL
CREATE TABLE warehouse.FactFxRate (
    rate_date date NOT NULL,
    pair_id tinyint NOT NULL REFERENCES warehouse.DimCurrencyPair(pair_id),
    source_sha256 char(64) NOT NULL REFERENCES audit.SourceFile(source_sha256),
    rate decimal(28, 14) NOT NULL CHECK (rate > 0),
    classification varchar(8) NOT NULL CHECK (classification IN ('observed', 'derived')),
    source_row int NOT NULL CHECK (source_row >= 2),
    input_currencies varchar(7) NOT NULL,
    run_id uniqueidentifier NOT NULL REFERENCES audit.PipelineRun(run_id),
    CONSTRAINT PK_FactFxRate PRIMARY KEY (rate_date, pair_id, source_sha256),
    CONSTRAINT CK_RateInputs CHECK (
        (pair_id = 1 AND classification = 'observed' AND input_currencies = 'USD') OR
        (pair_id = 2 AND classification = 'observed' AND input_currencies = 'GBP') OR
        (pair_id = 3 AND classification = 'derived' AND input_currencies = 'USD+GBP')
    )
);
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_RateRunSource')
    ALTER TABLE warehouse.FactFxRate ADD CONSTRAINT FK_RateRunSource
        FOREIGN KEY(run_id,source_sha256) REFERENCES audit.PipelineRun(run_id,source_sha256);
COMMIT;
GO
CREATE OR ALTER VIEW warehouse.PublishedFxRate AS
SELECT r.rate_date, p.pair_code, r.rate, r.classification,
       r.source_sha256, r.source_row, r.input_currencies, r.run_id
FROM warehouse.FactFxRate r
JOIN warehouse.DimCurrencyPair p ON p.pair_id = r.pair_id
JOIN audit.PipelineRun b ON b.run_id = r.run_id AND b.status = 'succeeded';
GO
