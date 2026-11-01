USE FxWarehouse;
GO
CREATE OR ALTER PROCEDURE warehouse.LoadSettlements
    @batch_id char(64), @run_id uniqueidentifier, @code_version varchar(64),
    @manifest nvarchar(max), @trades nvarchar(max), @payments nvarchar(max), @retrieved_at datetimeoffset
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF ISJSON(@manifest)<>1 OR ISNULL(JSON_VALUE(@manifest,'$.classification'),'')<>'synthetic'
       OR ISNULL(TRY_CONVERT(int,JSON_VALUE(@manifest,'$.generator_version')),0)<>1
        THROW 51000,'Expected a supported synthetic manifest.',1;
    IF LOWER(CONVERT(char(64),HASHBYTES('SHA2_256',CONVERT(varchar(max),@manifest COLLATE Latin1_General_100_BIN2_UTF8)),2))<>@batch_id
        THROW 51000,'Synthetic manifest checksum mismatch.',1;
    DECLARE @rate_hash char(64)=JSON_VALUE(@manifest,'$.rate_source_sha256'),
        @trade_hash char(64)=JSON_VALUE(@manifest,'$.files."trades.csv".sha256'),
        @payment_hash char(64)=JSON_VALUE(@manifest,'$.files."payments.csv".sha256'),
        @asof date=TRY_CONVERT(date,JSON_VALUE(@manifest,'$.as_of_date'),23),
        @seed int=TRY_CONVERT(int,JSON_VALUE(@manifest,'$.seed'));
    IF @asof IS NULL OR @seed IS NULL OR @trade_hash IS NULL OR @payment_hash IS NULL
        OR NOT EXISTS(SELECT 1 FROM audit.SourceFile WHERE source_sha256=@rate_hash)
        THROW 51000,'Synthetic source metadata is incomplete.',1;
    DECLARE @sources TABLE(hash char(64),source_url nvarchar(2048),blob_path nvarchar(1024),bytes bigint);
    INSERT @sources VALUES
      (@batch_id,'synthetic://manifest','synthetic/'+@batch_id+'/manifest.json',DATALENGTH(CONVERT(varchar(max),@manifest COLLATE Latin1_General_100_BIN2_UTF8))),
      (@trade_hash,'synthetic://trades','synthetic/'+@batch_id+'/trades.csv',TRY_CONVERT(bigint,JSON_VALUE(@manifest,'$.files."trades.csv".bytes'))),
      (@payment_hash,'synthetic://payments','synthetic/'+@batch_id+'/payments.csv',TRY_CONVERT(bigint,JSON_VALUE(@manifest,'$.files."payments.csv".bytes')));
    INSERT audit.SourceFile
    SELECT DISTINCT s.hash,s.source_url,s.blob_path,@retrieved_at,s.bytes FROM @sources s
    WHERE NOT EXISTS(SELECT 1 FROM audit.SourceFile t WHERE t.source_sha256=s.hash);
    INSERT audit.PipelineRun(run_id,source_sha256,code_version,status,pipeline_name)
    VALUES(@run_id,@batch_id,@code_version,'running','settlements');
    BEGIN TRY
        IF ISJSON(@trades)<>1 OR LEFT(LTRIM(@trades),1)<>'[' OR ISJSON(@payments)<>1 OR LEFT(LTRIM(@payments),1)<>'['
            THROW 51000,'Expected trade and payment arrays.',1;
        SELECT CONVERT(int,j.[key])+2 AS source_row,j.value AS raw_record,
            JSON_VALUE(j.value,'$.trade_id') AS trade_id,COUNT(*) OVER(PARTITION BY JSON_VALUE(j.value,'$.trade_id')) AS duplicate_count,p.pair_id,JSON_VALUE(j.value,'$.counterparty') AS counterparty,
            JSON_VALUE(j.value,'$.side') AS side,TRY_CONVERT(date,JSON_VALUE(j.value,'$.rate_date'),23) AS rate_date,
            TRY_CONVERT(date,JSON_VALUE(j.value,'$.trade_date'),23) AS trade_date,
            TRY_CONVERT(date,JSON_VALUE(j.value,'$.settlement_date'),23) AS settlement_date,
            TRY_CONVERT(decimal(18,2),JSON_VALUE(j.value,'$.base_amount')) AS base_amount,
            TRY_CONVERT(decimal(18,2),JSON_VALUE(j.value,'$.quote_amount')) AS quote_amount,
            JSON_VALUE(j.value,'$.rate_source_sha256') AS rate_source_sha256
        INTO #raw_trades FROM OPENJSON(@trades) j
        LEFT JOIN warehouse.DimCurrencyPair p ON p.pair_code=JSON_VALUE(j.value,'$.pair');
        SELECT CONVERT(int,j.[key])+2 AS source_row,j.value AS raw_record,
            JSON_VALUE(j.value,'$.payment_id') AS payment_id,COUNT(*) OVER(PARTITION BY JSON_VALUE(j.value,'$.payment_id')) AS duplicate_count,JSON_VALUE(j.value,'$.reference') AS reference,
            JSON_VALUE(j.value,'$.currency') AS currency,JSON_VALUE(j.value,'$.direction') AS direction,
            TRY_CONVERT(date,JSON_VALUE(j.value,'$.payment_date'),23) AS payment_date,
            TRY_CONVERT(decimal(18,2),JSON_VALUE(j.value,'$.amount')) AS amount
        INTO #raw_payments FROM OPENJSON(@payments) j;
        DECLARE @trade_count int=(SELECT COUNT(*) FROM #raw_trades),@payment_count int=(SELECT COUNT(*) FROM #raw_payments),
            @received int;
        SET @received=@trade_count+@payment_count;
        UPDATE audit.PipelineRun SET rows_received=@received WHERE run_id=@run_id;
        IF @trade_count<1 OR @trade_count>100000 OR @payment_count>300000
           OR @trade_count<>ISNULL(TRY_CONVERT(int,JSON_VALUE(@manifest,'$.trade_count')),-1)
           OR @payment_count<>ISNULL(TRY_CONVERT(int,JSON_VALUE(@manifest,'$.payment_count')),-1)
            THROW 51000,'Manifest row counts do not match bounded inputs.',1;
        INSERT audit.SettlementReject
        SELECT @run_id,'trade',t.source_row,t.raw_record,'Invalid trade, duplicate identifier or inconsistent ECB reference'
        FROM #raw_trades t LEFT JOIN warehouse.FactFxRate r ON r.rate_date=t.rate_date
            AND r.pair_id=t.pair_id AND r.source_sha256=t.rate_source_sha256
        WHERE t.trade_id IS NULL OR LEN(t.trade_id) NOT BETWEEN 1 AND 16 OR t.pair_id IS NULL
           OR t.counterparty IS NULL OR LEN(t.counterparty)<>4 OR t.counterparty NOT LIKE 'CP[0-9][0-9]'
           OR TRY_CONVERT(int,RIGHT(t.counterparty,2)) NOT BETWEEN 1 AND 20
           OR t.side IS NULL OR t.side NOT IN('BUY_BASE','SELL_BASE')
           OR t.rate_date IS NULL OR t.trade_date IS NULL OR t.settlement_date IS NULL
           OR t.rate_date<>t.trade_date OR t.settlement_date<t.trade_date
           OR t.base_amount IS NULL OR t.base_amount<=0 OR t.quote_amount IS NULL OR t.quote_amount<=0
           OR t.rate_source_sha256 IS NULL OR t.rate_source_sha256<>@rate_hash OR r.rate IS NULL
           OR t.quote_amount<>ROUND(t.base_amount*CONVERT(decimal(18,14),r.rate),2)
           OR t.duplicate_count>1;
        INSERT audit.SettlementReject
        SELECT @run_id,'payment',p.source_row,p.raw_record,'Invalid payment or duplicate identifier'
        FROM #raw_payments p
        WHERE p.payment_id IS NULL OR LEN(p.payment_id) NOT BETWEEN 1 AND 16
           OR p.reference IS NULL OR LEN(p.reference) NOT BETWEEN 1 AND 32
           OR p.currency IS NULL OR p.currency NOT IN('GBP','EUR','USD')
           OR p.direction IS NULL OR p.direction NOT IN('pay','receive') OR p.payment_date IS NULL
           OR p.amount IS NULL OR p.amount<=0
           OR p.duplicate_count>1;
        DECLARE @rejected int=(SELECT COUNT(*) FROM audit.SettlementReject WHERE run_id=@run_id);
        UPDATE audit.PipelineRun SET rows_rejected=@rejected WHERE run_id=@run_id;
        IF @rejected>0 THROW 51000,'Settlement input quality checks failed; inspect audit.SettlementReject.',1;
        -- Materialize narrow, validated rows once; EXCEPT/window plans must not carry
        -- JSON_VALUE's nvarchar(4000) metadata or raw JSON through their sorts.
        SELECT source_row,CONVERT(varchar(16),trade_id) AS trade_id,pair_id,
            CONVERT(varchar(4),counterparty) AS counterparty,CONVERT(varchar(9),side) AS side,
            rate_date,trade_date,settlement_date,base_amount,quote_amount,
            CONVERT(char(64),rate_source_sha256) AS rate_source_sha256
        INTO #trades FROM #raw_trades;
        SELECT source_row,CONVERT(varchar(16),payment_id) AS payment_id,
            CONVERT(varchar(32),reference) AS reference,CONVERT(char(3),currency) AS currency,
            CONVERT(varchar(7),direction) AS direction,payment_date,amount
        INTO #payments FROM #raw_payments;
        DROP TABLE #raw_trades;
        DROP TABLE #raw_payments;
        CREATE UNIQUE CLUSTERED INDEX IX_TradeId ON #trades(trade_id);
        CREATE UNIQUE CLUSTERED INDEX IX_PaymentId ON #payments(payment_id);
        BEGIN TRANSACTION;
        DECLARE @lock int,@resource varchar(100)='fx-settlements:'+@batch_id;
        EXEC @lock=sys.sp_getapplock @Resource=@resource,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=30000;
        IF @lock<0 THROW 51000,'Settlement publication lock failed.',1;
        -- Dense full-year date dimension supports time-intelligence without filling facts.
        DECLARE @first_date date,@last_date date;
        SELECT @first_date=DATEFROMPARTS(YEAR(MIN(d)),1,1),@last_date=DATEFROMPARTS(YEAR(MAX(d)),12,31)
        FROM (SELECT trade_date AS d FROM #trades UNION ALL SELECT settlement_date FROM #trades
              UNION ALL SELECT payment_date FROM #payments UNION ALL SELECT @asof
              UNION ALL SELECT calendar_date FROM warehouse.DimDate) dates;
        ;WITH calendar AS (
            SELECT @first_date AS calendar_date
            UNION ALL SELECT DATEADD(day,1,calendar_date) FROM calendar WHERE calendar_date<@last_date
        )
        INSERT warehouse.DimDate
        SELECT d.calendar_date,YEAR(d.calendar_date),MONTH(d.calendar_date),DAY(d.calendar_date) FROM calendar d
        WHERE NOT EXISTS(SELECT 1 FROM warehouse.DimDate x WHERE x.calendar_date=d.calendar_date)
        OPTION(MAXRECURSION 0);
        IF EXISTS(SELECT 1 FROM audit.SettlementBatch WHERE batch_id=@batch_id)
        BEGIN
            IF EXISTS(SELECT trade_id,pair_id,counterparty,side,rate_date,trade_date,settlement_date,base_amount,quote_amount,rate_source_sha256,source_row FROM #trades
                EXCEPT SELECT trade_id,pair_id,counterparty,side,rate_date,trade_date,settlement_date,base_amount,quote_amount,rate_source_sha256,source_row FROM warehouse.FactTrade WHERE batch_id=@batch_id)
              OR @trade_count<>(SELECT COUNT(*) FROM warehouse.FactTrade WHERE batch_id=@batch_id)
              OR EXISTS(SELECT payment_id,reference,currency,direction,payment_date,amount,source_row FROM #payments
                EXCEPT SELECT payment_id,reference,currency,direction,payment_date,amount,source_row FROM warehouse.FactPayment WHERE batch_id=@batch_id)
              OR @payment_count<>(SELECT COUNT(*) FROM warehouse.FactPayment WHERE batch_id=@batch_id)
                THROW 51000,'Settlement replay conflicts with immutable inputs.',1;
            UPDATE audit.PipelineRun SET status='succeeded',finished_at=SYSDATETIMEOFFSET(),rows_loaded=@received,
                rows_rejected=0,rows_inserted=0 WHERE run_id=@run_id;
            COMMIT;
            RETURN;
        END;
        INSERT warehouse.DimCounterparty
        SELECT DISTINCT t.counterparty,'Synthetic counterparty '+t.counterparty,1 FROM #trades t
        WHERE NOT EXISTS(SELECT 1 FROM warehouse.DimCounterparty c WHERE c.counterparty=t.counterparty);
        INSERT audit.SettlementBatch(batch_id,rate_source_sha256,trade_source_sha256,payment_source_sha256,
            seed,generator_version,manifest_json,as_of_date,ingest_run_id,is_synthetic)
        VALUES(@batch_id,@rate_hash,@trade_hash,@payment_hash,@seed,1,@manifest,@asof,@run_id,1);
        INSERT warehouse.FactTrade
        SELECT @batch_id,trade_id,pair_id,counterparty,side,rate_date,trade_date,settlement_date,
            base_amount,quote_amount,rate_source_sha256,source_row,@run_id FROM #trades;
        INSERT warehouse.FactSettlementLeg
        SELECT @batch_id,t.trade_id+':'+v.leg_kind,t.trade_id,v.leg_kind,
            CASE WHEN v.leg_kind='B' THEN p.base_currency ELSE p.quote_currency END,
            CASE WHEN (v.leg_kind='B' AND t.side='BUY_BASE') OR (v.leg_kind='Q' AND t.side='SELL_BASE')
                 THEN 'receive' ELSE 'pay' END,
            t.settlement_date,CASE WHEN v.leg_kind='B' THEN t.base_amount ELSE t.quote_amount END
        FROM #trades t JOIN warehouse.DimCurrencyPair p ON p.pair_id=t.pair_id CROSS JOIN (VALUES('B'),('Q')) v(leg_kind);
        INSERT warehouse.FactPayment
        SELECT @batch_id,payment_id,reference,currency,direction,payment_date,amount,source_row,@run_id FROM #payments;
        UPDATE audit.PipelineRun SET status='succeeded',finished_at=SYSDATETIMEOFFSET(),rows_loaded=@received,
            rows_rejected=0,rows_inserted=@received WHERE run_id=@run_id;
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT>0 ROLLBACK;
        UPDATE audit.PipelineRun SET status='failed',finished_at=SYSDATETIMEOFFSET(),rows_loaded=0,rows_inserted=0,
            error_message=LEFT(ERROR_MESSAGE(),2048) WHERE run_id=@run_id;
        THROW;
    END CATCH;
END;
GO
