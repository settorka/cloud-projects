param([int]$Count = 1000, [int]$Seed = 42)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. 'F:\fx\app\scripts\ssis-runtime.ps1'
$mutex = New-Object Threading.Mutex($false, 'Global\FxPipeline')
if (-not $mutex.WaitOne(0)) { throw 'Another settlement batch is already running.' }
try {
    Set-Location 'F:\fx\app'
    $context = Get-FxBlobContext
    & 'C:\Python312\python.exe' -m pipeline.generate_settlements 'F:\fx\data\fx_rates.csv' --output 'F:\fx\data\synthetic' --count $Count --seed $Seed
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic generation failed.' }
    & 'C:\Python312\python.exe' -m pipeline.build_settlement_batch 'F:\fx\data\synthetic' --code-version $env:FX_CODE_VERSION --output 'F:\fx\data'
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic batch verification failed.' }
    $batch = Get-Content 'F:\fx\data\settlement-batch.json' -Raw | ConvertFrom-Json
    foreach ($name in @('trades.csv','payments.csv','expected.json')) {
        Send-FxArtifact $context "synthetic/$($batch.batch_id)/$name" "F:\fx\data\synthetic\$name"
    }
    # Commit the input manifest last, after all verified files are stored.
    Send-FxArtifact $context "synthetic/$($batch.batch_id)/manifest.json" 'F:\fx\data\synthetic\manifest.json'
    $null = Invoke-FxPackage $context 'Settlements' $batch
    $run = [Guid]::NewGuid().ToString()
    $clock = [Diagnostics.Stopwatch]::StartNew()
    & sqlcmd -S localhost -E -b -d FxWarehouse -Q "EXEC warehouse.ReconcileSettlements @batch_id='$($batch.batch_id)',@run_id='$run',@as_of_date='$($batch.as_of_date)',@code_version='$($batch.code_version)'; SELECT settlement_status,currency,COUNT(*) AS legs,SUM(outstanding_amount) AS outstanding FROM warehouse.SettlementStatus WHERE batch_id='$($batch.batch_id)' GROUP BY settlement_status,currency;"
    if ($LASTEXITCODE -ne 0) { throw 'Settlement reconciliation failed.' }
    $clock.Stop()
    Write-Output "Reconciliation command wall time milliseconds (includes sqlcmd and summary): $($clock.ElapsedMilliseconds)"
    & sqlcmd -S localhost -E -b -d FxWarehouse -Q "SELECT DATEDIFF_BIG(microsecond,started_at,finished_at)/1000.0 AS sql_reconciliation_ms FROM audit.PipelineRun WHERE run_id='$run';"
    if ($LASTEXITCODE -ne 0) { throw 'Reconciliation timing query failed.' }
    & 'F:\fx\app\scripts\verify-settlements.ps1'
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
