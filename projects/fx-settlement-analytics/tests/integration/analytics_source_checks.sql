USE FxWarehouse;
GO
SET NOCOUNT ON;
-- Materialize every projected field: an aggregate-only check can hide projection errors.
SELECT BatchId,PaymentId,Reference,Currency,Direction,PaymentDate,Amount,AllocatedAmount,
    UnappliedAmount,PaymentStatus,Counterparty,Pair INTO #payments FROM analytics.Payment;
IF EXISTS(SELECT 1 FROM #payments p JOIN analytics.SettlementLeg l ON l.BatchId=p.BatchId AND l.LegId=p.Reference
    WHERE p.Counterparty IS NULL OR p.Pair IS NULL OR p.Counterparty<>l.Counterparty OR p.Pair<>l.Pair)
    THROW 51000,'Known payment reference lost its counterparty or pair in the full projection.',1;
IF (SELECT COUNT(*) FROM #payments)<>(SELECT COUNT(*) FROM warehouse.PaymentExceptions)
    THROW 51000,'Analytics payment projection changed cardinality.',1;
IF EXISTS(SELECT BatchId,PaymentId FROM #payments GROUP BY BatchId,PaymentId HAVING COUNT(*)>1)
    THROW 51000,'Analytics projection duplicated a payment.',1;
PRINT 'PASS: full payment projection preserves cardinality and reference dimensions.';
GO
DBCC CHECKDB (N'FxWarehouse') WITH NO_INFOMSGS, ALL_ERRORMSGS;
GO
