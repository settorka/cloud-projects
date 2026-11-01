USE FxWarehouse;
GO
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF COL_LENGTH('audit.PipelineRun','pipeline_name') IS NULL
    ALTER TABLE audit.PipelineRun ADD pipeline_name varchar(32) NOT NULL CONSTRAINT DF_PipelineName DEFAULT 'rates';
IF OBJECT_ID('warehouse.DimDate') IS NULL
CREATE TABLE warehouse.DimDate (
    calendar_date date NOT NULL PRIMARY KEY,
    calendar_year smallint NOT NULL,
    calendar_month tinyint NOT NULL,
    day_of_month tinyint NOT NULL
);
IF OBJECT_ID('warehouse.DimCurrency') IS NULL
CREATE TABLE warehouse.DimCurrency (currency char(3) NOT NULL PRIMARY KEY);
INSERT warehouse.DimCurrency SELECT v.currency FROM (VALUES ('EUR'),('GBP'),('USD')) v(currency)
WHERE NOT EXISTS (SELECT 1 FROM warehouse.DimCurrency c WHERE c.currency=v.currency);
IF OBJECT_ID('warehouse.DimCounterparty') IS NULL
CREATE TABLE warehouse.DimCounterparty (
    counterparty varchar(4) NOT NULL PRIMARY KEY,
    display_name varchar(64) NOT NULL,
    is_synthetic bit NOT NULL CHECK (is_synthetic=1)
);
IF OBJECT_ID('audit.SettlementBatch') IS NULL
CREATE TABLE audit.SettlementBatch (
    batch_id char(64) NOT NULL PRIMARY KEY REFERENCES audit.SourceFile(source_sha256),
    rate_source_sha256 char(64) NOT NULL REFERENCES audit.SourceFile(source_sha256),
    trade_source_sha256 char(64) NOT NULL REFERENCES audit.SourceFile(source_sha256),
    payment_source_sha256 char(64) NOT NULL REFERENCES audit.SourceFile(source_sha256),
    seed int NOT NULL,
    generator_version int NOT NULL,
    manifest_json nvarchar(max) NOT NULL CHECK (ISJSON(manifest_json)=1),
    as_of_date date NOT NULL,
    reconciled_as_of date NULL,
    reconciliation_run_id uniqueidentifier NULL REFERENCES audit.PipelineRun(run_id),
    ingest_run_id uniqueidentifier NOT NULL REFERENCES audit.PipelineRun(run_id),
    is_synthetic bit NOT NULL CHECK (is_synthetic=1)
);
IF OBJECT_ID('audit.SettlementReject') IS NULL
CREATE TABLE audit.SettlementReject (
    run_id uniqueidentifier NOT NULL REFERENCES audit.PipelineRun(run_id),
    entity varchar(16) NOT NULL,
    source_row int NOT NULL,
    raw_record nvarchar(max) NOT NULL,
    reason nvarchar(256) NOT NULL,
    PRIMARY KEY (run_id,entity,source_row)
);
IF OBJECT_ID('warehouse.FactTrade') IS NULL
CREATE TABLE warehouse.FactTrade (
    batch_id char(64) NOT NULL REFERENCES audit.SettlementBatch(batch_id),
    trade_id varchar(16) NOT NULL,
    pair_id tinyint NOT NULL REFERENCES warehouse.DimCurrencyPair(pair_id),
    counterparty varchar(4) NOT NULL REFERENCES warehouse.DimCounterparty(counterparty),
    side varchar(9) NOT NULL CHECK (side IN ('BUY_BASE','SELL_BASE')),
    rate_date date NOT NULL REFERENCES warehouse.DimDate(calendar_date),
    trade_date date NOT NULL REFERENCES warehouse.DimDate(calendar_date),
    settlement_date date NOT NULL REFERENCES warehouse.DimDate(calendar_date),
    base_amount decimal(18,2) NOT NULL CHECK (base_amount>0),
    quote_amount decimal(18,2) NOT NULL CHECK (quote_amount>0),
    rate_source_sha256 char(64) NOT NULL,
    source_row int NOT NULL CHECK (source_row>=2),
    run_id uniqueidentifier NOT NULL REFERENCES audit.PipelineRun(run_id),
    PRIMARY KEY (batch_id,trade_id),
    FOREIGN KEY (rate_date,pair_id,rate_source_sha256)
        REFERENCES warehouse.FactFxRate(rate_date,pair_id,source_sha256),
    CHECK (settlement_date>=trade_date)
);
IF OBJECT_ID('warehouse.FactSettlementLeg') IS NULL
CREATE TABLE warehouse.FactSettlementLeg (
    batch_id char(64) NOT NULL,
    leg_id varchar(32) NOT NULL,
    trade_id varchar(16) NOT NULL,
    leg_kind char(1) NOT NULL CHECK (leg_kind IN ('B','Q')),
    currency char(3) NOT NULL REFERENCES warehouse.DimCurrency(currency),
    direction varchar(7) NOT NULL CHECK (direction IN ('pay','receive')),
    due_date date NOT NULL REFERENCES warehouse.DimDate(calendar_date),
    expected_amount decimal(18,2) NOT NULL CHECK (expected_amount>0),
    PRIMARY KEY(batch_id,leg_id),
    UNIQUE(batch_id,trade_id,leg_kind),
    FOREIGN KEY(batch_id,trade_id) REFERENCES warehouse.FactTrade(batch_id,trade_id)
);
IF OBJECT_ID('warehouse.FactPayment') IS NULL
CREATE TABLE warehouse.FactPayment (
    batch_id char(64) NOT NULL REFERENCES audit.SettlementBatch(batch_id),
    payment_id varchar(16) NOT NULL,
    reference varchar(32) NOT NULL,
    currency char(3) NOT NULL REFERENCES warehouse.DimCurrency(currency),
    direction varchar(7) NOT NULL CHECK (direction IN ('pay','receive')),
    payment_date date NOT NULL REFERENCES warehouse.DimDate(calendar_date),
    amount decimal(18,2) NOT NULL CHECK (amount>0),
    source_row int NOT NULL CHECK(source_row>=2),
    run_id uniqueidentifier NOT NULL REFERENCES audit.PipelineRun(run_id),
    PRIMARY KEY(batch_id,payment_id)
);
IF OBJECT_ID('warehouse.BridgeSettlementAllocation') IS NULL
CREATE TABLE warehouse.BridgeSettlementAllocation (
    batch_id char(64) NOT NULL,
    payment_id varchar(16) NOT NULL,
    leg_id varchar(32) NOT NULL,
    allocated_amount decimal(18,2) NOT NULL CHECK (allocated_amount>0),
    reconciliation_run_id uniqueidentifier NOT NULL REFERENCES audit.PipelineRun(run_id),
    PRIMARY KEY(batch_id,payment_id),
    FOREIGN KEY(batch_id,payment_id) REFERENCES warehouse.FactPayment(batch_id,payment_id),
    FOREIGN KEY(batch_id,leg_id) REFERENCES warehouse.FactSettlementLeg(batch_id,leg_id)
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('warehouse.FactPayment') AND name='IX_PaymentReference')
CREATE INDEX IX_PaymentReference ON warehouse.FactPayment
    (batch_id,reference,currency,direction,payment_date,payment_id) INCLUDE(amount);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('warehouse.BridgeSettlementAllocation') AND name='IX_AllocationLeg')
