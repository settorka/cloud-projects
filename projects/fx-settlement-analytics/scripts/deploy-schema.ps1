param([Parameter(Mandatory = $true)][string]$schemaBase64)
$ErrorActionPreference = 'Stop'
$path = 'F:\fx\schema.sql'
[System.IO.File]::WriteAllBytes($path, [Convert]::FromBase64String($schemaBase64))
& sqlcmd -S localhost -E -b -f 65001 -i $path
if ($LASTEXITCODE -ne 0) { throw 'Schema deployment failed.' }
& sqlcmd -S localhost -E -b -d FxWarehouse -Q "SELECT name FROM sys.tables ORDER BY name; SELECT pair_code FROM warehouse.DimCurrencyPair ORDER BY pair_id;"
if ($LASTEXITCODE -ne 0) { throw 'Schema verification failed.' }
Write-Output 'FX_SQL_SUCCESS'
