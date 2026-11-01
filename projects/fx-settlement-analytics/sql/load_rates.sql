USE FxWarehouse;
GO
IF OBJECT_ID(N'audit.RateReject') IS NULL
CREATE TABLE audit.RateReject (
    run_id uniqueidentifier NOT NULL REFERENCES audit.PipelineRun(run_id),
    row_number int NOT NULL,
    raw_record nvarchar(max) NOT NULL,
    reason nvarchar(256) NOT NULL,
    PRIMARY KEY (run_id, row_number)
);
IF COL_LENGTH('audit.PipelineRun', 'rows_inserted') IS NULL
    ALTER TABLE audit.PipelineRun ADD rows_inserted int NULL;
IF COL_LENGTH('audit.PipelineRun', 'ssis_execution_id') IS NULL
    ALTER TABLE audit.PipelineRun ADD ssis_execution_id uniqueidentifier NULL, package_sha256 char(64) NULL;
GO
CREATE OR ALTER PROCEDURE warehouse.LoadRates
    @run_id uniqueidentifier,
    @source_sha256 char(64),
    @source_url nvarchar(2048),
    @blob_path nvarchar(1024),
    @retrieved_at datetimeoffset,
    @byte_count bigint,
    @code_version varchar(64),
    @payload nvarchar(max)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF NOT EXISTS (SELECT 1 FROM audit.SourceFile WHERE source_sha256 = @source_sha256)
        INSERT audit.SourceFile VALUES (@source_sha256, @source_url, @blob_path, @retrieved_at, @byte_count);
    IF EXISTS (SELECT 1 FROM audit.SourceFile WHERE source_sha256 = @source_sha256
        AND (source_url <> @source_url OR blob_path <> @blob_path OR byte_count <> @byte_count))
        THROW 51000, 'Source metadata conflicts with existing immutable snapshot.', 1;
    INSERT audit.PipelineRun (run_id, source_sha256, code_version, status)
    VALUES (@run_id, @source_sha256, @code_version, 'running');
    BEGIN TRY
        IF ISJSON(@payload) <> 1 OR LEFT(LTRIM(@payload), 1) <> '['
            THROW 51000, 'Expected a JSON array of prepared rates.', 1;
        SELECT CONVERT(int, j.[key]) + 1 AS row_number, j.value AS raw_record,
            TRY_CONVERT(date, JSON_VALUE(j.value, '$.rate_date'), 23) AS rate_date,
            p.pair_id,
            TRY_CONVERT(decimal(28,14), JSON_VALUE(j.value, '$.rate')) AS rate,
            JSON_VALUE(j.value, '$.classification') AS classification,
            JSON_VALUE(j.value, '$.source_sha256') AS source_sha256,
            TRY_CONVERT(int, JSON_VALUE(j.value, '$.source_row')) AS source_row,
            JSON_VALUE(j.value, '$.input_currencies') AS input_currencies
        INTO #rates
        FROM OPENJSON(@payload) j
        LEFT JOIN warehouse.DimCurrencyPair p ON p.pair_code = JSON_VALUE(j.value, '$.pair');
        CREATE INDEX IX_RateGrain ON #rates(rate_date,pair_id) INCLUDE(row_number,rate,source_row);
        DECLARE @received int = (SELECT COUNT(*) FROM #rates);
        UPDATE audit.PipelineRun SET rows_received = @received WHERE run_id = @run_id;
        IF @received = 0 THROW 51000, 'Empty rate batch.', 1;
        INSERT audit.RateReject
        SELECT @run_id, r.row_number, r.raw_record,
            CASE WHEN r.rate_date IS NULL THEN 'Invalid date'
                 WHEN r.pair_id IS NULL THEN 'Unsupported pair'
                 WHEN r.rate IS NULL OR r.rate <= 0 THEN 'Invalid or nonpositive rate'
                 WHEN r.source_sha256 IS NULL OR r.source_sha256 <> @source_sha256 THEN 'Source hash mismatch'
                 WHEN r.source_row IS NULL OR r.source_row < 2 THEN 'Invalid source row'
                 WHEN EXISTS (SELECT 1 FROM #rates d WHERE d.rate_date = r.rate_date
                      AND d.pair_id = r.pair_id AND d.row_number <> r.row_number) THEN 'Duplicate batch grain'
                 ELSE 'Invalid observed/derived provenance' END
        FROM #rates r
        WHERE r.rate_date IS NULL OR r.pair_id IS NULL OR r.rate IS NULL OR r.rate <= 0
           OR r.source_sha256 IS NULL OR r.source_sha256 <> @source_sha256
           OR r.source_row IS NULL OR r.source_row < 2
           OR r.classification IS NULL OR r.input_currencies IS NULL
           OR NOT ((r.pair_id = 1 AND r.classification = 'observed' AND r.input_currencies = 'USD')
                OR (r.pair_id = 2 AND r.classification = 'observed' AND r.input_currencies = 'GBP')
                OR (r.pair_id = 3 AND r.classification = 'derived' AND r.input_currencies = 'USD+GBP'))
           OR EXISTS (SELECT 1 FROM #rates d WHERE d.rate_date = r.rate_date
                      AND d.pair_id = r.pair_id AND d.row_number <> r.row_number);
        -- Cross rates must be supported by the two same-date, same-source-row inputs.
        INSERT audit.RateReject
        SELECT @run_id, r.row_number, r.raw_record, 'Cross rate lacks consistent same-date inputs'
        FROM #rates r
        WHERE r.pair_id = 3
          AND NOT EXISTS (SELECT 1 FROM audit.RateReject e WHERE e.run_id = @run_id AND e.row_number = r.row_number)
          AND NOT EXISTS (
              SELECT 1 FROM #rates u JOIN #rates g ON g.rate_date = u.rate_date
              WHERE u.pair_id = 1 AND g.pair_id = 2 AND u.rate_date = r.rate_date
                AND u.source_row = r.source_row AND g.source_row = r.source_row
                AND u.source_sha256 = @source_sha256 AND g.source_sha256 = @source_sha256
                AND g.rate > 0 AND u.rate > 0
                AND ABS(r.rate - CAST(u.rate AS decimal(20,10)) /
                    NULLIF(CAST(g.rate AS decimal(20,10)), 0)) <= 0.00000000000002
          );
        DECLARE @rejected int = (SELECT COUNT(*) FROM audit.RateReject WHERE run_id = @run_id);
        UPDATE audit.PipelineRun SET rows_rejected = @rejected WHERE run_id = @run_id;
        IF @rejected > 0 THROW 51000, 'Rate quality checks failed; inspect audit.RateReject.', 1;
        BEGIN TRANSACTION;
        DECLARE @lock int;
        EXEC @lock = sys.sp_getapplock @Resource = 'fx-rate-publication',
            @LockMode = 'Exclusive', @LockOwner = 'Transaction', @LockTimeout = 30000;
        IF @lock < 0 THROW 51000, 'Could not acquire rate publication lock.', 1;
        IF EXISTS (
            SELECT 1 FROM #rates s JOIN warehouse.FactFxRate t
              ON t.source_sha256 = @source_sha256 AND t.rate_date = s.rate_date AND t.pair_id = s.pair_id
            WHERE t.rate <> s.rate OR t.classification <> s.classification
               OR t.source_row <> s.source_row OR t.input_currencies <> s.input_currencies
        ) THROW 51000, 'Replay conflicts with already-published observations.', 1;
        INSERT warehouse.FactFxRate
            (rate_date, pair_id, source_sha256, rate, classification, source_row, input_currencies, run_id)
        SELECT s.rate_date, s.pair_id, @source_sha256, s.rate, s.classification,
            s.source_row, s.input_currencies, @run_id
        FROM #rates s WHERE NOT EXISTS (
            SELECT 1 FROM warehouse.FactFxRate t WHERE t.source_sha256 = @source_sha256
                AND t.rate_date = s.rate_date AND t.pair_id = s.pair_id);
        DECLARE @inserted int = @@ROWCOUNT;
        UPDATE audit.PipelineRun SET status = 'succeeded', finished_at = SYSDATETIMEOFFSET(),
            rows_loaded = @received, rows_rejected = 0, rows_inserted = @inserted WHERE run_id = @run_id;
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        UPDATE audit.PipelineRun SET status = 'failed', finished_at = SYSDATETIMEOFFSET(),
            rows_loaded = 0, rows_inserted = 0, error_message = LEFT(ERROR_MESSAGE(), 2048)
        WHERE run_id = @run_id;
        THROW;
    END CATCH;
END;
GO
