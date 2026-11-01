USE FxWarehouse;
GO
SET NOCOUNT ON;
SET XACT_ABORT OFF;
IF IS_SRVROLEMEMBER('sysadmin') <> 0
    THROW 51000, 'Deployment identity must not have server-wide sysadmin rights.', 1;
IF IS_ROLEMEMBER('db_owner') <> 1
    THROW 51000, 'Deployment identity requires ownership of FxWarehouse.', 1;
IF (SELECT COUNT(*) FROM warehouse.DimCurrencyPair) <> 3
    THROW 51000, 'Expected the three supported currency pairs.', 1;
DECLARE @hash char(64) = CONVERT(char(64), HASHBYTES('SHA2_256', CONVERT(varchar(36), NEWID())), 2);
DECLARE @run uniqueidentifier = NEWID();
BEGIN TRANSACTION;
BEGIN TRY
    INSERT audit.SourceFile VALUES (@hash, 'fixture://warehouse-check', 'test-only', SYSDATETIMEOFFSET(), 1);
    INSERT audit.PipelineRun (run_id, source_sha256, code_version, status)
    VALUES (@run, @hash, 'integration-check', 'running');
    INSERT warehouse.FactFxRate VALUES ('20250102', 3, @hash, 1.5625, 'derived', 2, 'USD+GBP', @run);
    IF EXISTS (SELECT 1 FROM warehouse.PublishedFxRate WHERE run_id = @run)
        THROW 51000, 'An unfinished batch leaked into published analytics.', 1;
    BEGIN TRY
        INSERT warehouse.FactFxRate VALUES ('20250102', 3, @hash, 1.5625, 'derived', 2, 'USD+GBP', @run);
        THROW 51000, 'Duplicate warehouse grain was accepted.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() NOT IN (2601, 2627) THROW;
    END CATCH;
    BEGIN TRY
        INSERT warehouse.FactFxRate VALUES ('20250103', 3, @hash, 1.5625, 'observed', 2, 'USD', @run);
        THROW 51000, 'False cross-rate provenance was accepted.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 547 THROW;
    END CATCH;
    BEGIN TRY
        UPDATE audit.PipelineRun SET status = 'succeeded', finished_at = SYSDATETIMEOFFSET(),
            rows_received = 2, rows_loaded = 1, rows_rejected = 0 WHERE run_id = @run;
        THROW 51000, 'A successful batch with inconsistent counts was accepted.', 1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() <> 547 THROW;
    END CATCH;
    DECLARE @other_hash char(64)=CONVERT(char(64),HASHBYTES('SHA2_256',CONVERT(varchar(36),NEWID())),2);
    INSERT audit.SourceFile VALUES (@other_hash,'fixture://other-source','test-only',SYSDATETIMEOFFSET(),1);
    BEGIN TRY
        INSERT warehouse.FactFxRate VALUES ('20250102',1,@other_hash,1.25,'observed',2,'USD',@run);
        THROW 51000,'Fact accepted a source different from its load run.',1;
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER()<>547 THROW;
    END CATCH;
    UPDATE audit.PipelineRun SET status = 'succeeded', finished_at = SYSDATETIMEOFFSET(),
        rows_received = 1, rows_loaded = 1, rows_rejected = 0 WHERE run_id = @run;
    IF (SELECT COUNT(*) FROM warehouse.PublishedFxRate WHERE run_id = @run AND rate = 1.5625) <> 1
        THROW 51000, 'A completed batch did not publish the expected rate.', 1;
    ROLLBACK;
    PRINT 'PASS: scoped permissions, dimensions, publication boundary, grain, provenance and row accounting.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK;
    THROW;
END CATCH;
GO
