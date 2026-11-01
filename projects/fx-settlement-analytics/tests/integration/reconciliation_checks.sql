USE FxWarehouse;
GO
SET NOCOUNT ON;
DECLARE @rate_hash char(64)=CONVERT(char(64),HASHBYTES('SHA2_256',CONVERT(varchar(36),NEWID())),2),
 @trade_hash char(64)=CONVERT(char(64),HASHBYTES('SHA2_256',CONVERT(varchar(36),NEWID())),2),
 @payment_hash char(64)=CONVERT(char(64),HASHBYTES('SHA2_256',CONVERT(varchar(36),NEWID())),2),
 @rate_run uniqueidentifier=NEWID(),@load uniqueidentifier=NEWID(),@replay uniqueidentifier=NEWID(),
 @early uniqueidentifier=NEWID(),@late uniqueidentifier=NEWID(),@repeat uniqueidentifier=NEWID(),@bad uniqueidentifier=NEWID();
DECLARE @manifest nvarchar(max)=N'{"classification":"synthetic","generator_version":1,"seed":42,"trade_count":1,"payment_count":9,"as_of_date":"2025-01-08","rate_source_sha256":"'+@rate_hash+'","files":{"trades.csv":{"sha256":"'+@trade_hash+'","bytes":100},"payments.csv":{"sha256":"'+@payment_hash+'","bytes":100}}}';
DECLARE @batch char(64)=LOWER(CONVERT(char(64),HASHBYTES('SHA2_256',CONVERT(varchar(max),@manifest COLLATE Latin1_General_100_BIN2_UTF8)),2));
DECLARE @trades nvarchar(max)=N'[{"trade_id":"T1","pair":"EUR/USD","counterparty":"CP01","side":"BUY_BASE","rate_date":"2025-01-02","trade_date":"2025-01-02","settlement_date":"2025-01-06","base_amount":"100.00","quote_amount":"125.00","rate_source_sha256":"'+@rate_hash+'"}]';
DECLARE @payments nvarchar(max)=N'[
 {"payment_id":"P1","reference":"T1:B","currency":"EUR","direction":"receive","payment_date":"2025-01-06","amount":"40.00"},
 {"payment_id":"P2","reference":"T1:B","currency":"EUR","direction":"receive","payment_date":"2025-01-06","amount":"30.00"},
 {"payment_id":"P3","reference":"T1:B","currency":"EUR","direction":"receive","payment_date":"2025-01-08","amount":"40.00"},
 {"payment_id":"P4","reference":"T1:B","currency":"EUR","direction":"receive","payment_date":"2025-01-08","amount":"100.00"},
 {"payment_id":"P5","reference":"T1:B","currency":"EUR","direction":"receive","payment_date":"2025-01-08","amount":"40.00"},
 {"payment_id":"P6","reference":"T1:Q","currency":"USD","direction":"pay","payment_date":"2025-01-06","amount":"125.00"},
 {"payment_id":"P7","reference":"T1:Q","currency":"USD","direction":"receive","payment_date":"2025-01-06","amount":"125.00"},
 {"payment_id":"P8","reference":"T1:B","currency":"USD","direction":"receive","payment_date":"2025-01-06","amount":"75.00"},
 {"payment_id":"P9","reference":"UNKNOWN","currency":"GBP","direction":"pay","payment_date":"2025-01-06","amount":"10.00"}
]';
BEGIN TRY
 INSERT audit.SourceFile VALUES(@rate_hash,'fixture://reconciliation','test-only',SYSDATETIMEOFFSET(),1);
 INSERT audit.PipelineRun(run_id,source_sha256,code_version,status,finished_at,rows_received,rows_loaded,rows_rejected)
 VALUES(@rate_run,@rate_hash,'integration-check','succeeded',SYSDATETIMEOFFSET(),1,1,0);
 INSERT warehouse.FactFxRate VALUES('20250102',1,@rate_hash,1.25,'observed',2,'USD',@rate_run);
 EXEC warehouse.LoadSettlements @batch,@load,'integration-check',@manifest,@trades,@payments,'2025-01-08';
 IF (SELECT COUNT(*) FROM warehouse.DimDate)<>(SELECT DATEDIFF(day,MIN(calendar_date),MAX(calendar_date))+1 FROM warehouse.DimDate)
    THROW 51000,'Calendar dimension contains gaps.',1;
 IF (SELECT COUNT(*) FROM warehouse.FactSettlementLeg WHERE batch_id=@batch)<>2
    THROW 51000,'Trade did not produce exactly two gross legs.',1;
 EXEC warehouse.LoadSettlements @batch,@replay,'integration-check',@manifest,@trades,@payments,'2025-01-08';
 IF NOT EXISTS(SELECT 1 FROM audit.PipelineRun WHERE run_id=@replay AND rows_inserted=0 AND status='succeeded')
    THROW 51000,'Settlement ingestion replay was not idempotent.',1;
 DECLARE @invalid nvarchar(max)=JSON_MODIFY(@payments,'$[0].direction','invalid');
 BEGIN TRY
    EXEC warehouse.LoadSettlements @batch,@bad,'integration-check',@manifest,@trades,@invalid,'2025-01-08';
    THROW 51000,'Invalid payment direction was accepted.',1;
 END TRY
 BEGIN CATCH
    IF ERROR_MESSAGE() NOT LIKE 'Settlement input quality checks failed%' THROW;
 END CATCH;
 IF NOT EXISTS(SELECT 1 FROM audit.SettlementReject WHERE run_id=@bad AND entity='payment' AND source_row=2)
    THROW 51000,'Invalid payment row lineage was not recorded.',1;
 EXEC warehouse.ReconcileSettlements @batch,@early,'2025-01-07','integration-check';
 IF NOT EXISTS(SELECT 1 FROM warehouse.SettlementStatus WHERE batch_id=@batch AND leg_id='T1:B'
    AND allocated_amount=70 AND outstanding_amount=30 AND is_late=0 AND is_overdue=1 AND settlement_status='partial')
    THROW 51000,'As-of reconciliation included future cash or lost partial balance.',1;
 IF EXISTS(SELECT 1 FROM warehouse.PaymentExceptions WHERE batch_id=@batch AND payment_id IN('P3','P4','P5'))
    THROW 51000,'Future payments appeared in observed exception results.',1;
 EXEC warehouse.ReconcileSettlements @batch,@late,'2025-01-08','integration-check';
 IF NOT EXISTS(SELECT 1 FROM warehouse.SettlementStatus WHERE batch_id=@batch AND leg_id='T1:B'
    AND allocated_amount=100 AND outstanding_amount=0 AND is_late=1 AND settlement_status='settled')
    THROW 51000,'Late settlement did not clear the correct balance.',1;
 IF NOT EXISTS(SELECT 1 FROM warehouse.BridgeSettlementAllocation WHERE batch_id=@batch AND payment_id='P3' AND allocated_amount=30)
    THROW 51000,'Overpayment was overallocated.',1;
 IF EXISTS(SELECT 1 FROM warehouse.PaymentExceptions WHERE batch_id=@batch AND (
    (payment_id='P3' AND payment_status<>'overpayment') OR (payment_id='P4' AND payment_status<>'unallocated_excess')
    OR (payment_id='P5' AND payment_status<>'duplicate_candidate') OR (payment_id='P7' AND payment_status<>'wrong_direction')
    OR (payment_id='P8' AND payment_status<>'wrong_currency') OR (payment_id='P9' AND payment_status<>'unknown_reference')))
    THROW 51000,'Payment exception classification is incorrect.',1;
 IF (SELECT COUNT(*) FROM warehouse.BridgeSettlementAllocation WHERE batch_id=@batch)<>4
    THROW 51000,'Invalid payments were allocated or split payments were lost.',1;
 EXEC warehouse.ReconcileSettlements @batch,@repeat,'2025-01-08','integration-check';
 IF (SELECT COUNT(*) FROM warehouse.BridgeSettlementAllocation WHERE batch_id=@batch)<>4
    OR (SELECT SUM(allocated_amount) FROM warehouse.BridgeSettlementAllocation WHERE batch_id=@batch)<>225
    THROW 51000,'Reconciliation replay changed allocation totals.',1;
 PRINT 'PASS: two-leg model, input replay/rejection, partial/split allocations, as-of cutoff, late settlement, excess/duplicate/wrong-reference exceptions and reconciliation replay.';