CREATE INDEX IX_AllocationLeg ON warehouse.BridgeSettlementAllocation(batch_id,leg_id) INCLUDE(allocated_amount,payment_id);
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_TradeRunSource')
    ALTER TABLE warehouse.FactTrade ADD CONSTRAINT FK_TradeRunSource
        FOREIGN KEY(run_id,batch_id) REFERENCES audit.PipelineRun(run_id,source_sha256);
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_PaymentRunSource')
    ALTER TABLE warehouse.FactPayment ADD CONSTRAINT FK_PaymentRunSource
        FOREIGN KEY(run_id,batch_id) REFERENCES audit.PipelineRun(run_id,source_sha256);
COMMIT;
GO
CREATE OR ALTER PROCEDURE warehouse.ReconcileSettlements
    @batch_id char(64), @run_id uniqueidentifier, @as_of_date date, @code_version varchar(64)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @as_of_date IS NULL OR NOT EXISTS (SELECT 1 FROM audit.SettlementBatch b
        JOIN audit.PipelineRun r ON r.run_id=b.ingest_run_id AND r.status='succeeded' WHERE b.batch_id=@batch_id)
        THROW 51000,'Batch is not published or as-of date is missing.',1;
    INSERT audit.PipelineRun(run_id,source_sha256,code_version,status,pipeline_name)
    VALUES(@run_id,@batch_id,@code_version,'running','reconciliation');
    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @lock int, @resource varchar(100)='fx-settlements:'+@batch_id;
        EXEC @lock=sys.sp_getapplock @Resource=@resource,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=30000;
        IF @lock<0 THROW 51000,'Settlement publication lock failed.',1;
        DELETE warehouse.BridgeSettlementAllocation WHERE batch_id=@batch_id;
        ;WITH eligible AS (
            SELECT p.batch_id,p.payment_id,l.leg_id,p.amount,l.expected_amount,
                COALESCE(SUM(p.amount) OVER (PARTITION BY p.batch_id,l.leg_id
                    ORDER BY p.payment_date,p.payment_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) AS prior_amount
            FROM warehouse.FactPayment p JOIN warehouse.FactSettlementLeg l
              ON l.batch_id=p.batch_id AND l.leg_id=p.reference
             AND l.currency=p.currency AND l.direction=p.direction
            WHERE p.batch_id=@batch_id AND p.payment_date<=@as_of_date
        )
        INSERT warehouse.BridgeSettlementAllocation
        SELECT batch_id,payment_id,leg_id,
            CASE WHEN amount<expected_amount-prior_amount THEN amount ELSE expected_amount-prior_amount END,@run_id
        FROM eligible WHERE prior_amount<expected_amount;
        DECLARE @allocated int=@@ROWCOUNT;
        IF EXISTS (SELECT 1 FROM warehouse.BridgeSettlementAllocation a JOIN warehouse.FactPayment p
            ON p.batch_id=a.batch_id AND p.payment_id=a.payment_id
            WHERE a.batch_id=@batch_id AND a.allocated_amount>p.amount)
            THROW 51000,'Allocation exceeds payment amount.',1;
        IF EXISTS (SELECT 1 FROM warehouse.BridgeSettlementAllocation a JOIN warehouse.FactSettlementLeg l
            ON l.batch_id=a.batch_id AND l.leg_id=a.leg_id WHERE a.batch_id=@batch_id
            GROUP BY a.leg_id,l.expected_amount HAVING SUM(a.allocated_amount)>l.expected_amount)
            THROW 51000,'Allocation exceeds expected leg.',1;
        DECLARE @processed int=(SELECT COUNT(*) FROM warehouse.FactSettlementLeg WHERE batch_id=@batch_id)
            +(SELECT COUNT(*) FROM warehouse.FactPayment WHERE batch_id=@batch_id AND payment_date<=@as_of_date);
        UPDATE audit.PipelineRun SET status='succeeded',finished_at=SYSDATETIMEOFFSET(),
            rows_received=@processed,rows_loaded=@processed,rows_rejected=0,rows_inserted=@allocated WHERE run_id=@run_id;
        UPDATE audit.SettlementBatch SET reconciled_as_of=@as_of_date,reconciliation_run_id=@run_id WHERE batch_id=@batch_id;
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT>0 ROLLBACK;
        UPDATE audit.PipelineRun SET status='failed',finished_at=SYSDATETIMEOFFSET(),rows_loaded=0,
            error_message=LEFT(ERROR_MESSAGE(),2048) WHERE run_id=@run_id;
        THROW;
    END CATCH;
END;
GO
CREATE OR ALTER VIEW warehouse.SettlementStatus AS
WITH applied AS (
    SELECT a.batch_id,a.leg_id,SUM(a.allocated_amount) AS allocated_amount,
        MAX(CASE WHEN p.payment_date>l.due_date THEN 1 ELSE 0 END) AS is_late
    FROM warehouse.BridgeSettlementAllocation a
    JOIN warehouse.FactPayment p ON p.batch_id=a.batch_id AND p.payment_id=a.payment_id
    JOIN warehouse.FactSettlementLeg l ON l.batch_id=a.batch_id AND l.leg_id=a.leg_id
    GROUP BY a.batch_id,a.leg_id
)
SELECT l.batch_id,l.leg_id,l.trade_id,t.counterparty,pair.pair_code,l.currency,l.direction,l.due_date,
    l.expected_amount,COALESCE(a.allocated_amount,0) AS allocated_amount,
    l.expected_amount-COALESCE(a.allocated_amount,0) AS outstanding_amount,
    COALESCE(a.is_late,0) AS is_late,
    CASE WHEN l.due_date<b.reconciled_as_of AND l.expected_amount>COALESCE(a.allocated_amount,0) THEN 1 ELSE 0 END AS is_overdue,
    CASE WHEN COALESCE(a.allocated_amount,0)=0 THEN 'unsettled'
         WHEN a.allocated_amount<l.expected_amount THEN 'partial' ELSE 'settled' END AS settlement_status,
    b.reconciled_as_of,b.is_synthetic
FROM warehouse.FactSettlementLeg l
JOIN warehouse.FactTrade t ON t.batch_id=l.batch_id AND t.trade_id=l.trade_id
JOIN warehouse.DimCurrencyPair pair ON pair.pair_id=t.pair_id
JOIN audit.SettlementBatch b ON b.batch_id=l.batch_id
JOIN audit.PipelineRun r ON r.run_id=b.reconciliation_run_id AND r.status='succeeded'
LEFT JOIN applied a ON a.batch_id=l.batch_id AND a.leg_id=l.leg_id;
GO
CREATE OR ALTER VIEW warehouse.PaymentExceptions AS
WITH observed AS (
    SELECT p.*,
        COUNT(*) OVER(PARTITION BY p.batch_id,p.reference,p.currency,p.direction,p.amount
            ORDER BY p.payment_date,p.payment_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_identical
    FROM warehouse.FactPayment p JOIN audit.SettlementBatch b ON b.batch_id=p.batch_id
    JOIN audit.PipelineRun r ON r.run_id=b.reconciliation_run_id AND r.status='succeeded'
    WHERE p.payment_date<=b.reconciled_as_of
)
SELECT p.batch_id,p.payment_id,p.reference,p.currency,p.direction,p.amount,p.payment_date,
    COALESCE(a.allocated_amount,0) AS allocated_amount,p.amount-COALESCE(a.allocated_amount,0) AS unapplied_amount,
    CASE WHEN l.leg_id IS NULL THEN 'unknown_reference'
         WHEN l.currency<>p.currency THEN 'wrong_currency'
         WHEN l.direction<>p.direction THEN 'wrong_direction'
         WHEN a.allocated_amount IS NULL AND p.prior_identical>0 THEN 'duplicate_candidate'
         WHEN a.allocated_amount IS NULL THEN 'unallocated_excess'
         WHEN a.allocated_amount<p.amount THEN 'overpayment'
         ELSE 'matched' END AS payment_status,
    t.counterparty,pair.pair_code
FROM observed p
LEFT JOIN warehouse.FactSettlementLeg l ON l.batch_id=p.batch_id AND l.leg_id=p.reference
LEFT JOIN warehouse.FactTrade t ON t.batch_id=l.batch_id AND t.trade_id=l.trade_id
LEFT JOIN warehouse.DimCurrencyPair pair ON pair.pair_id=t.pair_id
LEFT JOIN warehouse.BridgeSettlementAllocation a ON a.batch_id=p.batch_id AND a.payment_id=p.payment_id;
GO
