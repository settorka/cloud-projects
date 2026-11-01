param(
    [string]$SourceHash = '73db21584dd46cebf5cd6df75ebb6de7afcdeebff52f54d5046ca8e459c0fbb3',
    [string]$Start = '2025-01-01',
    [string]$End = '2025-12-31'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. 'F:\fx\app\scripts\ssis-runtime.ps1'
if ($SourceHash -notmatch '^[a-f0-9]{64}$') { throw 'Invalid source hash.' }
$mutex = New-Object Threading.Mutex($false, 'Global\FxPipeline')
if (-not $mutex.WaitOne(0)) { throw 'Another rate batch is already running.' }
try {
    Set-Location 'F:\fx\app'
    $context = Get-FxBlobContext
    $base = $context.Base
    $headers = $context.Headers
    $prefix = "$base/raw/ecb/$SourceHash"
    Invoke-WebRequest "$prefix/eurofxref-hist.zip" -Headers $headers -OutFile 'F:\fx\data\ecb.zip' -UseBasicParsing
    Invoke-WebRequest "$prefix/manifest.json" -Headers $headers -OutFile 'F:\fx\data\manifest.json' -UseBasicParsing
    if ((Get-FileHash 'F:\fx\data\ecb.zip' -Algorithm SHA256).Hash.ToLower() -ne $SourceHash) { throw 'Downloaded ECB checksum mismatch.' }
    & 'C:\Python312\python.exe' -m pipeline.build_rate_batch 'F:\fx\data\ecb.zip' 'F:\fx\data\manifest.json' --start $Start --end $End --code-version $env:FX_CODE_VERSION --output 'F:\fx\data'
    if ($LASTEXITCODE -ne 0) { throw 'Rate preparation failed.' }
    $batch = Get-Content 'F:\fx\data\batch.json' -Raw | ConvertFrom-Json
    Send-FxArtifact $context "prepared/$($batch.run_id)/fx_rates.csv" 'F:\fx\data\fx_rates.csv'
    Send-FxArtifact $context "prepared/$($batch.run_id)/batch.json" 'F:\fx\data\batch.json'
    $batch | Add-Member -NotePropertyName prepared_blob_path -NotePropertyValue "prepared/$($batch.run_id)/fx_rates.csv"
    $batch | Add-Member -NotePropertyName prepared_sha256 -NotePropertyValue ((Get-FileHash 'F:\fx\data\fx_rates.csv' -Algorithm SHA256).Hash.ToLower())
    $null = Invoke-FxPackage $context 'Rates' $batch
    & sqlcmd -S localhost -E -b -d FxWarehouse -Q "SELECT run_id,status,rows_received,rows_loaded,rows_rejected,rows_inserted FROM audit.PipelineRun WHERE run_id='$($batch.run_id)'; SELECT COUNT(*) AS published_rates FROM warehouse.PublishedFxRate;"
    if ($LASTEXITCODE -ne 0) { throw 'Rate load verification query failed.' }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
