# Compare every reconciled leg to scenario expectations generated before SQL matching.
$ErrorActionPreference = 'Stop'
$batch = Get-Content 'F:\fx\data\settlement-batch.json' -Raw | ConvertFrom-Json
$expected = [IO.File]::ReadAllText('F:\fx\data\synthetic\expected.json').Replace("'", "''")
$sql = @"
USE FxWarehouse;
SET NOCOUNT ON;
DECLARE @batch char(64)='$($batch.batch_id)';
SELECT leg_id,currency,TRY_CONVERT(decimal(18,2),allocated) AS allocated,
    TRY_CONVERT(decimal(18,2),outstanding) AS outstanding,is_late,scenario
INTO #expected FROM OPENJSON(N'$expected') WITH (
    leg_id varchar(32),currency char(3),allocated varchar(32),outstanding varchar(32),is_late bit,scenario varchar(32));
IF (SELECT COUNT(*) FROM #expected)<>2*$($batch.trades)
    THROW 51000,'Scenario expectations do not cover every leg.',1;
IF EXISTS (SELECT leg_id,currency,allocated,outstanding,is_late FROM #expected
    EXCEPT SELECT leg_id,currency,allocated_amount,outstanding_amount,is_late FROM warehouse.SettlementStatus WHERE batch_id=@batch)
    OR (SELECT COUNT(*) FROM warehouse.SettlementStatus WHERE batch_id=@batch)<>(SELECT COUNT(*) FROM #expected)
    THROW 51000,'Reconciliation differs from independent scenario expectations.',1;
IF (SELECT COUNT(*) FROM warehouse.FactTrade WHERE batch_id=@batch)<>$($batch.trades)
    OR (SELECT COUNT(*) FROM warehouse.FactPayment WHERE batch_id=@batch)<>$($batch.payments)
    THROW 51000,'Input counts were not preserved.',1;
IF (SELECT COUNT(*) FROM warehouse.PaymentExceptions WHERE batch_id=@batch AND payment_status='wrong_currency')
    <>(SELECT COUNT(*) FROM #expected WHERE scenario='wrong_currency')
    THROW 51000,'Wrong-currency payment classification differs.',1;
IF (SELECT COUNT(*) FROM warehouse.PaymentExceptions WHERE batch_id=@batch AND payment_status='duplicate_candidate')
    <>(SELECT COUNT(*) FROM #expected WHERE scenario='duplicate')
    THROW 51000,'Duplicate-candidate classification differs.',1;
IF (SELECT COUNT(*) FROM warehouse.PaymentExceptions WHERE batch_id=@batch AND payment_status='overpayment')
    <>(SELECT COUNT(*) FROM #expected WHERE scenario='overpaid')
    THROW 51000,'Overpayment classification differs.',1;
IF NOT EXISTS(SELECT 1 FROM audit.PipelineRun WHERE run_id='$($batch.run_id)' AND status='succeeded'
    AND rows_received=$($batch.trades)+$($batch.payments) AND rows_rejected=0 AND ssis_execution_id IS NOT NULL)
    THROW 51000,'Successful SSIS ingestion lineage is missing.',1;
IF EXISTS(SELECT 1 FROM warehouse.FactTrade t JOIN audit.SettlementBatch b ON b.batch_id=t.batch_id
    WHERE t.batch_id=@batch AND t.rate_source_sha256<>b.rate_source_sha256)
    THROW 51000,'Trade-to-ECB lineage mismatch.',1;
SELECT rows_received,rows_loaded,rows_inserted FROM audit.PipelineRun WHERE run_id='$($batch.run_id)';
SELECT payment_status,COUNT(*) AS payments FROM warehouse.PaymentExceptions WHERE batch_id=@batch GROUP BY payment_status;
PRINT 'PASS: every settlement leg, monetary balance, exception classification and SSIS lineage matches expected scenarios.';
"@
[IO.File]::WriteAllText('F:\fx\data\verify-synthetic.sql',$sql,(New-Object Text.UTF8Encoding($true)))
& sqlcmd -S localhost -E -b -f 65001 -i 'F:\fx\data\verify-synthetic.sql'
if ($LASTEXITCODE -ne 0) { throw 'Synthetic settlement verification failed.' }