END TRY
BEGIN CATCH
 DELETE warehouse.BridgeSettlementAllocation WHERE batch_id=@batch;
 DELETE warehouse.FactSettlementLeg WHERE batch_id=@batch;
 DELETE warehouse.FactPayment WHERE batch_id=@batch;
 DELETE warehouse.FactTrade WHERE batch_id=@batch;
 DELETE audit.SettlementBatch WHERE batch_id=@batch;
 DELETE audit.SettlementReject WHERE run_id IN(SELECT run_id FROM audit.PipelineRun WHERE source_sha256=@batch);
 DELETE audit.PipelineRun WHERE source_sha256=@batch;
 DELETE audit.SourceFile WHERE source_sha256 IN(@batch,@trade_hash,@payment_hash);
 DELETE warehouse.FactFxRate WHERE source_sha256=@rate_hash;
 DELETE audit.PipelineRun WHERE source_sha256=@rate_hash;
 DELETE audit.SourceFile WHERE source_sha256=@rate_hash;
 THROW;
END CATCH;
DELETE warehouse.BridgeSettlementAllocation WHERE batch_id=@batch;
DELETE warehouse.FactSettlementLeg WHERE batch_id=@batch;
DELETE warehouse.FactPayment WHERE batch_id=@batch;
DELETE warehouse.FactTrade WHERE batch_id=@batch;
DELETE audit.SettlementBatch WHERE batch_id=@batch;
DELETE audit.SettlementReject WHERE run_id IN(SELECT run_id FROM audit.PipelineRun WHERE source_sha256=@batch);
DELETE audit.PipelineRun WHERE source_sha256=@batch;
DELETE audit.SourceFile WHERE source_sha256 IN(@batch,@trade_hash,@payment_hash);
DELETE warehouse.FactFxRate WHERE source_sha256=@rate_hash;
DELETE audit.PipelineRun WHERE source_sha256=@rate_hash;
DELETE audit.SourceFile WHERE source_sha256=@rate_hash;
GO
