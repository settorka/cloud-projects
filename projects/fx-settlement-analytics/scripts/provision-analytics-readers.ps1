# One-time development provisioning: two server authentication logins, no server roles.
# Each receives SELECT only on FxWarehouse.analytics; SYSTEM remains non-sysadmin.
$ErrorActionPreference = 'Stop'
$mutex = New-Object Threading.Mutex($false,'Global\FxPipeline')
if (-not $mutex.WaitOne(0)) { throw 'Pipeline is busy; refusing SQL restart.' }
$agentWasRunning = (Get-Service SQLSERVERAGENT).Status -eq 'Running'
try {
    $count = & sqlcmd -S localhost -E -b -h -1 -W -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM sys.databases WHERE database_id>4 AND name<>'FxWarehouse';"
    if ($LASTEXITCODE -ne 0 -or ($count | Out-String).Trim() -ne '0') { throw 'Unexpected user database; refusing development bootstrap.' }
    $running = & sqlcmd -S localhost -E -b -d FxWarehouse -h -1 -W -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM audit.PipelineRun WHERE status='running';"
    if ($LASTEXITCODE -ne 0 -or ($running | Out-String).Trim() -ne '0') { throw 'Active/incomplete pipeline run; refusing restart.' }
    Stop-Service SQLSERVERAGENT -ErrorAction SilentlyContinue
    Stop-Service MSSQLSERVER -Force
    try {
        & net.exe start MSSQLSERVER /mSQLCMD
        if ($LASTEXITCODE -ne 0) { throw 'Single-user startup failed.' }
        & sqlcmd -S localhost -E -b -Q "IF SUSER_ID(N'NT SERVICE\MSOLAP`$FXTABULAR') IS NULL CREATE LOGIN [NT SERVICE\MSOLAP`$FXTABULAR] FROM WINDOWS; IF SUSER_ID(N'NT AUTHORITY\LOCAL SERVICE') IS NULL CREATE LOGIN [NT AUTHORITY\LOCAL SERVICE] FROM WINDOWS;"
        if ($LASTEXITCODE -ne 0) { throw 'Service authentication login creation failed.' }
    } finally {
        Stop-Service MSSQLSERVER -Force -ErrorAction SilentlyContinue
        Start-Service MSSQLSERVER
        if ($agentWasRunning) { Start-Service SQLSERVERAGENT }
    }
    & sqlcmd -S localhost -E -b -d FxWarehouse -Q "IF USER_ID(N'NT SERVICE\MSOLAP`$FXTABULAR') IS NULL CREATE USER [NT SERVICE\MSOLAP`$FXTABULAR] FOR LOGIN [NT SERVICE\MSOLAP`$FXTABULAR]; IF USER_ID(N'NT AUTHORITY\LOCAL SERVICE') IS NULL CREATE USER [NT AUTHORITY\LOCAL SERVICE] FOR LOGIN [NT AUTHORITY\LOCAL SERVICE]; GRANT SELECT ON SCHEMA::analytics TO [NT SERVICE\MSOLAP`$FXTABULAR]; GRANT SELECT ON SCHEMA::analytics TO [NT AUTHORITY\LOCAL SERVICE]; IF IS_SRVROLEMEMBER('sysadmin')<>0 THROW 51000,'Deployment identity unexpectedly has sysadmin rights.',1; SELECT name,type_desc FROM sys.database_principals WHERE name IN(N'NT SERVICE\MSOLAP`$FXTABULAR',N'NT AUTHORITY\LOCAL SERVICE');"
    if ($LASTEXITCODE -ne 0) { throw 'Warehouse reader permissions failed.' }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
