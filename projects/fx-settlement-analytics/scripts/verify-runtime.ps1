$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$pythonVersion = & 'C:\Python312\python.exe' --version
if ($LASTEXITCODE -ne 0) { throw 'Python unavailable.' }
$configPath = 'C:\Program Files\Microsoft SQL Server\MSAS16.FXTABULAR\OLAP\Config\msmdsrv.ini'
[xml]$config = Get-Content $configPath
$mode = $config.SelectSingleNode('//DeploymentMode').InnerText
if ($mode -ne '2') { throw "Expected Tabular mode 2, got $mode" }
$token = Invoke-RestMethod -Headers @{Metadata = 'true'} -Uri 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F'
$uri = 'https://stfx36c63c6a50e8.blob.core.windows.net/fx-data/raw/ecb/73db21584dd46cebf5cd6df75ebb6de7afcdeebff52f54d5046ca8e459c0fbb3/manifest.json'
$manifest = Invoke-RestMethod -Uri $uri -Headers @{
    Authorization = "Bearer $($token.access_token)"
    'x-ms-version' = '2023-11-03'
}
[pscustomobject]@{
    Python = $pythonVersion
    AnalysisServicesMode = $mode
    SqlStatus = (Get-Service MSSQLSERVER).Status.ToString()
    SsisStatus = (Get-Service MsDtsServer160).Status.ToString()
    SsasStatus = (Get-Service 'MSOLAP$FXTABULAR').Status.ToString()
    BlobReadViaManagedIdentity = $true
    SourceSha256 = $manifest.sha256
    DataDiskPresent = (Test-Path 'F:\fx\data')
} | ConvertTo-Json
