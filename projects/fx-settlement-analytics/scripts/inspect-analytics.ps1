$ErrorActionPreference = 'Stop'
$service = Get-CimInstance Win32_Service -Filter "Name='MSOLAP`$FXTABULAR'"
Write-Output ('SSAS service identity: ' + $service.StartName)
& sqlcmd -S localhost -E -b -d FxWarehouse -Q "SELECT ORIGINAL_LOGIN() AS deploy_identity,IS_SRVROLEMEMBER('sysadmin') AS server_admin,SUSER_ID(N'NT SERVICE\MSOLAP`$FXTABULAR') AS ssas_login_id; SELECT name,type_desc FROM sys.database_principals WHERE name IN(N'NT SERVICE\MSOLAP`$FXTABULAR',N'NT AUTHORITY\SYSTEM');"
if ($LASTEXITCODE -ne 0) { throw 'Analytics access inspection failed.' }
foreach ($name in @('Microsoft.AnalysisServices.Tabular','Microsoft.AnalysisServices.AdomdClient')) {
    $assembly = Get-ChildItem (Join-Path 'C:\Windows\Microsoft.NET\assembly\GAC_MSIL' $name) -Filter ($name+'.dll') -Recurse | Select-Object -First 1
    if (-not $assembly) { throw "Missing client assembly: $name" }
    Write-Output ($name + ': ' + $assembly.FullName)
}
