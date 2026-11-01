param([switch]$MetadataOnly)
$ErrorActionPreference = 'Stop'
$mutex = New-Object Threading.Mutex($false,'Global\FxPipeline')
if (-not $mutex.WaitOne(0)) { throw 'Pipeline is busy; refusing a concurrent model refresh.' }
$statePath = 'F:\fx\app\.state\model.json'
New-Item -ItemType Directory -Force -Path (Split-Path $statePath) | Out-Null
@{status='refreshing';started_at=[DateTimeOffset]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content $statePath -Encoding UTF8
$server = $null
try {
    $path = 'C:\Program Files\Microsoft SQL Server\MSAS16.FXTABULAR\OLAP\Config\msmdsrv.ini'
    [xml]$config = Get-Content $path
    $port = $config.SelectSingleNode('//Port')
    if (-not $port) { throw 'SSAS port configuration not found.' }
    if ($port.InnerText -eq '0') {
        $port.InnerText = '2384'
        $config.Save($path)
        Restart-Service 'MSOLAP$FXTABULAR'
    } elseif ($port.InnerText -ne '2384') { throw 'Unexpected SSAS port; refusing to overwrite it.' }
    $assembly = Get-ChildItem 'C:\Windows\Microsoft.NET\assembly\GAC_MSIL\Microsoft.AnalysisServices.Tabular' -Filter Microsoft.AnalysisServices.Tabular.dll -Recurse | Select-Object -First 1
    Add-Type -Path $assembly.FullName
    $server = New-Object Microsoft.AnalysisServices.Tabular.Server
    $server.Connect('Data Source=localhost:2384;')
    $model = Get-Content 'F:\fx\app\ssas\Model.bim' -Raw | ConvertFrom-Json
    $create = @{createOrReplace=@{object=@{database='FxSettlement'};database=$model}}
    if ($MetadataOnly) {
        $command = $create | ConvertTo-Json -Depth 100 -Compress
    } else {
        $refresh = @{refresh=@{type='full';objects=@(@{database='FxSettlement'})}}
        $command = @{sequence=@{maxParallelism=1;operations=@($create,$refresh)}} | ConvertTo-Json -Depth 100 -Compress
    }
    $results = $server.Execute($command)
    $errors = @($results | ForEach-Object { $_.Messages } | Where-Object { $_ -is [Microsoft.AnalysisServices.XmlaError] })
    if ($errors.Count -gt 0) { throw (($errors | ForEach-Object Description) -join '; ') }
    $server.Refresh()
    $database = $server.Databases.FindByName('FxSettlement')
    if (-not $database) { throw 'SSAS model is missing after deployment.' }
    if (-not $MetadataOnly) {
        & 'F:\fx\app\scripts\test-ssas.ps1'
        @{status='verified';verified_at=[DateTimeOffset]::UtcNow.ToString('o');model_sha256=(Get-FileHash 'F:\fx\app\ssas\Model.bim' -Algorithm SHA256).Hash.ToLower()} | ConvertTo-Json | Set-Content $statePath -Encoding UTF8
    }
    [pscustomobject]@{
        Database=$database.Name
        Tables=$database.Model.Tables.Count
        Relationships=$database.Model.Relationships.Count
        MetadataOnly=[bool]$MetadataOnly
        ModelSha256=(Get-FileHash 'F:\fx\app\ssas\Model.bim' -Algorithm SHA256).Hash.ToLower()
    } | ConvertTo-Json
} catch {
    @{status='failed';failed_at=[DateTimeOffset]::UtcNow.ToString('o');error=$_.Exception.Message} | ConvertTo-Json | Set-Content $statePath -Encoding UTF8
    throw
} finally {
    if ($server) { $server.Disconnect() }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
