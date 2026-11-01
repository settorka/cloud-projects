$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$python = 'C:\Python312\python.exe'
if (-not (Test-Path $python)) {
    $installer = 'C:\fx\python-installer.exe'
    Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer
    $signature = Get-AuthenticodeSignature $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw 'Python installer signature verification failed.'
    }
    $result = Start-Process $installer -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 Include_test=0 TargetDir=C:\Python312' -Wait -PassThru
    if ($result.ExitCode -notin @(0, 3010)) { throw "Python installation failed: $($result.ExitCode)" }
}
& $python --version
if ($LASTEXITCODE -ne 0) { throw 'Python failed to start.' }
& icacls 'F:\fx\sql' /grant 'NT SERVICE\MSSQLSERVER:(OI)(CI)M' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'SQL data directory permissions failed.' }
# Verify current Windows identity can administer the local SQL development instance.
& sqlcmd -S localhost -E -b -Q "SELECT ORIGINAL_LOGIN() AS login_name, IS_SRVROLEMEMBER('sysadmin') AS is_admin, @@VERSION AS sql_version;"
if ($LASTEXITCODE -ne 0) { throw 'SQL integrated authentication failed.' }
# Discover client assemblies needed for model deployment and Python DAX queries.
Get-ChildItem 'C:\Windows\Microsoft.NET\assembly\GAC_MSIL' -Directory |
    Where-Object Name -Match 'AnalysisServices|DTSRuntime|ManagedDTS' | Select-Object Name
Get-ChildItem 'C:\Program Files\Microsoft SQL Server' -Filter msmdsrv.ini -Recurse -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Output $_.FullName; Select-String -Path $_.FullName -Pattern 'DeploymentMode' }
