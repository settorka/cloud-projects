USE FxWarehouse;
GO
CREATE OR ALTER VIEW audit.PipelineHealth AS
SELECT r.run_id,r.pipeline_name,r.source_sha256,r.code_version,r.status,r.started_at,r.finished_at,
    DATEDIFF_BIG(millisecond,r.started_at,COALESCE(r.finished_at,SYSDATETIMEOFFSET())) AS elapsed_ms,
    r.rows_received,r.rows_loaded,r.rows_rejected,r.rows_inserted,
    r.ssis_execution_id,r.package_sha256,r.error_message,
    (SELECT COUNT(*) FROM audit.RateReject e WHERE e.run_id=r.run_id)
        +(SELECT COUNT(*) FROM audit.SettlementReject e WHERE e.run_id=r.run_id) AS recorded_rejections
FROM audit.PipelineRun r;
GO
