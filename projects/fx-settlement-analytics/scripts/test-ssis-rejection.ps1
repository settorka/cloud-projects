# Integration check: execute the real package with one invalid rate, then remove only test audit rows.
$ErrorActionPreference = 'Stop'
$mutex = New-Object Threading.Mutex($false, 'Global\FxPipeline')
if (-not $mutex.WaitOne(0)) { throw 'Rate pipeline is busy.' }
$path = 'F:\fx\data\current-rate-load.sql'
$original = [IO.File]::ReadAllBytes($path)
$run = [Guid]::NewGuid().ToString()
try {
    $batch = Get-Content 'F:\fx\data\batch.json' -Raw | ConvertFrom-Json
    $statement = [IO.File]::ReadAllText($path).Replace($batch.run_id, $run)
    $pattern = New-Object Text.RegularExpressions.Regex('"rate":"[^"]+"')
    if (-not $pattern.IsMatch($statement)) { throw 'Prepared payload has no rate to invalidate.' }
    $statement = $pattern.Replace($statement, '"rate":"0"', 1)
    [IO.File]::WriteAllText($path, $statement, (New-Object Text.UTF8Encoding($true)))
    $assembly = Get-ChildItem 'C:\Windows\Microsoft.NET\assembly\GAC_MSIL\Microsoft.SqlServer.ManagedDTS' -Filter Microsoft.SqlServer.ManagedDTS.dll -Recurse | Select-Object -First 1
    Add-Type -Path $assembly.FullName
    $application = New-Object Microsoft.SqlServer.Dts.Runtime.Application
    $package = $application.LoadPackage('F:\fx\app\ssis\LoadRates.dtsx', $null)
    $result = $package.Execute()
    if ($result.ToString() -ne 'Failure') { throw "Expected SSIS Failure, got $result" }
    & sqlcmd -S localhost -E -b -d FxWarehouse -Q "IF NOT EXISTS (SELECT 1 FROM audit.PipelineRun WHERE run_id='$run' AND status='failed' AND rows_loaded=0 AND rows_inserted=0) THROW 51000, 'Missing failed batch evidence.', 1; IF NOT EXISTS (SELECT 1 FROM audit.RateReject WHERE run_id='$run') THROW 51000, 'Missing rejected row.', 1; IF EXISTS (SELECT 1 FROM warehouse.FactFxRate WHERE run_id='$run') THROW 51000, 'Failed SSIS batch published data.', 1;"
    if ($LASTEXITCODE -ne 0) { throw 'SSIS rejection audit checks failed.' }
    Write-Output 'PASS: actual SSIS package propagates rejection, records failed batch and publishes no data.'
} finally {
    [IO.File]::WriteAllBytes($path, $original)
    & sqlcmd -S localhost -E -b -d FxWarehouse -Q "DELETE audit.RateReject WHERE run_id='$run'; DELETE audit.PipelineRun WHERE run_id='$run' AND NOT EXISTS (SELECT 1 FROM warehouse.FactFxRate WHERE run_id='$run');"
    $cleanupFailed = $LASTEXITCODE -ne 0
    $mutex.ReleaseMutex()
    $mutex.Dispose()
    if ($cleanupFailed) { throw 'SSIS integration fixture cleanup failed.' }
}
