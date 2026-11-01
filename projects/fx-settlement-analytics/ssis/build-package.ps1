param([ValidateSet('Rates','Settlements')][string]$Kind = 'Rates')
$ErrorActionPreference = 'Stop'
$assembly = Get-ChildItem 'C:\Windows\Microsoft.NET\assembly\GAC_MSIL\Microsoft.SqlServer.ManagedDTS' -Filter Microsoft.SqlServer.ManagedDTS.dll -Recurse | Select-Object -First 1
if (-not $assembly) { throw 'Installed SSIS runtime assembly not found.' }
Add-Type -Path $assembly.FullName
$package = New-Object Microsoft.SqlServer.Dts.Runtime.Package
$package.Name = 'Load' + $Kind
$package.Description = 'Load validated ' + $Kind + ' through warehouse stored procedures with explicit source provenance.'
$package.ProtectionLevel = [Microsoft.SqlServer.Dts.Runtime.DTSProtectionLevel]::DontSaveSensitive
$connection = $package.Connections.Add('OLEDB')
$connection.Name = 'FxWarehouse'
$connection.ConnectionString = 'Provider=MSOLEDBSQL;Data Source=localhost;Initial Catalog=FxWarehouse;Integrated Security=SSPI;Trust Server Certificate=True;'
$file = $package.Connections.Add('FILE')
$file.Name = $Kind + 'BatchSql'
$file.ConnectionString = if ($Kind -eq 'Rates') { 'F:\fx\data\current-rate-load.sql' } else { 'F:\fx\data\current-settlement-load.sql' }
$task = $package.Executables.Add('STOCK:SQLTask')
$task.Name = 'Validate and publish ' + $Kind
$sql = $task.InnerObject
$sql.Connection = $connection.ID
$sql.SQLStatementSourceType = [Enum]::Parse($sql.SQLStatementSourceType.GetType(), 'FileConnection')
$sql.SQLStatementSource = $file.ID
$sql.TimeOut = 120
$sql.BypassPrepare = $true
New-Item -ItemType Directory -Force -Path 'F:\fx\app\ssis' | Out-Null
$application = New-Object Microsoft.SqlServer.Dts.Runtime.Application
$application.SaveToXml(('F:\fx\app\ssis\Load' + $Kind + '.dtsx'), $package, $null)
Write-Output 'SSIS package saved.'
