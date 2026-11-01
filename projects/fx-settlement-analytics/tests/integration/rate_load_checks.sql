USE FxWarehouse;
GO
SET NOCOUNT ON;
DECLARE @hash char(64) = CONVERT(char(64), HASHBYTES('SHA2_256', CONVERT(varchar(36), NEWID())), 2);
DECLARE @payload nvarchar(max) = REPLACE(N'[
 {"rate_date":"2025-01-02","pair":"EUR/USD","rate":"1.25","classification":"observed","source_sha256":"HASH","source_row":2,"input_currencies":"USD"},
 {"rate_date":"2025-01-02","pair":"EUR/GBP","rate":"0.80","classification":"observed","source_sha256":"HASH","source_row":2,"input_currencies":"GBP"},
 {"rate_date":"2025-01-02","pair":"GBP/USD","rate":"1.5625","classification":"derived","source_sha256":"HASH","source_row":2,"input_currencies":"USD+GBP"}
]', 'HASH', @hash);
DECLARE @bad uniqueidentifier = NEWID(), @first uniqueidentifier = NEWID(),
        @replay uniqueidentifier = NEWID(), @conflict uniqueidentifier = NEWID();
DECLARE @invalid nvarchar(max) = JSON_MODIFY(@payload, '$[2].rate', '9.99');
BEGIN TRY
    BEGIN TRY
        EXEC warehouse.LoadRates @bad,@hash,N'fixture://rate-load',N'test-only','2025-01-03',1,'integration-check',@invalid;
        THROW 51000, 'Inconsistent cross rate was accepted.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_MESSAGE() NOT LIKE 'Rate quality checks failed%' THROW;
    END CATCH;
    IF NOT EXISTS (SELECT 1 FROM audit.PipelineRun WHERE run_id = @bad AND status = 'failed' AND rows_loaded = 0)
        THROW 51000, 'Failed batch audit missing.', 1;
    IF NOT EXISTS (SELECT 1 FROM audit.RateReject WHERE run_id = @bad AND row_number = 3)
        THROW 51000, 'Cross-rate rejection evidence missing.', 1;
    IF EXISTS (SELECT 1 FROM warehouse.FactFxRate WHERE source_sha256 = @hash)
        THROW 51000, 'Rejected batch published partial data.', 1;
    EXEC warehouse.LoadRates @first,@hash,N'fixture://rate-load',N'test-only','2025-01-03',1,'integration-check',@payload;
    IF NOT EXISTS (SELECT 1 FROM audit.PipelineRun WHERE run_id = @first AND status = 'succeeded'
        AND rows_received = 3 AND rows_loaded = 3 AND rows_inserted = 3 AND rows_rejected = 0)
        THROW 51000, 'First load counts incorrect.', 1;
    IF (SELECT COUNT(*) FROM warehouse.PublishedFxRate WHERE run_id = @first) <> 3
        THROW 51000, 'Expected three published observations.', 1;
    EXEC warehouse.LoadRates @replay,@hash,N'fixture://rate-load',N'test-only','2025-01-03',1,'integration-check',@payload;
    IF NOT EXISTS (SELECT 1 FROM audit.PipelineRun WHERE run_id = @replay AND status = 'succeeded' AND rows_inserted = 0)
        THROW 51000, 'Replay inserted data or did not succeed.', 1;
    IF (SELECT COUNT(*) FROM warehouse.FactFxRate WHERE source_sha256 = @hash AND run_id = @first) <> 3
        THROW 51000, 'Replay changed original row lineage.', 1;
    SET @invalid = JSON_MODIFY(@payload, '$[0].source_row', 3);
    SET @invalid = JSON_MODIFY(@invalid, '$[1].source_row', 3);
    SET @invalid = JSON_MODIFY(@invalid, '$[2].source_row', 3);
    BEGIN TRY
        EXEC warehouse.LoadRates @conflict,@hash,N'fixture://rate-load',N'test-only','2025-01-03',1,'integration-check',@invalid;
        THROW 51000, 'Changed provenance overwrote immutable facts.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_MESSAGE() NOT LIKE 'Replay conflicts%' THROW;
    END CATCH;
    IF EXISTS (SELECT 1 FROM warehouse.FactFxRate WHERE source_sha256 = @hash AND source_row <> 2)
        THROW 51000, 'Failed replay changed facts.', 1;
    PRINT 'PASS: rejected cross rate, failed audit, atomic publication, retry, safe replay and immutable lineage.';
END TRY
BEGIN CATCH
    DELETE warehouse.FactFxRate WHERE source_sha256 = @hash;
    DELETE audit.RateReject WHERE run_id IN (@bad,@first,@replay,@conflict);
    DELETE audit.PipelineRun WHERE source_sha256 = @hash;
    DELETE audit.SourceFile WHERE source_sha256 = @hash;
    THROW;
END CATCH;
DELETE warehouse.FactFxRate WHERE source_sha256 = @hash;
DELETE audit.RateReject WHERE run_id IN (@bad,@first,@replay,@conflict);
DELETE audit.PipelineRun WHERE source_sha256 = @hash;
DELETE audit.SourceFile WHERE source_sha256 = @hash;
GO
