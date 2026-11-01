# For the new, empty development VM only. Never use on a shared SQL instance.
param([Parameter(Mandatory = $true)][string]$schemaBase64)
$ErrorActionPreference = 'Stop'
$admin = & sqlcmd -S localhost -E -b -h -1 -W -Q "SET NOCOUNT ON; SELECT IS_SRVROLEMEMBER('sysadmin');"
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect SQL identity.' }
if (($admin | Out-String).Trim() -eq '1') { throw 'Use normal schema deployment with the existing administrator.' }
$existing = & sqlcmd -S localhost -E -b -h -1 -W -Q "SET NOCOUNT ON; SELECT CASE WHEN DB_ID('FxWarehouse') IS NULL THEN 0 ELSE 1 END;"
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect existing warehouse.' }
if (($existing | Out-String).Trim() -eq '1') {
    & sqlcmd -S localhost -E -b -d FxWarehouse -Q "IF IS_ROLEMEMBER('db_owner') <> 1 OR IS_SRVROLEMEMBER('sysadmin') <> 0 THROW 51000, 'Unexpected bootstrap permissions.', 1;"
    if ($LASTEXITCODE -ne 0) { throw 'Existing warehouse permissions differ; refusing further changes.' }
    Write-Output 'Warehouse already owned by deployment identity; no restart needed.'
    exit 0
}
$count = & sqlcmd -S localhost -E -b -h -1 -W -Q 'SET NOCOUNT ON; SELECT COUNT(*) FROM sys.databases WHERE database_id > 4;'
if ($LASTEXITCODE -ne 0 -or ($count | Out-String).Trim() -ne '0') {
    throw 'Refusing bootstrap restart: SQL is not a verified empty instance.'
}
$agentWasRunning = (Get-Service SQLSERVERAGENT).Status -eq 'Running'
Stop-Service SQLSERVERAGENT -ErrorAction SilentlyContinue
Stop-Service MSSQLSERVER -Force
try {
    & net.exe start MSSQLSERVER /mSQLCMD
    if ($LASTEXITCODE -ne 0) { throw 'Single-user startup failed.' }
    $schemaPath = 'F:\fx\bootstrap-schema.sql'
    [System.IO.File]::WriteAllBytes($schemaPath, [Convert]::FromBase64String($schemaBase64))
    & sqlcmd -S localhost -E -b -f 65001 -i $schemaPath
    if ($LASTEXITCODE -ne 0) { throw 'Initial warehouse schema failed.' }
    & sqlcmd -S localhost -E -b -d FxWarehouse -Q "IF IS_ROLEMEMBER('db_owner') <> 1 BEGIN IF USER_ID(N'NT AUTHORITY\SYSTEM') IS NULL CREATE USER [NT AUTHORITY\SYSTEM] FOR LOGIN [NT AUTHORITY\SYSTEM]; ALTER ROLE db_owner ADD MEMBER [NT AUTHORITY\SYSTEM]; END;"
    if ($LASTEXITCODE -ne 0) { throw 'Warehouse-scoped bootstrap permissions failed.' }
} finally {
    Stop-Service MSSQLSERVER -Force -ErrorAction SilentlyContinue
    Start-Service MSSQLSERVER
    if ($agentWasRunning) { Start-Service SQLSERVERAGENT }
}
& sqlcmd -S localhost -E -b -Q "SELECT ORIGINAL_LOGIN() AS login_name, IS_SRVROLEMEMBER('sysadmin') AS is_server_admin; USE FxWarehouse; SELECT IS_ROLEMEMBER('db_owner') AS is_warehouse_owner;"
if ($LASTEXITCODE -ne 0) { throw 'SQL bootstrap verification failed.' }
